"""Deterministic acquisition-grade second-pass synthesis."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re

from land_due_diligence_agent.analysis.front_end import (
    deal_impact_mechanism_for_issue,
    deal_impact_type_for_issue,
    fixability_classification_for_issue,
    timing_exposure_band_for_issue,
)
from land_due_diligence_agent.models import (
    AcquisitionControllingFact,
    AcquisitionCriticalPathStep,
    AcquisitionDecision,
    AcquisitionInsight,
    AcquisitionJudgment,
    AcquisitionRiskItem,
    CanonicalIssue,
    CanonicalIssueRegistry,
    Citation,
    ContradictionFinding,
    DocumentRecord,
    ExtractedChunk,
    OmissionAssessment,
    RecommendationDecision,
)
from land_due_diligence_agent.utils.text import clip_text, unique_preserve_order

_FACT_LABELS = {
    "lot_count": "Lot Count",
    "unit_count": "Unit Count",
    "entitlement_status": "Entitlement Status",
    "zoning": "Zoning / Land Use",
    "jurisdiction": "Jurisdiction",
    "owner_name": "Ownership",
}
_CONFIDENCE_RANK = {"low": 1, "medium": 2, "high": 3}
_BUCKET_ORDER = {
    "Deal Killers": 0,
    "Pre-Close Gating Items": 1,
    "Price Adjustments": 2,
    "Execution Risks": 3,
    "Noise": 4,
}
_STAGE_RULES = {
    "Final Map": {
        "terms": (
            "final map",
            "record",
            "recordation",
            "tract map",
            "subdivision map",
            "tentative map",
            "condition",
            "title",
            "easement",
            "vesting",
            "dedication",
            "annexation",
        ),
        "categories": {
            "Title / Access Concerns",
            "Entitlement Status",
            "Offsite Obligations",
            "Utilities / Infrastructure Issues",
        },
        "schedule_classes": {"immediate blocker", "pre-close blocker", "pre-final-map blocker"},
    },
    "Grading Permit": {
        "terms": (
            "grading",
            "geotech",
            "geotechnical",
            "drainage",
            "storm",
            "civil",
            "erosion",
            "improvement plan",
            "utility",
            "public works",
        ),
        "categories": {
            "Geotechnical Risks",
            "Flood / Drainage Issues",
            "Utilities / Infrastructure Issues",
            "Offsite Obligations",
            "Entitlement Status",
        },
        "schedule_classes": {"immediate blocker", "pre-close blocker", "pre-underwriting blocker"},
    },
    "Vertical Start": {
        "terms": (
            "vertical",
            "building permit",
            "foundation",
            "product",
            "unit",
            "lot",
            "utility",
            "offsite",
            "schedule",
            "permit",
        ),
        "categories": {
            "Entitlement Status",
            "Utilities / Infrastructure Issues",
            "Offsite Obligations",
            "Budget / Cost Reliability",
            "Fee / Exaction Burden",
            "Schedule Risks",
        },
        "schedule_classes": {"immediate blocker", "pre-close blocker", "pre-vertical-start blocker"},
    },
}
_DOC_TERMS_BY_FACT = {
    "lot_count": (("tentative map", 4), ("tract", 4), ("map", 3), ("staff report", 3), ("plan", 2), ("approval", 2)),
    "unit_count": (("tentative map", 4), ("staff report", 3), ("design review", 3), ("site plan", 2), ("plan", 2), ("approval", 2)),
    "zoning": (("resolution", 4), ("conditions", 4), ("staff report", 3), ("approval", 3), ("zoning", 3), ("land use", 2), ("general plan", 2)),
    "jurisdiction": (("city of", 4), ("county of", 4), ("staff report", 3), ("title", 2), ("approval", 2)),
    "owner_name": (("vested in", 5), ("title", 4), ("preliminary report", 4), ("commitment", 4), ("fee owner", 4), ("owner", 2)),
    "entitlement_status": (("resolution", 5), ("conditions", 5), ("planning commission", 4), ("city council", 4), ("tentative map", 4), ("approval", 3)),
}
_DOC_NEGATIVE_TERMS = (("summary", -2), ("overview", -2), ("matrix", -2), ("tracker", -1), ("draft", -1))
_COUNT_REJECT_TERMS = ("du/ac", "per acre")
_ZONING_REJECT_TERMS = (
    "approval",
    "condition",
    "conditions",
    "development standards",
    "sheet",
    "setback",
    "setbacks",
)
_OWNER_ENTITY_TERMS = ("llc", "lp", "l.p", "inc", "corp", "corporation", "company", "holdings", "ventures", "properties", "trust")


@dataclass(slots=True, frozen=True)
class _FactCandidate:
    fact_type: str
    value: str
    normalized_value: str
    relative_path: str
    excerpt: str
    page_number: int | None = None
    chunk_id: str = ""
    confidence: str = "medium"
    subtype: str = ""


def build_acquisition_judgment(
    *,
    documents: list[DocumentRecord],
    registry: CanonicalIssueRegistry,
    omission_assessments: list[OmissionAssessment],
    contradictions: list[ContradictionFinding],
    recommendation: RecommendationDecision,
    entitlement_status: str,
) -> AcquisitionJudgment:
    """Build a second-pass IC-ready synthesis from the analyzed deal package."""

    fact_candidates = _extract_control_fact_candidates(documents)
    controlling_facts = _build_controlling_facts(
        fact_candidates=fact_candidates,
        documents=documents,
        contradictions=contradictions,
        entitlement_status=entitlement_status,
    )
    risk_items = _build_risk_items(registry.issues)
    critical_path = _build_critical_path(registry.issues)
    decision = _build_investment_decision(
        risk_items=risk_items,
        omission_assessments=omission_assessments,
        contradictions=contradictions,
        recommendation=recommendation,
    )
    weak_misses = _build_weak_acquisition_misses(
        controlling_facts=controlling_facts,
        risk_items=risk_items,
        omission_assessments=omission_assessments,
        decision=decision,
    )
    return AcquisitionJudgment(
        controlling_facts=controlling_facts,
        risk_items=risk_items,
        critical_path=critical_path,
        investment_decision=decision,
        weak_acquisition_misses=weak_misses,
    )


def _extract_control_fact_candidates(documents: list[DocumentRecord]) -> dict[str, list[_FactCandidate]]:
    candidates: dict[str, list[_FactCandidate]] = {key: [] for key in _FACT_LABELS}
    seen: set[tuple[str, str, str, str, str | None]] = set()
    zoning_candidates: list[_FactCandidate] = []

    for document in documents:
        for chunk in _iter_document_chunks(document):
            text = chunk.text or ""

            for match in re.finditer(r"\b(\d{1,4})\s+(?:single[- ]family\s+)?lots?\b", text, re.IGNORECASE):
                _append_candidate(
                    candidates["lot_count"],
                    seen,
                    _FactCandidate(
                        fact_type="lot_count",
                        value=match.group(1),
                        normalized_value=_normalize_numeric(match.group(1)),
                        relative_path=document.relative_path.as_posix(),
                        excerpt=_excerpt(text, match.start(), match.end()),
                        page_number=chunk.page_number,
                        chunk_id=chunk.chunk_id,
                    ),
                )
            for match in re.finditer(r"\b(?:into|subdivide(?:d)?\s+into)\s+(\d{1,4})\s+(?:parcels?|lots?)\b", text, re.IGNORECASE):
                _append_candidate(
                    candidates["lot_count"],
                    seen,
                    _FactCandidate(
                        fact_type="lot_count",
                        value=match.group(1),
                        normalized_value=_normalize_numeric(match.group(1)),
                        relative_path=document.relative_path.as_posix(),
                        excerpt=_excerpt(text, match.start(), match.end()),
                        page_number=chunk.page_number,
                        chunk_id=chunk.chunk_id,
                    ),
                )

            for match in re.finditer(r"\b(\d{1,5})\s+(?:dwelling\s+)?units?\b", text, re.IGNORECASE):
                excerpt = _excerpt(text, match.start(), match.end())
                if any(term in excerpt.lower() for term in _COUNT_REJECT_TERMS):
                    continue
                _append_candidate(
                    candidates["unit_count"],
                    seen,
                    _FactCandidate(
                        fact_type="unit_count",
                        value=match.group(1),
                        normalized_value=_normalize_numeric(match.group(1)),
                        relative_path=document.relative_path.as_posix(),
                        excerpt=excerpt,
                        page_number=chunk.page_number,
                        chunk_id=chunk.chunk_id,
                    ),
                )
            for match in re.finditer(r"\b(\d{1,5})\s+(?:single[- ]family\s+)?homes?\b", text, re.IGNORECASE):
                excerpt = _excerpt(text, match.start(), match.end())
                if any(term in excerpt.lower() for term in _COUNT_REJECT_TERMS):
                    continue
                _append_candidate(
                    candidates["unit_count"],
                    seen,
                    _FactCandidate(
                        fact_type="unit_count",
                        value=match.group(1),
                        normalized_value=_normalize_numeric(match.group(1)),
                        relative_path=document.relative_path.as_posix(),
                        excerpt=excerpt,
                        page_number=chunk.page_number,
                        chunk_id=chunk.chunk_id,
                    ),
                )

            for match in re.finditer(r"\b(?:current\s+)?zoning(?:\s+designation|\s+district)?\s*(?:is|as|=|:)?\s*([A-Za-z0-9\-/ ()]{2,40}?)(?=[.;,\n]|$)", text, re.IGNORECASE):
                value = _normalize_named_value(match.group(1))
                if _valid_zoning_value(value):
                    zoning_candidates.append(
                        _FactCandidate(
                            fact_type="zoning",
                            value=value,
                            normalized_value=value.lower(),
                            relative_path=document.relative_path.as_posix(),
                            excerpt=_excerpt(text, match.start(), match.end()),
                            page_number=chunk.page_number,
                            chunk_id=chunk.chunk_id,
                            subtype="zoning",
                        )
                    )
            for match in re.finditer(r"\b(?:general\s+plan\s+)?land use(?:\s+designation)?\s*(?:is|as|=|:)?\s*([A-Za-z0-9\-/ ()]{2,50}?)(?=[.;,\n]|$)", text, re.IGNORECASE):
                value = _normalize_named_value(match.group(1))
                if _valid_zoning_value(value):
                    zoning_candidates.append(
                        _FactCandidate(
                            fact_type="zoning",
                            value=value,
                            normalized_value=value.lower(),
                            relative_path=document.relative_path.as_posix(),
                            excerpt=_excerpt(text, match.start(), match.end()),
                            page_number=chunk.page_number,
                            chunk_id=chunk.chunk_id,
                            subtype="land_use",
                        )
                    )

            for match in re.finditer(r"\bCity of\s+([A-Z][A-Za-z .-]{2,40})", text):
                value = _normalize_named_value(match.group(1))
                _append_candidate(
                    candidates["jurisdiction"],
                    seen,
                    _FactCandidate(
                        fact_type="jurisdiction",
                        value=value,
                        normalized_value=value.lower(),
                        relative_path=document.relative_path.as_posix(),
                        excerpt=_excerpt(text, match.start(), match.end()),
                        page_number=chunk.page_number,
                        chunk_id=chunk.chunk_id,
                        confidence="high",
                    ),
                )

            for match in re.finditer(r"\bvested in\s*:?\s*([A-Z][A-Za-z0-9 ,.()&-]{3,100}?)(?=[.;\n]|$)", text):
                value = _normalize_named_value(match.group(1))
                if _looks_like_entity_name(value):
                    _append_candidate(
                        candidates["owner_name"],
                        seen,
                        _FactCandidate(
                            fact_type="owner_name",
                            value=value,
                            normalized_value=value.lower(),
                            relative_path=document.relative_path.as_posix(),
                            excerpt=_excerpt(text, match.start(), match.end()),
                            page_number=chunk.page_number,
                            chunk_id=chunk.chunk_id,
                            confidence="high",
                        ),
                    )
            for match in re.finditer(r"\b(?:fee owner|record owner|owner)\s*(?:is|:)?\s*([A-Z][A-Za-z0-9 ,.()&-]{3,100}?)(?=[.;\n]|$)", text, re.IGNORECASE):
                value = _normalize_named_value(match.group(1))
                if _looks_like_entity_name(value):
                    _append_candidate(
                        candidates["owner_name"],
                        seen,
                        _FactCandidate(
                            fact_type="owner_name",
                            value=value,
                            normalized_value=value.lower(),
                            relative_path=document.relative_path.as_posix(),
                            excerpt=_excerpt(text, match.start(), match.end()),
                            page_number=chunk.page_number,
                            chunk_id=chunk.chunk_id,
                        ),
                    )

    candidates["zoning"] = _dedupe_candidates(zoning_candidates)
    return candidates


def _build_controlling_facts(
    *,
    fact_candidates: dict[str, list[_FactCandidate]],
    documents: list[DocumentRecord],
    contradictions: list[ContradictionFinding],
    entitlement_status: str,
) -> list[AcquisitionControllingFact]:
    controlling = [
        _build_standard_controlling_fact("lot_count", fact_candidates.get("lot_count", [])),
        _build_standard_controlling_fact("unit_count", fact_candidates.get("unit_count", [])),
        _build_entitlement_controlling_fact(
            documents=documents,
            contradictions=contradictions,
            entitlement_status=entitlement_status,
        ),
        _build_zoning_controlling_fact(fact_candidates.get("zoning", [])),
        _build_standard_controlling_fact("jurisdiction", fact_candidates.get("jurisdiction", [])),
        _build_standard_controlling_fact("owner_name", fact_candidates.get("owner_name", [])),
    ]
    return controlling


def _build_standard_controlling_fact(fact_type: str, candidates: list[_FactCandidate]) -> AcquisitionControllingFact:
    label = _FACT_LABELS[fact_type]
    if not candidates:
        return AcquisitionControllingFact(
            fact_type=fact_type,
            label=label,
            controlling_value="Not cleanly established from the current readable package.",
            controlling_document="No controlling source isolated",
            why_it_controls="No medium- or high-confidence candidate was extracted strongly enough to adjudicate this lane.",
        )

    support_counts = _support_counts(candidates)
    chosen = sorted(candidates, key=lambda item: _fact_sort_key(fact_type, item, support_counts))[0]
    rejected = [
        f"{candidate.value} ({_source_label(candidate.relative_path, candidate.page_number)})"
        for candidate in candidates
        if candidate.normalized_value != chosen.normalized_value
    ]
    return AcquisitionControllingFact(
        fact_type=fact_type,
        label=label,
        controlling_value=_format_fact_value(fact_type, chosen.value),
        controlling_document=_source_label(chosen.relative_path, chosen.page_number),
        why_it_controls=_why_fact_controls(fact_type, chosen, support_counts.get(chosen.normalized_value, 1)),
        rejected_alternatives=unique_preserve_order(rejected)[:4],
        citations=[_citation_from_candidate(chosen)],
    )


def _build_zoning_controlling_fact(candidates: list[_FactCandidate]) -> AcquisitionControllingFact:
    if not candidates:
        return AcquisitionControllingFact(
            fact_type="zoning",
            label=_FACT_LABELS["zoning"],
            controlling_value="Zoning / land use is not cleanly established from the current readable package.",
            controlling_document="No controlling source isolated",
            why_it_controls="The package does not contain a clean zoning or land-use reference strong enough to control underwriting.",
        )

    support_counts = _support_counts(candidates)
    zoning_candidates = [candidate for candidate in candidates if candidate.subtype == "zoning"] or candidates
    land_use_candidates = [candidate for candidate in candidates if candidate.subtype == "land_use"]
    chosen_zoning = sorted(zoning_candidates, key=lambda item: _fact_sort_key("zoning", item, support_counts))[0]
    controlling_value = chosen_zoning.value
    citations = [_citation_from_candidate(chosen_zoning)]
    controlling_document = _source_label(chosen_zoning.relative_path, chosen_zoning.page_number)

    if land_use_candidates:
        chosen_land_use = sorted(land_use_candidates, key=lambda item: _fact_sort_key("zoning", item, support_counts))[0]
        if chosen_land_use.normalized_value != chosen_zoning.normalized_value:
            controlling_value = f"{chosen_zoning.value}; land use {chosen_land_use.value}"
            citations.append(_citation_from_candidate(chosen_land_use))

    rejected = [
        f"{candidate.value} ({_source_label(candidate.relative_path, candidate.page_number)})"
        for candidate in candidates
        if candidate.normalized_value != chosen_zoning.normalized_value
    ]
    return AcquisitionControllingFact(
        fact_type="zoning",
        label=_FACT_LABELS["zoning"],
        controlling_value=controlling_value,
        controlling_document=controlling_document,
        why_it_controls=_why_fact_controls("zoning", chosen_zoning, support_counts.get(chosen_zoning.normalized_value, 1)),
        rejected_alternatives=unique_preserve_order(rejected)[:4],
        citations=_dedupe_citations(citations)[:3],
    )


def _build_entitlement_controlling_fact(
    *,
    documents: list[DocumentRecord],
    contradictions: list[ContradictionFinding],
    entitlement_status: str,
) -> AcquisitionControllingFact:
    candidates = [document for document in documents if _document_is_entitlement_relevant(document)]
    chosen = sorted(candidates, key=_entitlement_document_sort_key)[0] if candidates else None
    controlling_document = _document_label(chosen) if chosen is not None else "No controlling source isolated"
    controlling_value = entitlement_status.strip() or "Entitlement status is not clearly established from the current readable package."

    if chosen is not None:
        lowered = chosen.normalized_text.lower()
        if any(term in lowered for term in ("rezoning required", "variance required", "not approved", "appeal")):
            controlling_value = "Discretionary entitlement still appears open; the current package does not show a fully approved executable entitlement path."
        elif any(term in lowered for term in ("tentative map", "planning commission", "approved", "resolution")) and any(
            term in lowered for term in ("conditions of approval", "prior to final map", "prior to grading permit", "condition of approval")
        ):
            controlling_value = "Approvals appear in place, but execution still runs through condition closeout before final map and permit release."
        elif any(term in lowered for term in ("approved", "resolution", "planning commission")):
            controlling_value = "Readable approval support shows an approved entitlement path, subject to normal implementation steps."

    rejected = [
        clip_text(finding.description, 140)
        for finding in contradictions
        if "Entitlement Status" in finding.related_categories
    ]
    citations = [_citation_for_entitlement_document(chosen)] if chosen is not None else []
    why_controls = (
        f"{controlling_document} controls because official approval and condition documents outrank downstream summaries or narrative references in the entitlement lane."
        if chosen is not None
        else "No official approval or condition document was isolated strongly enough to control this lane."
    )
    return AcquisitionControllingFact(
        fact_type="entitlement_status",
        label=_FACT_LABELS["entitlement_status"],
        controlling_value=controlling_value,
        controlling_document=controlling_document,
        why_it_controls=why_controls,
        rejected_alternatives=unique_preserve_order(rejected)[:4],
        citations=citations,
    )


def _build_risk_items(issues: list[CanonicalIssue]) -> list[AcquisitionRiskItem]:
    ranked = sorted(
        issues,
        key=lambda issue: (
            _BUCKET_ORDER.get(_bucket_for_issue(issue), 9),
            0 if issue.acquisition_severity == "CRITICAL" else 1 if issue.acquisition_severity == "HIGH" else 2,
            0 if issue.blocking_flag else 1,
            -issue.priority_score.total,
            issue.title.lower(),
        ),
    )
    items: list[AcquisitionRiskItem] = []
    for issue in ranked:
        items.append(
            AcquisitionRiskItem(
                bucket=_bucket_for_issue(issue),
                title=issue.title,
                summary=clip_text(
                    deal_impact_mechanism_for_issue(issue)
                    or issue.practical_impact
                    or issue.likely_implication
                    or issue.why_it_matters
                    or issue.title,
                    200,
                ),
                impact=deal_impact_type_for_issue(issue),
                timing=issue.schedule_impact_classification or timing_exposure_band_for_issue(issue),
                curability=fixability_classification_for_issue(issue),
                issue_id=issue.issue_id,
                citations=issue.citations[:3],
                source_documents=issue.source_documents[:3],
            )
        )
    return items


def _bucket_for_issue(issue: CanonicalIssue) -> str:
    if issue.decision_action == "treat as fatal" or (
        issue.acquisition_severity == "CRITICAL"
        and issue.blocking_flag
        and issue.fixability == "low"
    ):
        return "Deal Killers"
    if issue.blocking_flag or issue.gating_item or issue.schedule_impact_classification in {
        "immediate blocker",
        "pre-close blocker",
        "pre-underwriting blocker",
        "pre-final-map blocker",
        "pre-vertical-start blocker",
    }:
        return "Pre-Close Gating Items"
    if issue.decision_action in {"reprice", "restructure"} or deal_impact_type_for_issue(issue) in {"price", "construction cost"} or issue.category in {
        "Budget / Cost Reliability",
        "Fee / Exaction Burden",
    }:
        return "Price Adjustments"
    if not issue.decision_relevant or (
        issue.front_end_flag == "routine item"
        and not issue.blocking_flag
        and issue.acquisition_severity == "LOW"
    ):
        return "Noise"
    return "Execution Risks"


def _build_critical_path(issues: list[CanonicalIssue]) -> list[AcquisitionCriticalPathStep]:
    ranked = sorted(
        issues,
        key=lambda issue: (
            0 if issue.blocking_flag else 1,
            0 if issue.critical_path_flag else 1,
            -issue.priority_score.total,
            issue.title.lower(),
        ),
    )
    steps: list[AcquisitionCriticalPathStep] = []
    for target, rule in _STAGE_RULES.items():
        candidates = [issue for issue in ranked if _stage_match_score(issue, rule) > 0]
        selected = candidates[:3] if candidates else ranked[:2]
        for index, issue in enumerate(selected, start=1):
            steps.append(
                AcquisitionCriticalPathStep(
                    target=target,
                    sequence=index,
                    blocker=issue.title,
                    why_it_blocks=clip_text(
                        issue.blocking_reason
                        or issue.critical_path_reason
                        or issue.likely_schedule_effect
                        or issue.practical_impact
                        or issue.likely_implication
                        or issue.why_it_matters,
                        200,
                    ),
                    issue_id=issue.issue_id,
                    citations=issue.citations[:3],
                    source_documents=issue.source_documents[:3],
                )
            )
    return steps


def _build_investment_decision(
    *,
    risk_items: list[AcquisitionRiskItem],
    omission_assessments: list[OmissionAssessment],
    contradictions: list[ContradictionFinding],
    recommendation: RecommendationDecision,
) -> AcquisitionDecision:
    non_noise = [item for item in risk_items if item.bucket != "Noise"]
    gating = [item for item in risk_items if item.bucket == "Pre-Close Gating Items"]
    killers = [item for item in risk_items if item.bucket == "Deal Killers"]

    posture = _normalize_posture(recommendation.posture)
    if killers:
        posture = "Do Not Advance"
    elif gating or _material_unknowns(omission_assessments) or contradictions:
        posture = "Advance Only If"
    elif posture == "Advance Only If" and not (gating or _material_unknowns(omission_assessments) or contradictions):
        posture = "Advance"

    biggest_unknown_text, biggest_unknown_citations = _biggest_unknown(omission_assessments, contradictions)
    top_real_risks = [
        f"{item.title}: {clip_text(item.summary, 140)}"
        for item in non_noise[:3]
    ]
    price_or_structure_changes = _price_or_structure_lines(risk_items, omission_assessments)
    rationale = " ".join(top_real_risks[:2]) if top_real_risks else (recommendation.rationale or "No decisive non-routine risk currently controls the deal.")
    citations = _dedupe_citations(biggest_unknown_citations + [citation for item in non_noise[:2] for citation in item.citations])[:3]
    return AcquisitionDecision(
        posture=posture,
        rationale=clip_text(rationale, 220),
        top_real_risks=top_real_risks,
        price_or_structure_changes=price_or_structure_changes,
        biggest_unknown=biggest_unknown_text,
        citations=citations,
    )


def _build_weak_acquisition_misses(
    *,
    controlling_facts: list[AcquisitionControllingFact],
    risk_items: list[AcquisitionRiskItem],
    omission_assessments: list[OmissionAssessment],
    decision: AcquisitionDecision,
) -> list[AcquisitionInsight]:
    insights: list[AcquisitionInsight] = []

    for fact in controlling_facts:
        if fact.rejected_alternatives:
            insights.append(
                AcquisitionInsight(
                    title=f"Do not underwrite {fact.label.lower()} as a range",
                    detail=clip_text(
                        f"Use {fact.controlling_value} from {fact.controlling_document}. Reject {', '.join(fact.rejected_alternatives[:2])} as non-controlling references.",
                        220,
                    ),
                    citations=fact.citations[:3],
                )
            )
            break

    top_gating = next((item for item in risk_items if item.bucket == "Pre-Close Gating Items"), None)
    if top_gating is not None:
        insights.append(
            AcquisitionInsight(
                title="Approved is not the same as executable",
                detail=clip_text(
                    f"{top_gating.title} still sits on the closing, map, or permit path. Treat it as a gating condition, not routine post-close cleanup.",
                    220,
                ),
                citations=top_gating.citations[:3],
                source_documents=top_gating.source_documents[:3],
            )
        )

    top_price = next((item for item in risk_items if item.bucket == "Price Adjustments"), None)
    if top_price is not None:
        insights.append(
            AcquisitionInsight(
                title="Basis exposure is hiding in the technical lane",
                detail=clip_text(
                    f"{top_price.title} should move price, seller paper, or contingency. It is not just an execution note for after closing.",
                    220,
                ),
                citations=top_price.citations[:3],
                source_documents=top_price.source_documents[:3],
            )
        )

    if decision.biggest_unknown:
        insights.append(
            AcquisitionInsight(
                title="The most dangerous blind spot is the missing control document",
                detail=clip_text(decision.biggest_unknown, 220),
                citations=decision.citations[:3],
            )
        )

    if len(insights) < 3:
        for assessment in omission_assessments:
            if assessment.front_end_status not in {"missing and important", "conflicting across documents", "stale and potentially unreliable"}:
                continue
            insights.append(
                AcquisitionInsight(
                    title=f"{assessment.item} is a deal signal, not memo housekeeping",
                    detail=clip_text(assessment.front_end_reason or assessment.rationale, 220),
                    citations=assessment.citations[:3],
                    source_documents=assessment.source_documents[:3],
                )
            )
            if len(insights) >= 3:
                break

    unique: list[AcquisitionInsight] = []
    seen: set[str] = set()
    for insight in insights:
        key = insight.title.strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(insight)
        if len(unique) >= 3:
            break
    return unique


def _iter_document_chunks(document: DocumentRecord) -> list[ExtractedChunk]:
    if document.chunks:
        return document.chunks
    text = document.normalized_text or document.raw_text
    if not text:
        return []
    return [
        ExtractedChunk(
            document_name=document.title,
            chunk_id=f"synthetic-{Path(document.relative_path).stem or 'chunk'}",
            text=text,
            page_number=None,
        )
    ]


def _append_candidate(items: list[_FactCandidate], seen: set[tuple[str, str, str, str, str | None]], candidate: _FactCandidate) -> None:
    dedupe_key = (
        candidate.fact_type,
        candidate.normalized_value,
        candidate.relative_path,
        candidate.chunk_id,
        str(candidate.page_number),
    )
    if dedupe_key in seen:
        return
    seen.add(dedupe_key)
    items.append(candidate)


def _dedupe_candidates(items: list[_FactCandidate]) -> list[_FactCandidate]:
    deduped: list[_FactCandidate] = []
    seen: set[tuple[str, str, str, str | None, str]] = set()
    for item in items:
        key = (item.fact_type, item.normalized_value, item.relative_path, str(item.page_number), item.subtype)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def _support_counts(candidates: list[_FactCandidate]) -> dict[str, int]:
    counts: dict[str, set[str]] = {}
    for candidate in candidates:
        counts.setdefault(candidate.normalized_value, set()).add(candidate.relative_path)
    return {key: len(paths) for key, paths in counts.items()}


def _fact_sort_key(fact_type: str, candidate: _FactCandidate, support_counts: dict[str, int]) -> tuple[int, int, int, str]:
    return (
        -_CONFIDENCE_RANK.get(candidate.confidence, 2),
        -_authority_score(fact_type, candidate),
        -support_counts.get(candidate.normalized_value, 1),
        candidate.value.lower(),
    )


def _authority_score(fact_type: str, candidate: _FactCandidate) -> int:
    haystack = f"{Path(candidate.relative_path).name.lower()} {candidate.excerpt.lower()}"
    score = 0
    for term, weight in _DOC_TERMS_BY_FACT.get(fact_type, ()):
        if term in haystack:
            score += weight
    for term, weight in _DOC_NEGATIVE_TERMS:
        if term in haystack:
            score += weight
    return score


def _why_fact_controls(fact_type: str, candidate: _FactCandidate, support_count: int) -> str:
    document_label = _source_label(candidate.relative_path, candidate.page_number)
    reasons = [f"{document_label} is the highest-authority readable source in this lane"]
    if support_count > 1:
        reasons.append(f"{support_count} readable sources repeat the same value")
    if candidate.confidence == "high":
        reasons.append("the extracted reference is strong enough to treat as controlling")
    return clip_text("; ".join(reasons) + ".", 220)


def _format_fact_value(fact_type: str, value: str) -> str:
    if fact_type == "lot_count":
        return f"{value} lots"
    if fact_type == "unit_count":
        return f"{value} units"
    return value


def _normalize_numeric(value: str) -> str:
    match = re.search(r"\d+(?:\.\d+)?", value)
    if match is None:
        return value.strip().lower()
    parsed = float(match.group(0))
    return str(int(parsed)) if parsed.is_integer() else f"{parsed:.2f}".rstrip("0").rstrip(".")


def _normalize_named_value(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip(" .;,:\"'")


def _valid_zoning_value(value: str) -> bool:
    lowered = value.lower()
    if not lowered or any(term in lowered for term in _ZONING_REJECT_TERMS):
        return False
    if len(lowered.split()) > 7:
        return False
    return any(character.isalpha() for character in lowered)


def _looks_like_entity_name(value: str) -> bool:
    lowered = value.lower()
    tokens = [token for token in re.split(r"[ ,()&/-]+", value) if token]
    if len(tokens) < 2:
        return False
    if any(term in lowered for term in _OWNER_ENTITY_TERMS):
        return True
    capitalized = sum(token[:1].isupper() for token in tokens if token[:1].isalpha())
    return capitalized >= max(2, len(tokens) - 1)


def _source_label(relative_path: str, page_number: int | None) -> str:
    label = Path(relative_path).name
    if page_number is not None:
        label += f" p. {page_number}"
    return label


def _citation_from_candidate(candidate: _FactCandidate) -> Citation:
    return Citation(
        document_name=Path(candidate.relative_path).name,
        chunk_id=candidate.chunk_id or f"fact-{candidate.fact_type}",
        page_number=candidate.page_number,
    )


def _document_is_entitlement_relevant(document: DocumentRecord) -> bool:
    text = document.normalized_text.lower()
    path = document.relative_path.as_posix().lower()
    return any(term in text or term in path for term, _ in _DOC_TERMS_BY_FACT["entitlement_status"])


def _entitlement_document_sort_key(document: DocumentRecord) -> tuple[int, str]:
    text = f"{document.relative_path.as_posix().lower()} {document.normalized_text.lower()}"
    score = 0
    for term, weight in _DOC_TERMS_BY_FACT["entitlement_status"]:
        if term in text:
            score -= weight
    return (score, document.relative_path.as_posix().lower())


def _document_label(document: DocumentRecord | None) -> str:
    if document is None:
        return ""
    first_chunk = _iter_document_chunks(document)[0]
    return _source_label(document.relative_path.as_posix(), first_chunk.page_number)


def _citation_for_entitlement_document(document: DocumentRecord) -> Citation:
    first_chunk = _iter_document_chunks(document)[0]
    return Citation(
        document_name=Path(document.relative_path).name,
        chunk_id=first_chunk.chunk_id,
        page_number=first_chunk.page_number,
    )


def _stage_match_score(issue: CanonicalIssue, rule: dict[str, object]) -> int:
    signal_text = _issue_signal_text(issue)
    score = 0
    if issue.blocking_flag:
        score += 5
    if issue.critical_path_flag:
        score += 4
    if issue.category in rule["categories"]:
        score += 2
    if issue.schedule_impact_classification in rule["schedule_classes"]:
        score += 3
    if any(term in signal_text for term in rule["terms"]):
        score += 4
    return score


def _issue_signal_text(issue: CanonicalIssue) -> str:
    return " ".join(
        part
        for part in [
            issue.title,
            issue.why_it_matters,
            issue.likely_implication,
            issue.blocking_reason,
            issue.critical_path_reason,
            " ".join(issue.best_evidence[:2]),
            " ".join(issue.core_facts[:2]),
            issue.site_specific_trigger,
        ]
        if part
    ).lower()


def _normalize_posture(raw_posture: str) -> str:
    lowered = (raw_posture or "").strip().lower()
    if lowered in {"do not advance", "do not proceed", "stop", "decline"}:
        return "Do Not Advance"
    if lowered in {"advance", "go"}:
        return "Advance"
    return "Advance Only If"


def _material_unknowns(omission_assessments: list[OmissionAssessment]) -> list[OmissionAssessment]:
    return [
        assessment
        for assessment in omission_assessments
        if assessment.front_end_status in {"missing and important", "conflicting across documents", "stale and potentially unreliable"}
    ]


def _biggest_unknown(
    omission_assessments: list[OmissionAssessment],
    contradictions: list[ContradictionFinding],
) -> tuple[str, list[Citation]]:
    material_unknowns = _material_unknowns(omission_assessments)
    if material_unknowns:
        assessment = material_unknowns[0]
        return (
            clip_text(
                f"The biggest unknown is {assessment.item.lower()} because {assessment.front_end_reason or assessment.rationale}",
                220,
            ),
            assessment.citations[:3],
        )
    if contradictions:
        finding = contradictions[0]
        return (
            clip_text(
                f"The biggest unknown is the unresolved contradiction that {finding.description.lower()} {finding.why_it_matters}",
                220,
            ),
            finding.citations[:3],
        )
    return ("No single unresolved unknown currently stands above the rest of the issue set.", [])


def _price_or_structure_lines(
    risk_items: list[AcquisitionRiskItem],
    omission_assessments: list[OmissionAssessment],
) -> list[str]:
    lines: list[str] = []
    for item in risk_items:
        if item.bucket == "Deal Killers":
            lines.append(f"Do not release hard money or remove close conditions against {item.title.lower()}.")
        elif item.bucket == "Pre-Close Gating Items":
            lines.append(f"Carry {item.title.lower()} as a closing condition or seller cure item, not a post-close assumption.")
        elif item.bucket == "Price Adjustments":
            lines.append(f"Reprice, add a seller credit, or reserve specific contingency for {item.title.lower()}.")
        if len(lines) >= 3:
            break
    if len(lines) < 3:
        for assessment in omission_assessments:
            if assessment.front_end_status != "missing and important":
                continue
            lines.append(f"Keep diligence open until {assessment.item.lower()} is current and readable enough to support price and structure.")
            if len(lines) >= 3:
                break
    return unique_preserve_order(lines)[:3] or ["No specific price or structure change rises above routine contingency beyond the current issue set."]


def _dedupe_citations(citations: list[Citation]) -> list[Citation]:
    deduped: list[Citation] = []
    seen: set[tuple[str, str, int | None]] = set()
    for citation in citations:
        key = (citation.document_name, citation.chunk_id, citation.page_number)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(citation)
    return deduped


def _excerpt(text: str, start: int, end: int, *, max_chars: int = 180) -> str:
    left = max(0, start - 80)
    right = min(len(text), end + 80)
    snippet = re.sub(r"\s+", " ", text[left:right]).strip()
    return snippet if len(snippet) <= max_chars else snippet[: max_chars - 3].rstrip() + "..."