"""Deterministic document and deal-level analysis heuristics."""

from __future__ import annotations

import re
from collections import defaultdict
from functools import lru_cache

from land_due_diligence_agent.analysis.risk_rules import (
    CATEGORY_RULES,
    DOCUMENT_GAP_HINTS,
    EXPECTED_DILIGENCE_ITEMS,
    EXPECTED_DILIGENCE_PATH_HINTS,
)
from land_due_diligence_agent.models import DocumentAnalysis, DocumentRecord, ReadingRecommendation, RiskFinding
from land_due_diligence_agent.utils.text import clip_text, extractive_summary, split_sentences, unique_preserve_order


_SEVERITY_RANK = {"low": 1, "medium": 2, "high": 3}
_CONFIDENCE_RANK = {"low": 1, "medium": 2, "high": 3}
_PAGE_MARKER_RE = re.compile(r"\[page\s+\d+\]\s*", re.IGNORECASE)
_NOISE_PHRASES = (
    "cover sheet",
    "sheet title",
    "vicinity map",
    "table of contents",
    "not to scale",
)
_QUESTION_BY_CATEGORY = {rule.category: rule.seller_question for rule in CATEGORY_RULES}
_RULE_BY_CATEGORY = {rule.category: rule for rule in CATEGORY_RULES}


def analyze_document(document: DocumentRecord) -> DocumentAnalysis:
    """Produce deterministic document-level diligence findings."""

    focus_areas = _derive_focus_areas(document)
    confidence, confidence_reason = _calculate_document_confidence(document)
    sentences = split_sentences(document.normalized_text)
    lower_sentences = [sentence.lower() for sentence in sentences]
    text_lower = document.normalized_text.lower()

    risks: list[RiskFinding] = []
    seller_questions: list[str] = []

    for rule in CATEGORY_RULES:
        in_focus_area = rule.category in focus_areas
        evidence = _collect_evidence(
            sentences=sentences,
            lower_sentences=lower_sentences,
            keywords=rule.keywords,
            severe_keywords=rule.severe_keywords,
        )
        if not evidence:
            continue

        score = _score_risk(evidence, rule.keywords, rule.severe_keywords, in_focus_area)
        if not in_focus_area and focus_areas and not _keep_cross_focus_signal(score, evidence):
            continue

        severity = _score_to_severity(score)

        summary = _build_risk_summary(document, rule.category, severity, evidence, in_focus_area)
        risks.append(RiskFinding(category=rule.category, severity=severity, summary=summary, evidence=evidence))

        if severity in {"medium", "high"} or in_focus_area:
            seller_questions.append(rule.seller_question)

    risks = sorted(
        risks,
        key=lambda risk: (
            -_SEVERITY_RANK[risk.severity],
            -_category_priority(risk.category),
            risk.category,
        ),
    )
    missing_items = _infer_document_gap_hints(text_lower, focus_areas, confidence)
    reading_priority = _estimate_reading_priority(document, focus_areas, risks, confidence)
    reading_reason = _build_reading_reason(focus_areas, risks, confidence)
    summary = _build_document_summary(
        document=document,
        focus_areas=focus_areas,
        risks=risks,
        missing_items=missing_items,
        confidence=confidence,
        confidence_reason=confidence_reason,
    )

    return DocumentAnalysis(
        document=document,
        summary=summary,
        risks=risks,
        seller_questions=unique_preserve_order(seller_questions),
        reading_priority=reading_priority,
        reading_reason=reading_reason,
        confidence=confidence,
        confidence_reason=confidence_reason,
        focus_areas=focus_areas,
        missing_items=missing_items,
    )


def identify_missing_items(
    documents: list[DocumentRecord],
    document_analyses: list[DocumentAnalysis],
) -> list[str]:
    """Identify diligence checklist gaps and unreadable critical documents."""

    combined_text = "\n".join(document.normalized_text.lower() for document in documents)
    missing_items: list[str] = []

    for item, keywords in EXPECTED_DILIGENCE_ITEMS.items():
        path_hints = EXPECTED_DILIGENCE_PATH_HINTS[item]
        matching_analyses = [
            analysis
            for analysis in document_analyses
            if _matches_expected_item(
                analysis.document.relative_path.as_posix().lower(),
                analysis.document.normalized_text.lower(),
                path_hints,
                keywords,
            )
        ]

        has_any_signal = bool(matching_analyses) or any(keyword in combined_text for keyword in keywords)
        has_readable_signal = any(
            analysis.confidence != "low" and bool(analysis.document.normalized_text.strip())
            for analysis in matching_analyses
        )

        if not has_any_signal:
            missing_items.append(item)
            continue

        if matching_analyses and not has_readable_signal:
            missing_items.append(f"Readable text or native file for {item.lower()}")

    return unique_preserve_order(missing_items)


