"""Environment-backed runtime settings."""

from __future__ import annotations

import os
from dataclasses import dataclass, replace
from pathlib import Path

from dotenv import load_dotenv


_DEFAULT_DEALS_ROOT = str(Path.home() / "Desktop" / "Agent_Diligence" / "Deals")


@dataclass(slots=True)
class Settings:
    """Application settings loaded from environment variables."""

    llm_provider: str = "heuristic"
    openai_api_key: str | None = None
    openai_model: str = "gpt-4.1"
    openai_base_url: str | None = None
    autonomous_learning_enabled: bool = True
    web_research_enabled: bool = True
    web_research_model: str = "gpt-4.1"
    web_research_max_queries: int = 4
    default_output_dir: str = "data/output"
    default_deals_root: str = _DEFAULT_DEALS_ROOT
    deal_source_subdir: str = "00_Source_Drop"
    deal_working_subdir: str = "01_Working"
    text_extraction_subdir: str = "02_Text_Extraction"
    metadata_subdir: str = "03_Metadata"
    report_output_subdir: str = "04_Output"
    log_level: str = "INFO"

    @classmethod
    def from_env(cls) -> "Settings":
        """Load configuration from a local `.env` file and process env vars."""

        load_dotenv()
        return cls._from_current_env()

    @classmethod
    def from_env_path(cls, env_path: str) -> "Settings":
        """Load configuration from an explicit `.env` file path."""

        load_dotenv(env_path, override=True)
        return cls._from_current_env()

    @classmethod
    def _from_current_env(cls) -> "Settings":
        """Build settings from the current process environment."""

        return cls(
            llm_provider=os.getenv("LLM_PROVIDER", "heuristic").strip().lower(),
            openai_api_key=_clean_env("OPENAI_API_KEY"),
            openai_model=os.getenv("OPENAI_MODEL", "gpt-4.1").strip(),
            openai_base_url=_clean_env("OPENAI_BASE_URL"),
            autonomous_learning_enabled=_env_bool("AUTONOMOUS_LEARNING_ENABLED", True),
            web_research_enabled=_env_bool("WEB_RESEARCH_ENABLED", True),
            web_research_model=os.getenv("WEB_RESEARCH_MODEL", "gpt-4.1").strip(),
            web_research_max_queries=_env_int("WEB_RESEARCH_MAX_QUERIES", 4),
            default_output_dir=os.getenv("DEFAULT_OUTPUT_DIR", "data/output").strip(),
            default_deals_root=_env_str("DEFAULT_DEALS_ROOT", _DEFAULT_DEALS_ROOT),
            deal_source_subdir=_env_str("DEAL_SOURCE_SUBDIR", "00_Source_Drop"),
            deal_working_subdir=_env_str("DEAL_WORKING_SUBDIR", "01_Working"),
            text_extraction_subdir=_env_str("TEXT_EXTRACTION_SUBDIR", "02_Text_Extraction"),
            metadata_subdir=_env_str("METADATA_SUBDIR", "03_Metadata"),
            report_output_subdir=_env_str("REPORT_OUTPUT_SUBDIR", "04_Output"),
            log_level=os.getenv("LOG_LEVEL", "INFO").strip().upper(),
        )

    def with_overrides(
        self,
        *,
        llm_provider: str | None = None,
        log_level: str | None = None,
    ) -> "Settings":
        """Return a copy of settings with CLI overrides applied."""

        return replace(
            self,
            llm_provider=(llm_provider or self.llm_provider).strip().lower(),
            log_level=(log_level or self.log_level).strip().upper(),
        )


def _clean_env(name: str) -> str | None:
    value = os.getenv(name)
    if value is None:
        return None
    value = value.strip()
    if not value:
        os.environ.pop(name, None)
        return None
    os.environ[name] = value
    return value


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() not in {"0", "false", "no", "off"}


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        parsed = int(value.strip())
    except ValueError:
        return default
    return parsed if parsed > 0 else default


def _env_str(name: str, default: str) -> str:
    value = os.getenv(name)
    if value is None:
        return default
    value = value.strip()
    return value or default
