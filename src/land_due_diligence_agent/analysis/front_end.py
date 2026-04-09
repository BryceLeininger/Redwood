"""Deterministic front-end opportunity assessment and follow-up planning."""

from __future__ import annotations

import re
from datetime import datetime

from land_due_diligence_agent.models import (
    CanonicalIssue,
    CanonicalIssueRegistry,
    ContradictionFinding,
    DocumentAnalysis,
    FurtherDiligenceRoadmap,
    OmissionAssessment,
    ReadingRecommendation,
    ResearchAgendaItem,
)
from land_due_diligence_agent.utils.text import unique_preserve_order

_CURRENT_YEAR = datetime.now().year
_REAL_FLAG_TYPES = {"red flag", "yellow flag"}
_ELEVATED_NORMALITY = {"elevated", "unusual"}
_CRITICAL_CATEGORIES = {
    "Title / Access Concerns",
    "Environmental Risks",
    "Geotechnical Risks",
    "Utilities / Infrastructure Issues",
    "Offsite Obligations",
    "Entitlement Status",
}
_ROUTINE_FRICTION_CATEGORIES = {
    "Entitlement Status",
    "Schedule Risks",
    "Fee / Exaction Burden",
    "Budget / Cost Reliability",
}
_TIME_SENSITIVE_CATEGORIES = {
    "Entitlement Status",
    "Fee / Exaction Burden",
    "Budget / Cost Reliability",
    "Utilities / Infrastructure Issues",
    "Schedule Risks",
    "Offsite Obligations",
}
_SHORT_DATE_RE = re.compile(
    r"\b(?:0?[1-9]|1[0-2])[-/.\s](?:0?[1-9]|[12]\d|3[01])[-/.\s](\d{2})(?!\d)"
)
_MONTH_YEAR_RE = re.compile(
    r"\b(?:jan|january|feb|february|mar|march|apr|april|may|jun|june|jul|july|aug|august|sep|sept|september|oct|october|nov|november|dec|december)"
    r"(?:[-/.\s]+\d{1,2})?[-/.\s,]+(\d{2,4})\b",
    re.IGNORECASE,
)
_LEGAL_CATEGORIES = {
    "Title / Access Concerns",
    "Entitlement Status",
    "Environmental Risks",
}
_PRIMARY_DOC_TERMS = (
    "title",
    "commitment",
    "survey",
    "report",
    "study",
    "conditions",
    "approval",
    "resolution",
    "plan",
    "phase i",
    "phase ii",
    "geotech",
    "geotechnical",
    "drainage",
    "stormwater",
    "fee schedule",
    "budget",
    "estimate",
    "utility",
    "will serve",
)
_SUMMARY_DOC_TERMS = (
    "summary",
    "memo",
    "overview",
    "executive",
    "matrix",
    "tracker",
    "checklist",
    "log",
)
_PRELIMINARY_TERMS = (
    "draft",
    "preliminary",
    "budgetary",
    "conceptual",
    "opinion of probable cost",
    "for discussion only",
)
_SOURCE_BY_CATEGORY = {
    "Title / Access Concerns": "title company, surveyor, and land-use counsel",
    "Entitlement Status": "planning staff, civil engineer, and land-use counsel",
    "Environmental Risks": "environmental consultant and agency file review",
    "Flood / Drainage Issues": "civil engineer and public works reviewer",
    "Geotechnical Risks": "geotechnical engineer and grading/civil engineer",
    "Offsite Obligations": "civil engineer, seller development manager, and public works staff",
    "Fee / Exaction Burden": "city fee desk, building department, and internal underwriting",
    "Budget / Cost Reliability": "site contractor or estimator and internal underwriting",
    "Utilities / Infrastructure Issues": "serving utility, civil engineer, and dry-utility coordinator",
    "Schedule Risks": "seller project manager, permit expeditor, and agency staff",
}
_SCHEDULE_BUCKET_ORDER = {
    "immediate blocker": 0,
    "pre-close blocker": 1,
    "pre-underwriting blocker": 2,
    "pre-final-map blocker": 3,
    "pre-vertical-start blocker": 4,
    "non-blocking": 5,
}
_READ_BUCKET_ORDER = {
    "must read personally": 0,
    "should skim": 1,
    "safe to rely on agent": 2,
}
_WHY_NOW_ORDER = {
    "investigate now": 0,
    "investigate after initial read": 1,
    "investigate before underwriting": 2,
    "monitor unless other signals worsen": 3,
    "likely routine unless contradicted": 4,
    "unclear": 5,
}
_ACQUISITION_SEVERITY_ORDER = {
    "CRITICAL": 0,
    "HIGH": 1,
    "MODERATE": 2,
    "LOW": 3,
}


def apply_front_end_assessment(
    *,
    registry: CanonicalIssueRegistry,
    document_analyses: list[DocumentAnalysis],
    omission_assessments: list[OmissionAssessment],
    contradictions: list[ContradictionFinding],
) -> tuple[list[ReadingRecommendation], FurtherDiligenceRoadmap]:
    """Apply deterministic front-end classification to issues, documents, and follow-up steps."""

    _annotate_document_basics(document_analyses)
    _annotate_omission_assessments(omission_assessments, document_analyses, contradictions)
    _annotate_issues(registry, document_analyses)
    _annotate_document_priorities(document_analyses, registry, contradictions)
    _annotate_package_assessment(
        registry=registry,
        document_analyses=document_analyses,
        omission_assessments=omission_assessments,
        contradictions=contradictions,
    )
    reading_order = build_front_end_reading_order(document_analyses)
    roadmap = build_further_diligence_roadmap(
        registry=registry,
        omission_assessments=omission_assessments,
        contradictions=contradictions,
        reading_order=reading_order,
    )
    return reading_order, roadmap


def deal_impact_summary_issues(issues: list[CanonicalIssue], *, limit: int = 3) -> list[CanonicalIssue]:
    """Return the issues that most directly drive deal-shaping impact summaries."""

    ordered = sorted(
        issues,
        key=lambda issue: (
            _ACQUISITION_SEVERITY_ORDER.get(issue.acquisition_severity, 4),
            0 if issue.gating_item else 1,
            0 if issue.blocking_flag else 1,
            0 if issue.critical_path_flag else 1,
            -_issue_max_impact(issue),
            -issue.priority_score.total,
            issue.title,
        ),
    )
    priority = [issue for issue in ordered if issue.acquisition_severity in {"CRITICAL", "HIGH"}]
    return (priority or ordered)[:limit]


def deal_impact_type_for_issue(issue: CanonicalIssue) -> str:
    """Return the primary underwriting/deal impact lane for an issue."""

    if issue.deal_impact_type:
        return issue.deal_impact_type

    if issue.category == "Title / Access Concerns" and (issue.blocking_flag or issue.priority_score.closing_risk >= 3):
        return "legal/title risk"
    if issue.category == "Entitlement Status" and (issue.blocking_flag or issue.priority_score.entitlement_fragility >= 3):
        return "entitlement risk"

    price_score = max(issue.priority_score.cost_exposure, issue.priority_score.yield_exposure)
    if issue.decision_action in {"reprice", "restructure"}:
        price_score += 2
    if "price" in issue.affects:
        price_score += 1

    schedule_score = issue.priority_score.schedule_exposure
    if issue.blocking_flag or issue.critical_path_flag:
        schedule_score += 2
    if "timeline" in issue.affects:
        schedule_score += 1

    entitlement_score = issue.priority_score.entitlement_fragility
    if issue.category == "Entitlement Status":
        entitlement_score += 3
    if "entitlement risk" in issue.affects:
        entitlement_score += 1

    construction_cost_score = issue.priority_score.cost_exposure
    if issue.category in {
        "Environmental Risks",
        "Geotechnical Risks",
        "Flood / Drainage Issues",
        "Utilities / Infrastructure Issues",
        "Offsite Obligations",
        "Fee / Exaction Burden",
        "Budget / Cost Reliability",
    }:
        construction_cost_score += 2
    if "construction cost" in issue.affects:
        construction_cost_score += 1

    legal_title_score = issue.priority_score.closing_risk
    if issue.category == "Title / Access Concerns":
        legal_title_score += 3
    if "legal/title risk" in issue.affects:
        legal_title_score += 1

    scores = {
        "legal/title risk": legal_title_score,
        "entitlement risk": entitlement_score,
        "timeline": schedule_score,
        "construction cost": construction_cost_score,
        "price": price_score,
    }
    best_label, best_score = max(
        scores.items(),
        key=lambda item: (-item[1], _impact_type_order(item[0])),
    )
    if best_score <= 0:
        return issue.affects[0] if issue.affects else "deal execution"
    return best_label