def infer_entitlement_status(documents: list[DocumentRecord]) -> str:
    """Infer a coarse entitlement status from the supplied documents."""

    combined_text = "\n".join(document.normalized_text.lower() for document in documents)
    positive_hits = sum(
        keyword in combined_text
        for keyword in ("approved", "recorded map", "recorded plat", "city council", "planning commission approved", "vesting tentative map")
    )
    negative_hits = sum(
        keyword in combined_text
        for keyword in ("pending", "rezoning required", "not approved", "variance required", "appeal", "condition of approval")
    )

    if positive_hits and not negative_hits:
        return "Documents suggest core entitlement approvals are substantially in place, but final approval status should still be confirmed with the seller and jurisdiction."
    if positive_hits and negative_hits:
        return "Documents suggest a mixed entitlement picture: approvals appear to be advancing, but conditions, remaining approvals, or implementation items still matter."
    if negative_hits:
        return "Documents suggest entitlement work is still pending or conditioned."
    return "Entitlement status is unclear from the current document set."


def aggregate_risks(document_analyses: list[DocumentAnalysis]) -> list[RiskFinding]:
    """Roll up document findings into deal-level category risks."""

    grouped: dict[str, list[tuple[DocumentAnalysis, RiskFinding]]] = defaultdict(list)
    for analysis in document_analyses:
        for risk in analysis.risks:
            grouped[risk.category].append((analysis, risk))

    aggregated: list[RiskFinding] = []
    for category, entries in grouped.items():
        ranked_entries = sorted(
            entries,
            key=lambda entry: (
                -(1 if entry[1].category in entry[0].focus_areas else 0),
                -_SEVERITY_RANK[entry[1].severity],
                -entry[0].reading_priority,
                -_CONFIDENCE_RANK[entry[0].confidence],
            ),
        )
        lead_analysis, lead_risk = ranked_entries[0]
        evidence: list[str] = []
        lead_titles: list[str] = []
        for analysis, risk in ranked_entries:
            lead_titles.append(analysis.document.title)
            for snippet in risk.evidence[:1]:
                evidence.append(f"{analysis.document.title}: {clip_text(snippet, 220)}")
            if len(evidence) >= 3:
                break

        summary = (
            f"{lead_risk.severity.title()}-priority {category.lower()} signals are concentrated in "
            f"{', '.join(unique_preserve_order(lead_titles)[:3])}."
        )
        aggregated.append(
            RiskFinding(
                category=category,
                severity=lead_risk.severity,
                summary=summary,
                evidence=evidence,
            )
        )

    return sorted(
        aggregated,
        key=lambda risk: (
            -_SEVERITY_RANK[risk.severity],
            -_category_priority(risk.category),
            risk.category,
        ),
    )


def build_category_rollup(document_analyses: list[DocumentAnalysis]) -> dict[str, str]:
    """Summarize each risk category across the full deal package."""

    aggregated = {risk.category: risk for risk in aggregate_risks(document_analyses)}
    rollup: dict[str, str] = {}

    for rule in CATEGORY_RULES:
        risk = aggregated.get(rule.category)
        if risk is not None:
            rollup[rule.category] = risk.summary
            continue

        focused_docs = [
            analysis.document.title
            for analysis in document_analyses
            if rule.category in analysis.focus_areas
        ]
        if focused_docs:
            rollup[rule.category] = (
                f"Relevant documents were provided for {rule.category.lower()}, but extracted text did not surface a concentrated issue."
            )
            continue

        rollup[rule.category] = "No clear signal found in the supplied document set."

    return rollup


