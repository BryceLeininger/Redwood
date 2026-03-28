"""PDF extraction helpers."""

from __future__ import annotations

from pathlib import Path

from pypdf import PdfReader


def extract_pdf_text(path: Path) -> tuple[str, dict[str, int], list[str]]:
    """Extract page text from a PDF using text-layer parsing only."""

    reader = PdfReader(str(path))
    warnings: list[str] = []
    pages: list[str] = []

    for index, page in enumerate(reader.pages, start=1):
        try:
            page_text = (page.extract_text() or "").strip()
        except Exception as exc:  # pragma: no cover - third-party parser behavior
            warnings.append(f"Page {index} extraction failed: {exc}")
            continue

        if not page_text:
            warnings.append(f"Page {index} returned no text. OCR fallback may be required.")
            continue

        pages.append(f"[Page {index}]\n{page_text}")

    if not pages:
        warnings.append("No PDF text extracted.")

    return "\n\n".join(pages), {"page_count": len(reader.pages)}, warnings
