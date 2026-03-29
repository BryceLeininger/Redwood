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
from land_due_diligence_agent.models import Citation, ContradictionFinding, DocumentAnalysis, DocumentRecord, ReadingRecommendation, RiskFinding
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
_PRIMARY_RISK_COUNT = 3
_MAX_CONTRADICTIONS = 3
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
_RISK_GATING_MAP = {
    "Title / Access Concerns": ("Closing", "Underwriting confidence"),
    "Entitlement Status": ("Underwriting confidence", "Vertical start"),
    "Environmental Risks": ("Underwriting confidence", "Vertical start"),
    "Flood / Drainage Issues": ("Underwriting confidence", "Vertical start"),
    "Geotechnical Risks": ("Underwriting confidence", "Vertical start"),
    "Offsite Obligations": ("Underwriting confidence", "Vertical start"),
    "Fee / Exaction Burden": ("Underwriting confidence",),
    "Budget / Cost Reliability": ("Underwriting confidence",),
    "Utilities / Infrastructure Issues": ("Underwriting confidence", "Vertical start"),
    "Schedule Risks": ("Underwriting confidence",),
}


def analyze_document(document: DocumentRecord) -> DocumentAnalysis:
    """Produce deterministic document-level diligence findings."""

    focus_areas = _derive_focus_areas(document)
    confidence, confidence_reason = _calculate_document_confidence(document)
    sentence_records = _build_sentence_records(document)
    text_lower = document.normalized_text.lower()

    risks: list[RiskFinding] = []
    seller_questions: list[str] = []

    for rule in CATEGORY_RULES:
        in_focus_area = rule.category in focus_areas
        evidence_records = _collect_evidence(
            sentence_records=sentence_records,
            keywords=rule.keywords,
            severe_keywords=rule.severe_keywords,
        )
        if not evidence_records:
            continue

        evidence_texts = [text for text, _ in evidence_records]
        citations = _unique_citations([citation for _, citation in evidence_records])

        score = _score_risk(evidence_texts, rule.keywords, rule.severe_keywords, in_focus_area)
        if not in_focus_area and focus_areas and not _keep_cross_focus_signal(score, evidence_texts):
            continue

        severity = _score_to_severity(score)

        summary = _build_risk_summary(document, rule.category, severity, evidence_texts, in_focus_area)
        risks.append(
            RiskFinding(
                category=rule.category,
                severity=severity,
                summary=summary,
                evidence=evidence_texts,
                citations=citations,
            )
        )

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
    risks = [risk for _, risk in ordered[:_MAX_KEY_RISKS]]
    for index, risk in enumerate(risks):
        risk.priority_tier = "primary" if index < _PRIMARY_RISK_COUNT else "secondary"
    return risks


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


def detect_contradictions(
    document_analyses: list[DocumentAnalysis],
    key_risks: list[RiskFinding],
    missing_items: list[str],
) -> list[ContradictionFinding]:
    """Identify high-signal cross-document contradictions or tensions."""

    candidates = [
        _detect_offsite_completion_tension(document_analyses),
        _detect_title_vs_plan_tension(document_analyses, key_risks),
        _detect_entitlement_vs_condition_tension(document_analyses),
        _detect_geotech_vs_budget_tension(document_analyses, key_risks, missing_items),
    ]

    contradictions = [candidate for candidate in candidates if candidate is not None]
    contradictions.sort(
        key=lambda finding: (
            -finding.priority,
            -len(finding.citations),
            finding.description,
        ),
    )

    deduped: list[ContradictionFinding] = []
    seen_descriptions: set[str] = set()
    for finding in contradictions:
        if finding.description in seen_descriptions:
            continue
        seen_descriptions.add(finding.description)
        deduped.append(finding)
        if len(deduped) >= _MAX_CONTRADICTIONS:
            break
    return deduped


