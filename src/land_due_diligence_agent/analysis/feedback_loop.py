"""Deterministic reviewer-feedback and issue-pattern learning helpers."""

from __future__ import annotations

import json
import re
from collections import defaultdict
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from land_due_diligence_agent.models import (
    CanonicalIssue,
    CanonicalIssueRegistry,
    DealFeedbackRecord,
    DealSynthesis,
    DocumentAnalysis,
    IssueFeedbackEntry,
    IssueKnowledgeBase,
    IssuePatternRecord,
    MissedIssueFeedback,
)
from land_due_diligence_agent.utils.files import ensure_directory, slugify
from land_due_diligence_agent.utils.text import clip_text, normalize_text, unique_preserve_order

_DEFAULT_PATTERN_PATH = Path(__file__).resolve().parents[3] / "data" / "precedents" / "issue_patterns.json"
_ALLOWED_FEEDBACK = {"correct", "incorrect", "irrelevant", "missed"}
_SEVERITY_ORDER = {"CRITICAL": 0, "HIGH": 1, "MODERATE": 2, "LOW": 3, "": 4}
_EXPECTED_DOCUMENT_TYPES = {
    "Title / Access Concerns": {"title", "survey", "legal"},
    "Entitlement Status": {"entitlement", "plan", "legal"},
    "Environmental Risks": {"environmental"},
    "Geotechnical Risks": {"geotechnical", "plan"},
    "Flood / Drainage Issues": {"drainage", "plan"},
    "Utilities / Infrastructure Issues": {"utilities", "plan"},
    "Offsite Obligations": {"offsite", "plan", "legal"},
    "Fee / Exaction Burden": {"cost", "legal"},
    "Budget / Cost Reliability": {"cost"},
    "Schedule Risks": {"entitlement", "utilities", "offsite", "cost", "plan"},
}
_SEED_PATTERNS: tuple[IssuePatternRecord, ...] = (
    IssuePatternRecord(
        pattern_id="title-access-clearance",
        issue_type="title-access-clearance",
        canonical_title="Title access clearance unresolved",
        categories=["Title / Access Concerns"],
        common_causes=["unresolved title exception or access rights not reconciled to the current plan"],
        common_impacts=["closability and legal/title clarity"],
        preferred_document_types=["title", "survey"],
        high_impact=True,
    ),
    IssuePatternRecord(
        pattern_id="entitlement-conditions",
        issue_type="entitlement-conditions",
        canonical_title="Entitlement condition closeout unresolved",
        categories=["Entitlement Status"],
        common_causes=["approval status outrunning condition closeout or controlling resolution support"],
        common_impacts=["timeline and entitlement certainty"],
        preferred_document_types=["entitlement", "plan"],
        high_impact=True,
    ),
    IssuePatternRecord(
        pattern_id="utility-capacity",
        issue_type="utility-capacity",
        canonical_title="Utility capacity confirmation unresolved",
        categories=["Utilities / Infrastructure Issues"],
        common_causes=["will-serve support or provider confirmation not closing the current utility assumption"],
        common_impacts=["timeline and offsite utility cost"],
        preferred_document_types=["utilities", "plan"],
        high_impact=True,
    ),
    IssuePatternRecord(
        pattern_id="environmental-followup",
        issue_type="environmental-followup",
        canonical_title="Environmental follow-up unresolved",
        categories=["Environmental Risks"],
        common_causes=["phase i, mitigation, or agency follow-up remaining open"],
        common_impacts=["cost, structure, and timeline"],
        preferred_document_types=["environmental"],
        high_impact=True,
    ),
    IssuePatternRecord(
        pattern_id="geotechnical-scope",
        issue_type="geotechnical-scope",
        canonical_title="Geotechnical scope unresolved",
        categories=["Geotechnical Risks"],
        common_causes=["soils recommendations not fully carried into grading, retaining, or foundation scope"],
        common_impacts=["cost and yield"],
        preferred_document_types=["geotechnical", "plan"],
        high_impact=True,
    ),
    IssuePatternRecord(
        pattern_id="stormwater-drainage",
        issue_type="stormwater-drainage",
        canonical_title="Stormwater drainage scope unresolved",
        categories=["Flood / Drainage Issues"],
        common_causes=["drainage design or public-works confirmation remaining open"],
        common_impacts=["cost and timeline"],
        preferred_document_types=["drainage", "plan"],
        high_impact=True,
    ),
    IssuePatternRecord(
        pattern_id="offsite-frontage",
        issue_type="offsite-frontage",
        canonical_title="Offsite frontage scope unresolved",
        categories=["Offsite Obligations"],
        common_causes=["buyer-facing frontage or offsite obligations not allocated cleanly"],
        common_impacts=["cost, closability, and timeline"],
        preferred_document_types=["offsite", "plan", "legal"],
        high_impact=True,
    ),
    IssuePatternRecord(
        pattern_id="fee-stack",
        issue_type="fee-stack",
        canonical_title="Fee stack unresolved",
        categories=["Fee / Exaction Burden"],
        common_causes=["fee schedule remaining preliminary or stale"],
        common_impacts=["price and underwriting"],
        preferred_document_types=["cost", "legal"],
        high_impact=True,
    ),
    IssuePatternRecord(
        pattern_id="budget-reliability",
        issue_type="budget-reliability",
        canonical_title="Budget reliability unresolved",
        categories=["Budget / Cost Reliability"],
        common_causes=["site-cost support remaining budgetary rather than auditable"],
        common_impacts=["price and underwriting"],
        preferred_document_types=["cost"],
        high_impact=True,
    ),
)


