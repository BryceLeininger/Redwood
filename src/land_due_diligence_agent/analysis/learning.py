"""Local feature-based continuous learning for issue calibration."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from land_due_diligence_agent.models import CanonicalIssue, DealMetadata, LearningSummary, PrecedentIssueRecord
from land_due_diligence_agent.utils.files import ensure_directory

_FEATURE_WEIGHTS = {
    "global": 0.10,
    "issue_id": 0.40,
    "category": 0.20,
    "evidence_basis": 0.10,
    "issue_strength": 0.07,
    "decision_action": 0.05,
    "stage": 0.04,
    "region": 0.02,
    "product": 0.02,
}
_MIN_SAMPLES = 3


@dataclass(slots=True)
class _FeatureStats:
    count: int = 0
    real_issue_count: int = 0
    real_issue_observations: int = 0
    false_positive_count: int = 0
    material_issue_count: int = 0
    decision_relevant_count: int = 0
    decision_relevant_observations: int = 0
    impact_count: int = 0
    impact_observations: int = 0

    def add(self, record: PrecedentIssueRecord) -> None:
        self.count += 1
        if record.real_issue is not None or record.false_positive_flag or record.actual_outcome in {"cost", "delay", "redesign"}:
            self.real_issue_observations += 1
        if record.real_issue is True or record.actual_outcome in {"cost", "delay", "redesign"}:
            self.real_issue_count += 1
        if record.false_positive_flag:
            self.false_positive_count += 1
        if record.materiality in {"medium", "high"}:
            self.material_issue_count += 1
        if record.decision_relevant is not None:
            self.decision_relevant_observations += 1
        if record.decision_relevant is True:
            self.decision_relevant_count += 1
        if record.actual_outcome in {"cost", "delay", "redesign"}:
            self.impact_count += 1
            self.impact_observations += 1

    def rate(self, numerator: int, denominator: int | None = None) -> float:
        resolved_denominator = self.count if denominator is None else denominator
        return (numerator + 1.0) / (resolved_denominator + 2.0)


class ContinuousLearningEngine:
    """Empirical-Bayes issue calibrator built from reviewer-labeled history."""

    def __init__(
        self,
        *,
        records: list[PrecedentIssueRecord],
        deal_metadata: DealMetadata,
        snapshot_path: Path | None = None,
    ) -> None:
        self.records = records
        self.deal_metadata = deal_metadata
        self.snapshot_path = snapshot_path
        self.feature_stats = _build_feature_stats(records)
        if snapshot_path is not None:
            save_learning_snapshot(
                feature_stats=self.feature_stats,
                path=snapshot_path,
            )

    def retrieve(self, issue: CanonicalIssue) -> LearningSummary:
        if not self.records:
            return LearningSummary(
                reasoning="No reviewer-labeled history is available yet, so learned calibration stays neutral.",
            )

        feature_keys = _issue_feature_keys(issue, self.deal_metadata)
        matched_features: list[str] = []
        weighted_sample = 0.0
        real_rate = 0.0
        false_rate = 0.0
        material_rate = 0.0
        decision_rate = 0.0
        impact_rate = 0.0

        for feature_name, key in feature_keys:
            stats = self.feature_stats.get((feature_name, key))
            if stats is None or stats.count == 0:
                continue
            weight = _FEATURE_WEIGHTS.get(feature_name, 0.0)
            matched_features.append(f"{feature_name}={key} (n={stats.count})")
            weighted_sample += stats.count * weight
            real_rate += stats.rate(stats.real_issue_count, stats.real_issue_observations or stats.count) * weight
            false_rate += stats.rate(stats.false_positive_count) * weight
            material_rate += stats.rate(stats.material_issue_count) * weight
            decision_rate += stats.rate(
                stats.decision_relevant_count,
                stats.decision_relevant_observations or stats.count,
            ) * weight
            impact_rate += stats.rate(stats.impact_count, stats.impact_observations or stats.count) * weight

        if not matched_features:
            return LearningSummary(
                reasoning="Historical records exist, but none matched this issue closely enough for a learned adjustment.",
            )

        score_adjustment = 0
        confidence_adjustment = "neutral"
        sample_size = max(1, round(weighted_sample))
        if sample_size >= _MIN_SAMPLES:
            score_adjustment = round(
                ((real_rate - 0.50) * 12)
                - ((false_rate - 0.30) * 12)
                + ((material_rate - 0.50) * 8)
                + ((decision_rate - 0.50) * 6)
                + ((impact_rate - 0.40) * 8)
            )
            score_adjustment = max(-10, min(10, score_adjustment))
            if score_adjustment >= 3:
                confidence_adjustment = "up"
            elif score_adjustment <= -3:
                confidence_adjustment = "down"

        reasoning = (
            f"Matched learned history on {', '.join(matched_features[:4])}. "
            f"Predicted real-issue rate={real_rate:.0%}, false-positive rate={false_rate:.0%}, "
            f"material rate={material_rate:.0%}, impact rate={impact_rate:.0%}."
        )
        return LearningSummary(
            sample_size=sample_size,
            real_issue_rate=real_rate,
            false_positive_rate=false_rate,
            material_issue_rate=material_rate,
            decision_relevant_rate=decision_rate,
            impact_rate=impact_rate,
            matched_features=matched_features[:6],
            confidence_adjustment=confidence_adjustment,
            score_adjustment=score_adjustment,
            reasoning=reasoning,
        )


def build_learning_engine(
    *,
    records: list[PrecedentIssueRecord],
    deal_metadata: DealMetadata,
    snapshot_path: Path | None = None,
) -> ContinuousLearningEngine:
    return ContinuousLearningEngine(
        records=records,
        deal_metadata=deal_metadata,
        snapshot_path=snapshot_path,
    )


def default_learning_snapshot_path(store_path: Path | None) -> Path:
    if store_path is not None:
        return store_path.with_name("learned_issue_model.json")
    return Path(__file__).resolve().parents[3] / "data" / "precedents" / "learned_issue_model.json"


def save_learning_snapshot(
    *,
    feature_stats: dict[tuple[str, str], _FeatureStats],
    path: Path,
) -> Path:
    ensure_directory(path.parent)
    payload = {
        "feature_stats": {
            f"{feature_name}:{key}": {
                "count": stats.count,
                "real_issue_rate": stats.rate(stats.real_issue_count, stats.real_issue_observations or stats.count),
                "false_positive_rate": stats.rate(stats.false_positive_count),
                "material_issue_rate": stats.rate(stats.material_issue_count),
                "decision_relevant_rate": stats.rate(
                    stats.decision_relevant_count,
                    stats.decision_relevant_observations or stats.count,
                ),
                "impact_rate": stats.rate(stats.impact_count, stats.impact_observations or stats.count),
            }
            for (feature_name, key), stats in sorted(feature_stats.items())
            if stats.count
        }
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _build_feature_stats(records: list[PrecedentIssueRecord]) -> dict[tuple[str, str], _FeatureStats]:
    stats: dict[tuple[str, str], _FeatureStats] = {}
    for record in records:
        for feature_name, key in _record_feature_keys(record):
            feature_key = (feature_name, key)
            if feature_key not in stats:
                stats[feature_key] = _FeatureStats()
            stats[feature_key].add(record)
    return stats


def _record_feature_keys(record: PrecedentIssueRecord) -> list[tuple[str, str]]:
    return [
        ("global", "all"),
        ("issue_id", record.issue_id or record.issue_type),
        ("category", record.category),
        ("evidence_basis", record.evidence_basis or "unknown"),
        ("issue_strength", record.issue_strength or "unknown"),
        ("decision_action", _decision_action_hint(record)),
        ("stage", record.deal_metadata.stage or "unknown"),
        ("region", record.deal_metadata.region or "unknown"),
        ("product", record.deal_metadata.product or "unknown"),
    ]


def _issue_feature_keys(issue: CanonicalIssue, deal_metadata: DealMetadata) -> list[tuple[str, str]]:
    return [
        ("global", "all"),
        ("issue_id", issue.issue_id),
        ("category", issue.category),
        ("evidence_basis", issue.evidence_basis or "unknown"),
        ("issue_strength", issue.issue_strength or "unknown"),
        ("decision_action", _decision_action_hint_for_issue(issue)),
        ("stage", deal_metadata.stage or "unknown"),
        ("region", deal_metadata.region or "unknown"),
        ("product", deal_metadata.product or "unknown"),
    ]


def _decision_action_hint(record: PrecedentIssueRecord) -> str:
    if record.false_positive_flag:
        return "downgrade"
    if record.decision_relevant is True:
        return "elevate"
    return "unknown"


def _decision_action_hint_for_issue(issue: CanonicalIssue) -> str:
    if issue.false_positive_risk == "high" or issue.process_friction_flag:
        return "downgrade"
    if issue.decision_action in {"treat as fatal", "condition closing", "restructure", "reprice", "assign to seller", "verify"}:
        return "elevate"
    if issue.blocking_flag or issue.critical_path_flag or issue.decision_relevant:
        return "elevate"
    return "unknown"
