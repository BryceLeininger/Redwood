"""Autonomous sub-agent that writes bounded pseudo-labels for future runs."""

from __future__ import annotations

import logging
from pathlib import Path

from land_due_diligence_agent.analysis.precedents import load_precedent_records, upsert_precedent_records
from land_due_diligence_agent.models import (
    AutonomousLearningSummary,
    CanonicalIssueRegistry,
    PrecedentIssueRecord,
)
from land_due_diligence_agent.utils.files import slugify
from land_due_diligence_agent.utils.text import clip_text, normalize_text


class AutonomousLearningAgent:
    """Generate conservative pseudo-labels from strong internal consensus only."""

    def build_records(
        self,
        *,
        deal_name: str,
        registry: CanonicalIssueRegistry,
    ) -> tuple[list[PrecedentIssueRecord], AutonomousLearningSummary]:
        records: list[PrecedentIssueRecord] = []
        positive_records = 0
        negative_records = 0
        skipped_issues = 0
        events: list[str] = []

        for issue in registry.issues:
            record = _autonomous_record_for_issue(issue, deal_name=deal_name, registry=registry)
            if record is None:
                skipped_issues += 1
                events.append(f"{issue.issue_id}: skip (low) - signals were mixed.")
                continue
            records.append(record)
            events.append(
                f"{issue.issue_id}: {'negative' if record.false_positive_flag else 'positive'} "
                f"({record.label_confidence}) - {record.notes}"
            )
            if record.false_positive_flag:
                negative_records += 1
            else:
                positive_records += 1

        summary = AutonomousLearningSummary(
            enabled=True,
            records_generated=len(records),
            positive_records=positive_records,
            negative_records=negative_records,
            skipped_issues=skipped_issues,
            events=events[:20],
            reasoning=(
                "Autonomous learning only stored issues with strong internal consensus. "
                "Direct, specific, blocking signals became low-weight positive labels; "
                "routine, omission-only, non-blocking friction became low-weight negative labels."
            ),
        )
        return records, summary


def default_autonomous_store_path(reviewer_store_path: Path | None = None) -> Path:
    if reviewer_store_path is not None:
        return reviewer_store_path.with_name("autonomous_issue_memory.jsonl")
    return Path(__file__).resolve().parents[3] / "data" / "precedents" / "autonomous_issue_memory.jsonl"


def load_autonomous_learning_records(path: Path | None = None) -> list[PrecedentIssueRecord]:
    return load_precedent_records(path or default_autonomous_store_path())


def upsert_autonomous_learning_records(
    records: list[PrecedentIssueRecord],
    *,
    path: Path | None = None,
) -> Path | None:
    if not records:
        return None
    return upsert_precedent_records(records, path=path or default_autonomous_store_path())


def persist_autonomous_learning_records(
    *,
    deal_name: str,
    registry: CanonicalIssueRegistry,
    store_path: Path,
    logger: logging.Logger | None = None,
) -> tuple[list[PrecedentIssueRecord], AutonomousLearningSummary]:
    agent = AutonomousLearningAgent()
    records, summary = agent.build_records(
        deal_name=deal_name,
        registry=registry,
    )
    summary.store_path = str(store_path)
    if not records:
        summary.reasoning = "No issue met the autonomous self-label threshold, so nothing was written."
        return records, summary
    upsert_autonomous_learning_records(records, path=store_path)
    if logger is not None:
        logger.info("Autonomous learning wrote %d record(s) to %s.", len(records), store_path)
    return records, summary


def _autonomous_record_for_issue(
    issue,
    *,
    deal_name: str,
    registry: CanonicalIssueRegistry,
) -> PrecedentIssueRecord | None:
    positive = _is_positive_autonomous_signal(issue)
    negative = _is_negative_autonomous_signal(issue)
    if positive == negative:
        return None

    reason = _reason_for_autonomous_label(issue, positive=positive)
    return PrecedentIssueRecord(
        precedent_id="",
        deal_name=deal_name,
        issue_type=issue.issue_type or issue.issue_id,
        canonical_title=issue.title,
        category=issue.category,
        issue_id=issue.issue_id,
        deal_id=slugify(deal_name or "deal"),
        description=clip_text(
            normalize_text(
                " ".join(
                    part
                    for part in [
                        issue.site_specific_trigger,
                        issue.why_it_matters,
                        issue.likely_implication,
                    ]
                    if part
                )
            ),
            220,
        ),
        deal_metadata=registry.deal_metadata,
        evidence_basis=issue.evidence_basis,
        issue_strength=issue.issue_strength,
        real_issue=True if positive else False,
        materiality=issue.materiality if positive else "low",
        decision_relevant=issue.decision_relevant if positive else False,
        actual_outcome="unknown",
        false_positive_flag=not positive,
        resolved_by="unknown",
        notes=reason,
        resolution_notes=reason,
        label_source="autonomous",
        label_confidence="medium" if positive else "low",
    )


def _is_positive_autonomous_signal(issue) -> bool:
    if issue.front_end_flag not in {"red flag", "yellow flag", "conflict / contradiction concern"}:
        return False
    if issue.evidence_basis not in {"direct_unresolved_risk", "direct_confirmed_risk", "contradictory_evidence_present"}:
        return False
    if issue.false_positive_risk != "low":
        return False
    if issue.process_friction_flag:
        return False
    if issue.issue_strength not in {"strong", "moderate"}:
        return False
    if not (issue.blocking_flag or issue.critical_path_flag or issue.specificity_level == "clearly site-specific"):
        return False
    if issue.priority_score.total < 80:
        return False
    return True


def _is_negative_autonomous_signal(issue) -> bool:
    if issue.blocking_flag or issue.critical_path_flag:
        return False
    if issue.front_end_flag not in {"routine item", "document gap"}:
        return False
    if issue.evidence_basis not in {"omission_only", "routine_missing_support", "weak_inference"}:
        return False
    if issue.false_positive_risk not in {"medium", "high"} and not issue.process_friction_flag:
        return False
    if issue.normality_classification not in {"routine", "mildly elevated"}:
        return False
    return True


def _reason_for_autonomous_label(issue, *, positive: bool) -> str:
    if positive:
        return (
            f"Autonomous positive label because {issue.title.lower()} is direct, specific, "
            f"{'blocking' if issue.blocking_flag else 'critical-path'}, and low false-positive risk."
        )
    return (
        f"Autonomous negative label because {issue.title.lower()} reads like omission-only or routine process friction "
        "without blocking reach."
    )
