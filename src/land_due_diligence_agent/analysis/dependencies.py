"""Deterministic dependency, consequence, and critical-path reasoning for canonical issues."""

from __future__ import annotations

from collections import defaultdict

from land_due_diligence_agent.models import (
    CanonicalIssue,
    CanonicalIssueRegistry,
    IssueCluster,
    IssueDependencyLink,
)
from land_due_diligence_agent.utils.files import slugify
from land_due_diligence_agent.utils.text import normalize_text, unique_preserve_order

_NON_BLOCKING = "non-blocking"
_CONSEQUENCE_FIELDS = (
    "likely_cost_effect",
    "likely_schedule_effect",
    "likely_yield_or_product_effect",
    "likely_closing_effect",
    "likely_structure_effect",
    "likely_underwriting_effect",
)

_DEPENDENCY_TYPE_BY_ISSUE_ID = {
    "title-access-clearance": "title",
    "entitlement-conditions": "approval",
    "geotechnical-scope": "design",
    "geotech-budget-alignment": "cost",
    "stormwater-drainage": "design",
    "fee-stack": "cost",
    "offsite-frontage": "design",
    "utility-capacity": "utility",
    "environmental-followup": "legal",
    "budget-reliability": "cost",
    "schedule-path": "schedule",
}

_CONSEQUENCE_MAP = {
    "title-access-clearance": {
        "likely_cost_effect": "Access or easement conflicts can force curative title work, redesign, or seller cure costs not carried in basis.",
        "likely_schedule_effect": "Closing and downstream design release can slip until the exception is cured, endorsed, or designed around.",
        "likely_yield_or_product_effect": "Access or easement constraints can force entry realignment, lost lots, or product layout changes.",
        "likely_closing_effect": "Closing and lenderability stay impaired until insurable access and site control are confirmed.",
        "likely_structure_effect": "May require seller cure covenants, escrow holdbacks, or a redesign-based PSA restructure.",
        "likely_underwriting_effect": "Land-control assumptions remain non-auditable, so basis and execution timing cannot be treated as firm.",
    },
    "entitlement-conditions": {
        "likely_cost_effect": "Open conditions can pull forward offsite, utility, or agency scope that is not fully priced.",
        "likely_schedule_effect": "Third-party condition sign-off can hold improvement plan approval, final map timing, or permit release.",
        "likely_yield_or_product_effect": "Late condition responses can change approved scope or product assumptions.",
        "likely_closing_effect": "If approval status is being overstated, closing structure may need to stay conditional.",
        "likely_structure_effect": "May require condition-closeout covenants, extension rights, or staged hard-money release.",
        "likely_underwriting_effect": "Permit-path assumptions remain provisional until the remaining conditions and owners are explicit.",
    },
    "geotechnical-scope": {
        "likely_cost_effect": "Updated grading, retaining, or foundation recommendations can expand land development cost beyond current basis.",
        "likely_schedule_effect": "Design rework and quantity reconciliation can delay bid locking and civil release.",
        "likely_yield_or_product_effect": "Overexcavation, retaining, or foundation changes can alter pad layout, yield, or product fit.",
        "likely_closing_effect": "Usually not a direct closing blocker, but it can change the economics required to close.",
        "likely_structure_effect": "May require seller cost sharing, contingency resets, or basis adjustment.",
        "likely_underwriting_effect": "Underwriting remains weak until soils recommendations are fully carried into design and quantities.",
    },
    "geotech-budget-alignment": {
        "likely_cost_effect": "Unreconciled soils scope can understate grading, retaining, or foundation cost.",
        "likely_schedule_effect": "Budget revisions and redesign can delay underwriting approval and internal sign-off.",
        "likely_yield_or_product_effect": "If grading or foundation assumptions move materially, the current product plan may need to be re-cut.",
        "likely_closing_effect": "Closing can remain conditional if the economics change after soils reconciliation.",
        "likely_structure_effect": "May require repricing, contingency resizing, or seller participation.",
        "likely_underwriting_effect": "Current basis cannot be treated as decision-grade until soils scope is priced with backup.",
    },
    "stormwater-drainage": {
        "likely_cost_effect": "Drainage redesign, detention, or agency-required improvements can add civil and offsite cost.",
        "likely_schedule_effect": "Drainage closure can sit on the path to improvement plans, map release, or permit timing.",
        "likely_yield_or_product_effect": "Detention or drainage geometry changes can affect net yield or pad configuration.",
        "likely_closing_effect": "Usually indirect, but unresolved drainage can keep the project from a clean pre-close path.",
        "likely_structure_effect": "May require scope carve-outs or timing conditions tied to civil approval.",
        "likely_underwriting_effect": "Siteability and schedule assumptions remain provisional until drainage scope is closed.",
    },
    "fee-stack": {
        "likely_cost_effect": "City-confirmed fees can reset land basis if current assumptions are stale.",
        "likely_schedule_effect": "Fee uncertainty usually delays underwriting sign-off rather than approvals.",
        "likely_yield_or_product_effect": "Higher fee burden can compress margins and push product re-underwriting.",
        "likely_closing_effect": "Can force retrade or repricing before closing if basis no longer holds.",
        "likely_structure_effect": "May require purchase price reset or fee true-up mechanics.",
        "likely_underwriting_effect": "Underwriting remains provisional while fee assumptions are estimated.",
    },
    "offsite-frontage": {
        "likely_cost_effect": "Buyer-facing frontage, dedications, or offsite improvements can move both hard cost and contingency.",
        "likely_schedule_effect": "Offsite scope often controls improvement plan timing, bond release sequencing, and map readiness.",
        "likely_yield_or_product_effect": "Roadway or frontage revisions can change lot count, building envelope, or product placement.",
        "likely_closing_effect": "If scope owner and trigger are unclear, closing structure stays exposed.",
        "likely_structure_effect": "May require seller delivery obligations, escrows, or phased closing mechanics.",
        "likely_underwriting_effect": "Execution risk stays understated until every offsite obligation has an owner, trigger, and cost.",
    },
    "utility-capacity": {
        "likely_cost_effect": "Upsizing, joint trench, or downstream utility work can add offsite and backbone cost.",
        "likely_schedule_effect": "Provider confirmation often sits on the path to improvement plan approval, final map timing, or vertical release.",
        "likely_yield_or_product_effect": "Capacity or alignment constraints can force product mix changes or phased delivery.",
        "likely_closing_effect": "Usually indirect, but lack of committed utility path can force conditional closing structure.",
        "likely_structure_effect": "May require utility milestones, seller delivery covenants, or delayed hard-money release.",
        "likely_underwriting_effect": "The delivery path is not reliable until will-serve scope, timing, and offsite obligations are explicit.",
    },
    "environmental-followup": {
        "likely_cost_effect": "Mitigation, remediation, or agency follow-up can add direct cost and reserve requirements.",
        "likely_schedule_effect": "Sampling, agency review, or mitigation closeout can delay underwriting and sometimes permit timing.",
        "likely_yield_or_product_effect": "Buffers, mitigation areas, or cleanup limits can reduce buildable area or product flexibility.",
        "likely_closing_effect": "Material environmental exposure can push the deal back to a conditional or paused closing posture.",
        "likely_structure_effect": "May require seller indemnity, credit, escrow, or post-close remediation allocation.",
        "likely_underwriting_effect": "Basis and timing remain provisional until residual environmental scope and cost owner are clear.",
    },
    "budget-reliability": {
        "likely_cost_effect": "Current basis may exclude real site scope, contingency, or pricing escalation.",
        "likely_schedule_effect": "Management approval can stall while the team rebuilds an auditable cost stack.",
        "likely_yield_or_product_effect": "If basis shifts materially, the current product or yield plan may no longer clear hurdles.",
        "likely_closing_effect": "Usually not a direct blocker, but it can force a retrade before hard-money release.",
        "likely_structure_effect": "May require price reset, contingency guardrails, or staged economics.",
        "likely_underwriting_effect": "This directly blocks a clean underwriting recommendation because the cost stack is not auditable.",
    },
    "schedule-path": {
        "likely_cost_effect": "Extended duration can pull fee escalation, carry, and offsite cost into basis.",
        "likely_schedule_effect": "The current schedule cannot be treated as reliable because it depends on unresolved approvals, utilities, or scope assumptions.",
        "likely_yield_or_product_effect": "Schedule slip can cascade into product release timing or phasing changes.",
        "likely_closing_effect": "Can force longer diligence, delayed close, or revised milestone structure.",
        "likely_structure_effect": "May require diligence extensions or milestone-based closing structure.",
        "likely_underwriting_effect": "Execution timing is not underwritten cleanly while the critical path rests on unconfirmed assumptions.",
    },
}

