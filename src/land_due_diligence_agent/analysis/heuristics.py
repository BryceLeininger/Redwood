"""Deterministic document and deal-level analysis heuristics."""

from __future__ import annotations

from collections import defaultdict

from land_due_diligence_agent.analysis.risk_rules import CATEGORY_RULES, DOCUMENT_GAP_HINTS, EXPECTED_DILIGENCE_ITEMS
from land_due_diligence_agent.models import DocumentAnalysis, DocumentRecord, ReadingRecommendation, RiskFinding
from land_due_diligence_agent.utils.text import clip_text, extractive_summary, split_sentences, unique_preserve_order


_SEVERITY_RANK = {"low": 1, "medium": 2, "high": 3}
_READING_KEYWORDS = {
    "title": 3,
    "survey": 3,
    "environment": 3,
    "phase": 3,
    "geotech": 3,
    "drainage": 2,
    "flood": 2,
    "utility": 2,
    "access": 2,
    "plat": 2,
    "schedule": 2,
}


def analyze_document(document: DocumentRecord) -> DocumentAnalysis:
    """Produce deterministic document-level diligence findings."""

    sentences = split_sentences(document.normalized_text)
    lower_sentences = [sentence.lower() for sentence in sentences]
    text_lower = document.normalized_text.lower()

    risks: list[RiskFinding] = []
    seller_questions: list[str] = []

    for rule in CATEGORY_RULES:
        evidence = _collect_evidence(sentences, lower_sentences, rule.keywords)
        if not evidence:
            continue

        severity = _classify_severity(evidence, rule.severe_keywords)
        summary = _build_risk_summary(rule.category, severity, evidence)
        risks.append(RiskFinding(category=rule.category, severity=severity, summary=summary, evidence=evidence))

        if severity in {"medium", "high"} or rule.category == "Entitlement Status":
            seller_questions.append(rule.seller_question)

    missing_items = _infer_document_gap_hints(text_lower)
    reading_priority = _estimate_reading_priority(document, risks)
    reading_reason = _build_reading_reason(document, risks)
    summary = _build_document_summary(document, risks, missing_items)

    return DocumentAnalysis(
        document=document,
        summary=summary,
        risks=risks,
        seller_questions=unique_preserve_order(seller_questions),
        reading_priority=reading_priority,
        reading_reason=reading_reason,
        missing_items=missing_items,
    )


def identify_missing_items(documents: list[DocumentRecord]) -> list[str]:
    """Identify diligence checklist gaps from document keyword coverage."""

    combined_text = "\n".join(document.normalized_text.lower() for document in documents)
    missing_items = [
        item
        for item, keywords in EXPECTED_DILIGENCE_ITEMS.items()
        if not any(keyword in combined_text for keyword in keywords)
    ]
    return unique_preserve_order(missing_items)


def infer_entitlement_status(documents: list[DocumentRecord]) -> str:
    """Infer a coarse entitlement status from the supplied documents."""

    combined_text = "\n".join(document.normalized_text.lower() for document in documents)
    positive_hits = sum(keyword in combined_text for keyword in ("approved", "recorded plat", "annexed", "entitled", "zoned"))
    negative_hits = sum(keyword in combined_text for keyword in ("pending", "rezoning required", "not approved", "variance required", "appeal"))

    if positive_hits and not negative_hits:
        return "Documents suggest core entitlement approvals may already be in place, but confirm final status directly with the seller."
    if positive_hits and negative_hits:
        return "Documents suggest a mixed entitlement picture: some approvals appear in place, but additional entitlement actions still look active or unresolved."
    if negative_hits:
        return "Documents suggest entitlement work is still pending or incomplete."
    return "Entitlement status is unclear from the current document set."


def aggregate_risks(document_analyses: list[DocumentAnalysis]) -> list[RiskFinding]:
    """Roll up document findings into deal-level category risks."""

    grouped: dict[str, list[tuple[str, RiskFinding]]] = defaultdict(list)
    for analysis in document_analyses:
        for risk in analysis.risks:
            grouped[risk.category].append((analysis.document.title, risk))

    aggregated: list[RiskFinding] = []
    for category, entries in grouped.items():
        highest = max(entries, key=lambda entry: _SEVERITY_RANK[entry[1].severity])[1]
        evidence: list[str] = []
        document_titles: list[str] = []
        for title, risk in entries:
            document_titles.append(title)
            for snippet in risk.evidence[:1]:
                evidence.append(f"{title}: {clip_text(snippet, 220)}")
            if len(evidence) >= 3:
                break

        unique_titles = unique_preserve_order(document_titles)
        summary = (
            f"{len(entries)} document(s) flagged {category.lower()} signals across "
            f"{', '.join(unique_titles[:3])}."
        )
        aggregated.append(
            RiskFinding(
                category=category,
                severity=highest.severity,
                summary=summary,
                evidence=evidence,
            )
        )

    return sorted(aggregated, key=lambda risk: (-_SEVERITY_RANK[risk.severity], risk.category))


