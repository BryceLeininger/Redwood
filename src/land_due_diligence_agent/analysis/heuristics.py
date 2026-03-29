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
_RULE_BY_CATEGORY = {rule.category: rule for rule in CATEGORY_RULES}
_MAX_KEY_RISKS = 6
_GENERIC_UNRESOLVED_TERMS = (
    "pending",
    "required",
    "condition",
    "conditions of approval",
    "subject to",
    "confirm",
    "prior to",
    "must",
    "shall",
    "outstanding",
    "unreadable",
    "budgetary",
    "preliminary",
)
_CATEGORY_DECISION_TERMS = {
    "Entitlement Status": ("condition of approval", "conditions of approval", "prior to", "required", "shall", "must"),
    "Environmental Risks": ("recognized environmental condition", "phase ii", "remediation", "contamination", "hazardous", "wetlands", "mitigation", "habitat"),
    "Flood / Drainage Issues": ("floodplain", "fema", "100-year", "stormwater", "drainage", "detention", "offsite drainage"),
    "Geotechnical Risks": ("liquefaction", "settlement", "foundation", "grading", "overexcavation", "seismic", "expansive soil"),
    "Offsite Obligations": ("frontage", "offsite", "encroachment permit", "guarantee", "dedicated", "improvement plan", "reimbursement"),
    "Fee / Exaction Burden": ("impact fee", "capacity fee", "school fee", "fee increase", "public works fee", "building department fees"),
    "Budget / Cost Reliability": ("budgetary", "proposal", "bid form", "preliminary", "allowance", "contingency", "pricing", "no plans provided"),
    "Utilities / Infrastructure Issues": ("will serve", "water service", "sewer service", "joint trench", "capacity", "upsizing", "lift station", "substation"),
    "Title / Access Concerns": ("title exception", "easement", "encroachment", "access", "ingress", "egress", "right-of-way", "encumbrance"),
    "Schedule Risks": ("delay", "backlog", "moratorium", "critical path", "long lead", "phasing"),
}
_CATEGORY_BENIGN_TERMS = {
    "Entitlement Status": ("approved", "consistent with the zoning ordinance", "consistent with the zoning ordinance and general plan"),
    "Environmental Risks": ("no mapped sites were found", "no mapped sites", "no recognized environmental condition"),
    "Schedule Risks": ("turnaround times",),
}


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
        return "Core land use approvals appear materially advanced, with no obvious sign in the file set that a major discretionary approval remains open."
    if positive_hits and negative_hits:
        return "Core approvals appear to be in place, but the path to permit issuance and execution still looks conditioned on remaining approval requirements or conditions of approval."
    if negative_hits:
        return "Entitlement completion still appears open, and the file set suggests meaningful approval or condition-related work remains."
    return "Entitlement status is unclear from the current document set."


def aggregate_risks(document_analyses: list[DocumentAnalysis]) -> list[RiskFinding]:
    """Roll up document findings into deal-level category risks."""

    grouped: dict[str, list[tuple[DocumentAnalysis, RiskFinding]]] = defaultdict(list)
    for analysis in document_analyses:
        for risk in analysis.risks:
            grouped[risk.category].append((analysis, risk))

    aggregated_candidates: list[tuple[int, RiskFinding]] = []
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
        aggregate = _build_aggregate_risk(category, ranked_entries)
        if aggregate is None:
            continue
        aggregated_candidates.append(aggregate)

    ordered = sorted(
        aggregated_candidates,
        key=lambda item: (
            -_SEVERITY_RANK[item[1].severity],
            -item[0],
            -_category_priority(item[1].category),
            item[1].category,
        ),
    )
    return [risk for _, risk in ordered[:_MAX_KEY_RISKS]]