def collect_seller_questions(
    document_analyses: list[DocumentAnalysis],
    missing_items: list[str],
    key_risks: list[RiskFinding],
    contradictions: list[ContradictionFinding],
) -> list[str]:
    """Merge category-driven questions with confidence and gap follow-up."""

    questions: list[str] = []

    for risk in key_risks:
        if risk.severity in {"medium", "high"}:
            questions.append(_build_negotiation_question(risk))

    for contradiction in contradictions:
        questions.append(_build_contradiction_question(contradiction))

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
    contradictions: list[ContradictionFinding],
    entitlement_status: str,
    missing_items: list[str],
    extraction_errors: list[str],
) -> str:
    """Build a deterministic executive summary before optional LLM refinement."""

    lead_docs = ", ".join(_select_lead_document_titles(document_analyses, limit=4))
    low_confidence_docs = [analysis.document.title for analysis in document_analyses if analysis.confidence == "low"]
    primary_risks = [risk for risk in key_risks if risk.priority_tier == "primary"] or key_risks[:_PRIMARY_RISK_COUNT]
    secondary_risks = [risk for risk in key_risks if risk.priority_tier == "secondary"]
    conclusions = "\n".join(f"- {conclusion}" for conclusion in _build_top_conclusions(key_risks, entitlement_status, missing_items, low_confidence_docs))
    known_points = "\n".join(f"- {point}" for point in _build_known_points(document_analyses, entitlement_status))
    unresolved_points = "\n".join(f"- {point}" for point in _build_unresolved_points(key_risks, contradictions, missing_items, low_confidence_docs))
    primary_risk_text = "\n".join(f"- {risk.summary}" for risk in primary_risks) or "- No primary deal-shaping risk was isolated from the extracted text."
    secondary_risk_text = (
        "\n".join(f"- {risk.summary}" for risk in secondary_risks)
        if secondary_risks
        else "- No secondary risk was elevated beyond the primary issue set."
    )
    contradiction_text = (
        "\n".join(f"- {finding.description} Why it matters: {finding.why_it_matters}" for finding in contradictions)
        if contradictions
        else "- No material cross-document contradiction was isolated from the current package."
    )
    gating_points = "\n".join(f"- {point}" for point in _build_gating_points(key_risks, missing_items, low_confidence_docs))
    decision_points = "\n".join(f"- {point}" for point in _build_decision_points(key_risks, contradictions, missing_items, low_confidence_docs))
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
        f"Primary risks (deal-shaping):\n{primary_risk_text}\n\n"
        f"Secondary risks (important but not gating):\n{secondary_risk_text}\n\n"
        f"What appears known:\n{known_points}\n\n"
        f"What appears unresolved:\n{unresolved_points}\n\n"
        f"Potential contradictions / tensions:\n{contradiction_text}\n\n"
        f"Gating issues:\n{gating_points}\n\n"
        f"What matters most for the acquisition decision:\n{decision_points}"
        f"{limitation_text}{extraction_text}"
    ).strip()


def _build_aggregate_risk(
    category: str,
    ranked_entries: list[tuple[DocumentAnalysis, RiskFinding]],
) -> tuple[int, RiskFinding] | None:
    focused_entries = [entry for entry in ranked_entries if category in entry[0].focus_areas] or ranked_entries
    lead_analysis, lead_risk = focused_entries[0]
    source_documents: list[str] = []
    citations: list[Citation] = []
    evidence: list[str] = []
    evidence_text_parts: list[str] = []
    low_confidence_sources = 0

    for analysis, risk in focused_entries:
        source_documents.append(analysis.document.title)
        if analysis.confidence == "low":
            low_confidence_sources += 1
        for index, snippet in enumerate(risk.evidence[:1]):
            clipped = clip_text(snippet, 220)
            citation = risk.citations[index] if index < len(risk.citations) else Citation(
                document_name=analysis.document.title,
                chunk_id="chunk-0001",
                page_number=None,
            )
            citations.append(citation)
            evidence.append(_format_evidence_with_citation(clipped, citation))
            evidence_text_parts.append(clipped)
        if len(evidence) >= 3:
            break

    evidence_text = " ".join(evidence_text_parts).lower()
    decision_score = _decision_score(category, evidence_text, lead_risk.severity, low_confidence_sources)
    if not _should_include_aggregate(category, lead_risk.severity, decision_score):
        return None

    anchor = _build_anchor_text(category, lead_analysis)
    issue = _build_issue_text(category, anchor, evidence_text, low_confidence_sources)
    why_it_matters = _build_why_it_matters_text(category, anchor, evidence_text)
    likely_implication = _build_implication_text(category, anchor, evidence_text, low_confidence_sources)
    uncertainty_reason = _build_uncertainty_reason(category, evidence_text, low_confidence_sources, focused_entries)
    gating_flags = list(_RISK_GATING_MAP.get(category, ("Underwriting confidence",)))

    summary_parts = [issue, why_it_matters, f"Likely implication: {likely_implication}"]
    if uncertainty_reason:
        summary_parts.append(f"Remaining uncertainty: {uncertainty_reason}")
    summary = " ".join(summary_parts)

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
            anchor=anchor,
            gating_flags=gating_flags,
            uncertainty_reason=uncertainty_reason,
            citations=_unique_citations(citations)[:3],
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
    anchor: str,
    evidence_text: str,
    low_confidence_sources: int,
) -> str:
    if category == "Title / Access Concerns":
        return f"{anchor} lists easement, encroachment, access, or survey exceptions that need to be reconciled against the current plan set before closing."
    if category == "Entitlement Status":
        return f"{anchor} shows the core approvals are advanced, but the conditions of approval still leave permit-stage obligations open."
    if category == "Geotechnical Risks":
        return f"{anchor} identifies liquefaction, settlement, grading, or foundation recommendations that need to be carried into design and budget assumptions."
    if category == "Flood / Drainage Issues":
        return f"{anchor} drives drainage, detention, and flood-control assumptions that still affect civil scope and the permit path."
    if category == "Fee / Exaction Burden":
        return f"{anchor} shows a meaningful public-works and impact-fee load that still needs to be locked into land basis."
    if category == "Offsite Obligations":
        return f"{anchor} leaves frontage, dedication, permit, or offsite improvement scope with the project rather than fully closed out."
    if category == "Budget / Cost Reliability":
        if low_confidence_sources:
            return f"{anchor} is unreadable or incomplete, so site-development pricing cannot yet be treated as decision-grade."
        return f"{anchor} still reads as budgetary pricing rather than a fully auditable site-cost package."
    if category == "Utilities / Infrastructure Issues":
        return f"{anchor} leaves service, capacity, or joint-trench scope dependent on assumptions that still need direct confirmation."
    if category == "Environmental Risks":
        if any(_keyword_present(evidence_text, term) for term in ("recognized environmental condition", "phase ii", "contamination", "remediation")):
            return f"{anchor} identifies environmental follow-up rather than a clean closeout."
        if any(_keyword_present(evidence_text, term) for term in ("wetlands", "mitigation", "habitat", "hazardous")):
            return f"{anchor} leaves mitigation, compliance, or agency-coordination items open in the execution path."
        return f"{anchor} is not a clean environmental closeout, and the extracted text does not resolve the remaining follow-up scope."
    if category == "Schedule Risks":
        return f"{anchor} leaves timing exposure on the path from current approvals to a fully executable development program."
    return f"{anchor} is material to the acquisition decision."


