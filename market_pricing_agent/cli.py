"""Command-line interface for the market pricing agent."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .agent import run_pricing_agent


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="market-pricing-agent",
        description="Fetch new-home community pricing and resale comps, then recommend pricing for a new project.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    analyze_parser = subparsers.add_parser(
        "analyze",
        help="Run the full pricing workflow from source fetch through recommendation output.",
    )
    analyze_parser.add_argument("--project-config", required=True, help="Path to the project JSON config.")
    analyze_parser.add_argument("--sources-config", required=True, help="Path to the sources JSON config.")
    analyze_parser.add_argument(
        "--output-dir",
        default="market_pricing_agent/outputs",
        help="Output directory for reports, JSON summaries, and normalized comp exports.",
    )
    analyze_parser.add_argument(
        "--print-report",
        action="store_true",
        help="Print the recommendation markdown to stdout after the run completes.",
    )
    return parser


def _handle_analyze(args: argparse.Namespace) -> None:
    result, artifacts = run_pricing_agent(
        project_config_path=Path(args.project_config),
        sources_config_path=Path(args.sources_config),
        output_dir=Path(args.output_dir),
    )

    print(
        json.dumps(
            {
                "project": result.project.to_dict(),
                "recommendation": result.recommendation.to_dict(),
                "warnings": result.warnings,
                "artifacts": {
                    "run_dir": str(artifacts.run_dir.resolve()),
                    "report_path": str(artifacts.report_path.resolve()),
                    "analysis_path": str(artifacts.analysis_path.resolve()),
                    "comps_path": str(artifacts.comps_path.resolve()),
                },
            },
            indent=2,
        )
    )

    if args.print_report:
        print()
        print(artifacts.report_path.read_text(encoding="utf-8"))


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    try:
        if args.command == "analyze":
            _handle_analyze(args)
            return
        parser.error(f"Unknown command: {args.command}")
    except Exception as error:  # noqa: BLE001
        print(f"Error: {error}", file=sys.stderr)
        raise SystemExit(1) from error


if __name__ == "__main__":
    main()