"""Tests for document discovery."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from land_due_diligence_agent.ingestion.discovery import discover_all_files, discover_deal_files, discover_documents


class DiscoveryTests(unittest.TestCase):
    def test_discovers_only_supported_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "nested").mkdir()
            (root / "alpha.txt").write_text("alpha", encoding="utf-8")
            (root / "nested" / "beta.md").write_text("beta", encoding="utf-8")
            (root / "nested" / "gamma.xls").write_text("xls", encoding="utf-8")
            (root / "ignore.png").write_text("nope", encoding="utf-8")

            results = discover_documents(root)

            self.assertEqual(
                [path.relative_to(root).as_posix() for path in results],
                ["alpha.txt", "nested/beta.md", "nested/gamma.xls"],
            )

    def test_discovers_all_files_for_manifest_generation(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "nested").mkdir()
            (root / "alpha.txt").write_text("alpha", encoding="utf-8")
            (root / "nested" / "beta.md").write_text("beta", encoding="utf-8")
            (root / "ignore.png").write_text("nope", encoding="utf-8")

            results = discover_all_files(root)

            self.assertEqual(
                [path.relative_to(root).as_posix() for path in results],
                ["alpha.txt", "ignore.png", "nested/beta.md"],
            )

    def test_deal_discovery_prefers_source_drop(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "deal"
            source_drop = root / "00_Source_Drop"
            output_dir = root / "04_Output"
            source_drop.mkdir(parents=True)
            output_dir.mkdir(parents=True)
            (source_drop / "alpha.txt").write_text("alpha", encoding="utf-8")
            (output_dir / "result.txt").write_text("result", encoding="utf-8")

            results = discover_deal_files(root)

            self.assertEqual(
                [path.relative_to(source_drop).as_posix() for path in results],
                ["alpha.txt"],
            )


if __name__ == "__main__":
    unittest.main()
