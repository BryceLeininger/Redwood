"""Canonical issue registry, scoring, and selection helpers."""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Callable

from land_due_diligence_agent.analysis.evaluator import (
    build_evaluator_adjustments,
    evaluate_registry,
    should_revise_registry,
)
from land_due_diligence_agent.analysis.risk_rules import (
    EXPECTED_DILIGENCE_ITEMS,
    EXPECTED_DILIGENCE_PATH_HINTS,
)
from land_due_diligence_agent.models import (
    CanonicalIssue,
    CanonicalIssueRegistry,
    ChallengeFinding,
    Citation,
    ContradictionFinding,
    DealMetadata,
    DocumentAnalysis,
    IssueAnalysis,
    IssueFragment,
    IssuePriorityScore,
    MergeDecision,
    MergeArbitrationRecord,
    OmissionAssessment,
    OutputIssueSelection,
    PrecedentCalibration,
    PrecedentReference,
    PriorityAssessment,
    PriorityCallout,
    PriorityWeights,
    RecommendationDecision,
    ReviewerIssueFeedback,
    RiskFinding,
)
from land_due_diligence_agent.utils.files import slugify
from land_due_diligence_agent.utils.text import clip_text, unique_preserve_order

_LEVEL_SCORE = {"low": 1, "medium": 3, "high": 5}
_CONFIDENCE_SCORE = {"low": 1, "medium": 3, "high": 5}
_FIXABILITY_SCORE = {"low": 5, "medium": 3, "high": 1}
_STATUS_PRIORITY = {
    "conflicted": 5,
    "not found": 4,
    "unclear whether present": 3,
    "present but weak": 2,
    "open": 2,
    "partially resolved": 1,
}
_CATEGORY_PRIORITY = {
    "Title / Access Concerns": 100,
    "Entitlement Status": 95,
    "Environmental Risks": 92,
    "Geotechnical Risks": 91,
    "Flood / Drainage Issues": 89,
    "Utilities / Infrastructure Issues": 88,
    "Offsite Obligations": 87,
    "Fee / Exaction Burden": 85,
    "Budget / Cost Reliability": 84,
    "Schedule Risks": 80,
}

_RELATION_ORDER = {
    "separate": 0,
    "related_but_distinct": 1,
    "parent_child": 2,
    "same_issue": 3,
}

MergeArbiter = Callable[[IssueFragment, IssueFragment], tuple[str, str] | None]
PrecedentRetriever = Callable[[CanonicalIssue], PrecedentCalibration | None]

_ALLOWED_CROSS_CATEGORY_MERGES = {
    frozenset({"Budget / Cost Reliability", "Title / Access Concerns"}),
    frozenset({"Budget / Cost Reliability", "Geotechnical Risks"}),
    frozenset({"Budget / Cost Reliability", "Utilities / Infrastructure Issues"}),
    frozenset({"Budget / Cost Reliability", "Offsite Obligations"}),
    frozenset({"Budget / Cost Reliability", "Fee / Exaction Burden"}),
    frozenset({"Schedule Risks", "Title / Access Concerns"}),
    frozenset({"Schedule Risks", "Entitlement Status"}),
    frozenset({"Schedule Risks", "Utilities / Infrastructure Issues"}),
    frozenset({"Schedule Risks", "Offsite Obligations"}),
    frozenset({"Schedule Risks", "Flood / Drainage Issues"}),
    frozenset({"Schedule Risks", "Geotechnical Risks"}),
    frozenset({"Schedule Risks", "Environmental Risks"}),
}


def _contains_any_term(text: str, terms: tuple[str, ...]) -> bool:
    normalized = f" {text.lower()} "
    for term in terms:
        pattern = r"\b" + re.escape(term.lower()) + r"\b"
        if re.search(pattern, normalized):
            return True
    return False


@dataclass(frozen=True, slots=True)
class _CoverageRule:
    item: str
    category: str
    keywords: tuple[str, ...]
    path_hints: tuple[str, ...]


_COVERAGE_RULES: tuple[_CoverageRule, ...] = (
    _CoverageRule(
        item="Current title commitment or title report",
        category="Title / Access Concerns",
        keywords=EXPECTED_DILIGENCE_ITEMS["Current title commitment or title report"],
        path_hints=EXPECTED_DILIGENCE_PATH_HINTS["Current title commitment or title report"],
    ),
    _CoverageRule(
        item="ALTA or boundary survey",
        category="Title / Access Concerns",
        keywords=EXPECTED_DILIGENCE_ITEMS["ALTA or boundary survey"],
        path_hints=EXPECTED_DILIGENCE_PATH_HINTS["ALTA or boundary survey"],
    ),
    _CoverageRule(
        item="Environmental report (Phase I / wetlands)",
        category="Environmental Risks",
        keywords=EXPECTED_DILIGENCE_ITEMS["Environmental report (Phase I / wetlands)"],
        path_hints=EXPECTED_DILIGENCE_PATH_HINTS["Environmental report (Phase I / wetlands)"],
    ),
    _CoverageRule(
        item="Geotechnical report",
        category="Geotechnical Risks",
        keywords=EXPECTED_DILIGENCE_ITEMS["Geotechnical report"],
        path_hints=EXPECTED_DILIGENCE_PATH_HINTS["Geotechnical report"],
    ),
    _CoverageRule(
        item="Floodplain or drainage study",
        category="Flood / Drainage Issues",
        keywords=EXPECTED_DILIGENCE_ITEMS["Floodplain or drainage study"],
        path_hints=EXPECTED_DILIGENCE_PATH_HINTS["Floodplain or drainage study"],
    ),
    _CoverageRule(
        item="Utility availability / will-serve documentation",
        category="Utilities / Infrastructure Issues",
        keywords=EXPECTED_DILIGENCE_ITEMS["Utility availability / will-serve documentation"]
        + ("will-serve", "will serve letter"),
        path_hints=EXPECTED_DILIGENCE_PATH_HINTS["Utility availability / will-serve documentation"],
    ),
    _CoverageRule(
        item="Entitlement or zoning support",
        category="Entitlement Status",
        keywords=EXPECTED_DILIGENCE_ITEMS["Entitlement or zoning support"],
        path_hints=EXPECTED_DILIGENCE_PATH_HINTS["Entitlement or zoning support"],
    ),
    _CoverageRule(
        item="Fee schedule or exaction matrix",
        category="Fee / Exaction Burden",
        keywords=EXPECTED_DILIGENCE_ITEMS["Fee schedule or exaction matrix"],
        path_hints=EXPECTED_DILIGENCE_PATH_HINTS["Fee schedule or exaction matrix"],
    ),
    _CoverageRule(
        item="Site development budget or bid backup",
        category="Budget / Cost Reliability",
        keywords=EXPECTED_DILIGENCE_ITEMS["Site development budget or bid backup"],
        path_hints=EXPECTED_DILIGENCE_PATH_HINTS["Site development budget or bid backup"],
    ),
    _CoverageRule(
        item="Updated geotechnical confirmation",
        category="Geotechnical Risks",
        keywords=("geotechnical addendum", "geotechnical update", "soils update", "recommendation update"),
        path_hints=("geotechnical", "geotech", "soils"),
    ),
    _CoverageRule(
        item="Agency correspondence log",
        category="Entitlement Status",
        keywords=("agency correspondence", "city comments", "planning comments", "staff comments", "agency email"),
        path_hints=("comments", "correspondence", "review"),
    ),
    _CoverageRule(
        item="Detailed conditions-of-approval tracker",
        category="Entitlement Status",
        keywords=("conditions tracker", "conditions of approval tracker", "coa tracker", "condition status"),
        path_hints=("condition", "tracker", "coa"),
    ),
    _CoverageRule(
        item="Title exception synthesis",
        category="Title / Access Concerns",
        keywords=("title exception matrix", "title exception summary", "exception synthesis"),
        path_hints=("title", "exception", "survey"),
    ),
    _CoverageRule(
        item="Offsite improvement scope confirmation",
        category="Offsite Obligations",
        keywords=("offsite scope", "frontage scope", "improvement scope", "offsite improvement"),
        path_hints=("offsite", "frontage", "improvement"),
    ),
    _CoverageRule(
        item="Entitlement expiration or extension summary",
        category="Entitlement Status",
        keywords=("expiration", "extension", "extended", "expiration date"),
        path_hints=("entitlement", "resolution", "extension"),
    ),
)

