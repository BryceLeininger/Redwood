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
_CRITICAL_CATEGORIES = {
    "Title / Access Concerns",
    "Environmental Risks",
    "Geotechnical Risks",
    "Utilities / Infrastructure Issues",
    "Offsite Obligations",
    "Entitlement Status",
}
_TIME_SENSITIVE_CATEGORIES = {
    "Entitlement Status",
    "Fee / Exaction Burden",
    "Budget / Cost Reliability",
    "Utilities / Infrastructure Issues",
    "Schedule Risks",
    "Offsite Obligations",
}
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

    important_issues = [
        issue
        for issue in registry.issues
        if issue.front_end_flag in {"red flag", "yellow flag", "conflict / contradiction concern"}
    ]
    gap_issues = [
        issue
        for issue in registry.issues
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
        reading_order=reading_order,
        omission_assessments=omission_assessments,
        contradictions=contradictions,
        research_lines=research_lines,
    )

    return FurtherDiligenceRoadmap(
        top_real_flags=real_flags,
        top_missing_items_to_request=missing_items,
        top_contradictions_to_resolve=contradiction_lines,
        top_stale_materials_to_refresh=stale_lines,
        top_public_consultant_internal_research=research_lines,
        top_documents_to_read_first=read_first,
        follow_up_order=follow_up_order,
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
        issue.front_end_flag, issue.front_end_flag_reason = _issue_front_end_flag(issue)
        issue.missing_confirmation = issue.what_would_resolve_it or _default_missing_confirmation(issue)
        issue.research_agenda = [_research_agenda_item(issue)] if issue.front_end_flag != "routine item" else []

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
                issue.front_end_flag_reason,
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
        support_count = _supported_top_issue_count(analysis, registry)
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
        if support_count:
            score += 6 * support_count
            factors.append("other conclusions depend on it")
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
            support_count=support_count,
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
    real_flags = [issue for issue in registry.issues if issue.front_end_flag in _REAL_FLAG_TYPES]
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

    registry.package_quality, registry.package_quality_reason = _package_quality(
        contradictions=contradictions,
        stale_docs=stale_docs,
        missing_important=missing_important,
        low_confidence_primary=low_confidence_primary,
    )
    registry.front_end_known_points = _front_end_known_points(real_flags, registry)
    registry.front_end_unresolved_points = _front_end_unresolved_points(blind_spots, omission_assessments, stale_docs, contradictions)
    registry.front_end_routine_points = _front_end_routine_points(routine_items)
    registry.front_end_deeper_work = _front_end_deeper_work(real_flags, blind_spots)


def _document_role(analysis: DocumentAnalysis) -> str:
    text = f"{analysis.document.title} {analysis.document.relative_path.as_posix()}".lower()
    if any(term in text for term in _PRIMARY_DOC_TERMS):
        return "primary"
    if any(term in text for term in _SUMMARY_DOC_TERMS):
        return "summary"
    return "supporting"


def _document_staleness(analysis: DocumentAnalysis) -> tuple[str, str]:
    text = f"{analysis.document.title} {analysis.document.relative_path.as_posix()} {analysis.document.normalized_text[:1800]}".lower()
    years = [int(year) for year in re.findall(r"\b(19\d{2}|20\d{2})\b", text)]
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
    if issue.normal_friction_flag or issue.false_positive_risk == "high" or not issue.decision_relevant:
        return (
            "routine item",
            "The current signal looks closer to routine diligence friction than to a concentrated front-end flag.",
        )

    seriousness = 0
    seriousness += 3 if issue.blocking_flag else 0
    seriousness += 2 if issue.critical_path_flag else 0
    seriousness += 2 if issue.materiality == "high" else 1 if issue.materiality == "medium" else 0
    seriousness += 1 if issue.decision_relevant else 0
    seriousness += 1 if issue.issue_strength == "strong" else 0
    seriousness += 1 if issue.false_positive_risk == "low" else 0
    seriousness += 1 if issue.priority_score.total >= 95 else 0
    seriousness += 1 if issue.schedule_impact_classification in {
        "immediate blocker",
        "pre-close blocker",
        "pre-underwriting blocker",
    } else 0
    if seriousness >= 8:
        return (
            "red flag",
            "Direct evidence shows this issue is both real and close enough to the critical path that it should stand out in screening.",
        )
    if seriousness >= 5:
        return (
            "yellow flag",
            "The issue appears real and decision-relevant, but it does not yet read like a hard stop.",
        )
    return (
        "routine item",
        "The current support does not justify elevating this lane above routine process friction.",
    )


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


def _supported_top_issue_count(analysis: DocumentAnalysis, registry: CanonicalIssueRegistry) -> int:
    aliases = _analysis_aliases(analysis)
    count = 0
    for issue in registry.issues:
        if issue.front_end_flag not in {"red flag", "yellow flag", "conflict / contradiction concern"}:
            continue
        issue_aliases = {name.lower() for name in issue.source_documents}
        issue_aliases.update(citation.document_name.lower() for citation in issue.citations)
        if aliases.intersection(issue_aliases) or issue.category in analysis.focus_areas:
            count += 1
    return count


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
    support_count: int,
    legal_significance: bool,
) -> str:
    if (
        analysis.contradiction_count
        or (analysis.document_role == "primary" and legal_significance and support_count)
        or score >= 105
        or (analysis.confidence == "low" and analysis.document_role == "primary")
    ):
        return "must read personally"
    if score >= 82 or support_count or analysis.staleness_status == "stale and potentially unreliable":
        return "should skim"
    return "safe to rely on agent"