def default_issue_patterns_path(path: Path | None = None) -> Path:
    return path or _DEFAULT_PATTERN_PATH


def load_issue_knowledge_base(path: Path | None = None) -> IssueKnowledgeBase:
    resolved_path = default_issue_patterns_path(path)
    if not resolved_path.exists():
        return _default_issue_knowledge_base()

    payload = json.loads(resolved_path.read_text(encoding="utf-8"))
    patterns = [
        IssuePatternRecord(
            pattern_id=str(item.get("pattern_id", "")).strip(),
            issue_type=str(item.get("issue_type", "")).strip(),
            canonical_title=str(item.get("canonical_title", "")).strip(),
            categories=list(item.get("categories", [])),
            common_causes=list(item.get("common_causes", [])),
            common_impacts=list(item.get("common_impacts", [])),
            preferred_document_types=list(item.get("preferred_document_types", [])),
            high_impact=bool(item.get("high_impact", False)),
            priority_boost=int(item.get("priority_boost", 0) or 0),
            feedback_stats={str(key): int(value) for key, value in dict(item.get("feedback_stats", {})).items()},
            severity_overrides={str(key): int(value) for key, value in dict(item.get("severity_overrides", {})).items()},
            cause_counts={str(key): int(value) for key, value in dict(item.get("cause_counts", {})).items()},
            impact_counts={str(key): int(value) for key, value in dict(item.get("impact_counts", {})).items()},
            document_type_counts={str(key): int(value) for key, value in dict(item.get("document_type_counts", {})).items()},
            last_updated=str(item.get("last_updated", "")).strip(),
        )
        for item in payload.get("patterns", [])
        if str(item.get("pattern_id", "")).strip()
    ]
    if not patterns:
        patterns = list(_default_issue_knowledge_base().patterns)
    return IssueKnowledgeBase(
        schema_version=str(payload.get("schema_version", "1.0")).strip() or "1.0",
        updated_at=str(payload.get("updated_at", "")).strip(),
        patterns=patterns,
    )