_EDGE_RULES = {
    "title-access-clearance": (
        ("offsite-frontage", "title", "Access and easement uncertainty keeps offsite design assumptions unstable.", "Offsite scope and improvement alignment stay provisional."),
        ("budget-reliability", "cost", "Unclear land control keeps downstream cost assumptions provisional.", "Basis remains exposed until the title cure path is explicit."),
        ("schedule-path", "schedule", "Title cure timing can sit ahead of close and downstream execution sequencing.", "The headline schedule remains conditional."),
    ),
    "entitlement-conditions": (
        ("offsite-frontage", "approval", "Open conditions often control frontage, utility, and offsite completion obligations.", "Offsite scope ownership and triggers remain open."),
        ("utility-capacity", "approval", "Remaining conditions can depend on provider sign-off and agency coordination.", "Utility timing and approvals stay linked."),
        ("schedule-path", "schedule", "Condition closeout drives permit and map timing.", "The approval path cannot be treated as firm."),
    ),
    "geotechnical-scope": (
        ("geotech-budget-alignment", "design", "Soils recommendations need to flow into grading and foundation assumptions.", "The cost basis cannot be treated as final."),
        ("budget-reliability", "cost", "Uncarried soils scope understates site-development cost.", "Underwriting basis remains provisional."),
        ("schedule-path", "schedule", "Design rework and quantity reconciliation extend the execution path.", "Critical dates remain assumption-based."),
    ),
    "geotech-budget-alignment": (
        ("budget-reliability", "cost", "Unpriced soils scope cascades into the land-development budget.", "Basis remains non-auditable."),
        ("schedule-path", "schedule", "Repricing and redesign can move approval and release timing.", "Execution timing stays unstable."),
    ),
    "stormwater-drainage": (
        ("offsite-frontage", "design", "Drainage closure often changes civil frontage and offsite improvement scope.", "Offsite design and scope ownership can move late."),
        ("schedule-path", "schedule", "Drainage sign-off can control civil approval and permit release.", "Final map or permit timing stays exposed."),
    ),
    "fee-stack": (
        ("budget-reliability", "cost", "Estimated fees flow directly into the land basis.", "Underwriting economics remain provisional."),
    ),
    "offsite-frontage": (
        ("budget-reliability", "cost", "Buyer-facing offsite scope needs to be priced into the basis.", "Hard-cost and contingency assumptions stay exposed."),
        ("schedule-path", "schedule", "Frontage and offsite completion often sit on the release path for maps and permits.", "The execution path stays conditional."),
    ),
    "utility-capacity": (
        ("offsite-frontage", "utility", "Provider requirements often change offsite trench, frontage, and improvement scope.", "Offsite readiness and cost can move."),
        ("schedule-path", "schedule", "Utility confirmation can sit ahead of improvement plan approval and vertical readiness.", "The real critical path stays unresolved."),
    ),
    "environmental-followup": (
        ("budget-reliability", "cost", "Residual mitigation or remediation scope belongs in the basis.", "Underwriting remains exposed until cost ownership is explicit."),
        ("schedule-path", "schedule", "Testing, mitigation, or agency follow-up can move permit or close timing.", "Execution timing stays conditional."),
    ),
    "budget-reliability": (
        ("schedule-path", "schedule", "An unauditable cost stack delays underwriting sign-off and execution confidence.", "The team cannot rely on the current timeline."),
    ),
}