def _build_why_it_matters_text(category: str, anchor: str, evidence_text: str) -> str:
    if category == "Title / Access Concerns":
        return "This goes directly to closability, lenderability, and whether the approved site plan can actually be built as shown."
    if category == "Entitlement Status":
        return "Approved land use actions do not de-risk the deal if permit-stage conditions, dedications, and implementation triggers are still open."
    if category == "Geotechnical Risks":
        return "Soils recommendations flow straight into grading quantities, retaining, foundation design, contingency, and sometimes yield."
    if category == "Flood / Drainage Issues":
        return "Drainage scope affects both engineering cost and how quickly the project can clear civil and public-works review."
    if category == "Fee / Exaction Burden":
        return "Fee exposure moves directly into land basis and can reset the deal if underwriting is using stale assumptions."
    if category == "Offsite Obligations":
        return "Uncleared frontage and offsite work add real dollars before vertical construction and can hold up permit release."
    if category == "Budget / Cost Reliability":
        return "Acquisition underwriting is not reliable when a meaningful part of the site-cost package cannot be audited back to readable support."
    if category == "Utilities / Infrastructure Issues":
        return "Utility assumptions govern first permits, underground scope, and whether offsite infrastructure cost is still hiding outside the budget."
    if category == "Environmental Risks":
        if any(_keyword_present(evidence_text, term) for term in ("recognized environmental condition", "phase ii", "contamination", "remediation")):
            return "Environmental follow-up creates direct diligence scope, consultant cost, and potential closing or agency conditions."
        return "Environmental and habitat follow-up can still affect mitigation scope, agency timing, and execution certainty."
    if category == "Schedule Risks":
        return "Schedule drift changes carry, fee timing, and the window for locking approvals and bids."
    return "It has direct implications for acquisition underwriting and execution."


def _build_implication_text(category: str, anchor: str, evidence_text: str, low_confidence_sources: int) -> str:
    if category == "Title / Access Concerns":
        return "Closing should not be treated as clean until each title and access item is cured, endorsed, or designed around."
    if category == "Entitlement Status":
        return "Permit timing and vertical start should be treated as conditional until the remaining approval items are closed."
    if category == "Geotechnical Risks":
        return "Expect pressure on grading, retaining, foundation scope, and contingency."
    if category == "Flood / Drainage Issues":
        return "Expect further civil iteration and potential permit drag until the drainage assumptions are fully locked."
    if category == "Fee / Exaction Burden":
        return "Land basis remains exposed to fee movement until the city-confirmed fee stack is locked."
    if category == "Offsite Obligations":
        return "Basis is exposed to additional frontage and offsite cost, and vertical timing remains open until the obligation list is closed."
    if category == "Budget / Cost Reliability":
        if low_confidence_sources:
            return "Current site cost numbers should be treated as provisional, not final underwriting support."
        return "Cost certainty remains weak until budgetary pricing is replaced with auditable bids or clearly bounded assumptions."
    if category == "Utilities / Infrastructure Issues":
        return "Service timing and underground or offsite infrastructure cost remain open."
    if category == "Environmental Risks":
        if any(_keyword_present(evidence_text, term) for term in ("recognized environmental condition", "phase ii", "contamination", "remediation")):
            return "Buyer diligence scope, mitigation cost, and agency signoff remain open."
        return "Execution still depends on clearing environmental or habitat follow-up without adding new mitigation scope."
    if category == "Schedule Risks":
        return "Hold period exposure increases if the current approval and permit path slips."
    return "Acquisition risk requiring direct verification."


