"""Typed models for the local deal-folder workflow."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from land_due_diligence_agent.models import DocumentRecord


@dataclass(slots=True, frozen=True)
class DealPaths:
    """Resolved deal-folder paths for one local run."""

    deal_folder: Path
    source_drop_dir: Path
    working_dir: Path
    text_extraction_dir: Path
    metadata_dir: Path
    output_dir: Path
    text_run_dir: Path
    metadata_run_dir: Path
    output_run_dir: Path


@dataclass(slots=True)
class ClassificationResult:
    """Best-effort DD category classification for one document."""

    category: str
    document_type_guess: str
    confidence: str
    matched_keywords: list[str] = field(default_factory=list)


@dataclass(slots=True, frozen=True)
class SourceReference:
    """Traceable source location for a fact or conflict."""

    relative_path: str
    page_number: int | None = None
    chunk_id: str | None = None
    excerpt: str = ""


@dataclass(slots=True)
class ManifestEntry:
    """File-level manifest record for one discovered document."""

    file_path: str
    relative_path: str
    file_name: str
    extension: str
    size_bytes: int
    last_modified: str
    supported: bool
    document_type_guess: str
    category: str
    classification_confidence: str
    ocr_used: bool
    ocr_pages: list[int] = field(default_factory=list)
    extraction_status: str = "pending"
    notes: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    extracted_text_path: str | None = None
    structured_text_path: str | None = None


@dataclass(slots=True)
class ProcessedDocument:
    """Parsed document plus its manifest and classification metadata."""

    document: DocumentRecord
    classification: ClassificationResult
    manifest_entry: ManifestEntry


@dataclass(slots=True)
class FactRecord:
    """Traceable extracted fact or evidence-backed package signal."""

    fact_id: str
    fact_type: str
    label: str
    value: str
    normalized_value: str
    statement: str
    category: str
    confidence: str
    sources: list[SourceReference] = field(default_factory=list)
    uncertainty: str = ""


@dataclass(slots=True)
class ConflictRecord:
    """Cross-document contradiction or mismatch detected from extracted facts."""

    conflict_id: str
    fact_type: str
    label: str
    description: str
    values: list[str] = field(default_factory=list)
    sources: list[SourceReference] = field(default_factory=list)
    uncertainty: str = ""


@dataclass(slots=True)
class MissingItem:
    """Expected DD item or key fact that was not located in the package."""

    item_id: str
    label: str
    category: str
    reason: str
    suggested_request: str
    confidence: str = "medium"


@dataclass(slots=True)
class SellerQuestion:
    """Traceable follow-up question generated from missing data or conflicts."""

    question_id: str
    question: str
    reason: str
    related_item_ids: list[str] = field(default_factory=list)
    sources: list[SourceReference] = field(default_factory=list)


@dataclass(slots=True)
class IssueRegistry:
    """Structured first-pass DD registry for downstream review workflows."""

    facts: list[FactRecord] = field(default_factory=list)
    conflicts: list[ConflictRecord] = field(default_factory=list)
    missing_items: list[MissingItem] = field(default_factory=list)
    seller_questions: list[SellerQuestion] = field(default_factory=list)


@dataclass(slots=True)
class DealRunResult:
    """Top-level result bundle for one local deal run."""

    run_id: str
    deal_name: str
    deal_paths: DealPaths
    debug_mode: bool = False
    manifest_entries: list[ManifestEntry] = field(default_factory=list)
    processed_documents: list[ProcessedDocument] = field(default_factory=list)
    issue_registry: IssueRegistry = field(default_factory=IssueRegistry)
    category_counts: dict[str, int] = field(default_factory=dict)
    files_discovered: int = 0
    supported_files: int = 0
    extracted_files: int = 0
    failed_files: int = 0
    unsupported_files: int = 0
    ocr_files: int = 0
    review_report_path: str = ""
    run_log_path: str = ""
    manifest_json_path: str = ""
    manifest_csv_path: str = ""
    issue_registry_path: str = ""
    run_summary_path: str = ""
    latest_run_path: str = ""