def save_issue_knowledge_base(knowledge_base: IssueKnowledgeBase, path: Path | None = None) -> Path:
    resolved_path = default_issue_patterns_path(path)
    ensure_directory(resolved_path.parent)
    resolved_path.parent.mkdir(parents=True, exist_ok=True)
    ordered_patterns = sorted(
        knowledge_base.patterns,
        key=lambda pattern: (pattern.pattern_id, pattern.issue_type, pattern.canonical_title),
    )
    payload = {
        "schema_version": knowledge_base.schema_version,
        "updated_at": knowledge_base.updated_at,
        "patterns": [asdict(pattern) for pattern in ordered_patterns],
    }
    resolved_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return resolved_path


def load_deal_feedback_record(path: Path) -> DealFeedbackRecord | None:
    if not path.exists():
        return None

    payload = json.loads(path.read_text(encoding="utf-8"))
    issue_feedback = [
        IssueFeedbackEntry(
            issue_id=str(item.get("issue_id", "")).strip(),
            issue_type=str(item.get("issue_type", "")).strip(),
            canonical_title=str(item.get("canonical_title", "")).strip(),
            category=str(item.get("category", "")).strip(),
            model_severity=str(item.get("model_severity", "")).strip(),
            feedback_status=str(item.get("feedback_status", "")).strip().lower(),
            severity_override=str(item.get("severity_override", "")).strip().upper(),
            reviewer_notes=str(item.get("reviewer_notes", "")).strip(),
            likely_cause=str(item.get("likely_cause", "")).strip(),
            observed_impact=str(item.get("observed_impact", "")).strip(),
            source_documents=list(item.get("source_documents", [])),
            source_document_types=list(item.get("source_document_types", [])),
            confidence_score=int(item.get("confidence_score", 0) or 0),
            confidence_level=str(item.get("confidence_level", "low")).strip().lower() or "low",
        )
        for item in payload.get("issue_feedback", [])
        if str(item.get("issue_id", "")).strip()
    ]
    missed_issues = [
        MissedIssueFeedback(
            title=str(item.get("title", "")).strip(),
            category=str(item.get("category", "")).strip(),
            issue_type=str(item.get("issue_type", "")).strip(),
            expected_severity=str(item.get("expected_severity", "")).strip().upper(),
            likely_cause=str(item.get("likely_cause", "")).strip(),
            observed_impact=str(item.get("observed_impact", "")).strip(),
            source_documents=list(item.get("source_documents", [])),
            source_document_types=list(item.get("source_document_types", [])),
            reviewer_notes=str(item.get("reviewer_notes", "")).strip(),
        )
        for item in payload.get("missed_issues", [])
        if str(item.get("title", "")).strip()
    ]
    return DealFeedbackRecord(
        schema_version=str(payload.get("schema_version", "1.0")).strip() or "1.0",
        deal_id=str(payload.get("deal_id", "")).strip(),
        deal_name=str(payload.get("deal_name", "")).strip(),
        run_id=str(payload.get("run_id", "")).strip(),
        generated_at=str(payload.get("generated_at", "")).strip(),
        knowledge_base_path=str(payload.get("knowledge_base_path", "")).strip(),
        allowed_feedback_statuses=list(payload.get("allowed_feedback_statuses", ["correct", "incorrect", "irrelevant", "missed"])),
        issue_feedback=issue_feedback,
        missed_issues=missed_issues,
    )


def feedback_record_has_signal(record: DealFeedbackRecord | None) -> bool:
    if record is None:
        return False
    if any(
        entry.feedback_status in _ALLOWED_FEEDBACK or entry.severity_override
        for entry in record.issue_feedback
    ):
        return True
    return any(item.title.strip() for item in record.missed_issues)