def build_category_rollup(document_analyses: list[DocumentAnalysis]) -> dict[str, str]:
    """Summarize each risk category across the full deal package."""

    aggregated = {risk.category: risk for risk in aggregate_risks(document_analyses)}
    rollup: dict[str, str] = {}

    for rule in CATEGORY_RULES:
        risk = aggregated.get(rule.category)
        if risk is None:
            rollup[rule.category] = "No clear signal found in the supplied document set."
            continue
        rollup[rule.category] = risk.summary

    return rollup


def recommend_reading_order(document_analyses: list[DocumentAnalysis]) -> list[ReadingRecommendation]:
    """Sort documents by priority for human review."""

    ordered = sorted(
        document_analyses,
        key=lambda analysis: (-analysis.reading_priority, analysis.document.relative_path.as_posix().lower()),
    )
    return [
        ReadingRecommendation(
            title=analysis.document.title,
            relative_path=analysis.document.relative_path.as_posix(),
            priority=analysis.reading_priority,
            reason=analysis.reading_reason,
        )
        for analysis in ordered
    ]


def collect_seller_questions(document_analyses: list[DocumentAnalysis], missing_items: list[str]) -> list[str]:
    """Merge document-derived questions with gap-driven requests."""

    questions = [question for analysis in document_analyses for question in analysis.seller_questions]
    questions.extend(f"Please provide the latest {item.lower()} if it exists." for item in missing_items)
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

    risk_labels = ", ".join(risk.category for risk in key_risks[:3]) or "no concentrated diligence themes"
    missing_text = ", ".join(missing_items[:4]) or "no obvious checklist gaps from keyword coverage"
    extraction_text = (
        f" {len(extraction_errors)} file(s) had extraction issues and should be checked manually."
        if extraction_errors
        else ""
    )
    return (
        f"Reviewed {len(document_analyses)} document(s) for {deal_name}. "
        f"Entitlement status: {entitlement_status} "
        f"The most important diligence themes currently appear to be {risk_labels}. "
        f"Potential missing diligence items include {missing_text}.{extraction_text}"
    ).strip()


def _collect_evidence(
    sentences: list[str],
    lower_sentences: list[str],
    keywords: tuple[str, ...],
) -> list[str]:
    evidence: list[str] = []
    for sentence, lower_sentence in zip(sentences, lower_sentences):
        if any(keyword in lower_sentence for keyword in keywords):
            evidence.append(clip_text(sentence, 240))
        if len(evidence) >= 3:
            break
    return evidence


def _classify_severity(evidence: list[str], severe_keywords: tuple[str, ...]) -> str:
    evidence_text = " ".join(evidence).lower()
    if any(keyword in evidence_text for keyword in severe_keywords):
        return "high"
    if len(evidence) >= 2:
        return "medium"
    return "low"


def _build_risk_summary(category: str, severity: str, evidence: list[str]) -> str:
    lead = evidence[0] if evidence else "No supporting evidence captured."
    return f"{category} shows {severity} urgency based on extracted text. Lead indicator: {lead}"


def _build_document_summary(
    document: DocumentRecord,
    risks: list[RiskFinding],
    missing_items: list[str],
) -> str:
    base_summary = extractive_summary(document.normalized_text, max_sentences=3)
    risk_text = ", ".join(risk.category for risk in risks[:4]) or "no concentrated risk themes detected"
    warning_text = (
        f" Extraction warnings: {'; '.join(document.warnings)}"
        if document.warnings
        else ""
    )
    gap_text = (
        f" Potential gaps noted in this document: {', '.join(missing_items)}."
        if missing_items
        else ""
    )
    return (
        f"{base_summary}\n\n"
        f"This document primarily points to {risk_text}.{gap_text}{warning_text}"
    ).strip()


def _estimate_reading_priority(document: DocumentRecord, risks: list[RiskFinding]) -> int:
    priority = 1 + sum(_SEVERITY_RANK[risk.severity] for risk in risks)
    filename = document.relative_path.name.lower()
    for keyword, bonus in _READING_KEYWORDS.items():
        if keyword in filename:
            priority += bonus
    if document.warnings:
        priority += 1
    return priority


def _build_reading_reason(document: DocumentRecord, risks: list[RiskFinding]) -> str:
    if risks:
        highest = max(risks, key=lambda risk: _SEVERITY_RANK[risk.severity])
        return f"Contains {highest.severity}-priority {highest.category.lower()} indicators."
    if document.warnings:
        return "Review manually because automated extraction was incomplete."
    return "Baseline supporting document for context."


def _infer_document_gap_hints(text_lower: str) -> list[str]:
    hints = [
        item
        for item, markers in DOCUMENT_GAP_HINTS.items()
        if any(marker in text_lower for marker in markers)
    ]
    return unique_preserve_order(hints)
