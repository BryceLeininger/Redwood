"""Dispatch file parsing to the appropriate extractor."""

from __future__ import annotations

from pathlib import Path

from land_due_diligence_agent.models import DocumentRecord
from land_due_diligence_agent.parsing.docx_parser import extract_docx_text
from land_due_diligence_agent.parsing.pdf_parser import extract_pdf_text
from land_due_diligence_agent.parsing.spreadsheet_parser import extract_csv_text, extract_xlsx_text
from land_due_diligence_agent.parsing.text_parser import extract_text_file
from land_due_diligence_agent.utils.files import humanize_filename
from land_due_diligence_agent.utils.text import normalize_text


_PARSERS = {
    ".pdf": extract_pdf_text,
    ".docx": extract_docx_text,
    ".xlsx": extract_xlsx_text,
    ".csv": extract_csv_text,
    ".txt": extract_text_file,
    ".md": extract_text_file,
}


def parse_document(path: Path, input_root: Path) -> DocumentRecord:
    """Parse a supported file into a normalized document record."""

    suffix = path.suffix.lower()
    parser = _PARSERS.get(suffix)
    if parser is None:
        raise ValueError(f"Unsupported file type: {path.suffix}")

    raw_text, metadata, warnings = parser(path)
    normalized = normalize_text(raw_text)

    if not normalized:
        warnings.append("Normalized text is empty after extraction.")

    return DocumentRecord(
        source_path=path,
        relative_path=path.relative_to(input_root),
        extension=suffix,
        title=humanize_filename(path.stem),
        raw_text=raw_text,
        normalized_text=normalized,
        metadata=metadata,
        warnings=warnings,
    )
