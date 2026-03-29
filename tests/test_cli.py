"""Tests for CLI argument parsing."""

from __future__ import annotations

import unittest

from land_due_diligence_agent.cli import build_parser


class CLITests(unittest.TestCase):
    def test_mode_defaults_to_fast(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["--input-folder", "data/input/demo"])
        self.assertEqual(args.mode, "fast")

    def test_mode_accepts_full(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["--input-folder", "data/input/demo", "--mode", "full"])
        self.assertEqual(args.mode, "full")


if __name__ == "__main__":
    unittest.main()