_ISSUE_TEMPLATE_BY_KEY = {
    "title_access_clearance": {
        "title": "Title and access clearance is not closed",
        "category": "Title / Access Concerns",
        "resolve": "Deliver a title exception matrix reconciled to the current plan set and clear every exception by cure, endorsement, or redesign.",
        "action": "condition closing",
        "fixability": "medium",
    },
    "entitlement_conditions": {
        "title": "Approval status is ahead of condition closeout",
        "category": "Entitlement Status",
        "resolve": "Provide a live conditions and permit tracker showing every remaining trigger to map recordation, grading permit, building permit, and vertical start.",
        "action": "condition closing",
        "fixability": "medium",
    },
    "geotechnical_scope": {
        "title": "Geotechnical recommendations still control site scope",
        "category": "Geotechnical Risks",
        "resolve": "Confirm the active geotechnical recommendations and show where each one is carried into grading, retaining, foundation, and contingency assumptions.",
        "action": "verify",
        "fixability": "medium",
    },
    "geotech_budget_alignment": {
        "title": "Geotechnical scope is not reconciled to budget",
        "category": "Budget / Cost Reliability",
        "resolve": "Reconcile soils-driven grading, retaining, and foundation scope into the current site-development budget with auditable backup.",
        "action": "reprice",
        "fixability": "medium",
    },
    "stormwater_drainage": {
        "title": "Stormwater and drainage scope is not fully closed",
        "category": "Flood / Drainage Issues",
        "resolve": "Provide the current drainage scope memo and identify what still requires civil redesign, detention work, or public-works confirmation.",
        "action": "verify",
        "fixability": "medium",
    },
    "fee_stack": {
        "title": "Fee stack is not locked",
        "category": "Fee / Exaction Burden",
        "resolve": "Replace estimated fees with a current city-confirmed fee matrix and quantify any exposure if schedule slips.",
        "action": "reprice",
        "fixability": "high",
    },
    "offsite_frontage": {
        "title": "Offsite and frontage scope is still buyer-facing",
        "category": "Offsite Obligations",
        "resolve": "Provide one closing-ready offsite scope schedule showing each frontage or offsite obligation, cost owner, timing trigger, and permit dependency.",
        "action": "restructure",
        "fixability": "medium",
    },
    "utility_capacity": {
        "title": "Utility capacity and provider confirmation remain open",
        "category": "Utilities / Infrastructure Issues",
        "resolve": "Provide current will-serve or provider confirmation and show any remaining upsizing, joint-trench, or offsite utility obligations.",
        "action": "condition closing",
        "fixability": "medium",
    },
    "environmental_followup": {
        "title": "Environmental follow-up is not fully closed",
        "category": "Environmental Risks",
        "resolve": "State whether contamination, mitigation, habitat, or agency follow-up remains open and quantify the residual scope, cost, and timing exposure.",
        "action": "verify",
        "fixability": "medium",
    },
    "budget_reliability": {
        "title": "Cost package is still budgetary",
        "category": "Budget / Cost Reliability",
        "resolve": "Replace budgetary pricing and unreadable backup with auditable bids, assumptions, and contingency logic.",
        "action": "reprice",
        "fixability": "high",
    },
    "schedule_path": {
        "title": "Critical path still relies on unconfirmed assumptions",
        "category": "Schedule Risks",
        "resolve": "Rebuild the critical path using only confirmed approvals, utility releases, offsite triggers, and pricing assumptions.",
        "action": "monitor",
        "fixability": "medium",
    },
}

_PRIORITY_DIMENSIONS_BY_KEY = {
    "title_access_clearance": (2, 2, 1, 4, 5, 4, 2, 5),
    "entitlement_conditions": (2, 5, 3, 5, 3, 5, 2, 5),
    "geotechnical_scope": (4, 3, 2, 1, 1, 3, 2, 4),
    "geotech_budget_alignment": (5, 3, 2, 1, 1, 4, 2, 5),
    "stormwater_drainage": (3, 4, 1, 2, 1, 3, 2, 3),
    "fee_stack": (4, 2, 0, 1, 1, 2, 3, 4),
    "offsite_frontage": (4, 4, 1, 2, 3, 4, 3, 4),
    "utility_capacity": (3, 5, 1, 3, 2, 4, 3, 4),
    "environmental_followup": (3, 3, 2, 3, 2, 4, 2, 4),
    "budget_reliability": (4, 2, 0, 0, 0, 2, 1, 4),
    "schedule_path": (2, 4, 0, 1, 1, 3, 2, 3),
}


def build_omission_assessments(document_analyses: list[DocumentAnalysis]) -> list[OmissionAssessment]:
    """Assess whether expected diligence items are present and usable."""

    assessments: list[OmissionAssessment] = []
    for rule in _COVERAGE_RULES:
        relevant = _matching_analyses_for_rule(document_analyses, rule)
        path_hits = [
            analysis
            for analysis in relevant
            if any(hint in analysis.document.relative_path.as_posix().lower() for hint in rule.path_hints)
        ]
        readable = [analysis for analysis in relevant if analysis.confidence in {"high", "medium"}]
        focused = [analysis for analysis in relevant if rule.category in analysis.focus_areas]

        if not relevant:
            status = "not found"
            rationale = f"No document in the package clearly provides {rule.item.lower()}."
        elif not path_hits and not focused:
            status = "unclear whether present"
            rationale = f"{rule.item} is referenced indirectly, but the package does not contain a clearly identifiable source file for it."
        elif not readable:
            status = "present but weak"
            rationale = f"The package contains some support for {rule.item.lower()}, but extraction quality or document readability is too weak to rely on it."
        elif all(analysis.confidence == "medium" for analysis in readable):
            status = "present but weak"
            rationale = f"{rule.item} appears to be present, but the support is still weak enough that it should not be treated as decision-grade."
        else:
            status = "present and adequate"
            rationale = f"{rule.item} appears to be present in a readable form."

        source_documents = unique_preserve_order(analysis.document.title for analysis in relevant)[:3]
        citations = _citations_from_analyses(relevant)[:3]
        assessments.append(
            OmissionAssessment(
                item=rule.item,
                category=rule.category,
                status=status,
                rationale=rationale,
                source_documents=source_documents,
                citations=citations,
            )
        )

    return assessments


def build_canonical_issue_registry(
    *,
    key_risks: list[RiskFinding],
    contradictions: list[ContradictionFinding],
    omission_assessments: list[OmissionAssessment],
    document_analyses: list[DocumentAnalysis],
    weights: PriorityWeights | None = None,
    merge_arbiter: MergeArbiter | None = None,
    precedent_retriever: PrecedentRetriever | None = None,
    deal_metadata: DealMetadata | None = None,
) -> CanonicalIssueRegistry:
    """Build the canonical issue registry from raw deal signals."""

    weights = weights or PriorityWeights()
    fragments = _build_issue_fragments(
        key_risks=key_risks,
        contradictions=contradictions,
        omission_assessments=omission_assessments,
        document_analyses=document_analyses,
    )
    issues, merge_decisions, arbitration_records = _merge_issue_fragments(
        fragments,
        merge_arbiter=merge_arbiter,
    )
    _calibrate_canonical_issues(
        issues,
        omission_assessments=omission_assessments,
        precedent_retriever=precedent_retriever,
    )
    scored_issues = _score_canonical_issues(issues, weights)
    registry = CanonicalIssueRegistry(
        fragments=fragments,
        issues=scored_issues,
        merge_decisions=merge_decisions,
        arbitration_records=arbitration_records,
        omission_assessments=omission_assessments,
        weights=weights,
        deal_metadata=deal_metadata or DealMetadata(),
    )
    _evaluate_and_revise_registry(registry)
    return registry


def build_issue_analyses_from_registry(registry: CanonicalIssueRegistry) -> list[IssueAnalysis]:
    """Derive appendix-friendly issue analyses from canonical issues."""

    analyses: list[IssueAnalysis] = []
    for issue in registry.issues:
        analyses.append(
            IssueAnalysis(
                category=issue.category,
                label=issue.title,
                core_facts=[],
                unresolved_questions=issue.open_questions[:4],
                why_it_matters=issue.why_it_matters,
                likely_implication=issue.likely_implication,
                confidence=issue.confidence,
                citations=issue.citations[:4],
                source_documents=issue.source_documents[:4],
                priority_score=issue.priority_score.total,
                decision_summary=issue.title,
            )
        )
    return analyses


def build_priority_assessment_from_registry(registry: CanonicalIssueRegistry) -> PriorityAssessment:
    """Build compatibility priority callouts from canonical issues."""

    issues = [issue for issue in registry.issues if issue.top_line_eligible] or registry.issues
    top_deal_shaping = [_to_priority_callout(issue) for issue in issues[:3]]
    return PriorityAssessment(
        top_deal_shaping_issues=[callout for callout in top_deal_shaping if callout is not None],
        top_cost_risk=_to_priority_callout(_max_issue(issues, lambda issue: issue.priority_score.cost_exposure)),
        top_timing_risk=_to_priority_callout(_max_issue(issues, lambda issue: issue.priority_score.schedule_exposure)),
        top_closability_risk=_to_priority_callout(_max_issue(issues, lambda issue: issue.priority_score.closing_risk)),
    )


def build_category_rollup_from_registry(registry: CanonicalIssueRegistry) -> dict[str, str]:
    """Build a concise category rollup from canonical issues."""

    rollup: dict[str, str] = {}
    for issue in registry.issues:
        if issue.category in rollup:
            continue
        rollup[issue.category] = f"{issue.title}. {issue.likely_implication}".strip()
    return rollup


def build_recommendation_from_registry(registry: CanonicalIssueRegistry) -> RecommendationDecision:
    """Create decision posture, reasons, and conditions from ranked issues."""

    issues = [issue for issue in registry.issues if issue.top_line_eligible] or registry.issues
    if not issues:
        return RecommendationDecision(
            posture="proceed",
            rationale="No concentrated issue was elevated from the current package.",
        )

    top_issues = issues[:3]
    max_closing = max(issue.priority_score.closing_risk for issue in top_issues)
    max_cost = max(issue.priority_score.cost_exposure for issue in top_issues)
    unresolved_title = any(issue.issue_id == "title-access-clearance" for issue in top_issues)
    unsupported_core = any(issue.status in {"not found", "unclear whether present"} for issue in top_issues)
    retrade_signal = any(issue.decision_action in {"reprice", "restructure"} for issue in top_issues)

    if any(issue.decision_action == "treat as fatal" for issue in top_issues):
        posture = "no-go"
    elif unresolved_title and max_closing >= 5 and unsupported_core:
        posture = "pause"
    elif retrade_signal and max_cost >= 4:
        posture = "retrade"
    elif any(issue.gating_flags for issue in top_issues):
        posture = "proceed with conditions"
    else:
        posture = "proceed"

    reasons = [_issue_reason_line(issue) for issue in top_issues[:3]]
    conditions = unique_preserve_order(_issue_condition_line(issue) for issue in top_issues[:3])[:3]
    rationale = (
        f"{posture.title()} is the current posture because the deal is being driven by {', '.join(issue.title.lower() for issue in top_issues[:2])}."
        if len(top_issues) > 1
        else f"{posture.title()} is the current posture because the lead issue is {top_issues[0].title.lower()}."
    )
    return RecommendationDecision(
        posture=posture,
        rationale=rationale,
        reasons=reasons,
        conditions=conditions,
    )


