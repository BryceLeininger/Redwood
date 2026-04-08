"""Local deal-folder orchestration for due diligence document analysis."""

from __future__ import annotations

from collections import Counter
from datetime import datetime
from pathlib import Path

from land_due_diligence_agent.analysis.first_pass import build_issue_registry
from land_due_diligence_agent.classification import classify_document
from land_due_diligence_agent.config import Settings
from land_due_diligence_agent.deal_models import DealPaths, DealRunResult, ManifestEntry, ProcessedDocument
from land_due_diligence_agent.ingestion.discovery import discover_all_files, is_supported_document
from land_due_diligence_agent.output.deal_writer import (
    write_document_artifacts,
    write_failure_artifact,
    write_json,
    write_manifest_csv,
)
from land_due_diligence_agent.output.docx_writer import write_due_diligence_report_docx
from land_due_diligence_agent.parsing.service import parse_document
from land_due_diligence_agent.utils.files import ensure_directory
from land_due_diligence_agent.utils.logging import close_logging, configure_logging


def run_local_deal_pipeline(
    deal_folder: Path,
    *,
    settings: Settings,
    deal_name: str | None = None,
) -> tuple[DealRunResult, int]:
    """Run the local document workflow against one deal folder."""

    resolved_deal_folder = deal_folder.expanduser().resolve()
    if not resolved_deal_folder.exists():
        raise FileNotFoundError(f"Deal folder does not exist: {resolved_deal_folder}")
    if not resolved_deal_folder.is_dir():
        raise NotADirectoryError(f"Deal path is not a directory: {resolved_deal_folder}")

    run_id = datetime.now().astimezone().strftime("%Y%m%d_%H%M%S")
    deal_paths = _resolve_deal_paths(resolved_deal_folder, settings, run_id)
    run_log_path = deal_paths.output_dir / "run_log.txt"
    logger = configure_logging(settings.log_level, run_log_path)
    resolved_deal_name = deal_name or resolved_deal_folder.name

    result = DealRunResult(
        run_id=run_id,
        deal_name=resolved_deal_name,
        deal_paths=deal_paths,
        debug_mode=settings.debug_mode,
        run_log_path=str(run_log_path),
    )

    logger.info("Starting local due diligence run for '%s'.", resolved_deal_name)
    logger.info("Deal folder: %s", deal_paths.deal_folder)
    logger.info("Source drop: %s", deal_paths.source_drop_dir)
    logger.info("Metadata output: %s", deal_paths.metadata_dir)
    logger.info("Primary report output: %s", deal_paths.output_dir)
    if settings.debug_mode:
        logger.info("Debug extraction output: %s", deal_paths.text_run_dir)
        logger.info("Debug metadata snapshot: %s", deal_paths.metadata_run_dir)
        logger.info("Debug report snapshot: %s", deal_paths.output_run_dir)
    try:
        discovered_files = discover_all_files(deal_paths.source_drop_dir)
        result.files_discovered = len(discovered_files)

        if not discovered_files:
            logger.warning("No files were found under %s.", deal_paths.source_drop_dir)

        manifest_entries: list[ManifestEntry] = []
        processed_documents: list[ProcessedDocument] = []

        for file_path in discovered_files:
            manifest_entry = _build_manifest_entry(file_path, deal_paths.source_drop_dir)
            manifest_entries.append(manifest_entry)
            logger.info("Discovered %s", manifest_entry.relative_path)

            if not manifest_entry.supported:
                manifest_entry.extraction_status = "unsupported"
                manifest_entry.notes.append("Unsupported file type; preserved in place and skipped.")
                result.unsupported_files += 1
                continue

            result.supported_files += 1
            try:
                document = parse_document(file_path, deal_paths.source_drop_dir)
                classification = classify_document(file_path, document.normalized_text)
                text_path = None
                json_path = None
                if settings.debug_mode:
                    text_path, json_path = write_document_artifacts(deal_paths.text_run_dir, document, classification)

                manifest_entry.document_type_guess = classification.document_type_guess
                manifest_entry.category = classification.category
                manifest_entry.classification_confidence = classification.confidence
                manifest_entry.ocr_used = bool(document.ocr_pages)
                manifest_entry.ocr_pages = document.ocr_pages.copy()
                manifest_entry.extraction_status = "success"
                manifest_entry.notes.extend(document.warnings)
                manifest_entry.extracted_text_path = str(text_path) if text_path is not None else None
                manifest_entry.structured_text_path = str(json_path) if json_path is not None else None

                processed_documents.append(
                    ProcessedDocument(
                        document=document,
                        classification=classification,
                        manifest_entry=manifest_entry,
                    )
                )
                result.extracted_files += 1
                if document.ocr_pages:
                    result.ocr_files += 1
                if document.warnings:
                    logger.warning("Parsed %s with warnings: %s", manifest_entry.relative_path, "; ".join(document.warnings))
                else:
                    logger.info("Parsed %s successfully.", manifest_entry.relative_path)
            except Exception as exc:
                classification = classify_document(file_path)
                manifest_entry.document_type_guess = classification.document_type_guess
                manifest_entry.category = classification.category
                manifest_entry.classification_confidence = classification.confidence
                manifest_entry.extraction_status = "failed"
                error_message = f"{type(exc).__name__}: {exc}"
                manifest_entry.errors.append(error_message)
                failure_artifact_path = write_failure_artifact(
                    deal_paths.text_run_dir,
                    Path(manifest_entry.relative_path),
                    error_message,
                )
                manifest_entry.notes.append(
                    f"Failure artifact: {failure_artifact_path.relative_to(deal_paths.deal_folder).as_posix()}"
                )
                result.failed_files += 1
                logger.exception("Failed to parse %s", manifest_entry.relative_path)

        result.manifest_entries = manifest_entries
        result.processed_documents = processed_documents
        result.category_counts = dict(
            sorted(
                Counter(
                    processed.classification.category
                    for processed in processed_documents
                    if processed.classification.category != "Miscellaneous"
                ).items()
            )
        )
        result.issue_registry = build_issue_registry(processed_documents, manifest_entries)

        _write_run_artifacts(result)

        logger.info(
            "Run complete: %d discovered, %d extracted, %d failed, %d unsupported.",
            result.files_discovered,
            result.extracted_files,
            result.failed_files,
            result.unsupported_files,
        )
        logger.info("Manifest JSON: %s", result.manifest_json_path)
        logger.info("Issue registry JSON: %s", result.issue_registry_path)
        logger.info("Due diligence review: %s", result.review_report_path)
        logger.info("Run log: %s", result.run_log_path)

        exit_code = 0 if result.extracted_files > 0 else 1
        return result, exit_code
    finally:
        close_logging(logger)