def recommend_reading_order(document_analyses: list[DocumentAnalysis]) -> list[ReadingRecommendation]:
    """Sort documents by priority for human review."""

    ordered = sorted(
        document_analyses,
        key=lambda analysis: (
            -analysis.reading_priority,
            -_CONFIDENCE_RANK[analysis.confidence],
            analysis.document.relative_path.as_posix().lower(),
        ),
    )
    grouped: dict[str, list[DocumentAnalysis]] = defaultdict(list)
    uncategorized: list[DocumentAnalysis] = []
    for analysis in ordered:
        primary_focus = _primary_focus_area(analysis.focus_areas)
        if primary_focus is None:
            uncategorized.append(analysis)
            continue
        grouped[primary_focus].append(analysis)

    interleaved: list[DocumentAnalysis] = []
    for focus in sorted(grouped, key=lambda category: (-_category_priority(category), category)):
        interleaved.append(grouped[focus].pop(0))

    remaining = sorted(
        [analysis for analyses in grouped.values() for analysis in analyses] + uncategorized,
        key=lambda analysis: (
            -analysis.reading_priority,
            -_CONFIDENCE_RANK[analysis.confidence],
            analysis.document.relative_path.as_posix().lower(),
        ),
    )
    ordered = interleaved + remaining

    return [
        ReadingRecommendation(
            title=analysis.document.title,
            relative_path=analysis.document.relative_path.as_posix(),
            priority=analysis.reading_priority,
            reason=analysis.reading_reason,
            confidence=analysis.confidence,
            focus_areas=analysis.focus_areas,
        )
        for analysis in ordered
    ]


def collect_seller_questions(
    document_analyses: list[DocumentAnalysis],
    missing_items: list[str],
    key_risks: list[RiskFinding],
) -> list[str]:
    """Merge category-driven questions with confidence and gap follow-up."""

    questions: list[str] = []

    for risk in key_risks:
        if risk.severity in {"medium", "high"}:
            question = _QUESTION_BY_CATEGORY.get(risk.category)
            if question:
                questions.append(question)

    for analysis in document_analyses:
        if analysis.confidence == "low" and analysis.focus_areas:
            questions.append(
                f"Please provide a text-readable or native version of {analysis.document.relative_path.name} so the {analysis.focus_areas[0].lower()} material can be reviewed fully."
            )

    for item in missing_items:
        if item.startswith("Readable text or native file for "):
            questions.append(f"Please provide {item[0].lower() + item[1:]}.")
        else:
            questions.append(f"Please provide the latest {item.lower()} if it exists.")

    return unique_preserve_order(questions)


def build_executive_summary_draft(
    deal_name: str,
    document_analyses: list[DocumentAnalysis],
    key_risks: list[RiskFinding],
    entitlement_status: str,
    missing_items: list[str],
    extraction_errors: list[str],
) -> str:
    """Build a deterministic executive summary before optional LLM refinement."""

    top_risks = ", ".join(risk.category for risk in key_risks[:3]) or "no concentrated diligence themes"
    lead_docs = ", ".join(_select_lead_document_titles(document_analyses, limit=3))
    low_confidence_docs = [analysis.document.title for analysis in document_analyses if analysis.confidence == "low"]
    missing_text = ", ".join(missing_items[:3]) or "no obvious checklist gaps or unreadable critical files"
    limitation_text = (
        f" Low-confidence extraction affected {len(low_confidence_docs)} document(s): {', '.join(low_confidence_docs[:3])}."
        if low_confidence_docs
        else ""
    )
    extraction_text = (
        f" {len(extraction_errors)} file(s) had extraction errors and should be checked manually."
        if extraction_errors
        else ""
    )
    return (
        f"Reviewed {len(document_analyses)} document(s) for {deal_name}. "
        f"Entitlement status: {entitlement_status} "
        f"The most decision-relevant themes currently appear to be {top_risks}, with primary attention on {lead_docs}. "
        f"Potential missing or unreadable diligence items include {missing_text}.{limitation_text}{extraction_text}"
    ).strip()


def _derive_focus_areas(document: DocumentRecord) -> list[str]:
    path_text = document.relative_path.as_posix().lower()
    focus_areas = [
        rule.category
        for rule in CATEGORY_RULES
        if any(hint in path_text for hint in rule.path_hints)
    ]
    return sorted(
        unique_preserve_order(focus_areas),
        key=lambda category: (-_category_priority(category), category),
    )


