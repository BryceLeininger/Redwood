"""Agent_Diligence root package wrapper."""

from __future__ import annotations

import importlib
import sys

from agent_diligence._bootstrap import ensure_src_path

ensure_src_path()

DISPLAY_NAME = "Agent_Diligence"

_ALIASES = (
	"analysis",
	"classification",
	"config",
	"deal_models",
	"deal_pipeline",
	"ingestion",
	"llm",
	"models",
	"output",
	"parsing",
	"utils",
)


def _alias_modules() -> None:
	for module_name in _ALIASES:
		alias_name = f"agent_diligence.{module_name}"
		target_name = f"land_due_diligence_agent.{module_name}"
		if alias_name in sys.modules:
			continue
		sys.modules[alias_name] = importlib.import_module(target_name)


_alias_modules()

