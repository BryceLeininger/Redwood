"""Plain-text and Markdown extraction helpers."""

from __future__ import annotations

from pathlib import Path


def extract_text_file(path: Path) -> tuple[str, dict[str, str | int], list[str], list[dict[str, str | int | None]]]:
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

    paragraphs = [paragraph.strip() for paragraph in text.split("\n\n") if paragraph.strip()]
    chunk_records = [
        {
            "chunk_id": f"paragraph-{index:04d}",
            "page_number": None,
            "text": paragraph,
        }
        for index, paragraph in enumerate(paragraphs, start=1)
    ]
    if not chunk_records and text.strip():
        chunk_records.append(
            {
                "chunk_id": "paragraph-0001",
                "page_number": None,
                "text": text.strip(),
            }
        )

    metadata = {
        "encoding": encoding_used,
        "line_count": text.count("\n") + 1 if text else 0,
    }
    return text, metadata, warnings, chunk_records
