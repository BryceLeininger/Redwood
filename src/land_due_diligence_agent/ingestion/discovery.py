"""Discover supported diligence files from an input folder."""

from __future__ import annotations

from collections.abc import Collection
from pathlib import Path


SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".xlsx", ".xls", ".csv", ".txt", ".md"}
DEFAULT_DEAL_EXCLUDED_DIRECTORIES = {
    "01_Working",
    "02_Text_Extraction",
    "03_Metadata",
    "04_Output",
    "__pycache__",
}


def is_supported_document(path: Path) -> bool:
    """Return whether a file extension is supported for text extraction."""

    return path.suffix.lower() in SUPPORTED_EXTENSIONS


def discover_all_files(
    input_folder: Path,
    *,
    exclude_dir_names: Collection[str] | None = None,
) -> list[Path]:
    """Return all files in sorted order, with optional directory exclusions."""

    _validate_input_folder(input_folder)
    excluded = {name.lower() for name in (exclude_dir_names or ())}

    discovered: list[Path] = []
    for path in input_folder.rglob("*"):
        if not path.is_file():
            continue
        relative_parts = path.relative_to(input_folder).parts[:-1]
        if any(part.lower() in excluded for part in relative_parts):
            continue
        discovered.append(path)

    return sorted(discovered, key=lambda path: path.as_posix().lower())


def discover_documents(
    input_folder: Path,
    *,
    exclude_dir_names: Collection[str] | None = None,
) -> list[Path]:
    """Return supported files in sorted order for deterministic processing."""

    return [
        path
        for path in discover_all_files(input_folder, exclude_dir_names=exclude_dir_names)
        if is_supported_document(path)
    ]


def discover_deal_files(
    deal_folder: Path,
    *,
    source_dir_name: str = "00_Source_Drop",
    exclude_dir_names: Collection[str] | None = None,
) -> list[Path]:
    """Return all files for a deal, preferring the source-drop folder when present."""

    _validate_input_folder(deal_folder)
    source_folder = deal_folder / source_dir_name
    if source_folder.exists():
        if not source_folder.is_dir():
            raise NotADirectoryError(f"Deal source path is not a directory: {source_folder}")
        return discover_all_files(source_folder, exclude_dir_names=exclude_dir_names)

    extra_exclusions = set(DEFAULT_DEAL_EXCLUDED_DIRECTORIES)
    extra_exclusions.update(exclude_dir_names or ())
    return discover_all_files(deal_folder, exclude_dir_names=extra_exclusions)


def _validate_input_folder(input_folder: Path) -> None:
    if not input_folder.exists():
        raise FileNotFoundError(f"Input folder does not exist: {input_folder}")
    if not input_folder.is_dir():
        raise NotADirectoryError(f"Input path is not a directory: {input_folder}")
