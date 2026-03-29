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
                "09_investment_committee_brief.md",
            ]
        )
    planned_output_names.extend(["08_error_report.md", "run.log"])
    run_summary.output_files_created = planned_output_names

    files: list[tuple[Path, str]] = [
        (output_dir / "00_run_summary.md", _build_run_summary_markdown(run_summary, synthesis)),
    ]

    if synthesis is not None:
        files.extend(
            [
                (
                    output_dir / "01_executive_summary.md",
                    _build_executive_summary_markdown(synthesis, run_summary.llm_provider, run_summary),
                ),
                (output_dir / "02_key_risks.md", _build_key_risks_markdown(synthesis)),
                (output_dir / "03_recommended_reading_order.md", _build_reading_order_markdown(synthesis)),
                (output_dir / "04_seller_questions.md", _build_seller_questions_markdown(synthesis)),
                (output_dir / "05_document_summaries.md", _build_document_summaries_markdown(synthesis)),
                (output_dir / "06_missing_diligence_items.md", _build_missing_items_markdown(synthesis)),
                (output_dir / "07_deal_synthesis.md", _build_deal_synthesis_markdown(synthesis)),
                (output_dir / "09_investment_committee_brief.md", _build_investment_committee_brief_markdown(synthesis)),
            ]
        )

    files.append((output_dir / "08_error_report.md", _build_error_report_markdown(run_summary, synthesis)))

    written_paths: list[Path] = []
    for path, content in files:
        path.write_text(content, encoding="utf-8")
        written_paths.append(path)
    return written_paths


def _build_run_summary_markdown(
    run_summary: RunSummary,
    synthesis: DealSynthesis | None,
) -> str:
    lines = [
        "# Run Summary",
        "",
        f"- Run ID: `{run_summary.run_id}`",
        f"- Deal: {run_summary.deal_name}",
        f"- Input Folder: `{run_summary.input_folder}`",
        f"- Output Folder: `{run_summary.output_folder}`",
        f"- LLM Provider: `{run_summary.llm_provider}`",
        f"- LLM Model: `{run_summary.llm_model or 'n/a'}`",
        f"- Started At: `{run_summary.started_at}`",
        f"- Completed At: `{run_summary.completed_at or 'In progress'}`",
        "",
        "## Counts",
        "",
        f"- Files found: {run_summary.files_found}",
        f"- Parsed successfully: {run_summary.files_parsed_successfully}",
        f"- Failed: {run_summary.files_failed}",
        "",
    ]

    ocr_results = _ocr_affected_results(run_summary)
    if ocr_results:
        lines.extend(
            [
                "## OCR / Extraction Watchlist",
                "",
                f"- OCR-related warnings affected {len(ocr_results)} file(s).",
            ]
        )
        lines.extend(f"- `{result.relative_path}`" for result in ocr_results)
        lines.append("")

    if synthesis is not None:
        confidence_counts = _confidence_counts(synthesis)
        lines.extend(
            [
                "## Confidence Snapshot",
                "",
                f"- High confidence documents: {confidence_counts['high']}",
                f"- Medium confidence documents: {confidence_counts['medium']}",
                f"- Low confidence documents: {confidence_counts['low']}",
                "",
            ]
        )

        if synthesis.llm_failures:
            lines.extend(
                [
                    "## LLM Refinement Issues",
                    "",
                    f"- LLM refinement failed for {len(synthesis.llm_failures)} call(s). See `08_error_report.md` for details.",
                    "",
                ]
            )

    lines.extend(
        [
            "## File Results",
            "",
        ]
    )

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