def _build_anchor_text(category: str, analysis: DocumentAnalysis) -> str:
    document = analysis.document
    title = document.title
    title_lower = title.lower()
    path_text = document.relative_path.as_posix().lower()

    if category == "Title / Access Concerns":
        if "survey" in path_text or "survey" in title_lower:
            return f"The survey file ({title})"
        return f"The preliminary title report ({title})" if "title" in title_lower or "prelim" in title_lower else f"The title file ({title})"
    if category == "Environmental Risks":
        if "phase i" in title_lower or "phase i" in path_text:
            return f"The Phase I ESA ({title})"
        if "phase ii" in title_lower or "phase ii" in path_text:
            return f"The Phase II environmental report ({title})"
        if "habitat" in title_lower or "biological" in title_lower or "mitigation" in title_lower:
            return f"The habitat or biological memo ({title})"
        return f"The environmental report ({title})"
    if category == "Flood / Drainage Issues":
        if "storm water" in title_lower or "stormwater" in title_lower:
            return f"The stormwater control plan ({title})"
        if "drainage" in title_lower:
            return f"The drainage study ({title})"
        return f"The flood or drainage file ({title})"
    if category == "Geotechnical Risks":
        if "pavement" in title_lower:
            return f"The pavement design letter ({title})"
        return f"The geotechnical report ({title})"
    if category == "Offsite Obligations":
        if "condition" in title_lower or "resolution" in title_lower:
            return f"The approval conditions file ({title})"
        if "storm water" in title_lower or "stormwater" in title_lower:
            return f"The stormwater control plan ({title})"
        return f"The offsite obligation file ({title})"
    if category == "Fee / Exaction Burden":
        return f"The fee schedule ({title})"
    if category == "Budget / Cost Reliability":
        return f"The budget or pricing file ({title})"
    if category == "Utilities / Infrastructure Issues":
        if "joint trench" in title_lower:
            return f"The joint-trench file ({title})"
        return f"The utility file ({title})"
    if category == "Entitlement Status":
        if "condition" in title_lower:
            return f"The conditions of approval ({title})"
        if "permit" in title_lower or "plan" in title_lower:
            return f"The design permit plans ({title})"
        if "resolution" in title_lower:
            return f"The entitlement resolution ({title})"
        return f"The entitlement file ({title})"
    if category == "Schedule Risks":
        return f"The approval or permit file ({title})"
    return f"The supporting file ({title})"


def _build_uncertainty_reason(
    category: str,
    evidence_text: str,
    low_confidence_sources: int,
    entries: list[tuple[DocumentAnalysis, RiskFinding]],
) -> str:
    if low_confidence_sources:
        return "At least one supporting file extracted poorly, so the exact scope still needs manual review."
    if category == "Environmental Risks" and not any(
        _keyword_present(evidence_text, term)
        for term in ("recognized environmental condition", "phase ii", "contamination", "remediation", "wetlands", "mitigation", "habitat")
    ):
        return "The extracted environmental text does not clearly distinguish contamination, mitigation, or general compliance follow-up."
    if category == "Flood / Drainage Issues" and not any(
        _keyword_present(evidence_text, term)
        for term in ("stormwater", "drainage", "detention", "offsite drainage", "100-year", "fema")
    ):
        return "The drainage conclusion is driven by plan notes and needs direct civil review to confirm the active scope."
    if category == "Offsite Obligations" and not any(
        _keyword_present(evidence_text, term)
        for term in ("frontage", "dedicated", "offsite", "reimbursement", "encroachment permit", "improvement plan")
    ):
        return "The supporting files do not yet tie the obligation list into one clean buyer-facing scope memo."
    return ""


def _build_negotiation_question(risk: RiskFinding) -> str:
    source_text = ", ".join(risk.source_documents[:2])
    source_hint = _build_question_source_hint(risk)
    if risk.category == "Title / Access Concerns":
        return f"Please mark up {source_text or 'the preliminary title report and survey'} against the current plan set, and identify every exception, easement, encroachment, and access right that must be cured, endorsed, or redesigned before closing.{source_hint}"
    if risk.category == "Entitlement Status":
        return f"Please provide the live conditions-of-approval tracker tied to {source_text or 'the entitlement package'}, and identify every item still open before map recordation, grading permit, building permit, and vertical start.{source_hint}"
    if risk.category == "Geotechnical Risks":
        return f"Please confirm which recommendations in {source_text or 'the geotechnical reports'} are actually driving grading and foundation design, and state whether liquefaction, settlement, overexcavation, and retaining assumptions are fully carried in the site budget.{source_hint}"
    if risk.category == "Flood / Drainage Issues":
        return f"Please reconcile {source_text or 'the stormwater and drainage files'} into a single scope memo identifying every unresolved stormwater, floodplain, detention, and offsite drainage item still affecting permit issuance or civil cost.{source_hint}"
    if risk.category == "Fee / Exaction Burden":
        return f"Please provide the underwriting fee matrix tied to {source_text or 'the fee schedule'}, identify what is city-confirmed versus estimated, and quantify the exposure if permits slip.{source_hint}"
    if risk.category == "Offsite Obligations":
        return f"Please deliver a closing checklist built off {source_text or 'the offsite and approval files'} that identifies every remaining frontage, dedication, permit, guarantee, reimbursement, and offsite improvement obligation, who pays it, and when it hits the schedule.{source_hint}"
    if risk.category == "Budget / Cost Reliability":
        return f"Please break out which site-development numbers in {source_text or 'the current pricing package'} are hard bids versus budgetary allowances, identify the largest open contingencies, and replace any unreadable files with native copies.{source_hint}"
    if risk.category == "Utilities / Infrastructure Issues":
        return f"Please reconcile {source_text or 'the utility files'} into a utility status memo stating all will-serve assumptions, offsite extensions, joint-trench scope, and serving-agency approvals that are not yet in hand.{source_hint}"
    if risk.category == "Environmental Risks":
        return f"Please use {source_text or 'the environmental package'} to state whether any REC, mitigation obligation, habitat constraint, or agency follow-up item remains open, and identify who bears the cost, schedule, and closing risk.{source_hint}"
    if risk.category == "Schedule Risks":
        return f"Please provide the current critical-path schedule tied back to {source_text or 'the approval package'}, showing remaining approvals, utility releases, offsite triggers, and the assumptions required to hit first permit and vertical-start dates.{source_hint}"
    return f"Please address the current {risk.category.lower()} issue in a form that can be underwritten at closing.{source_hint}"


