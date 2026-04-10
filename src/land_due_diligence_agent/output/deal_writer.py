"""Artifact writers for the local deal-folder workflow."""

from __future__ import annotations

import csv
import json
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any

from land_due_diligence_agent.deal_models import ClassificationResult, ManifestEntry
from land_due_diligence_agent.models import DocumentRecord
from land_due_diligence_agent.utils.files import ensure_directory


def write_json(path: Path, payload: Any) -> Path:
    """Write a JSON artifact with stable formatting."""

    ensure_directory(path.parent)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_serialize(payload), indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def write_manifest_csv(path: Path, manifest_entries: list[ManifestEntry]) -> Path:
    """Write the deal manifest to CSV for spreadsheet review."""

    ensure_directory(path.parent)
    path.parent.mkdir(parents=True, exist_ok=True)
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
        "file_hash",
        "cache_hit",
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
                    "file_hash": entry.file_hash,
                    "cache_hit": entry.cache_hit,
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
    text_path.parent.mkdir(parents=True, exist_ok=True)
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


def write_failure_artifact(output_root: Path, relative_path: Path, error_message: str) -> Path:
    """Write a small failure artifact when extraction fails."""

    failure_path = output_root / "failed" / relative_path.parent / f"{relative_path.name}.error.txt"
    ensure_directory(failure_path.parent)
    failure_path.parent.mkdir(parents=True, exist_ok=True)
    failure_path.write_text(error_message.strip() + "\n", encoding="utf-8")
    return failure_path


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