def _build_executive_summary_markdown(
    synthesis: DealSynthesis,
    provider_name: str,
    run_summary: RunSummary,
) -> str:
    limitations = _build_known_limitations(run_summary, synthesis)
    conclusions = _build_executive_conclusions(synthesis)
    known_points = _build_known_points(synthesis)
    unresolved_points = _build_unresolved_points(synthesis)
    decision_points = _build_decision_points(synthesis)
    lines = [
        "# Executive Summary",
        "",
        f"**Deal:** {synthesis.deal_name}",
        "",
        f"**Provider:** {provider_name}",
        "",
        f"**Entitlement Status:** {synthesis.entitlement_status}",
        "",
        "## Overall Read",
        "",
        synthesis.executive_summary,
        "",
        "## Most Important Conclusions",
        "",
    ]
    lines.extend(f"- {item}" for item in conclusions)
    lines.extend(
        [
            "",
            "## What Appears Known",
            "",
        ]
    )
    lines.extend(f"- {item}" for item in known_points)
    lines.extend(
        [
            "",
            "## What Appears Unresolved",
            "",
        ]
    )
    lines.extend(f"- {item}" for item in unresolved_points)
    lines.extend(
        [
            "",
            "## What Matters Most For The Acquisition Decision",
            "",
        ]
    )
    lines.extend(f"- {item}" for item in decision_points)
    lines.extend(
        [
            "",
        "## Known Limitations Of This Run",
        "",
        ]
    )
    lines.extend(f"- {item}" for item in limitations)
    return "\n".join(lines) + "\n"


def _build_key_risks_markdown(synthesis: DealSynthesis) -> str:
    lines = ["# Key Risks", ""]
    if not synthesis.key_risks:
        lines.append("No concentrated risk signals were detected from the supplied document text.")
        return "\n".join(lines) + "\n"

    for risk in synthesis.key_risks:
        lines.append(f"## {risk.category}")
        lines.append(f"- Severity: {risk.severity}")
        if risk.issue:
            lines.append(f"- Issue: {risk.issue}")
        if risk.why_it_matters:
            lines.append(f"- Why It Matters: {risk.why_it_matters}")
        if risk.likely_implication:
            lines.append(f"- Likely Implication: {risk.likely_implication}")
        lines.append(f"- Summary: {risk.summary}")
        if risk.source_documents:
            lines.append(f"- Primary Support: {', '.join(risk.source_documents)}")
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
        lines.append(f"   Confidence: {recommendation.confidence}")
        if recommendation.focus_areas:
            lines.append(f"   Focus Areas: {', '.join(recommendation.focus_areas)}")
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
        lines.append(f"- Confidence: {analysis.confidence} ({analysis.confidence_reason})")
        if analysis.focus_areas:
            lines.append(f"- Focus Areas: {', '.join(analysis.focus_areas)}")
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
        "## Overall Read",
        synthesis.executive_summary,
        "",
        "## Core Issues",
        "",
    ]

    for category, summary in synthesis.category_rollup.items():
        lines.append(f"- **{category}:** {summary}")

    return "\n".join(lines) + "\n"


def _build_investment_committee_brief_markdown(synthesis: DealSynthesis) -> str:
    overall_read = _build_ic_overall_read(synthesis)
    biggest_risks = _build_ic_biggest_risks(synthesis)
    biggest_unknowns = _build_ic_biggest_unknowns(synthesis)
    verify_points = _build_ic_verify_points(synthesis)
    decision_ready = _build_decision_ready_assessment(synthesis)

    lines = [
        "# Investment Committee Brief",
        "",
        "## Overall Read",
        "",
        overall_read,
        "",
        "## Biggest Risks",
        "",
    ]
    lines.extend(f"- {item}" for item in biggest_risks)
    lines.extend(
        [
            "",
            "## Biggest Unknowns",
            "",
        ]
    )
    lines.extend(f"- {item}" for item in biggest_unknowns)
    lines.extend(
        [
            "",
            "## What To Personally Verify",
            "",
        ]
    )
    lines.extend(f"- {item}" for item in verify_points)
    lines.extend(
        [
            "",
            "## Decision-Ready?",
            "",
            decision_ready,
            "",
        ]
    )
    return "\n".join(lines)


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
    ocr_results = _ocr_affected_results(run_summary)

    lines.append("## OCR / Low Confidence Documents")
    lines.append("")
    if ocr_results:
        lines.extend(
            f"- `{result.relative_path}`: {'; '.join(result.warnings)}"
            for result in ocr_results
        )
    else:
        lines.append("- No OCR-related warnings were recorded.")

    if synthesis is not None:
        low_confidence_docs = [
            analysis
            for analysis in synthesis.document_analyses
            if analysis.confidence == "low"
        ]
        if low_confidence_docs:
            lines.append("")
            lines.append("## Low Confidence Review Targets")
            lines.append("")
            lines.extend(
                f"- `{analysis.document.relative_path.as_posix()}`: {analysis.confidence_reason}"
                for analysis in low_confidence_docs
            )

        if synthesis.llm_failures:
            lines.append("")
            lines.append("## LLM Refinement Failures")
            lines.append("")
            lines.extend(
                f"- [{failure.stage}] `{failure.target}` | model: `{failure.model}` | {failure.detail}"
                for failure in synthesis.llm_failures
            )

    lines.append("")
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