def build_category_rollup(document_analyses: list[DocumentAnalysis]) -> dict[str, str]:
    """Summarize each risk category across the full deal package."""

    return {risk.category: risk.summary for risk in aggregate_risks(document_analyses)}


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
            questions.append(_build_negotiation_question(risk))

    for analysis in document_analyses:
        if analysis.confidence == "low" and analysis.focus_areas:
            questions.append(
                f"Please replace {analysis.document.relative_path.name} with a native or text-readable file, because that unreadable document currently weakens diligence on {analysis.focus_areas[0].lower()}."
            )

    for item in missing_items:
        if item.startswith("Readable text or native file for "):
            questions.append(f"Please provide {item[0].lower() + item[1:]}, because that file is needed to underwrite the issue cleanly.")
        else:
            questions.append(f"Please provide the latest {item.lower()} and confirm whether it is the version currently being used for underwriting and approvals.")

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

    lead_docs = ", ".join(_select_lead_document_titles(document_analyses, limit=4))
    low_confidence_docs = [analysis.document.title for analysis in document_analyses if analysis.confidence == "low"]
    conclusions = "\n".join(f"- {conclusion}" for conclusion in _build_top_conclusions(key_risks, entitlement_status, missing_items, low_confidence_docs))
    known_points = "\n".join(f"- {point}" for point in _build_known_points(document_analyses, entitlement_status))
    unresolved_points = "\n".join(f"- {point}" for point in _build_unresolved_points(key_risks, missing_items, low_confidence_docs))
    decision_points = "\n".join(f"- {point}" for point in _build_decision_points(key_risks, missing_items, low_confidence_docs))
    limitation_text = (
        f"\nLow-confidence extraction affected {len(low_confidence_docs)} document(s): {', '.join(low_confidence_docs[:3])}."
        if low_confidence_docs
        else ""
    )
    extraction_text = (
        f"\n{len(extraction_errors)} file(s) had extraction errors and should be checked manually."
        if extraction_errors
        else ""
    )
    return (
        f"Deal: {deal_name}\n"
        f"Primary source documents: {lead_docs}\n"
        f"Entitlement status: {entitlement_status}\n\n"
        f"Most important conclusions:\n{conclusions}\n\n"
        f"What appears known:\n{known_points}\n\n"
        f"What appears unresolved:\n{unresolved_points}\n\n"
        f"What matters most for the acquisition decision:\n{decision_points}"
        f"{limitation_text}{extraction_text}"
    ).strip()


def _build_aggregate_risk(
    category: str,
    ranked_entries: list[tuple[DocumentAnalysis, RiskFinding]],
) -> tuple[int, RiskFinding] | None:
    lead_analysis, lead_risk = ranked_entries[0]
    source_documents: list[str] = []
    evidence: list[str] = []
    evidence_text_parts: list[str] = []
    low_confidence_sources = 0

    for analysis, risk in ranked_entries:
        source_documents.append(analysis.document.title)
        if analysis.confidence == "low":
            low_confidence_sources += 1
        for snippet in risk.evidence[:1]:
            clipped = clip_text(snippet, 220)
            evidence.append(f"{analysis.document.title}: {clipped}")
            evidence_text_parts.append(clipped)
        if len(evidence) >= 3:
            break

    evidence_text = " ".join(evidence_text_parts).lower()
    decision_score = _decision_score(category, evidence_text, lead_risk.severity, low_confidence_sources)
    if not _should_include_aggregate(category, lead_risk.severity, decision_score):
        return None

    issue = _build_issue_text(category, evidence_text, source_documents, low_confidence_sources)
    why_it_matters = _build_why_it_matters_text(category)
    likely_implication = _build_implication_text(category, evidence_text, low_confidence_sources)
    summary = f"{issue} {why_it_matters} Likely implication: {likely_implication}"

    return (
        decision_score,
        RiskFinding(
            category=category,
            severity=lead_risk.severity,
            summary=summary,
            evidence=evidence,
            issue=issue,
            why_it_matters=why_it_matters,
            likely_implication=likely_implication,
            source_documents=unique_preserve_order(source_documents)[:3],
        ),
    )


def _decision_score(category: str, evidence_text: str, severity: str, low_confidence_sources: int) -> int:
    rule = _RULE_BY_CATEGORY[category]
    score = _SEVERITY_RANK[severity] * 2
    score += _count_keyword_hits(evidence_text, rule.severe_keywords) * 3
    score += sum(_keyword_present(evidence_text, term) for term in _CATEGORY_DECISION_TERMS.get(category, ())) * 2
    score += sum(_keyword_present(evidence_text, term) for term in _GENERIC_UNRESOLVED_TERMS)
    score -= sum(_keyword_present(evidence_text, term) for term in _CATEGORY_BENIGN_TERMS.get(category, ())) * 2
    if low_confidence_sources and category == "Budget / Cost Reliability":
        score += 3
    return score


def _should_include_aggregate(category: str, severity: str, decision_score: int) -> bool:
    thresholds = {
        "Entitlement Status": 4,
        "Environmental Risks": 4,
        "Flood / Drainage Issues": 4,
        "Geotechnical Risks": 4,
        "Offsite Obligations": 4,
        "Fee / Exaction Burden": 3,
        "Budget / Cost Reliability": 3,
        "Utilities / Infrastructure Issues": 4,
        "Title / Access Concerns": 3,
        "Schedule Risks": 7,
    }
    threshold = thresholds.get(category, 4)
    if severity == "low":
        if category == "Schedule Risks":
            return False
        return decision_score >= threshold
    return decision_score >= threshold


