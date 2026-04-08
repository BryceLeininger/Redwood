"""Configuration management for the FRED agent."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


class ConfigError(RuntimeError):
    """Raised when required configuration is missing."""


@dataclass(frozen=True)
class AgentConfig:
    """Resolved configuration for the FRED agent runtime."""

    api_key: str
    raw_output_dir: Path
    master_output_path: Path


def _resolve_project_root() -> Path:
    return Path(__file__).resolve().parent


def _get_env_var(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise ConfigError(f"Environment variable '{name}' is not set.")
    return value


def load_config() -> AgentConfig:
    """Load and validate agent configuration from the environment."""

    project_root = _resolve_project_root()
    raw_output_dir = project_root / "outputs" / "raw"
    master_output_path = project_root / "outputs" / "master" / "fred_master.csv"

    api_key = _get_env_var("FRED_API_KEY")

    raw_output_dir.mkdir(parents=True, exist_ok=True)
    master_output_path.parent.mkdir(parents=True, exist_ok=True)

    return AgentConfig(
        api_key=api_key,
        raw_output_dir=raw_output_dir,
        master_output_path=master_output_path,
    )
