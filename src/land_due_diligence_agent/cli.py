"""CLI entry point for the land due diligence agent."""

from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

from land_due_diligence_agent.analysis.precedents import ingest_reviewer_feedback_files
from land_due_diligence_agent.analysis.service import run_analysis
from land_due_diligence_agent.config import Settings
from land_due_diligence_agent.ingestion.discovery import discover_documents
from land_due_diligence_agent.llm.factory import build_llm_provider
from land_due_diligence_agent.models import FileProcessingResult, RunSummary
from land_due_diligence_agent.output.markdown_writer import write_markdown_outputs
from land_due_diligence_agent.parsing.service import parse_document
from land_due_diligence_agent.utils.files import ensure_directory, slugify
from land_due_diligence_agent.utils.logging import configure_logging


def build_parser() -> argparse.ArgumentParser:
    """Create the CLI argument parser."""

    parser = argparse.ArgumentParser(
        description="Analyze a folder of land acquisition due diligence files and write Markdown outputs.",
    )
    parser.add_argument("--input-folder", required=True, help="Folder containing PDF, DOCX, XLSX, CSV, TXT, or MD files.")
    parser.add_argument(
        "--output-folder",
        help="Base output folder. Defaults to DEFAULT_OUTPUT_DIR from .env or data/output.",
    )
    parser.add_argument("--deal-name", help="Optional deal name for the output folder and report headings.")
    parser.add_argument(
        "--mode",
        choices=("fast", "full"),
        default="fast",
        help="Analysis depth. Fast mode is the default quick-read path; full mode runs the full decision-grade workflow.",
    )
    parser.add_argument(
        "--llm-provider",
        choices=("heuristic", "openai"),
        help="Override the LLM provider configured in the environment.",
    )
    parser.add_argument("--log-level", help="Override the configured log level, e.g. INFO or DEBUG.")
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run the diligence pipeline."""

    parser = build_parser()
    args = parser.parse_args(argv)

    settings = Settings.from_env().with_overrides(
        llm_provider=args.llm_provider,
        log_level=args.log_level,
    )

    input_folder = Path(args.input_folder).expanduser().resolve()
    deal_name = args.deal_name or input_folder.name
    output_root = Path(args.output_folder or settings.default_output_dir).expanduser().resolve()
    started_at = datetime.now().astimezone()
    run_id = started_at.strftime("%Y%m%d_%H%M%S")
    run_output_dir = ensure_directory(output_root / slugify(deal_name) / run_id)
    logger = configure_logging(settings.log_level, run_output_dir / "run.log")
    run_summary = RunSummary(
        run_id=run_id,
        deal_name=deal_name,
        input_folder=str(input_folder),
        output_folder=str(run_output_dir),
        llm_provider=settings.llm_provider,
        llm_model=settings.openai_model if settings.llm_provider == "openai" else None,
        started_at=started_at.isoformat(timespec="seconds"),
        analysis_mode=args.mode,
    )

    logger.info("Starting diligence review for '%s'.", deal_name)
    logger.info("Run ID: %s", run_id)
    logger.info("Input folder: %s", input_folder)
    logger.info("Output folder: %s", run_output_dir)
    logger.info("Analysis mode: %s", run_summary.analysis_mode)

    try:
        document_paths = discover_documents(input_folder)
    except Exception as exc:
        logger.error("Unable to load input folder: %s", exc)
        run_summary.run_errors.append(f"Unable to load input folder: {type(exc).__name__}: {exc}")
        run_summary.completed_at = datetime.now().astimezone().isoformat(timespec="seconds")
        write_markdown_outputs(run_output_dir, run_summary=run_summary)
        return 1

    run_summary.files_found = len(document_paths)
    logger.info("Found %d supported file(s) for ingestion.", len(document_paths))

    if not document_paths:
        logger.error("No supported documents were found in %s", input_folder)
        run_summary.run_errors.append("No supported documents were found in the input folder.")
        run_summary.completed_at = datetime.now().astimezone().isoformat(timespec="seconds")
        write_markdown_outputs(run_output_dir, run_summary=run_summary)
        return 1

    parsed_documents = []
    extraction_errors: list[str] = []

    for path in document_paths:
        relative_path = path.relative_to(input_folder).as_posix()
        try:
            document = parse_document(path, input_folder)
            parsed_documents.append(document)
            run_summary.file_results.append(
                FileProcessingResult(
                    relative_path=relative_path,
                    status="parsed",
                    warnings=document.warnings.copy(),
                    ocr_pages=document.ocr_pages.copy(),
                    ocr_recovered_pages=document.ocr_recovered_pages.copy(),
                )
            )
            if document.warnings:
                message = f"Parsed {relative_path}"
                if document.ocr_pages:
                    message += f" with OCR on page(s): {', '.join(str(page) for page in document.ocr_pages)}"
                message += f" | warnings: {'; '.join(document.warnings)}"
                logger.warning(message)
            elif document.ocr_pages:
                logger.info(
                    "Parsed %s with OCR on page(s): %s.",
                    relative_path,
                    ", ".join(str(page) for page in document.ocr_pages),
                )
            else:
                logger.info("Parsed %s successfully.", relative_path)
        except Exception as exc:
            logger.exception("Failed to parse %s", relative_path)
            error_message = f"{type(exc).__name__}: {exc}"
            extraction_errors.append(f"{relative_path}: {error_message}")
            run_summary.file_results.append(
                FileProcessingResult(
                    relative_path=relative_path,
                    status="failed",
                    error_message=error_message,
                )
            )

    run_summary.files_parsed_successfully = sum(result.status == "parsed" for result in run_summary.file_results)
    run_summary.files_failed = sum(result.status == "failed" for result in run_summary.file_results)
    logger.info(
        "Parse summary: %d found, %d parsed successfully, %d failed.",
        run_summary.files_found,
        run_summary.files_parsed_successfully,
        run_summary.files_failed,
    )

    if not parsed_documents:
        logger.error("No documents could be parsed successfully.")
        run_summary.run_errors.append("No documents could be parsed successfully.")
        run_summary.completed_at = datetime.now().astimezone().isoformat(timespec="seconds")
        written_paths = write_markdown_outputs(run_output_dir, run_summary=run_summary)
        logger.info("Wrote %d report file(s).", len(written_paths))
        return 1

    try:
        llm_provider = build_llm_provider(settings, logger)
    except Exception as exc:
        logger.exception("Unable to initialize the configured LLM provider")
        run_summary.run_errors.append(f"Unable to initialize the configured LLM provider: {type(exc).__name__}: {exc}")
        run_summary.completed_at = datetime.now().astimezone().isoformat(timespec="seconds")
        write_markdown_outputs(run_output_dir, run_summary=run_summary)
        return 1

    run_summary.llm_provider = llm_provider.provider_name
    run_summary.llm_model = getattr(llm_provider, "model", None)
    if run_summary.llm_model:
        logger.info("Using LLM provider: %s | model: %s", llm_provider.provider_name, run_summary.llm_model)
    else:
        logger.info("Using LLM provider: %s", llm_provider.provider_name)

    deal_output_root = output_root / slugify(deal_name)
    prior_feedback_paths = _reviewer_feedback_paths(deal_output_root, exclude_run_dir=run_output_dir)
    if prior_feedback_paths:
        ingest_reviewer_feedback_files(
            feedback_paths=prior_feedback_paths,
            logger=logger,
        )

    synthesis = run_analysis(
        deal_name=deal_name,
        documents=parsed_documents,
        llm_provider=llm_provider,
        logger=logger,
        extraction_errors=extraction_errors,
        mode=run_summary.analysis_mode,
    )
    run_summary.llm_calls_made = synthesis.llm_calls_attempted

    run_summary.completed_at = datetime.now().astimezone().isoformat(timespec="seconds")
    written_paths = write_markdown_outputs(
        run_output_dir,
        run_summary=run_summary,
        synthesis=synthesis,
    )
    ingest_reviewer_feedback_files(
        feedback_paths=_reviewer_feedback_paths(deal_output_root),
        logger=logger,
    )
    logger.info("Wrote %d markdown files.", len(written_paths))
    logger.info("Output files created: %s", ", ".join(path.name for path in written_paths + [run_output_dir / "run.log"]))
    logger.info(
        "Run summary: %d found, %d parsed successfully, %d failed.",
        run_summary.files_found,
        run_summary.files_parsed_successfully,
        run_summary.files_failed,
    )
    logger.info("Approximate LLM calls made: %d", run_summary.llm_calls_made)

    if extraction_errors:
        logger.warning("Completed with %d extraction error(s). See output markdown and run.log for details.", len(extraction_errors))
    else:
        logger.info("Completed without extraction errors.")

    return 0


def _reviewer_feedback_paths(deal_output_root: Path, *, exclude_run_dir: Path | None = None) -> list[Path]:
    if not deal_output_root.exists():
        return []
    feedback_paths = sorted(
        deal_output_root.glob("*/12_reviewer_feedback_template.json"),
        key=lambda path: path.parent.name,
    )
    if exclude_run_dir is not None:
        excluded = exclude_run_dir.resolve()
        feedback_paths = [path for path in feedback_paths if path.parent.resolve() != excluded]
    return feedback_paths