_CLUSTER_LABELS = {
    "utility-capacity": "utility/offsite readiness",
    "offsite-frontage": "utility/offsite readiness",
    "title-access-clearance": "title/easement cleanup",
    "geotechnical-scope": "geotech integration into grading/foundation assumptions",
    "geotech-budget-alignment": "geotech integration into grading/foundation assumptions",
    "entitlement-conditions": "entitlement/third-party approval sequencing",
    "stormwater-drainage": "drainage/civil readiness",
    "environmental-followup": "environmental closure path",
    "budget-reliability": "basis reliability",
    "fee-stack": "basis reliability",
    "schedule-path": "execution sequencing",
}


def apply_dependency_reasoning(registry: CanonicalIssueRegistry) -> None:
    """Populate dependency graph fields, blocker classifications, and causal clusters."""

    if not registry.issues:
        return

    issue_by_id = {issue.issue_id: issue for issue in registry.issues}
    for issue in registry.issues:
        issue.dependency_type = _dependency_type(issue)
        issue.upstream_dependencies = []
        issue.downstream_dependencies = []
        _apply_consequence_map(issue)

    for source_issue_id, target_issue_id, dependency_type, mechanism, effect in _dependency_edges(issue_by_id):
        source_issue = issue_by_id[source_issue_id]
        target_issue = issue_by_id[target_issue_id]
        source_issue.downstream_dependencies.append(
            IssueDependencyLink(
                issue_id=target_issue_id,
                title=target_issue.title,
                dependency_type=dependency_type,
                mechanism=mechanism,
                effect=effect,
            )
        )
        target_issue.upstream_dependencies.append(
            IssueDependencyLink(
                issue_id=source_issue_id,
                title=source_issue.title,
                dependency_type=dependency_type,
                mechanism=mechanism,
                effect=effect,
            )
        )

    for issue in registry.issues:
        issue.schedule_impact_classification = _schedule_impact_classification(issue)
        issue.blocking_flag = _blocking_flag(issue)

    for issue in registry.issues:
        issue.critical_path_flag = _critical_path_flag(issue, issue_by_id)
        issue.blocker_classification = _blocker_classification(issue)
        issue.blocking_reason = _blocking_reason(issue, issue_by_id)
        issue.critical_path_reason = _critical_path_reason(issue, issue_by_id)
        if issue.blocking_flag:
            issue.top_line_filter_reasons = [
                reason
                for reason in issue.top_line_filter_reasons
                if reason not in {
                    "weak issue strength",
                    "high false-positive risk",
                    "normal process friction",
                    "omission-only without high criticality",
                    "not decision relevant",
                    "evaluator-pruned weak or routine issue",
                    "evaluator-flagged redundancy",
                }
            ]
            issue.top_line_eligible = True
        elif issue.critical_path_flag and issue.false_positive_risk != "high":
            issue.top_line_filter_reasons = [
                reason
                for reason in issue.top_line_filter_reasons
                if reason not in {
                    "normal process friction",
                    "not decision relevant",
                    "evaluator-pruned weak or routine issue",
                }
            ]
            issue.top_line_eligible = not issue.top_line_filter_reasons

    registry.blocker_issue_ids = [issue.issue_id for issue in registry.issues if issue.blocker_classification == "blocking issue"]
    registry.sequencing_issue_ids = [issue.issue_id for issue in registry.issues if issue.blocker_classification == "sequencing issue"]
    registry.confirmatory_issue_ids = [issue.issue_id for issue in registry.issues if issue.blocker_classification == "confirmatory issue"]
    registry.monitoring_issue_ids = [issue.issue_id for issue in registry.issues if issue.blocker_classification == "monitoring issue"]
    registry.critical_path_issue_ids = [issue.issue_id for issue in registry.issues if issue.critical_path_flag]
    registry.issue_clusters = _issue_clusters(registry.issues, issue_by_id)
    registry.central_risk_pattern = _central_risk_pattern(registry, issue_by_id)
    registry.cluster_pattern = _cluster_pattern(registry)
    registry.fragility_classification = _fragility_classification(registry)
    registry.critical_path_summary = _critical_path_summary(registry, issue_by_id)
    registry.confidence_unlocks = _confidence_unlocks(registry)


