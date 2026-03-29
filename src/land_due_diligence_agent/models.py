"""Typed data models shared across the ingestion and analysis pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class DocumentRecord:
    """Normalized representation of an extracted diligence document."""

    source_path: Path
    relative_path: Path
    extension: str
    title: str
    raw_text: str
    normalized_text: str
    metadata: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


@dataclass(slots=True)
class FileProcessingResult:
    """Outcome for a single file discovered during a run."""

    relative_path: str
    status: str
    warnings: list[str] = field(default_factory=list)
    error_message: str | None = None


@dataclass(slots=True)
class RiskFinding:
    """Structured finding for a diligence risk theme."""

    category: str
    severity: str
    summary: str
    evidence: list[str] = field(default_factory=list)
    issue: str = ""
    why_it_matters: str = ""
    likely_implication: str = ""
    source_documents: list[str] = field(default_factory=list)


@dataclass(slots=True)
class LLMCallFailure:
    """Structured details for a failed LLM refinement call."""

    stage: str
    target: str
    model: str
    detail: str


@dataclass(slots=True)
class ReadingRecommendation:
    """Suggested document reading sequence for deal review."""

    title: str
    relative_path: str
    priority: int
    reason: str
    confidence: str
    focus_areas: list[str] = field(default_factory=list)


@dataclass(slots=True)
class DocumentAnalysis:
    """Per-document analysis output."""

    document: DocumentRecord
    summary: str
    risks: list[RiskFinding]
    seller_questions: list[str]
    reading_priority: int
    reading_reason: str
    confidence: str
    confidence_reason: str
    focus_areas: list[str] = field(default_factory=list)
    missing_items: list[str] = field(default_factory=list)


@dataclass(slots=True)
class DealSynthesis:
    """Deal-level rollup assembled from all document analyses."""

    deal_name: str
    executive_summary: str
    entitlement_status: str
    key_risks: list[RiskFinding]
    recommended_reading_order: list[ReadingRecommendation]
    seller_questions: list[str]
    missing_items: list[str]
    category_rollup: dict[str, str]
    document_analyses: list[DocumentAnalysis]
    extraction_errors: list[str] = field(default_factory=list)
    llm_failures: list[LLMCallFailure] = field(default_factory=list)


@dataclass(slots=True)
class RunSummary:
    """Operational summary for a diligence CLI run."""

    run_id: str
    deal_name: str
    input_folder: str
    output_folder: str
    llm_provider: str
    started_at: str
    llm_model: str | None = None
    completed_at: str | None = None
    files_found: int = 0
    files_parsed_successfully: int = 0
    files_failed: int = 0
    output_files_created: list[str] = field(default_factory=list)
    file_results: list[FileProcessingResult] = field(default_factory=list)
    run_errors: list[str] = field(default_factory=list)
