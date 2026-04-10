"""Typed data models shared across the ingestion and analysis pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(slots=True, frozen=True)
class Citation:
    """Compact source reference for a claim or evidence snippet."""

    document_name: str
    chunk_id: str
    page_number: int | None = None


@dataclass(slots=True)
class ExtractedChunk:
    """Normalized chunk-level extraction record used for traceable analysis."""

    document_name: str
    chunk_id: str
    text: str
    page_number: int | None = None
    ocr_used: bool = False


@dataclass(slots=True)
class DocumentRecord:
    """Normalized representation of an extracted diligence document."""

    source_path: Path
    relative_path: Path
    extension: str
    title: str
    raw_text: str
    normalized_text: str
    metadata: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    chunks: list[ExtractedChunk] = field(default_factory=list)
    ocr_pages: list[int] = field(default_factory=list)
    ocr_recovered_pages: list[int] = field(default_factory=list)


@dataclass(slots=True)
class FileProcessingResult:
    """Outcome for a single file discovered during a run."""

    relative_path: str
    status: str
    warnings: list[str] = field(default_factory=list)
    error_message: str | None = None
    ocr_pages: list[int] = field(default_factory=list)
    ocr_recovered_pages: list[int] = field(default_factory=list)


@dataclass(slots=True)
class RiskFinding:
    """Structured finding for a diligence risk theme."""

    category: str
    severity: str
    summary: str
    evidence: list[str] = field(default_factory=list)
    issue: str = ""
    why_it_matters: str = ""
    likely_implication: str = ""
    source_documents: list[str] = field(default_factory=list)
    anchor: str = ""
    priority_tier: str = ""
    gating_flags: list[str] = field(default_factory=list)
    uncertainty_reason: str = ""
    citations: list[Citation] = field(default_factory=list)
    specificity_score: int = 0
    specificity_basis: str = ""
    generic_signal_only: bool = False


@dataclass(slots=True)
class ContradictionFinding:
    """Focused cross-document contradiction or tension finding."""

    description: str
    why_it_matters: str
    citations: list[Citation] = field(default_factory=list)
    source_documents: list[str] = field(default_factory=list)
    related_categories: list[str] = field(default_factory=list)
    priority: int = 0


@dataclass(slots=True)
class OmissionAssessment:
    """Assessment of whether a normally expected diligence item is present and usable."""

    item: str
    category: str
    status: str
    rationale: str
    source_documents: list[str] = field(default_factory=list)
    citations: list[Citation] = field(default_factory=list)
    front_end_status: str = ""
    importance: str = "normal"
    recommended_request: str = ""
    front_end_reason: str = ""


@dataclass(slots=True)
class StructuredFact:
    """Document-anchored fact extracted into an issue/category lane."""

    category: str
    statement: str
    document_name: str
    confidence: str
    citations: list[Citation] = field(default_factory=list)


@dataclass(slots=True)
class FactValidationStats:
    """Inspectable counts for fact cleaning before downstream analysis."""

    total_candidates: int = 0
    kept_count: int = 0
    filtered_count: int = 0
    deduplicated_count: int = 0
    downgraded_count: int = 0
    low_confidence_excluded_count: int = 0
    weak_context_count: int = 0


@dataclass(slots=True)
class FactValidationLogEntry:
    """Debug trace for a fact that was kept, downgraded, deduplicated, or filtered."""

    lane: str
    action: str
    fact_type: str
    value: str
    normalized_value: str = ""
    reason: str = ""
    source_document: str = ""
    confidence_before: str = ""
    confidence_after: str = ""


@dataclass(slots=True)
class IssueFragment:
    """Intermediate fragment before canonical issue consolidation."""

    fragment_id: str
    source_type: str
    title: str
    category: str
    dependency_key: str
    status: str
    source_title: str = ""
    core_facts: list[str] = field(default_factory=list)
    best_evidence: list[str] = field(default_factory=list)
    why_it_matters: str = ""
    likely_implication: str = ""
    what_would_resolve_it: str = ""
    open_questions: list[str] = field(default_factory=list)
    confidence: str = "medium"
    severity: str = "medium"
    likelihood: str = "medium"
    timing_sensitivity: str = "medium"
    cost_sensitivity: str = "medium"
    fixability: str = "medium"
    decision_action: str = "verify"
    citations: list[Citation] = field(default_factory=list)
    source_documents: list[str] = field(default_factory=list)
    gating_flags: list[str] = field(default_factory=list)


@dataclass(slots=True)
class IssueAnalysis:
    """Multi-pass issue analysis for one acquisition workstream."""

    category: str
    label: str
    core_facts: list[StructuredFact]
    unresolved_questions: list[str]
    why_it_matters: str
    likely_implication: str
    confidence: str
    citations: list[Citation] = field(default_factory=list)
    source_documents: list[str] = field(default_factory=list)
    priority_score: int = 0
    decision_summary: str = ""


@dataclass(slots=True)
class ChallengeFinding:
    """Adversarial challenge against the current recommendation."""

    heading: str
    concern: str
    why_it_matters: str
    likely_pushback: str
    citations: list[Citation] = field(default_factory=list)
    source_documents: list[str] = field(default_factory=list)
    priority: int = 0


@dataclass(slots=True)
class PriorityCallout:
    """Named priority cut for the decision-maker."""

    label: str
    statement: str
    why_it_matters: str
    citations: list[Citation] = field(default_factory=list)
    category: str = ""


@dataclass(slots=True, frozen=True)
class DealMetadata:
    """Portable deal metadata used for precedent matching and calibration."""

    stage: str = ""
    region: str = ""
    product: str = ""


@dataclass(slots=True)
class PriorityAssessment:
    """Decision-priority rollup derived from issue analyses and contradictions."""

    top_deal_shaping_issues: list[PriorityCallout] = field(default_factory=list)
    top_cost_risk: PriorityCallout | None = None
    top_timing_risk: PriorityCallout | None = None
    top_closability_risk: PriorityCallout | None = None


@dataclass(slots=True, frozen=True)
class PriorityWeights:
    """Configurable weights for decision-priority scoring."""

    cost_exposure: int = 5
    schedule_exposure: int = 5
    yield_exposure: int = 3
    entitlement_fragility: int = 5
    closing_risk: int = 6
    likelihood: int = 4
    evidence_confidence: int = 3
    preclose_mitigation_difficulty: int = 4
    seller_shiftability_penalty: int = 3
    ic_sensitivity: int = 5
    precedent_signal: int = 1
    learning_signal: int = 1


@dataclass(slots=True)
class IssuePriorityScore:
    """Weighted score breakdown for a canonical issue."""

    total: int = 0
    cost_exposure: int = 0
    schedule_exposure: int = 0
    yield_exposure: int = 0
    entitlement_fragility: int = 0
    closing_risk: int = 0
    likelihood: int = 0
    evidence_confidence: int = 0
    preclose_mitigation_difficulty: int = 0
    seller_shiftability: int = 0
    ic_sensitivity: int = 0
    calibration_adjustment: int = 0
    precedent_adjustment: int = 0
    learning_adjustment: int = 0
    feedback_adjustment: int = 0
    evaluator_adjustment: int = 0


@dataclass(slots=True)
class PrecedentReference:
    """Retrieved precedent issue used for outcome-aware calibration."""

    precedent_id: str
    title: str
    issue_id: str = ""
    deal_id: str = ""
    deal_name: str = ""
    issue_type: str = ""
    canonical_title: str = ""
    category: str = ""
    deal_metadata: DealMetadata = field(default_factory=DealMetadata)
    similarity_score: float = 0.0
    category_match: bool = False
    stage_match: bool = False
    region_match: bool = False
    product_match: bool = False
    real_issue: bool | None = None
    materiality: str = "medium"
    actual_outcome: str = "unknown"
    false_positive_flag: bool = False
    decision_relevant: bool | None = None
    resolved_by: str = "unknown"
    resolution_notes: str = ""
    relevance: str = ""
    note: str = ""


@dataclass(slots=True)
class PrecedentIssueRecord:
    """Historical issue outcome record used by the local precedent store."""

    precedent_id: str
    deal_name: str
    issue_type: str
    canonical_title: str
    category: str
    issue_id: str = ""
    deal_id: str = ""
    description: str = ""
    deal_metadata: DealMetadata = field(default_factory=DealMetadata)
    evidence_basis: str = ""
    issue_strength: str = ""
    real_issue: bool | None = None
    materiality: str = "medium"
    decision_relevant: bool | None = None
    actual_outcome: str = "unknown"
    false_positive_flag: bool = False
    resolved_by: str = "unknown"
    notes: str = ""
    resolution_notes: str = ""
    label_source: str = "reviewer"
    label_confidence: str = "high"


@dataclass(slots=True)
class PrecedentSummary:
    """Aggregate precedent calibration for one canonical issue."""

    historical_frequency: int = 0
    real_rate: float | None = None
    false_positive_rate: float | None = None
    outcome_stats: dict[str, int] = field(default_factory=dict)
    typical_impact: str = "none"
    resolution_pattern: str = ""
    confidence_adjustment: str = "neutral"
    score_adjustment: int = 0
    sample_size: int = 0
    sparse_data: bool = True
    reasoning: str = ""


@dataclass(slots=True)
class PrecedentCalibration:
    """Retrieved precedent matches plus the summary used to calibrate an issue."""

    matches: list[PrecedentReference] = field(default_factory=list)
    summary: PrecedentSummary = field(default_factory=PrecedentSummary)


@dataclass(slots=True)
class LearningSummary:
    """Local learned calibration built from reviewer-labeled historical records."""

    sample_size: int = 0
    real_issue_rate: float | None = None
    false_positive_rate: float | None = None
    material_issue_rate: float | None = None
    decision_relevant_rate: float | None = None
    impact_rate: float | None = None
    matched_features: list[str] = field(default_factory=list)
    confidence_adjustment: str = "neutral"
    score_adjustment: int = 0
    reasoning: str = ""


@dataclass(slots=True)
class AutonomousLearningSummary:
    """Inspectible summary of autonomous pseudo-label generation for future runs."""

    enabled: bool = False
    store_path: str = ""
    records_generated: int = 0
    positive_records: int = 0
    negative_records: int = 0
    skipped_issues: int = 0
    events: list[str] = field(default_factory=list)
    reasoning: str = ""


@dataclass(slots=True)
class ReviewerIssueFeedback:
    """Reviewer feedback template row for post-run calibration."""

    issue_id: str
    canonical_title: str = ""
    category: str = ""
    deal_id: str = ""
    deal_name: str = ""
    deal_metadata: DealMetadata = field(default_factory=DealMetadata)
    evidence_basis: str = ""
    issue_strength: str = ""
    false_positive_risk: str = ""
    model_materiality: str = "medium"
    model_decision_relevant: bool | None = None
    model_action: str = ""
    real_issue: bool | None = None
    false_positive_flag: bool = False
    materiality: str = "medium"
    decision_relevant: bool | None = None
    duplicate_of: str | None = None
    overstated: bool = False
    understated: bool = False
    actual_outcome: str = "unknown"
    resolved_by: str = "unknown"
    correct_action: str = ""
    notes: str = ""


@dataclass(slots=True)
class IssueFeedbackEntry:
    """Per-issue reviewer feedback for one local deal run."""

    issue_id: str
    issue_type: str = ""
    canonical_title: str = ""
    category: str = ""
    model_severity: str = ""
    feedback_status: str = ""
    severity_override: str = ""
    reviewer_notes: str = ""
    likely_cause: str = ""
    observed_impact: str = ""
    source_documents: list[str] = field(default_factory=list)
    source_document_types: list[str] = field(default_factory=list)
    confidence_score: int = 0
    confidence_level: str = "low"


@dataclass(slots=True)
class MissedIssueFeedback:
    """Reviewer-supplied issue that the current run failed to elevate."""

    title: str
    category: str = ""
    issue_type: str = ""
    expected_severity: str = ""
    likely_cause: str = ""
    observed_impact: str = ""
    source_documents: list[str] = field(default_factory=list)
    source_document_types: list[str] = field(default_factory=list)
    reviewer_notes: str = ""


@dataclass(slots=True)
class DealFeedbackRecord:
    """Structured per-deal feedback artifact used for deterministic learning."""

    schema_version: str = "1.0"
    deal_id: str = ""
    deal_name: str = ""
    run_id: str = ""
    generated_at: str = ""
    knowledge_base_path: str = ""
    allowed_feedback_statuses: list[str] = field(default_factory=lambda: ["correct", "incorrect", "irrelevant", "missed"])
    issue_feedback: list[IssueFeedbackEntry] = field(default_factory=list)
    missed_issues: list[MissedIssueFeedback] = field(default_factory=list)


@dataclass(slots=True)
class IssuePatternRecord:
    """Persistent deterministic pattern learned from prior reviewer feedback."""

    pattern_id: str
    issue_type: str
    canonical_title: str = ""
    categories: list[str] = field(default_factory=list)
    common_causes: list[str] = field(default_factory=list)
    common_impacts: list[str] = field(default_factory=list)
    preferred_document_types: list[str] = field(default_factory=list)
    high_impact: bool = False
    priority_boost: int = 0
    feedback_stats: dict[str, int] = field(default_factory=dict)
    severity_overrides: dict[str, int] = field(default_factory=dict)
    cause_counts: dict[str, int] = field(default_factory=dict)
    impact_counts: dict[str, int] = field(default_factory=dict)
    document_type_counts: dict[str, int] = field(default_factory=dict)
    last_updated: str = ""


@dataclass(slots=True)
class IssueKnowledgeBase:
    """Persistent issue-pattern knowledge base built from deterministic feedback."""

    schema_version: str = "1.0"
    updated_at: str = ""
    patterns: list[IssuePatternRecord] = field(default_factory=list)


@dataclass(slots=True)
class IssueMergeSuggestion:
    """Evaluator suggestion for redundant issues that should collapse in ranking."""

    primary_issue_id: str
    secondary_issue_id: str
    rationale: str = ""


@dataclass(slots=True)
class IssueRegistryEvaluation:
    """Evaluator output for the ranked canonical issue set."""

    redundancy_score: int = 0
    false_positive_score: int = 0
    missed_issue_risk: int = 0
    ranking_quality: int = 100
    top_issues_should_be: list[str] = field(default_factory=list)
    issues_to_remove: list[str] = field(default_factory=list)
    issues_to_merge: list[IssueMergeSuggestion] = field(default_factory=list)
    revision_applied: bool = False
    revision_reason: str = ""


@dataclass(slots=True)
class IssueDependencyLink:
    """Directed dependency edge between canonical issues."""

    issue_id: str
    title: str = ""
    dependency_type: str = ""
    mechanism: str = ""
    effect: str = ""


@dataclass(slots=True)
class ResearchAgendaItem:
    """Practical next-step item for front-end diligence follow-up."""

    issue_id: str = ""
    title: str = ""
    verify_what: str = ""
    request_item: str = ""
    likely_source: str = ""
    timing: str = "now"


@dataclass(slots=True)
class IssueCluster:
    """Causal cluster of linked issues with a root issue and downstream effects."""

    cluster_id: str
    label: str
    tier: str = ""
    root_issue_id: str = ""
    issue_ids: list[str] = field(default_factory=list)
    downstream_effects: list[str] = field(default_factory=list)
    key_unresolved_confirmations: list[str] = field(default_factory=list)
    decision_implication: str = ""
    critical_path_issue_ids: list[str] = field(default_factory=list)


@dataclass(slots=True)
class MergeArbitrationRecord:
    """Trace for ambiguous merge review, optionally via LLM arbitration."""

    left_key: str
    right_key: str
    deterministic_relation: str
    deterministic_confidence: str
    final_relation: str
    used_arbiter: bool = False
    rationale: str = ""


@dataclass(slots=True)
class CanonicalIssue:
    """Single source-of-truth issue used by all downstream outputs."""

    issue_id: str
    title: str
    category: str
    status: str
    issue_type: str = ""
    core_facts: list[str] = field(default_factory=list)
    best_evidence: list[str] = field(default_factory=list)
    why_it_matters: str = ""
    likely_implication: str = ""
    what_would_resolve_it: str = ""
    open_questions: list[str] = field(default_factory=list)
    confidence: str = "medium"
    severity: str = "medium"
    likelihood: str = "medium"
    timing_sensitivity: str = "medium"
    cost_sensitivity: str = "medium"
    fixability: str = "medium"
    decision_action: str = "verify"
    citations: list[Citation] = field(default_factory=list)
    source_documents: list[str] = field(default_factory=list)
    gating_flags: list[str] = field(default_factory=list)
    merged_fragment_ids: list[str] = field(default_factory=list)
    merged_fragment_titles: list[str] = field(default_factory=list)
    priority_score: IssuePriorityScore = field(default_factory=IssuePriorityScore)
    materiality: str = "medium"
    evidence_basis: str = "weak_inference"
    issue_strength: str = "moderate"
    false_positive_risk: str = "medium"
    normal_friction_flag: bool = False
    decision_relevant: bool = True
    top_line_eligible: bool = True
    top_line_filter_reasons: list[str] = field(default_factory=list)
    calibration_notes: list[str] = field(default_factory=list)
    precedent_references: list[PrecedentReference] = field(default_factory=list)
    precedent_summary: PrecedentSummary = field(default_factory=PrecedentSummary)
    learning_summary: LearningSummary = field(default_factory=LearningSummary)
    dependency_type: str = ""
    upstream_dependencies: list[IssueDependencyLink] = field(default_factory=list)
    downstream_dependencies: list[IssueDependencyLink] = field(default_factory=list)
    critical_path_flag: bool = False
    blocking_flag: bool = False
    blocker_classification: str = "monitoring issue"
    schedule_impact_classification: str = "non-blocking"
    blocking_reason: str = ""
    critical_path_reason: str = ""
    likely_cost_effect: str = ""
    likely_schedule_effect: str = ""
    likely_yield_or_product_effect: str = ""
    likely_closing_effect: str = ""
    likely_structure_effect: str = ""
    likely_underwriting_effect: str = ""
    acquisition_severity: str = "LOW"
    acquisition_severity_reason: str = ""
    affects: list[str] = field(default_factory=list)
    practical_impact: str = ""
    deal_impact_type: str = ""
    deal_impact_magnitude: str = ""
    deal_impact_mechanism: str = ""
    cost_exposure_band: str = ""
    timing_exposure_band: str = ""
    fixability_classification: str = ""
    downside_if_wrong: str = ""
    likely_explanation: str = ""
    reality_vs_noise: str = ""
    gating_item: bool = False
    front_end_flag: str = "routine item"
    front_end_flag_reason: str = ""
    information_status: str = "present and adequate"
    information_status_reason: str = ""
    normality_classification: str = "unknown"
    process_friction_flag: bool = False
    unusualness_rationale: str = ""
    why_now: str = "unclear"
    specificity_level: str = "generic"
    abnormality_basis: str = "routine category only"
    site_specific_trigger: str = ""
    genericity_penalty: int = 0
    missing_confirmation: str = ""
    research_agenda: list[ResearchAgendaItem] = field(default_factory=list)
    confidence_score: int = 0
    confidence_level: str = "low"
    confidence_factors: list[str] = field(default_factory=list)
    knowledge_pattern_id: str = ""
    knowledge_pattern_summary: str = ""
    knowledge_priority_boost: int = 0
    knowledge_feedback_counts: dict[str, int] = field(default_factory=dict)
    output_bucket: str = "appendix"


@dataclass(slots=True)
class MergeDecision:
    """Traceable merge record for canonical issue consolidation."""

    canonical_issue_id: str
    dependency_key: str
    fragment_ids: list[str] = field(default_factory=list)
    fragment_titles: list[str] = field(default_factory=list)
    rationale: str = ""


@dataclass(slots=True)
class OutputIssueSelection:
    """Selection trace for which canonical issues feed each output."""

    output_name: str
    issue_id: str
    rank: int
    reason: str


@dataclass(slots=True)
class RecommendationDecision:
    """Decision posture built from ranked canonical issues."""

    posture: str = "pause"
    rationale: str = ""
    reasons: list[str] = field(default_factory=list)
    conditions: list[str] = field(default_factory=list)


@dataclass(slots=True)
class CanonicalIssueRegistry:
    """Inspectable canonical issue registry and its supporting decisions."""

    fragments: list[IssueFragment] = field(default_factory=list)
    issues: list[CanonicalIssue] = field(default_factory=list)
    merge_decisions: list[MergeDecision] = field(default_factory=list)
    arbitration_records: list[MergeArbitrationRecord] = field(default_factory=list)
    omission_assessments: list[OmissionAssessment] = field(default_factory=list)
    output_selections: list[OutputIssueSelection] = field(default_factory=list)
    weights: PriorityWeights = field(default_factory=PriorityWeights)
    deal_metadata: DealMetadata = field(default_factory=DealMetadata)
    evaluator_result: IssueRegistryEvaluation = field(default_factory=IssueRegistryEvaluation)
    initial_issue_order: list[str] = field(default_factory=list)
    final_issue_order: list[str] = field(default_factory=list)
    issue_clusters: list[IssueCluster] = field(default_factory=list)
    blocker_issue_ids: list[str] = field(default_factory=list)
    sequencing_issue_ids: list[str] = field(default_factory=list)
    confirmatory_issue_ids: list[str] = field(default_factory=list)
    monitoring_issue_ids: list[str] = field(default_factory=list)
    critical_path_issue_ids: list[str] = field(default_factory=list)
    central_risk_pattern: str = ""
    cluster_pattern: str = ""
    fragility_classification: str = ""
    critical_path_summary: str = ""
    confidence_unlocks: list[str] = field(default_factory=list)
    package_quality: str = ""
    package_quality_reason: str = ""
    confidence_in_initial_read: str = "medium"
    package_quality_inputs: list[str] = field(default_factory=list)
    concern_pattern: str = ""
    front_end_known_points: list[str] = field(default_factory=list)
    front_end_unresolved_points: list[str] = field(default_factory=list)
    front_end_routine_points: list[str] = field(default_factory=list)
    front_end_elevated_points: list[str] = field(default_factory=list)
    front_end_attention_now_points: list[str] = field(default_factory=list)
    front_end_deeper_work: list[str] = field(default_factory=list)


@dataclass(slots=True)
class LLMCallFailure:
    """Structured details for a failed LLM refinement call."""

    stage: str
    target: str
    model: str
    detail: str


@dataclass(slots=True)
class ReadingRecommendation:
    """Suggested document reading sequence for deal review."""

    title: str
    relative_path: str
    priority: int
    reason: str
    confidence: str
    focus_areas: list[str] = field(default_factory=list)
    bucket: str = "should skim"
    document_role: str = "supporting"
    rationale_factors: list[str] = field(default_factory=list)


@dataclass(slots=True)
class DocumentAnalysis:
    """Per-document analysis output."""

    document: DocumentRecord
    summary: str
    risks: list[RiskFinding]
    seller_questions: list[str]
    reading_priority: int
    reading_reason: str
    confidence: str
    confidence_reason: str
    focus_areas: list[str] = field(default_factory=list)
    missing_items: list[str] = field(default_factory=list)
    document_takeaway: str = ""
    key_points: list[str] = field(default_factory=list)
    open_loops: list[str] = field(default_factory=list)
    document_role: str = "supporting"
    staleness_status: str = "present and adequate"
    staleness_reason: str = ""
    contradiction_count: int = 0
    reading_bucket: str = "should skim"
    reading_rationale_factors: list[str] = field(default_factory=list)


@dataclass(slots=True)
class FurtherDiligenceRoadmap:
    """Front-end follow-up roadmap built from flags, blind spots, and document quality."""

    top_real_flags: list[str] = field(default_factory=list)
    top_missing_items_to_request: list[str] = field(default_factory=list)
    top_contradictions_to_resolve: list[str] = field(default_factory=list)
    top_stale_materials_to_refresh: list[str] = field(default_factory=list)
    top_public_consultant_internal_research: list[str] = field(default_factory=list)
    top_documents_to_read_first: list[str] = field(default_factory=list)
    deal_killers_or_gating_items: list[str] = field(default_factory=list)
    recommended_next_steps: list[str] = field(default_factory=list)
    follow_up_order: list[str] = field(default_factory=list)
    investigate_immediately: list[str] = field(default_factory=list)
    request_or_verify_soon: list[str] = field(default_factory=list)
    read_personally: list[str] = field(default_factory=list)
    monitor_later: list[str] = field(default_factory=list)
    likely_routine_unless_changed: list[str] = field(default_factory=list)


@dataclass(slots=True)
class AcquisitionControllingFact:
    """Controlling fact adjudication for one underwriting-critical descriptor."""

    fact_type: str
    label: str
    controlling_value: str
    controlling_document: str
    why_it_controls: str
    rejected_alternatives: list[str] = field(default_factory=list)
    citations: list[Citation] = field(default_factory=list)


@dataclass(slots=True)
class AcquisitionRiskItem:
    """IC-ready risk item grouped into a decisive acquisition bucket."""

    bucket: str
    title: str
    summary: str
    impact: str
    timing: str
    curability: str
    issue_id: str = ""
    citations: list[Citation] = field(default_factory=list)
    source_documents: list[str] = field(default_factory=list)


@dataclass(slots=True)
class AcquisitionCriticalPathStep:
    """Ordered blocker on the path to a specific execution milestone."""

    target: str
    sequence: int
    blocker: str
    why_it_blocks: str
    issue_id: str = ""
    citations: list[Citation] = field(default_factory=list)
    source_documents: list[str] = field(default_factory=list)


@dataclass(slots=True)
class AcquisitionInsight:
    """Non-obvious acquisition insight surfaced by the second pass."""

    title: str
    detail: str
    citations: list[Citation] = field(default_factory=list)
    source_documents: list[str] = field(default_factory=list)


@dataclass(slots=True)
class AcquisitionDecision:
    """Investment decision frame produced by the acquisition second pass."""

    posture: str = "Advance Only If"
    rationale: str = ""
    top_real_risks: list[str] = field(default_factory=list)
    price_or_structure_changes: list[str] = field(default_factory=list)
    biggest_unknown: str = ""
    citations: list[Citation] = field(default_factory=list)


@dataclass(slots=True)
class AcquisitionJudgment:
    """Acquisition-grade second-pass synthesis layered on top of issue reasoning."""

    controlling_facts: list[AcquisitionControllingFact] = field(default_factory=list)
    risk_items: list[AcquisitionRiskItem] = field(default_factory=list)
    critical_path: list[AcquisitionCriticalPathStep] = field(default_factory=list)
    investment_decision: AcquisitionDecision = field(default_factory=AcquisitionDecision)
    weak_acquisition_misses: list[AcquisitionInsight] = field(default_factory=list)


@dataclass(slots=True)
class WebResearchResult:
    """Public-web fallback result for an unresolved diligence question."""

    issue_id: str
    title: str
    question: str
    query: str
    status: str = "not_run"
    answer: str = ""
    confidence: str = "low"
    next_step: str = ""
    source_titles: list[str] = field(default_factory=list)
    source_urls: list[str] = field(default_factory=list)
    source_snippets: list[str] = field(default_factory=list)
    note: str = ""


@dataclass(slots=True)
class DealSynthesis:
    """Deal-level rollup assembled from all document analyses."""

    deal_name: str
    executive_summary: str
    entitlement_status: str
    key_risks: list[RiskFinding]
    recommended_reading_order: list[ReadingRecommendation]
    seller_questions: list[str]
    missing_items: list[str]
    category_rollup: dict[str, str]
    document_analyses: list[DocumentAnalysis]
    structured_facts: list[StructuredFact] = field(default_factory=list)
    fact_validation_stats: FactValidationStats = field(default_factory=FactValidationStats)
    fact_validation_log: list[FactValidationLogEntry] = field(default_factory=list)
    omission_assessments: list[OmissionAssessment] = field(default_factory=list)
    issue_analyses: list[IssueAnalysis] = field(default_factory=list)
    canonical_issue_registry: CanonicalIssueRegistry = field(default_factory=CanonicalIssueRegistry)
    challenge_findings: list[ChallengeFinding] = field(default_factory=list)
    priority_assessment: PriorityAssessment = field(default_factory=PriorityAssessment)
    recommendation: RecommendationDecision = field(default_factory=RecommendationDecision)
    contradictions: list[ContradictionFinding] = field(default_factory=list)
    further_diligence_roadmap: FurtherDiligenceRoadmap = field(default_factory=FurtherDiligenceRoadmap)
    acquisition_judgment: AcquisitionJudgment = field(default_factory=AcquisitionJudgment)
    web_research_results: list[WebResearchResult] = field(default_factory=list)
    autonomous_learning_summary: AutonomousLearningSummary = field(default_factory=AutonomousLearningSummary)
    autonomous_learning_records: list[PrecedentIssueRecord] = field(default_factory=list)
    extraction_errors: list[str] = field(default_factory=list)
    llm_failures: list[LLMCallFailure] = field(default_factory=list)
    analysis_mode: str = "full"
    llm_calls_attempted: int = 0


@dataclass(slots=True)
class RunSummary:
    """Operational summary for a diligence CLI run."""

    run_id: str
    deal_name: str
    input_folder: str
    output_folder: str
    llm_provider: str
    started_at: str
    llm_model: str | None = None
    completed_at: str | None = None
    analysis_mode: str = "fast"
    llm_calls_made: int = 0
    web_research_queries: int = 0
    autonomous_learning_records: int = 0
    files_found: int = 0
    files_parsed_successfully: int = 0
    files_failed: int = 0
    output_files_created: list[str] = field(default_factory=list)
    file_results: list[FileProcessingResult] = field(default_factory=list)
    run_errors: list[str] = field(default_factory=list)