def deal_impact_magnitude_for_issue(issue: CanonicalIssue) -> str:
    """Return a qualitative magnitude label for deal impact."""

    if issue.deal_impact_magnitude:
        return issue.deal_impact_magnitude

    max_impact = _issue_max_impact(issue)
    if issue.decision_action == "treat as fatal":
        return "deal-shaping"
    if issue.acquisition_severity == "CRITICAL":
        return "deal-shaping"
    if issue.blocking_flag and max_impact >= 4:
        return "deal-shaping"
    if issue.acquisition_severity == "HIGH" or max_impact >= 4:
        return "material"
    if issue.acquisition_severity == "MODERATE" or max_impact >= 3:
        return "meaningful"
    return "limited"


def deal_impact_mechanism_for_issue(issue: CanonicalIssue) -> str:
    """Return the main mechanism by which the issue can move the deal."""

    if issue.deal_impact_mechanism:
        return issue.deal_impact_mechanism

    impact_type = deal_impact_type_for_issue(issue)
    if impact_type == "legal/title risk":
        candidates = [
            issue.likely_closing_effect,
            issue.likely_structure_effect,
            issue.practical_impact,
            issue.why_it_matters,
            issue.likely_implication,
        ]
    elif impact_type == "entitlement risk":
        candidates = [
            issue.likely_implication,
            issue.likely_yield_or_product_effect,
            issue.practical_impact,
            issue.why_it_matters,
        ]
    elif impact_type == "timeline":
        candidates = [
            issue.likely_schedule_effect,
            issue.practical_impact,
            issue.likely_implication,
            issue.why_it_matters,
        ]
    elif impact_type == "construction cost":
        candidates = [
            issue.likely_cost_effect,
            issue.likely_underwriting_effect,
            issue.practical_impact,
            issue.why_it_matters,
        ]
    elif impact_type == "price":
        candidates = [
            issue.likely_underwriting_effect,
            issue.likely_cost_effect,
            issue.likely_yield_or_product_effect,
            issue.practical_impact,
            issue.why_it_matters,
        ]
    else:
        candidates = [
            issue.practical_impact,
            issue.likely_implication,
            issue.why_it_matters,
            issue.title,
        ]

    for candidate in unique_preserve_order(candidates):
        if candidate:
            return candidate
    return issue.title


def cost_exposure_band_for_issue(issue: CanonicalIssue) -> str:
    """Return a qualitative cost exposure band."""

    if issue.cost_exposure_band:
        return issue.cost_exposure_band

    score = max(issue.priority_score.cost_exposure, issue.priority_score.yield_exposure)
    impact_type = deal_impact_type_for_issue(issue)
    if issue.decision_action in {"treat as fatal", "reprice"} and impact_type in {"price", "construction cost"}:
        score = max(score, 5)
    if score >= 5:
        return "potentially deal-changing"
    if score >= 4:
        return "material re-underwrite"
    if score >= 3:
        return "noticeable budget pressure"
    if impact_type in {"price", "construction cost"} or issue.likely_cost_effect or issue.likely_underwriting_effect:
        return "limited but real"
    return "little direct cost signal"


def timing_exposure_band_for_issue(issue: CanonicalIssue) -> str:
    """Return a qualitative timing exposure band."""

    if issue.timing_exposure_band:
        return issue.timing_exposure_band

    if issue.schedule_impact_classification in {"immediate blocker", "pre-close blocker"}:
        return "can stop the next gate"
    if (
        issue.schedule_impact_classification in {"pre-underwriting blocker", "pre-final-map blocker"}
        or issue.priority_score.schedule_exposure >= 4
        or issue.critical_path_flag
    ):
        return "material delay risk"
    if (
        issue.schedule_impact_classification == "pre-vertical-start blocker"
        or issue.priority_score.schedule_exposure >= 3
        or "timeline" in issue.affects
        or issue.likely_schedule_effect
    ):
        return "execution timing drag"
    return "limited direct timing signal"


def fixability_classification_for_issue(issue: CanonicalIssue) -> str:
    """Translate fixability into a deal-facing execution classification."""

    if issue.fixability_classification:
        return issue.fixability_classification

    if issue.decision_action == "treat as fatal":
        return "hard to cure before closing"
    if issue.category == "Title / Access Concerns" and issue.blocking_flag:
        return "needs title cure, insurance, or redesign"
    if issue.category == "Entitlement Status" and issue.blocking_flag:
        return "needs agency closure or plan change"
    if issue.fixability == "low":
        return "hard to fix pre-close"
    if issue.fixability == "medium":
        if issue.front_end_flag in {"document gap", "stale-information concern"} and not issue.blocking_flag:
            return "fixable if current support exists and is produced"
        return "fixable, but only with time, scope closure, or economics reset"
    if issue.fixability == "high":
        if issue.front_end_flag in {"document gap", "stale-information concern"}:
            return "mostly documentable"
        return "likely fixable through normal diligence clean-up"
    return "unknown"


def if_wrong_line_for_issue(issue: CanonicalIssue) -> str:
    """Return the downside if the current working assumption proves wrong."""

    if issue.downside_if_wrong:
        return issue.downside_if_wrong

    if issue.status == "conflicted":
        return "If the wrong source controls, the team can underwrite to the wrong plan, cost basis, or closing assumption."

    impact_type = deal_impact_type_for_issue(issue)
    if impact_type == "legal/title risk":
        return "If the current assumption is wrong, closing control, insured access, or legal buildability can fail rather than just slip."
    if impact_type == "entitlement risk":
        return "If the current assumption is wrong, approved product, density, or permit path can move and force a re-underwrite."
    if impact_type == "timeline":
        return "If the current assumption is wrong, carry and execution timing can slip before the next decision gate."
    if impact_type == "construction cost":
        return "If the current assumption is wrong, site scope can expand beyond the current budget and contingency."
    if impact_type == "price":
        return "If the current assumption is wrong, the deal may need repricing, seller credit, or a different structure."
    return "If the current assumption is wrong, the deal can move materially on price, timing, or execution."


def underwrite_confidence_level(
    *,
    registry: CanonicalIssueRegistry,
    omission_assessments: list[OmissionAssessment],
    contradictions: list[ContradictionFinding],
    document_analyses: list[DocumentAnalysis],
    issues: list[CanonicalIssue] | None = None,
) -> str:
    """Return a qualitative confidence label for the current underwriting stance."""

    issue_pool = issues or registry.issues
    critical_count = sum(issue.acquisition_severity == "CRITICAL" for issue in issue_pool)
    high_count = sum(issue.acquisition_severity == "HIGH" for issue in issue_pool)
    blind_spot_count = sum(
        assessment.front_end_status in {"missing and important", "conflicting across documents", "stale and potentially unreliable"}
        for assessment in omission_assessments
    )
    low_confidence_primary = sum(
        analysis.document_role == "primary" and analysis.confidence == "low"
        for analysis in document_analyses
    )

    if (
        registry.package_quality in {"selectively presented", "thin", "stale", "unclear"}
        or critical_count
        or contradictions
        or blind_spot_count >= 2
        or low_confidence_primary
    ):
        return "low"
    if (
        registry.package_quality in {"mixed", "adequate"}
        and (high_count >= 2 or blind_spot_count or any(issue.gating_item for issue in issue_pool))
    ):
        return "guarded"
    if high_count or blind_spot_count:
        return "moderate"
    return "high"


def underwrite_confidence_reason(
    *,
    registry: CanonicalIssueRegistry,
    omission_assessments: list[OmissionAssessment],
    contradictions: list[ContradictionFinding],
    document_analyses: list[DocumentAnalysis],
    issues: list[CanonicalIssue] | None = None,
) -> str:
    """Explain the current underwriting confidence level in one short paragraph."""

    issue_pool = issues or registry.issues
    critical_count = sum(issue.acquisition_severity == "CRITICAL" for issue in issue_pool)
    high_count = sum(issue.acquisition_severity == "HIGH" for issue in issue_pool)
    blind_spot_count = sum(
        assessment.front_end_status in {"missing and important", "conflicting across documents", "stale and potentially unreliable"}
        for assessment in omission_assessments
    )
    low_confidence_primary = sum(
        analysis.document_role == "primary" and analysis.confidence == "low"
        for analysis in document_analyses
    )

    parts = [
        f"Package quality is {registry.package_quality or 'mixed'} with {registry.confidence_in_initial_read} initial-read confidence.",
    ]
    if critical_count:
        parts.append(f"{critical_count} critical issue(s) still sit on the underwriting path.")
    elif high_count:
        parts.append(f"{high_count} high-severity issue(s) still need direct support before the basis is stable.")
    if contradictions:
        parts.append(f"{len(contradictions)} contradiction(s) still leave a controlling assumption unsettled.")
    elif blind_spot_count:
        parts.append(f"{blind_spot_count} major blind spot(s) still limit what can be underwritten with confidence.")
    if low_confidence_primary:
        parts.append("At least one primary control document still needs manual confirmation because extraction quality was weak.")
    elif registry.confidence_unlocks:
        parts.append(f"Confidence improves once {registry.confidence_unlocks[0].rstrip('.')}.")
    return " ".join(parts[:3])


