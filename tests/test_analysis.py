"""Tests for the analysis pipeline."""

from __future__ import annotations

import logging
import unittest
from pathlib import Path

from land_due_diligence_agent.analysis.service import run_analysis
from land_due_diligence_agent.llm.base import LLMProvider
from land_due_diligence_agent.llm.heuristic_provider import HeuristicProvider
from land_due_diligence_agent.models import ContradictionFinding, DocumentRecord, RiskFinding
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


if __name__ == "__main__":
    unittest.main()