def update_issue_knowledge_base_from_feedback(
    knowledge_base: IssueKnowledgeBase,
    feedback_record: DealFeedbackRecord,
) -> dict[str, int]:
    patterns_by_id = {pattern.pattern_id: pattern for pattern in knowledge_base.patterns}
    processed_entries = 0
    missed_entries = 0

    for entry in feedback_record.issue_feedback:
        if entry.feedback_status not in _ALLOWED_FEEDBACK and not entry.severity_override:
            continue
        pattern = _ensure_pattern(
            patterns_by_id,
            pattern_id=entry.issue_type or entry.issue_id,
            issue_type=entry.issue_type or entry.issue_id,
            canonical_title=entry.canonical_title,
            category=entry.category,
        )
        _update_pattern_from_feedback_entry(pattern, entry)
        processed_entries += 1

    for missed in feedback_record.missed_issues:
        if not missed.title.strip():
            continue
        pattern = _ensure_pattern(
            patterns_by_id,
            pattern_id=slugify(missed.issue_type or missed.title),
            issue_type=slugify(missed.issue_type or missed.title),
            canonical_title=missed.title,
            category=missed.category,
        )
        _update_pattern_from_missed_issue(pattern, missed)
        missed_entries += 1

    knowledge_base.patterns = sorted(patterns_by_id.values(), key=lambda pattern: (pattern.pattern_id, pattern.issue_type))
    knowledge_base.updated_at = _timestamp()
    return {
        "issue_feedback_entries": processed_entries,
        "missed_issue_entries": missed_entries,
        "patterns_tracked": len(knowledge_base.patterns),
    }


def ingest_feedback_record_into_knowledge_base(
    *,
    feedback_path: Path,
    knowledge_base_path: Path | None = None,
) -> dict[str, int]:
    feedback_record = load_deal_feedback_record(feedback_path)
    if not feedback_record_has_signal(feedback_record):
        return {
            "issue_feedback_entries": 0,
            "missed_issue_entries": 0,
            "patterns_tracked": len(load_issue_knowledge_base(knowledge_base_path).patterns),
        }

    knowledge_base = load_issue_knowledge_base(knowledge_base_path)
    stats = update_issue_knowledge_base_from_feedback(knowledge_base, feedback_record)
    save_issue_knowledge_base(knowledge_base, knowledge_base_path)
    return stats


def build_deal_feedback_record(
    *,
    synthesis: DealSynthesis,
    run_id: str,
    knowledge_base_path: Path,
    existing_feedback: DealFeedbackRecord | None = None,
) -> DealFeedbackRecord:
    existing_by_issue_id = {
        entry.issue_id: entry
        for entry in (existing_feedback.issue_feedback if existing_feedback is not None else [])
    }
    current_issue_feedback: list[IssueFeedbackEntry] = []
    for issue in synthesis.canonical_issue_registry.issues:
        matched_documents = _matching_document_analyses(issue, synthesis.document_analyses)
        previous = existing_by_issue_id.get(issue.issue_id)
        current_issue_feedback.append(
            IssueFeedbackEntry(
                issue_id=issue.issue_id,
                issue_type=issue.issue_type or issue.issue_id,
                canonical_title=issue.title,
                category=issue.category,
                model_severity=issue.acquisition_severity,
                feedback_status=previous.feedback_status if previous is not None else "",
                severity_override=previous.severity_override if previous is not None else "",
                reviewer_notes=previous.reviewer_notes if previous is not None else "",
                likely_cause=previous.likely_cause if previous is not None else clip_text(issue.likely_explanation, 220),
                observed_impact=previous.observed_impact if previous is not None else clip_text(issue.practical_impact or issue.likely_implication, 220),
                source_documents=_issue_source_documents(issue),
                source_document_types=_issue_document_types(issue, matched_documents),
                confidence_score=issue.confidence_score,
                confidence_level=issue.confidence_level,
            )
        )

    missed_issues = existing_feedback.missed_issues[:] if existing_feedback is not None else []
    return DealFeedbackRecord(
        schema_version="1.0",
        deal_id=slugify(synthesis.deal_name or "deal"),
        deal_name=synthesis.deal_name,
        run_id=run_id,
        generated_at=_timestamp(),
        knowledge_base_path=str(default_issue_patterns_path(knowledge_base_path)),
        allowed_feedback_statuses=["correct", "incorrect", "irrelevant", "missed"],
        issue_feedback=current_issue_feedback,
        missed_issues=missed_issues,
    )