def _build_question_source_hint(risk: RiskFinding) -> str:
    if not risk.citations:
        return ""
    return f" (Source: {_format_citation_label(risk.citations[0])})"


def _build_contradiction_question(contradiction: ContradictionFinding) -> str:
    source_text = ", ".join(contradiction.source_documents[:2]) or "the current diligence package"
    source_hint = (
        f" (Sources: {', '.join(_format_citation_label(citation) for citation in contradiction.citations[:2])})"
        if contradiction.citations
        else ""
    )
    return (
        f"Please reconcile the tension between {source_text} and confirm which assumption is controlling underwriting, "
        f"scope, and schedule: {contradiction.description}{source_hint}"
    )


def _detect_offsite_completion_tension(document_analyses: list[DocumentAnalysis]) -> ContradictionFinding | None:
    complete_signal = _find_best_sentence(
        document_analyses,
        include_terms=("already improved", "frontage is already improved", "existing frontage", "already constructed"),
        focus_categories=("Offsite Obligations", "Flood / Drainage Issues"),
        title_terms=("stormwater", "plan", "design permit"),
    )
    unresolved_signal = _find_best_sentence(
        document_analyses,
        include_terms=("shall confirm", "confirm if", "frontage", "dedicated", "improvement plan stage"),
        focus_categories=("Offsite Obligations", "Entitlement Status"),
        title_terms=("condition", "exhibit b", "subdivision", "resolution"),
        exclude_document_names={complete_signal[2].document.title} if complete_signal is not None else None,
    )
    if complete_signal is None or unresolved_signal is None:
        return None

    return ContradictionFinding(
        description=(
            f"{_format_citation_label(complete_signal[1])} treats frontage or offsite work as already improved, "
            f"but {_format_citation_label(unresolved_signal[1])} still carries open dedication or frontage obligations."
        ),
        why_it_matters="That tension keeps offsite scope, cost allocation, and the vertical-start path open instead of fully closed.",
        citations=_unique_citations([complete_signal[1], unresolved_signal[1]]),
        source_documents=unique_preserve_order([complete_signal[2].document.title, unresolved_signal[2].document.title]),
        related_categories=["Offsite Obligations", "Entitlement Status", "Flood / Drainage Issues"],
        priority=100,
    )


def _detect_title_vs_plan_tension(
    document_analyses: list[DocumentAnalysis],
    key_risks: list[RiskFinding],
) -> ContradictionFinding | None:
    title_risk = _risk_by_category(key_risks, "Title / Access Concerns")
    if title_risk is None or not title_risk.citations:
        return None

    title_citation = title_risk.citations[0]
    plan_signal = _find_best_sentence(
        document_analyses,
        include_terms=("project entry", "private access", "vehicular project entry", "access", "entry located"),
        focus_categories=("Entitlement Status", "Offsite Obligations"),
        title_terms=("plan", "design permit"),
        exclude_document_names={title_citation.document_name},
    )
    if plan_signal is None:
        return None

    return ContradictionFinding(
        description=(
            f"{_format_citation_label(plan_signal[1])} assumes the current access and entry layout works as designed, "
            f"but {_format_citation_label(title_citation)} still carries title or access exceptions that are not reconciled to that layout."
        ),
        why_it_matters="If the plan relies on access rights that are not cleared in title, the issue goes directly to closability, lenderability, and buildability.",
        citations=_unique_citations([plan_signal[1], title_citation]),
        source_documents=unique_preserve_order([plan_signal[2].document.title, title_citation.document_name]),
        related_categories=["Title / Access Concerns", "Entitlement Status", "Offsite Obligations"],
        priority=95,
    )