def _dependency_type(issue: CanonicalIssue) -> str:
    return _DEPENDENCY_TYPE_BY_ISSUE_ID.get(issue.issue_id, "schedule")


def _apply_consequence_map(issue: CanonicalIssue) -> None:
    consequence_map = _CONSEQUENCE_MAP.get(issue.issue_id, {})
    for field_name in _CONSEQUENCE_FIELDS:
        setattr(issue, field_name, normalize_text(consequence_map.get(field_name, "")))


def _dependency_edges(issue_by_id: dict[str, CanonicalIssue]) -> list[tuple[str, str, str, str, str]]:
    edges: list[tuple[str, str, str, str, str]] = []
    for source_issue_id, targets in _EDGE_RULES.items():
        if source_issue_id not in issue_by_id:
            continue
        for target_issue_id, dependency_type, mechanism, effect in targets:
            if target_issue_id not in issue_by_id:
                continue
            edges.append((source_issue_id, target_issue_id, dependency_type, mechanism, effect))
    return edges


def _schedule_impact_classification(issue: CanonicalIssue) -> str:
    if issue.decision_action == "treat as fatal" or (
        issue.issue_id == "title-access-clearance"
        and issue.status == "conflicted"
        and "Closing" in issue.gating_flags
    ):
        return "immediate blocker"
    if "Closing" in issue.gating_flags or issue.issue_id == "title-access-clearance":
        return "pre-close blocker"
    if issue.issue_id in {"entitlement-conditions", "utility-capacity", "offsite-frontage", "stormwater-drainage"}:
        return "pre-final-map blocker"
    if (
        "Underwriting confidence" in issue.gating_flags
        and issue.issue_id in {"budget-reliability", "geotechnical-scope", "geotech-budget-alignment", "fee-stack", "environmental-followup"}
    ):
        return "pre-underwriting blocker"
    if "Vertical start" in issue.gating_flags or issue.issue_id == "schedule-path":
        return "pre-vertical-start blocker"
    return _NON_BLOCKING


