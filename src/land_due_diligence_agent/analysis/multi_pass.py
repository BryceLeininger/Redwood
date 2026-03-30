"""Multi-pass reasoning helpers for deeper deal analysis."""

from __future__ import annotations

from dataclasses import dataclass

from land_due_diligence_agent.analysis.risk_rules import CATEGORY_RULES
from land_due_diligence_agent.models import (
    ChallengeFinding,
    Citation,
    ContradictionFinding,
    DocumentAnalysis,
    IssueAnalysis,
    PriorityAssessment,
    PriorityCallout,
    RiskFinding,
    StructuredFact,
)
from land_due_diligence_agent.utils.text import clip_text, unique_preserve_order

_SEVERITY_RANK = {"low": 1, "medium": 2, "high": 3}
_CONFIDENCE_RANK = {"low": 1, "medium": 2, "high": 3}
_RULE_BY_CATEGORY = {rule.category: rule for rule in CATEGORY_RULES}


@dataclass(frozen=True, slots=True)
class _IssueConfig:
    risk_category: str
    label: str
    missing_terms: tuple[str, ...]
    generic_why: str
    generic_implication: str
    cost_weight: int = 0
    timing_weight: int = 0
    closability_weight: int = 0


_ISSUE_CONFIGS = [
    _IssueConfig(
        risk_category="Title / Access Concerns",
        label="Title / Access",
        missing_terms=("title", "survey", "alta", "access", "easement"),
        generic_why="This issue goes directly to site control, legal access, and whether the approved plan can actually close and be built.",
        generic_implication="Closing and plan reliance stay conditional until title and access assumptions are expressly cleared.",
        closability_weight=6,
    ),
    _IssueConfig(
        risk_category="Environmental Risks",
        label="Environmental",
        missing_terms=("environmental", "phase i", "phase ii", "remediation", "hazard"),
        generic_why="Environmental follow-up changes diligence scope, consultant cost, and possible agency or closing conditions.",
        generic_implication="Mitigation cost, follow-up scope, and execution certainty remain open until environmental closeout is clearer.",
        cost_weight=1,
        timing_weight=1,
    ),
    _IssueConfig(
        risk_category="Geotechnical Risks",
        label="Geotechnical / Grading",
        missing_terms=("geotechnical", "soils", "grading", "foundation", "geotech"),
        generic_why="Soils recommendations flow directly into grading, retaining, foundation design, contingency, and sometimes plan layout.",
        generic_implication="Expect cost and design movement until the active geotechnical recommendations are fully carried into plans and budget.",
        cost_weight=4,
        timing_weight=2,
    ),
    _IssueConfig(
        risk_category="Flood / Drainage Issues",
        label="Stormwater / Drainage",
        missing_terms=("stormwater", "drainage", "hydrology", "detention", "flood"),
        generic_why="Drainage scope affects both engineering cost and the pace of civil and public-works approvals.",
        generic_implication="Civil scope and permit timing remain exposed until drainage assumptions are fully locked.",
        cost_weight=2,
        timing_weight=3,
    ),
    _IssueConfig(
        risk_category="Fee / Exaction Burden",
        label="Fees / Exactions",
        missing_terms=("fee", "exaction", "impact fee", "public works fee", "school fee"),
        generic_why="Fee exposure moves straight into land basis and can materially reset returns if underwriting is stale.",
        generic_implication="Land basis remains exposed until the city-confirmed fee stack is locked and allocated correctly.",
        cost_weight=4,
    ),
    _IssueConfig(
        risk_category="Offsite Obligations",
        label="Offsite / Frontage Obligations",
        missing_terms=("offsite", "frontage", "dedication", "improvement plan", "encroachment permit"),
        generic_why="Frontage and offsite work create real pre-vertical cost and can hold up permit release if they remain buyer-facing.",
        generic_implication="Basis and timing stay exposed until the full offsite obligation list is closed and costed.",
        cost_weight=3,
        timing_weight=3,
    ),
    _IssueConfig(
        risk_category="Entitlement Status",
        label="Entitlement / Permit Status",
        missing_terms=("entitlement", "permit", "approval", "conditions of approval", "resolution"),
        generic_why="Approved land use actions do not de-risk the deal if permit-stage conditions, dedications, or implementation triggers remain open.",
        generic_implication="Permit timing and vertical start should stay conditional until the remaining approval items are closed.",
        timing_weight=4,
        closability_weight=1,
    ),
    _IssueConfig(
        risk_category="Budget / Cost Reliability",
        label="Budget / Scope Alignment",
        missing_terms=("budget", "pricing", "bid", "cost", "allowance", "proposal"),
        generic_why="Underwriting is not reliable when the cost package does not clearly carry the scope shown in the technical and approval files.",
        generic_implication="Land basis and contingency stay provisional until scope and budget align cleanly.",
        cost_weight=4,
    ),
]

