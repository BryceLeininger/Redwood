"""Deterministic first-pass fact, conflict, and missing-item extraction."""

from __future__ import annotations

from collections import defaultdict
import re
from dataclasses import dataclass
from typing import Callable

from land_due_diligence_agent.deal_models import (
    ConflictRecord,
    FactRecord,
    IssueRegistry,
    MissingItem,
    ProcessedDocument,
    SellerQuestion,
    SourceReference,
)
from land_due_diligence_agent.utils.text import normalize_text


@dataclass(frozen=True, slots=True)
class _ScalarPattern:
    fact_type: str
    label: str
    category: str
    regexes: tuple[re.Pattern[str], ...]
    statement_template: str
    normalizer: Callable[[str], str]
    confidence: str = "high"
    uncertainty: str = ""
    conflict_eligible: bool = True


@dataclass(frozen=True, slots=True)
class _SignalPattern:
    fact_type: str
    label: str
    category: str
    regexes: tuple[re.Pattern[str], ...]
    statement: str
    confidence: str = "medium"


def _compile_patterns(*patterns: str) -> tuple[re.Pattern[str], ...]:
    return tuple(re.compile(pattern, re.IGNORECASE) for pattern in patterns)


def _normalize_simple(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip(" .;,:\"'").lower()


def _normalize_apn(value: str) -> str:
    return re.sub(r"[^a-z0-9-]", "", value.lower())


def _normalize_numeric(value: str) -> str:
    match = re.search(r"\d+(?:\.\d+)?", value)
    if match is None:
        return _normalize_simple(value)
    parsed = float(match.group(0))
    if parsed.is_integer():
        return str(int(parsed))
    return f"{parsed:.2f}".rstrip("0").rstrip(".")


def _normalize_money(value: str) -> str:
    digits = re.sub(r"[^0-9.]", "", value)
    if not digits:
        return _normalize_simple(value)
    parsed = float(digits)
    return f"{parsed:.2f}"


_SCALAR_PATTERNS: tuple[_ScalarPattern, ...] = (
    _ScalarPattern(
        fact_type="apn",
        label="APN",
        category="Title",
        regexes=_compile_patterns(
            r"\b(?:A\.?P\.?N\.?|APN|Assessor(?:'s)? Parcel Number(?:\(s\))?)\s*(?:No\.?|#|:)?\s*([A-Z0-9-]{6,})",
        ),
        statement_template="APN identified as {value}.",
        normalizer=_normalize_apn,
        uncertainty="Multiple APNs can be legitimate if the deal spans several parcels; confirm the controlling parcel set before relying on this alone.",
    ),
    _ScalarPattern(
        fact_type="gross_acreage",
        label="Gross Acreage",
        category="Map / Plat / Improvement Plans",
        regexes=_compile_patterns(
            r"\bgross(?:\s+site)?\s+(?:acreage|acres?)\s*(?:is|=|:)?\s*(\d+(?:\.\d+)?)\s*(?:acres?|ac\.?)",
        ),
        statement_template="Gross acreage referenced as {value} acres.",
        normalizer=_normalize_numeric,
        uncertainty="Gross and net acreage can differ legitimately; verify whether the cited figure is gross, net, or approximate.",
    ),
    _ScalarPattern(
        fact_type="net_acreage",
        label="Net Acreage",
        category="Map / Plat / Improvement Plans",
        regexes=_compile_patterns(
            r"\bnet\s+(?:acreage|acres?)\s*(?:is|=|:)?\s*(\d+(?:\.\d+)?)\s*(?:acres?|ac\.?)",
        ),
        statement_template="Net acreage referenced as {value} acres.",
        normalizer=_normalize_numeric,
        uncertainty="Gross and net acreage can differ legitimately; verify whether the cited figure is gross, net, or approximate.",
    ),
    _ScalarPattern(
        fact_type="site_acreage",
        label="Site Acreage",
        category="Map / Plat / Improvement Plans",
        regexes=_compile_patterns(
            r"\b(?:site|property|parcel)?\s*acreage\s*(?:is|=|:)?\s*(\d+(?:\.\d+)?)\s*(?:acres?|ac\.?)",
            r"\b(\d+(?:\.\d+)?)\s*acres?\b",
        ),
        statement_template="Site acreage referenced as {value} acres.",
        normalizer=_normalize_numeric,
        confidence="medium",
        uncertainty="Acreage references can reflect gross, net, or approximate figures; verify the controlling measurement.",
    ),
    _ScalarPattern(
        fact_type="zoning",
        label="Zoning",
        category="Entitlement / Planning / Conditions",
        regexes=_compile_patterns(
            r"\b(?:current\s+)?zoning(?:\s+designation|\s+district)?\s*(?:is|=|:)?\s*([A-Za-z0-9\-\/ ]{2,25}?)(?=[.;,\n]|$)",
            r"\bzone(?:\s+district)?\s*(?:is|=|:)?\s*([A-Za-z0-9\-\/ ]{2,25}?)(?=[.;,\n]|$)",
        ),
        statement_template="Zoning referenced as {value}.",
        normalizer=_normalize_simple,
        confidence="medium",
    ),
    _ScalarPattern(
        fact_type="jurisdiction",
        label="Jurisdiction",
        category="Entitlement / Planning / Conditions",
        regexes=_compile_patterns(
            r"\b(?:city of|county of)\s+([A-Z][A-Za-z .-]{2,40})",
            r"\bjurisdiction\s*(?:is|=|:)?\s*([A-Za-z .-]{2,40}?)(?=[.;,\n]|$)",
        ),
        statement_template="Referenced jurisdiction: {value}.",
        normalizer=_normalize_simple,
        confidence="medium",
    ),
    _ScalarPattern(
        fact_type="owner_name",
        label="Owner / Vesting Party",
        category="Vesting / Legal",
        regexes=_compile_patterns(
            r"\b(?:owner|vesting(?:\s+owner)?|fee owner)\s*(?:is|:)?\s*([A-Z][A-Za-z0-9 ,.()&-]{3,80}?)(?=[.;\n]|$)",
            r"\b(?:seller)\s*(?:is|:)?\s*([A-Z][A-Za-z0-9 ,.()&-]{3,80}?)(?=[.;\n]|$)",
        ),
        statement_template="Owner or seller referenced as {value}.",
        normalizer=_normalize_simple,
        confidence="medium",
        uncertainty="The contract seller and record vesting owner can differ legitimately; confirm the controlling entity for title and closing.",
    ),
    _ScalarPattern(
        fact_type="purchase_price",
        label="Purchase Price",
        category="Purchase / Sale / Contract",
        regexes=_compile_patterns(
            r"\b(?:purchase price|sale price|contract price)\s*(?:is|=|:)?\s*\$?\s*([0-9][0-9,]*(?:\.\d{2})?)",
        ),
        statement_template="Purchase price referenced as ${value}.",
        normalizer=_normalize_money,
    ),
    _ScalarPattern(
        fact_type="lot_count",
        label="Lot Count",
        category="Map / Plat / Improvement Plans",
        regexes=_compile_patterns(
            r"\b(\d{1,4})\s+(?:single[- ]family\s+)?lots?\b",
        ),
        statement_template="Lot count referenced as {value} lots.",
        normalizer=_normalize_numeric,
        confidence="medium",
        uncertainty="Lot counts can differ between draft plans and approved plans; confirm which plan set controls.",
    ),
    _ScalarPattern(
        fact_type="unit_count",
        label="Unit Count",
        category="Financial / underwriting support",
        regexes=_compile_patterns(
            r"\b(\d{1,5})\s+(?:dwelling\s+)?units?\b",
        ),
        statement_template="Unit count referenced as {value} units.",
        normalizer=_normalize_numeric,
        confidence="medium",
        uncertainty="Unit counts can differ between conceptual, submitted, and approved plans; confirm the current governing count.",
    ),
)


_SIGNAL_PATTERNS: tuple[_SignalPattern, ...] = (
    _SignalPattern(
        fact_type="signal_environmental",
        label="Environmental Signal",
        category="Environmental",
        regexes=_compile_patterns(
            r"\brecognized environmental condition\b",
            r"\bwetlands?\b",
            r"\bfloodplain\b",
            r"\bremediation\b",
        ),
        statement="Environmental material references a site constraint or follow-up item.",
    ),
    _SignalPattern(
        fact_type="signal_geotech",
        label="Geotech Signal",
        category="Geotech / Soils",
        regexes=_compile_patterns(
            r"\bliquefaction\b",
            r"\bexpansive soils?\b",
            r"\bsettlement\b",
        ),
        statement="Geotechnical material references a soil or seismic risk item.",
    ),
    _SignalPattern(
        fact_type="signal_title",
        label="Title Signal",
        category="Title",
        regexes=_compile_patterns(
            r"\b(?:title )?exception\b",
            r"\beasement\b",
            r"\bencroachment\b",
        ),
        statement="Title or legal material references an exception, easement, or encroachment concern.",
    ),
    _SignalPattern(
        fact_type="signal_utilities",
        label="Utilities Signal",
        category="Utilities",
        regexes=_compile_patterns(
            r"\bwill[- ]serve\b",
            r"\butility capacity\b",
            r"\bwater capacity\b",
            r"\bsewer capacity\b",
        ),
        statement="Utilities material references service availability or capacity status.",
    ),
    _SignalPattern(
        fact_type="signal_entitlement",
        label="Entitlement Signal",
        category="Entitlement / Planning / Conditions",
        regexes=_compile_patterns(
            r"\bconditions? of approval\b",
            r"\brezoning?\b",
            r"\bannexation\b",
            r"\btentative map\b",
            r"\bplanning commission\b",
        ),
        statement="Entitlement material references approvals, conditions, or discretionary actions.",
    ),
)

_ZONING_NOISE_VALUES = {
    "setback",
    "setbacks",
    "development standard",
    "development standards",
    "base zoning",
    "designation",
    "provided",
}
_JURISDICTION_NOISE_TERMS = (
    "setback",
    "development standard",
    "fee",
    "lease",
)
_OWNER_NOISE_TERMS = (
    "setback",
    "development standard",
    "tentative map",
    "site plan",
    "grading",
    "streetscape",
    "colors",
    "materials",
    "lease",
    "leases",
    "ship fees",
)
_OWNER_ENTITY_TERMS = (
    "llc",
    "inc",
    "lp",
    "l.p",
    "trust",
    "company",
    "co",
    "corp",
    "corporation",
    "holdings",
    "partners",
    "properties",
    "ventures",
)
_UNIT_TOTAL_CONTEXT = (
    "total units",
    "proposed units",
    "approved units",
    "residential units",
    "multifamily",
    "apartment",
    "development",
)
_UNIT_SUBCOMPONENT_TERMS = (
    "building",
    "phase",
    "pod",
    "floor",
    "per acre",
    "du/ac",
    "garage",
    "parking",
    "sheet",
    "elevation",
    "typ",
)
_LOT_TOTAL_CONTEXT = (
    "total lots",
    "proposed lots",
    "approved lots",
    "lot count",
    "tentative map",
    "subdivision",
)
_LOT_SUBCOMPONENT_TERMS = (
    "phase",
    "pod",
    "sheet",
    "detail",
    "typ",
)


_REQUIRED_CATEGORIES: tuple[tuple[str, str, str], ...] = (
    (
        "Purchase / Sale / Contract",
        "Current purchase contract / LOI package",
        "Please provide the current purchase agreement or LOI, plus all amendments that control the deal terms.",
    ),
    (
        "Title",
        "Current title package",
        "Please provide the current preliminary title report or commitment, including listed exceptions.",
    ),
    (
        "Environmental",
        "Environmental support",
        "Please provide the current environmental reports and any follow-up correspondence or closure documentation.",
    ),
    (
        "Geotech / Soils",
        "Geotechnical or soils support",
        "Please provide the current geotechnical or soils report relied on for the site.",
    ),
    (
        "Utilities",
        "Utility availability support",
        "Please provide current utility availability, will-serve, or capacity support for the site.",
    ),
    (
        "Entitlement / Planning / Conditions",
        "Planning or entitlement support",
        "Please provide the current zoning, entitlement approvals, and conditions of approval for the project.",
    ),
    (
        "Map / Plat / Improvement Plans",
        "Map, plat, or plan support",
        "Please provide the controlling map, plat, survey, or improvement plan set for the site.",
    ),
)


def build_issue_registry(
    processed_documents: list[ProcessedDocument],
    manifest_entries: list,
) -> IssueRegistry:
    """Build a deterministic issue registry from extracted documents."""

    facts = _extract_facts(processed_documents)
    conflicts = _detect_conflicts(facts)
    missing_items = _build_missing_items(processed_documents, manifest_entries, facts)
    seller_questions = _build_seller_questions(conflicts, missing_items)

    return IssueRegistry(
        facts=facts,
        conflicts=conflicts,
        missing_items=missing_items,
        seller_questions=seller_questions,
    )


def _extract_facts(processed_documents: list[ProcessedDocument]) -> list[FactRecord]:
    facts: list[FactRecord] = []
    seen: set[tuple[str, str, str, str | None]] = set()
    signal_seen: set[tuple[str, str]] = set()
    fact_index = 1
    per_document_scalar_counts: dict[tuple[str, str], int] = {}

    for processed in processed_documents:
        relative_path = processed.document.relative_path.as_posix()
        for chunk in processed.document.chunks:
            chunk_text = normalize_text(chunk.text)
            if not chunk_text:
                continue

            for pattern in _SCALAR_PATTERNS:
                doc_pattern_key = (relative_path, pattern.fact_type)
                current_count = per_document_scalar_counts.get(doc_pattern_key, 0)
                if current_count >= 3:
                    continue

                for regex in pattern.regexes:
                    for match in regex.finditer(chunk_text):
                        current_count = per_document_scalar_counts.get(doc_pattern_key, 0)
                        if current_count >= 3:
                            break

                        raw_value = _clean_display_value(match.group(1))
                        normalized_value = pattern.normalizer(raw_value)
                        if not normalized_value:
                            continue
                        excerpt = _build_excerpt(chunk_text, match.start(), match.end())
                        if not _is_valid_scalar_match(
                            fact_type=pattern.fact_type,
                            raw_value=raw_value,
                            normalized_value=normalized_value,
                            excerpt=excerpt,
                        ):
                            continue

                        fact_key = (pattern.fact_type, normalized_value, relative_path, chunk.chunk_id)
                        if fact_key in seen:
                            continue
                        seen.add(fact_key)
                        per_document_scalar_counts[doc_pattern_key] = current_count + 1

                        facts.append(
                            FactRecord(
                                fact_id=f"fact-{fact_index:04d}",
                                fact_type=pattern.fact_type,
                                label=pattern.label,
                                value=raw_value,
                                normalized_value=normalized_value,
                                statement=pattern.statement_template.format(value=raw_value),
                                category=pattern.category,
                                confidence=pattern.confidence,
                                uncertainty=pattern.uncertainty,
                                sources=[
                                    SourceReference(
                                        relative_path=relative_path,
                                        page_number=chunk.page_number,
                                        chunk_id=chunk.chunk_id,
                                        excerpt=excerpt,
                                    )
                                ],
                            )
                        )
                        fact_index += 1

            for pattern in _SIGNAL_PATTERNS:
                signal_key = (pattern.fact_type, relative_path)
                if signal_key in signal_seen:
                    continue
                for regex in pattern.regexes:
                    match = regex.search(chunk_text)
                    if match is None:
                        continue
                    signal_seen.add(signal_key)
                    matched_text = _clean_display_value(match.group(0))
                    facts.append(
                        FactRecord(
                            fact_id=f"fact-{fact_index:04d}",
                            fact_type=pattern.fact_type,
                            label=pattern.label,
                            value=matched_text,
                            normalized_value=_normalize_simple(matched_text),
                            statement=pattern.statement,
                            category=pattern.category,
                            confidence=pattern.confidence,
                            sources=[
                                SourceReference(
                                    relative_path=relative_path,
                                    page_number=chunk.page_number,
                                    chunk_id=chunk.chunk_id,
                                    excerpt=_build_excerpt(chunk_text, match.start(), match.end()),
                                )
                            ],
                        )
                    )
                    fact_index += 1
                    break

    return _assign_fact_confidence(facts, processed_documents)


def _detect_conflicts(facts: list[FactRecord]) -> list[ConflictRecord]:
    grouped: dict[str, list[FactRecord]] = {}
    eligible_types = {pattern.fact_type for pattern in _SCALAR_PATTERNS if pattern.conflict_eligible}
    for fact in facts:
        if fact.fact_type not in eligible_types or fact.confidence == "low":
            continue
        grouped.setdefault(fact.fact_type, []).append(fact)

    conflicts: list[ConflictRecord] = []
    conflict_index = 1

    for pattern in _SCALAR_PATTERNS:
        group = grouped.get(pattern.fact_type, [])
        if not group:
            continue

        representative_facts = _representative_conflict_facts(pattern.fact_type, group)
        distinct_values = [fact.value for fact in representative_facts]

        if len(distinct_values) <= 1:
            continue

        description = _build_conflict_description(pattern.fact_type, representative_facts)
        if not description:
            continue

        conflict_sources: list[SourceReference] = []
        seen_sources: set[tuple[str, int | None, str | None, str]] = set()
        for fact in representative_facts:
            for source in fact.sources:
                source_key = (
                    source.relative_path,
                    source.page_number,
                    source.chunk_id,
                    source.excerpt,
                )
                if source_key in seen_sources:
                    continue
                seen_sources.add(source_key)
                conflict_sources.append(source)
        conflict_sources = conflict_sources[:6]

        conflicts.append(
            ConflictRecord(
                conflict_id=f"conflict-{conflict_index:04d}",
                fact_type=pattern.fact_type,
                label=pattern.label,
                description=description,
                values=distinct_values,
                sources=conflict_sources,
                uncertainty=_build_conflict_uncertainty(pattern.fact_type, representative_facts),
            )
        )
        conflict_index += 1

    return conflicts


def _build_missing_items(
    processed_documents: list[ProcessedDocument],
    manifest_entries: list,
    facts: list[FactRecord],
) -> list[MissingItem]:
    success_categories = {
        processed.classification.category
        for processed in processed_documents
        if processed.classification.category != "Miscellaneous"
    }
    observed_categories = {
        entry.category
        for entry in manifest_entries
        if entry.category != "Miscellaneous"
    }
    fact_types = {fact.fact_type for fact in facts}

    missing_items: list[MissingItem] = []
    item_index = 1

    for category, label, request in _REQUIRED_CATEGORIES:
        if category in success_categories:
            continue

        if category in observed_categories:
            reason = f"Files were tagged as {category}, but no usable extracted text was produced from that lane."
        else:
            reason = f"No document was classified as {category} in the provided package."

        missing_items.append(
            MissingItem(
                item_id=f"missing-{item_index:04d}",
                label=label,
                category=category,
                reason=reason,
                suggested_request=request,
                confidence="high",
            )
        )
        item_index += 1

    required_fact_groups = (
        (
            ("apn",),
            "Current APN set",
            "Title",
            "No APN value was extracted from the provided documents.",
            "Please confirm the current APN list used for diligence, underwriting, and closing.",
        ),
        (
            ("gross_acreage", "net_acreage", "site_acreage"),
            "Site acreage",
            "Map / Plat / Improvement Plans",
            "No acreage value was extracted from the provided documents.",
            "Please confirm the controlling gross and net acreage for the site.",
        ),
        (
            ("zoning",),
            "Current zoning",
            "Entitlement / Planning / Conditions",
            "No zoning designation was extracted from the provided documents.",
            "Please confirm the current zoning designation and approval path for the project.",
        ),
        (
            ("owner_name",),
            "Owner / vesting party",
            "Vesting / Legal",
            "No owner, seller, or vesting party name was extracted from the provided documents.",
            "Please identify the current vesting owner and the contract seller for the transaction.",
        ),
    )

    for fact_group, label, category, reason, request in required_fact_groups:
        if any(fact_type in fact_types for fact_type in fact_group):
            continue
        missing_items.append(
            MissingItem(
                item_id=f"missing-{item_index:04d}",
                label=label,
                category=category,
                reason=reason,
                suggested_request=request,
                confidence="medium",
            )
        )
        item_index += 1

    return missing_items


def _build_seller_questions(
    conflicts: list[ConflictRecord],
    missing_items: list[MissingItem],
) -> list[SellerQuestion]:
    questions: list[SellerQuestion] = []
    seen_questions: set[str] = set()
    question_index = 1

    for conflict in conflicts:
        question = _conflict_question(conflict)
        if question in seen_questions:
            continue
        seen_questions.add(question)
        questions.append(
            SellerQuestion(
                question_id=f"question-{question_index:04d}",
                question=question,
                reason=conflict.description,
                related_item_ids=[conflict.conflict_id],
                sources=conflict.sources,
            )
        )
        question_index += 1

    for missing_item in missing_items:
        question = missing_item.suggested_request
        if question in seen_questions:
            continue
        seen_questions.add(question)
        questions.append(
            SellerQuestion(
                question_id=f"question-{question_index:04d}",
                question=question,
                reason=missing_item.reason,
                related_item_ids=[missing_item.item_id],
            )
        )
        question_index += 1

    return questions


def _conflict_question(conflict: ConflictRecord) -> str:
    questions = {
        "apn": "Please provide the controlling APN schedule, identify every parcel included in the deal, and confirm which title or survey set governs.",
        "gross_acreage": "Please confirm the controlling gross acreage, identify the map or survey that governs, and explain any parcel exclusions or dedications.",
        "net_acreage": "Please confirm the controlling net acreage, identify the map or survey that governs, and explain any parcel exclusions or dedications.",
        "site_acreage": "Please confirm the controlling gross and net acreage, identify the governing map or survey, and explain any excluded acreage.",
        "zoning": "Please confirm the current zoning designation, any proposed zoning or land-use designation, and the document that controls underwriting.",
        "jurisdiction": "Please confirm the governing city or county jurisdiction and the approval path that applies to the current plan.",
        "owner_name": "Please confirm the vesting owner, the contract seller, and which entity has authority to close this transaction.",
        "purchase_price": "Please provide the latest purchase agreement or amendment set and confirm the current purchase price being underwritten.",
        "lot_count": "Please confirm the controlling lot count, identify the governing map or plan set, and explain any phase or revision differences.",
        "unit_count": "Please confirm the controlling unit count, identify the governing plan set, and explain any plan-version or subcomponent differences.",
    }
    return questions.get(conflict.fact_type, "Please reconcile the conflicting information cited in the package and identify the controlling source document.")


def _is_valid_scalar_match(
    *,
    fact_type: str,
    raw_value: str,
    normalized_value: str,
    excerpt: str,
) -> bool:
    excerpt_lower = excerpt.lower()

    if fact_type == "zoning":
        if normalized_value in _ZONING_NOISE_VALUES:
            return False
        if any(term in normalized_value for term in _ZONING_NOISE_VALUES):
            return False
        return bool(re.search(r"[a-z]", raw_value, re.IGNORECASE))

    if fact_type == "jurisdiction":
        return (
            not any(term in normalized_value for term in _JURISDICTION_NOISE_TERMS)
            and 1 <= len(raw_value.split()) <= 4
            and not any(character.isdigit() for character in raw_value)
        )

    if fact_type == "owner_name":
        return _looks_like_entity_name(raw_value, normalized_value)

    if fact_type == "purchase_price":
        amount = _coerce_float(normalized_value)
        return amount is not None and amount >= 100000

    if fact_type in {"gross_acreage", "net_acreage", "site_acreage"}:
        acreage = _coerce_float(normalized_value)
        if acreage is None or acreage <= 0:
            return False
        if fact_type == "site_acreage" and acreage < 0.25:
            return any(term in excerpt_lower for term in ("site acreage", "property acreage", "parcel acreage", "project acreage"))
        return True

    if fact_type == "lot_count":
        count = _coerce_int(normalized_value)
        if count is None or count <= 0:
            return False
        if count < 10 and not _has_any_term(excerpt_lower, _LOT_TOTAL_CONTEXT):
            return False
        return True

    if fact_type == "unit_count":
        count = _coerce_int(normalized_value)
        if count is None or count <= 0:
            return False
        if "per acre" in excerpt_lower or "du/ac" in excerpt_lower:
            return False
        if count < 10 and not _has_any_term(excerpt_lower, _UNIT_TOTAL_CONTEXT):
            return False
        if count < 20 and _has_any_term(excerpt_lower, _UNIT_SUBCOMPONENT_TERMS) and not _has_any_term(excerpt_lower, _UNIT_TOTAL_CONTEXT):
            return False
        return True

    return True


def _looks_like_entity_name(raw_value: str, normalized_value: str) -> bool:
    tokens = [token for token in re.split(r"[ ,()&/-]+", raw_value) if token]
    if len(tokens) < 2:
        return False
    if any(term in normalized_value for term in _OWNER_NOISE_TERMS):
        return False
    if any(term in normalized_value for term in _OWNER_ENTITY_TERMS):
        return True
    capitalized_tokens = sum(token[:1].isupper() for token in tokens if token[:1].isalpha())
    return len(tokens) >= 3 and capitalized_tokens >= max(2, len(tokens) - 1)


def _assign_fact_confidence(
    facts: list[FactRecord],
    processed_documents: list[ProcessedDocument],
) -> list[FactRecord]:
    document_map = {
        processed.document.relative_path.as_posix(): processed.document
        for processed in processed_documents
    }
    support_by_value: dict[tuple[str, str], set[str]] = defaultdict(set)

    for fact in facts:
        for source in fact.sources:
            support_by_value[(fact.fact_type, fact.normalized_value)].add(source.relative_path)

    for fact in facts:
        support_count = len(support_by_value[(fact.fact_type, fact.normalized_value)])
        weak_support = any(
            (document_map.get(source.relative_path) is not None)
            and (
                document_map[source.relative_path].ocr_pages
                or document_map[source.relative_path].warnings
            )
            for source in fact.sources
        )
        if weak_support and support_count <= 1:
            fact.confidence = "low"
        elif support_count >= 2 and not weak_support:
            fact.confidence = "high"
        else:
            fact.confidence = "medium"

    return facts


def _representative_conflict_facts(
    fact_type: str,
    facts: list[FactRecord],
) -> list[FactRecord]:
    filtered = [fact for fact in facts if fact.confidence != "low"]
    if fact_type in {"unit_count", "lot_count"}:
        filtered = _prune_count_conflict_noise(fact_type, filtered)

    deduped: dict[str, FactRecord] = {}
    for fact in sorted(filtered, key=_conflict_sort_key):
        deduped.setdefault(fact.normalized_value, fact)
    return list(deduped.values())


def _prune_count_conflict_noise(
    fact_type: str,
    facts: list[FactRecord],
) -> list[FactRecord]:
    non_subcomponent = [fact for fact in facts if not _is_subcomponent_count(fact_type, fact)]
    if non_subcomponent:
        facts = non_subcomponent

    numbers = [_coerce_int(fact.normalized_value) for fact in facts]
    numbers = [number for number in numbers if number is not None]
    if len(set(numbers)) < 3 or not numbers:
        return facts

    max_count = max(numbers)
    threshold = max(20 if fact_type == "unit_count" else 10, int(max_count * 0.25))
    contextual_floor = max(10 if fact_type == "unit_count" else 5, threshold // 2)
    total_context = _UNIT_TOTAL_CONTEXT if fact_type == "unit_count" else _LOT_TOTAL_CONTEXT
    filtered = [
        fact
        for fact in facts
        if (
            (_coerce_int(fact.normalized_value) or 0) >= threshold
            or (
                (_coerce_int(fact.normalized_value) or 0) >= contextual_floor
                and _has_any_term(" ".join(source.excerpt.lower() for source in fact.sources), total_context)
            )
        )
    ]
    return filtered if len({fact.normalized_value for fact in filtered}) >= 2 else facts


def _is_subcomponent_count(fact_type: str, fact: FactRecord) -> bool:
    count = _coerce_int(fact.normalized_value)
    if count is None:
        return False
    excerpt = " ".join(source.excerpt.lower() for source in fact.sources)
    if fact_type == "unit_count":
        return count < 20 and _has_any_term(excerpt, _UNIT_SUBCOMPONENT_TERMS) and not _has_any_term(excerpt, _UNIT_TOTAL_CONTEXT)
    return count < 10 and _has_any_term(excerpt, _LOT_SUBCOMPONENT_TERMS) and not _has_any_term(excerpt, _LOT_TOTAL_CONTEXT)


def _build_conflict_description(
    fact_type: str,
    facts: list[FactRecord],
) -> str:
    numbers = [_coerce_int(fact.normalized_value) for fact in facts]
    numeric_values = [number for number in numbers if number is not None]

    if fact_type == "unit_count" and numeric_values:
        return (
            f"Unit count references range from {min(numeric_values)} to {max(numeric_values)} across the package; "
            "lower figures likely reflect subplans, building-level counts, or earlier plan sets rather than the full project."
        )
    if fact_type == "lot_count" and numeric_values:
        return (
            f"Lot count references range from {min(numeric_values)} to {max(numeric_values)} across the package; "
            "the difference likely reflects phase counts, draft map revisions, or plan-set changes rather than one controlling total."
        )
    if fact_type in {"gross_acreage", "net_acreage", "site_acreage"} and numeric_values:
        return (
            f"{_fact_label_for_type(fact_type)} references range from {min(numeric_values)} to {max(numeric_values)} acres; "
            "the difference likely reflects gross versus net acreage, parcel carve-outs, or plan-set rounding."
        )
    if fact_type == "purchase_price":
        return "Purchase price references differ across the package; this likely reflects different contract versions, amendments, or legacy deal terms."
    if fact_type == "zoning":
        return "Zoning references differ across the package; the mix likely reflects current zoning, planned land-use terminology, or interim planning shorthand rather than one controlling designation."
    if fact_type == "jurisdiction":
        return "Jurisdiction references differ across the package; this likely reflects boundary, annexation, or approval-path confusion that still needs to be reconciled."
    if fact_type == "owner_name":
        return "Ownership references differ across the package; this likely reflects a mismatch between vesting owner, contract seller, or affiliated entities involved in the transaction."
    if fact_type == "apn":
        return "APN references differ across the package; this likely reflects multiple parcels, partial parcel references, or an incomplete title schedule."
    return "The extracted package contains conflicting references that still need to be reconciled to one controlling source."


def _build_conflict_uncertainty(
    fact_type: str,
    facts: list[FactRecord],
) -> str:
    del facts
    why_it_matters = {
        "apn": "Title, acreage, and closing assumptions should only rely on the confirmed parcel schedule.",
        "gross_acreage": "Land basis, density, and engineering assumptions depend on the controlling acreage measure.",
        "net_acreage": "Yield and entitlement assumptions depend on the controlling net acreage.",
        "site_acreage": "Yield, density, and basis assumptions depend on the controlling gross and net acreage.",
        "zoning": "Entitlement path, density, and product assumptions depend on the controlling zoning designation.",
        "jurisdiction": "Schedule, entitlement, and fee assumptions depend on the correct governing jurisdiction.",
        "owner_name": "Closing authority and title assumptions depend on identifying the correct seller and vesting owner.",
        "purchase_price": "Land basis and contract economics should rely only on the current governing amendment set.",
        "lot_count": "Yield and underwriting should use only the controlling lot program.",
        "unit_count": "Yield and land basis should use only the controlling unit program.",
    }
    return why_it_matters.get(fact_type, "The conflicting references still need one controlling source before the deal can be underwritten cleanly.")


def _conflict_sort_key(fact: FactRecord) -> tuple[int, float, str]:
    numeric_value = _coerce_float(fact.normalized_value)
    if numeric_value is not None:
        return (0, numeric_value, fact.value.lower())
    return (1, 0.0, fact.value.lower())


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


def _fact_label_for_type(fact_type: str) -> str:
    labels = {
        "gross_acreage": "Gross acreage",
        "net_acreage": "Net acreage",
        "site_acreage": "Site acreage",
    }
    return labels.get(fact_type, fact_type.replace("_", " ").title())


def _has_any_term(text: str, terms: tuple[str, ...]) -> bool:
    return any(term in text for term in terms)


def _clean_display_value(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip(" .;,:\"'")


def _build_excerpt(text: str, start: int, end: int, *, max_chars: int = 180) -> str:
    left = max(0, start - 70)
    right = min(len(text), end + 70)
    excerpt = normalize_text(text[left:right])
    if len(excerpt) <= max_chars:
        return excerpt
    return excerpt[: max_chars - 3].rstrip() + "..."