def apply_feedback_learning_layer(
    *,
    registry: CanonicalIssueRegistry,
    document_analyses: list[DocumentAnalysis],
    knowledge_base: IssueKnowledgeBase,
) -> None:
    patterns = {pattern.pattern_id: pattern for pattern in knowledge_base.patterns}
    for issue in registry.issues:
        existing_feedback_adjustment = issue.priority_score.feedback_adjustment
        if existing_feedback_adjustment:
            issue.priority_score.total = max(0, issue.priority_score.total - existing_feedback_adjustment)
            issue.priority_score.feedback_adjustment = 0
        matched_documents = _matching_document_analyses(issue, document_analyses)
        confidence_score, confidence_level, confidence_factors = _issue_confidence(issue, matched_documents)
        issue.confidence_score = confidence_score
        issue.confidence_level = confidence_level
        issue.confidence_factors = confidence_factors

        pattern = _match_pattern(issue, patterns)
        if pattern is None:
            issue.knowledge_priority_boost = 0
            issue.knowledge_pattern_id = ""
            issue.knowledge_pattern_summary = ""
            issue.knowledge_feedback_counts = {}
            continue

        issue.knowledge_pattern_id = pattern.pattern_id
        issue.knowledge_feedback_counts = dict(pattern.feedback_stats)
        issue.knowledge_pattern_summary = _pattern_summary(pattern)
        boost = _pattern_priority_boost(pattern, issue)
        issue.knowledge_priority_boost = boost
        issue.priority_score.feedback_adjustment = boost
        issue.priority_score.total += boost
        dominant_severity = _dominant_severity_override(pattern)
        if dominant_severity and _SEVERITY_ORDER.get(dominant_severity, 4) < _SEVERITY_ORDER.get(issue.acquisition_severity, 4):
            issue.acquisition_severity = dominant_severity
            note = f"Reviewer feedback on similar issues most often reset severity to {dominant_severity}."
            issue.acquisition_severity_reason = unique_preserve_order([issue.acquisition_severity_reason, note])[-1]
        if _should_apply_pattern_cause(issue, pattern):
            issue.likely_explanation = (
                f"{issue.likely_explanation.rstrip('.')} Reviewer feedback on similar issues most often pointed to {pattern.common_causes[0]}."
                if issue.likely_explanation
                else f"Current documents do not fully isolate the driver. Reviewer feedback on similar issues most often pointed to {pattern.common_causes[0]}."
            )
        if _should_apply_pattern_impact(issue, pattern):
            issue.practical_impact = f"Reviewer feedback on similar issues most often affected {pattern.common_impacts[0]}."
        issue.calibration_notes = unique_preserve_order(
            [
                *issue.calibration_notes,
                f"feedback-confidence={issue.confidence_score} ({issue.confidence_level})",
                f"knowledge-pattern={pattern.pattern_id}",
                f"knowledge-boost={boost}",
                issue.knowledge_pattern_summary,
            ]
        )

    registry.issues.sort(
        key=lambda issue: (
            _SEVERITY_ORDER.get(issue.acquisition_severity, 4),
            0 if issue.gating_item else 1,
            0 if issue.blocking_flag else 1,
            -issue.priority_score.total,
            issue.title,
        )
    )
    registry.final_issue_order = [issue.issue_id for issue in registry.issues]


def _default_issue_knowledge_base() -> IssueKnowledgeBase:
    return IssueKnowledgeBase(
        schema_version="1.0",
        updated_at="",
        patterns=[IssuePatternRecord(**asdict(pattern)) for pattern in _SEED_PATTERNS],
    )