_CONFIG_BY_RISK_CATEGORY = {config.risk_category: config for config in _ISSUE_CONFIGS}


def build_structured_facts(document_analyses: list[DocumentAnalysis]) -> list[StructuredFact]:
    """Pass 1: extract document-anchored facts by issue category."""

    facts: list[StructuredFact] = []
    seen: set[tuple[str, str, str]] = set()

    for analysis in document_analyses:
        for risk in analysis.risks:
            if risk.category not in _CONFIG_BY_RISK_CATEGORY:
                continue
            if risk.generic_signal_only:
                continue
            if analysis.focus_areas and risk.category not in analysis.focus_areas:
                continue

            evidence_snippets = risk.evidence[:2] or [risk.summary]
            for index, snippet in enumerate(evidence_snippets):
                statement = f"{analysis.document.title}: {clip_text(snippet.strip(), 240)}"
                citation = (
                    [risk.citations[index]]
                    if index < len(risk.citations)
                    else [
                        Citation(
                            document_name=analysis.document.title,
                            chunk_id=f"fact-{index + 1:04d}",
                            page_number=None,
                        )
                    ]
                )
                key = (risk.category, analysis.document.title, statement)
                if key in seen:
                    continue
                seen.add(key)
                facts.append(
                    StructuredFact(
                        category=risk.category,
                        statement=statement,
                        document_name=analysis.document.title,
                        confidence=analysis.confidence,
                        citations=citation,
                    )
                )

    return facts


def build_issue_analyses(
    *,
    structured_facts: list[StructuredFact],
    document_analyses: list[DocumentAnalysis],
    key_risks: list[RiskFinding],
    missing_items: list[str],
) -> list[IssueAnalysis]:
    """Pass 2: build issue-specific reasoning lanes before contradictions."""

    issue_analyses: list[IssueAnalysis] = []
    analysis_by_title = {analysis.document.title: analysis for analysis in document_analyses}

    for config in _ISSUE_CONFIGS:
        related_facts = [fact for fact in structured_facts if fact.category == config.risk_category]
        related_risk = next((risk for risk in key_risks if risk.category == config.risk_category), None)
        related_missing_items = _related_missing_items(missing_items, config)

        if related_risk is None and not related_missing_items:
            continue

        selected_facts = _select_issue_facts(
            facts=_build_seed_facts(related_risk, config)
            + _filter_facts_for_issue(related_facts, related_risk, config, analysis_by_title),
            config=config,
            related_risk=related_risk,
            analysis_by_title=analysis_by_title,
        )
        unresolved_questions = _build_issue_unresolved_questions(
            related_risk=related_risk,
            related_missing_items=related_missing_items,
            related_documents=_related_low_confidence_documents(document_analyses, config),
        )
        citations = _unique_citations(
            [citation for fact in selected_facts for citation in fact.citations]
            + (related_risk.citations[:2] if related_risk is not None else [])
        )[:4]
        source_documents = unique_preserve_order(
            [fact.document_name for fact in selected_facts]
            + (related_risk.source_documents if related_risk is not None else [])
        )[:4]

        confidence = _issue_confidence(selected_facts, related_missing_items, related_risk)
        priority_score = _issue_priority_score(config, related_risk, selected_facts, related_missing_items)
        decision_summary = _issue_decision_summary(config, related_risk, selected_facts)

        issue_analyses.append(
            IssueAnalysis(
                category=config.risk_category,
                label=config.label,
                core_facts=selected_facts,
                unresolved_questions=unresolved_questions,
                why_it_matters=related_risk.why_it_matters if related_risk is not None else config.generic_why,
                likely_implication=related_risk.likely_implication if related_risk is not None else config.generic_implication,
                confidence=confidence,
                citations=citations,
                source_documents=source_documents,
                priority_score=priority_score,
                decision_summary=decision_summary,
            )
        )

    issue_analyses.sort(key=lambda item: (-item.priority_score, item.label))
    return issue_analyses