def build_section_selections(
    registry: CanonicalIssueRegistry,
    recommendation: RecommendationDecision,
    *,
    analysis_mode: str,
) -> list[OutputIssueSelection]:
    """Select which issues should feed which output artifacts."""

    del recommendation
    issues = registry.issues
    top_line_issues = [issue for issue in issues if issue.top_line_eligible]
    if analysis_mode == "fast":
        executive_ids = [issue.issue_id for issue in top_line_issues[:3]]
        key_risk_ids = executive_ids
        seller_ids = [issue.issue_id for issue in issues[:3]]
        return _selection_records(
            executive_ids=executive_ids,
            key_risk_ids=key_risk_ids,
            ic_ids=[],
            seller_ids=seller_ids,
            appendix_ids=[issue.issue_id for issue in issues],
        )

    executive_ids = [issue.issue_id for issue in top_line_issues[:4]]
    key_risk_ids = [issue.issue_id for issue in top_line_issues[:5]]
    ic_ids = [issue.issue_id for issue in top_line_issues[:3]]
    seller_ids = [issue.issue_id for issue in issues[:5]]
    appendix_ids = [issue.issue_id for issue in issues]

    selections = _selection_records(
        executive_ids=executive_ids,
        key_risk_ids=key_risk_ids,
        ic_ids=ic_ids,
        seller_ids=seller_ids,
        appendix_ids=appendix_ids,
    )

    bucket_by_issue_id: dict[str, str] = {}
    for issue_id in executive_ids:
        bucket_by_issue_id[issue_id] = "executive"
    for issue_id in key_risk_ids:
        bucket_by_issue_id.setdefault(issue_id, "key_risk")
    for issue in registry.issues:
        issue.output_bucket = bucket_by_issue_id.get(issue.issue_id, "appendix")

    return selections


def build_reviewer_feedback_template(
    registry: CanonicalIssueRegistry,
    *,
    deal_name: str = "",
) -> list[ReviewerIssueFeedback]:
    """Build a structured reviewer-feedback template from canonical issues."""

    return [
        ReviewerIssueFeedback(
            issue_id=issue.issue_id,
            canonical_title=issue.title,
            category=issue.category,
            deal_id=slugify(deal_name or "deal"),
            deal_name=deal_name,
            deal_metadata=registry.deal_metadata,
            evidence_basis=issue.evidence_basis,
            issue_strength=issue.issue_strength,
            false_positive_risk=issue.false_positive_risk,
            model_materiality=issue.materiality,
            model_decision_relevant=issue.decision_relevant,
            model_action=issue.decision_action,
            materiality=issue.materiality,
            decision_relevant=issue.decision_relevant,
            correct_action=issue.decision_action,
        )
        for issue in registry.issues
    ]


def build_adversarial_challenges_from_registry(
    *,
    registry: CanonicalIssueRegistry,
    document_analyses: list[DocumentAnalysis],
) -> list[ChallengeFinding]:
    """Build a sharper adversarial pass from canonical issues and omissions."""

    issues = registry.issues
    challenges: list[ChallengeFinding] = []

    unsupported_issues = [
        issue
        for issue in issues
        if issue.confidence != "high" or issue.status in {"not found", "unclear whether present", "present but weak"}
    ]
    for issue in unsupported_issues[:2]:
        challenges.append(
            ChallengeFinding(
                heading="Unsupported Assumption",
                concern=f"The current view on {issue.title.lower()} still leans on incomplete or weak support.",
                why_it_matters=f"That weakens the recommendation because {issue.why_it_matters.lower()}",
                likely_pushback=f"IC is likely to ask why money is being committed before {issue.what_would_resolve_it.lower()}",
                citations=issue.citations[:3],
                source_documents=issue.source_documents[:3],
                priority=issue.priority_score.total,
            )
        )

    cost_issue = _max_issue(issues, lambda issue: issue.priority_score.cost_exposure)
    if cost_issue is not None:
        challenges.append(
            ChallengeFinding(
                heading="Understated Cost Risk",
                concern=f"The downside on {cost_issue.title.lower()} is likely larger than the current package implies if the issue is not repriced pre-close.",
                why_it_matters=cost_issue.likely_implication,
                likely_pushback="IC is likely to ask what protects basis if the current cost assumption is wrong.",
                citations=cost_issue.citations[:2],
                source_documents=cost_issue.source_documents[:2],
                priority=cost_issue.priority_score.total - 1,
            )
        )

    hard_money_blockers = [
        issue
        for issue in issues
        if issue.decision_action in {"condition closing", "reprice", "treat as fatal"} and issue.priority_score.total >= 80
    ]
    for issue in hard_money_blockers[:2]:
        challenges.append(
            ChallengeFinding(
                heading="Hard Money Release Blocker",
                concern=f"Hard money should not be released while {issue.title.lower()} remains open.",
                why_it_matters=issue.what_would_resolve_it,
                likely_pushback="IC is likely to ask what specific pre-close condition prevents this issue from slipping into post-close cleanup.",
                citations=issue.citations[:2],
                source_documents=issue.source_documents[:2],
                priority=issue.priority_score.total,
            )
        )

    low_confidence_docs = [analysis for analysis in document_analyses if analysis.confidence == "low"]
    if low_confidence_docs:
        analysis = low_confidence_docs[0]
        challenges.append(
            ChallengeFinding(
                heading="False Confidence Risk",
                concern=f"{analysis.document.title} still extracted weakly, so one part of the recommendation may look more supported than it actually is.",
                why_it_matters="Unreadable support can hide scope, cost, or legal exposure until late in the process.",
                likely_pushback=f"IC is likely to ask why {analysis.document.title} was not replaced before the package was treated as recommendation-grade.",
                citations=[],
                source_documents=[analysis.document.title],
                priority=84,
            )
        )

    challenges.sort(key=lambda item: (-item.priority, item.heading, item.concern))
    deduped: list[ChallengeFinding] = []
    seen: set[tuple[str, str]] = set()
    for challenge in challenges:
        key = (challenge.heading, challenge.concern)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(challenge)
    return deduped[:5]


def build_overall_read_draft(
    *,
    deal_name: str,
    registry: CanonicalIssueRegistry,
    recommendation: RecommendationDecision,
    entitlement_status: str,
    challenge_findings: list[ChallengeFinding],
) -> str:
    """Build a short overall read from canonical issues only."""

    issues = ([issue for issue in registry.issues if issue.top_line_eligible] or registry.issues)[:3]
    if not issues:
        return f"{deal_name} does not currently present a concentrated diligence issue, but the package should still be checked for completeness."

    issue_text = "; ".join(
        f"{issue.title.lower()} ({issue.likely_implication.lower()})"
        for issue in issues[:2]
    )
    challenge_text = (
        f" The main pushback is that {challenge_findings[0].concern.lower()}"
        if challenge_findings
        else ""
    )
    return (
        f"{deal_name} currently reads as '{recommendation.posture}'. {entitlement_status} "
        f"The recommendation is being driven by {issue_text}.{challenge_text}"
    ).strip()


def build_seller_questions_from_registry(registry: CanonicalIssueRegistry) -> list[str]:
    """Build negotiation and verification questions from canonical issues."""

    questions: list[str] = []
    for issue in registry.issues[:6]:
        source_hint = _source_hint(issue.citations[:2], issue.source_documents[:2])
        questions.append(
            f"Please confirm how {issue.title.lower()} is being resolved, provide the current support, and state exactly what clears it for underwriting.{source_hint}"
        )
        if issue.what_would_resolve_it:
            questions.append(f"What current document or deliverable satisfies this condition: {issue.what_would_resolve_it}{source_hint}")

    return unique_preserve_order(questions)[:8]


def _matching_analyses_for_rule(
    document_analyses: list[DocumentAnalysis],
    rule: _CoverageRule,
) -> list[DocumentAnalysis]:
    matches: list[DocumentAnalysis] = []
    for analysis in document_analyses:
        rel_path = analysis.document.relative_path.as_posix().lower()
        title = analysis.document.title.lower()
        text = analysis.document.normalized_text.lower()
        if any(hint in rel_path for hint in rule.path_hints):
            matches.append(analysis)
            continue
        if any(keyword in title or keyword in text for keyword in rule.keywords):
            matches.append(analysis)
            continue
        if rule.category in analysis.focus_areas:
            matches.append(analysis)
    return matches


def _citations_from_analyses(document_analyses: list[DocumentAnalysis]) -> list[Citation]:
    citations: list[Citation] = []
    for analysis in document_analyses:
        for risk in analysis.risks:
            citations.extend(risk.citations[:2])
        if not citations:
            citations.extend(_document_chunk_citations(analysis.document))
    return _unique_citations(citations)