def _build_issue_text(
    category: str,
    evidence_text: str,
    source_documents: list[str],
    low_confidence_sources: int,
) -> str:
    if category == "Title / Access Concerns":
        return "Title materials reference access, easement, encumbrance, or survey-related items that could conflict with the current site plan and closing assumptions."
    if category == "Entitlement Status":
        return "Core approvals appear advanced, but conditions of approval and implementation items still need to be closed before the entitlement package can be treated as execution-ready."
    if category == "Geotechnical Risks":
        return "Geotechnical reports point to settlement, liquefaction, grading, or foundation sensitivity that could change the real site-development scope."
    if category == "Flood / Drainage Issues":
        return "Stormwater and flood-control materials indicate drainage design assumptions that may still drive engineering scope or permit conditions."
    if category == "Fee / Exaction Burden":
        return "The file set shows meaningful impact and public works fee exposure that needs to be locked before the land basis is treated as reliable."
    if category == "Offsite Obligations":
        return "The package suggests frontage, dedication, permit, or offsite improvement obligations may still remain with the project."
    if category == "Budget / Cost Reliability":
        if low_confidence_sources:
            return "Cost certainty is weak because at least part of the site-development pricing package is unreadable or only budgetary."
        return "Current site-development pricing still appears preliminary rather than fully converted into hard, decision-grade bids."
    if category == "Utilities / Infrastructure Issues":
        return "Utility planning appears tied to service, joint trench, or infrastructure assumptions that still need confirmation from the serving parties."
    if category == "Environmental Risks":
        if any(_keyword_present(evidence_text, term) for term in ("recognized environmental condition", "phase ii", "contamination", "remediation")):
            return "Environmental diligence points to potential contamination or follow-up work rather than a clean no-issue file."
        return "Environmental materials point to mitigation, compliance, or habitat-related items that may still affect execution."
    if category == "Schedule Risks":
        return "The file set still suggests timing exposure on the path from current approvals to a fully executable development program."
    return f"{category} appears material to the acquisition decision."


def _build_why_it_matters_text(category: str) -> str:
    if category == "Title / Access Concerns":
        return "If title exceptions or access rights do not line up with the plan set, closability, lender comfort, and buildability can all be impaired."
    if category == "Entitlement Status":
        return "Approved entitlements do not fully de-risk the deal if permit-stage conditions, dedications, or implementation triggers are still open."
    if category == "Geotechnical Risks":
        return "Soils-driven scope typically flows directly into grading, retaining, foundation design, contingency, and sometimes yield or layout."
    if category == "Flood / Drainage Issues":
        return "Drainage and flood constraints can push both engineering complexity and permit timing, especially if detention or offsite work is required."
    if category == "Fee / Exaction Burden":
        return "Unconfirmed fees move directly into land basis and can change materially before permits if the schedule slips."
    if category == "Offsite Obligations":
        return "Remaining frontage or offsite obligations can add real cost and can hold up vertical execution if they are not clearly allocated."
    if category == "Budget / Cost Reliability":
        return "A land acquisition decision is materially weaker when the cost package is still preliminary or cannot be fully read and audited."
    if category == "Utilities / Infrastructure Issues":
        return "Utility constraints can delay first permits or vertical start and can also create additional offsite and underground cost."
    if category == "Environmental Risks":
        return "Environmental follow-up can create third-party workstreams, mitigation cost, and closing or execution conditions."
    if category == "Schedule Risks":
        return "Timing risk matters because carry, option structure, and fee exposure can move quickly if the critical path slips."
    return "It has direct implications for acquisition underwriting and execution."


def _build_implication_text(category: str, evidence_text: str, low_confidence_sources: int) -> str:
    if category == "Title / Access Concerns":
        return "Closability and site-plan execution risk until title/access items are fully cleared."
    if category == "Entitlement Status":
        return "Permit timing and execution risk until remaining conditions or implementation items are closed."
    if category == "Geotechnical Risks":
        return "Higher grading and foundation cost, additional engineering iterations, and larger contingency."
    if category == "Flood / Drainage Issues":
        return "Potential added stormwater/offsite work, slower permits, and site-engineering scope creep."
    if category == "Fee / Exaction Burden":
        return "Pressure on land basis and reduced cost certainty before permit issuance."
    if category == "Offsite Obligations":
        return "Added pre-vertical cost and possible timing drag if buyer-facing obligations remain."
    if category == "Budget / Cost Reliability":
        if low_confidence_sources:
            return "Underwriting risk because a meaningful part of the cost package is not yet decision-grade."
        return "Cost-overrun and renegotiation risk if preliminary site numbers are being treated as firm."
    if category == "Utilities / Infrastructure Issues":
        return "Timing and cost risk if service, capacity, or joint trench assumptions prove incomplete."
    if category == "Environmental Risks":
        return "Potential added diligence scope, mitigation cost, or agency follow-up before execution."
    if category == "Schedule Risks":
        return "Longer hold period and more exposure to fee, carry, and market timing changes."
    return "Acquisition risk requiring direct verification."


