"""Fact validation and cleaning helpers used before downstream analysis."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import replace
import re

from land_due_diligence_agent.deal_models import FactRecord, ProcessedDocument, SourceReference
from land_due_diligence_agent.models import (
    DocumentAnalysis,
    FactValidationLogEntry,
    FactValidationStats,
    StructuredFact,
)
from land_due_diligence_agent.utils.text import clip_text, normalize_text

_CONFIDENCE_RANK = {"low": 1, "medium": 2, "high": 3}
_FRAGMENT_START_TOKENS = {
    "a",
    "an",
    "and",
    "by",
    "for",
    "from",
    "in",
    "of",
    "on",
    "or",
    "the",
    "to",
    "with",
}
_CAMELCASE_ARTIFACT_RE = re.compile(r"\b[A-Za-z]{3,}[a-z][A-Z][a-z]{3,}\b")
_NON_ALNUM_NOISE_RE = re.compile(r"[^A-Za-z0-9\s\-\/&().,%$']")
_REPEATED_SYMBOL_RE = re.compile(r"[|_]{2,}|[^\w\s]{3,}")
_ZONING_ALLOWED_WORDS = {
    "agricultural",
    "agriculture",
    "commercial",
    "development",
    "industrial",
    "mixed",
    "planned",
    "residential",
    "specific",
    "use",
}
_ZONING_REJECT_TERMS = {
    "approval",
    "condition",
    "conditions",
    "development standards",
    "moisture",
    "provided",
    "seasonal",
    "setback",
    "setbacks",
    "sheet",
}
_JURISDICTION_CONTEXT_TERMS = ("city of", "county of", "jurisdiction")
_JURISDICTION_REJECT_TERMS = {
    "telephone",
    "fax",
    "email",
    "sheet",
    "setback",
    "lease",
}
_OWNER_CONTEXT_TERMS = (
    "fee owner",
    "owner",
    "preliminary title",
    "record owner",
    "title report",
    "vesting",
    "vested in",
)
_OWNER_DISCLAIMER_TERMS = {
    "assigns",
    "grantor",
    "grantee",
    "herein",
    "lease",
    "leases",
    "seller represents",
    "subject to",
    "successors",
    "tenant",
    "undersigned",
    "whereas",
}
_OWNER_ENTITY_TERMS = {
    "co",
    "company",
    "corp",
    "corporation",
    "holdings",
    "inc",
    "llc",
    "lp",
    "l.p",
    "partners",
    "properties",
    "trust",
    "ventures",
}
_UNIT_STRONG_CONTEXT = (
    "approved",
    "density",
    "development",
    "dwelling units",
    "entitled",
    "plan set",
    "project",
    "proposed",
    "site plan",
    "tentative map",
    "total units",
    "unit count",
)
_ACREAGE_STRONG_CONTEXT = (
    "acreage",
    "gross acreage",
    "net acreage",
    "parcel",
    "property",
    "site acreage",
    "site area",
    "survey",
)
_ANALYSIS_FRAGMENT_STARTS = _FRAGMENT_START_TOKENS | {"if", "that", "which"}


def clean_first_pass_facts(
    facts: list[FactRecord],
    processed_documents: list[ProcessedDocument],
) -> tuple[list[FactRecord], FactValidationStats, list[FactValidationLogEntry]]:
    """Validate, deduplicate, and confidence-filter scalar first-pass facts."""

    stats = FactValidationStats(total_candidates=len(facts))
    log: list[FactValidationLogEntry] = []
    document_map = {
        processed.document.relative_path.as_posix(): processed
        for processed in processed_documents
    }

    grouped: dict[tuple[str, str], list[FactRecord]] = defaultdict(list)
    for fact in facts:
        grouped[(fact.fact_type, fact.normalized_value)].append(fact)

    cleaned_facts: list[FactRecord] = []
    for key, grouped_facts in grouped.items():
        merged = _merge_fact_group(grouped_facts)
        if len(grouped_facts) > 1:
            duplicates_removed = len(grouped_facts) - 1
            stats.deduplicated_count += duplicates_removed
            log.append(
                _log_entry(
                    lane="first_pass",
                    action="deduplicated",
                    fact=merged,
                    reason=f"merged {duplicates_removed + 1} matching facts into one canonical entry",
                )
            )

        valid, reasons, weak_context = _validate_first_pass_fact(merged, document_map)
        if weak_context:
            stats.weak_context_count += 1
        if not valid:
            stats.filtered_count += 1
            log.append(
                _log_entry(
                    lane="first_pass",
                    action="filtered",
                    fact=merged,
                    reason="; ".join(reasons),
                )
            )
            continue

        support_count = len({source.relative_path for source in merged.sources})
        confidence_before = merged.confidence
        confidence_after = _adjust_first_pass_confidence(
            merged,
            support_count=support_count,
            weak_context=weak_context,
            document_map=document_map,
        )
        if confidence_after != confidence_before:
            stats.downgraded_count += 1
            log.append(
                _log_entry(
                    lane="first_pass",
                    action="downgraded",
                    fact=merged,
                    reason=_confidence_change_reason(merged, weak_context=weak_context, document_map=document_map),
                    confidence_before=confidence_before,
                    confidence_after=confidence_after,
                )
            )
        merged.confidence = confidence_after
        if confidence_after == "low":
            stats.filtered_count += 1
            stats.low_confidence_excluded_count += 1
            log.append(
                _log_entry(
                    lane="first_pass",
                    action="filtered",
                    fact=merged,
                    reason="low-confidence fact was excluded from downstream analysis",
                    confidence_before=confidence_before,
                    confidence_after=confidence_after,
                )
            )
            continue
        cleaned_facts.append(merged)

    cleaned_facts = _renumber_fact_ids(cleaned_facts)
    stats.kept_count = len(cleaned_facts)
    return cleaned_facts, stats, log


def clean_structured_facts(
    facts: list[StructuredFact],
    document_analyses: list[DocumentAnalysis],
) -> tuple[list[StructuredFact], FactValidationStats, list[FactValidationLogEntry]]:
    """Filter structured fact statements so only medium/high-confidence facts remain."""

    stats = FactValidationStats(total_candidates=len(facts))
    log: list[FactValidationLogEntry] = []
    analysis_by_title = {
        analysis.document.title: analysis
        for analysis in document_analyses
    }
    seen: set[tuple[str, str, str]] = set()
    cleaned: list[StructuredFact] = []

    for fact in facts:
        statement = normalize_text(fact.statement).replace("\n", " ").strip()
        payload = _structured_fact_payload(statement)
        reasons = _generic_text_issues(payload, expect_sentence=True)
        analysis = analysis_by_title.get(fact.document_name)
        weak_document = analysis is not None and analysis.confidence == "low"
        weak_context = analysis is not None and analysis.confidence == "medium" and len(payload.split()) < 7
        confidence_before = fact.confidence
        confidence_after = fact.confidence

        if weak_document:
            confidence_after = _downgrade_confidence(confidence_after)
        if weak_context:
            stats.weak_context_count += 1
            confidence_after = _downgrade_confidence(confidence_after)
        if _contains_non_alphanumeric_noise(payload):
            confidence_after = _downgrade_confidence(confidence_after)
            reasons.append("contains non-alphanumeric noise")

        if reasons:
            stats.filtered_count += 1
            if weak_document or confidence_after == "low":
                stats.low_confidence_excluded_count += 1
            if confidence_after != confidence_before:
                stats.downgraded_count += 1
            log.append(
                FactValidationLogEntry(
                    lane="synthesis",
                    action="filtered",
                    fact_type=fact.category,
                    value=payload,
                    normalized_value=payload.lower(),
                    reason="; ".join(dict.fromkeys(reasons)),
                    source_document=fact.document_name,
                    confidence_before=confidence_before,
                    confidence_after=confidence_after,
                )
            )
            continue

        if confidence_after != confidence_before:
            stats.downgraded_count += 1
            log.append(
                FactValidationLogEntry(
                    lane="synthesis",
                    action="downgraded",
                    fact_type=fact.category,
                    value=payload,
                    normalized_value=payload.lower(),
                    reason="source quality reduced confidence",
                    source_document=fact.document_name,
                    confidence_before=confidence_before,
                    confidence_after=confidence_after,
                )
            )
        if confidence_after == "low":
            stats.filtered_count += 1
            stats.low_confidence_excluded_count += 1
            log.append(
                FactValidationLogEntry(
                    lane="synthesis",
                    action="filtered",
                    fact_type=fact.category,
                    value=payload,
                    normalized_value=payload.lower(),
                    reason="low-confidence fact was excluded from downstream analysis",
                    source_document=fact.document_name,
                    confidence_before=confidence_before,
                    confidence_after=confidence_after,
                )
            )
            continue

        dedupe_key = (fact.category, payload.lower(), fact.document_name)
        if dedupe_key in seen:
            stats.deduplicated_count += 1
            log.append(
                FactValidationLogEntry(
                    lane="synthesis",
                    action="deduplicated",
                    fact_type=fact.category,
                    value=payload,
                    normalized_value=payload.lower(),
                    reason="duplicate structured fact was removed",
                    source_document=fact.document_name,
                    confidence_before=confidence_after,
                    confidence_after=confidence_after,
                )
            )
            continue
        seen.add(dedupe_key)
        cleaned.append(
            replace(
                fact,
                statement=_rebuild_structured_fact_statement(fact.document_name, payload),
                confidence=confidence_after,
            )
        )

    stats.kept_count = len(cleaned)
    return cleaned, stats, log


def is_analysis_sentence_usable(sentence: str) -> bool:
    """Return False for noisy sentence fragments that should not seed analysis."""

    cleaned = normalize_text(sentence).replace("\n", " ").strip()
    if not cleaned:
        return False
    if _contains_non_alphanumeric_noise(cleaned) or _contains_camelcase_artifact(cleaned):
        return False
    tokens = re.findall(r"[A-Za-z0-9%$'/-]+", cleaned)
    if len(tokens) < 5:
        return False
    if tokens[0].lower() in _ANALYSIS_FRAGMENT_STARTS and len(tokens) < 8:
        return False
    if len(tokens[0]) == 1 and tokens[0].islower():
        return False
    return True


def _validate_first_pass_fact(
    fact: FactRecord,
    document_map: dict[str, ProcessedDocument],
) -> tuple[bool, list[str], bool]:
    reasons = _generic_text_issues(fact.value)
    source_context = _source_context_text(fact, document_map)
    source_categories = _source_categories(fact, document_map)
    weak_context = False

    if fact.fact_type == "unit_count":
        valid, type_reasons, weak_context = _validate_unit_count(fact, source_context)
    elif fact.fact_type in {"gross_acreage", "net_acreage", "site_acreage"}:
        valid, type_reasons, weak_context = _validate_acreage(fact, source_context)
    elif fact.fact_type == "jurisdiction":
        valid, type_reasons, weak_context = _validate_jurisdiction(fact, source_context)
    elif fact.fact_type == "owner_name":
        valid, type_reasons, weak_context = _validate_owner_name(fact, source_context, source_categories)
    elif fact.fact_type == "zoning":
        valid, type_reasons, weak_context = _validate_zoning(fact, source_context)
    else:
        valid, type_reasons = True, []

    reasons.extend(type_reasons)
    return not reasons and valid, list(dict.fromkeys(reasons)), weak_context


def _validate_unit_count(fact: FactRecord, source_context: str) -> tuple[bool, list[str], bool]:
    count = _coerce_int(fact.normalized_value)
    if count is None:
        return False, ["unit count is not numeric"], False
    if count < 1 or count > 500:
        return False, ["unit count falls outside the expected 1-500 range"], False
    if 1900 <= count <= 2100:
        return False, ["unit count looks more like a year or sheet label than a project total"], False
    weak_context = not any(term in source_context for term in _UNIT_STRONG_CONTEXT)
    return True, [], weak_context


def _validate_acreage(fact: FactRecord, source_context: str) -> tuple[bool, list[str], bool]:
    acreage = _coerce_float(fact.normalized_value)
    if acreage is None:
        return False, ["acreage is not numeric"], False
    if acreage < 0.1 or acreage > 100:
        return False, ["acreage falls outside the expected 0.1-100 acre range"], False
    weak_context = not any(term in source_context for term in _ACREAGE_STRONG_CONTEXT)
    return True, [], weak_context


def _validate_jurisdiction(fact: FactRecord, source_context: str) -> tuple[bool, list[str], bool]:
    tokens = [token for token in re.split(r"[ .-]+", fact.value) if token]
    if not tokens or len(tokens) > 4:
        return False, ["jurisdiction does not resemble a city or county name"], False
    if any(token.lower() in _JURISDICTION_REJECT_TERMS for token in tokens):
        return False, ["jurisdiction includes malformed or concatenated text"], False
    if any(any(character.isdigit() for character in token) for token in tokens):
        return False, ["jurisdiction includes numeric noise"], False
    if not any(term in source_context for term in _JURISDICTION_CONTEXT_TERMS):
        return False, ["jurisdiction is not anchored to a city or county context"], True
    return True, [], False


def _validate_owner_name(
    fact: FactRecord,
    source_context: str,
    source_categories: set[str],
) -> tuple[bool, list[str], bool]:
    if source_categories.isdisjoint({"Title", "Vesting / Legal"}):
        return False, ["ownership reference is not sourced from a title report or vesting document"], False
    if not any(term in source_context for term in _OWNER_CONTEXT_TERMS):
        return False, ["ownership reference is not anchored to vesting or title language"], True
    if any(term in source_context for term in _OWNER_DISCLAIMER_TERMS):
        return False, ["ownership reference reads like legal boilerplate rather than an entity name"], False
    if not _looks_like_entity_name(fact.value):
        return False, ["ownership reference does not resemble a clearly identifiable entity name"], False
    return True, [], False


def _validate_zoning(fact: FactRecord, source_context: str) -> tuple[bool, list[str], bool]:
    lowered = fact.value.lower()
    if any(term in lowered for term in _ZONING_REJECT_TERMS):
        return False, ["zoning value reads like narrative text instead of a zoning label"], False
    if _contains_camelcase_artifact(fact.value):
        return False, ["zoning value contains concatenated OCR text"], False
    tokens = [token for token in re.split(r"[ /-]+", lowered) if token]
    code_like = bool(re.fullmatch(r"[A-Za-z]{1,4}(?:-?\d{0,3}[A-Za-z]?)?(?:/[A-Za-z0-9-]+)?", fact.value.strip()))
    words_like = 1 <= len(tokens) <= 4 and all(
        token in _ZONING_ALLOWED_WORDS or bool(re.fullmatch(r"[a-z]{1,4}\d{0,2}[a-z]?", token))
        for token in tokens
    )
    if not code_like and not words_like:
        return False, ["zoning value does not resemble a recognized zoning label"], False
    weak_context = not any(term in source_context for term in ("zoning", "zone", "district", "designation"))
    return True, [], weak_context


def _adjust_first_pass_confidence(
    fact: FactRecord,
    *,
    support_count: int,
    weak_context: bool,
    document_map: dict[str, ProcessedDocument],
) -> str:
    confidence = fact.confidence
    if _fact_has_weak_source(fact, document_map):
        confidence = _downgrade_confidence(confidence)
    if weak_context and support_count <= 1:
        confidence = _downgrade_confidence(confidence)
    if _contains_non_alphanumeric_noise(fact.value):
        confidence = _downgrade_confidence(confidence, steps=2)
    return confidence


def _confidence_change_reason(
    fact: FactRecord,
    *,
    weak_context: bool,
    document_map: dict[str, ProcessedDocument],
) -> str:
    reasons: list[str] = []
    if _fact_has_weak_source(fact, document_map):
        reasons.append("source document required OCR fallback or carried extraction warnings")
    if weak_context:
        reasons.append("fact appeared only in weak context")
    if _contains_non_alphanumeric_noise(fact.value):
        reasons.append("fact contains non-alphanumeric noise")
    return "; ".join(reasons) or "fact confidence was reduced"


def _merge_fact_group(grouped_facts: list[FactRecord]) -> FactRecord:
    ordered = sorted(
        grouped_facts,
        key=lambda fact: (
            -_CONFIDENCE_RANK.get(fact.confidence, 0),
            _fact_numeric_suffix(fact.fact_id),
        ),
    )
    primary = ordered[0]
    merged_sources = _merge_sources(grouped_facts)
    display_value = _canonical_display_value(primary.fact_type, primary.value, primary.normalized_value)
    return replace(
        primary,
        value=display_value,
        statement=_build_first_pass_statement(primary.fact_type, primary.label, display_value, primary.normalized_value),
        sources=merged_sources,
    )


def _renumber_fact_ids(facts: list[FactRecord]) -> list[FactRecord]:
    ordered = sorted(facts, key=lambda fact: _fact_numeric_suffix(fact.fact_id))
    return [replace(fact, fact_id=f"fact-{index:04d}") for index, fact in enumerate(ordered, start=1)]


def _merge_sources(grouped_facts: list[FactRecord]) -> list[SourceReference]:
    merged: list[SourceReference] = []
    seen: set[tuple[str, int | None, str | None, str]] = set()
    for fact in grouped_facts:
        for source in fact.sources:
            key = (source.relative_path, source.page_number, source.chunk_id, source.excerpt)
            if key in seen:
                continue
            seen.add(key)
            merged.append(source)
    return merged[:6]


def _canonical_display_value(fact_type: str, value: str, normalized_value: str) -> str:
    if fact_type in {"gross_acreage", "net_acreage", "site_acreage", "lot_count", "unit_count"}:
        return normalized_value
    if fact_type == "purchase_price":
        amount = _coerce_float(normalized_value)
        if amount is None:
            return value
        if amount.is_integer():
            return f"{int(amount):,}"
        return f"{amount:,.2f}"
    if fact_type == "jurisdiction":
        return " ".join(part if part.lower() == "of" else part[:1].upper() + part[1:] for part in value.split())
    if fact_type == "zoning" and " " not in value:
        return value.upper()
    return normalize_text(value).replace("\n", " ").strip()


def _build_first_pass_statement(fact_type: str, label: str, value: str, normalized_value: str) -> str:
    if fact_type == "purchase_price":
        return f"Purchase price referenced as ${value}."
    if fact_type in {"gross_acreage", "net_acreage", "site_acreage"}:
        return f"{label} referenced as {normalized_value} acres."
    if fact_type in {"lot_count", "unit_count"}:
        noun = "lots" if fact_type == "lot_count" else "units"
        return f"{label} referenced as {normalized_value} {noun}."
    if fact_type == "owner_name":
        return f"Owner or seller referenced as {value}."
    if fact_type == "jurisdiction":
        return f"Referenced jurisdiction: {value}."
    if fact_type == "zoning":
        return f"Zoning referenced as {value}."
    if fact_type == "apn":
        return f"APN identified as {value}."
    return f"{label} referenced as {value}."


def _source_context_text(fact: FactRecord, document_map: dict[str, ProcessedDocument]) -> str:
    parts: list[str] = []
    for source in fact.sources:
        parts.append(source.excerpt.lower())
        processed = document_map.get(source.relative_path)
        if processed is None:
            continue
        parts.append(processed.classification.category.lower())
        parts.append(processed.document.title.lower())
        parts.append(processed.document.relative_path.as_posix().lower())
    return " ".join(part for part in parts if part)


def _source_categories(fact: FactRecord, document_map: dict[str, ProcessedDocument]) -> set[str]:
    categories: set[str] = set()
    for source in fact.sources:
        processed = document_map.get(source.relative_path)
        if processed is not None:
            categories.add(processed.classification.category)
    return categories


def _fact_has_weak_source(fact: FactRecord, document_map: dict[str, ProcessedDocument]) -> bool:
    for source in fact.sources:
        processed = document_map.get(source.relative_path)
        if processed is None:
            continue
        if processed.document.warnings:
            return True
        if source.page_number is not None and source.page_number in processed.document.ocr_pages:
            return True
        if processed.document.ocr_pages and len(processed.document.ocr_pages) >= max(1, int(processed.document.metadata.get("page_count", 1) or 1)):
            return True
    return False


def _generic_text_issues(text: str, *, expect_sentence: bool = False) -> list[str]:
    cleaned = normalize_text(text).replace("\n", " ").strip()
    if not cleaned:
        return ["fact value is empty"]
    reasons: list[str] = []
    tokens = [token for token in re.findall(r"[A-Za-z0-9%$'/-]+", cleaned) if token]
    if _contains_camelcase_artifact(cleaned):
        reasons.append("contains concatenated OCR text")
    if _contains_non_alphanumeric_noise(cleaned):
        reasons.append("contains non-alphanumeric noise")
    if tokens and len(tokens[0]) == 1 and tokens[0].islower():
        reasons.append("starts like an incomplete fragment")
    if not expect_sentence and tokens and tokens[0].lower() in _FRAGMENT_START_TOKENS and len(tokens) <= 4:
        reasons.append("looks like a sentence fragment")
    if expect_sentence and tokens and tokens[0].lower() in _ANALYSIS_FRAGMENT_STARTS and len(tokens) < 8:
        reasons.append("looks like an incomplete sentence fragment")
    return reasons


def _structured_fact_payload(statement: str) -> str:
    _, separator, remainder = statement.partition(":")
    return remainder.strip() if separator else statement.strip()


def _rebuild_structured_fact_statement(document_name: str, payload: str) -> str:
    return f"{document_name}: {clip_text(payload, 240)}"


def _looks_like_entity_name(value: str) -> bool:
    tokens = [token for token in re.split(r"[ ,()&/-]+", value) if token]
    if len(tokens) < 2:
        return False
    lowered_tokens = {token.lower() for token in tokens}
    if lowered_tokens & _OWNER_DISCLAIMER_TERMS:
        return False
    if lowered_tokens & _OWNER_ENTITY_TERMS:
        return True
    capitalized_tokens = sum(token[:1].isupper() for token in tokens if token[:1].isalpha())
    return len(tokens) >= 3 and capitalized_tokens >= max(2, len(tokens) - 1)


def _contains_camelcase_artifact(text: str) -> bool:
    return _CAMELCASE_ARTIFACT_RE.search(text) is not None


def _contains_non_alphanumeric_noise(text: str) -> bool:
    compact = "".join(character for character in text if not character.isspace())
    if not compact:
        return False
    if _REPEATED_SYMBOL_RE.search(text):
        return True
    noise_count = len(_NON_ALNUM_NOISE_RE.findall(text))
    return (noise_count / len(compact)) > 0.08


def _downgrade_confidence(confidence: str, *, steps: int = 1) -> str:
    ordered = ["low", "medium", "high"]
    index = ordered.index(confidence) if confidence in ordered else 1
    return ordered[max(0, index - steps)]


def _fact_numeric_suffix(value: str) -> int:
    match = re.search(r"(\d+)$", value)
    return int(match.group(1)) if match is not None else 0


def _coerce_float(value: str) -> float | None:
    try:
        return float(value)
    except ValueError:
        return None


def _coerce_int(value: str) -> int | None:
    try:
        return int(float(value))
    except ValueError:
        return None


def _log_entry(
    *,
    lane: str,
    action: str,
    fact: FactRecord,
    reason: str,
    confidence_before: str = "",
    confidence_after: str = "",
) -> FactValidationLogEntry:
    source_document = fact.sources[0].relative_path if fact.sources else ""
    return FactValidationLogEntry(
        lane=lane,
        action=action,
        fact_type=fact.fact_type,
        value=fact.value,
        normalized_value=fact.normalized_value,
        reason=reason,
        source_document=source_document,
        confidence_before=confidence_before or fact.confidence,
        confidence_after=confidence_after or fact.confidence,
    )