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
    gating_points = _build_gating_points(synthesis)
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
            "## Gating Issues",
            "",
        ]
    )
    lines.extend(f"- {item}" for item in gating_points)
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

    primary_risks, secondary_risks = _split_risk_tiers(synthesis.key_risks)

    lines.extend(["## Primary Risks (Deal-Shaping)", ""])
    for risk in primary_risks:
        lines.extend(_render_risk_block(risk, heading_level="###"))

    if secondary_risks:
        lines.extend(["## Secondary Risks (Important But Not Gating Yet)", ""])
        for risk in secondary_risks:
            lines.extend(_render_risk_block(risk, heading_level="###"))

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
    primary_risks, secondary_risks = _split_risk_tiers(synthesis.key_risks)
    lines = [
        "# Deal Synthesis",
        "",
        "## Overall Read",
        synthesis.executive_summary,
        "",
        "## Primary Risks (Deal-Shaping)",
        "",
    ]

    if primary_risks:
        lines.extend(f"- **{risk.category}:** {risk.issue} {risk.likely_implication}".strip() for risk in primary_risks)
    else:
        lines.append("- No primary deal-shaping risk was isolated from the extracted text.")

    lines.extend(["", "## Secondary Risks (Important But Not Gating Yet)", ""])
    if secondary_risks:
        lines.extend(f"- **{risk.category}:** {risk.issue} {risk.likely_implication}".strip() for risk in secondary_risks)
    else:
        lines.append("- No secondary risk was elevated beyond the primary issue set.")

    lines.extend(["", "## Gating Issues", ""])
    lines.extend(f"- {item}" for item in _build_gating_points(synthesis))

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


def _split_risk_tiers(key_risks: list) -> tuple[list, list]:
    primary = [risk for risk in key_risks if risk.priority_tier == "primary"] or key_risks[:3]
    secondary = [risk for risk in key_risks if risk.priority_tier == "secondary"]
    if not secondary and len(key_risks) > len(primary):
        secondary = key_risks[len(primary):]
    return primary, secondary


def _render_risk_block(risk, *, heading_level: str) -> list[str]:
    lines = [f"{heading_level} {risk.category}"]
    if risk.anchor:
        lines.append(f"- Document Anchor: {risk.anchor}")
    lines.append(f"- Severity: {risk.severity}")
    if risk.gating_flags:
        lines.append(f"- Gating Impact: {', '.join(risk.gating_flags)}")
    if risk.issue:
        lines.append(f"- Issue: {risk.issue}")
    if risk.why_it_matters:
        lines.append(f"- Why It Matters: {risk.why_it_matters}")
    if risk.likely_implication:
        lines.append(f"- Likely Implication: {risk.likely_implication}")
    if risk.uncertainty_reason:
        lines.append(f"- Remaining Uncertainty: {risk.uncertainty_reason}")
    lines.append(f"- Summary: {risk.summary}")
    if risk.source_documents:
        lines.append(f"- Primary Support: {', '.join(risk.source_documents)}")
    if risk.evidence:
        lines.append("- Evidence:")
        lines.extend(f"  - {evidence}" for evidence in risk.evidence)
    lines.append("")
    return lines


def _build_executive_conclusions(synthesis: DealSynthesis) -> list[str]:
    primary_risks, _ = _split_risk_tiers(synthesis.key_risks)
    conclusions = [risk.issue or risk.summary for risk in primary_risks[:3]]
    if any(analysis.confidence == "low" for analysis in synthesis.document_analyses):
        conclusions.append("At least one key cost or support file still requires manual review because extraction quality was weak.")
    if not conclusions:
        conclusions.append(synthesis.entitlement_status)
    return conclusions[:5]


def _build_known_points(synthesis: DealSynthesis) -> list[str]:
    points = [synthesis.entitlement_status]
    readable_focus_sets = {
        focus
        for analysis in synthesis.document_analyses
        if analysis.confidence != "low"
        for focus in analysis.focus_areas
    }
    coverage = []
    if "Title / Access Concerns" in readable_focus_sets:
        coverage.append("title")
    if "Environmental Risks" in readable_focus_sets:
        coverage.append("environmental")
    if "Geotechnical Risks" in readable_focus_sets:
        coverage.append("geotechnical")
    if "Flood / Drainage Issues" in readable_focus_sets:
        coverage.append("stormwater")
    if "Fee / Exaction Burden" in readable_focus_sets:
        coverage.append("fee")
    if coverage:
        points.append(
            f"The package includes readable {', '.join(coverage[:4])} support, so the current problem is not missing entire workstreams; it is resolving the open items inside them."
        )
    return points[:4]


def _build_unresolved_points(synthesis: DealSynthesis) -> list[str]:
    primary_risks, _ = _split_risk_tiers(synthesis.key_risks)
    points = [risk.issue for risk in primary_risks[:3] if risk.issue]
    for risk in primary_risks[:3]:
        if risk.uncertainty_reason:
            points.append(f"{risk.category}: {risk.uncertainty_reason}")
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