def _build_negotiation_question(risk: RiskFinding) -> str:
    if risk.category == "Title / Access Concerns":
        return "Please mark up the title package and survey with every exception, easement, encroachment, and access right that affects the current plan set, and identify what must be cured, endorsed, or redesigned before closing."
    if risk.category == "Entitlement Status":
        return "Please provide the live conditions-of-approval tracker and identify every remaining item required before map recordation, grading permit, building permit, or vertical start."
    if risk.category == "Geotechnical Risks":
        return "Please confirm which geotechnical recommendations are currently driving grading and foundation design, and state whether liquefaction, settlement, overexcavation, and retaining assumptions are fully carried in the site budget."
    if risk.category == "Flood / Drainage Issues":
        return "Please identify every unresolved stormwater, floodplain, detention, or offsite drainage obligation that could delay permits or add civil scope beyond the current underwriting."
    if risk.category == "Fee / Exaction Burden":
        return "Please provide the fee matrix currently used in underwriting, identify which figures are confirmed with the city, and quantify exposure to fee updates before permit issuance."
    if risk.category == "Offsite Obligations":
        return "Please identify every remaining frontage, dedication, permit, guarantee, reimbursement, or offsite improvement obligation that survives closing and state who is expected to pay for each item."
    if risk.category == "Budget / Cost Reliability":
        return "Please break out which site-development numbers are hard bids versus budgetary pricing, identify the largest open contingencies, and replace any unreadable budget files with native copies."
    if risk.category == "Utilities / Infrastructure Issues":
        return "Please confirm all will-serve and utility-capacity assumptions, required offsite extensions, and joint-trench scope, and identify any serving-agency approvals that are not yet in hand."
    if risk.category == "Environmental Risks":
        return "Please confirm whether the environmental package identified any RECs, mitigation obligations, habitat constraints, or follow-up agency work that is still open, and state who bears the cost and timing risk."
    if risk.category == "Schedule Risks":
        return "Please provide the current critical-path schedule showing remaining approvals, utility releases, offsite triggers, and the assumptions required to hit first permit and vertical-start dates."
    return f"Please address the current {risk.category.lower()} issue in a form that can be underwritten at closing."


def _build_top_conclusions(
    key_risks: list[RiskFinding],
    entitlement_status: str,
    missing_items: list[str],
    low_confidence_docs: list[str],
) -> list[str]:
    conclusions: list[str] = []
    if key_risks:
        for risk in key_risks[:4]:
            conclusions.append(risk.issue or risk.summary)
    else:
        conclusions.append(entitlement_status)

    if low_confidence_docs:
        conclusions.append("Cost certainty remains weaker than the rest of the file set because at least one budget document could not be fully read.")

    if missing_items:
        conclusions.append(f"Decision-readiness is limited until the package is supplemented with: {', '.join(missing_items[:2])}.")

    return unique_preserve_order(conclusions)[:5]


def _build_known_points(document_analyses: list[DocumentAnalysis], entitlement_status: str) -> list[str]:
    points = [entitlement_status]

    focus_sets = {focus for analysis in document_analyses for focus in analysis.focus_areas}
    if "Title / Access Concerns" in focus_sets:
        points.append("The file set includes a title package, which means title/access issues can be reviewed rather than assumed.")
    if "Geotechnical Risks" in focus_sets:
        points.append("Multiple geotechnical reports are present, so soils and foundation assumptions are at least partially documented.")
    if "Flood / Drainage Issues" in focus_sets:
        points.append("Stormwater and drainage materials are present, so civil assumptions are not being underwritten blind.")
    if "Fee / Exaction Burden" in focus_sets:
        points.append("A fee schedule is in the package, giving a starting point for public-works and impact-fee underwriting.")

    return unique_preserve_order(points)[:4]


def _build_unresolved_points(
    key_risks: list[RiskFinding],
    missing_items: list[str],
    low_confidence_docs: list[str],
) -> list[str]:
    points = [risk.issue for risk in key_risks[:4] if risk.issue]
    if low_confidence_docs:
        points.append(f"Low-confidence extraction remains on: {', '.join(low_confidence_docs[:2])}.")
    if missing_items:
        points.append(f"Missing or unsupported diligence items still include: {', '.join(missing_items[:3])}.")
    return unique_preserve_order(points)[:5]


def _build_decision_points(
    key_risks: list[RiskFinding],
    missing_items: list[str],
    low_confidence_docs: list[str],
) -> list[str]:
    points = [risk.likely_implication for risk in key_risks[:4] if risk.likely_implication]
    if low_confidence_docs:
        points.append("Do not treat the current cost package as fully decision-grade until unreadable or budgetary files are replaced with native support.")
    if missing_items:
        points.append("Underwriting should remain provisional where required supporting files are still missing or only indirectly referenced.")
    return unique_preserve_order(points)[:5]


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
