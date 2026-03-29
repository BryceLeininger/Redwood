"""Independent evaluator pass for canonical issue ranking and filtering."""

from __future__ import annotations

import re

from land_due_diligence_agent.models import (
    CanonicalIssue,
    CanonicalIssueRegistry,
    IssueMergeSuggestion,
    IssueRegistryEvaluation,
)

_TOKEN_PATTERN = re.compile(r"[a-z0-9]+")
_LOW_SIGNAL_BASES = {"omission_only", "routine_missing_support", "weak_inference"}
_STRONG_IMPLICATION_TERMS = ("closing", "fatal", "material", "no-go", "should not be treated")


def evaluate_registry(registry: CanonicalIssueRegistry) -> IssueRegistryEvaluation:
    """Critique ranked issues with an independent, deterministic pass."""

    if not registry.issues:
        return IssueRegistryEvaluation()

    suggested_order = sorted(
        registry.issues,
        key=lambda issue: (
            -_evaluator_priority(issue),
            -issue.priority_score.total,
            issue.title,
        ),
    )
    top_issues_should_be = [issue.issue_id for issue in suggested_order[:5]]
    issues_to_remove = _issues_to_remove(registry.issues, top_issues_should_be)
    issues_to_merge = _issues_to_merge(registry.issues)
    redundancy_score = min(100, len(issues_to_merge) * 30 + len(issues_to_remove) * 10)
    false_positive_score = _false_positive_score(registry.issues[:5])
    missed_issue_risk = _missed_issue_risk(registry.issues, top_issues_should_be)
    ranking_quality = _ranking_quality(registry.issues, top_issues_should_be, issues_to_remove, issues_to_merge)
    return IssueRegistryEvaluation(
        redundancy_score=redundancy_score,
        false_positive_score=false_positive_score,
        missed_issue_risk=missed_issue_risk,
        ranking_quality=ranking_quality,
        top_issues_should_be=top_issues_should_be,
        issues_to_remove=issues_to_remove,
        issues_to_merge=issues_to_merge,
    )


def should_revise_registry(evaluation: IssueRegistryEvaluation) -> bool:
    """Decide whether the light revision loop should rerun ranking/filtering."""

    return evaluation.redundancy_score >= 40 or evaluation.ranking_quality < 65


def build_evaluator_adjustments(
    registry: CanonicalIssueRegistry,
    evaluation: IssueRegistryEvaluation,
) -> dict[str, int]:
    """Translate evaluator conclusions into bounded score nudges."""

    current_rank = {issue.issue_id: index for index, issue in enumerate(registry.issues)}
    suggested_rank = {issue_id: index for index, issue_id in enumerate(evaluation.top_issues_should_be)}
    secondary_ids = {suggestion.secondary_issue_id for suggestion in evaluation.issues_to_merge}
    adjustments: dict[str, int] = {}

    for issue in registry.issues:
        adjustment = 0
        rank_gap = current_rank[issue.issue_id] - suggested_rank.get(issue.issue_id, current_rank[issue.issue_id])
        if rank_gap > 0:
            adjustment += min(rank_gap, 3) * 4
        if issue.issue_id in evaluation.issues_to_remove:
            adjustment -= 10
        if issue.issue_id in secondary_ids:
            adjustment -= 6
        adjustments[issue.issue_id] = adjustment

    return adjustments


def _evaluator_priority(issue: CanonicalIssue) -> int:
    score = 0
    score += {
        "contradictory_evidence_present": 40,
        "direct_unresolved_risk": 38,
        "direct_confirmed_risk": 26,
        "omission_only": 6,
        "routine_missing_support": 0,
        "weak_inference": -6,
    }.get(issue.evidence_basis, 0)
    score += {"high": 20, "medium": 8, "low": 0}.get(issue.materiality, 0)
    score += {"strong": 12, "moderate": 4, "weak": -10}.get(issue.issue_strength, 0)
    score += {"low": 0, "medium": -8, "high": -18}.get(issue.false_positive_risk, 0)
    score += 16 if "Closing" in issue.gating_flags else 0
    score += 10 if "Underwriting confidence" in issue.gating_flags else 0
    score += 8 if issue.decision_relevant else -12
    score += issue.precedent_summary.score_adjustment
    score -= 12 if issue.normal_friction_flag else 0
    score -= 10 if _unsupported_implication(issue) else 0
    return score


def _issues_to_remove(issues: list[CanonicalIssue], suggested_top: list[str]) -> list[str]:
    suggested_top_set = set(suggested_top[:3])
    removals: list[str] = []
    for issue in issues[:5]:
        if issue.issue_id in suggested_top_set:
            continue
        if _looks_elevated_too_high(issue):
            removals.append(issue.issue_id)
    return removals


