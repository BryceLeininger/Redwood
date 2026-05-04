"""Utility helpers for the Google Sheets agent."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

GOOGLE_SHEET_ID_RE = re.compile(r"/spreadsheets/d/([a-zA-Z0-9-_]+)")
NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")


class SheetInputError(ValueError):
    """Raised when a sheet id or URL cannot be parsed."""


def extract_sheet_id(sheet_id: str | None = None, sheet_url: str | None = None) -> str:
    """Return a Google Sheets document id from either a raw id or full URL."""

    if sheet_id:
        cleaned = sheet_id.strip()
        if cleaned:
            return cleaned

    if not sheet_url:
        raise SheetInputError("Provide either --sheet-id or --sheet-url.")

    candidate = sheet_url.strip()
    match = GOOGLE_SHEET_ID_RE.search(candidate)
    if not match:
        raise SheetInputError(
            "The provided Google Sheets URL is invalid. Expected a URL like "
            "https://docs.google.com/spreadsheets/d/<sheet-id>/edit"
        )
    return match.group(1)


def snake_case(value: str) -> str:
    """Convert text into a filesystem and dataframe safe snake_case string."""

    text = value.strip().lower()
    text = text.replace("%", " percent ").replace("$", " dollar ")
    text = NON_ALNUM_RE.sub("_", text)
    text = text.strip("_")
    return text or "column"


def flatten_duplicate_names(names: list[str]) -> list[str]:
    """Ensure duplicate column names become unique while preserving order."""

    counters: dict[str, int] = {}
    flattened: list[str] = []
    for name in names:
        current = name or "column"
        count = counters.get(current, 0)
        counters[current] = count + 1
        flattened.append(current if count == 0 else f"{current}_{count + 1}")
    return flattened


def safe_file_stem(value: str) -> str:
    """Return a cross-platform safe filename stem."""

    return snake_case(value).replace("__", "_") or "worksheet"


def ensure_directory(path: Path) -> Path:
    """Create a directory if it does not already exist."""

    path.mkdir(parents=True, exist_ok=True)
    return path


def utc_timestamp() -> str:
    """Return an ISO-8601 UTC timestamp for manifests and logs."""

    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()