def _calculate_document_confidence(document: DocumentRecord) -> tuple[str, str]:
    warnings_text = " ".join(document.warnings).lower()
    ocr_page_warnings = sum("returned no text" in warning.lower() for warning in document.warnings)
    page_count = int(document.metadata.get("page_count", 0) or 0)
    text_length = len(document.normalized_text.strip())

    if "no pdf text extracted" in warnings_text or "normalized text is empty" in warnings_text or text_length == 0:
        return "low", "No usable text was extracted from the document."

    if ocr_page_warnings:
        if page_count and (ocr_page_warnings / page_count) >= 0.15:
            return "low", f"{ocr_page_warnings} page(s) out of {page_count} had no extracted text."
        return "medium", f"{ocr_page_warnings} page(s) had no extracted text, reducing confidence."

    if text_length < 500:
        return "medium", "Extracted text was limited, so conclusions are directional."

    return "high", "Text extraction was strong with no OCR-related warnings."


def _collect_evidence(
    *,
    sentences: list[str],
    lower_sentences: list[str],
    keywords: tuple[str, ...],
    severe_keywords: tuple[str, ...],
) -> list[str]:
    scored_sentences: list[tuple[int, str]] = []

    for sentence, lower_sentence in zip(sentences, lower_sentences):
        match_count = _count_keyword_hits(lower_sentence, keywords)
        if not match_count:
            continue

        cleaned = _clean_sentence(sentence)
        if not _is_substantive_sentence(cleaned):
            continue

        severe_count = _count_keyword_hits(lower_sentence, severe_keywords)
        score = (match_count * 3) + (severe_count * 5)
        scored_sentences.append((score, cleaned))

    scored_sentences.sort(key=lambda item: (-item[0], len(item[1])))
    return unique_preserve_order(sentence for _, sentence in scored_sentences)[:3]


def _score_risk(
    evidence: list[str],
    keywords: tuple[str, ...],
    severe_keywords: tuple[str, ...],
    in_focus_area: bool,
) -> int:
    evidence_text = " ".join(evidence).lower()
    score = len(evidence)
    score += _count_keyword_hits(evidence_text, keywords)
    score += 2 * _count_keyword_hits(evidence_text, severe_keywords)
    if in_focus_area:
        score += 1
    return score


def _score_to_severity(score: int) -> str:
    if score >= 5:
        return "high"
    if score >= 3:
        return "medium"
    return "low"


def _build_risk_summary(
    document: DocumentRecord,
    category: str,
    severity: str,
    evidence: list[str],
    in_focus_area: bool,
) -> str:
    lead = evidence[0] if evidence else "No supporting evidence captured."
    focus_prefix = "Category-aligned source document." if in_focus_area else "Supporting signal detected."
    return f"{focus_prefix} {category} appears {severity} priority based on extracted text. Lead indicator: {lead}"


def _build_document_summary(
    *,
    document: DocumentRecord,
    focus_areas: list[str],
    risks: list[RiskFinding],
    missing_items: list[str],
    confidence: str,
    confidence_reason: str,
) -> str:
    cleaned_text = _clean_sentence(document.normalized_text)
    base_summary = extractive_summary(cleaned_text, max_sentences=2)
    focus_text = ", ".join(focus_areas[:3]) or "General diligence support"
    aligned_risks = [risk for risk in risks if risk.category in focus_areas]
    lead_risks = aligned_risks or risks
    risk_text = ", ".join(risk.category for risk in lead_risks[:3]) or "no concentrated risk signals surfaced from extracted text"
    gap_text = (
        f" Potential follow-up: {', '.join(missing_items)}."
        if missing_items
        else ""
    )
    return (
        f"{document.title} is primarily a {focus_text.lower()} document. {base_summary}\n\n"
        f"Primary review themes: {risk_text}. Confidence: {confidence.title()} ({confidence_reason}).{gap_text}"
    ).strip()