def _build_issue_fragments(
    *,
    key_risks: list[RiskFinding],
    contradictions: list[ContradictionFinding],
    omission_assessments: list[OmissionAssessment],
    document_analyses: list[DocumentAnalysis],
) -> list[IssueFragment]:
    fragments: list[IssueFragment] = []

    for index, risk in enumerate(key_risks, start=1):
        dependency_key = _dependency_key_for_risk(risk)
        template = _template_for_key(dependency_key, risk.category)
        fragments.append(
            IssueFragment(
                fragment_id=f"risk-{index:02d}-{slugify(risk.category)}",
                source_type="risk",
                title=template["title"],
                category=template["category"],
                dependency_key=dependency_key,
                status="open",
                core_facts=unique_preserve_order(risk.evidence[:3]),
                best_evidence=unique_preserve_order(([risk.anchor] if risk.anchor else []) + risk.evidence[:2]),
                why_it_matters=risk.why_it_matters or risk.summary,
                likely_implication=risk.likely_implication or risk.summary,
                what_would_resolve_it=template["resolve"],
                open_questions=_risk_open_questions(risk),
                confidence=_confidence_from_risk(risk),
                severity=risk.severity,
                likelihood=_likelihood_from_risk(risk),
                timing_sensitivity=_timing_from_risk(risk),
                cost_sensitivity=_cost_from_risk(risk),
                fixability=template["fixability"],
                decision_action=template["action"],
                citations=risk.citations[:4],
                source_documents=risk.source_documents[:4],
                gating_flags=risk.gating_flags[:],
            )
        )

    for index, contradiction in enumerate(contradictions, start=1):
        dependency_key = _dependency_key_for_contradiction(contradiction)
        template = _template_for_key(
            dependency_key,
            contradiction.related_categories[0] if contradiction.related_categories else "Schedule Risks",
        )
        fragments.append(
            IssueFragment(
                fragment_id=f"contradiction-{index:02d}-{slugify(dependency_key)}",
                source_type="contradiction",
                title=template["title"],
                category=template["category"],
                dependency_key=dependency_key,
                status="conflicted",
                core_facts=[contradiction.description],
                best_evidence=[contradiction.description],
                why_it_matters=contradiction.why_it_matters,
                likely_implication=_likely_implication_from_contradiction(contradiction),
                what_would_resolve_it=template["resolve"],
                open_questions=_contradiction_open_questions(contradiction),
                confidence="high" if contradiction.citations else "medium",
                severity="high" if contradiction.priority >= 90 else "medium",
                likelihood="high",
                timing_sensitivity=_timing_from_categories(contradiction.related_categories),
                cost_sensitivity=_cost_from_categories(contradiction.related_categories),
                fixability=template["fixability"],
                decision_action=template["action"],
                citations=contradiction.citations[:4],
                source_documents=contradiction.source_documents[:4],
                gating_flags=_gating_from_categories(contradiction.related_categories),
            )
        )

    for index, omission in enumerate(omission_assessments, start=1):
        if omission.status == "present and adequate":
            continue
        dependency_key = _dependency_key_for_omission(omission)
        template = _template_for_key(dependency_key, omission.category)
        fragments.append(
            IssueFragment(
                fragment_id=f"omission-{index:02d}-{slugify(omission.item)}",
                source_type="omission",
                title=template["title"],
                category=template["category"],
                dependency_key=dependency_key,
                status=omission.status,
                core_facts=[omission.rationale],
                best_evidence=[omission.rationale],
                why_it_matters=_why_omission_matters(omission),
                likely_implication=_implication_from_omission(omission),
                what_would_resolve_it=_resolve_line_for_omission(omission, template["resolve"]),
                open_questions=[f"Has {omission.item.lower()} been produced in a current, readable form?"],
                confidence="low" if omission.status != "present but weak" else "medium",
                severity="high" if omission.status == "not found" else "medium",
                likelihood="high" if omission.status in {"not found", "unclear whether present"} else "medium",
                timing_sensitivity=_timing_from_categories([omission.category]),
                cost_sensitivity=_cost_from_categories([omission.category]),
                fixability=template["fixability"],
                decision_action=_action_for_omission(omission, template["action"]),
                citations=omission.citations[:3],
                source_documents=omission.source_documents[:3],
                gating_flags=_gating_from_categories([omission.category]),
            )
        )

    if not fragments:
        fragments.extend(_fallback_fragments_from_documents(document_analyses))

    return fragments


def _resolve_fragment_groups(
    by_key: dict[str, list[IssueFragment]],
    *,
    merge_arbiter: MergeArbiter | None,
) -> tuple[list[tuple[str, list[IssueFragment]]], list[MergeArbitrationRecord]]:
    groups = [(dependency_key, fragments[:]) for dependency_key, fragments in by_key.items()]
    records: list[MergeArbitrationRecord] = []
    seen_pairs: set[tuple[str, str]] = set()

    merged = True
    while merged and len(groups) > 1:
        merged = False
        for left_index in range(len(groups)):
            if merged:
                break
            for right_index in range(left_index + 1, len(groups)):
                left_key, left_fragments = groups[left_index]
                right_key, right_fragments = groups[right_index]
                pair_key = tuple(sorted((left_key, right_key)))
                if pair_key in seen_pairs:
                    continue
                seen_pairs.add(pair_key)
                relation, confidence, rationale, used_arbiter = _classify_group_relation(
                    left_fragments,
                    right_fragments,
                    merge_arbiter=merge_arbiter,
                )
                if used_arbiter or relation in {"same_issue", "parent_child"}:
                    records.append(
                        MergeArbitrationRecord(
                            left_key=left_key,
                            right_key=right_key,
                            deterministic_relation=relation if not used_arbiter else "ambiguous",
                            deterministic_confidence=confidence,
                            final_relation=relation,
                            used_arbiter=used_arbiter,
                            rationale=rationale,
                        )
                    )
                if relation in {"same_issue", "parent_child"}:
                    merged_fragments = left_fragments + right_fragments
                    groups[left_index] = (_dominant_dependency_key(merged_fragments), merged_fragments)
                    del groups[right_index]
                    seen_pairs = set()
                    merged = True
                    break

    return groups, records


def _classify_group_relation(
    left_fragments: list[IssueFragment],
    right_fragments: list[IssueFragment],
    *,
    merge_arbiter: MergeArbiter | None,
) -> tuple[str, str, str, bool]:
    left_rep = _representative_fragment(left_fragments)
    right_rep = _representative_fragment(right_fragments)
    relation, confidence, rationale = _deterministic_group_relation(left_fragments, right_fragments)
    if confidence == "low" and merge_arbiter is not None:
        arbitration = merge_arbiter(left_rep, right_rep)
        if arbitration is not None:
            arbiter_relation, arbiter_rationale = arbitration
            return arbiter_relation, confidence, arbiter_rationale, True
    return relation, confidence, rationale, False


def _deterministic_group_relation(
    left_fragments: list[IssueFragment],
    right_fragments: list[IssueFragment],
) -> tuple[str, str, str]:
    left_rep = _representative_fragment(left_fragments)
    right_rep = _representative_fragment(right_fragments)
    if left_rep.dependency_key == right_rep.dependency_key:
        return "same_issue", "high", "Fragments already share the same dependency key."

    left_categories = {fragment.category for fragment in left_fragments}
    right_categories = {fragment.category for fragment in right_fragments}
    shared_categories = left_categories.intersection(right_categories)
    if not shared_categories and not _cross_category_merge_allowed(left_categories, right_categories):
        return "separate", "medium", "The categories do not belong to a supported cross-category merge pair."
    left_docs = {document for fragment in left_fragments for document in fragment.source_documents}
    right_docs = {document for fragment in right_fragments for document in fragment.source_documents}
    shared_docs = left_docs.intersection(right_docs)
    left_gates = {gate for fragment in left_fragments for gate in fragment.gating_flags}
    right_gates = {gate for fragment in right_fragments for gate in fragment.gating_flags}
    shared_gates = left_gates.intersection(right_gates)
    title_overlap = _token_overlap(left_rep.title, right_rep.title)
    evidence_overlap = _token_overlap(" ".join(left_rep.best_evidence[:2]), " ".join(right_rep.best_evidence[:2]))

    score = 0
    if shared_categories:
        score += 2
    if shared_docs:
        score += 2
    if shared_gates:
        score += 1
    if title_overlap >= 2:
        score += 2
    elif title_overlap == 1:
        score += 1
    if evidence_overlap >= 2:
        score += 1

    if score >= 6:
        return "same_issue", "high", "Category, source, and title signals indicate one underlying issue."
    if score >= 4:
        return "parent_child", "low", "Signals overlap materially, but the dependency split may still be distinct."
    if score >= 2:
        return "related_but_distinct", "low", "Issues overlap on some signals but are not clearly the same problem."
    return "separate", "medium", "The fragments do not share enough category, source, or evidence overlap to merge."


def _representative_fragment(fragments: list[IssueFragment]) -> IssueFragment:
    return sorted(
        fragments,
        key=lambda fragment: (
            -_STATUS_PRIORITY.get(fragment.status, 0),
            -_LEVEL_SCORE.get(fragment.severity, 0),
            -_CONFIDENCE_SCORE.get(fragment.confidence, 0),
            fragment.fragment_id,
        ),
    )[0]


def _dominant_dependency_key(fragments: list[IssueFragment]) -> str:
    representative = _representative_fragment(fragments)
    return representative.dependency_key


