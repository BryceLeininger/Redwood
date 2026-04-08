"""Tests for the standardized agent_diligence package namespace."""

from __future__ import annotations

import unittest


class AgentDiligencePackageTests(unittest.TestCase):
    def test_core_modules_import_from_agent_diligence_namespace(self) -> None:
        from agent_diligence.cli import build_parser
        from agent_diligence.config import Settings
        from agent_diligence.deal_pipeline import run_local_deal_pipeline

        self.assertTrue(callable(build_parser))
        self.assertTrue(callable(run_local_deal_pipeline))
        self.assertEqual(Settings.__name__, "Settings")


if __name__ == "__main__":
    unittest.main()