def underwrite_confidence_limiters(
    *,
    registry: CanonicalIssueRegistry,
    omission_assessments: list[OmissionAssessment],
    contradictions: list[ContradictionFinding],
    document_analyses: list[DocumentAnalysis],
    issues: list[CanonicalIssue] | None = None,
    limit: int = 3,
) -> list[str]:
    """Return the short list of assumptions still carrying the underwrite."""

    issue_pool = issues or registry.issues
    lines: list[str] = []
    for issue in deal_impact_summary_issues(issue_pool, limit=limit):
        request = issue.missing_confirmation or issue.what_would_resolve_it or (issue.open_questions[0] if issue.open_questions else "")
        if request:
            lines.append(f"{issue.title}: underwriting still leans on {request.rstrip('.').lower()}.")
        else:
            lines.append(
                f"{issue.title}: underwriting still leans on the current {deal_impact_type_for_issue(issue)} assumption staying true."
            )
    for finding in contradictions[:limit]:
        lines.append(f"Contradiction to reconcile: {finding.description}")
    for assessment in omission_assessments:
        if assessment.front_end_status in {"missing and important", "conflicting across documents"}:
            lines.append(f"Missing hard backing: {assessment.item}.")
        if len(lines) >= limit + 2:
            break
    if not lines and any(analysis.document_role == "primary" and analysis.confidence == "low" for analysis in document_analyses):
        lines.append("A primary control document still requires manual confirmation because extraction quality was weak.")
    return unique_preserve_order(lines)[:limit]


def build_front_end_reading_order(document_analyses: list[DocumentAnalysis]) -> list[ReadingRecommendation]:
    """Build a front-end oriented reading sequence with explicit review buckets."""

    ordered = sorted(
        document_analyses,
        key=lambda analysis: (
            _READ_BUCKET_ORDER.get(analysis.reading_bucket, 1),
            -analysis.reading_priority,
            analysis.document.relative_path.as_posix().lower(),
        ),
    )
    return [
        ReadingRecommendation(
            title=analysis.document.title,
            relative_path=analysis.document.relative_path.as_posix(),
            priority=analysis.reading_priority,
            reason=analysis.reading_reason,
            confidence=analysis.confidence,
            focus_areas=analysis.focus_areas,
            bucket=analysis.reading_bucket,
            document_role=analysis.document_role,
            rationale_factors=analysis.reading_rationale_factors,
        )
        for analysis in ordered
    ]


def build_further_diligence_roadmap(
    *,
    registry: CanonicalIssueRegistry,
    omission_assessments: list[OmissionAssessment],
    contradictions: list[ContradictionFinding],
    reading_order: list[ReadingRecommendation],
) -> FurtherDiligenceRoadmap:
    """Build a practical follow-up roadmap for front-end diligence."""

    prioritized_issues = sorted(
        registry.issues,
        key=lambda issue: (
            _WHY_NOW_ORDER.get(issue.why_now, 5),
            {"unusual": 3, "elevated": 2, "mildly elevated": 1, "routine": 0, "unknown": 0}.get(issue.normality_classification, 0) * -1,
            -int(issue.blocking_flag),
            -len(issue.downstream_dependencies),
            -issue.priority_score.total,
            issue.title,
        ),
    )
    important_issues = [
        issue
        for issue in prioritized_issues
        if issue.front_end_flag in {"red flag", "yellow flag", "conflict / contradiction concern"}
    ]
    gap_issues = [
        issue
        for issue in prioritized_issues
        if issue.front_end_flag in {"document gap", "stale-information concern"}
    ]
    real_flags = [
        _issue_roadmap_line(issue)
        for issue in important_issues
        if issue.front_end_flag in _REAL_FLAG_TYPES
    ][:5]
    missing_items = [
        _omission_roadmap_line(assessment)
        for assessment in omission_assessments
        if assessment.front_end_status in {"missing and important", "missing but normally expected"}
    ][:5]
    contradiction_lines = [
        f"{finding.description} Resolve by identifying which source controls and updating the underwriting assumption to that source."
        for finding in contradictions[:5]
    ]
    stale_lines = [
        f"{recommendation.title}: refresh the document because current conclusions rely on stale or dated support."
        for recommendation in reading_order
        if recommendation.reason.lower().find("stale") >= 0
    ][:5]

    research_lines: list[str] = []
    for issue in important_issues + gap_issues:
        for step in issue.research_agenda[:1]:
            research_lines.append(
                f"{step.title}: verify {step.verify_what} via {step.likely_source}; request {step.request_item} ({step.timing})."
            )
    research_lines = unique_preserve_order(research_lines)[:6]

    read_first = [
        f"{recommendation.title} ({recommendation.relative_path}): {recommendation.reason}"
        for recommendation in reading_order
        if recommendation.bucket == "must read personally"
    ][:5]
    follow_up_order = _build_follow_up_order(
        issues=prioritized_issues,
        reading_order=reading_order,
        omission_assessments=omission_assessments,
        contradictions=contradictions,
        research_lines=research_lines,
    )
    investigate_immediately = [
        _issue_roadmap_line(issue)
        for issue in important_issues
        if issue.why_now == "investigate now"
    ][:5]
    request_or_verify_soon = unique_preserve_order(
        [
            *(
                _issue_roadmap_line(issue)
                for issue in prioritized_issues
                if issue.why_now in {"investigate after initial read", "investigate before underwriting"}
            ),
            *(
                _omission_roadmap_line(assessment)
                for assessment in omission_assessments
                if assessment.front_end_status in {"missing and important", "stale and potentially unreliable"}
            ),
        ]
    )[:6]
    read_personally = [
        f"{recommendation.title} ({recommendation.relative_path}): {recommendation.reason}"
        for recommendation in reading_order
        if recommendation.bucket == "must read personally"
    ][:5]
    monitor_later = [
        _issue_roadmap_line(issue)
        for issue in prioritized_issues
        if issue.why_now == "monitor unless other signals worsen"
    ][:5]
    likely_routine = [
        f"{issue.title}: {issue.unusualness_rationale}"
        for issue in prioritized_issues
        if issue.why_now == "likely routine unless contradicted"
    ][:5]
    gating_items = [
        _gating_item_line(issue)
        for issue in prioritized_issues
        if issue.gating_item
    ][:6]
    recommended_next_steps = _recommended_next_steps(
        issues=prioritized_issues,
        omission_assessments=omission_assessments,
        reading_order=reading_order,
    )

    return FurtherDiligenceRoadmap(
        top_real_flags=real_flags,
        top_missing_items_to_request=missing_items,
        top_contradictions_to_resolve=contradiction_lines,
        top_stale_materials_to_refresh=stale_lines,
        top_public_consultant_internal_research=research_lines,
        top_documents_to_read_first=read_first,
        deal_killers_or_gating_items=gating_items,
        recommended_next_steps=recommended_next_steps,
        follow_up_order=follow_up_order,
        investigate_immediately=investigate_immediately,
        request_or_verify_soon=request_or_verify_soon,
        read_personally=read_personally,
        monitor_later=monitor_later,
        likely_routine_unless_changed=likely_routine,
    )


def _annotate_document_basics(document_analyses: list[DocumentAnalysis]) -> None:
    for analysis in document_analyses:
        analysis.document_role = _document_role(analysis)
        analysis.staleness_status, analysis.staleness_reason = _document_staleness(analysis)


def _annotate_omission_assessments(
    omission_assessments: list[OmissionAssessment],
    document_analyses: list[DocumentAnalysis],
    contradictions: list[ContradictionFinding],
) -> None:
    for assessment in omission_assessments:
        relevant = [
            analysis
            for analysis in document_analyses
            if assessment.category in analysis.focus_areas
            or analysis.document.title in assessment.source_documents
        ]
        has_stale_support = any(analysis.staleness_status == "stale and potentially unreliable" for analysis in relevant)
        conflict_without_control = _category_has_conflict(assessment.category, contradictions) and not any(
            analysis.document_role == "primary" and analysis.confidence in {"high", "medium"}
            for analysis in relevant
        )
        if conflict_without_control:
            assessment.front_end_status = "conflicting across documents"
            assessment.importance = "important"
            assessment.front_end_reason = (
                "The package has conflicting signals in this lane and no clearly controlling current source document."
            )
        elif has_stale_support and assessment.status in {"present and adequate", "present but weak"}:
            assessment.front_end_status = "stale and potentially unreliable"
            assessment.importance = "important" if assessment.category in _TIME_SENSITIVE_CATEGORIES else "normal"
            assessment.front_end_reason = "The referenced support appears dated enough that current reliance is unsafe without refresh."
        elif assessment.status in {"not found", "unclear whether present", "present but weak"}:
            assessment.front_end_status = (
                "missing and important" if assessment.category in _CRITICAL_CATEGORIES else "missing but normally expected"
            )
            assessment.importance = "important" if assessment.category in _CRITICAL_CATEGORIES else "normal"
            assessment.front_end_reason = "The package does not contain current, readable support for a normally expected diligence item."
        else:
            assessment.front_end_status = "present and adequate"
            assessment.importance = "normal"
            assessment.front_end_reason = "Current, readable support appears to be present."
        assessment.recommended_request = _recommended_request_for_omission(assessment)


