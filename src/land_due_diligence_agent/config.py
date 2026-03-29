"""Environment-backed runtime settings."""

from __future__ import annotations

import os
from dataclasses import dataclass, replace

from dotenv import load_dotenv


@dataclass(slots=True)
class Settings:
    """Application settings loaded from environment variables."""

    llm_provider: str = "heuristic"
    openai_api_key: str | None = None
    openai_model: str = "gpt-4.1"
    openai_base_url: str | None = None
    default_output_dir: str = "data/output"
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
            default_output_dir=os.getenv("DEFAULT_OUTPUT_DIR", "data/output").strip(),
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