def _token_overlap(left_text: str, right_text: str) -> int:
    left_tokens = {token for token in re.findall(r"[a-z0-9]+", left_text.lower()) if len(token) > 3}
    right_tokens = {token for token in re.findall(r"[a-z0-9]+", right_text.lower()) if len(token) > 3}
    return len(left_tokens.intersection(right_tokens))


def _cross_category_merge_allowed(left_categories: set[str], right_categories: set[str]) -> bool:
    for left_category in left_categories:
        for right_category in right_categories:
            if frozenset({left_category, right_category}) in _ALLOWED_CROSS_CATEGORY_MERGES:
                return True
    return False


def _merge_issue_fragments(
    fragments: list[IssueFragment],
    *,
    merge_arbiter: MergeArbiter | None = None,
) -> tuple[list[CanonicalIssue], list[MergeDecision], list[MergeArbitrationRecord]]:
    by_key: dict[str, list[IssueFragment]] = defaultdict(list)
    for fragment in fragments:
        by_key[fragment.dependency_key].append(fragment)

    groups, arbitration_records = _resolve_fragment_groups(
        by_key,
        merge_arbiter=merge_arbiter,
    )
    issues: list[CanonicalIssue] = []
    merge_decisions: list[MergeDecision] = []
    for dependency_key, grouped_fragments in groups:
        ordered_fragments = sorted(
            grouped_fragments,
            key=lambda fragment: (
                -_STATUS_PRIORITY.get(fragment.status, 0),
                -_LEVEL_SCORE.get(fragment.severity, 0),
                -_CONFIDENCE_SCORE.get(fragment.confidence, 0),
                fragment.fragment_id,
            ),
        )
        template = _template_for_key(dependency_key, ordered_fragments[0].category)
        lead_fragment = ordered_fragments[0]
        issue_id = dependency_key.replace("_", "-")
        core_facts = unique_preserve_order(
            fact for fragment in ordered_fragments for fact in fragment.core_facts if fact.strip()
        )[:5]
        best_evidence = unique_preserve_order(
            evidence for fragment in ordered_fragments for evidence in fragment.best_evidence if evidence.strip()
        )[:4]
        citations = _unique_citations(
            [citation for fragment in ordered_fragments for citation in fragment.citations]
        )[:6]
        source_documents = unique_preserve_order(
            document_name
            for fragment in ordered_fragments
            for document_name in fragment.source_documents
            if document_name
        )[:6]
        issues.append(
            CanonicalIssue(
                issue_id=issue_id,
                title=template["title"],
                category=template["category"],
                status=_merge_status(ordered_fragments),
                issue_type=issue_id,
                core_facts=core_facts,
                best_evidence=best_evidence or core_facts[:2],
                why_it_matters=_select_fragment_line(
                    ordered_fragments,
                    "why_it_matters",
                    fallback=lead_fragment.why_it_matters,
                ),
                likely_implication=_select_fragment_line(
                    ordered_fragments,
                    "likely_implication",
                    fallback=lead_fragment.likely_implication,
                ),
                what_would_resolve_it=_select_concise_line(
                    [fragment.what_would_resolve_it for fragment in ordered_fragments],
                    fallback=template["resolve"],
                ),
                open_questions=unique_preserve_order(
                    question
                    for fragment in ordered_fragments
                    for question in fragment.open_questions
                    if question.strip()
                )[:4],
                confidence=_merge_confidence(ordered_fragments, citations),
                severity=_merge_level(ordered_fragments, "severity"),
                likelihood=_merge_level(ordered_fragments, "likelihood"),
                timing_sensitivity=_merge_level(ordered_fragments, "timing_sensitivity"),
                cost_sensitivity=_merge_level(ordered_fragments, "cost_sensitivity"),
                fixability=_select_fixability(ordered_fragments, template["fixability"]),
                decision_action=_select_decision_action(ordered_fragments, template["action"]),
                citations=citations,
                source_documents=source_documents,
                gating_flags=unique_preserve_order(
                    flag
                    for fragment in ordered_fragments
                    for flag in fragment.gating_flags
                    if flag
                )[:4],
                merged_fragment_ids=[fragment.fragment_id for fragment in ordered_fragments],
                merged_fragment_titles=unique_preserve_order(fragment.title for fragment in ordered_fragments),
            )
        )
        merge_decisions.append(
            MergeDecision(
                canonical_issue_id=issue_id,
                dependency_key=dependency_key,
                fragment_ids=[fragment.fragment_id for fragment in ordered_fragments],
                fragment_titles=unique_preserve_order(fragment.title for fragment in ordered_fragments),
                rationale=_merge_rationale(dependency_key, ordered_fragments),
            )
        )

    issues.sort(
        key=lambda issue: (
            -_CATEGORY_PRIORITY.get(issue.category, 0),
            issue.title,
        )
    )
    return issues, merge_decisions, arbitration_records


def _calibrate_canonical_issues(
    issues: list[CanonicalIssue],
    *,
    omission_assessments: list[OmissionAssessment],
    precedent_retriever: PrecedentRetriever | None,
) -> None:
    omission_status_by_issue_id = {
        _dependency_key_for_omission(assessment).replace("_", "-"): assessment.status
        for assessment in omission_assessments
    }
    for issue in issues:
        issue.evidence_basis = _classify_evidence_basis(issue, omission_status_by_issue_id)
        issue.materiality = _classify_materiality(issue)
        issue.normal_friction_flag = _is_normal_friction(issue)
        issue.issue_strength = _classify_issue_strength(issue)
        issue.false_positive_risk = _classify_false_positive_risk(issue)
        issue.decision_relevant = _is_decision_relevant(issue)
        if precedent_retriever is not None:
            calibration = precedent_retriever(issue)
            if calibration is not None:
                issue.precedent_references = calibration.matches
                issue.precedent_summary = calibration.summary
                _apply_precedent_calibration(issue)
        issue.decision_relevant = _is_decision_relevant(issue)
        issue.top_line_filter_reasons = _top_line_filter_reasons(issue)
        issue.top_line_eligible = not issue.top_line_filter_reasons
        issue.calibration_notes = _calibration_notes(issue)


def _classify_evidence_basis(
    issue: CanonicalIssue,
    omission_status_by_issue_id: dict[str, str],
) -> str:
    fragment_ids = issue.merged_fragment_ids
    has_risk = any(fragment_id.startswith("risk-") for fragment_id in fragment_ids)
    has_contradiction = any(fragment_id.startswith("contradiction-") for fragment_id in fragment_ids)
    has_omission = any(fragment_id.startswith("omission-") for fragment_id in fragment_ids)
    has_fallback = any(fragment_id.startswith("fallback-") for fragment_id in fragment_ids)

    if has_contradiction:
        return "contradictory_evidence_present"
    if has_risk:
        if issue.status in {"open", "conflicted", "not found", "unclear whether present", "present but weak"}:
            return "direct_unresolved_risk"
        return "direct_confirmed_risk"
    if has_omission:
        omission_status = omission_status_by_issue_id.get(issue.issue_id, issue.status)
        if omission_status in {"present but weak", "unclear whether present"} and issue.category in {"Entitlement Status", "Schedule Risks"}:
            return "routine_missing_support"
        return "omission_only"
    if has_fallback or not issue.citations:
        return "weak_inference"
    return "direct_confirmed_risk"


def _classify_materiality(issue: CanonicalIssue) -> str:
    if "Closing" in issue.gating_flags or issue.category == "Title / Access Concerns":
        return "high"
    if issue.category in {"Offsite Obligations", "Environmental Risks", "Geotechnical Risks", "Utilities / Infrastructure Issues"}:
        return "high" if issue.evidence_basis in {"direct_unresolved_risk", "contradictory_evidence_present"} else "medium"
    if issue.category in {"Budget / Cost Reliability", "Fee / Exaction Burden", "Flood / Drainage Issues", "Entitlement Status"}:
        return "medium"
    return "low"


def _is_normal_friction(issue: CanonicalIssue) -> bool:
    if issue.evidence_basis == "routine_missing_support":
        return True
    if issue.evidence_basis == "omission_only" and issue.category in {"Entitlement Status", "Schedule Risks"}:
        return True
    if issue.issue_id == "schedule-path" and issue.evidence_basis != "direct_unresolved_risk":
        return True
    return False


def _classify_issue_strength(issue: CanonicalIssue) -> str:
    if issue.evidence_basis in {"direct_confirmed_risk", "direct_unresolved_risk", "contradictory_evidence_present"}:
        if issue.confidence in {"high", "medium"}:
            return "strong"
        return "moderate"
    if issue.evidence_basis == "omission_only":
        return "moderate" if issue.materiality == "high" else "weak"
    if issue.evidence_basis == "routine_missing_support":
        return "weak"
    return "weak"


def _classify_false_positive_risk(issue: CanonicalIssue) -> str:
    if issue.evidence_basis in {"weak_inference", "routine_missing_support"}:
        return "high"
    if issue.evidence_basis == "omission_only":
        return "medium" if issue.materiality == "high" else "high"
    if issue.normal_friction_flag:
        return "high"
    if issue.confidence == "low":
        return "medium"
    return "low"


def _is_decision_relevant(issue: CanonicalIssue) -> bool:
    if (
        issue.precedent_summary.confidence_adjustment == "down"
        and issue.evidence_basis in {"omission_only", "routine_missing_support", "weak_inference"}
    ):
        return False
    if "Closing" in issue.gating_flags:
        return True
    if issue.materiality == "high" and issue.false_positive_risk != "high":
        return True
    if issue.evidence_basis in {"direct_unresolved_risk", "contradictory_evidence_present"} and issue.issue_strength == "strong":
        return True
    if (
        issue.precedent_summary.confidence_adjustment == "up"
        and issue.evidence_basis in {"direct_confirmed_risk", "direct_unresolved_risk", "contradictory_evidence_present"}
        and issue.false_positive_risk != "high"
    ):
        return True
    return False


