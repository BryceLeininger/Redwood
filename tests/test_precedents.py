"""Tests for local precedent retrieval and outcome-aware calibration."""

from __future__ import annotations

import unittest

from land_due_diligence_agent.analysis.issue_registry import build_canonical_issue_registry
from land_due_diligence_agent.analysis.precedents import PrecedentEngine
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
        self.assertEqual(calibration.summary.confidence_adjustment, "none")


if __name__ == "__main__":
    unittest.main()