def _annotate_issues(
    registry: CanonicalIssueRegistry,
    document_analyses: list[DocumentAnalysis],
) -> None:
    for issue in registry.issues:
        source_analyses = _source_analyses_for_issue(issue, document_analyses)
        issue.information_status, issue.information_status_reason = _issue_information_status(issue, source_analyses)
        issue.process_friction_flag = _process_friction_flag(issue)
        issue.normality_classification, issue.unusualness_rationale = _issue_normality(issue)
        issue.front_end_flag, issue.front_end_flag_reason = _issue_front_end_flag(issue)
        issue.why_now = _why_now(issue)
        issue.missing_confirmation = issue.what_would_resolve_it or _default_missing_confirmation(issue)
        issue.affects = _issue_affects(issue)
        issue.likely_explanation = _issue_likely_explanation(issue)
        issue.practical_impact = _issue_practical_impact(issue)
        issue.reality_vs_noise = _issue_reality_vs_noise(issue)
        issue.acquisition_severity, issue.acquisition_severity_reason = _issue_acquisition_severity(issue)
        issue.deal_impact_type = deal_impact_type_for_issue(issue)
        issue.deal_impact_magnitude = deal_impact_magnitude_for_issue(issue)
        issue.deal_impact_mechanism = deal_impact_mechanism_for_issue(issue)
        issue.cost_exposure_band = cost_exposure_band_for_issue(issue)
        issue.timing_exposure_band = timing_exposure_band_for_issue(issue)
        issue.fixability_classification = fixability_classification_for_issue(issue)
        issue.downside_if_wrong = if_wrong_line_for_issue(issue)
        issue.gating_item = _issue_is_gating_item(issue)
        issue.research_agenda = (
            [_research_agenda_item(issue)]
            if issue.front_end_flag != "routine item" or issue.why_now != "likely routine unless contradicted"
            else []
        )

        specificity_gate_reason = _specificity_gate_reason(issue)
        if specificity_gate_reason:
            issue.top_line_filter_reasons = unique_preserve_order(
                [*issue.top_line_filter_reasons, specificity_gate_reason]
            )
            issue.top_line_eligible = False

        if issue.front_end_flag == "routine item" and not issue.blocking_flag:
            issue.top_line_filter_reasons = unique_preserve_order(
                [*issue.top_line_filter_reasons, "front-end routine suppression"]
            )
            issue.top_line_eligible = False
        issue.calibration_notes = unique_preserve_order(
            [
                *issue.calibration_notes,
                f"front-end flag={issue.front_end_flag}",
                f"information status={issue.information_status}",
                f"normality={issue.normality_classification}",
                f"why now={issue.why_now}",
                f"acquisition severity={issue.acquisition_severity}",
                f"affects={', '.join(issue.affects) or 'none'}",
                f"deal impact={issue.deal_impact_type or 'deal execution'} / {issue.deal_impact_magnitude or 'limited'}",
                f"exposure bands: cost={issue.cost_exposure_band or 'n/a'}, timing={issue.timing_exposure_band or 'n/a'}",
                f"fixability classification={issue.fixability_classification or 'n/a'}",
                f"specificity={issue.specificity_level}",
                f"abnormality basis={issue.abnormality_basis}",
                f"genericity penalty={issue.genericity_penalty}",
                issue.front_end_flag_reason,
                issue.unusualness_rationale,
                issue.acquisition_severity_reason,
                issue.practical_impact,
                issue.reality_vs_noise,
            ]
        )


def _annotate_document_priorities(
    document_analyses: list[DocumentAnalysis],
    registry: CanonicalIssueRegistry,
    contradictions: list[ContradictionFinding],
) -> None:
    for analysis in document_analyses:
        factors: list[str] = []
        score = analysis.reading_priority
        elevated_support, routine_support, package_uncertainty_support = _supported_issue_mix(analysis, registry)
        legal_significance = any(category in _LEGAL_CATEGORIES for category in analysis.focus_areas)
        cost_schedule_significance = any(category in _TIME_SENSITIVE_CATEGORIES for category in analysis.focus_areas)

        if analysis.document_role == "primary":
            score += 8
            factors.append("primary source document")
        elif analysis.document_role == "summary":
            score -= 3
            factors.append("summary / secondary view")

        analysis.contradiction_count = _document_contradiction_count(analysis, contradictions)
        if analysis.contradiction_count:
            score += 12 * analysis.contradiction_count
            factors.append(f"supports {analysis.contradiction_count} contradiction signal(s)")
        if elevated_support:
            score += 8 * elevated_support
            factors.append("supports elevated or unusual issue(s)")
        if package_uncertainty_support:
            score += 5 * package_uncertainty_support
            factors.append("matters to package-quality uncertainty")
        if routine_support and not elevated_support and not package_uncertainty_support:
            score -= 4
            factors.append("mostly tied to routine process items")
        if legal_significance:
            score += 8
            factors.append("legal significance")
        if cost_schedule_significance:
            score += 5
            factors.append("cost / schedule significance")
        if analysis.staleness_status == "stale and potentially unreliable":
            score += 6
            factors.append("appears stale")
        if analysis.confidence == "low":
            score += 6
            factors.append("manual review required because extraction is weak")
        if any(term in analysis.document.normalized_text.lower() for term in _PRELIMINARY_TERMS):
            score += 3
            factors.append("contains preliminary or budgetary language")

        analysis.reading_priority = score
        analysis.reading_rationale_factors = unique_preserve_order(factors)
        analysis.reading_bucket = _reading_bucket(
            score=score,
            analysis=analysis,
            elevated_support=elevated_support,
            routine_support=routine_support,
            package_uncertainty_support=package_uncertainty_support,
            legal_significance=legal_significance,
        )
        analysis.reading_reason = _reading_reason_from_factors(analysis)


def _annotate_package_assessment(
    *,
    registry: CanonicalIssueRegistry,
    document_analyses: list[DocumentAnalysis],
    omission_assessments: list[OmissionAssessment],
    contradictions: list[ContradictionFinding],
) -> None:
    real_flags = [
        issue
        for issue in registry.issues
        if issue.front_end_flag in _REAL_FLAG_TYPES and issue.normality_classification in {"mildly elevated", "elevated", "unusual"}
    ]
    blind_spots = [
        issue
        for issue in registry.issues
        if issue.front_end_flag in {"document gap", "stale-information concern", "conflict / contradiction concern"}
    ]
    routine_items = [issue for issue in registry.issues if issue.front_end_flag == "routine item"]
    stale_docs = [analysis for analysis in document_analyses if analysis.staleness_status == "stale and potentially unreliable"]
    missing_important = [assessment for assessment in omission_assessments if assessment.front_end_status == "missing and important"]
    low_confidence_primary = [
        analysis
        for analysis in document_analyses
        if analysis.document_role == "primary" and analysis.confidence == "low"
    ]
    primary_docs = [analysis for analysis in document_analyses if analysis.document_role == "primary"]
    summary_docs = [analysis for analysis in document_analyses if analysis.document_role == "summary"]
    direct_elevated = [
        issue
        for issue in registry.issues
        if issue.normality_classification in _ELEVATED_NORMALITY and issue.information_status == "present and adequate"
    ]

    (
        registry.package_quality,
        registry.package_quality_reason,
        registry.confidence_in_initial_read,
        registry.package_quality_inputs,
    ) = _package_quality(
        document_count=len(document_analyses),
        primary_docs=primary_docs,
        summary_docs=summary_docs,
        contradictions=contradictions,
        stale_docs=stale_docs,
        missing_important=missing_important,
        low_confidence_primary=low_confidence_primary,
        direct_elevated=direct_elevated,
    )
    registry.concern_pattern = _concern_pattern(
        real_flags=real_flags,
        blind_spots=blind_spots,
        routine_items=routine_items,
    )
    registry.front_end_known_points = _front_end_known_points(real_flags, registry)
    registry.front_end_unresolved_points = _front_end_unresolved_points(blind_spots, omission_assessments, stale_docs, contradictions)
    registry.front_end_routine_points = _front_end_routine_points(routine_items)
    registry.front_end_elevated_points = _front_end_elevated_points(
        [
            *real_flags,
            *[
                issue
                for issue in blind_spots
                if issue.front_end_flag == "conflict / contradiction concern"
                or issue.normality_classification in {"mildly elevated", "elevated", "unusual"}
            ],
        ]
    )
    registry.front_end_attention_now_points = _front_end_attention_now_points(registry.issues)
    registry.front_end_deeper_work = _front_end_deeper_work(real_flags, blind_spots)