def _detect_entitlement_vs_condition_tension(document_analyses: list[DocumentAnalysis]) -> ContradictionFinding | None:
    approval_signal = _find_best_sentence(
        document_analyses,
        include_terms=("approved", "adopted", "approved by the city council", "planning commission", "city council"),
        focus_categories=("Entitlement Status",),
        title_terms=("resolution", "city council", "design permit", "map"),
    )
    condition_signal = _find_best_sentence(
        document_analyses,
        include_terms=("condition of approval", "prior to", "shall", "must", "confirm"),
        focus_categories=("Entitlement Status", "Offsite Obligations"),
        title_terms=("condition", "exhibit a", "exhibit b"),
        exclude_document_names={approval_signal[2].document.title} if approval_signal is not None else None,
    )
    if approval_signal is None or condition_signal is None:
        return None

    return ContradictionFinding(
        description=(
            f"{_format_citation_label(approval_signal[1])} shows approvals are in place, "
            f"but {_format_citation_label(condition_signal[1])} still carries permit-stage or implementation obligations."
        ),
        why_it_matters="That tension means approval status alone does not make the project execution-ready; permit timing and entitlement certainty still depend on clearing the remaining conditions.",
        citations=_unique_citations([approval_signal[1], condition_signal[1]]),
        source_documents=unique_preserve_order([approval_signal[2].document.title, condition_signal[2].document.title]),
        related_categories=["Entitlement Status", "Schedule Risks", "Offsite Obligations"],
        priority=85,
    )


def _detect_geotech_vs_budget_tension(
    document_analyses: list[DocumentAnalysis],
    key_risks: list[RiskFinding],
    missing_items: list[str],
) -> ContradictionFinding | None:
    geotech_risk = _risk_by_category(key_risks, "Geotechnical Risks")
    if geotech_risk is None or not geotech_risk.citations:
        return None

    budget_signal = _find_best_sentence(
        document_analyses,
        include_terms=("budgetary", "allowance", "proposal", "preliminary", "pricing"),
        focus_categories=("Budget / Cost Reliability",),
        title_terms=("budget", "pricing", "bid"),
    )
    budget_document = _find_budget_support_gap(document_analyses, missing_items)
    if budget_signal is None and budget_document is None:
        return None

    if budget_signal is not None:
        budget_citation = budget_signal[1]
        budget_document_name = budget_signal[2].document.title
    else:
        budget_citation = Citation(document_name=budget_document.document.title, chunk_id="document", page_number=None)
        budget_document_name = budget_document.document.title

    return ContradictionFinding(
        description=(
            f"{_format_citation_label(geotech_risk.citations[0])} identifies soils-driven scope, "
            f"but {_format_citation_label(budget_citation)} does not show that scope as fully carried into the current cost package."
        ),
        why_it_matters="That disconnect weakens land-basis confidence and raises the risk that grading, retaining, or foundation costs move after deal approval.",
        citations=_unique_citations([geotech_risk.citations[0], budget_citation]),
        source_documents=unique_preserve_order([geotech_risk.citations[0].document_name, budget_document_name]),
        related_categories=["Geotechnical Risks", "Budget / Cost Reliability"],
        priority=90,
    )


def _risk_by_category(key_risks: list[RiskFinding], category: str) -> RiskFinding | None:
    return next((risk for risk in key_risks if risk.category == category), None)


def _find_budget_support_gap(
    document_analyses: list[DocumentAnalysis],
    missing_items: list[str],
) -> DocumentAnalysis | None:
    budget_analyses = [
        analysis
        for analysis in document_analyses
        if "Budget / Cost Reliability" in analysis.focus_areas
    ]
    for analysis in budget_analyses:
        if analysis.confidence == "low":
            return analysis
        text_lower = analysis.document.normalized_text.lower()
        if any(term in text_lower for term in ("budgetary", "preliminary", "allowance", "proposal", "pricing")):
            return analysis

    if any("site development budget" in item.lower() for item in missing_items):
        return budget_analyses[0] if budget_analyses else None
    return None


def _find_best_sentence(
    document_analyses: list[DocumentAnalysis],
    *,
    include_terms: tuple[str, ...],
    focus_categories: tuple[str, ...] = (),
    title_terms: tuple[str, ...] = (),
    exclude_document_names: set[str] | None = None,
) -> tuple[str, Citation, DocumentAnalysis] | None:
    exclude_document_names = exclude_document_names or set()
    candidates: list[tuple[int, str, Citation, DocumentAnalysis]] = []

    for analysis in document_analyses:
        if analysis.document.title in exclude_document_names:
            continue

        analysis_categories = set(analysis.focus_areas) | {risk.category for risk in analysis.risks}
        if focus_categories and not any(category in analysis_categories for category in focus_categories):
            continue

        title_text = f"{analysis.document.title} {analysis.document.relative_path.as_posix()}".lower()
        if title_terms and not any(term in title_text for term in title_terms):
            continue

        for sentence, citation in _build_sentence_records(analysis.document):
            cleaned = _clean_sentence(sentence)
            if not _is_substantive_sentence(cleaned):
                continue

            lower_sentence = cleaned.lower()
            if not any(_keyword_present(lower_sentence, term) for term in include_terms):
                continue

            score = _count_keyword_hits(lower_sentence, include_terms) * 3
            score += 2 * sum(term in title_text for term in title_terms)
            score += 2 * sum(category in analysis.focus_areas for category in focus_categories)
            score += 2 if analysis.confidence == "high" else 1 if analysis.confidence == "medium" else 0
            candidates.append((score, cleaned, citation, analysis))

    if not candidates:
        return None

    candidates.sort(
        key=lambda item: (
            -item[0],
            -_CONFIDENCE_RANK[item[3].confidence],
            len(item[1]),
        ),
    )
    _, text, citation, analysis = candidates[0]
    return text, citation, analysis