def _ensure_pattern(
    patterns_by_id: dict[str, IssuePatternRecord],
    *,
    pattern_id: str,
    issue_type: str,
    canonical_title: str,
    category: str,
) -> IssuePatternRecord:
    normalized_id = slugify(pattern_id or issue_type or canonical_title or category or "issue-pattern")
    pattern = patterns_by_id.get(normalized_id)
    if pattern is None:
        pattern = IssuePatternRecord(
            pattern_id=normalized_id,
            issue_type=slugify(issue_type or normalized_id),
            canonical_title=canonical_title,
            categories=[category] if category else [],
        )
        patterns_by_id[normalized_id] = pattern
    else:
        if category:
            pattern.categories = unique_preserve_order([*pattern.categories, category])
        if canonical_title and not pattern.canonical_title:
            pattern.canonical_title = canonical_title
    return pattern


def _update_pattern_from_feedback_entry(pattern: IssuePatternRecord, entry: IssueFeedbackEntry) -> None:
    if entry.category:
        pattern.categories = unique_preserve_order([*pattern.categories, entry.category])
    if entry.feedback_status in _ALLOWED_FEEDBACK:
        stats = defaultdict(int, pattern.feedback_stats)
        stats[entry.feedback_status] += 1
        pattern.feedback_stats = dict(stats)
    if entry.severity_override:
        overrides = defaultdict(int, pattern.severity_overrides)
        overrides[entry.severity_override] += 1
        pattern.severity_overrides = dict(overrides)
    _update_counter(pattern.cause_counts, entry.likely_cause)
    _update_counter(pattern.impact_counts, entry.observed_impact)
    for document_type in entry.source_document_types:
        _update_counter(pattern.document_type_counts, document_type)
    pattern.common_causes = _top_ranked_terms(pattern.cause_counts)
    pattern.common_impacts = _top_ranked_terms(pattern.impact_counts)
    pattern.preferred_document_types = _top_ranked_terms(pattern.document_type_counts)
    pattern.high_impact = pattern.high_impact or _entry_reads_high_impact(entry)
    pattern.priority_boost = _computed_pattern_priority_boost(pattern)
    pattern.last_updated = _timestamp()


def _update_pattern_from_missed_issue(pattern: IssuePatternRecord, missed: MissedIssueFeedback) -> None:
    if missed.category:
        pattern.categories = unique_preserve_order([*pattern.categories, missed.category])
    if missed.likely_cause:
        _update_counter(pattern.cause_counts, missed.likely_cause)
    if missed.observed_impact:
        _update_counter(pattern.impact_counts, missed.observed_impact)
    for document_type in missed.source_document_types:
        _update_counter(pattern.document_type_counts, document_type)
    pattern.common_causes = _top_ranked_terms(pattern.cause_counts)
    pattern.common_impacts = _top_ranked_terms(pattern.impact_counts)
    pattern.preferred_document_types = _top_ranked_terms(pattern.document_type_counts)
    stats = defaultdict(int, pattern.feedback_stats)
    stats["missed"] += 1
    pattern.feedback_stats = dict(stats)
    if missed.expected_severity:
        overrides = defaultdict(int, pattern.severity_overrides)
        overrides[missed.expected_severity] += 1
        pattern.severity_overrides = dict(overrides)
    pattern.high_impact = pattern.high_impact or missed.expected_severity in {"CRITICAL", "HIGH"}
    pattern.priority_boost = _computed_pattern_priority_boost(pattern)
    pattern.last_updated = _timestamp()


def _computed_pattern_priority_boost(pattern: IssuePatternRecord) -> int:
    positive = pattern.feedback_stats.get("correct", 0) + pattern.feedback_stats.get("missed", 0)
    negative = pattern.feedback_stats.get("incorrect", 0) + pattern.feedback_stats.get("irrelevant", 0)
    high_severity_votes = pattern.severity_overrides.get("CRITICAL", 0) + pattern.severity_overrides.get("HIGH", 0)
    boost = 2 if pattern.high_impact else 0
    boost += min(6, positive * 2)
    boost += min(3, high_severity_votes)
    boost -= min(6, negative * 2)
    return max(0, min(12, boost))


