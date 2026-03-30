"""Tests for local precedent retrieval and outcome-aware calibration."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from land_due_diligence_agent.analysis.issue_registry import build_canonical_issue_registry
from land_due_diligence_agent.analysis.learning import build_learning_engine
from land_due_diligence_agent.analysis.precedents import (
    PrecedentEngine,
    ingest_reviewer_feedback_files,
    load_precedent_records,
)
from land_due_diligence_agent.models import (
    CanonicalIssue,
    Citation,
    DealMetadata,
    OmissionAssessment,
    PrecedentIssueRecord,
    RiskFinding,
)


class PrecedentTests(unittest.TestCase):
    def test_precedent_engine_prefers_same_issue_type(self) -> None:
        engine = PrecedentEngine(
            records=[
                PrecedentIssueRecord(
                    precedent_id="p1",
                    deal_name="Deal One",
                    issue_type="title-access-clearance",
                    canonical_title="Title and access clearance is not closed",
                    category="Title / Access Concerns",
                    description="Title exceptions conflicted with the access layout.",
                    deal_metadata=DealMetadata(stage="acquisition-dd", region="west", product="multifamily"),
                    real_issue=True,
                    materiality="high",
                    actual_outcome="delay",
                    resolution_notes="Resolved through endorsements and redesign.",
                ),
                PrecedentIssueRecord(
                    precedent_id="p2",
                    deal_name="Deal Two",
                    issue_type="stormwater-drainage",
                    canonical_title="Stormwater and drainage scope is not fully closed",
                    category="Flood / Drainage Issues",
                    description="Drainage package initially looked incomplete.",
                    deal_metadata=DealMetadata(stage="acquisition-dd", region="west", product="single-family"),
                    real_issue=False,
                    materiality="low",
                    actual_outcome="none",
                    false_positive_flag=True,
                    resolution_notes="Resolved as a support gap.",
                ),
            ],
            deal_metadata=DealMetadata(stage="acquisition-dd", region="west", product="multifamily"),
        )

        calibration = engine.retrieve(
            CanonicalIssue(
                issue_id="title-access-clearance",
                title="Title and access clearance is not closed",
                category="Title / Access Concerns",
                status="open",
                issue_type="title-access-clearance",
                why_it_matters="This directly affects closability.",
                likely_implication="Closing should not be treated as clean until the exception is cured.",
            )
        )

        self.assertTrue(calibration.matches)
        self.assertEqual(calibration.matches[0].precedent_id, "p1")
        self.assertGreater(calibration.matches[0].similarity_score, 0.5)
        self.assertEqual(calibration.summary.real_rate, 1.0)
        self.assertEqual(calibration.summary.outcome_stats, {"delay": 1})

    def test_omission_only_issue_is_downgraded_by_false_positive_precedent(self) -> None:
        engine = PrecedentEngine(
            records=[
                PrecedentIssueRecord(
                    precedent_id="s1",
                    deal_name="Drainage Deal One",
                    issue_type="stormwater-drainage",
                    canonical_title="Stormwater and drainage scope is not fully closed",
                    category="Flood / Drainage Issues",
                    description="Missing drainage support later proved to be routine file assembly noise.",
                    deal_metadata=DealMetadata(stage="acquisition-dd", region="west", product="single-family"),
                    real_issue=False,
                    materiality="low",
                    actual_outcome="none",
                    false_positive_flag=True,
                    resolution_notes="Resolved once the current calculations were added to the file.",
                ),
                PrecedentIssueRecord(
                    precedent_id="s2",
                    deal_name="Drainage Deal Two",
                    issue_type="stormwater-drainage",
                    canonical_title="Stormwater and drainage scope is not fully closed",
                    category="Flood / Drainage Issues",
                    description="Initial concern was not commercially meaningful after the civil set was matched.",
                    deal_metadata=DealMetadata(stage="acquisition-dd", region="west", product="single-family"),
                    real_issue=False,
                    materiality="low",
                    actual_outcome="none",
                    false_positive_flag=True,
                    resolution_notes="Closed as routine support clean-up.",
                ),
            ],
            deal_metadata=DealMetadata(stage="acquisition-dd", region="west", product="single-family"),
        )

        registry = build_canonical_issue_registry(
            key_risks=[],
            contradictions=[],
            omission_assessments=[
                OmissionAssessment(
                    item="Floodplain or drainage study",
                    category="Flood / Drainage Issues",
                    status="unclear whether present",
                    rationale="No drainage package is clearly indexed in the current file set.",
                )
            ],
            document_analyses=[],
            precedent_retriever=engine.retrieve,
            deal_metadata=engine.deal_metadata,
        )

        issue = next(issue for issue in registry.issues if issue.issue_id == "stormwater-drainage")
        self.assertEqual(issue.precedent_summary.confidence_adjustment, "down")
        self.assertLess(issue.priority_score.precedent_adjustment, 0)
        self.assertFalse(issue.top_line_eligible)

    def test_direct_issue_is_upgraded_by_high_impact_precedent(self) -> None:
        engine = PrecedentEngine(
            records=[
                PrecedentIssueRecord(
                    precedent_id="t1",
                    deal_name="Title Deal One",
                    issue_type="title-access-clearance",
                    canonical_title="Title and access clearance is not closed",
                    category="Title / Access Concerns",
                    description="Access exceptions delayed closing.",
                    deal_metadata=DealMetadata(stage="acquisition-dd", region="west", product="multifamily"),
                    real_issue=True,
                    materiality="high",
                    actual_outcome="delay",
                    resolution_notes="Resolved through endorsements and updated access exhibits.",
                ),
                PrecedentIssueRecord(
                    precedent_id="t2",
                    deal_name="Title Deal Two",
                    issue_type="title-access-clearance",
                    canonical_title="Title and access clearance is not closed",
                    category="Title / Access Concerns",
                    description="Title restrictions forced a redesign of the entry condition.",
                    deal_metadata=DealMetadata(stage="acquisition-dd", region="west", product="multifamily"),
                    real_issue=True,
                    materiality="high",
                    actual_outcome="redesign",
                    resolution_notes="Closed after redesign and endorsement.",
                ),
            ],
            deal_metadata=DealMetadata(stage="acquisition-dd", region="west", product="multifamily"),
        )

        registry = build_canonical_issue_registry(
            key_risks=[
                RiskFinding(
                    category="Title / Access Concerns",
                    severity="high",
                    summary="Preliminary title report lists an access easement exception affecting the site layout.",
                    issue="Title and access clearance is not closed.",
                    why_it_matters="This goes directly to closability and lenderability.",
                    likely_implication="Closing should not be treated as clean until the exception is cured or endorsed.",
                    source_documents=["Title Report"],
                    citations=[Citation(document_name="Title Report", chunk_id="page-0001", page_number=1)],
                    gating_flags=["Closing", "Underwriting confidence"],
                )
            ],
            contradictions=[],
            omission_assessments=[],
            document_analyses=[],
            precedent_retriever=engine.retrieve,
            deal_metadata=engine.deal_metadata,
        )

        issue = registry.issues[0]
        self.assertEqual(issue.precedent_summary.confidence_adjustment, "up")
        self.assertGreater(issue.priority_score.precedent_adjustment, 0)
        self.assertTrue(issue.top_line_eligible)
        self.assertEqual(issue.precedent_summary.outcome_stats, {"delay": 1, "redesign": 1})

    def test_precedent_engine_falls_back_cleanly_without_records(self) -> None:
        engine = PrecedentEngine(records=[], deal_metadata=DealMetadata(stage="acquisition-dd"))
        calibration = engine.retrieve(
            CanonicalIssue(
                issue_id="utility-capacity",
                title="Utility capacity and provider confirmation remain open",
                category="Utilities / Infrastructure Issues",
                status="open",
                issue_type="utility-capacity",
                why_it_matters="Provider commitment remains open.",
                likely_implication="Schedule remains exposed.",
            )
        )

        self.assertFalse(calibration.matches)
        self.assertEqual(calibration.summary.score_adjustment, 0)
        self.assertEqual(calibration.summary.confidence_adjustment, "neutral")

    def test_feedback_ingestion_updates_issue_memory_store(self) -> None:
        feedback_rows = [
            {
                "issue_id": "environmental-followup",
                "canonical_title": "Environmental follow-up is not fully closed",
                "category": "Environmental Risks",
                "deal_id": "demo-deal",
                "deal_name": "Demo Deal",
                "deal_metadata": {
                    "stage": "acquisition-dd",
                    "geography": "west",
                    "product": "multifamily",
                },
                "evidence_basis": "direct_unresolved_risk",
                "issue_strength": "strong",
                "false_positive_risk": "low",
                "model_materiality": "high",
                "model_decision_relevant": True,
                "model_action": "verify",
                "real_issue": True,
                "false_positive_flag": False,
                "materiality": "high",
                "decision_relevant": True,
                "duplicate_of": None,
                "overstated": False,
                "understated": False,
                "actual_outcome": "cost",
                "resolved_by": "seller",
                "correct_action": "verify",
                "notes": "Seller credit covered the remediation reserve.",
            }
        ]

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            feedback_path = temp_path / "12_reviewer_feedback_template.json"
            store_path = temp_path / "issue_memory.jsonl"
            feedback_path.write_text(json.dumps(feedback_rows, indent=2), encoding="utf-8")

            result = ingest_reviewer_feedback_files(
                feedback_paths=[feedback_path],
                store_path=store_path,
            )

            self.assertEqual(result["files_ingested"], 1)
            self.assertEqual(result["records_upserted"], 1)
            stored = load_precedent_records(store_path)
            self.assertEqual(len(stored), 1)
            self.assertEqual(stored[0].issue_id, "environmental-followup")
            self.assertEqual(stored[0].deal_id, "demo-deal")
            self.assertEqual(stored[0].actual_outcome, "cost")
            self.assertEqual(stored[0].resolved_by, "seller")
            self.assertTrue(stored[0].decision_relevant)

    def test_learning_engine_upgrades_repeated_real_issue_pattern(self) -> None:
        records = [
            PrecedentIssueRecord(
                precedent_id=f"u{i}",
                deal_name=f"Utility Deal {i}",
                issue_type="utility-capacity",
                canonical_title="Utility capacity confirmation unresolved",
                category="Utilities / Infrastructure Issues",
                issue_id="utility-capacity",
                deal_id=f"utility-{i}",
                description="Provider will-serve stayed open and later delayed execution.",
                deal_metadata=DealMetadata(stage="acquisition-dd", region="west", product="multifamily"),
                evidence_basis="direct_unresolved_risk",
                issue_strength="strong",
                real_issue=True,
                materiality="high",
                decision_relevant=True,
                actual_outcome="delay",
                false_positive_flag=False,
                resolved_by="seller",
            )
            for i in range(4)
        ]
        engine = build_learning_engine(
            records=records,
            deal_metadata=DealMetadata(stage="acquisition-dd", region="west", product="multifamily"),
        )

        summary = engine.retrieve(
            CanonicalIssue(
                issue_id="utility-capacity",
                title="Utility capacity confirmation unresolved",
                category="Utilities / Infrastructure Issues",
                status="open",
                issue_type="utility-capacity",
                evidence_basis="direct_unresolved_risk",
                issue_strength="strong",
                decision_action="verify",
            )
        )

        self.assertGreaterEqual(summary.sample_size, 3)
        self.assertEqual(summary.confidence_adjustment, "up")
        self.assertGreater(summary.score_adjustment, 0)
        self.assertGreater(summary.real_issue_rate or 0.0, 0.7)

    def test_learning_engine_downgrades_repeated_false_positive_pattern(self) -> None:
        records = [
            PrecedentIssueRecord(
                precedent_id=f"d{i}",
                deal_name=f"Drainage Deal {i}",
                issue_type="stormwater-drainage",
                canonical_title="Stormwater support not provided",
                category="Flood / Drainage Issues",
                issue_id="stormwater-drainage",
                deal_id=f"drainage-{i}",
                description="Missing package support later proved routine.",
                deal_metadata=DealMetadata(stage="acquisition-dd", region="west", product="single-family"),
                evidence_basis="omission_only",
                issue_strength="weak",
                real_issue=False,
                materiality="low",
                decision_relevant=False,
                actual_outcome="none",
                false_positive_flag=True,
                resolved_by="seller",
            )
            for i in range(4)
        ]
        engine = build_learning_engine(
            records=records,
            deal_metadata=DealMetadata(stage="acquisition-dd", region="west", product="single-family"),
        )

        summary = engine.retrieve(
            CanonicalIssue(
                issue_id="stormwater-drainage",
                title="Stormwater support not provided",
                category="Flood / Drainage Issues",
                status="not found",
                issue_type="stormwater-drainage",
                evidence_basis="omission_only",
                issue_strength="weak",
                decision_action="monitor",
                false_positive_risk="high",
            )
        )

        self.assertGreaterEqual(summary.sample_size, 3)
        self.assertEqual(summary.confidence_adjustment, "down")
        self.assertLess(summary.score_adjustment, 0)
        self.assertGreater(summary.false_positive_rate or 0.0, 0.6)

    def test_registry_applies_learning_adjustment_and_snapshot(self) -> None:
        records = [
            PrecedentIssueRecord(
                precedent_id=f"t{i}",
                deal_name=f"Title Deal {i}",
                issue_type="title-access-clearance",
                canonical_title="Title access clearance unresolved",
                category="Title / Access Concerns",
                issue_id="title-access-clearance",
                deal_id=f"title-{i}",
                description="Access exception delayed or constrained the deal.",
                deal_metadata=DealMetadata(stage="acquisition-dd", region="west", product="multifamily"),
                evidence_basis="direct_unresolved_risk",
                issue_strength="strong",
                real_issue=True,
                materiality="high",
                decision_relevant=True,
                actual_outcome="delay",
                false_positive_flag=False,
            )
            for i in range(3)
        ]

        with tempfile.TemporaryDirectory() as temp_dir:
            snapshot_path = Path(temp_dir) / "learned_issue_model.json"
            engine = build_learning_engine(
                records=records,
                deal_metadata=DealMetadata(stage="acquisition-dd", region="west", product="multifamily"),
                snapshot_path=snapshot_path,
            )

            registry = build_canonical_issue_registry(
                key_risks=[
                    RiskFinding(
                        category="Title / Access Concerns",
                        severity="high",
                        summary="A title exception burdens the site entry condition.",
                        issue="Title access clearance unresolved.",
                        why_it_matters="This goes to access control and closability.",
                        likely_implication="The entry condition stays provisional until the burden is cleared or endorsed.",
                        source_documents=["Title Report"],
                        citations=[Citation(document_name="Title Report", chunk_id="page-0001", page_number=1)],
                        gating_flags=["Closing", "Underwriting confidence"],
                    )
                ],
                contradictions=[],
                omission_assessments=[],
                document_analyses=[],
                learning_retriever=engine.retrieve,
                deal_metadata=engine.deal_metadata,
            )

            issue = registry.issues[0]
            self.assertTrue(snapshot_path.exists())
            snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
            self.assertIn("feature_stats", snapshot)
            self.assertGreaterEqual(issue.learning_summary.sample_size, 3)
            self.assertEqual(issue.learning_summary.confidence_adjustment, "up")
            self.assertGreater(issue.priority_score.learning_adjustment, 0)


if __name__ == "__main__":
    unittest.main()
