"""Discover supported diligence files from an input folder."""

from __future__ import annotations

from pathlib import Path


SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".xlsx", ".csv", ".txt", ".md"}


def discover_documents(input_folder: Path) -> list[Path]:
    """Return supported files in sorted order for deterministic processing."""

    if not input_folder.exists():
        raise FileNotFoundError(f"Input folder does not exist: {input_folder}")
    if not input_folder.is_dir():
        raise NotADirectoryError(f"Input path is not a directory: {input_folder}")

    return sorted(
        [
            path
            for path in input_folder.rglob("*")
            if path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS
        ],
        key=lambda path: path.as_posix().lower(),
    )
