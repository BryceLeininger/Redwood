"""Command-line interface for the Outlook Email Secretary agent."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .agent import OESAgent
from .config import load_config
from .local_outlook import LocalOutlookProvider
from .storage import LocalStore


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="oes-agent",
        description=(
            "Outlook Email Secretary agent with Outlook inbox triage, calendar support, "
            "approval-queued actions, and reminder management."
        ),
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    serve_parser = subparsers.add_parser(
        "serve",
        help="Start the local web application for laptop and phone browser access.",
    )
    serve_parser.add_argument("--host", default="127.0.0.1", help="Host interface to bind.")
    serve_parser.add_argument("--port", type=int, default=8787, help="Port for the web server.")

    sync_parser = subparsers.add_parser(
        "sync",
        help="Sync inbox and calendar data into the local OES dashboard store.",
    )
    sync_parser.add_argument(
        "--live",
        action="store_true",
        help="Pull live data from Microsoft Graph instead of using a local sample inbox cache.",
    )
    sync_parser.add_argument(
        "--sample-json",
        default="generated_agents/outlook_local_cache.json",
        help="Path to a local sample inbox JSON payload used when --live is not set.",
    )
    sync_parser.add_argument("--mail-limit", type=int, default=25, help="Maximum inbox messages to load.")
    sync_parser.add_argument("--calendar-days", type=int, default=14, help="Upcoming calendar window in days.")

    subparsers.add_parser(
        "auth",
        help="Run Microsoft Graph device-code authentication and cache the token locally.",
    )

    subparsers.add_parser(
        "doctor",
        help="Validate local OES configuration and dependency readiness.",
    )
    return parser


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()
    config = load_config()
    store = LocalStore(config.db_path)
    store.ensure_ready()
    agent = OESAgent(config=config, store=store)

    if args.command == "serve":
        import uvicorn

        uvicorn.run(
            "oes_agent.web:create_app",
            host=args.host,
            port=args.port,
            factory=True,
            reload=False,
        )
        return

    if args.command == "auth":
        result = agent.authenticate_graph()
        print(json.dumps(result, indent=2))
        return

    if args.command == "sync":
        sample_json = None if args.live else Path(args.sample_json)
        result = agent.sync(
            sample_json_path=sample_json,
            mail_limit=args.mail_limit,
            calendar_days=args.calendar_days,
        )
        print(json.dumps(result, indent=2))
        return

    if args.command == "doctor":
        result = {
            "data_dir": str(config.data_dir.resolve()),
            "db_path": str(config.db_path.resolve()),
            "token_cache_path": str(config.token_cache_path.resolve()),
            "graph": {
                "configured": config.has_graph_config,
                "tenant_id": config.graph_tenant_id,
                "client_id_present": bool(config.graph_client_id),
                "scopes": list(config.graph_scopes),
            },
            "ai": {
                "configured": config.has_ai_config,
                "model": config.openai_model,
            },
            "local_outlook": LocalOutlookProvider.detect().to_dict(),
            "pending_approvals": len(store.list_approvals()),
            "open_reminders": len(store.list_reminders()),
            "notes": [],
        }
        if not config.has_graph_config:
            result["notes"].append(
                "Set OES_GRAPH_CLIENT_ID to enable Microsoft Graph access, or use the local Outlook desktop fallback for live sync."
            )
        if not config.has_ai_config:
            result["notes"].append("Set OPENAI_API_KEY to enable AI triage and drafting.")
        print(json.dumps(result, indent=2))
        return

    parser.error(f"Unknown command: {args.command}")
