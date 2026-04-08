"""Agent_Diligence CLI wrapper."""

from __future__ import annotations

from agent_diligence._bootstrap import ensure_src_path

ensure_src_path()

from land_due_diligence_agent.cli import build_parser, main

__all__ = ["build_parser", "main"]