def _document_role(analysis: DocumentAnalysis) -> str:
    text = f"{analysis.document.title} {analysis.document.relative_path.as_posix()}".lower()
    if any(term in text for term in _PRIMARY_DOC_TERMS):
        return "primary"
    if any(term in text for term in _SUMMARY_DOC_TERMS):
        return "summary"
    return "supporting"


def _document_staleness(analysis: DocumentAnalysis) -> tuple[str, str]:
    header_text = f"{analysis.document.title} {analysis.document.relative_path.as_posix()}"
    years = _extract_visible_years(header_text)
    years.extend(_extract_visible_years(analysis.document.normalized_text[:800]))
    latest_year = max(years) if years else None
    time_sensitive = bool(set(analysis.focus_areas).intersection(_TIME_SENSITIVE_CATEGORIES))
    if latest_year is not None:
        threshold = 3 if time_sensitive else 5
        if _CURRENT_YEAR - latest_year >= threshold:
            return (
                "stale and potentially unreliable",
                f"The latest visible date appears to be {latest_year}, which is old for this diligence lane.",
            )
    return "present and adequate", "No obvious staleness signal was isolated."


def _extract_visible_years(text: str) -> list[int]:
    years = [int(year) for year in re.findall(r"\b(19\d{2}|20\d{2})\b", text)]
    years.extend(_expand_short_year(int(year)) for year in _SHORT_DATE_RE.findall(text))
    for year in _MONTH_YEAR_RE.findall(text):
        if len(year) == 2:
            years.append(_expand_short_year(int(year)))
        else:
            years.append(int(year))
    return years


def _expand_short_year(year: int) -> int:
    return 2000 + year if year <= (_CURRENT_YEAR % 100) + 2 else 1900 + year


def _issue_information_status(issue: CanonicalIssue, source_analyses: list[DocumentAnalysis]) -> tuple[str, str]:
    if issue.evidence_basis == "contradictory_evidence_present" or issue.status == "conflicted":
        return (
            "conflicting across documents",
            "The current package points in different directions and does not yet show which source controls.",
        )
    if any(analysis.staleness_status == "stale and potentially unreliable" for analysis in source_analyses):
        return (
            "stale and potentially unreliable",
            "The cited support appears dated enough that the issue should be refreshed before relying on it.",
        )
    if issue.evidence_basis in {"omission_only", "routine_missing_support"} or issue.status in {
        "not found",
        "unclear whether present",
        "present but weak",
    }:
        if issue.materiality == "high" or issue.blocking_flag or issue.category in _CRITICAL_CATEGORIES:
            return (
                "missing and important",
                "The package is missing current support for a lane that matters to front-end deal confidence.",
            )
        return (
            "missing but normally expected",
            "The package lacks a normal support item, but the gap does not yet read like a deal-specific red flag.",
        )
    return "present and adequate", "This issue is supported by current direct evidence rather than by a missing-document inference."


def _process_friction_flag(issue: CanonicalIssue) -> bool:
    if issue.normal_friction_flag:
        return True
    if issue.evidence_basis == "routine_missing_support":
        return True
    if issue.information_status == "missing but normally expected" and not issue.blocking_flag:
        return True
    if (
        issue.evidence_basis == "omission_only"
        and issue.category in _ROUTINE_FRICTION_CATEGORIES
        and not issue.blocking_flag
        and issue.status != "conflicted"
    ):
        return True
    if (
        issue.blocker_classification in {"confirmatory issue", "monitoring issue"}
        and issue.category in _ROUTINE_FRICTION_CATEGORIES.union({"Utilities / Infrastructure Issues"})
        and len(issue.downstream_dependencies) <= 1
        and issue.false_positive_risk != "low"
    ):
        return True
    if (
        issue.precedent_summary.confidence_adjustment == "down"
        and issue.evidence_basis in {"omission_only", "routine_missing_support", "weak_inference"}
    ):
        return True
    if (
        issue.learning_summary.confidence_adjustment == "down"
        and issue.learning_summary.sample_size >= 3
        and issue.evidence_basis in {"omission_only", "routine_missing_support", "weak_inference"}
    ):
        return True
    return False


def _issue_normality(issue: CanonicalIssue) -> tuple[str, str]:
    if issue.evidence_basis == "weak_inference" and not issue.citations and not issue.source_documents:
        return "unknown", "The current file set does not contain enough direct support to tell whether this issue is routine or unusual."

    reach = len(issue.downstream_dependencies)
    score = 0
    score += 4 if issue.specificity_level == "clearly site-specific" else 1 if issue.specificity_level == "somewhat specific" else -4
    score += 3 if issue.abnormality_basis in {"direct abnormal finding", "conflict"} else 1 if issue.abnormality_basis in {"unresolved constraint", "missing critical confirmation"} else -3
    score += 5 if issue.information_status == "conflicting across documents" else 0
    score += 3 if issue.blocking_flag else 0
    score += 2 if issue.critical_path_flag else 0
    score += 2 if issue.evidence_basis == "contradictory_evidence_present" else 0
    score += 2 if issue.evidence_basis == "direct_unresolved_risk" else 1 if issue.evidence_basis == "direct_confirmed_risk" else 0
    score += 2 if issue.schedule_impact_classification in {"immediate blocker", "pre-close blocker"} else 1 if issue.schedule_impact_classification == "pre-underwriting blocker" else 0
    score += 2 if reach >= 2 else 1 if reach == 1 else 0
    score += 1 if issue.materiality == "high" else 0
    score += 1 if issue.issue_strength == "strong" else 0
    score += 1 if issue.decision_relevant else 0
    score += 1 if issue.precedent_summary.confidence_adjustment == "up" and issue.precedent_summary.sample_size >= 2 else 0
    score += 1 if issue.learning_summary.confidence_adjustment == "up" and issue.learning_summary.sample_size >= 3 else 0
    score -= 4 if issue.process_friction_flag else 0
    score -= 3 if issue.evidence_basis == "routine_missing_support" else 0
    score -= 2 if issue.evidence_basis == "omission_only" else 0
    score -= 2 if issue.false_positive_risk == "high" else 1 if issue.false_positive_risk == "medium" else 0
    score -= 1 if issue.information_status == "missing but normally expected" else 0
    score -= 1 if issue.precedent_summary.confidence_adjustment == "down" and issue.precedent_summary.sample_size >= 2 else 0
    score -= 1 if issue.learning_summary.confidence_adjustment == "down" and issue.learning_summary.sample_size >= 3 else 0

    if issue.specificity_level == "generic" and not issue.site_specific_trigger and not issue.blocking_flag:
        return "routine", "This mostly reflects category presence or normal diligence background noise rather than a site-specific issue."
    if issue.information_status == "conflicting across documents" and issue.blocking_flag:
        return "unusual", "This looks unusual because documents conflict on a core path assumption rather than on a routine clean-up item."
    if issue.process_friction_flag and score <= 0:
        return "routine", "This reads like normal process friction because it is a common support or coordination gap without unusual deal-specific reach."
    if issue.information_status == "missing but normally expected" and not issue.blocking_flag:
        return "routine", "This reads like common seller-package incompleteness rather than unusual property or development risk."
    if issue.information_status == "missing and important" and not issue.blocking_flag and issue.evidence_basis in {"omission_only", "routine_missing_support"}:
        return "mildly elevated", "The missing support matters, but it still looks more like a meaningful diligence gap than an unusual property-level problem."
    if score >= 8:
        return "unusual", "Direct evidence leaves a core path issue or contradiction unresolved in a way that is not normal front-end friction."
    if score >= 5:
        return "elevated", "This issue is more than routine friction because it carries direct evidence, dependency reach, or critical-path significance."
    if score >= 2:
        return "mildly elevated", "This deserves attention, but it still resembles a fairly common diligence issue rather than something clearly unusual."
    return "routine", "The current signal still looks closer to standard entitlement, engineering, utility, or package-assembly friction than to unusual risk."


