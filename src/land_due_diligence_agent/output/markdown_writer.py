"""Write structured Markdown outputs for a diligence run."""

from __future__ import annotations

from pathlib import Path

from land_due_diligence_agent.models import DealSynthesis, RunSummary


def write_markdown_outputs(
    output_dir: Path,
    *,
    run_summary: RunSummary,
    synthesis: DealSynthesis | None = None,
) -> list[Path]:
    """Write the diligence output set and operational reports."""

    planned_output_names = ["00_run_summary.md"]
    if synthesis is not None:
        planned_output_names.extend(
            [
                "01_executive_summary.md",
                "02_key_risks.md",
                "03_recommended_reading_order.md",
                "04_seller_questions.md",
                "05_document_summaries.md",
                "06_missing_diligence_items.md",
                "07_deal_synthesis.md",
            ]
        )
    planned_output_names.extend(["08_error_report.md", "run.log"])
    run_summary.output_files_created = planned_output_names

    files: list[tuple[Path, str]] = [
        (output_dir / "00_run_summary.md", _build_run_summary_markdown(run_summary)),
    ]

    if synthesis is not None:
        files.extend(
            [
                (
                    output_dir / "01_executive_summary.md",
                    _build_executive_summary_markdown(synthesis, run_summary.llm_provider),
                ),
                (output_dir / "02_key_risks.md", _build_key_risks_markdown(synthesis)),
                (output_dir / "03_recommended_reading_order.md", _build_reading_order_markdown(synthesis)),
                (output_dir / "04_seller_questions.md", _build_seller_questions_markdown(synthesis)),
                (output_dir / "05_document_summaries.md", _build_document_summaries_markdown(synthesis)),
                (output_dir / "06_missing_diligence_items.md", _build_missing_items_markdown(synthesis)),
                (output_dir / "07_deal_synthesis.md", _build_deal_synthesis_markdown(synthesis)),
            ]
        )

    files.append((output_dir / "08_error_report.md", _build_error_report_markdown(run_summary, synthesis)))

    written_paths: list[Path] = []
    for path, content in files:
        path.write_text(content, encoding="utf-8")
        written_paths.append(path)
    return written_paths


def _build_run_summary_markdown(run_summary: RunSummary) -> str:
    lines = [
        "# Run Summary",
        "",
        f"- Run ID: `{run_summary.run_id}`",
        f"- Deal: {run_summary.deal_name}",
        f"- Input Folder: `{run_summary.input_folder}`",
        f"- Output Folder: `{run_summary.output_folder}`",
        f"- LLM Provider: `{run_summary.llm_provider}`",
        f"- Started At: `{run_summary.started_at}`",
        f"- Completed At: `{run_summary.completed_at or 'In progress'}`",
        "",
        "## Counts",
        "",
        f"- Files found: {run_summary.files_found}",
        f"- Parsed successfully: {run_summary.files_parsed_successfully}",
        f"- Failed: {run_summary.files_failed}",
        "",
        "## File Results",
        "",
    ]

    if not run_summary.file_results:
        lines.append("- No file-level processing results were recorded.")
    else:
        for result in run_summary.file_results:
            detail = f"- `{result.relative_path}`: {result.status}"
            if result.warnings:
                detail += f" | warnings: {'; '.join(result.warnings)}"
            if result.error_message:
                detail += f" | error: {result.error_message}"
            lines.append(detail)

    lines.extend(["", "## Output Files Created", ""])
    lines.extend(f"- `{name}`" for name in run_summary.output_files_created)

    if run_summary.run_errors:
        lines.extend(["", "## Run-Level Errors", ""])
        lines.extend(f"- {error}" for error in run_summary.run_errors)

    return "\n".join(lines) + "\n"


def _build_executive_summary_markdown(synthesis: DealSynthesis, provider_name: str) -> str:
    return (
        f"# Executive Summary\n\n"
        f"**Deal:** {synthesis.deal_name}\n\n"
        f"**Provider:** {provider_name}\n\n"
        f"**Entitlement Status:** {synthesis.entitlement_status}\n\n"
        f"{synthesis.executive_summary}\n"
    )


