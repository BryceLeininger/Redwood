"""Tests for markdown output generation."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from land_due_diligence_agent.models import DealSynthesis, DocumentAnalysis, DocumentRecord, ReadingRecommendation, RiskFinding
from land_due_diligence_agent.output.markdown_writer import write_markdown_outputs


class OutputWriterTests(unittest.TestCase):
    def test_writes_expected_markdown_files(self) -> None:
        document = DocumentRecord(
            source_path=Path("memo.txt"),
            relative_path=Path("memo.txt"),
            extension=".txt",
            title="Memo",
            raw_text="memo",
            normalized_text="memo",
        )
        analysis = DocumentAnalysis(
            document=document,
            summary="Summary text.",
            risks=[RiskFinding(category="Environmental Risks", severity="high", summary="Risk summary.", evidence=["Memo: evidence"])],
            seller_questions=["What remediation is still outstanding?"],
            reading_priority=5,
            reading_reason="Contains high-priority environmental indicators.",
        )
        synthesis = DealSynthesis(
            deal_name="Demo Deal",
            executive_summary="Executive summary text.",
            entitlement_status="Status unclear.",
            key_risks=analysis.risks,
            recommended_reading_order=[
                ReadingRecommendation(
                    title="Memo",
                    relative_path="memo.txt",
                    priority=5,
                    reason="Contains high-priority environmental indicators.",
                )
            ],
            seller_questions=analysis.seller_questions,
            missing_items=["ALTA or boundary survey"],
            category_rollup={"Environmental Risks": "One document flagged environmental signals."},
            document_analyses=[analysis],
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir)
            written = write_markdown_outputs(output_dir, synthesis, "heuristic")

            self.assertEqual(len(written), 7)
            self.assertTrue((output_dir / "00_executive_summary.md").exists())
            content = (output_dir / "00_executive_summary.md").read_text(encoding="utf-8")
            self.assertIn("Demo Deal", content)
            self.assertIn("heuristic", content)


if __name__ == "__main__":
    unittest.main()