def _resolve_deal_paths(deal_folder: Path, settings: Settings, run_id: str) -> DealPaths:
    source_drop_dir = deal_folder / settings.deal_source_subdir
    if not source_drop_dir.exists():
        raise FileNotFoundError(
            f"The deal folder does not contain {settings.deal_source_subdir}: {source_drop_dir}"
        )
    if not source_drop_dir.is_dir():
        raise NotADirectoryError(
            f"The source drop path is not a directory: {source_drop_dir}"
        )

    working_dir = ensure_directory(deal_folder / settings.deal_working_subdir)
    text_extraction_dir = ensure_directory(deal_folder / settings.text_extraction_subdir)
    metadata_dir = ensure_directory(deal_folder / settings.metadata_subdir)
    output_dir = ensure_directory(deal_folder / settings.report_output_subdir)

    if settings.debug_mode:
        text_run_dir = ensure_directory(text_extraction_dir / run_id)
        metadata_run_dir = ensure_directory(metadata_dir / run_id)
        output_run_dir = ensure_directory(output_dir / run_id)
    else:
        text_run_dir = text_extraction_dir
        metadata_run_dir = metadata_dir
        output_run_dir = output_dir

    return DealPaths(
        deal_folder=deal_folder,
        source_drop_dir=source_drop_dir,
        working_dir=working_dir,
        text_extraction_dir=text_extraction_dir,
        metadata_dir=metadata_dir,
        output_dir=output_dir,
        text_run_dir=text_run_dir,
        metadata_run_dir=metadata_run_dir,
        output_run_dir=output_run_dir,
    )


