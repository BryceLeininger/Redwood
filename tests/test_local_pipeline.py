"""Tests for the local deal-folder workflow."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from land_due_diligence_agent.config import Settings
from land_due_diligence_agent.deal_pipeline import run_local_deal_pipeline


class LocalDealPipelineTests(unittest.TestCase):
    def test_pipeline_writes_manifest_registry_and_report(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            deal_folder = Path(temp_dir) / "d1_375Diana"
            source_drop = deal_folder / "00_Source_Drop"
            (deal_folder / "01_Working").mkdir(parents=True)
            source_drop.mkdir(parents=True)

            (source_drop / "purchase_agreement.txt").write_text(
                "Purchase Price: $12,500,000. APN: 123-456-78. Zoning: R-1. 84 lots.",
                encoding="utf-8",
            )
            (source_drop / "title_report.txt").write_text(
                "Assessor Parcel Number: 123-456-79. Owner: Diana Land Holdings LLC. Easement exception shown in title.",
                encoding="utf-8",
            )
            (source_drop / "environment_notes.csv").write_text(
                "topic,value\nenvironment,recognized environmental condition\nutilities,will serve pending\n",
                encoding="utf-8",
            )
            (source_drop / "image.png").write_text("not supported", encoding="utf-8")

            settings = Settings(log_level="INFO")
            result, exit_code = run_local_deal_pipeline(deal_folder, settings=settings)

            self.assertEqual(exit_code, 0)
            self.assertTrue(Path(result.manifest_json_path).exists())
            self.assertTrue(Path(result.issue_registry_path).exists())
            self.assertTrue(Path(result.review_report_path).exists())
            self.assertTrue(Path(result.latest_run_path).exists())

            manifest_payload = json.loads(Path(result.manifest_json_path).read_text(encoding="utf-8"))
            self.assertEqual(manifest_payload["file_count"], 4)
            statuses = {
                item["file_name"]: item["extraction_status"]
                for item in manifest_payload["files"]
            }
            self.assertEqual(statuses["image.png"], "unsupported")
            self.assertEqual(statuses["purchase_agreement.txt"], "success")

            registry_payload = json.loads(Path(result.issue_registry_path).read_text(encoding="utf-8"))
            self.assertTrue(registry_payload["facts"])
            self.assertTrue(registry_payload["conflicts"])
            self.assertTrue(registry_payload["seller_questions"])

            review_text = Path(result.review_report_path).read_text(encoding="utf-8")
            self.assertIn("## Facts", review_text)
            self.assertIn("## Conflicts / Contradictions", review_text)
            self.assertIn("## Not Found In Provided Documents", review_text)

            source_files = sorted(path.name for path in source_drop.iterdir())
            self.assertEqual(
                source_files,
                [
                    "environment_notes.csv",
                    "image.png",
                    "purchase_agreement.txt",
                    "title_report.txt",
                ],
            )


if __name__ == "__main__":
    unittest.main()