def _blocking_flag(issue: CanonicalIssue) -> bool:
    if issue.schedule_impact_classification == _NON_BLOCKING:
        return False
    if issue.normal_friction_flag and issue.issue_strength == "weak":
        return False
    if issue.false_positive_risk == "high" and issue.evidence_basis in {"routine_missing_support", "weak_inference"}:
        return False
    if issue.schedule_impact_classification in {"immediate blocker", "pre-close blocker"}:
        return True
    if issue.decision_action in {"condition closing", "restructure", "reprice", "treat as fatal"} and issue.decision_relevant:
        return True
    return issue.materiality == "high" and issue.decision_relevant and issue.false_positive_risk != "high"


def _critical_path_flag(issue: CanonicalIssue, issue_by_id: dict[str, CanonicalIssue]) -> bool:
    if issue.blocking_flag:
        return True
    if issue.normal_friction_flag or not issue.decision_relevant:
        return False
    if issue.schedule_impact_classification == _NON_BLOCKING:
        return False
    if any(issue_by_id[link.issue_id].blocking_flag for link in issue.upstream_dependencies if link.issue_id in issue_by_id):
        return True
    return bool(issue.downstream_dependencies)


def _blocker_classification(issue: CanonicalIssue) -> str:
    if issue.blocking_flag:
        return "blocking issue"
    if issue.critical_path_flag:
        return "sequencing issue"
    if issue.decision_relevant and not issue.normal_friction_flag:
        return "confirmatory issue"
    return "monitoring issue"


def _blocking_reason(issue: CanonicalIssue, issue_by_id: dict[str, CanonicalIssue]) -> str:
    if issue.blocking_flag:
        blocked = _blocked_outcomes(issue, issue_by_id)
        return normalize_text(
            f"Labeled blocking because it is a {issue.schedule_impact_classification} and currently blocks {', '.join(blocked[:3]) or 'the next decision gate'}."
        )
    if issue.critical_path_flag:
        return "Not a standalone blocker, but it sits on the same sequencing path as higher-priority gating issues."
    if issue.blocker_classification == "confirmatory issue":
        return "Material enough to confirm before relying on the package, but it does not currently set the next gate."
    return "Routine, weakly evidenced, or otherwise outside the real critical path."


def _critical_path_reason(issue: CanonicalIssue, issue_by_id: dict[str, CanonicalIssue]) -> str:
    if not issue.critical_path_flag:
        return "Not on the current critical path."
    blocked = _blocked_outcomes(issue, issue_by_id)
    if issue.blocking_flag:
        return normalize_text(
            f"On the critical path because it directly controls {', '.join(blocked[:2]) or 'the next material milestone'}."
        )
    upstream = [issue_by_id[link.issue_id].title for link in issue.upstream_dependencies if link.issue_id in issue_by_id]
    return normalize_text(
        f"On the critical path because it sequences downstream consequences after {', '.join(title.lower() for title in upstream[:2]) or 'the lead blocker'}."
    )


