"""Artifact writers for the local deal-folder workflow."""

from __future__ import annotations

import csv
import json
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any

from land_due_diligence_agent.deal_models import ClassificationResult, DealRunResult, ManifestEntry, SourceReference
from land_due_diligence_agent.models import DocumentRecord
from land_due_diligence_agent.utils.files import ensure_directory


def write_json(path: Path, payload: Any) -> Path:
    """Write a JSON artifact with stable formatting."""

    ensure_directory(path.parent)
    path.write_text(json.dumps(_serialize(payload), indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def write_manifest_csv(path: Path, manifest_entries: list[ManifestEntry]) -> Path:
    """Write the deal manifest to CSV for spreadsheet review."""

    ensure_directory(path.parent)
    fieldnames = [
        "file_path",
        "relative_path",
        "file_name",
        "extension",
        "size_bytes",
        "last_modified",
        "supported",
        "document_type_guess",
        "category",
        "classification_confidence",
        "ocr_used",
        "ocr_pages",
        "extraction_status",
        "notes",
        "errors",
        "extracted_text_path",
        "structured_text_path",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for entry in manifest_entries:
            writer.writerow(
                {
                    "file_path": entry.file_path,
                    "relative_path": entry.relative_path,
                    "file_name": entry.file_name,
                    "extension": entry.extension,
                    "size_bytes": entry.size_bytes,
                    "last_modified": entry.last_modified,
                    "supported": entry.supported,
                    "document_type_guess": entry.document_type_guess,
                    "category": entry.category,
                    "classification_confidence": entry.classification_confidence,
                    "ocr_used": entry.ocr_used,
                    "ocr_pages": ", ".join(str(page) for page in entry.ocr_pages),
                    "extraction_status": entry.extraction_status,
                    "notes": " | ".join(entry.notes),
                    "errors": " | ".join(entry.errors),
                    "extracted_text_path": entry.extracted_text_path or "",
                    "structured_text_path": entry.structured_text_path or "",
                }
            )
    return path


def write_document_artifacts(
    output_root: Path,
    document: DocumentRecord,
    classification: ClassificationResult,
) -> tuple[Path, Path]:
    """Write extracted text and structured JSON for one document."""

    relative_parent = document.relative_path.parent
    text_path = output_root / relative_parent / f"{document.source_path.name}.txt"
    json_path = output_root / relative_parent / f"{document.source_path.name}.json"
    ensure_directory(text_path.parent)
    text_path.write_text(document.raw_text or document.normalized_text, encoding="utf-8")

    payload = {
        "source_path": str(document.source_path),
        "relative_path": document.relative_path.as_posix(),
        "file_name": document.source_path.name,
        "document_type_guess": classification.document_type_guess,
        "category": classification.category,
        "classification_confidence": classification.confidence,
        "matched_keywords": classification.matched_keywords,
        "metadata": document.metadata,
        "warnings": document.warnings,
        "ocr_pages": document.ocr_pages,
        "ocr_recovered_pages": document.ocr_recovered_pages,
        "chunks": [
            {
                "chunk_id": chunk.chunk_id,
                "page_number": chunk.page_number,
                "ocr_used": chunk.ocr_used,
                "text": chunk.text,
            }
            for chunk in document.chunks
        ],
    }
    write_json(json_path, payload)
    return text_path, json_path


def write_review_markdown(path: Path, result: DealRunResult) -> Path:
    """Write the first-pass markdown review."""

    ensure_directory(path.parent)
    path.write_text(_build_review_markdown(result), encoding="utf-8")
    return path


def _build_review_markdown(result: DealRunResult) -> str:
    lines = [
        "# First-Pass Due Diligence Review",
        "",
        f"- Deal: {result.deal_name}",
        f"- Run ID: `{result.run_id}`",
        f"- Deal Folder: `{result.deal_paths.deal_folder}`",
        f"- Source Drop: `{result.deal_paths.source_drop_dir}`",
        f"- Extracted Text Folder: `{result.deal_paths.text_run_dir}`",
        f"- Metadata Folder: `{result.deal_paths.metadata_run_dir}`",
        f"- Report Folder: `{result.deal_paths.output_run_dir}`",
        "",
        "## Package Summary",
        "",
        f"- Files discovered: {result.files_discovered}",
        f"- Supported files: {result.supported_files}",
        f"- Extracted successfully: {result.extracted_files}",
        f"- Failed extraction: {result.failed_files}",
        f"- Unsupported files: {result.unsupported_files}",
        f"- OCR fallback used on: {result.ocr_files} file(s)",
        "",
        "This is a first-pass, document-bound review. Facts below are limited to extracted text from the provided package. If an item is missing, conflicted, or low-confidence, that is stated explicitly.",
        "",
        "## Category Coverage",
        "",
    ]

    if result.category_counts:
        for category, count in sorted(result.category_counts.items()):
            lines.append(f"- {category}: {count}")
    else:
        lines.append("- No successfully extracted documents were classified into DD categories.")

    lines.extend(["", "## Facts", ""])
    if result.issue_registry.facts:
        for fact in result.issue_registry.facts:
            lines.append(
                f"- {fact.statement} Confidence: {fact.confidence}. Sources: {_format_sources(fact.sources)}"
            )
            if fact.uncertainty:
                lines.append(f"  Uncertainty: {fact.uncertainty}")
    else:
        lines.append("- No structured facts were extracted from the provided documents.")

    lines.extend(["", "## Conflicts / Contradictions", ""])
    if result.issue_registry.conflicts:
        for conflict in result.issue_registry.conflicts:
            lines.append(
                f"- {conflict.description} Sources: {_format_sources(conflict.sources)}"
            )
            if conflict.uncertainty:
                lines.append(f"  Uncertainty: {conflict.uncertainty}")
    else:
        lines.append("- No explicit contradiction was detected across the extracted fact set. This does not confirm the package is internally consistent.")

    lines.extend(["", "## Not Found In Provided Documents", ""])
    if result.issue_registry.missing_items:
        for item in result.issue_registry.missing_items:
            lines.append(f"- {item.label}: {item.reason}")
    else:
        lines.append("- No major missing DD lane was flagged from the current rule set.")

    lines.extend(["", "## Seller Questions", ""])
    if result.issue_registry.seller_questions:
        for question in result.issue_registry.seller_questions:
            lines.append(f"- {question.question}")
            lines.append(f"  Reason: {question.reason}")
            if question.sources:
                lines.append(f"  Sources: {_format_sources(question.sources)}")
    else:
        lines.append("- No seller follow-up question was generated from the current rule set.")

    extraction_issues = [
        entry
        for entry in result.manifest_entries
        if entry.extraction_status in {"failed", "unsupported"}
    ]
    lines.extend(["", "## Extraction Watchlist", ""])
    if extraction_issues:
        for entry in extraction_issues:
            detail = f"- {entry.relative_path}: {entry.extraction_status}"
            notes = entry.errors or entry.notes
            if notes:
                detail += f". {'; '.join(notes)}"
            lines.append(detail)
    else:
        lines.append("- No unsupported or failed files were recorded in this run.")

    lines.extend(
        [
            "",
            "## Traceability",
            "",
            f"- Deal manifest JSON: `{result.manifest_json_path}`",
            f"- Deal manifest CSV: `{result.manifest_csv_path}`",
            f"- Issue registry JSON: `{result.issue_registry_path}`",
            f"- Run summary JSON: `{result.run_summary_path}`",
        ]
    )

    return "\n".join(lines) + "\n"


def _format_sources(sources: list[SourceReference]) -> str:
    if not sources:
        return "not available"

    formatted: list[str] = []
    for source in sources[:4]:
        detail = source.relative_path
        if source.page_number is not None:
            detail += f" | page {source.page_number}"
        elif source.chunk_id:
            detail += f" | {source.chunk_id}"
        if source.excerpt:
            detail += f" | \"{source.excerpt}\""
        formatted.append(detail)
    return "; ".join(formatted)


def _serialize(value: Any) -> Any:
    if is_dataclass(value):
        return {key: _serialize(item) for key, item in asdict(value).items()}
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _serialize(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_serialize(item) for item in value]
    if isinstance(value, tuple):
        return [_serialize(item) for item in value]
    return value