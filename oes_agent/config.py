"""Configuration helpers for the Outlook Email Secretary agent."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

DEFAULT_GRAPH_SCOPES = (
    "User.Read",
    "Mail.Read",
    "Mail.ReadWrite",
    "Mail.Send",
    "Calendars.ReadWrite",
    "Tasks.ReadWrite",
    "offline_access",
)


def _parse_scopes(raw_value: str | None) -> tuple[str, ...]:
    if not raw_value:
        return DEFAULT_GRAPH_SCOPES
    parts = [item.strip() for item in raw_value.split(",")]
    return tuple(item for item in parts if item)


@dataclass(frozen=True)
class OESConfig:
    data_dir: Path
    db_path: Path
    token_cache_path: Path
    host: str
    port: int
    graph_client_id: str | None
    graph_tenant_id: str
    graph_scopes: tuple[str, ...]
    openai_api_key: str | None
    openai_model: str | None

    @property
    def has_graph_config(self) -> bool:
        return bool(self.graph_client_id)

    @property
    def has_ai_config(self) -> bool:
        return bool(self.openai_api_key)


def load_config(env_path: Path | None = None) -> OESConfig:
    load_dotenv(dotenv_path=env_path or Path(".env"), override=False)

    data_dir = Path(os.getenv("OES_DATA_DIR", "data/output/oes_agent"))
    data_dir.mkdir(parents=True, exist_ok=True)

    db_path = data_dir / "oes_agent.db"
    token_cache_path = data_dir / "graph_token_cache.bin"

    return OESConfig(
        data_dir=data_dir,
        db_path=db_path,
        token_cache_path=token_cache_path,
        host=os.getenv("OES_HOST", "127.0.0.1"),
        port=int(os.getenv("OES_PORT", "8787")),
        graph_client_id=os.getenv("OES_GRAPH_CLIENT_ID"),
        graph_tenant_id=os.getenv("OES_GRAPH_TENANT_ID", "common"),
        graph_scopes=_parse_scopes(os.getenv("OES_GRAPH_SCOPES")),
        openai_api_key=os.getenv("OPENAI_API_KEY"),
        openai_model=os.getenv("OES_OPENAI_MODEL") or "gpt-4.1-mini",
    )