def enrich_issue_analyses_with_contradictions(
    issue_analyses: list[IssueAnalysis],
    contradictions: list[ContradictionFinding],
) -> list[IssueAnalysis]:
    """Pass 3 bridge: inject contradiction-driven unresolved questions back into issue analyses."""

    enriched: list[IssueAnalysis] = []
    for issue in issue_analyses:
        related_contradictions = [
            finding
            for finding in contradictions
            if issue.category in finding.related_categories
        ]
        unresolved_questions = issue.unresolved_questions + [
            f"Which source controls this lane: {finding.description}"
            for finding in related_contradictions[:2]
        ]
        citations = _unique_citations(issue.citations + [citation for finding in related_contradictions for citation in finding.citations[:2]])[:4]
        priority_score = issue.priority_score + (len(related_contradictions) * 4)
        enriched.append(
            IssueAnalysis(
                category=issue.category,
                label=issue.label,
                core_facts=issue.core_facts,
                unresolved_questions=unique_preserve_order(unresolved_questions)[:4],
                why_it_matters=issue.why_it_matters,
                likely_implication=issue.likely_implication,
                confidence=issue.confidence,
                citations=citations,
                source_documents=issue.source_documents,
                priority_score=priority_score,
                decision_summary=issue.decision_summary,
            )
        )
    enriched.sort(key=lambda item: (-item.priority_score, item.label))

    existing_categories = {issue.category for issue in enriched}
    for finding in contradictions:
        for category in finding.related_categories:
            if category in existing_categories or category not in _CONFIG_BY_RISK_CATEGORY:
                continue
            config = _CONFIG_BY_RISK_CATEGORY[category]
            enriched.append(
                IssueAnalysis(
                    category=category,
                    label=config.label,
                    core_facts=[
                        StructuredFact(
                            category=category,
                            statement=finding.description,
                            document_name=finding.source_documents[0] if finding.source_documents else config.label,
                            confidence="medium",
                            citations=finding.citations[:2],
                        )
                    ],
                    unresolved_questions=[f"Which source controls this lane: {finding.description}"],
                    why_it_matters=finding.why_it_matters,
                    likely_implication=config.generic_implication,
                    confidence="medium",
                    citations=finding.citations[:3],
                    source_documents=finding.source_documents[:3],
                    priority_score=finding.priority,
                    decision_summary=finding.description,
                )
            )
            existing_categories.add(category)

    enriched.sort(key=lambda item: (-item.priority_score, item.label))
    return enriched


def build_priority_assessment(
    issue_analyses: list[IssueAnalysis],
    contradictions: list[ContradictionFinding],
) -> PriorityAssessment:
    """Pass 4: rank the issue stack into decision-maker callouts."""

    ordered_issues = sorted(issue_analyses, key=lambda item: (-item.priority_score, item.label))
    top_deal_shaping_issues = [
        _priority_callout_from_issue(issue)
        for issue in ordered_issues[:3]
    ]

    top_cost_risk = _select_priority_callout(
        ordered_issues,
        lambda config: config.cost_weight,
    )
    top_timing_risk = _select_priority_callout(
        ordered_issues,
        lambda config: config.timing_weight,
    )
    top_closability_risk = _select_priority_callout(
        ordered_issues,
        lambda config: config.closability_weight,
    )

    if top_closability_risk is None and contradictions:
        title_tension = next(
            (finding for finding in contradictions if "Title / Access Concerns" in finding.related_categories),
            None,
        )
        if title_tension is not None:
            top_closability_risk = PriorityCallout(
                label="Top Closability Risk",
                statement=title_tension.description,
                why_it_matters=title_tension.why_it_matters,
                citations=title_tension.citations[:2],
                category="Title / Access Concerns",
            )

    return PriorityAssessment(
        top_deal_shaping_issues=top_deal_shaping_issues,
        top_cost_risk=top_cost_risk,
        top_timing_risk=top_timing_risk,
        top_closability_risk=top_closability_risk,
    )