def _ocr_affected_results(run_summary: RunSummary) -> list:
    return [
        result
        for result in run_summary.file_results
        if any(_is_ocr_warning(warning) for warning in result.warnings)
    ]


def _is_ocr_warning(warning: str) -> bool:
    warning_lower = warning.lower()
    return (
        "ocr fallback" in warning_lower
        or "no pdf text extracted" in warning_lower
        or "normalized text is empty" in warning_lower
    )


def _confidence_counts(synthesis: DealSynthesis) -> dict[str, int]:
    counts = {"high": 0, "medium": 0, "low": 0}
    for analysis in synthesis.document_analyses:
        counts[analysis.confidence] += 1
    return counts


def _build_known_limitations(
    run_summary: RunSummary,
    synthesis: DealSynthesis,
) -> list[str]:
    limitations: list[str] = []

    if run_summary.llm_provider == "heuristic":
        limitations.append("This run used heuristic mode only; no OpenAI refinement was applied.")

    ocr_results = _ocr_affected_results(run_summary)
    if ocr_results:
        limitations.append(f"OCR-related extraction warnings affected {len(ocr_results)} document(s).")

    low_confidence_docs = [analysis for analysis in synthesis.document_analyses if analysis.confidence == "low"]
    if low_confidence_docs:
        limitations.append(
            f"{len(low_confidence_docs)} document(s) were assessed at low confidence because extraction was incomplete or empty."
        )

    if synthesis.extraction_errors:
        limitations.append(f"{len(synthesis.extraction_errors)} extraction error(s) were carried into analysis.")

    if synthesis.llm_failures:
        limitations.append(f"OpenAI refinement failed for {len(synthesis.llm_failures)} call(s); heuristic drafts were retained where needed.")

    if not limitations:
        limitations.append("No major extraction limitations were recorded for this run.")

    return limitations


def _build_executive_conclusions(synthesis: DealSynthesis) -> list[str]:
    conclusions = [risk.issue or risk.summary for risk in synthesis.key_risks[:5]]
    if not conclusions:
        conclusions.append(synthesis.entitlement_status)
    return conclusions[:5]


def _build_known_points(synthesis: DealSynthesis) -> list[str]:
    points = [synthesis.entitlement_status]
    focus_sets = {focus for analysis in synthesis.document_analyses for focus in analysis.focus_areas}
    if "Title / Access Concerns" in focus_sets:
        points.append("The package includes title materials, so access and exception issues can be checked directly rather than assumed.")
    if "Geotechnical Risks" in focus_sets:
        points.append("Geotechnical studies are present, so the main soils assumptions are at least partially documented.")
    if "Flood / Drainage Issues" in focus_sets:
        points.append("Stormwater and drainage materials are present, so civil assumptions are not being underwritten blind.")
    if "Fee / Exaction Burden" in focus_sets:
        points.append("A fee schedule is in the file set, providing a usable starting point for public-fee underwriting.")
    return points[:4]


