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

    def test_deal_argument_is_accepted(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["--deal", "d1_375Diana"])
        self.assertEqual(args.deal, "d1_375Diana")

    def test_deal_folder_argument_is_accepted(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["--deal-folder", "C:/Deals/d1_375Diana"])
        self.assertEqual(args.deal_folder, "C:/Deals/d1_375Diana")


if __name__ == "__main__":
    unittest.main()
