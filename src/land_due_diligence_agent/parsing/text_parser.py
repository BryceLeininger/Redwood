"""Plain-text and Markdown extraction helpers."""

from __future__ import annotations

from pathlib import Path


def extract_text_file(path: Path) -> tuple[str, dict[str, str | int], list[str]]:
    """Extract text from a UTF-8 or Latin-1 encoded text file."""

    warnings: list[str] = []
    text = ""
    encoding_used = "utf-8"

    for encoding in ("utf-8", "utf-8-sig", "latin-1"):
        try:
            text = path.read_text(encoding=encoding)
            encoding_used = encoding
            break
        except UnicodeDecodeError:
            continue

    if not text.strip():
        warnings.append("Text file is empty or unreadable.")

    metadata = {
        "encoding": encoding_used,
        "line_count": text.count("\n") + 1 if text else 0,
    }
    return text, metadata, warnings
