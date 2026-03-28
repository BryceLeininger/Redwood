"""Write structured Markdown outputs for a diligence run."""

from __future__ import annotations

from pathlib import Path

from land_due_diligence_agent.models import DealSynthesis


def write_markdown_outputs(output_dir: Path, synthesis: DealSynthesis, provider_name: str) -> list[Path]:
    """Write the full diligence output set into Markdown files."""

    files = {
        output_dir / "00_executive_summary.md": _build_executive_summary_markdown(synthesis, provider_name),
        output_dir / "01_key_risks.md": _build_key_risks_markdown(synthesis),
        output_dir / "02_recommended_reading_order.md": _build_reading_order_markdown(synthesis),
        output_dir / "03_seller_questions.md": _build_seller_questions_markdown(synthesis),
        output_dir / "04_document_summaries.md": _build_document_summaries_markdown(synthesis),
        output_dir / "05_missing_diligence_items.md": _build_missing_items_markdown(synthesis),
        output_dir / "06_deal_synthesis.md": _build_deal_synthesis_markdown(synthesis),
    }

    written_paths: list[Path] = []
    for path, content in files.items():
        path.write_text(content, encoding="utf-8")
        written_paths.append(path)
    return written_paths


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