def _build_gating_points(synthesis: DealSynthesis) -> list[str]:
    grouped = _group_risks_by_gate(synthesis.key_risks)
    points: list[str] = []

    if grouped["Closing"]:
        actions = "; ".join(_build_gate_action_text(risk) for risk in grouped["Closing"][:2])
        points.append(f"Before closing: {actions}.")
    if grouped["Underwriting confidence"]:
        actions = "; ".join(_build_gate_action_text(risk) for risk in grouped["Underwriting confidence"][:3])
        if any(analysis.confidence == "low" for analysis in synthesis.document_analyses):
            actions += "; replace unreadable budget or support files"
        points.append(f"Before underwriting confidence: {actions}.")
    if grouped["Vertical start"]:
        actions = "; ".join(_build_gate_action_text(risk) for risk in grouped["Vertical start"][:3])
        points.append(f"Before vertical start: {actions}.")

    if not points and synthesis.missing_items:
        points.append(f"Before relying on the package: obtain direct support for {', '.join(synthesis.missing_items[:2])}.")

    return points[:4]


def _build_decision_points(synthesis: DealSynthesis) -> list[str]:
    grouped = _group_risks_by_gate(synthesis.key_risks)
    points: list[str] = []
    if grouped["Closing"]:
        points.append("Treat closing as conditional until the title, access, and other land-control issues are expressly cleared.")
    if grouped["Underwriting confidence"]:
        points.append("Treat land basis as provisional until cost, fee, offsite, and other buyer-facing obligations are converted into auditable support.")
    if grouped["Vertical start"]:
        points.append("Treat the vertical-start schedule as conditional until permit-stage, civil, utility, and offsite execution items are closed.")
    if any(analysis.confidence == "low" for analysis in synthesis.document_analyses):
        points.append("Do not treat the current cost package as fully decision-grade until unreadable or budgetary files are replaced with native support.")
    return points[:5]


def _build_ic_overall_read(synthesis: DealSynthesis) -> str:
    if not synthesis.key_risks:
        return "The file set does not surface a concentrated issue, but the package should still be checked for completeness before it is treated as decision-ready."

    primary_risks, _ = _split_risk_tiers(synthesis.key_risks)
    lead_issues = "; ".join((risk.issue or risk.summary) for risk in primary_risks[:3])
    return (
        f"The package is substantive, but it is not ready for a clean recommendation yet. {lead_issues} "
        f"Those issues still control closing risk, land-basis reliability, and execution timing."
    )


def _build_ic_biggest_risks(synthesis: DealSynthesis) -> list[str]:
    primary_risks, _ = _split_risk_tiers(synthesis.key_risks)
    risks = []
    for risk in primary_risks[:4]:
        risk_text = f"{risk.issue} {risk.likely_implication}".strip()
        if risk.anchor:
            risk_text = f"{risk.anchor}: {risk_text[0].lower() + risk_text[1:]}" if risk_text else risk.anchor
        risks.append(risk_text)
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
    primary_risks, _ = _split_risk_tiers(synthesis.key_risks)
    unknowns.extend(
        f"{risk.category}: {risk.uncertainty_reason}"
        for risk in primary_risks[:3]
        if risk.uncertainty_reason
    )
    return unknowns[:4] or ["No major unknown was surfaced from the current package."]


def _build_ic_verify_points(synthesis: DealSynthesis) -> list[str]:
    primary_risks, _ = _split_risk_tiers(synthesis.key_risks)
    verify_points = []
    for risk in primary_risks[:4]:
        if risk.source_documents:
            verify_points.append(
                f"Personally review {', '.join(risk.source_documents[:2])} to verify the current {risk.category.lower()} issue and whether the underwriting treatment is actually supported."
            )
    if not verify_points:
        verify_points.append("Personally review the highest-priority documents in the recommended reading order.")
    return verify_points[:4]


def _build_decision_ready_assessment(synthesis: DealSynthesis) -> str:
    grouped = _group_risks_by_gate(synthesis.key_risks)
    if grouped["Closing"] or synthesis.missing_items or any(analysis.confidence == "low" for analysis in synthesis.document_analyses):
        return "Not decision-ready. The package is useful, but closing and underwriting should stay conditional until the gating title, scope, cost, and support gaps are resolved."
    if grouped["Underwriting confidence"] or grouped["Vertical start"]:
        return "Not fully decision-ready. The package is substantive, but the risk stack is still too open on basis and execution timing to support a final recommendation."
    return "Close to decision-ready, but still requires targeted verification of the highest-priority risks before final investment committee reliance."


def _group_risks_by_gate(key_risks: list) -> dict[str, list]:
    grouped = {"Closing": [], "Underwriting confidence": [], "Vertical start": []}
    for risk in key_risks:
        for gate in risk.gating_flags:
            if gate in grouped:
                grouped[gate].append(risk)
    return grouped


def _build_gate_action_text(risk) -> str:
    if risk.category == "Title / Access Concerns":
        return "clear the title and access exceptions against the current plan set"
    if risk.category == "Entitlement Status":
        return "close the remaining approval and permit-stage conditions"
    if risk.category == "Geotechnical Risks":
        return "confirm the active geotechnical recommendations are fully carried into design and budget"
    if risk.category == "Flood / Drainage Issues":
        return "lock the drainage and stormwater scope"
    if risk.category == "Fee / Exaction Burden":
        return "lock the city-confirmed fee stack"
    if risk.category == "Offsite Obligations":
        return "allocate every frontage and offsite obligation into a clean buyer-facing scope"
    if risk.category == "Budget / Cost Reliability":
        return "replace unreadable or budgetary cost support with auditable pricing"
    if risk.category == "Utilities / Infrastructure Issues":
        return "confirm utility capacity, will-serve assumptions, and required offsite utility work"
    if risk.category == "Environmental Risks":
        return "resolve the environmental and mitigation follow-up scope"
    if risk.category == "Schedule Risks":
        return "rebuild the critical path with only confirmed assumptions"
    return f"resolve the current {risk.category.lower()} issue"
