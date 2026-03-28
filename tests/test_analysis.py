"""Tests for the analysis pipeline."""

from __future__ import annotations

import logging
import unittest
from pathlib import Path

from land_due_diligence_agent.analysis.service import run_analysis
from land_due_diligence_agent.llm.heuristic_provider import HeuristicProvider
from land_due_diligence_agent.models import DocumentRecord
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


if __name__ == "__main__":
    unittest.main()