def _top_line_filter_reasons(issue: CanonicalIssue) -> list[str]:
    reasons: list[str] = []
    if issue.issue_strength == "weak":
        reasons.append("weak issue strength")
    if issue.false_positive_risk == "high":
        reasons.append("high false-positive risk")
    if issue.normal_friction_flag:
        reasons.append("normal process friction")
    if issue.evidence_basis in {"omission_only", "routine_missing_support"} and issue.materiality != "high":
        reasons.append("omission-only without high criticality")
    if not issue.decision_relevant:
        reasons.append("not decision relevant")
    return reasons


def _calibration_notes(issue: CanonicalIssue) -> list[str]:
    notes = [f"evidence basis={issue.evidence_basis}"]
    if issue.normal_friction_flag:
        notes.append("looks closer to routine process friction than a deal-specific problem")
    if issue.evidence_basis == "omission_only":
        notes.append("issue is being inferred from missing support rather than direct conflicting evidence")
    if issue.precedent_summary.sample_size:
        outcome_stats = ", ".join(
            f"{label}={count}"
            for label, count in sorted(issue.precedent_summary.outcome_stats.items())
        ) or "none"
        notes.append(
            "precedent sample="
            f"{issue.precedent_summary.sample_size}, "
            f"historical frequency={issue.precedent_summary.historical_frequency}, "
            f"real rate={_format_precedent_rate(issue.precedent_summary.real_rate)}, "
            f"false-positive rate={_format_precedent_rate(issue.precedent_summary.false_positive_rate)}, "
            f"outcomes={outcome_stats}, "
            f"confidence adjustment={issue.precedent_summary.confidence_adjustment}, "
            f"score adjustment={issue.precedent_summary.score_adjustment:+d}"
        )
    if issue.priority_score.evaluator_adjustment:
        notes.append(f"evaluator rerank adjustment={issue.priority_score.evaluator_adjustment:+d}")
    if issue.top_line_filter_reasons:
        notes.append("filtered from top-line outputs because " + ", ".join(issue.top_line_filter_reasons))
    return notes


def _apply_precedent_calibration(issue: CanonicalIssue) -> None:
    del issue


def _format_precedent_rate(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:.0%}"


def _score_canonical_issues(
    issues: list[CanonicalIssue],
    weights: PriorityWeights,
) -> list[CanonicalIssue]:
    for issue in issues:
        issue.priority_score = _score_issue(issue, weights)
    issues.sort(
        key=lambda issue: (
            -issue.priority_score.total,
            -_STATUS_PRIORITY.get(issue.status, 0),
            issue.title,
        )
    )
    return issues


def _evaluate_and_revise_registry(registry: CanonicalIssueRegistry) -> None:
    registry.initial_issue_order = [issue.issue_id for issue in registry.issues]
    registry.evaluator_result = evaluate_registry(registry)
    if not should_revise_registry(registry.evaluator_result):
        registry.final_issue_order = registry.initial_issue_order.copy()
        return

    registry.evaluator_result.revision_applied = True
    reasons: list[str] = []
    if registry.evaluator_result.redundancy_score >= 40:
        reasons.append("high redundancy")
    if registry.evaluator_result.ranking_quality < 65:
        reasons.append("poor ranking quality")
    registry.evaluator_result.revision_reason = ", ".join(reasons) or "evaluator-triggered rerank"

    secondary_merge_ids = {
        suggestion.secondary_issue_id
        for suggestion in registry.evaluator_result.issues_to_merge
    }
    adjustments = build_evaluator_adjustments(registry, registry.evaluator_result)
    for issue in registry.issues:
        adjustment = adjustments.get(issue.issue_id, 0)
        issue.priority_score.evaluator_adjustment = adjustment
        issue.priority_score.total += adjustment
        if issue.issue_id in registry.evaluator_result.issues_to_remove:
            issue.top_line_filter_reasons = unique_preserve_order(
                [*issue.top_line_filter_reasons, "evaluator-pruned weak or routine issue"]
            )
        if issue.issue_id in secondary_merge_ids:
            issue.top_line_filter_reasons = unique_preserve_order(
                [*issue.top_line_filter_reasons, "evaluator-flagged redundancy"]
            )
        issue.top_line_eligible = not issue.top_line_filter_reasons
        issue.calibration_notes = _calibration_notes(issue)

    registry.issues.sort(
        key=lambda issue: (
            -issue.priority_score.total,
            -_STATUS_PRIORITY.get(issue.status, 0),
            issue.title,
        )
    )
    registry.final_issue_order = [issue.issue_id for issue in registry.issues]


def _score_issue(issue: CanonicalIssue, weights: PriorityWeights) -> IssuePriorityScore:
    base = _PRIORITY_DIMENSIONS_BY_KEY.get(issue.issue_id.replace("-", "_"), (2, 2, 0, 1, 1, 2, 2, 3))
    cost_exposure = max(base[0], _LEVEL_SCORE.get(issue.cost_sensitivity, 0), 5 if issue.decision_action == "reprice" else 0)
    schedule_exposure = max(base[1], _LEVEL_SCORE.get(issue.timing_sensitivity, 0), 5 if "Vertical start" in issue.gating_flags else 0)
    yield_exposure = max(base[2], 3 if issue.category in {"Geotechnical Risks", "Title / Access Concerns"} else 0)
    entitlement_fragility = max(base[3], 4 if issue.category == "Entitlement Status" else 0)
    closing_risk = max(base[4], 5 if "Closing" in issue.gating_flags else 0)
    likelihood = max(base[5], _LEVEL_SCORE.get(issue.likelihood, 0))
    evidence_confidence = _CONFIDENCE_SCORE.get(issue.confidence, 0)
    preclose_mitigation_difficulty = max(base[6], _FIXABILITY_SCORE.get(issue.fixability, 0))
    seller_shiftability = _seller_shiftability(issue)
    ic_sensitivity = max(base[7], 5 if issue.status in {"conflicted", "not found"} else 0)
    calibration_adjustment = _calibration_adjustment(issue)
    precedent_adjustment = issue.precedent_summary.score_adjustment * weights.precedent_signal

    total = (
        cost_exposure * weights.cost_exposure
        + schedule_exposure * weights.schedule_exposure
        + yield_exposure * weights.yield_exposure
        + entitlement_fragility * weights.entitlement_fragility
        + closing_risk * weights.closing_risk
        + likelihood * weights.likelihood
        + evidence_confidence * weights.evidence_confidence
        + preclose_mitigation_difficulty * weights.preclose_mitigation_difficulty
        + seller_shiftability * weights.seller_shiftability_penalty
        + ic_sensitivity * weights.ic_sensitivity
        + calibration_adjustment
        + precedent_adjustment
    )
    return IssuePriorityScore(
        total=total,
        cost_exposure=cost_exposure,
        schedule_exposure=schedule_exposure,
        yield_exposure=yield_exposure,
        entitlement_fragility=entitlement_fragility,
        closing_risk=closing_risk,
        likelihood=likelihood,
        evidence_confidence=evidence_confidence,
        preclose_mitigation_difficulty=preclose_mitigation_difficulty,
        seller_shiftability=seller_shiftability,
        ic_sensitivity=ic_sensitivity,
        calibration_adjustment=calibration_adjustment,
        precedent_adjustment=precedent_adjustment,
        evaluator_adjustment=0,
    )


def _calibration_adjustment(issue: CanonicalIssue) -> int:
    basis_adjustment = {
        "direct_confirmed_risk": 16,
        "direct_unresolved_risk": 22,
        "contradictory_evidence_present": 20,
        "omission_only": -16,
        "weak_inference": -24,
        "routine_missing_support": -30,
    }.get(issue.evidence_basis, 0)
    strength_adjustment = {"strong": 14, "moderate": 0, "weak": -20}.get(issue.issue_strength, 0)
    false_positive_penalty = {"low": 0, "medium": -8, "high": -20}.get(issue.false_positive_risk, 0)
    materiality_adjustment = {"high": 12, "medium": 0, "low": -12}.get(issue.materiality, 0)
    decision_adjustment = 8 if issue.decision_relevant else -18
    friction_penalty = -16 if issue.normal_friction_flag else 0
    return (
        basis_adjustment
        + strength_adjustment
        + false_positive_penalty
        + materiality_adjustment
        + decision_adjustment
        + friction_penalty
    )


def _template_for_key(dependency_key: str, category: str) -> dict[str, str]:
    template = _ISSUE_TEMPLATE_BY_KEY.get(dependency_key)
    if template is not None:
        return template
    return {
        "title": f"{category} issue remains open",
        "category": category,
        "resolve": f"Provide current support that closes the remaining {category.lower()} issue.",
        "action": "verify",
        "fixability": "medium",
    }