def _issue_front_end_flag(issue: CanonicalIssue) -> tuple[str, str]:
    if issue.information_status == "conflicting across documents":
        return (
            "conflict / contradiction concern",
            "A controlling assumption conflicts across documents, so the package still lacks a clear source of truth.",
        )
    if issue.information_status == "stale and potentially unreliable":
        return (
            "stale-information concern",
            "The support for this lane appears dated enough that current conclusions should not rely on it without refresh.",
        )
    if issue.information_status in {"missing and important", "missing but normally expected"}:
        return (
            "document gap",
            "This reads as a support gap or missing confirmation, not as a confirmed property-level problem.",
        )
    if issue.normality_classification == "routine" or issue.process_friction_flag or (issue.false_positive_risk == "high" and not issue.blocking_flag):
        return (
            "routine item",
            "The current signal looks closer to routine diligence friction than to a concentrated front-end flag.",
        )

    if issue.normality_classification == "unusual":
        return (
            "red flag",
            "This should stand out because it looks unusual for a normal front-end package and still affects a core path assumption.",
        )
    if issue.normality_classification == "elevated":
        if issue.blocking_flag or issue.critical_path_flag or issue.priority_score.total >= 95:
            return (
                "red flag",
                "This is elevated enough, and close enough to the critical path, that it deserves immediate front-end attention.",
            )
        return (
            "yellow flag",
            "The issue appears elevated and decision-relevant, but it does not yet read like a front-end stop sign.",
        )
    if issue.normality_classification == "mildly elevated":
        return (
            "yellow flag",
            "This issue is worth attention, but it still resembles a fairly common diligence problem rather than something clearly unusual.",
        )
    return (
        "routine item",
        "The current support does not justify elevating this lane above routine process friction.",
    )


def _issue_affects(issue: CanonicalIssue) -> list[str]:
    affects: list[str] = []
    if (
        issue.priority_score.cost_exposure >= 4
        or issue.category in {"Fee / Exaction Burden", "Budget / Cost Reliability", "Offsite Obligations"}
        or issue.decision_action in {"reprice", "restructure"}
    ):
        affects.append("price")
    if (
        issue.priority_score.schedule_exposure >= 4
        or issue.schedule_impact_classification != "non-blocking"
        or issue.blocking_flag
        or issue.critical_path_flag
    ):
        affects.append("timeline")
    if issue.priority_score.entitlement_fragility >= 4 or issue.category == "Entitlement Status":
        affects.append("entitlement risk")
    if (
        issue.category in {
            "Environmental Risks",
            "Geotechnical Risks",
            "Flood / Drainage Issues",
            "Utilities / Infrastructure Issues",
            "Offsite Obligations",
            "Fee / Exaction Burden",
            "Budget / Cost Reliability",
        }
        or "Vertical start" in issue.gating_flags
    ):
        affects.append("construction cost")
    if issue.category == "Title / Access Concerns" or issue.priority_score.closing_risk >= 4 or "Closing" in issue.gating_flags:
        affects.append("legal/title risk")
    return unique_preserve_order(affects)


def _impact_type_order(label: str) -> int:
    return {
        "legal/title risk": 0,
        "entitlement risk": 1,
        "timeline": 2,
        "construction cost": 3,
        "price": 4,
        "deal execution": 5,
    }.get(label, 99)


def _issue_max_impact(issue: CanonicalIssue) -> int:
    return max(
        issue.priority_score.cost_exposure,
        issue.priority_score.schedule_exposure,
        issue.priority_score.entitlement_fragility,
        issue.priority_score.closing_risk,
        issue.priority_score.yield_exposure,
    )


def _issue_likely_explanation(issue: CanonicalIssue) -> str:
    signal_text = " ".join(
        part
        for part in [
            issue.title,
            issue.site_specific_trigger,
            issue.why_it_matters,
            issue.likely_implication,
            " ".join(issue.best_evidence[:2]),
            " ".join(issue.core_facts[:2]),
        ]
        if part
    ).lower()

    if issue.status == "conflicted":
        if any(term in signal_text for term in ("unit", "lot", "count", "density", "yield")):
            return (
                "The package likely mixes different plan vintages, conceptual yield ranges, or lot-count versus unit-count references, "
                "and it does not yet identify the controlling approved plan set."
            )
        if any(term in signal_text for term in ("acre", "gross", "net", "site area", "site acreage")):
            return (
                "The documents likely mix gross, net, and site-area references or rely on different map or survey vintages, "
                "and the controlling acreage basis has not been pinned down."
            )
        if any(term in signal_text for term in ("owner", "vesting", "deed", "grantee", "seller entity")):
            return (
                "The documents likely span different vesting dates, transfer steps, or seller entities, and the current closing vesting position "
                "has not been clearly tied to one controlling title source."
            )
        if any(term in signal_text for term in ("apn", "parcel", "legal description")):
            return (
                "The package likely mixes legacy parcel references, partial-site references, or a recent split/merge, and the controlling parcel basis "
                "has not been identified."
            )
        if any(term in signal_text for term in ("zoning", "approval", "resolution", "condition", "permit", "map", "annexation")):
            return (
                "The documents likely reflect different approval vintages or status trackers, and the controlling entitlement resolution, condition tracker, "
                "or approved plan has not been identified."
            )
        if any(term in signal_text for term in ("utility", "will serve", "provider", "water", "sewer", "capacity")):
            return (
                "The package likely combines preliminary utility assumptions with later coordination notes, and the current provider-confirmed position "
                "has not been established."
            )
        return "Different readable documents appear to be using different assumptions or plan versions, and no controlling source has been established."
    if issue.status in {"not found", "unclear whether present", "present but weak"}:
        return "The package does not contain a current controlling document that cleanly closes this issue."

    category_explanations = {
        "Title / Access Concerns": "Title exceptions, access rights, or ownership structure have not yet been reconciled to the current closing plan.",
        "Entitlement Status": "Project approvals may be farther along than the actual condition closeout, zoning compliance, or permit path support.",
        "Environmental Risks": "Environmental follow-up still appears open or not fully allocated into basis, schedule, or deal structure.",
        "Geotechnical Risks": "Soils recommendations exist, but the current plan and cost stack do not clearly show they are fully carried through.",
        "Flood / Drainage Issues": "Drainage or flood-control requirements still appear to depend on civil redesign or later permit-stage confirmation.",
        "Utilities / Infrastructure Issues": "Provider confirmation and required utility scope are still not locked for the current plan.",
        "Offsite Obligations": "Frontage or offsite scope still appears buyer-facing, or the responsible party is not fixed in the current support.",
        "Fee / Exaction Burden": "Current fee support looks preliminary, stale, or not fully confirmed by the governing agency.",
        "Budget / Cost Reliability": "Current cost support remains budgetary, incomplete, or not auditable enough to lock underwriting assumptions.",
        "Schedule Risks": "The current schedule still depends on assumptions that are not fully confirmed in the package.",
    }
    return category_explanations.get(issue.category, "The current package still lacks a clean controlling basis for this issue.")


def _issue_practical_impact(issue: CanonicalIssue) -> str:
    impact_lines = unique_preserve_order(
        [
            issue.likely_underwriting_effect if "price" in issue.affects else "",
            issue.likely_cost_effect if "construction cost" in issue.affects or "price" in issue.affects else "",
            issue.likely_schedule_effect if "timeline" in issue.affects else "",
            issue.likely_closing_effect if "legal/title risk" in issue.affects else "",
            issue.likely_yield_or_product_effect if "price" in issue.affects else "",
            issue.likely_implication if "entitlement risk" in issue.affects else "",
            issue.why_it_matters,
        ]
    )
    filtered = [line for line in impact_lines if line]
    if filtered:
        return " ".join(filtered[:3])
    return issue.likely_implication or issue.why_it_matters or issue.title


def _issue_reality_vs_noise(issue: CanonicalIssue) -> str:
    if issue.information_status == "conflicting across documents":
        return "Likely real inconsistency because readable documents conflict on a controlling deal assumption, not just on fragmentary text."
    if issue.information_status == "stale and potentially unreliable":
        return "Likely stale support rather than a true contradiction; refresh the current controlling document before relying on older references."
    if issue.specificity_level == "generic" and not issue.site_specific_trigger:
        return "Likely noise or routine category presence until a site-specific trigger is confirmed."
    if issue.evidence_basis in {"omission_only", "routine_missing_support"}:
        return "Likely a package completeness problem rather than a proven property defect, but it still limits underwriting confidence."
    if issue.confidence == "low":
        return "Signal is weak and should not be over-weighted until it is confirmed in a cleaner controlling document."
    return "Likely real issue because readable, site-specific support points to a live deal constraint."


def _issue_acquisition_severity(issue: CanonicalIssue) -> tuple[str, str]:
    max_impact = max(
        issue.priority_score.cost_exposure,
        issue.priority_score.schedule_exposure,
        issue.priority_score.entitlement_fragility,
        issue.priority_score.closing_risk,
        issue.priority_score.yield_exposure,
    )

    if issue.decision_action == "treat as fatal":
        return "CRITICAL", "The issue is explicitly modeled as a deal-stopping condition."
    if issue.blocking_flag and issue.schedule_impact_classification in {"immediate blocker", "pre-close blocker"}:
        return "CRITICAL", "The issue blocks a core decision gate or closing path and can stop the deal until resolved."
    if issue.blocking_flag and issue.priority_score.closing_risk >= 5:
        return "CRITICAL", "The issue directly threatens closability or legal control of the deal."
    if issue.blocking_flag and max_impact >= 4 and issue.false_positive_risk != "high":
        return "CRITICAL", "The issue is decision-relevant, blocks progress, and can materially move price or timing."
    if (
        issue.critical_path_flag
        or issue.front_end_flag in {"red flag", "conflict / contradiction concern"}
        or max_impact >= 5
        or issue.priority_score.total >= 95
    ):
        return "HIGH", "The issue is unlikely to kill the deal on its own, but it can materially change underwriting, timing, or execution risk."
    if (
        issue.front_end_flag in {"yellow flag", "document gap", "stale-information concern"}
        or issue.decision_relevant
        or max_impact >= 3
        or issue.priority_score.total >= 70
    ):
        return "MODERATE", "The issue needs clarification before relying on the package, but it does not currently read as fatal."
    return "LOW", "The issue currently reads as informational, minor, or closer to diligence background noise than to a decision driver."