def _build_key_risks_markdown(synthesis: DealSynthesis) -> str:
    lines = ["# Key Risks", ""]
    if not synthesis.key_risks:
        lines.append("No concentrated risk signals were detected from the supplied document text.")
        return "\n".join(lines) + "\n"

    for risk in synthesis.key_risks:
        lines.append(f"## {risk.category}")
        lines.append(f"- Severity: {risk.severity}")
        lines.append(f"- Summary: {risk.summary}")
        if risk.evidence:
            lines.append("- Evidence:")
            lines.extend(f"  - {evidence}" for evidence in risk.evidence)
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _build_reading_order_markdown(synthesis: DealSynthesis) -> str:
    lines = ["# Recommended Reading Order", ""]
    for index, recommendation in enumerate(synthesis.recommended_reading_order, start=1):
        lines.append(f"{index}. **{recommendation.title}** (`{recommendation.relative_path}`)")
        lines.append(f"   Priority Score: {recommendation.priority}")
        lines.append(f"   Reason: {recommendation.reason}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _build_seller_questions_markdown(synthesis: DealSynthesis) -> str:
    lines = ["# Seller Questions", ""]
    if not synthesis.seller_questions:
        lines.append("- No seller questions were generated.")
        return "\n".join(lines) + "\n"

    lines.extend(f"- {question}" for question in synthesis.seller_questions)
    return "\n".join(lines) + "\n"


def _build_document_summaries_markdown(synthesis: DealSynthesis) -> str:
    lines = ["# Document Summaries", ""]
    for analysis in synthesis.document_analyses:
        lines.append(f"## {analysis.document.title}")
        lines.append(f"- Source: `{analysis.document.relative_path.as_posix()}`")
        lines.append(f"- File Type: `{analysis.document.extension}`")
        lines.append(f"- Reading Priority: {analysis.reading_priority}")
        lines.append(f"- Reading Rationale: {analysis.reading_reason}")
        if analysis.document.warnings:
            lines.append(f"- Extraction Warnings: {'; '.join(analysis.document.warnings)}")
        lines.append("")
        lines.append(analysis.summary)
        lines.append("")

        if analysis.risks:
            lines.append("### Detected Risks")
            for risk in analysis.risks:
                lines.append(f"- {risk.category} ({risk.severity}): {risk.summary}")
            lines.append("")

        if analysis.seller_questions:
            lines.append("### Document-Specific Questions")
            for question in analysis.seller_questions:
                lines.append(f"- {question}")
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _build_missing_items_markdown(synthesis: DealSynthesis) -> str:
    lines = ["# Missing Diligence Items", ""]
    if synthesis.missing_items:
        lines.extend(f"- {item}" for item in synthesis.missing_items)
    else:
        lines.append("- No obvious checklist gaps were inferred from document keyword coverage.")

    if synthesis.extraction_errors:
        lines.append("")
        lines.append("## Extraction Errors")
        lines.extend(f"- {error}" for error in synthesis.extraction_errors)
    return "\n".join(lines) + "\n"


def _build_deal_synthesis_markdown(synthesis: DealSynthesis) -> str:
    lines = [
        "# Deal Synthesis",
        "",
        "## Entitlement Status",
        synthesis.entitlement_status,
        "",
        "## Category Rollup",
        "",
    ]

    for category, summary in synthesis.category_rollup.items():
        lines.append(f"- **{category}:** {summary}")

    return "\n".join(lines) + "\n"


def _build_error_report_markdown(
    run_summary: RunSummary,
    synthesis: DealSynthesis | None,
) -> str:
    lines = ["# Error Report", ""]

    if run_summary.run_errors:
        lines.append("## Run-Level Errors")
        lines.append("")
        lines.extend(f"- {error}" for error in run_summary.run_errors)
        lines.append("")

    failed_results = [result for result in run_summary.file_results if result.status == "failed"]
    warning_results = [result for result in run_summary.file_results if result.warnings]

    lines.append("## Failed Files")
    lines.append("")
    if failed_results:
        lines.extend(
            f"- `{result.relative_path}`: {result.error_message or 'Unknown error.'}"
            for result in failed_results
        )
    else:
        lines.append("- No file parse failures were recorded.")

    lines.append("")
    lines.append("## Parsed With Warnings")
    lines.append("")
    if warning_results:
        lines.extend(
            f"- `{result.relative_path}`: {'; '.join(result.warnings)}"
            for result in warning_results
        )
    else:
        lines.append("- No parser warnings were recorded.")

    if synthesis is not None and synthesis.extraction_errors:
        lines.append("")
        lines.append("## Extraction Errors Passed Into Analysis")
        lines.append("")
        lines.extend(f"- {error}" for error in synthesis.extraction_errors)

    if not run_summary.run_errors and not failed_results and not warning_results:
        lines.append("")
        lines.append("No run-level errors, parse failures, or parser warnings were recorded.")

    return "\n".join(lines) + "\n"