def _dependency_key_for_risk(risk: RiskFinding) -> str:
    text = " ".join(
        part
        for part in [
            risk.category,
            risk.issue,
            risk.summary,
            risk.anchor,
            " ".join(risk.evidence[:2]),
        ]
        if part
    ).lower()
    if risk.category == "Title / Access Concerns" or _contains_any_term(text, ("title", "access", "easement", "encroachment")):
        return "title_access_clearance"
    if risk.category == "Environmental Risks" or _contains_any_term(text, ("phase i", "remediation", "contamination", "wetlands", "mitigation")):
        return "environmental_followup"
    if risk.category == "Geotechnical Risks":
        return "geotechnical_scope"
    if risk.category == "Flood / Drainage Issues":
        return "stormwater_drainage"
    if risk.category == "Fee / Exaction Burden":
        return "fee_stack"
    if risk.category == "Offsite Obligations":
        return "offsite_frontage"
    if risk.category == "Utilities / Infrastructure Issues":
        return "utility_capacity"
    if risk.category == "Entitlement Status":
        return "entitlement_conditions"
    if risk.category == "Budget / Cost Reliability":
        if _contains_any_term(text, ("geotech", "grading", "foundation", "retaining", "liquefaction", "soil", "soils")):
            return "geotech_budget_alignment"
        if _contains_any_term(text, ("water", "sewer", "utility", "joint trench", "will serve")):
            return "utility_capacity"
        if _contains_any_term(text, ("frontage", "offsite", "dedication", "encroachment")):
            return "offsite_frontage"
        if _contains_any_term(text, ("fee", "impact fee", "capacity fee", "school fee")):
            return "fee_stack"
        return "budget_reliability"
    if risk.category == "Schedule Risks":
        if _contains_any_term(text, ("water", "sewer", "utility", "joint trench", "will serve")):
            return "utility_capacity"
        if _contains_any_term(text, ("frontage", "offsite", "dedication", "encroachment")):
            return "offsite_frontage"
        if _contains_any_term(text, ("title", "access", "easement", "encroachment")):
            return "title_access_clearance"
        if _contains_any_term(text, ("approval", "permit", "condition", "recordation", "map", "entitlement")):
            return "entitlement_conditions"
        if _contains_any_term(text, ("drainage", "stormwater", "flood", "detention")):
            return "stormwater_drainage"
        if _contains_any_term(text, ("geotech", "grading", "foundation", "soil", "soils")):
            return "geotechnical_scope"
        if _contains_any_term(text, ("fee", "exaction", "impact fee", "capacity fee")):
            return "fee_stack"
        return "schedule_path"
    return "schedule_path"


def _dependency_key_for_contradiction(contradiction: ContradictionFinding) -> str:
    text = " ".join(
        [contradiction.description, contradiction.why_it_matters, " ".join(contradiction.related_categories)]
    ).lower()
    related = set(contradiction.related_categories)
    if "Title / Access Concerns" in related or _contains_any_term(text, ("title", "access", "easement", "site plan")):
        return "title_access_clearance"
    if "Offsite Obligations" in related or _contains_any_term(text, ("frontage", "offsite", "dedication")):
        return "offsite_frontage"
    if {"Geotechnical Risks", "Budget / Cost Reliability"}.issubset(related):
        return "geotech_budget_alignment"
    if "Utilities / Infrastructure Issues" in related or _contains_any_term(text, ("utility", "will serve", "water", "sewer")):
        return "utility_capacity"
    if "Entitlement Status" in related:
        return "entitlement_conditions"
    if "Flood / Drainage Issues" in related:
        return "stormwater_drainage"
    if "Environmental Risks" in related:
        return "environmental_followup"
    if "Fee / Exaction Burden" in related:
        return "fee_stack"
    if "Budget / Cost Reliability" in related:
        return "budget_reliability"
    return "schedule_path"


def _dependency_key_for_omission(omission: OmissionAssessment) -> str:
    text = f"{omission.item} {omission.category}".lower()
    if _contains_any_term(text, ("title", "survey", "alta", "exception")):
        return "title_access_clearance"
    if _contains_any_term(text, ("environment", "phase i", "wetland")):
        return "environmental_followup"
    if _contains_any_term(text, ("geotechnical", "geotech", "soils")):
        return "geotechnical_scope"
    if _contains_any_term(text, ("flood", "stormwater", "drainage")):
        return "stormwater_drainage"
    if _contains_any_term(text, ("utility", "will-serve", "will serve", "water", "sewer")):
        return "utility_capacity"
    if _contains_any_term(text, ("entitlement", "conditions", "approval", "agency correspondence", "expiration", "extension")):
        return "entitlement_conditions"
    if _contains_any_term(text, ("fee", "exaction")):
        return "fee_stack"
    if _contains_any_term(text, ("budget", "bid", "pricing", "cost")):
        return "budget_reliability"
    if _contains_any_term(text, ("offsite", "frontage")):
        return "offsite_frontage"
    return "schedule_path"


def _risk_open_questions(risk: RiskFinding) -> list[str]:
    questions: list[str] = []
    if risk.uncertainty_reason:
        questions.append(risk.uncertainty_reason)
    if risk.category == "Title / Access Concerns":
        questions.append("Which title exceptions still conflict with the active plan set, and how are they being cleared?")
    elif risk.category == "Entitlement Status":
        questions.append("Which approval conditions are still open, and which one controls the next permit milestone?")
    elif risk.category == "Geotechnical Risks":
        questions.append("Which soils recommendations still change grading, retaining, or foundation scope?")
    elif risk.category == "Flood / Drainage Issues":
        questions.append("Which drainage assumptions still require civil redesign or public-works confirmation?")
    elif risk.category == "Fee / Exaction Burden":
        questions.append("Which fees remain estimated rather than city-confirmed?")
    elif risk.category == "Offsite Obligations":
        questions.append("Which frontage or offsite items remain buyer-facing at closing?")
    elif risk.category == "Utilities / Infrastructure Issues":
        questions.append("Which utility commitments still depend on provider confirmation or will-serve support?")
    elif risk.category == "Budget / Cost Reliability":
        questions.append("Which cost assumptions are still budgetary rather than backed by auditable pricing?")
    elif risk.category == "Environmental Risks":
        questions.append("What environmental follow-up remains open, and who carries the cost?")
    elif risk.category == "Schedule Risks":
        questions.append("Which critical-path date still relies on an unconfirmed assumption?")
    return unique_preserve_order(questions)[:3]


def _contradiction_open_questions(contradiction: ContradictionFinding) -> list[str]:
    source_text = _format_citation_text(contradiction.citations[:2]) or ", ".join(contradiction.source_documents[:2])
    return [f"Which source controls: {source_text or 'the conflicting documents'}?"]


def _confidence_from_risk(risk: RiskFinding) -> str:
    if not risk.citations:
        return "low"
    if risk.uncertainty_reason:
        return "medium"
    return "high"


def _likelihood_from_risk(risk: RiskFinding) -> str:
    if risk.severity == "high":
        return "high"
    if risk.priority_tier == "primary":
        return "medium"
    return "low"


def _timing_from_risk(risk: RiskFinding) -> str:
    if "Vertical start" in risk.gating_flags or risk.category in {
        "Entitlement Status",
        "Offsite Obligations",
        "Utilities / Infrastructure Issues",
        "Schedule Risks",
    }:
        return "high"
    if risk.category in {"Flood / Drainage Issues", "Geotechnical Risks"}:
        return "medium"
    return "low"


def _cost_from_risk(risk: RiskFinding) -> str:
    if risk.category in {
        "Budget / Cost Reliability",
        "Geotechnical Risks",
        "Fee / Exaction Burden",
        "Offsite Obligations",
    }:
        return "high"
    if risk.category in {"Environmental Risks", "Flood / Drainage Issues", "Utilities / Infrastructure Issues"}:
        return "medium"
    return "low"


def _timing_from_categories(categories: list[str]) -> str:
    if any(
        category in {"Entitlement Status", "Offsite Obligations", "Utilities / Infrastructure Issues", "Schedule Risks"}
        for category in categories
    ):
        return "high"
    if any(category in {"Flood / Drainage Issues", "Geotechnical Risks"} for category in categories):
        return "medium"
    return "low"


def _cost_from_categories(categories: list[str]) -> str:
    if any(
        category in {"Budget / Cost Reliability", "Geotechnical Risks", "Fee / Exaction Burden", "Offsite Obligations"}
        for category in categories
    ):
        return "high"
    if any(category in {"Environmental Risks", "Flood / Drainage Issues", "Utilities / Infrastructure Issues"} for category in categories):
        return "medium"
    return "low"


def _gating_from_categories(categories: list[str]) -> list[str]:
    gating: list[str] = []
    for category in categories:
        if category == "Title / Access Concerns":
            gating.extend(["Closing", "Underwriting confidence"])
        elif category in {
            "Entitlement Status",
            "Environmental Risks",
            "Flood / Drainage Issues",
            "Geotechnical Risks",
            "Offsite Obligations",
            "Utilities / Infrastructure Issues",
        }:
            gating.extend(["Underwriting confidence", "Vertical start"])
        elif category in {"Fee / Exaction Burden", "Budget / Cost Reliability", "Schedule Risks"}:
            gating.append("Underwriting confidence")
    return unique_preserve_order(gating)


def _likely_implication_from_contradiction(contradiction: ContradictionFinding) -> str:
    if contradiction.why_it_matters:
        return contradiction.why_it_matters
    related = set(contradiction.related_categories)
    if "Title / Access Concerns" in related:
        return "Closing and buildability remain exposed until the title assumption and plan assumption are reconciled."
    if "Offsite Obligations" in related:
        return "Buyer-facing scope and basis remain exposed until the offsite obligation is reconciled."
    if {"Geotechnical Risks", "Budget / Cost Reliability"}.issubset(related):
        return "Current basis is not reliable if soils-driven scope is not fully priced."
    return "The conflicting assumptions keep underwriting and execution confidence open."