def _reading_reason_from_factors(analysis: DocumentAnalysis) -> str:
    factor_text = ", ".join(analysis.reading_rationale_factors[:4]) or "general package coverage"
    return (
        f"{analysis.reading_bucket.title()} because this document carries {factor_text}. "
        f"Confidence is {analysis.confidence}."
    )


def _package_quality(
    *,
    contradictions: list[ContradictionFinding],
    stale_docs: list[DocumentAnalysis],
    missing_important: list[OmissionAssessment],
    low_confidence_primary: list[DocumentAnalysis],
) -> tuple[str, str]:
    if contradictions and (missing_important or low_confidence_primary):
        return (
            "selectively presented",
            "The package has material conflicts and does not include enough current controlling support to cleanly resolve them.",
        )
    if len(stale_docs) >= 2:
        return (
            "stale",
            "Too much of the primary support appears dated for a confident current read.",
        )
    if len(missing_important) >= 2 or len(low_confidence_primary) >= 2:
        return (
            "thin",
            "Important source documents are missing, weak, or unreadable, so the package still leaves major blind spots.",
        )
    return (
        "credible",
        "The package contains enough current direct support to form a meaningful first-pass read, even if follow-up work remains.",
    )


def _front_end_known_points(real_flags: list[CanonicalIssue], registry: CanonicalIssueRegistry) -> list[str]:
    points = [
        f"{issue.title}: {(issue.core_facts[0] if issue.core_facts else issue.likely_implication)}"
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
        f"{issue.title}: {issue.front_end_flag_reason}"
        for issue in routine_items[:3]
    )


def _front_end_deeper_work(real_flags: list[CanonicalIssue], blind_spots: list[CanonicalIssue]) -> list[str]:
    points: list[str] = []
    for issue in [*real_flags[:3], *blind_spots[:2]]:
        if issue.research_agenda:
            step = issue.research_agenda[0]
            points.append(
                f"{issue.title}: verify {step.verify_what}; request {step.request_item}; use {step.likely_source} ({step.timing})."
            )
    return unique_preserve_order(points)[:5]


def _issue_roadmap_line(issue: CanonicalIssue) -> str:
    blocked = issue.downstream_dependencies[0].title if issue.downstream_dependencies else "downstream diligence confidence"
    return (
        f"{issue.title}: {issue.front_end_flag}. "
        f"Why it matters: {issue.why_it_matters} "
        f"What it blocks: {blocked.lower()}."
    )


def _omission_roadmap_line(assessment: OmissionAssessment) -> str:
    return (
        f"{assessment.item}: {assessment.front_end_status}. "
        f"Request {assessment.recommended_request.lower()}."
    )


def _build_follow_up_order(
    *,
    reading_order: list[ReadingRecommendation],
    omission_assessments: list[OmissionAssessment],
    contradictions: list[ContradictionFinding],
    research_lines: list[str],
) -> list[str]:
    steps: list[str] = []
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
    if issue.front_end_flag in {"red flag", "conflict / contradiction concern"}:
        return "now"
    if issue.schedule_impact_classification in {"immediate blocker", "pre-close blocker"}:
        return "now"
    if issue.schedule_impact_classification == "pre-underwriting blocker" or issue.decision_action in {
        "condition closing",
        "reprice",
    }:
        return "before underwriting"
    return "before deeper pursuit"


def _recommended_request_for_omission(assessment: OmissionAssessment) -> str:
    if assessment.front_end_status == "stale and potentially unreliable":
        return f"a refreshed {assessment.item.lower()}"
    return f"a current, readable {assessment.item.lower()}"