def _issue_is_gating_item(issue: CanonicalIssue) -> bool:
    if issue.acquisition_severity == "CRITICAL":
        return True
    if issue.blocking_flag and issue.schedule_impact_classification in {"pre-underwriting blocker", "pre-final-map blocker"}:
        return True
    if issue.priority_score.closing_risk >= 5 and issue.decision_relevant:
        return True
    return False


def _specificity_gate_reason(issue: CanonicalIssue) -> str:
    if issue.front_end_flag == "conflict / contradiction concern":
        return ""
    if issue.specificity_level == "clearly site-specific" and issue.site_specific_trigger:
        return ""
    if (
        issue.specificity_level == "somewhat specific"
        and (
            issue.abnormality_basis == "missing critical confirmation"
            or issue.blocking_flag
            or issue.critical_path_flag
            or bool(issue.site_specific_trigger)
        )
    ):
        return ""
    if issue.blocking_flag or issue.critical_path_flag:
        if issue.site_specific_trigger or issue.abnormality_basis in {"unresolved constraint", "direct abnormal finding"}:
            return ""
    if issue.front_end_flag in {"document gap", "stale-information concern"} and issue.abnormality_basis == "missing critical confirmation":
        return ""
    return "site-specificity gate: generic category presence only"


def _why_now(issue: CanonicalIssue) -> str:
    if issue.normality_classification == "routine":
        return "likely routine unless contradicted"
    if issue.information_status == "conflicting across documents":
        return "investigate now"
    if issue.blocking_flag and issue.schedule_impact_classification in {"immediate blocker", "pre-close blocker"}:
        return "investigate now"
    if issue.normality_classification == "unusual":
        return "investigate now"
    if issue.schedule_impact_classification == "pre-underwriting blocker" or issue.decision_action in {"condition closing", "reprice"}:
        return "investigate before underwriting"
    if issue.normality_classification in {"elevated", "mildly elevated"} or issue.information_status in {"missing and important", "stale and potentially unreliable"}:
        return "investigate after initial read"
    if issue.blocker_classification in {"monitoring issue", "confirmatory issue"}:
        return "monitor unless other signals worsen"
    return "unclear"


def _research_agenda_item(issue: CanonicalIssue) -> ResearchAgendaItem:
    verify_what = issue.open_questions[0] if issue.open_questions else _verify_what(issue)
    return ResearchAgendaItem(
        issue_id=issue.issue_id,
        title=issue.title,
        verify_what=verify_what,
        request_item=issue.missing_confirmation or issue.what_would_resolve_it or _default_missing_confirmation(issue),
        likely_source=_SOURCE_BY_CATEGORY.get(issue.category, "seller team and relevant consultant"),
        timing=_research_timing(issue),
    )


def _supported_issue_mix(analysis: DocumentAnalysis, registry: CanonicalIssueRegistry) -> tuple[int, int, int]:
    aliases = _analysis_aliases(analysis)
    elevated = 0
    routine = 0
    package_uncertainty = 0
    for issue in registry.issues:
        issue_aliases = {name.lower() for name in issue.source_documents}
        issue_aliases.update(citation.document_name.lower() for citation in issue.citations)
        if aliases.intersection(issue_aliases) or issue.category in analysis.focus_areas:
            if issue.front_end_flag in {"document gap", "stale-information concern", "conflict / contradiction concern"}:
                package_uncertainty += 1
            elif issue.normality_classification in {"mildly elevated", "elevated", "unusual"}:
                elevated += 1
            else:
                routine += 1
    return elevated, routine, package_uncertainty


def _document_contradiction_count(analysis: DocumentAnalysis, contradictions: list[ContradictionFinding]) -> int:
    aliases = _analysis_aliases(analysis)
    count = 0
    for finding in contradictions:
        if aliases.intersection({name.lower() for name in finding.source_documents}) or any(
            citation.document_name.lower() in aliases for citation in finding.citations
        ):
            count += 1
    return count


def _reading_bucket(
    *,
    score: int,
    analysis: DocumentAnalysis,
    elevated_support: int,
    routine_support: int,
    package_uncertainty_support: int,
    legal_significance: bool,
) -> str:
    if (
        analysis.contradiction_count
        or (analysis.document_role == "primary" and legal_significance and (elevated_support or package_uncertainty_support))
        or score >= 105
        or (analysis.confidence == "low" and analysis.document_role == "primary")
        or elevated_support >= 2
    ):
        return "must read personally"
    if (
        score >= 82
        or elevated_support
        or package_uncertainty_support
        or analysis.staleness_status == "stale and potentially unreliable"
    ):
        return "should skim"
    if routine_support:
        return "safe to rely on agent"
    return "safe to rely on agent"


def _reading_reason_from_factors(analysis: DocumentAnalysis) -> str:
    factor_text = ", ".join(analysis.reading_rationale_factors[:4]) or "general package coverage"
    return (
        f"{analysis.reading_bucket.title()} because this document carries {factor_text}. "
        f"Confidence is {analysis.confidence}."
    )


