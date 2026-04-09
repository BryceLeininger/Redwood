"""Tests for deterministic feedback and issue-pattern learning."""

from __future__ import annotations

import logging
import tempfile
import unittest
from pathlib import Path

from land_due_diligence_agent.analysis.feedback_loop import (
    apply_feedback_learning_layer,
    build_deal_feedback_record,
    load_issue_knowledge_base,
    save_issue_knowledge_base,
    update_issue_knowledge_base_from_feedback,
)
from land_due_diligence_agent.analysis.service import run_analysis
from land_due_diligence_agent.llm.heuristic_provider import HeuristicProvider
from land_due_diligence_agent.models import DocumentRecord, MissedIssueFeedback
from land_due_diligence_agent.utils.text import normalize_text


def _document(relative_path: str, text: str) -> DocumentRecord:
    path = Path(relative_path)
    return DocumentRecord(
        source_path=path,
        relative_path=path,
        extension=path.suffix,
        title=path.stem.replace("_", " ").title(),
        raw_text=text,
        normalized_text=normalize_text(text),
    )


class FeedbackLoopTests(unittest.TestCase):
    def test_builds_structured_feedback_record_for_a_deal(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            knowledge_base_path = Path(temp_dir) / "issue_patterns.json"
            synthesis = run_analysis(
                deal_name="Utility Deal",
                documents=[
                    _document(
                        "utility_letter.txt",
                        (
                            "Utility capacity remains pending and a will serve letter has not been issued. "
                            "Water and sewer provider confirmation remain open."
                        ),
                    ),
                    _document(
                        "utility_email.txt",
                        (
                            "Dry utility coordination remains open and provider confirmation is still pending."
                        ),
                    ),
                ],
                llm_provider=HeuristicProvider(),
                logger=logging.getLogger("test-feedback-record"),
                issue_patterns_path=knowledge_base_path,
            )

            feedback_record = build_deal_feedback_record(
                synthesis=synthesis,
                run_id="20260409_120000",
                knowledge_base_path=knowledge_base_path,
            )

            self.assertEqual(feedback_record.schema_version, "1.0")
            self.assertIn("correct", feedback_record.allowed_feedback_statuses)
            self.assertIn("incorrect", feedback_record.allowed_feedback_statuses)
            self.assertIn("irrelevant", feedback_record.allowed_feedback_statuses)
            self.assertIn("missed", feedback_record.allowed_feedback_statuses)
            self.assertTrue(feedback_record.issue_feedback)
            self.assertEqual(feedback_record.missed_issues, [])
            utility_entry = next(
                entry for entry in feedback_record.issue_feedback if entry.issue_id == "utility-capacity"
            )
            self.assertEqual(utility_entry.feedback_status, "")
            self.assertEqual(utility_entry.severity_override, "")
            self.assertEqual(utility_entry.issue_type, "utility-capacity")
            self.assertGreater(utility_entry.confidence_score, 0)
            self.assertTrue(utility_entry.source_document_types)

    def test_feedback_updates_knowledge_base_and_changes_next_run(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            knowledge_base_path = Path(temp_dir) / "issue_patterns.json"
            documents = [
                _document(
                    "utility_letter.txt",
                    (
                        "Utility capacity remains pending and a will serve letter has not been issued. "
                        "Water and sewer provider confirmation remain open."
                    ),
                ),
                _document(
                    "utility_schedule.txt",
                    (
                        "The current schedule still depends on utility provider confirmation and dry utility coordination."
                    ),
                ),
            ]

            first_synthesis = run_analysis(
                deal_name="Utility Deal",
                documents=documents,
                llm_provider=HeuristicProvider(),
                logger=logging.getLogger("test-feedback-first-run"),
                issue_patterns_path=knowledge_base_path,
            )
            first_issue = next(
                issue for issue in first_synthesis.canonical_issue_registry.issues if issue.issue_id == "utility-capacity"
            )
            feedback_record = build_deal_feedback_record(
                synthesis=first_synthesis,
                run_id="20260409_120000",
                knowledge_base_path=knowledge_base_path,
            )
            utility_entry = next(
                entry for entry in feedback_record.issue_feedback if entry.issue_id == "utility-capacity"
            )
            utility_entry.feedback_status = "correct"
            utility_entry.severity_override = "HIGH"
            utility_entry.likely_cause = "provider confirmation remained open"
            utility_entry.observed_impact = "timeline and offsite utility cost"
            feedback_record.missed_issues.append(
                MissedIssueFeedback(
                    title="Utility phasing conflict",
                    category="Utilities / Infrastructure Issues",
                    issue_type="utility-capacity",
                    expected_severity="HIGH",
                    likely_cause="utility phasing assumptions were not confirmed",
                    observed_impact="timeline and cost",
                    source_documents=["Utility Schedule"],
                    source_document_types=["utilities"],
                    reviewer_notes="Should have been elevated as part of the same utility path issue.",
                )
            )

            knowledge_base = load_issue_knowledge_base(knowledge_base_path)
            stats = update_issue_knowledge_base_from_feedback(knowledge_base, feedback_record)
            save_issue_knowledge_base(knowledge_base, knowledge_base_path)

            self.assertEqual(stats["issue_feedback_entries"], 1)
            self.assertEqual(stats["missed_issue_entries"], 1)

            second_synthesis = run_analysis(
                deal_name="Utility Deal",
                documents=documents,
                llm_provider=HeuristicProvider(),
                logger=logging.getLogger("test-feedback-second-run"),
                issue_patterns_path=knowledge_base_path,
            )
            second_issue = next(
                issue for issue in second_synthesis.canonical_issue_registry.issues if issue.issue_id == "utility-capacity"
            )
            stored_pattern = next(
                pattern for pattern in load_issue_knowledge_base(knowledge_base_path).patterns if pattern.pattern_id == "utility-capacity"
            )

            self.assertEqual(second_issue.knowledge_pattern_id, "utility-capacity")
            self.assertGreater(second_issue.knowledge_priority_boost, first_issue.knowledge_priority_boost)
            self.assertGreater(second_issue.priority_score.feedback_adjustment, 0)
            self.assertIn("feedback correct=1", second_issue.knowledge_pattern_summary)
            self.assertEqual(stored_pattern.feedback_stats.get("correct"), 1)
            self.assertEqual(stored_pattern.feedback_stats.get("missed"), 1)
            self.assertIn("provider confirmation remained open", stored_pattern.common_causes)
            self.assertIn("timeline and offsite utility cost", stored_pattern.common_impacts)

    def test_feedback_application_is_idempotent_for_the_same_registry(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            knowledge_base_path = Path(temp_dir) / "issue_patterns.json"
            synthesis = run_analysis(
                deal_name="Utility Deal",
                documents=[
                    _document(
                        "utility_letter.txt",
                        (
                            "Utility capacity remains pending and a will serve letter has not been issued. "
                            "Water and sewer provider confirmation remain open."
                        ),
                    ),
                    _document(
                        "utility_schedule.txt",
                        (
                            "The current schedule still depends on utility provider confirmation and dry utility coordination."
                        ),
                    ),
                ],
                llm_provider=HeuristicProvider(),
                logger=logging.getLogger("test-feedback-idempotent"),
                issue_patterns_path=knowledge_base_path,
            )
            registry = synthesis.canonical_issue_registry
            utility_issue = next(issue for issue in registry.issues if issue.issue_id == "utility-capacity")
            first_total = utility_issue.priority_score.total
            first_adjustment = utility_issue.priority_score.feedback_adjustment
            first_boost = utility_issue.knowledge_priority_boost

            apply_feedback_learning_layer(
                registry=registry,
                document_analyses=synthesis.document_analyses,
                knowledge_base=load_issue_knowledge_base(knowledge_base_path),
            )

            utility_issue = next(issue for issue in registry.issues if issue.issue_id == "utility-capacity")
            self.assertEqual(utility_issue.priority_score.total, first_total)
            self.assertEqual(utility_issue.priority_score.feedback_adjustment, first_adjustment)
            self.assertEqual(utility_issue.knowledge_priority_boost, first_boost)


if __name__ == "__main__":
    unittest.main()
