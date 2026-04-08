"""Filesystem helpers."""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path


def ensure_directory(path: Path) -> Path:
    """Create a directory if it does not already exist."""

    path.mkdir(parents=True, exist_ok=True)
    return path


def humanize_filename(stem: str) -> str:
    """Convert a file stem into a readable display title."""

    return re.sub(r"\s+", " ", stem.replace("_", " ").replace("-", " ")).strip().title()


def slugify(value: str) -> str:
    """Convert arbitrary text into a safe portable folder or file slug."""

    normalized = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    normalized = re.sub(r"[^a-zA-Z0-9]+", "-", normalized).strip("-").lower()
    return normalized or "run"