def _blocked_outcomes(issue: CanonicalIssue, issue_by_id: dict[str, CanonicalIssue]) -> list[str]:
    downstream_titles = [
        issue_by_id[link.issue_id].title.lower()
        for link in issue.downstream_dependencies
        if link.issue_id in issue_by_id
    ]
    milestones: list[str] = []
    if issue.schedule_impact_classification == "immediate blocker":
        milestones.append("the current decision posture")
    if issue.schedule_impact_classification == "pre-close blocker":
        milestones.append("closing")
    if issue.schedule_impact_classification == "pre-underwriting blocker":
        milestones.append("underwriting confidence")
    if issue.schedule_impact_classification == "pre-final-map blocker":
        milestones.append("final map and improvement-plan timing")
    if issue.schedule_impact_classification == "pre-vertical-start blocker":
        milestones.append("vertical-start readiness")
    if issue.likely_underwriting_effect:
        milestones.append("the underwriting basis")
    return unique_preserve_order(milestones + downstream_titles)


def _issue_clusters(
    issues: list[CanonicalIssue],
    issue_by_id: dict[str, CanonicalIssue],
) -> list[IssueCluster]:
    adjacency: dict[str, set[str]] = defaultdict(set)
    for issue in issues:
        for link in issue.downstream_dependencies:
            adjacency[issue.issue_id].add(link.issue_id)
            adjacency[link.issue_id].add(issue.issue_id)
        for link in issue.upstream_dependencies:
            adjacency[issue.issue_id].add(link.issue_id)
            adjacency[link.issue_id].add(issue.issue_id)

    visited: set[str] = set()
    components: list[list[str]] = []
    for issue in issues:
        if issue.issue_id in visited:
            continue
        stack = [issue.issue_id]
        component: list[str] = []
        while stack:
            current = stack.pop()
            if current in visited:
                continue
            visited.add(current)
            component.append(current)
            stack.extend(sorted(adjacency.get(current, set()) - visited))
        components.append(component)

    ranked_components = sorted(
        components,
        key=lambda component: (
            -sum(issue_by_id[issue_id].priority_score.total for issue_id in component),
            -len(component),
            component[0],
        ),
    )

    clusters: list[IssueCluster] = []
    tier_labels = ["Primary", "Secondary", "Tertiary"]
    for index, component in enumerate(ranked_components, start=1):
        cluster_issues = sorted(
            (issue_by_id[issue_id] for issue_id in component),
            key=lambda issue: (-issue.priority_score.total, issue.title),
        )
        root_issue = _root_issue(cluster_issues, component)
        label = _CLUSTER_LABELS.get(root_issue.issue_id, root_issue.title.lower())
        downstream_effects = unique_preserve_order(
            effect
            for issue in cluster_issues
            for effect in (
                issue.likely_schedule_effect,
                issue.likely_cost_effect,
                issue.likely_underwriting_effect,
            )
            if effect
        )[:3]
        confirmations = unique_preserve_order(
            item
            for issue in cluster_issues
            for item in ([issue.what_would_resolve_it] + issue.open_questions[:1])
            if item
        )[:3]
        decision_implication = normalize_text(
            root_issue.likely_underwriting_effect
            or root_issue.likely_closing_effect
            or root_issue.likely_schedule_effect
        )
        clusters.append(
            IssueCluster(
                cluster_id=f"cluster-{index:02d}-{slugify(label)}",
                label=label,
                tier=tier_labels[index - 1] if index <= len(tier_labels) else f"Additional {index}",
                root_issue_id=root_issue.issue_id,
                issue_ids=[issue.issue_id for issue in cluster_issues],
                downstream_effects=downstream_effects,
                key_unresolved_confirmations=confirmations,
                decision_implication=decision_implication,
                critical_path_issue_ids=[issue.issue_id for issue in cluster_issues if issue.critical_path_flag],
            )
        )

    return clusters


def _root_issue(cluster_issues: list[CanonicalIssue], component: list[str]) -> CanonicalIssue:
    component_set = set(component)
    return sorted(
        cluster_issues,
        key=lambda issue: (
            sum(1 for link in issue.upstream_dependencies if link.issue_id in component_set),
            -sum(1 for link in issue.downstream_dependencies if link.issue_id in component_set),
            -int(issue.blocking_flag),
            -issue.priority_score.total,
            issue.title,
        ),
    )[0]