def _build_top_conclusions(
    key_risks: list[RiskFinding],
    entitlement_status: str,
    missing_items: list[str],
    low_confidence_docs: list[str],
) -> list[str]:
    conclusions: list[str] = []
    primary_risks = [risk for risk in key_risks if risk.priority_tier == "primary"] or key_risks[:_PRIMARY_RISK_COUNT]
    if key_risks:
        for risk in primary_risks[:3]:
            conclusions.append(risk.issue or risk.summary)
    else:
        conclusions.append(entitlement_status)

    if low_confidence_docs:
        conclusions.append("Cost certainty is not fully underwritten because at least one budget document could not be read cleanly.")

    if missing_items:
        conclusions.append(f"Decision-readiness is limited until the package is supplemented with: {', '.join(missing_items[:2])}.")

    return unique_preserve_order(conclusions)[:5]


def _build_known_points(document_analyses: list[DocumentAnalysis], entitlement_status: str) -> list[str]:
    points = [entitlement_status]

    readable_focus_sets = {
        focus
        for analysis in document_analyses
        if analysis.confidence != "low"
        for focus in analysis.focus_areas
    }
    coverage_labels: list[str] = []
    if "Title / Access Concerns" in readable_focus_sets:
        coverage_labels.append("title")
    if "Environmental Risks" in readable_focus_sets:
        coverage_labels.append("environmental")
    if "Geotechnical Risks" in readable_focus_sets:
        coverage_labels.append("geotechnical")
    if "Flood / Drainage Issues" in readable_focus_sets:
        coverage_labels.append("stormwater")
    if "Fee / Exaction Burden" in readable_focus_sets:
        coverage_labels.append("fee")
    if coverage_labels:
        points.append(
            f"The package includes readable {', '.join(coverage_labels[:4])} support, so the remaining issue is closure of open items rather than a total lack of core diligence."
        )

    return unique_preserve_order(points)[:4]


def _build_unresolved_points(
    key_risks: list[RiskFinding],
    contradictions: list[ContradictionFinding],
    missing_items: list[str],
    low_confidence_docs: list[str],
) -> list[str]:
    primary_risks = [risk for risk in key_risks if risk.priority_tier == "primary"] or key_risks[:_PRIMARY_RISK_COUNT]
    points = [risk.issue for risk in primary_risks[:3] if risk.issue]
    points.extend(finding.description for finding in contradictions[:2])
    for risk in primary_risks[:3]:
        if risk.uncertainty_reason:
            points.append(f"{risk.category}: {risk.uncertainty_reason}")
    if low_confidence_docs:
        points.append(f"Low-confidence extraction remains on: {', '.join(low_confidence_docs[:2])}.")
    if missing_items:
        points.append(f"Missing or unsupported diligence items still include: {', '.join(missing_items[:3])}.")
    return unique_preserve_order(points)[:5]


def _build_gating_points(
    key_risks: list[RiskFinding],
    missing_items: list[str],
    low_confidence_docs: list[str],
) -> list[str]:
    points: list[str] = []
    grouped = _group_risks_by_gate(key_risks)

    if grouped["Closing"]:
        actions = "; ".join(_build_gate_action_text(risk) for risk in grouped["Closing"][:2])
        points.append(f"Before closing: {actions}.")
    if grouped["Underwriting confidence"]:
        actions = "; ".join(_build_gate_action_text(risk) for risk in grouped["Underwriting confidence"][:3])
        if low_confidence_docs:
            actions += "; replace unreadable budget or support files"
        points.append(f"Before underwriting confidence: {actions}.")
    if grouped["Vertical start"]:
        actions = "; ".join(_build_gate_action_text(risk) for risk in grouped["Vertical start"][:3])
        points.append(f"Before vertical start: {actions}.")

    if not points and missing_items:
        points.append(f"Before relying on the package: obtain direct support for {', '.join(missing_items[:2])}.")

    return unique_preserve_order(points)[:4]


def _build_decision_points(
    key_risks: list[RiskFinding],
    contradictions: list[ContradictionFinding],
    missing_items: list[str],
    low_confidence_docs: list[str],
) -> list[str]:
    points: list[str] = []
    grouped = _group_risks_by_gate(key_risks)
    if grouped["Closing"]:
        points.append("Treat closing as conditional until the title, access, and other pre-closing land-control issues are expressly cleared.")
    if grouped["Underwriting confidence"]:
        points.append("Treat land basis as provisional until cost, fee, offsite, and other buyer-facing obligations are converted into auditable support.")
    if grouped["Vertical start"]:
        points.append("Treat the vertical-start schedule as conditional until permit-stage, civil, utility, and offsite execution items are closed.")
    if contradictions:
        points.append("Where documents conflict, underwrite to the more conservative assumption until the contradiction is reconciled with direct support.")
    if low_confidence_docs:
        points.append("Do not treat the current cost package as fully decision-grade until unreadable or budgetary files are replaced with native support.")
    if missing_items:
        points.append("Underwriting should remain provisional where required supporting files are still missing or only indirectly referenced.")
    return unique_preserve_order(points)[:5]