def _pattern_priority_boost(pattern: IssuePatternRecord, issue: CanonicalIssue) -> int:
    boost = pattern.priority_boost
    if issue.confidence_score >= 70 and pattern.high_impact:
        boost += 1
    if issue.confidence_score <= 35 and pattern.feedback_stats.get("incorrect", 0) + pattern.feedback_stats.get("irrelevant", 0) > 0:
        boost = max(0, boost - 2)
    return max(0, min(12, boost))


def _dominant_severity_override(pattern: IssuePatternRecord) -> str:
    if not pattern.severity_overrides:
        return ""
    return sorted(
        pattern.severity_overrides.items(),
        key=lambda item: (-item[1], _SEVERITY_ORDER.get(item[0], 4), item[0]),
    )[0][0]


def _pattern_summary(pattern: IssuePatternRecord) -> str:
    counts = pattern.feedback_stats
    cause = pattern.common_causes[0] if pattern.common_causes else "no dominant cause yet"
    impact = pattern.common_impacts[0] if pattern.common_impacts else "no dominant impact yet"
    return (
        f"feedback correct={counts.get('correct', 0)}, incorrect={counts.get('incorrect', 0)}, "
        f"irrelevant={counts.get('irrelevant', 0)}, missed={counts.get('missed', 0)}; "
        f"common cause={cause}; common impact={impact}."
    )


def _should_apply_pattern_cause(issue: CanonicalIssue, pattern: IssuePatternRecord) -> bool:
    if not pattern.common_causes:
        return False
    if issue.likely_explanation and len(issue.likely_explanation.split()) >= 10 and issue.site_specific_trigger:
        return False
    return True


def _should_apply_pattern_impact(issue: CanonicalIssue, pattern: IssuePatternRecord) -> bool:
    if not pattern.common_impacts:
        return False
    return not issue.practical_impact


def _issue_confidence(
    issue: CanonicalIssue,
    matched_documents: list[DocumentAnalysis],
) -> tuple[int, str, list[str]]:
    source_names = set(_issue_source_documents(issue))
    source_names.update(citation.document_name for citation in issue.citations)
    for analysis in matched_documents:
        source_names.add(analysis.document.title)
    source_count = len(source_names)
    source_score = min(40, source_count * 15)

    document_types = _issue_document_types(issue, matched_documents)
    expected_types = _EXPECTED_DOCUMENT_TYPES.get(issue.category, set())
    if document_types and expected_types.intersection(document_types):
        document_type_score = 28
    elif any(analysis.document_role == "primary" for analysis in matched_documents):
        document_type_score = 20
    elif document_types:
        document_type_score = 12
    else:
        document_type_score = 8 if source_count else 0

    quality_map = {"high": 25, "medium": 16, "low": 8}
    if matched_documents:
        quality_score = round(
            sum(quality_map.get(analysis.confidence, 10) for analysis in matched_documents) / len(matched_documents)
        )
        quality_label = matched_documents[0].confidence if len({analysis.confidence for analysis in matched_documents}) == 1 else "mixed"
    else:
        quality_score = {"high": 18, "medium": 12, "low": 6}.get(issue.confidence, 10)
        quality_label = issue.confidence

    total = max(0, min(100, source_score + document_type_score + quality_score))
    level = "high" if total >= 70 else "medium" if total >= 45 else "low"
    factors = [
        f"sources={source_count}",
        f"document_types={', '.join(document_types) or 'unknown'}",
        f"extraction_quality={quality_label}",
    ]
    return total, level, factors