def _estimate_reading_priority(
    document: DocumentRecord,
    focus_areas: list[str],
    risks: list[RiskFinding],
    confidence: str,
) -> int:
    base_priority = max((_RULE_BY_CATEGORY[focus].reading_priority for focus in focus_areas), default=55)
    aligned_risks = [risk for risk in risks if risk.category in focus_areas]
    signal_risks = aligned_risks or risks[:1]
    severity_bonus = sum(
        4 if risk.severity == "high" else 2 if risk.severity == "medium" else 1
        for risk in signal_risks[:2]
    )
    confidence_bonus = 6 if confidence == "low" and focus_areas else 2 if confidence == "medium" and focus_areas else 0

    filename = document.relative_path.name.lower()
    filename_bonus = max(
        (
            2
            for focus in focus_areas
            if any(hint in filename for hint in _RULE_BY_CATEGORY[focus].path_hints)
        ),
        default=0,
    )

    return base_priority + severity_bonus + confidence_bonus + filename_bonus + max(len(focus_areas) - 1, 0)


def _build_reading_reason(
    focus_areas: list[str],
    risks: list[RiskFinding],
    confidence: str,
) -> str:
    focus_label = _primary_focus_area(focus_areas) or "supporting diligence"
    aligned_risks = [risk for risk in risks if risk.category in focus_areas]
    lead_risk = max(
        aligned_risks or risks,
        key=lambda risk: _SEVERITY_RANK[risk.severity],
        default=None,
    )

    if confidence == "low":
        return f"Primary {focus_label.lower()} source document, but extraction confidence is low; manual review or OCR is needed."
    if lead_risk is not None:
        return f"Primary {focus_label.lower()} source document with {lead_risk.severity}-priority {lead_risk.category.lower()} signals."
    return f"Primary {focus_label.lower()} source document for deal review."


def _infer_document_gap_hints(text_lower: str, focus_areas: list[str], confidence: str) -> list[str]:
    hints = [
        item
        for item, markers in DOCUMENT_GAP_HINTS.items()
        if any(marker in text_lower for marker in markers)
    ]

    if confidence == "low" and focus_areas:
        hints.append("Readable text or native file may be needed for this document")

    return unique_preserve_order(hints)


def _matches_expected_item(
    path_text: str,
    text_lower: str,
    path_hints: tuple[str, ...],
    keywords: tuple[str, ...],
) -> bool:
    return any(hint in path_text for hint in path_hints) or any(_keyword_present(text_lower, keyword) for keyword in keywords)


def _keep_cross_focus_signal(score: int, evidence: list[str]) -> bool:
    return len(evidence) >= 2 or score >= 2


def _count_keyword_hits(text: str, keywords: tuple[str, ...]) -> int:
    return sum(_keyword_present(text, keyword) for keyword in keywords)


@lru_cache(maxsize=512)
def _keyword_pattern(keyword: str) -> re.Pattern[str]:
    escaped = re.escape(keyword)
    escaped = escaped.replace(r"\ ", r"\s+").replace(r"\-", r"[-\s]?")
    return re.compile(rf"(?<!\w){escaped}(?!\w)", re.IGNORECASE)


def _keyword_present(text: str, keyword: str) -> bool:
    return bool(_keyword_pattern(keyword).search(text))


def _category_priority(category: str) -> int:
    return _RULE_BY_CATEGORY.get(category, CATEGORY_RULES[-1]).reading_priority


def _primary_focus_area(focus_areas: list[str]) -> str | None:
    if not focus_areas:
        return None
    return max(focus_areas, key=_category_priority)


def _select_lead_document_titles(document_analyses: list[DocumentAnalysis], *, limit: int) -> list[str]:
    ordered = recommend_reading_order(document_analyses)
    selected: list[str] = []
    seen_focuses: set[str] = set()

    for recommendation in ordered:
        primary_focus = _primary_focus_area(recommendation.focus_areas)
        if primary_focus and primary_focus in seen_focuses:
            continue
        selected.append(recommendation.title)
        if primary_focus:
            seen_focuses.add(primary_focus)
        if len(selected) >= limit:
            return selected

    return selected[:limit]


def _clean_sentence(text: str) -> str:
    text = _PAGE_MARKER_RE.sub("", text)
    text = text.replace("\n", " ").strip()
    text = re.sub(r"\s+", " ", text)
    return text


def _is_substantive_sentence(sentence: str) -> bool:
    if len(sentence) < 30:
        return False
    if sentence.count(" ") < 4:
        return False
    lower_sentence = sentence.lower()
    if any(phrase in lower_sentence for phrase in _NOISE_PHRASES):
        return False

    alpha_count = sum(character.isalpha() for character in sentence)
    if alpha_count < 30:
        return False

    return True
