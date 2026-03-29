"""Dispatch file parsing to the appropriate extractor."""

from __future__ import annotations

from pathlib import Path

from land_due_diligence_agent.models import DocumentRecord, ExtractedChunk
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

    raw_text, metadata, warnings, chunk_records = parser(path)
    normalized = normalize_text(raw_text)
    title = humanize_filename(path.stem)
    chunks = _build_chunks(title, chunk_records)
    ocr_pages = [
        page
        for page in metadata.get("ocr_pages", [])
        if isinstance(page, int)
    ]
    ocr_recovered_pages = [
        page
        for page in metadata.get("ocr_recovered_pages", [])
        if isinstance(page, int)
    ]

    if not normalized:
        warnings.append("Normalized text is empty after extraction.")
    elif not chunks:
        chunks.append(
            ExtractedChunk(
                document_name=title,
                chunk_id="chunk-0001",
                text=normalized,
                page_number=None,
            )
        )

    metadata = dict(metadata)
    metadata["chunk_count"] = len(chunks)

    return DocumentRecord(
        source_path=path,
        relative_path=path.relative_to(input_root),
        extension=suffix,
        title=title,
        raw_text=raw_text,
        normalized_text=normalized,
        metadata=metadata,
        warnings=warnings,
        chunks=chunks,
        ocr_pages=ocr_pages,
        ocr_recovered_pages=ocr_recovered_pages,
    )


def _build_chunks(title: str, chunk_records: list[dict[str, str | int | None]]) -> list[ExtractedChunk]:
    chunks: list[ExtractedChunk] = []
    for index, record in enumerate(chunk_records, start=1):
        text = normalize_text(str(record.get("text") or ""))
        if not text:
            continue
        chunk_id = str(record.get("chunk_id") or f"chunk-{index:04d}")
        page_number = record.get("page_number")
        chunks.append(
            ExtractedChunk(
                document_name=title,
                chunk_id=chunk_id,
                text=text,
                page_number=page_number if isinstance(page_number, int) else None,
                ocr_used=bool(record.get("ocr_used")),
            )
        )
    return chunks