def _issues_to_merge(issues: list[CanonicalIssue]) -> list[IssueMergeSuggestion]:
    suggestions: list[IssueMergeSuggestion] = []
    secondaries: set[str] = set()
    for index, left_issue in enumerate(issues):
        for right_issue in issues[index + 1 :]:
            if right_issue.issue_id in secondaries:
                continue
            if left_issue.category != right_issue.category:
                continue
            similarity = _issue_similarity(left_issue, right_issue)
            if similarity < 0.62:
                continue
            primary_issue, secondary_issue = _primary_secondary(left_issue, right_issue)
            if secondary_issue.issue_id in secondaries:
                continue
            secondaries.add(secondary_issue.issue_id)
            suggestions.append(
                IssueMergeSuggestion(
                    primary_issue_id=primary_issue.issue_id,
                    secondary_issue_id=secondary_issue.issue_id,
                    rationale=f"High semantic overlap inside {left_issue.category.lower()} ({similarity:.2f} similarity).",
                )
            )
    return suggestions


def _false_positive_score(top_issues: list[CanonicalIssue]) -> int:
    if not top_issues:
        return 0
    penalty = 0
    for issue in top_issues:
        penalty += {"low": 0, "medium": 12, "high": 24}.get(issue.false_positive_risk, 0)
        if issue.normal_friction_flag:
            penalty += 12
        if issue.issue_strength == "weak":
            penalty += 10
        if _unsupported_implication(issue):
            penalty += 10
    return min(100, round(penalty / len(top_issues)))


def _missed_issue_risk(issues: list[CanonicalIssue], suggested_top: list[str]) -> int:
    current_top = {issue.issue_id for issue in issues[:3]}
    risk = 0
    for issue in issues:
        if issue.issue_id not in set(suggested_top[:3]) or issue.issue_id in current_top:
            continue
        if issue.materiality == "high":
            risk += 25
        if "Closing" in issue.gating_flags:
            risk += 20
        if issue.evidence_basis in {"direct_unresolved_risk", "contradictory_evidence_present"}:
            risk += 20
    return min(100, risk)


def _ranking_quality(
    issues: list[CanonicalIssue],
    suggested_top: list[str],
    issues_to_remove: list[str],
    issues_to_merge: list[IssueMergeSuggestion],
) -> int:
    current_rank = {issue.issue_id: index for index, issue in enumerate(issues[:5])}
    distance_penalty = 0
    for expected_rank, issue_id in enumerate(suggested_top[:5]):
        if issue_id not in current_rank:
            distance_penalty += 12
            continue
        distance_penalty += abs(current_rank[issue_id] - expected_rank) * 8
    quality = 100 - distance_penalty - len(issues_to_remove) * 10 - len(issues_to_merge) * 8
    return max(0, quality)


def _looks_elevated_too_high(issue: CanonicalIssue) -> bool:
    if issue.normal_friction_flag:
        return True
    if issue.issue_strength == "weak":
        return True
    if issue.evidence_basis in _LOW_SIGNAL_BASES and issue.false_positive_risk != "low":
        return True
    if _unsupported_implication(issue):
        return True
    return False


def _unsupported_implication(issue: CanonicalIssue) -> bool:
    if issue.evidence_basis not in _LOW_SIGNAL_BASES:
        return False
    implication = issue.likely_implication.lower()
    return any(term in implication for term in _STRONG_IMPLICATION_TERMS)


def _issue_similarity(left_issue: CanonicalIssue, right_issue: CanonicalIssue) -> float:
    left_tokens = _issue_tokens(left_issue)
    right_tokens = _issue_tokens(right_issue)
    if not left_tokens or not right_tokens:
        return 0.0
    intersection = len(left_tokens.intersection(right_tokens))
    union = len(left_tokens.union(right_tokens))
    return round(intersection / union, 3) if union else 0.0


def _issue_tokens(issue: CanonicalIssue) -> set[str]:
    text = " ".join(
        [
            issue.title,
            issue.why_it_matters,
            issue.likely_implication,
            issue.what_would_resolve_it,
        ]
    ).lower()
    return {token for token in _TOKEN_PATTERN.findall(text) if len(token) > 2}


def _primary_secondary(left_issue: CanonicalIssue, right_issue: CanonicalIssue) -> tuple[CanonicalIssue, CanonicalIssue]:
    if left_issue.priority_score.total > right_issue.priority_score.total:
        return left_issue, right_issue
    if right_issue.priority_score.total > left_issue.priority_score.total:
        return right_issue, left_issue
    if left_issue.issue_strength == "strong" and right_issue.issue_strength != "strong":
        return left_issue, right_issue
    return (left_issue, right_issue) if left_issue.title <= right_issue.title else (right_issue, left_issue)