def _matching_document_analyses(issue: CanonicalIssue, document_analyses: list[DocumentAnalysis]) -> list[DocumentAnalysis]:
    source_names = {name.lower() for name in _issue_source_documents(issue)}
    source_names.update(citation.document_name.lower() for citation in issue.citations)
    matched = []
    for analysis in document_analyses:
        aliases = {
            analysis.document.title.lower(),
            analysis.document.relative_path.as_posix().lower(),
            analysis.document.relative_path.name.lower(),
            analysis.document.relative_path.stem.lower(),
        }
        if source_names.intersection(aliases) or issue.category in analysis.focus_areas:
            matched.append(analysis)
    return matched


def _issue_source_documents(issue: CanonicalIssue) -> list[str]:
    labels = issue.source_documents[:]
    labels.extend(citation.document_name for citation in issue.citations)
    return unique_preserve_order(label for label in labels if label)[:4]


def _issue_document_types(issue: CanonicalIssue, matched_documents: list[DocumentAnalysis]) -> list[str]:
    document_types = [
        _document_type_from_text(f"{analysis.document.title} {analysis.document.relative_path.as_posix()}")
        for analysis in matched_documents
    ]
    if not document_types:
        document_types = [_document_type_from_text(name) for name in _issue_source_documents(issue)]
    return unique_preserve_order(document_type for document_type in document_types if document_type)


def _document_type_from_text(text: str) -> str:
    lowered = normalize_text(text).lower()
    if _contains_any(lowered, ("title", "commitment", "prelim", "vesting", "deed", "easement", "legal")):
        return "title"
    if _contains_any(lowered, ("survey", "alta", "boundary")):
        return "survey"
    if _contains_any(lowered, ("entitlement", "resolution", "conditions", "approval", "zoning", "permit", "development agreement")):
        return "entitlement"
    if _contains_any(lowered, ("environmental", "phase i", "phase ii", "wetland", "biological", "habitat")):
        return "environmental"
    if _contains_any(lowered, ("geotech", "geotechnical", "soils")):
        return "geotechnical"
    if _contains_any(lowered, ("drainage", "stormwater", "flood", "hydrology")):
        return "drainage"
    if _contains_any(lowered, ("utility", "will serve", "water", "sewer")):
        return "utilities"
    if _contains_any(lowered, ("offsite", "frontage", "signal", "dedication")):
        return "offsite"
    if _contains_any(lowered, ("budget", "estimate", "bid", "fee", "pricing", "cost")):
        return "cost"
    if _contains_any(lowered, ("plan", "site", "grading", "improvement", "tract", "map", "plat")):
        return "plan"
    return ""


def _match_pattern(
    issue: CanonicalIssue,
    patterns: dict[str, IssuePatternRecord],
) -> IssuePatternRecord | None:
    candidate_keys = [
        slugify(issue.issue_type or ""),
        slugify(issue.issue_id or ""),
        slugify(issue.title or ""),
    ]
    for key in candidate_keys:
        if not key:
            continue
        if key in patterns:
            return patterns[key]
    return None


def _entry_reads_high_impact(entry: IssueFeedbackEntry) -> bool:
    severity = (entry.severity_override or entry.model_severity).upper()
    if severity in {"CRITICAL", "HIGH"}:
        return True
    impact_text = f"{entry.observed_impact} {entry.canonical_title} {entry.category}".lower()
    return _contains_any(impact_text, ("price", "timeline", "legal", "title", "clos", "cost", "yield", "entitlement"))


def _top_ranked_terms(counter: dict[str, int], *, limit: int = 3) -> list[str]:
    return [
        item
        for item, _ in sorted(counter.items(), key=lambda pair: (-pair[1], pair[0]))[:limit]
    ]


def _update_counter(counter: dict[str, int], value: str) -> None:
    normalized = normalize_text(value).strip().rstrip(".")
    if not normalized:
        return
    counter[normalized] = counter.get(normalized, 0) + 1


def _contains_any(text: str, terms: tuple[str, ...]) -> bool:
    return any(re.search(r"\b" + re.escape(term) + r"\b", text) for term in terms)


def _timestamp() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")
