"""Tests for markdown output generation."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from land_due_diligence_agent.models import (
    DealSynthesis,
    DocumentAnalysis,
    DocumentRecord,
    FileProcessingResult,
    ReadingRecommendation,
    RiskFinding,
    RunSummary,
)
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
        run_summary = RunSummary(
            run_id="20260328_120000",
            deal_name="Demo Deal",
            input_folder="data/input/demo-deal",
            output_folder="data/output/demo-deal/20260328_120000",
            llm_provider="heuristic",
            started_at="2026-03-28T12:00:00-07:00",
            completed_at="2026-03-28T12:01:00-07:00",
            files_found=1,
            files_parsed_successfully=1,
            files_failed=0,
            file_results=[FileProcessingResult(relative_path="memo.txt", status="parsed")],
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir)
            (output_dir / "run.log").write_text("log", encoding="utf-8")
            written = write_markdown_outputs(output_dir, run_summary=run_summary, synthesis=synthesis)

            self.assertEqual(len(written), 9)
            self.assertTrue((output_dir / "00_run_summary.md").exists())
            self.assertTrue((output_dir / "08_error_report.md").exists())
            self.assertTrue((output_dir / "01_executive_summary.md").exists())
            content = (output_dir / "01_executive_summary.md").read_text(encoding="utf-8")
            self.assertIn("Demo Deal", content)
            self.assertIn("heuristic", content)
            summary_content = (output_dir / "00_run_summary.md").read_text(encoding="utf-8")
            self.assertIn("Files found: 1", summary_content)
            self.assertIn("run.log", summary_content)

    def test_writes_summary_and_error_report_without_synthesis(self) -> None:
        run_summary = RunSummary(
            run_id="20260328_120000",
            deal_name="Broken Deal",
            input_folder="data/input/broken-deal",
            output_folder="data/output/broken-deal/20260328_120000",
            llm_provider="heuristic",
            started_at="2026-03-28T12:00:00-07:00",
            completed_at="2026-03-28T12:01:00-07:00",
            files_found=2,
            files_parsed_successfully=0,
            files_failed=2,
            file_results=[
                FileProcessingResult(relative_path="bad.pdf", status="failed", error_message="PdfReadError: corrupt"),
                FileProcessingResult(relative_path="scan.pdf", status="failed", error_message="RuntimeError: no text"),
            ],
            run_errors=["No documents could be parsed successfully."],
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir)
            (output_dir / "run.log").write_text("log", encoding="utf-8")
            written = write_markdown_outputs(output_dir, run_summary=run_summary)

            self.assertEqual(len(written), 2)
            error_content = (output_dir / "08_error_report.md").read_text(encoding="utf-8")
            self.assertIn("bad.pdf", error_content)
            self.assertIn("No documents could be parsed successfully.", error_content)


if __name__ == "__main__":
    unittest.main()