def _build_unresolved_points(synthesis: DealSynthesis) -> list[str]:
    points = [risk.issue for risk in synthesis.key_risks[:5] if risk.issue]
    low_confidence_docs = [
        analysis.document.relative_path.name
        for analysis in synthesis.document_analyses
        if analysis.confidence == "low"
    ]
    if low_confidence_docs:
        points.append(f"Low-confidence extraction remains on: {', '.join(low_confidence_docs[:2])}.")
    if synthesis.missing_items:
        points.append(f"Missing or unsupported diligence still includes: {', '.join(synthesis.missing_items[:3])}.")
    return points[:5]


def _build_decision_points(synthesis: DealSynthesis) -> list[str]:
    points = [risk.likely_implication for risk in synthesis.key_risks[:5] if risk.likely_implication]
    if any(analysis.confidence == "low" for analysis in synthesis.document_analyses):
        points.append("Cost underwriting should remain provisional until unreadable or budgetary files are replaced with native support.")
    return points[:5]


def _build_ic_overall_read(synthesis: DealSynthesis) -> str:
    if not synthesis.key_risks:
        return "The file set does not surface a concentrated issue, but the package should still be checked for completeness before it is treated as decision-ready."

    top_labels = ", ".join(risk.category.lower() for risk in synthesis.key_risks[:3])
    return (
        f"The package reads as substantive but not yet clean. The issues most likely to move the land decision are {top_labels}. "
        f"Before treating the deal as fully underwritten, confirm that those items do not break closability, materially move basis, or slow the path to permits and execution."
    )


def _build_ic_biggest_risks(synthesis: DealSynthesis) -> list[str]:
    risks = []
    for risk in synthesis.key_risks[:4]:
        risks.append(f"{risk.issue} {risk.likely_implication}".strip())
    return risks or ["No concentrated issue was elevated into a top risk."]


def _build_ic_biggest_unknowns(synthesis: DealSynthesis) -> list[str]:
    unknowns = []
    if synthesis.missing_items:
        unknowns.extend(f"Need direct support for: {item}." for item in synthesis.missing_items[:3])
    low_confidence_docs = [
        analysis.document.relative_path.name
        for analysis in synthesis.document_analyses
        if analysis.confidence == "low"
    ]
    if low_confidence_docs:
        unknowns.append(f"Unreadable or weakly extracted documents still affect: {', '.join(low_confidence_docs[:2])}.")
    if synthesis.key_risks:
        unknowns.extend(
            f"Need tighter confirmation on {risk.category.lower()} before relying on the current underwriting."
            for risk in synthesis.key_risks[:2]
        )
    return unknowns[:4] or ["No major unknown was surfaced from the current package."]


def _build_ic_verify_points(synthesis: DealSynthesis) -> list[str]:
    verify_points = []
    for risk in synthesis.key_risks[:4]:
        if risk.source_documents:
            verify_points.append(
                f"Personally review {', '.join(risk.source_documents[:2])} for the current {risk.category.lower()} issue."
            )
    if not verify_points:
        verify_points.append("Personally review the highest-priority documents in the recommended reading order.")
    return verify_points[:4]


def _build_decision_ready_assessment(synthesis: DealSynthesis) -> str:
    if synthesis.missing_items or any(analysis.confidence == "low" for analysis in synthesis.document_analyses):
        return "Not yet decision-ready. The package is directionally useful, but closing, cost, or execution assumptions should not be treated as fully underwritten until the open support gaps are resolved."
    if len(synthesis.key_risks) >= 4:
        return "Not yet fully decision-ready. The diligence package is substantive, but the current risk stack is still too open to rely on without targeted confirmation."
    return "Close to decision-ready, but still requires targeted verification of the highest-priority risks before final investment committee reliance."
