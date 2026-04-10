"""Stable extraction cache helpers for local deal-folder runs."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from land_due_diligence_agent.deal_models import ClassificationResult
from land_due_diligence_agent.models import DocumentRecord, ExtractedChunk
from land_due_diligence_agent.utils.files import ensure_directory, humanize_filename
from land_due_diligence_agent.utils.text import normalize_text


_CACHE_SCHEMA_VERSION = 1


@dataclass(slots=True, frozen=True)
class CachedParse:
    document: DocumentRecord
    classification: ClassificationResult
    file_hash: str
    text_path: Path
    metadata_path: Path


def load_cached_parse(path: Path, input_root: Path, cache_root: Path) -> CachedParse | None:
    """Load a cached parse result when the source file is unchanged."""

    relative_path = path.relative_to(input_root)
    text_path, metadata_path = _cache_paths(cache_root, relative_path)
    if not text_path.exists() or not metadata_path.exists():
        return None

    try:
        payload = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None

    if payload.get("cache_schema_version") != _CACHE_SCHEMA_VERSION:
        return None

    stats = path.stat()
    if payload.get("source_size_bytes") != stats.st_size:
        return None
    if payload.get("source_mtime_ns") != stats.st_mtime_ns:
        return None

    try:
        raw_text = text_path.read_text(encoding="utf-8")
    except OSError:
        return None

    normalized_text = str(payload.get("normalized_text") or normalize_text(raw_text))
    chunks = _deserialize_chunks(str(payload.get("title") or humanize_filename(path.stem)), payload.get("chunks") or [])
    document = DocumentRecord(
        source_path=path,
        relative_path=relative_path,
        extension=path.suffix.lower(),
        title=str(payload.get("title") or humanize_filename(path.stem)),
        raw_text=raw_text,
        normalized_text=normalized_text,
        metadata=dict(payload.get("metadata") or {}),
        warnings=[str(item) for item in payload.get("warnings") or []],
        chunks=chunks,
        ocr_pages=[int(page) for page in payload.get("ocr_pages") or [] if isinstance(page, int)],
        ocr_recovered_pages=[int(page) for page in payload.get("ocr_recovered_pages") or [] if isinstance(page, int)],
    )
    classification_payload = dict(payload.get("classification") or {})
    classification = ClassificationResult(
        category=str(classification_payload.get("category") or "Miscellaneous"),
        document_type_guess=str(classification_payload.get("document_type_guess") or humanize_filename(path.stem)),
        confidence=str(classification_payload.get("confidence") or "low"),
        matched_keywords=[str(item) for item in classification_payload.get("matched_keywords") or []],
    )
    return CachedParse(
        document=document,
        classification=classification,
        file_hash=str(payload.get("file_hash") or ""),
        text_path=text_path,
        metadata_path=metadata_path,
    )


def save_cached_parse(
    *,
    path: Path,
    input_root: Path,
    cache_root: Path,
    document: DocumentRecord,
    classification: ClassificationResult,
    file_hash: str,
) -> tuple[Path, Path]:
    """Persist a parsed document so future unchanged runs can skip extraction."""

    relative_path = path.relative_to(input_root)
    text_path, metadata_path = _cache_paths(cache_root, relative_path)
    ensure_directory(text_path.parent)
    raw_text = document.raw_text or document.normalized_text
    text_path.write_text(raw_text, encoding="utf-8")

    stats = path.stat()
    payload: dict[str, Any] = {
        "cache_schema_version": _CACHE_SCHEMA_VERSION,
        "source_path": str(path),
        "relative_path": relative_path.as_posix(),
        "source_size_bytes": stats.st_size,
        "source_mtime_ns": stats.st_mtime_ns,
        "source_last_modified": datetime.fromtimestamp(stats.st_mtime).astimezone().isoformat(timespec="seconds"),
        "file_hash": file_hash,
        "title": document.title,
        "normalized_text": document.normalized_text,
        "metadata": document.metadata,
        "warnings": document.warnings,
        "ocr_pages": document.ocr_pages,
        "ocr_recovered_pages": document.ocr_recovered_pages,
        "ocr_used": bool(document.ocr_pages),
        "extracted_text_path": str(text_path),
        "classification": {
            "category": classification.category,
            "document_type_guess": classification.document_type_guess,
            "confidence": classification.confidence,
            "matched_keywords": classification.matched_keywords,
        },
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
    metadata_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return text_path, metadata_path


def compute_file_hash(path: Path, *, chunk_size: int = 1024 * 1024) -> str:
    """Compute a stable content hash for a source file."""

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _cache_paths(cache_root: Path, relative_path: Path) -> tuple[Path, Path]:
    text_path = cache_root / relative_path.parent / f"{relative_path.name}.txt"
    metadata_path = cache_root / relative_path.parent / f"{relative_path.name}.json"
    return text_path, metadata_path


def _deserialize_chunks(title: str, payload: list[dict[str, Any]]) -> list[ExtractedChunk]:
    chunks: list[ExtractedChunk] = []
    for index, record in enumerate(payload, start=1):
        text = normalize_text(str(record.get("text") or ""))
        if not text:
            continue
        page_number = record.get("page_number")
        chunks.append(
            ExtractedChunk(
                document_name=title,
                chunk_id=str(record.get("chunk_id") or f"chunk-{index:04d}"),
                text=text,
                page_number=page_number if isinstance(page_number, int) else None,
                ocr_used=bool(record.get("ocr_used")),
            )
        )
    return chunks