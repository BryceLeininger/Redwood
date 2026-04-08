"""Bootstrap helpers for the root-level Agent_Diligence package."""

from __future__ import annotations

import sys
from pathlib import Path


def ensure_src_path() -> None:
    """Ensure the repository's src directory is importable."""

    repo_root = Path(__file__).resolve().parent.parent
    src_path = repo_root / "src"
    src_path_str = str(src_path)
    if src_path.exists() and src_path_str not in sys.path:
        sys.path.insert(0, src_path_str)
