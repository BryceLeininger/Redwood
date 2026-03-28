"""CLI entry point for the land due diligence agent."""

from __future__ import annotations

import argparse
from pathlib import Path

from land_due_diligence_agent.analysis.service import run_analysis
from land_due_diligence_agent.config import Settings
from land_due_diligence_agent.ingestion.discovery import discover_documents
from land_due_diligence_agent.llm.factory import build_llm_provider
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
    run_output_dir = ensure_directory(output_root / slugify(deal_name))
    logger = configure_logging(settings.log_level, run_output_dir / "run.log")

    logger.info("Starting diligence review for '%s'.", deal_name)
    logger.info("Input folder: %s", input_folder)
    logger.info("Output folder: %s", run_output_dir)

    try:
        document_paths = discover_documents(input_folder)
    except Exception as exc:
        logger.error("Unable to load input folder: %s", exc)
        return 1

    if not document_paths:
        logger.error("No supported documents were found in %s", input_folder)
        return 1

    parsed_documents = []
    extraction_errors: list[str] = []

    for path in document_paths:
        relative_path = path.relative_to(input_folder).as_posix()
        try:
            parsed_documents.append(parse_document(path, input_folder))
            logger.info("Parsed %s", relative_path)
        except Exception as exc:
            logger.exception("Failed to parse %s", relative_path)
            extraction_errors.append(f"{relative_path}: {exc}")

    if not parsed_documents:
        logger.error("No documents could be parsed successfully.")
        return 1

    llm_provider = build_llm_provider(settings, logger)
    logger.info("Using LLM provider: %s", llm_provider.provider_name)

    synthesis = run_analysis(
        deal_name=deal_name,
        documents=parsed_documents,
        llm_provider=llm_provider,
        logger=logger,
        extraction_errors=extraction_errors,
    )

    written_paths = write_markdown_outputs(run_output_dir, synthesis, llm_provider.provider_name)
    logger.info("Wrote %d markdown files.", len(written_paths))

    if extraction_errors:
        logger.warning("Completed with %d extraction error(s). See output markdown and run.log for details.", len(extraction_errors))
    else:
        logger.info("Completed without extraction errors.")

    return 0