def _group_risks_by_gate(key_risks: list[RiskFinding]) -> dict[str, list[RiskFinding]]:
    grouped = {"Closing": [], "Underwriting confidence": [], "Vertical start": []}
    for risk in key_risks:
        for gate in risk.gating_flags:
            if gate in grouped:
                grouped[gate].append(risk)
    return grouped


def _build_gate_action_text(risk: RiskFinding) -> str:
    if risk.category == "Title / Access Concerns":
        return "clear the title and access exceptions against the current plan set"
    if risk.category == "Entitlement Status":
        return "close the remaining approval and permit-stage conditions"
    if risk.category == "Geotechnical Risks":
        return "confirm the active geotechnical recommendations are fully carried into design and budget"
    if risk.category == "Flood / Drainage Issues":
        return "lock the drainage and stormwater scope"
    if risk.category == "Fee / Exaction Burden":
        return "lock the city-confirmed fee stack"
    if risk.category == "Offsite Obligations":
        return "allocate every frontage and offsite obligation into a clean buyer-facing scope"
    if risk.category == "Budget / Cost Reliability":
        return "replace unreadable or budgetary cost support with auditable pricing"
    if risk.category == "Utilities / Infrastructure Issues":
        return "confirm utility capacity, will-serve assumptions, and required offsite utility work"
    if risk.category == "Environmental Risks":
        return "resolve the environmental and mitigation follow-up scope"
    if risk.category == "Schedule Risks":
        return "rebuild the critical path with only confirmed assumptions"
    return f"resolve the current {risk.category.lower()} issue"


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
    ocr_pages = len(document.ocr_pages)
    unrecovered_ocr_pages = max(0, len(document.ocr_pages) - len(document.ocr_recovered_pages))
    page_count = int(document.metadata.get("page_count", 0) or 0)
    text_length = len(document.normalized_text.strip())

    if "no pdf text extracted" in warnings_text or "normalized text is empty" in warnings_text or text_length == 0:
        return "low", "No usable text was extracted from the document."

    if unrecovered_ocr_pages:
        if page_count and (unrecovered_ocr_pages / page_count) >= 0.15:
            return "low", f"{unrecovered_ocr_pages} page(s) out of {page_count} still had no usable text after OCR fallback."
        return "medium", f"{unrecovered_ocr_pages} page(s) still had weak or missing text after OCR fallback."

    if ocr_pages:
        if page_count and (ocr_pages / page_count) >= 0.4:
            return "low", f"OCR fallback was required on {ocr_pages} page(s) out of {page_count}, so the document should be spot-checked manually."
        return "medium", f"OCR fallback was required on {ocr_pages} page(s), so extraction should be spot-checked."

    if text_length < 500:
        return "medium", "Extracted text was limited, so conclusions are directional."

    return "high", "Text extraction was strong with no OCR-related warnings."


def _build_sentence_records(document: DocumentRecord) -> list[tuple[str, Citation]]:
    records: list[tuple[str, Citation]] = []
    if document.chunks:
        for chunk in document.chunks:
            citation = Citation(
                document_name=chunk.document_name,
                chunk_id=chunk.chunk_id,
                page_number=chunk.page_number,
            )
            for sentence in split_sentences(chunk.text):
                records.append((sentence, citation))
        if records:
            return records

    fallback_citation = Citation(
        document_name=document.title,
        chunk_id="chunk-0001",
        page_number=None,
    )
    return [(sentence, fallback_citation) for sentence in split_sentences(document.normalized_text)]


def _collect_evidence(
    *,
    sentence_records: list[tuple[str, Citation]],
    keywords: tuple[str, ...],
    severe_keywords: tuple[str, ...],
) -> list[tuple[str, Citation]]:
    scored_sentences: list[tuple[int, str, Citation]] = []

    for sentence, citation in sentence_records:
        lower_sentence = sentence.lower()
        match_count = _count_keyword_hits(lower_sentence, keywords)
        if not match_count:
            continue

        cleaned = _clean_sentence(sentence)
        if not _is_substantive_sentence(cleaned):
            continue

        severe_count = _count_keyword_hits(lower_sentence, severe_keywords)
        score = (match_count * 3) + (severe_count * 5)
        scored_sentences.append((score, cleaned, citation))

    scored_sentences.sort(key=lambda item: (-item[0], len(item[1])))
    selected: list[tuple[str, Citation]] = []
    seen_sentences: set[str] = set()
    for _, sentence, citation in scored_sentences:
        if sentence in seen_sentences:
            continue
        seen_sentences.add(sentence)
        selected.append((sentence, citation))
        if len(selected) >= 3:
            break
    return selected


def _format_evidence_with_citation(text: str, citation: Citation) -> str:
    return f"{_format_citation_label(citation)}: {text}"


def _unique_citations(citations: list[Citation]) -> list[Citation]:
    ordered: list[Citation] = []
    seen: set[Citation] = set()
    for citation in citations:
        if citation in seen:
            continue
        seen.add(citation)
        ordered.append(citation)
    return ordered


def _format_citation_label(citation: Citation) -> str:
    if citation.page_number is not None:
        return f"{citation.document_name} p. {citation.page_number}"
    return citation.document_name


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