def _why_omission_matters(omission: OmissionAssessment) -> str:
    return f"Without {omission.item.lower()}, the deal still relies on assumption instead of directly auditable support."


def _implication_from_omission(omission: OmissionAssessment) -> str:
    if omission.category == "Title / Access Concerns":
        return "Closing and lender comfort remain exposed until land-control support is complete."
    if omission.category == "Entitlement Status":
        return "Permit and schedule assumptions remain open until approval status is documented cleanly."
    if omission.category == "Budget / Cost Reliability":
        return "Basis remains provisional because the cost stack is not fully auditable."
    if omission.category == "Utilities / Infrastructure Issues":
        return "Execution timing remains exposed until provider commitments are documented."
    return f"{omission.category} remains less reliable than it should be for a recommendation-grade package."


def _resolve_line_for_omission(omission: OmissionAssessment, fallback: str) -> str:
    return f"Provide {omission.item.lower()} in a current, readable form." if omission.item else fallback


def _action_for_omission(omission: OmissionAssessment, fallback: str) -> str:
    if omission.status == "not found":
        if omission.category in {"Title / Access Concerns", "Entitlement Status", "Utilities / Infrastructure Issues"}:
            return "condition closing"
        if omission.category in {"Budget / Cost Reliability", "Fee / Exaction Burden"}:
            return "reprice"
    return fallback


def _fallback_fragments_from_documents(document_analyses: list[DocumentAnalysis]) -> list[IssueFragment]:
    fragments: list[IssueFragment] = []
    for index, analysis in enumerate(document_analyses[:3], start=1):
        category = analysis.focus_areas[0] if analysis.focus_areas else "Schedule Risks"
        dependency_key = _dependency_key_for_omission(
            OmissionAssessment(
                item=analysis.document.title,
                category=category,
                status="unclear whether present",
                rationale="The document exists but did not produce a concentrated issue signal.",
            )
        )
        template = _template_for_key(dependency_key, category)
        fragments.append(
            IssueFragment(
                fragment_id=f"fallback-{index:02d}",
                source_type="document",
                title=template["title"],
                category=template["category"],
                dependency_key=dependency_key,
                status="unclear whether present",
                core_facts=[clip_text(analysis.summary, 220)],
                best_evidence=[clip_text(analysis.summary, 220)],
                why_it_matters=f"{category} still requires manual confirmation because the file did not isolate a concentrated issue signal.",
                likely_implication=f"The package remains incomplete on {category.lower()} until this support is reviewed directly.",
                what_would_resolve_it=template["resolve"],
                confidence=analysis.confidence,
                citations=_document_chunk_citations(analysis.document)[:2],
                source_documents=[analysis.document.title],
                gating_flags=_gating_from_categories([category]),
            )
        )
    return fragments


def _merge_status(fragments: list[IssueFragment]) -> str:
    ranked = sorted(fragments, key=lambda fragment: (-_STATUS_PRIORITY.get(fragment.status, 0), fragment.status))
    return ranked[0].status if ranked else "open"


def _merge_confidence(fragments: list[IssueFragment], citations: list[Citation]) -> str:
    if not citations:
        return "low"
    confidences = Counter(fragment.confidence for fragment in fragments)
    if confidences["high"] and not confidences["low"]:
        return "high"
    if confidences["low"] >= max(confidences["high"], 1):
        return "medium"
    return "medium"


def _merge_level(fragments: list[IssueFragment], field_name: str) -> str:
    levels = [getattr(fragment, field_name) for fragment in fragments]
    return max(levels, key=lambda value: _LEVEL_SCORE.get(value, 0))


def _select_fixability(fragments: list[IssueFragment], fallback: str) -> str:
    values = [fragment.fixability for fragment in fragments if fragment.fixability]
    if not values:
        return fallback
    return min(values, key=lambda value: _FIXABILITY_SCORE.get(value, 0))


def _select_decision_action(fragments: list[IssueFragment], fallback: str) -> str:
    action_priority = {
        "treat as fatal": 7,
        "condition closing": 6,
        "restructure": 5,
        "reprice": 4,
        "assign to seller": 3,
        "verify": 2,
        "monitor": 1,
        "accept": 0,
    }
    values = [fragment.decision_action for fragment in fragments if fragment.decision_action]
    if not values:
        return fallback
    return max(values, key=lambda value: action_priority.get(value, -1))


def _select_concise_line(candidates: list[str], *, fallback: str) -> str:
    cleaned = [normalize_line(candidate) for candidate in candidates if candidate and normalize_line(candidate)]
    if not cleaned:
        return normalize_line(fallback)
    return max(cleaned, key=lambda item: (len(item.split()), item))


def _select_fragment_line(
    fragments: list[IssueFragment],
    attribute: str,
    *,
    fallback: str,
) -> str:
    source_priority = {"risk": 0, "contradiction": 1, "omission": 2, "document": 3}
    prioritized = sorted(
        fragments,
        key=lambda fragment: (
            source_priority.get(fragment.source_type, 9),
            -_CONFIDENCE_SCORE.get(fragment.confidence, 0),
            -_LEVEL_SCORE.get(fragment.severity, 0),
        ),
    )
    for fragment in prioritized:
        value = normalize_line(getattr(fragment, attribute, ""))
        if value:
            return value
    return normalize_line(fallback)


def _merge_rationale(dependency_key: str, fragments: list[IssueFragment]) -> str:
    source_types = Counter(fragment.source_type for fragment in fragments)
    categories = unique_preserve_order(fragment.category for fragment in fragments)
    return (
        f"Merged {len(fragments)} fragment(s) into '{dependency_key}' because they point to the same underlying dependency "
        f"across {', '.join(categories[:3])}. Source mix: "
        f"{', '.join(f'{source_type}={count}' for source_type, count in sorted(source_types.items()))}."
    )


def _seller_shiftability(issue: CanonicalIssue) -> int:
    if issue.decision_action == "assign to seller":
        return 1
    if issue.decision_action in {"restructure", "reprice"}:
        return 4
    if issue.decision_action == "condition closing":
        return 5
    if issue.decision_action == "verify":
        return 3
    if issue.decision_action == "monitor":
        return 2
    return 3


def _issue_reason_line(issue: CanonicalIssue) -> str:
    return f"{issue.title}: {issue.why_it_matters}"


def _issue_condition_line(issue: CanonicalIssue) -> str:
    return issue.what_would_resolve_it or f"Resolve {issue.title.lower()} before relying on the current underwriting."


def _selection_records(
    *,
    executive_ids: list[str],
    key_risk_ids: list[str],
    ic_ids: list[str],
    seller_ids: list[str],
    appendix_ids: list[str],
) -> list[OutputIssueSelection]:
    selections: list[OutputIssueSelection] = []
    for index, issue_id in enumerate(executive_ids, start=1):
        selections.append(OutputIssueSelection("01_executive_summary.md", issue_id, index, "Highest weighted decision priority"))
    for index, issue_id in enumerate(key_risk_ids, start=1):
        selections.append(OutputIssueSelection("02_key_risks.md", issue_id, index, "Top ranked issue"))
    for index, issue_id in enumerate(seller_ids, start=1):
        selections.append(OutputIssueSelection("04_seller_questions.md", issue_id, index, "Needs direct resolution or confirmation"))
    for index, issue_id in enumerate(ic_ids, start=1):
        selections.append(OutputIssueSelection("09_investment_committee_brief.md", issue_id, index, "Board-level decision driver"))
    for index, issue_id in enumerate(appendix_ids, start=1):
        selections.append(OutputIssueSelection("10_issue_analysis.md", issue_id, index, "Appendix coverage"))
    return selections


def _to_priority_callout(issue: CanonicalIssue | None) -> PriorityCallout | None:
    if issue is None:
        return None
    return PriorityCallout(
        label=issue.title,
        statement=f"{issue.title}. {issue.likely_implication}".strip(),
        why_it_matters=issue.why_it_matters,
        citations=issue.citations[:2],
        category=issue.category,
    )


def _max_issue(issues: list[CanonicalIssue], scorer) -> CanonicalIssue | None:
    if not issues:
        return None
    return max(issues, key=scorer)


def _source_hint(citations: list[Citation], source_documents: list[str]) -> str:
    citation_text = _format_citation_text(citations)
    if citation_text:
        return f" (Source: {citation_text})"
    if source_documents:
        return f" (Source: {', '.join(source_documents[:2])})"
    return ""


def _document_chunk_citations(document) -> list[Citation]:
    citations: list[Citation] = []
    for chunk in document.chunks[:3]:
        citations.append(
            Citation(
                document_name=document.title,
                chunk_id=chunk.chunk_id,
                page_number=chunk.page_number,
            )
        )
    return citations


def _unique_citations(citations: list[Citation]) -> list[Citation]:
    seen: set[tuple[str, str, int | None]] = set()
    ordered: list[Citation] = []
    for citation in citations:
        key = (citation.document_name, citation.chunk_id, citation.page_number)
        if key in seen:
            continue
        seen.add(key)
        ordered.append(citation)
    return ordered


def _format_citation_text(citations: list[Citation]) -> str:
    parts: list[str] = []
    for citation in citations[:3]:
        if citation.page_number is not None:
            parts.append(f"{citation.document_name} p. {citation.page_number}")
        else:
            parts.append(citation.document_name)
    return "; ".join(parts)


def normalize_line(text: str) -> str:
    return " ".join(text.split()).strip()