def _package_quality(
    *,
    document_count: int,
    primary_docs: list[DocumentAnalysis],
    summary_docs: list[DocumentAnalysis],
    contradictions: list[ContradictionFinding],
    stale_docs: list[DocumentAnalysis],
    missing_important: list[OmissionAssessment],
    low_confidence_primary: list[DocumentAnalysis],
    direct_elevated: list[CanonicalIssue],
) -> tuple[str, str, str, list[str]]:
    inputs: list[str] = [
        f"documents={document_count}",
        f"primary_docs={len(primary_docs)}",
        f"summary_docs={len(summary_docs)}",
        f"contradictions={len(contradictions)}",
        f"stale_docs={len(stale_docs)}",
        f"missing_important={len(missing_important)}",
        f"low_confidence_primary={len(low_confidence_primary)}",
        f"direct_elevated={len(direct_elevated)}",
    ]
    if document_count == 0:
        return (
            "unclear",
            "No document set was available, so package quality cannot be assessed.",
            "low",
            inputs,
        )
    if contradictions and (missing_important or low_confidence_primary or len(primary_docs) <= len(summary_docs)):
        return (
            "selectively presented",
            "The package has material conflicts and does not include enough current controlling support to cleanly resolve them.",
            "low",
            inputs,
        )
    if len(stale_docs) >= 2 or (stale_docs and len(stale_docs) >= max(1, len(primary_docs) // 2 or 1)):
        return (
            "stale",
            "Too much of the primary support appears dated for a confident current read.",
            "low" if len(stale_docs) >= 2 else "medium",
            inputs,
        )
    if len(missing_important) >= 2 or len(low_confidence_primary) >= 2 or len(primary_docs) == 0:
        return (
            "thin",
            "Important source documents are missing, weak, or unreadable, so the package still leaves major blind spots.",
            "low",
            inputs,
        )
    if contradictions or stale_docs or missing_important:
        return (
            "mixed",
            "The package supports a meaningful initial read, but the support quality is uneven across the issues that matter most.",
            "medium",
            inputs,
        )
    if len(primary_docs) >= 2 and len(summary_docs) <= len(primary_docs) and direct_elevated:
        return (
            "strong",
            "The package contains current primary support in the lanes driving the initial read, so the first-pass judgment is reasonably grounded.",
            "high",
            inputs,
        )
    return (
        "adequate",
        "The package is good enough for a first-pass read, but it still depends on follow-up and selective manual review.",
        "medium",
        inputs,
    )


def _front_end_known_points(real_flags: list[CanonicalIssue], registry: CanonicalIssueRegistry) -> list[str]:
    points = [
        f"{issue.title}: {(issue.site_specific_trigger or (issue.core_facts[0] if issue.core_facts else issue.likely_implication))}"
        for issue in real_flags[:3]
    ]
    if registry.central_risk_pattern:
        points.append(registry.central_risk_pattern)
    return unique_preserve_order(points)[:4]


def _front_end_unresolved_points(
    blind_spots: list[CanonicalIssue],
    omission_assessments: list[OmissionAssessment],
    stale_docs: list[DocumentAnalysis],
    contradictions: list[ContradictionFinding],
) -> list[str]:
    points = [
        f"{issue.title}: {issue.missing_confirmation or issue.information_status_reason}"
        for issue in blind_spots[:3]
    ]
    points.extend(
        f"{assessment.item}: {assessment.front_end_status}."
        for assessment in omission_assessments
        if assessment.front_end_status in {"missing and important", "stale and potentially unreliable"} and assessment.item
    )
    points.extend(finding.description for finding in contradictions[:2])
    points.extend(
        f"{analysis.document.title}: {analysis.staleness_reason}"
        for analysis in stale_docs[:2]
    )
    return unique_preserve_order(points)[:6]


def _front_end_routine_points(routine_items: list[CanonicalIssue]) -> list[str]:
    return unique_preserve_order(
        (
            f"{issue.title}: verify whether this is truly an issue here."
            if issue.specificity_level == "generic"
            else f"{issue.title}: {issue.unusualness_rationale}"
        )
        for issue in routine_items[:3]
    )


def _front_end_elevated_points(real_flags: list[CanonicalIssue]) -> list[str]:
    return unique_preserve_order(
        f"{issue.title}: {issue.site_specific_trigger or issue.unusualness_rationale}"
        for issue in real_flags[:4]
    )


def _front_end_attention_now_points(issues: list[CanonicalIssue]) -> list[str]:
    return unique_preserve_order(
        f"{issue.title}: {issue.site_specific_trigger or issue.why_now}"
        for issue in issues
        if issue.why_now == "investigate now"
    )[:4]


def _front_end_deeper_work(real_flags: list[CanonicalIssue], blind_spots: list[CanonicalIssue]) -> list[str]:
    points: list[str] = []
    for issue in [*real_flags[:3], *blind_spots[:2]]:
        if issue.research_agenda:
            step = issue.research_agenda[0]
            if issue.specificity_level == "generic":
                points.append(f"{issue.title}: verify whether this is truly an issue here.")
            else:
                points.append(
                    f"{issue.title}: verify {step.verify_what}; request {step.request_item}; use {step.likely_source} ({step.timing})."
                )
    return unique_preserve_order(points)[:5]


def _issue_roadmap_line(issue: CanonicalIssue) -> str:
    blocked = issue.downstream_dependencies[0].title if issue.downstream_dependencies else "downstream diligence confidence"
    if issue.specificity_level == "generic":
        return f"{issue.title}: verify whether this is truly an issue here."
    return (
        f"{issue.title}: {issue.acquisition_severity}, {issue.normality_classification}, {issue.front_end_flag}. "
        f"Why now: {issue.why_now}. "
        f"What it blocks: {blocked.lower()}."
    )


def _omission_roadmap_line(assessment: OmissionAssessment) -> str:
    return (
        f"{assessment.item}: {assessment.front_end_status}. "
        f"Request {assessment.recommended_request.lower()}."
    )


def _build_follow_up_order(
    *,
    issues: list[CanonicalIssue],
    reading_order: list[ReadingRecommendation],
    omission_assessments: list[OmissionAssessment],
    contradictions: list[ContradictionFinding],
    research_lines: list[str],
) -> list[str]:
    steps: list[str] = []
    for issue in issues:
        if issue.why_now == "investigate now":
            steps.append(f"Investigate now: {issue.title}.")
        if len(steps) >= 2:
            break
    for recommendation in reading_order:
        if recommendation.bucket == "must read personally":
            steps.append(f"Read {recommendation.title} first because other conclusions depend on it.")
        if len(steps) >= 2:
            break
    for assessment in omission_assessments:
        if assessment.front_end_status == "missing and important":
            steps.append(f"Request {assessment.recommended_request.lower()} now.")
        if len(steps) >= 4:
            break
    for finding in contradictions[:2]:
        steps.append(f"Resolve the contradiction: {finding.description}")
    steps.extend(research_lines[:3])
    return unique_preserve_order(steps)[:7]


def _gating_item_line(issue: CanonicalIssue) -> str:
    affects = ", ".join(issue.affects) or "deal viability"
    confirm_line = _normalized_next_step(
        issue.missing_confirmation or issue.what_would_resolve_it or _default_missing_confirmation(issue)
    )
    return (
        f"{issue.title} [{issue.acquisition_severity}]: {confirm_line} "
        f"Affects {affects}."
    )


def _recommended_next_steps(
    *,
    issues: list[CanonicalIssue],
    omission_assessments: list[OmissionAssessment],
    reading_order: list[ReadingRecommendation],
) -> list[str]:
    steps: list[str] = []

    for issue in issues:
        if issue.acquisition_severity not in {"CRITICAL", "HIGH", "MODERATE"}:
            continue
        steps.append(_normalized_next_step(issue.what_would_resolve_it or issue.missing_confirmation or issue.title))
        if len(steps) >= 6:
            break

    for assessment in omission_assessments:
        if assessment.front_end_status not in {"missing and important", "stale and potentially unreliable", "conflicting across documents"}:
            continue
        steps.append(_normalized_next_step(assessment.recommended_request or assessment.item))
        if len(steps) >= 8:
            break

    for recommendation in reading_order:
        if recommendation.bucket != "must read personally":
            continue
        steps.append(f"Review {recommendation.title} directly because other conclusions depend on it.")
        if len(steps) >= 8:
            break

    return unique_preserve_order(steps)[:8]


def _normalized_next_step(text: str) -> str:
    cleaned = text.strip().rstrip(".")
    if not cleaned:
        return "Confirm the controlling source before relying on the current assumption."
    lowered = cleaned.lower()
    if lowered.startswith(("provide ", "replace ", "reconcile ", "confirm ", "refresh ", "review ", "state ", "obtain ")):
        return cleaned[0].upper() + cleaned[1:] + "."
    if lowered.startswith(("a current", "current ", "updated ", "an updated", "a refreshed", "refreshed ")):
        return f"Obtain {cleaned}."
    return f"Confirm {cleaned}."


def _source_analyses_for_issue(issue: CanonicalIssue, document_analyses: list[DocumentAnalysis]) -> list[DocumentAnalysis]:
    source_names = {name.lower() for name in issue.source_documents}
    source_names.update(citation.document_name.lower() for citation in issue.citations)
    matched = [
        analysis
        for analysis in document_analyses
        if _analysis_aliases(analysis).intersection(source_names)
    ]
    if matched:
        return matched
    return [analysis for analysis in document_analyses if issue.category in analysis.focus_areas]


def _analysis_aliases(analysis: DocumentAnalysis) -> set[str]:
    path = analysis.document.relative_path
    return {
        analysis.document.title.lower(),
        path.as_posix().lower(),
        path.name.lower(),
        path.stem.lower(),
    }


def _category_has_conflict(category: str, contradictions: list[ContradictionFinding]) -> bool:
    return any(category in finding.related_categories for finding in contradictions)


def _verify_what(issue: CanonicalIssue) -> str:
    if issue.blocking_flag and issue.downstream_dependencies:
        return f"what keeps {issue.downstream_dependencies[0].title.lower()} blocked"
    if issue.likely_implication:
        return issue.likely_implication.rstrip(".").lower()
    return issue.title.lower()


def _default_missing_confirmation(issue: CanonicalIssue) -> str:
    if issue.category == "Title / Access Concerns":
        return "a current title exception matrix and matching survey markup"
    if issue.category == "Entitlement Status":
        return "a current condition tracker and approval-status memo"
    if issue.category == "Utilities / Infrastructure Issues":
        return "current will-serve or provider confirmation"
    if issue.category == "Budget / Cost Reliability":
        return "current bid backup or an auditable cost reconciliation"
    return "current direct support for this issue"


def _research_timing(issue: CanonicalIssue) -> str:
    if issue.why_now in {
        "investigate now",
        "investigate after initial read",
        "investigate before underwriting",
        "monitor unless other signals worsen",
        "likely routine unless contradicted",
    }:
        return issue.why_now
    return "before deeper pursuit"


def _concern_pattern(
    *,
    real_flags: list[CanonicalIssue],
    blind_spots: list[CanonicalIssue],
    routine_items: list[CanonicalIssue],
) -> str:
    if len(blind_spots) > len(real_flags) and len(blind_spots) >= len(routine_items):
        return "Current concerns lean more toward package-quality uncertainty than toward confirmed property-level risk."
    if len(real_flags) >= len(blind_spots) and len(real_flags) >= len(routine_items):
        return "Current concerns lean more toward real property and development risk than toward package noise."
    if len(routine_items) > len(real_flags) and len(routine_items) > len(blind_spots):
        return "Most current issues look like normal process noise rather than unusual property risk."
    return "Current concerns are split between real risk and package-quality uncertainty."


def _recommended_request_for_omission(assessment: OmissionAssessment) -> str:
    if assessment.front_end_status == "stale and potentially unreliable":
        return f"a refreshed {assessment.item.lower()}"
    return f"a current, readable {assessment.item.lower()}"
