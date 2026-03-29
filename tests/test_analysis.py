"""Tests for the analysis pipeline."""

from __future__ import annotations

import logging
import unittest
from pathlib import Path

from land_due_diligence_agent.analysis.issue_registry import (
    build_canonical_issue_registry,
    build_recommendation_from_registry,
    build_section_selections,
)
from land_due_diligence_agent.analysis.service import run_analysis
from land_due_diligence_agent.llm.base import LLMProvider
from land_due_diligence_agent.llm.heuristic_provider import HeuristicProvider
from land_due_diligence_agent.models import Citation, ContradictionFinding, DocumentRecord, OmissionAssessment, RiskFinding
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


class AnalysisTests(unittest.TestCase):
    def test_normalize_text_repairs_common_mojibake(self) -> None:
        text = "The dealâ€™s geotech scopeâ€”and cost basisâ€”need review."
        self.assertEqual(
            normalize_text(text),
            "The deal's geotech scope-and cost basis-need review.",
        )

    def test_generates_key_risks_and_questions(self) -> None:
        documents = [
            _document(
                "environmental_report.txt",
                (
                    "Phase I environmental site assessment identified a recognized environmental condition. "
                    "Wetlands and floodplain constraints affect a portion of the site. "
                    "Utility capacity remains pending and a will serve letter has not been issued."
                ),
            ),
            _document(
                "zoning_memo.txt",
                (
                    "Current zoning is not approved and rezoning required before final plat approval. "
                    "Title review notes an access easement exception. "
                    "The city backlog may delay the schedule and create a long lead entitlement path."
                ),
            ),
        ]

        synthesis = run_analysis(
            deal_name="Test Deal",
            documents=documents,
            llm_provider=HeuristicProvider(),
            logger=logging.getLogger("test-analysis"),
        )

        categories = {risk.category for risk in synthesis.key_risks}
        self.assertIn("Environmental Risks", categories)
        self.assertIn("Flood / Drainage Issues", categories)
        self.assertIn("Entitlement Status", categories)
        self.assertIn("Title / Access Concerns", categories)
        self.assertIn("Schedule Risks", categories)
        self.assertTrue(synthesis.seller_questions)
        self.assertTrue(any("ALTA" in item for item in synthesis.missing_items))
        self.assertTrue(all(risk.citations for risk in synthesis.key_risks))

    def test_detects_cross_document_tensions(self) -> None:
        documents = [
            _document(
                "title_report.txt",
                "Preliminary title report lists an access easement exception affecting the current site layout.",
            ),
            _document(
                "design_permit_plans.txt",
                "The vehicular project entry is located along the Diana Avenue frontage and private access drive.",
            ),
            _document(
                "conditions_of_approval.txt",
                "At improvement plan stage, the project shall confirm if the Diana Avenue frontage was dedicated to the City.",
            ),
            _document(
                "stormwater_plan.txt",
                "Diana Avenue frontage is already improved.",
            ),
            _document(
                "geotechnical_report.txt",
                "Liquefaction triggering and foundation recommendations apply to the site and must be incorporated into design.",
            ),
            _document(
                "site_budget.txt",
                "Budgetary pricing only. Preliminary proposal with allowances and unresolved contingencies.",
            ),
        ]

        synthesis = run_analysis(
            deal_name="Contradiction Deal",
            documents=documents,
            llm_provider=HeuristicProvider(),
            logger=logging.getLogger("test-contradictions"),
        )

        self.assertTrue(synthesis.contradictions)
        self.assertTrue(synthesis.issue_analyses)
        self.assertTrue(synthesis.priority_assessment.top_deal_shaping_issues)
        self.assertTrue(synthesis.challenge_findings)
        self.assertTrue(any("frontage" in finding.description.lower() or "access" in finding.description.lower() for finding in synthesis.contradictions))
        self.assertTrue(all(finding.citations for finding in synthesis.contradictions))

    def test_fast_mode_limits_analysis_depth_and_llm_calls(self) -> None:
        class CountingProvider(LLMProvider):
            provider_name = "openai"

            def __init__(self) -> None:
                self.model = "fake-openai"
                self.document_calls = 0
                self.executive_calls = 0

            def refine_document_summary(
                self,
                document: DocumentRecord,
                draft_summary: str,
                risks: list[RiskFinding],
                missing_items: list[str],
            ) -> str:
                self.document_calls += 1
                return draft_summary

            def refine_executive_summary(
                self,
                deal_name: str,
                draft_summary: str,
                category_rollup: dict[str, str],
                key_risks: list[RiskFinding],
                contradictions: list[ContradictionFinding],
                missing_items: list[str],
            ) -> str:
                self.executive_calls += 1
                return draft_summary

        documents = [
            _document(
                "title_report.txt",
                "Preliminary title report lists an access easement exception affecting the current site layout.",
            ),
            _document(
                "design_permit_plans.txt",
                "The vehicular project entry is located along the Diana Avenue frontage and private access drive.",
            ),
            _document(
                "conditions_of_approval.txt",
                "At improvement plan stage, the project shall confirm if the Diana Avenue frontage was dedicated to the City.",
            ),
            _document(
                "stormwater_plan.txt",
                "Diana Avenue frontage is already improved.",
            ),
        ]

        provider = CountingProvider()
        synthesis = run_analysis(
            deal_name="Fast Deal",
            documents=documents,
            llm_provider=provider,
            logger=logging.getLogger("test-fast-mode"),
            mode="fast",
        )

        self.assertEqual(provider.document_calls, 0)
        self.assertEqual(provider.executive_calls, 1)
        self.assertEqual(synthesis.llm_calls_attempted, 1)
        self.assertFalse(synthesis.contradictions)
        self.assertLessEqual(len(synthesis.key_risks), 3)
        self.assertLessEqual(len(synthesis.seller_questions), 6)

    def test_canonical_registry_merges_overlapping_utility_signals(self) -> None:
        risks = [
            RiskFinding(
                category="Utilities / Infrastructure Issues",
                severity="high",
                summary="Utility capacity remains pending and will-serve support is not in the file.",
                issue="Utility capacity and provider confirmation remain open.",
                why_it_matters="Provider commitment is still required before the utility path is reliable.",
                likely_implication="Schedule and offsite utility scope remain exposed.",
                source_documents=["Utility Memo"],
            ),
            RiskFinding(
                category="Schedule Risks",
                severity="medium",
                summary="Provider coordination remains open and keeps the schedule path exposed.",
                issue="Utility-related schedule risk remains open.",
                why_it_matters="The critical path still depends on provider coordination.",
                likely_implication="Schedule slips remain likely until utility assumptions are confirmed.",
                source_documents=["Schedule Memo"],
            ),
            RiskFinding(
                category="Budget / Cost Reliability",
                severity="medium",
                summary="Joint trench and dry-utility scope still reads as budgetary.",
                issue="Offsite utility risk is not fully priced.",
                why_it_matters="Basis remains exposed if utility work is larger than assumed.",
                likely_implication="Cost can move if utility scope is repriced.",
                source_documents=["Budget Memo"],
            ),
        ]
        omissions = [
            OmissionAssessment(
                item="Utility availability / will-serve documentation",
                category="Utilities / Infrastructure Issues",
                status="not found",
                rationale="No current will-serve letter is in the package.",
            )
        ]
        registry = build_canonical_issue_registry(
            key_risks=risks,
            contradictions=[],
            omission_assessments=omissions,
            document_analyses=[],
        )

        utility_issue = next((issue for issue in registry.issues if issue.issue_id == "utility-capacity"), None)
        self.assertIsNotNone(utility_issue)
        self.assertGreaterEqual(len(utility_issue.merged_fragment_ids), 3)
        self.assertEqual(utility_issue.decision_action, "condition closing")

    def test_registry_ranking_and_output_selection_are_stable(self) -> None:
        documents = [
            _document(
                "title_report.txt",
                "Preliminary title report lists an access easement exception affecting the current site layout.",
            ),
            _document(
                "budget.txt",
                "Budgetary pricing only. Preliminary proposal with allowances and unresolved contingencies.",
            ),
        ]
        synthesis = run_analysis(
            deal_name="Ranking Deal",
            documents=documents,
            llm_provider=HeuristicProvider(),
            logger=logging.getLogger("test-ranking"),
        )
        registry = synthesis.canonical_issue_registry
        self.assertTrue(registry.issues)
        self.assertEqual(registry.issues[0].issue_id, "title-access-clearance")

        recommendation = build_recommendation_from_registry(registry)
        selections = build_section_selections(registry, recommendation, analysis_mode="full")
        executive_ids = [selection.issue_id for selection in selections if selection.output_name == "01_executive_summary.md"]
        key_risk_ids = [selection.issue_id for selection in selections if selection.output_name == "02_key_risks.md"]
        self.assertEqual(len(executive_ids), len(set(executive_ids)))
        self.assertEqual(len(key_risk_ids), len(set(key_risk_ids)))
        self.assertTrue(set(executive_ids).issubset(set(key_risk_ids)))

    def test_omission_only_issue_is_downgraded_when_not_critical(self) -> None:
        registry = build_canonical_issue_registry(
            key_risks=[],
            contradictions=[],
            omission_assessments=[
                OmissionAssessment(
                    item="Agency correspondence log",
                    category="Entitlement Status",
                    status="unclear whether present",
                    rationale="No clean correspondence log is in the package.",
                )
            ],
            document_analyses=[],
        )

        issue = next(issue for issue in registry.issues if issue.issue_id == "entitlement-conditions")
        self.assertEqual(issue.evidence_basis, "routine_missing_support")
        self.assertEqual(issue.issue_strength, "weak")
        self.assertFalse(issue.top_line_eligible)
        self.assertIn("normal process friction", issue.top_line_filter_reasons)

    def test_strong_direct_evidence_issue_stays_top_line_eligible(self) -> None:
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
        )

        issue = registry.issues[0]
        self.assertIn(issue.evidence_basis, {"direct_confirmed_risk", "direct_unresolved_risk"})
        self.assertEqual(issue.issue_strength, "strong")
        self.assertTrue(issue.top_line_eligible)

    def test_output_selection_filters_weak_routine_issue(self) -> None:
        registry = build_canonical_issue_registry(
            key_risks=[
                RiskFinding(
                    category="Environmental Risks",
                    severity="high",
                    summary="Phase I ESA identifies follow-up work.",
                    issue="Environmental follow-up is not fully closed.",
                    why_it_matters="Environmental scope still affects underwriting confidence.",
                    likely_implication="Mitigation cost remains open.",
                    source_documents=["Phase I ESA"],
                    gating_flags=["Underwriting confidence"],
                )
            ],
            contradictions=[],
            omission_assessments=[
                OmissionAssessment(
                    item="Agency correspondence log",
                    category="Entitlement Status",
                    status="unclear whether present",
                    rationale="No clean correspondence log is in the package.",
                )
            ],
            document_analyses=[],
        )
        recommendation = build_recommendation_from_registry(registry)
        selections = build_section_selections(registry, recommendation, analysis_mode="full")

        executive_ids = [selection.issue_id for selection in selections if selection.output_name == "01_executive_summary.md"]
        self.assertIn("environmental-followup", executive_ids)
        self.assertNotIn("entitlement-conditions", executive_ids)

    def test_ambiguous_merge_arbiter_is_used(self) -> None:
        arbiter_calls: list[tuple[str, str]] = []

        def _arbiter(left_fragment, right_fragment):
            arbiter_calls.append((left_fragment.fragment_id, right_fragment.fragment_id))
            return "same_issue", "Utility scope and schedule exposure should be treated as one issue."

        registry = build_canonical_issue_registry(
            key_risks=[
                RiskFinding(
                    category="Budget / Cost Reliability",
                    severity="high",
                    summary="The site-development cost package is still budgetary and allowance-driven.",
                    issue="Cost package is still budgetary.",
                    why_it_matters="Basis remains exposed if the current cost stack is not auditable.",
                    likely_implication="Land basis remains provisional until pricing is locked.",
                    source_documents=["Cost Memo"],
                    gating_flags=["Underwriting confidence"],
                ),
                RiskFinding(
                    category="Fee / Exaction Burden",
                    severity="medium",
                    summary="Impact fee assumptions are still preliminary in the same underwriting package.",
                    issue="Fee stack is not locked.",
                    why_it_matters="The same underwriting package still depends on estimated fee assumptions.",
                    likely_implication="Land basis can move if the fee stack resets.",
                    source_documents=["Cost Memo"],
                    gating_flags=["Underwriting confidence"],
                ),
            ],
            contradictions=[],
            omission_assessments=[],
            document_analyses=[],
            merge_arbiter=_arbiter,
        )

        self.assertTrue(arbiter_calls)
        self.assertTrue(registry.arbitration_records)
        self.assertTrue(registry.arbitration_records[0].used_arbiter)


if __name__ == "__main__":
    unittest.main()