def _build_manifest_entry(file_path: Path, source_root: Path) -> ManifestEntry:
    classification = classify_document(file_path)
    stats = file_path.stat()
    return ManifestEntry(
        file_path=str(file_path),
        relative_path=file_path.relative_to(source_root).as_posix(),
        file_name=file_path.name,
        extension=file_path.suffix.lower(),
        size_bytes=stats.st_size,
        last_modified=datetime.fromtimestamp(stats.st_mtime).astimezone().isoformat(timespec="seconds"),
        supported=is_supported_document(file_path),
        document_type_guess=classification.document_type_guess,
        category=classification.category,
        classification_confidence=classification.confidence,
        ocr_used=False,
    )


def _write_run_artifacts(result: DealRunResult) -> None:
    manifest_json_path = result.deal_paths.metadata_dir / "deal_manifest.json"
    manifest_csv_path = result.deal_paths.metadata_dir / "deal_manifest.csv"
    issue_registry_path = result.deal_paths.metadata_dir / "issue_registry.json"
    run_summary_path = result.deal_paths.metadata_dir / "run_summary.json"
    review_report_path = result.deal_paths.output_dir / "Due_Diligence_Review.docx"

    result.manifest_json_path = str(manifest_json_path)
    result.manifest_csv_path = str(manifest_csv_path)
    result.issue_registry_path = str(issue_registry_path)
    result.run_summary_path = str(run_summary_path)
    result.latest_run_path = ""
    result.review_report_path = str(review_report_path)

    manifest_payload = {
        "run_id": result.run_id,
        "deal_name": result.deal_name,
        "source_drop_dir": str(result.deal_paths.source_drop_dir),
        "file_count": result.files_discovered,
        "files": result.manifest_entries,
    }
    issue_registry_payload = {
        "run_id": result.run_id,
        "deal_name": result.deal_name,
        "facts": result.issue_registry.facts,
        "conflicts": result.issue_registry.conflicts,
        "missing_items": result.issue_registry.missing_items,
        "seller_questions": result.issue_registry.seller_questions,
    }

    write_json(manifest_json_path, manifest_payload)
    write_manifest_csv(manifest_csv_path, result.manifest_entries)
    write_json(issue_registry_path, issue_registry_payload)

    summary_payload = {
        "run_id": result.run_id,
        "deal_name": result.deal_name,
        "deal_folder": str(result.deal_paths.deal_folder),
        "source_drop_dir": str(result.deal_paths.source_drop_dir),
        "text_extraction_dir": str(result.deal_paths.text_extraction_dir),
        "metadata_dir": str(result.deal_paths.metadata_dir),
        "report_dir": str(result.deal_paths.output_dir),
        "debug_mode": result.debug_mode,
        "files_discovered": result.files_discovered,
        "supported_files": result.supported_files,
        "extracted_files": result.extracted_files,
        "failed_files": result.failed_files,
        "unsupported_files": result.unsupported_files,
        "ocr_files": result.ocr_files,
        "category_counts": result.category_counts,
        "run_log_path": result.run_log_path,
        "manifest_json_path": result.manifest_json_path,
        "manifest_csv_path": result.manifest_csv_path,
        "issue_registry_path": result.issue_registry_path,
        "debug_text_artifact_dir": str(result.deal_paths.text_run_dir) if result.debug_mode else None,
        "debug_metadata_snapshot_dir": str(result.deal_paths.metadata_run_dir) if result.debug_mode else None,
        "debug_output_snapshot_dir": str(result.deal_paths.output_run_dir) if result.debug_mode else None,
        "review_report_path": result.review_report_path,
    }
    write_json(run_summary_path, summary_payload)
    if result.debug_mode:
        write_json(result.deal_paths.metadata_run_dir / "deal_manifest.json", manifest_payload)
        write_manifest_csv(result.deal_paths.metadata_run_dir / "deal_manifest.csv", result.manifest_entries)
        write_json(result.deal_paths.metadata_run_dir / "issue_registry.json", issue_registry_payload)
        write_json(result.deal_paths.metadata_run_dir / "run_summary.json", summary_payload)

    write_due_diligence_report_docx(review_report_path, result)
    if result.debug_mode:
        write_due_diligence_report_docx(result.deal_paths.output_run_dir / "Due_Diligence_Review.docx", result)