def _central_risk_pattern(registry: CanonicalIssueRegistry, issue_by_id: dict[str, CanonicalIssue]) -> str:
    if not registry.issue_clusters:
        return "The current issue set does not show a concentrated causal pattern."
    lead_cluster = registry.issue_clusters[0]
    root_issue = issue_by_id.get(lead_cluster.root_issue_id)
    if root_issue is None:
        return "The current issue set does not show a concentrated causal pattern."
    if len(lead_cluster.issue_ids) > 1:
        return normalize_text(
            f"Risk is concentrated around {lead_cluster.label}, with {root_issue.title.lower()} acting as the root issue that drives downstream underwriting and schedule exposure."
        )
    return normalize_text(
        f"Risk is less clustered and is currently led by {root_issue.title.lower()} rather than one broad causal chain."
    )


def _cluster_pattern(registry: CanonicalIssueRegistry) -> str:
    if not registry.issue_clusters:
        return "Risks are not clustered tightly enough yet to show a root-cause pattern."
    multi_issue_clusters = [cluster for cluster in registry.issue_clusters if len(cluster.issue_ids) > 1]
    if multi_issue_clusters and len(registry.issue_clusters) <= 2:
        return "Most of the important issues cluster around one or two root causes rather than behaving independently."
    if any(len(cluster.issue_ids) > 1 for cluster in registry.issue_clusters[:2]):
        return "The issue set is partially clustered, with one main causal lane and a few independent confirmation items."
    return "The current issues are more independent than clustered."


def _fragility_classification(registry: CanonicalIssueRegistry) -> str:
    if len(registry.blocker_issue_ids) >= 2 or any(len(cluster.critical_path_issue_ids) >= 2 for cluster in registry.issue_clusters):
        return "fragile sequencing"
    if not registry.blocker_issue_ids and all(
        issue.blocker_classification in {"confirmatory issue", "monitoring issue"}
        for issue in registry.issues[:3]
    ):
        return "normal friction"
    return "mixed but closer to fragile sequencing"


def _critical_path_summary(registry: CanonicalIssueRegistry, issue_by_id: dict[str, CanonicalIssue]) -> str:
    path = _best_critical_path(registry, issue_by_id)
    if not path:
        return "No multi-step critical path was isolated beyond the current blocker list."
    titles = " -> ".join(issue_by_id[issue_id].title.lower() for issue_id in path if issue_id in issue_by_id)
    return normalize_text(f"The real critical path runs through {titles}.")


def _best_critical_path(registry: CanonicalIssueRegistry, issue_by_id: dict[str, CanonicalIssue]) -> list[str]:
    downstream_map = {
        issue.issue_id: [link.issue_id for link in issue.downstream_dependencies if link.issue_id in issue_by_id]
        for issue in registry.issues
    }
    downstream_targets = {
        link.issue_id
        for issue in registry.issues
        for link in issue.downstream_dependencies
        if link.issue_id in issue_by_id
    }
    candidate_roots = [
        issue.issue_id
        for issue in registry.issues
        if issue.critical_path_flag and issue.issue_id not in downstream_targets
    ]
    if not candidate_roots:
        candidate_roots = [issue.issue_id for issue in registry.issues if issue.blocking_flag]

    def _path_score(path: list[str]) -> tuple[int, int]:
        return (
            sum(issue_by_id[issue_id].priority_score.total for issue_id in path),
            len(path),
        )

    best_path: list[str] = []

    def _visit(current_issue_id: str, path: list[str]) -> None:
        nonlocal best_path
        next_nodes = [
            node
            for node in downstream_map.get(current_issue_id, [])
            if node not in path and issue_by_id[node].critical_path_flag
        ]
        if not next_nodes:
            if _path_score(path) > _path_score(best_path):
                best_path = path[:]
            return
        for next_issue_id in next_nodes:
            _visit(next_issue_id, [*path, next_issue_id])

    for root_issue_id in candidate_roots:
        _visit(root_issue_id, [root_issue_id])

    if best_path:
        return best_path
    return registry.blocker_issue_ids[:3]


def _confidence_unlocks(registry: CanonicalIssueRegistry) -> list[str]:
    unlocks = unique_preserve_order(
        issue.what_would_resolve_it or issue.open_questions[0]
        for issue in registry.issues
        if issue.blocking_flag or issue.critical_path_flag
    )
    return unlocks[:4]