def build_adversarial_challenges(
    *,
    issue_analyses: list[IssueAnalysis],
    contradictions: list[ContradictionFinding],
    missing_items: list[str],
    document_analyses: list[DocumentAnalysis],
    priority_assessment: PriorityAssessment,
) -> list[ChallengeFinding]:
    """Pass 5: identify optimistic assumptions and likely pushback."""

    challenges: list[ChallengeFinding] = []

    for finding in contradictions[:2]:
        challenges.append(
            ChallengeFinding(
                heading="Optimism Check",
                concern=finding.description,
                why_it_matters=finding.why_it_matters,
                likely_pushback=_pushback_for_categories(finding.related_categories),
                citations=finding.citations[:3],
                source_documents=finding.source_documents[:3],
                priority=finding.priority + 10,
            )
        )

    low_confidence_analyses = [analysis for analysis in document_analyses if analysis.confidence == "low"]
    for analysis in low_confidence_analyses[:1]:
        challenges.append(
            ChallengeFinding(
                heading="False Confidence Risk",
                concern=f"{analysis.document.title} is still low confidence, so the package can look more complete than it actually is in that lane.",
                why_it_matters="Unreadable or incomplete support weakens any conclusion that depends on that file for scope, basis, or closing comfort.",
                likely_pushback=f"An IC reviewer is likely to ask why the recommendation relies on {analysis.document.title} before the unreadable support is replaced.",
                citations=[],
                source_documents=[analysis.document.title],
                priority=85,
            )
        )

    if missing_items:
        challenges.append(
            ChallengeFinding(
                heading="Missing Support Challenge",
                concern=f"The package still lacks direct support for {missing_items[0].lower()}, which keeps part of the recommendation assumption-driven.",
                why_it_matters="Absent support increases the risk that a late document changes basis, timing, or legal posture after the deal advances.",
                likely_pushback=f"Leadership is likely to ask why the recommendation is moving forward before {missing_items[0].lower()} is verified.",
                citations=[],
                source_documents=[],
                priority=78,
            )
        )

    worsening_candidates = [
        callout
        for callout in (priority_assessment.top_cost_risk, priority_assessment.top_timing_risk)
        if callout is not None
    ]
    seen_worsening: set[str] = set()
    for callout in worsening_candidates:
        if callout.statement in seen_worsening:
            continue
        seen_worsening.add(callout.statement)
        challenges.append(
            ChallengeFinding(
                heading="Issue Most Likely To Worsen If Pursued",
                concern=callout.statement,
                why_it_matters=callout.why_it_matters,
                likely_pushback="If this assumption is wrong, the downside usually shows up after money and time have already been committed to the deal path.",
                citations=callout.citations[:2],
                source_documents=[],
                priority=74,
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


def build_category_rollup_from_issue_analyses(issue_analyses: list[IssueAnalysis]) -> dict[str, str]:
    """Build a concise rollup from multi-pass issue analyses."""

    return {
        issue.category: issue.decision_summary or issue.likely_implication
        for issue in issue_analyses
    }


def _related_missing_items(missing_items: list[str], config: _IssueConfig) -> list[str]:
    return [
        item
        for item in missing_items
        if any(term in item.lower() for term in config.missing_terms)
    ][:2]


def _related_low_confidence_documents(
    document_analyses: list[DocumentAnalysis],
    config: _IssueConfig,
) -> list[str]:
    return [
        analysis.document.title
        for analysis in document_analyses
        if analysis.confidence == "low" and config.risk_category in analysis.focus_areas
    ][:2]


def _build_issue_unresolved_questions(
    *,
    related_risk: RiskFinding | None,
    related_missing_items: list[str],
    related_documents: list[str],
) -> list[str]:
    questions: list[str] = []
    if related_risk is not None and related_risk.uncertainty_reason:
        questions.append(f"What direct support resolves this remaining uncertainty: {related_risk.uncertainty_reason}")
    for item in related_missing_items:
        questions.append(f"Where is the current support for {item.lower()} and is that support the version underwriting is relying on?")
    for document_title in related_documents:
        questions.append(f"Can {document_title} be replaced with a readable native file before this lane is treated as closed?")
    if not questions and related_risk is not None and related_risk.gating_flags:
        questions.append(f"What needs to happen before this issue can be cleared for {', '.join(related_risk.gating_flags).lower()}?")
    return unique_preserve_order(questions)[:4]


def _issue_confidence(
    selected_facts: list[StructuredFact],
    related_missing_items: list[str],
    related_risk: RiskFinding | None,
) -> str:
    if not selected_facts:
        return "low"
    if related_missing_items:
        return "medium"
    if any(fact.confidence == "low" for fact in selected_facts):
        return "medium"
    if related_risk is not None and related_risk.uncertainty_reason:
        return "medium"
    return "high"


def _issue_priority_score(
    config: _IssueConfig,
    related_risk: RiskFinding | None,
    selected_facts: list[StructuredFact],
    related_missing_items: list[str],
) -> int:
    severity_score = _SEVERITY_RANK.get(related_risk.severity, 1) * 10 if related_risk is not None else 0
    gating_score = len(related_risk.gating_flags) * 4 if related_risk is not None else 0
    fact_score = sum(_CONFIDENCE_RANK.get(fact.confidence, 1) for fact in selected_facts[:2])
    missing_score = len(related_missing_items) * 3
    bias_score = config.cost_weight + config.timing_weight + config.closability_weight
    uncertainty_penalty = 4 if related_risk is not None and related_risk.uncertainty_reason else 0
    confidence_penalty = 4 if any(fact.confidence == "medium" for fact in selected_facts[:1]) else 0
    return severity_score + gating_score + fact_score + missing_score + bias_score - uncertainty_penalty - confidence_penalty


def _issue_decision_summary(
    config: _IssueConfig,
    related_risk: RiskFinding | None,
    selected_facts: list[StructuredFact],
) -> str:
    if related_risk is not None and related_risk.issue:
        return f"{related_risk.issue} {related_risk.likely_implication}".strip()
    if selected_facts:
        return f"{selected_facts[0].statement} {config.generic_implication}".strip()
    return config.generic_implication


def _build_seed_facts(related_risk: RiskFinding | None, config: _IssueConfig) -> list[StructuredFact]:
    if related_risk is None:
        return []
    seed_text = related_risk.issue or related_risk.summary or config.generic_implication
    seed_document = related_risk.source_documents[0] if related_risk.source_documents else config.label
    return [
        StructuredFact(
            category=config.risk_category,
            statement=seed_text,
            document_name=seed_document,
            confidence="high" if related_risk.severity == "high" else "medium",
            citations=related_risk.citations[:2],
        )
    ]


def _filter_facts_for_issue(
    related_facts: list[StructuredFact],
    related_risk: RiskFinding | None,
    config: _IssueConfig,
    analysis_by_title: dict[str, DocumentAnalysis],
) -> list[StructuredFact]:
    category_aligned = [
        fact
        for fact in related_facts
        if _issue_document_alignment_score(
            fact.document_name,
            config=config,
            analysis_by_title=analysis_by_title,
        )
        >= 4
    ]
    if related_risk is None or not related_risk.source_documents:
        return category_aligned or related_facts

    preferred_documents = set(related_risk.source_documents)
    filtered = [
        fact
        for fact in category_aligned or related_facts
        if fact.document_name in preferred_documents
    ]
    if filtered:
        return filtered

    cited_documents = {citation.document_name for citation in related_risk.citations}
    filtered = [
        fact
        for fact in category_aligned or related_facts
        if fact.document_name in cited_documents
    ]
    return filtered or category_aligned or related_facts


def _select_issue_facts(
    *,
    facts: list[StructuredFact],
    config: _IssueConfig,
    related_risk: RiskFinding | None,
    analysis_by_title: dict[str, DocumentAnalysis],
) -> list[StructuredFact]:
    ordered = sorted(
        facts,
        key=lambda fact: (
            -_issue_fact_score(
                fact,
                config=config,
                related_risk=related_risk,
                analysis_by_title=analysis_by_title,
            ),
            -_CONFIDENCE_RANK.get(fact.confidence, 0),
            -len(fact.citations),
            fact.statement,
        ),
    )
    return ordered[:2]


def _issue_fact_score(
    fact: StructuredFact,
    *,
    config: _IssueConfig,
    related_risk: RiskFinding | None,
    analysis_by_title: dict[str, DocumentAnalysis],
) -> int:
    score = (_CONFIDENCE_RANK.get(fact.confidence, 1) * 10) + len(fact.citations)
    score += _issue_document_alignment_score(
        fact.document_name,
        config=config,
        analysis_by_title=analysis_by_title,
    )
    if related_risk is None:
        return score

    if fact.document_name in related_risk.source_documents:
        score += 8
    cited_documents = {citation.document_name for citation in related_risk.citations}
    if fact.document_name in cited_documents:
        score += 10
    if fact.statement == (related_risk.issue or related_risk.summary):
        score += 12
    return score


def _issue_document_alignment_score(
    document_name: str,
    *,
    config: _IssueConfig,
    analysis_by_title: dict[str, DocumentAnalysis],
) -> int:
    analysis = analysis_by_title.get(document_name)
    if analysis is None:
        return 0

    score = 0
    if config.risk_category in analysis.focus_areas:
        score += 8
    elif analysis.focus_areas:
        score -= 6

    rule = _RULE_BY_CATEGORY.get(config.risk_category)
    title_text = analysis.document.title.lower()
    path_text = analysis.document.relative_path.as_posix().lower()
    if rule is not None and any(hint in title_text or hint in path_text for hint in rule.path_hints):
        score += 4

    if analysis.confidence == "high":
        score += 2
    elif analysis.confidence == "low":
        score -= 2

    return score


def _priority_callout_from_issue(issue: IssueAnalysis) -> PriorityCallout:
    return PriorityCallout(
        label=issue.label,
        statement=issue.decision_summary,
        why_it_matters=issue.why_it_matters,
        citations=issue.citations[:2],
        category=issue.category,
    )


def _select_priority_callout(
    ordered_issues: list[IssueAnalysis],
    weight_selector,
) -> PriorityCallout | None:
    ranked: list[tuple[int, IssueAnalysis]] = []
    for issue in ordered_issues:
        config = _CONFIG_BY_RISK_CATEGORY.get(issue.category)
        if config is None:
            continue
        weight = weight_selector(config)
        if weight <= 0:
            continue
        ranked.append((issue.priority_score + (weight * 5), issue))
    if not ranked:
        return None
    ranked.sort(key=lambda item: (-item[0], item[1].label))
    return _priority_callout_from_issue(ranked[0][1])


def _pushback_for_categories(categories: list[str]) -> str:
    if "Title / Access Concerns" in categories:
        return "An IC reviewer is likely to push back on any recommendation that assumes clean closing while title and access remain unreconciled to the plan set."
    if "Offsite Obligations" in categories:
        return "An IC reviewer is likely to ask who actually owns the frontage and offsite cost before approving basis."
    if "Budget / Cost Reliability" in categories or "Geotechnical Risks" in categories:
        return "An IC reviewer is likely to challenge whether the current budget really carries the technical scope the reports require."
    if "Entitlement Status" in categories:
        return "An IC reviewer is likely to ask whether approvals are being overstated when conditions of approval still drive the permit path."
    return "An IC reviewer is likely to challenge whether the current package is more assumption-driven than the recommendation implies."


def _unique_citations(citations: list[Citation]) -> list[Citation]:
    seen: set[Citation] = set()
    ordered: list[Citation] = []
    for citation in citations:
        if citation in seen:
            continue
        seen.add(citation)
        ordered.append(citation)
    return ordered
