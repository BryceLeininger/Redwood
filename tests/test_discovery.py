"""Tests for document discovery."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from land_due_diligence_agent.ingestion.discovery import discover_documents


class DiscoveryTests(unittest.TestCase):
    def test_discovers_only_supported_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "nested").mkdir()
            (root / "alpha.txt").write_text("alpha", encoding="utf-8")
            (root / "nested" / "beta.md").write_text("beta", encoding="utf-8")
            (root / "ignore.png").write_text("nope", encoding="utf-8")

            results = discover_documents(root)

            self.assertEqual(
                [path.relative_to(root).as_posix() for path in results],
                ["alpha.txt", "nested/beta.md"],
            )


if __name__ == "__main__":
    unittest.main()
