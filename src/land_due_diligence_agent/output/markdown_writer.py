"""Write structured Markdown outputs for a diligence run."""

from __future__ import annotations

import json
from pathlib import Path

from land_due_diligence_agent.models import CanonicalIssue, DealSynthesis, RunSummary
from land_due_diligence_agent.utils.text import normalize_text


def write_markdown_outputs(
    output_dir: Path,
    *,
    run_summary: RunSummary,
    synthesis: DealSynthesis | None = None,
) -> list[Path]:
    """Write the diligence output set and operational reports."""

    planned_output_names = ["00_run_summary.md"]
    if synthesis is not None:
        planned_output_names.extend(_analysis_output_names(run_summary.analysis_mode))
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
                (output_dir / "02_key_risks.md", _build_key_risks_markdown(synthesis, run_summary.analysis_mode)),
                (output_dir / "04_seller_questions.md", _build_seller_questions_markdown(synthesis, run_summary.analysis_mode)),
            ]
        )
        if run_summary.analysis_mode == "full":
            files.extend(
                [
                    (output_dir / "03_recommended_reading_order.md", _build_reading_order_markdown(synthesis)),
                    (output_dir / "05_document_summaries.md", _build_document_summaries_markdown(synthesis)),
                    (output_dir / "06_missing_diligence_items.md", _build_missing_items_markdown(synthesis)),
                    (output_dir / "07_deal_synthesis.md", _build_deal_synthesis_markdown(synthesis)),
                    (output_dir / "09_investment_committee_brief.md", _build_investment_committee_brief_markdown(synthesis)),
                    (output_dir / "10_issue_analysis.md", _build_issue_analysis_markdown(synthesis)),
                    (output_dir / "11_issue_registry_debug.md", _build_issue_registry_debug_markdown(synthesis)),
                    (output_dir / "12_reviewer_feedback_template.json", _build_reviewer_feedback_template_json(synthesis)),
                ]
            )

    files.append((output_dir / "08_error_report.md", _build_error_report_markdown(run_summary, synthesis)))

    written_paths: list[Path] = []
    for path, content in files:
        path.write_text(content, encoding="utf-8")
        written_paths.append(path)
    return written_paths


def _analysis_output_names(analysis_mode: str) -> list[str]:
    if analysis_mode == "fast":
        return [
            "01_executive_summary.md",
            "02_key_risks.md",
            "04_seller_questions.md",
        ]

    return [
        "01_executive_summary.md",
        "02_key_risks.md",
        "03_recommended_reading_order.md",
        "04_seller_questions.md",
        "05_document_summaries.md",
        "06_missing_diligence_items.md",
        "07_deal_synthesis.md",
        "09_investment_committee_brief.md",
        "10_issue_analysis.md",
        "11_issue_registry_debug.md",
        "12_reviewer_feedback_template.json",
    ]


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
        f"- Analysis Mode: `{run_summary.analysis_mode}`",
        f"- LLM Provider: `{run_summary.llm_provider}`",
        f"- LLM Model: `{run_summary.llm_model or 'n/a'}`",
        f"- Approximate LLM Calls: {run_summary.llm_calls_made}",
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
        lines.extend(_format_ocr_result_line(result) for result in ocr_results)
        lines.append("")

    ocr_used_results = _ocr_used_results(run_summary)
    if ocr_used_results:
        total_ocr_pages = sum(len(result.ocr_pages) for result in ocr_used_results)
        lines.extend(
            [
                "## OCR Fallback Applied",
                "",
                f"- OCR fallback was required on {len(ocr_used_results)} file(s) across {total_ocr_pages} page(s).",
            ]
        )
        lines.extend(_format_ocr_result_line(result, include_warning_summary=False) for result in ocr_used_results)
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
            if result.ocr_pages:
                detail += f" | ocr pages: {_format_page_list(result.ocr_pages)}"
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
    top_issues = _selected_issues(synthesis, "01_executive_summary.md", default_count=4)
    bullets = _build_executive_bullets(synthesis, top_issues)
    overall_read = normalize_text(synthesis.executive_summary)
    lines = [
        "# Executive Summary",
        "",
        f"**Deal:** {synthesis.deal_name}",
        "",
        f"**Provider:** {provider_name}",
        "",
        f"**Mode:** {run_summary.analysis_mode}",
        "",
        f"**Entitlement Status:** {synthesis.entitlement_status}",
        "",
        f"**Recommendation Posture:** {synthesis.recommendation.posture}",
        "",
        "## Overall Read",
        "",
        overall_read,
    ]
    if run_summary.analysis_mode == "full":
        lines.extend(
            [
                "",
                "## Decision Framing",
                "",
            ]
        )
        lines.extend(_build_decision_framing_lines(synthesis))
    lines.extend(
        [
            "",
            "## Executive Call",
            "",
        ]
    )
    lines.extend(f"- {item}" for item in bullets)
    lines.extend(
        [
            "",
            "## Known Limitations Of This Run",
            "",
        ]
    )
    lines.extend(f"- {item}" for item in limitations)
    return "\n".join(lines) + "\n"


def _build_key_risks_markdown(synthesis: DealSynthesis, analysis_mode: str) -> str:
    lines = ["# Key Risks", ""]
    issues = _selected_issues(
        synthesis,
        "02_key_risks.md",
        default_count=3 if analysis_mode == "fast" else 5,
    )
    if not issues:
        lines.append("No concentrated issue was elevated from the current package.")
        return "\n".join(lines) + "\n"

    lines.extend(["## Ranked Issues", ""])
    for index, issue in enumerate(issues, start=1):
        lines.extend(_render_canonical_issue_risk_block(issue, index=index))

    if analysis_mode == "full" and synthesis.contradictions:
        lines.extend(["## Potential Contradictions / Tensions", ""])
        lines.extend(_render_contradictions(synthesis.contradictions))

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


def _build_seller_questions_markdown(synthesis: DealSynthesis, analysis_mode: str) -> str:
    lines = ["# Seller Questions", ""]
    if not synthesis.seller_questions:
        lines.append("- No seller questions were generated.")
        return "\n".join(lines) + "\n"

    questions = synthesis.seller_questions[:6] if analysis_mode == "fast" else synthesis.seller_questions
    lines.extend(f"- {question}" for question in questions)
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
        if analysis.document.ocr_pages:
            lines.append(f"- OCR Pages: {_format_page_list(analysis.document.ocr_pages)}")
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


def _build_issue_analysis_markdown(synthesis: DealSynthesis) -> str:
    lines = ["# Issue Analysis", ""]
    issues = synthesis.canonical_issue_registry.issues
    if not issues:
        lines.append("- No canonical issue was populated.")
        return "\n".join(lines) + "\n"

    for issue in issues:
        lines.append(f"## {issue.title}")
        lines.append(f"- Category: {issue.category}")
        lines.append(f"- Priority Score: {issue.priority_score.total}")
        lines.append(f"- Status: {issue.status}")
        lines.append(f"- Confidence: {issue.confidence}")
        lines.append(f"- Decision Action: {issue.decision_action}")
        if issue.citations:
            lines.append(f"- Source: {_format_citations(issue.citations)}")
        elif issue.source_documents:
            lines.append(f"- Source: {', '.join(issue.source_documents)}")
        lines.append("")
        lines.append("### Core Facts")
        if issue.core_facts:
            lines.extend(f"- {fact}" for fact in issue.core_facts[:4])
        else:
            lines.append("- No concentrated fact pattern was isolated in this lane.")
        lines.append("")
        lines.append("### Best Evidence")
        if issue.best_evidence:
            lines.extend(f"- {evidence}" for evidence in issue.best_evidence[:3])
        else:
            lines.append("- No short-form evidence snippet was captured.")
        lines.append("")
        lines.append("### Unresolved Questions")
        if issue.open_questions:
            lines.extend(f"- {question}" for question in issue.open_questions[:4])
        else:
            lines.append("- No unresolved question was isolated beyond the current cited facts.")
        lines.append("")
        lines.append("### Why It Matters")
        lines.append(f"- {issue.why_it_matters}")
        lines.append("")
        lines.append("### Likely Implication")
        lines.append(f"- {issue.likely_implication}")
        lines.append("")
        lines.append("### What Would Resolve It")
        lines.append(f"- {issue.what_would_resolve_it}")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def _build_missing_items_markdown(synthesis: DealSynthesis) -> str:
    lines = ["# Missing Diligence Items", ""]
    grouped = {
        "not found": [],
        "unclear whether present": [],
        "present but weak": [],
        "present and adequate": [],
    }
    for assessment in synthesis.omission_assessments:
        grouped.setdefault(assessment.status, []).append(assessment)

    for status in ("not found", "unclear whether present", "present but weak", "present and adequate"):
        assessments = grouped.get(status, [])
        if not assessments:
            continue
        lines.append(f"## {status.title()}")
        lines.append("")
        for assessment in assessments:
            source = _format_citations(assessment.citations[:2]) or ", ".join(assessment.source_documents[:2])
            suffix = f" [Source: {source}]" if source else ""
            lines.append(f"- **{assessment.item}:** {assessment.rationale}{suffix}")
        lines.append("")

    if not synthesis.omission_assessments:
        lines.append("- No omission assessment was generated.")

    if synthesis.extraction_errors:
        lines.append("")
        lines.append("## Extraction Errors")
        lines.extend(f"- {error}" for error in synthesis.extraction_errors)
    return "\n".join(lines) + "\n"


def _build_deal_synthesis_markdown(synthesis: DealSynthesis) -> str:
    issues = synthesis.canonical_issue_registry.issues
    top_issues = issues[:3]
    lines = [
        "# Deal Synthesis",
        "",
        "## Overall Read",
        normalize_text(synthesis.executive_summary),
        "",
        "## Risk Pattern",
        "",
    ]
    lines.extend(f"- {item}" for item in _build_pattern_lines(synthesis, top_issues))

    lines.extend(["", "## Potential Contradictions / Tensions", ""])
    lines.extend(_render_contradictions(synthesis.contradictions))

    lines.extend(["", "## Adversarial Challenge", ""])
    lines.extend(_render_challenge_findings(synthesis.challenge_findings, limit=4))

    lines.extend(["", "## Gating Issues", ""])
    lines.extend(f"- {item}" for item in _build_decision_gate_lines(synthesis))

    return "\n".join(lines) + "\n"


def _build_investment_committee_brief_markdown(synthesis: DealSynthesis) -> str:
    overall_read = _build_ic_overall_read(synthesis)
    verify_points = _build_personal_verification_items(synthesis)
    readiness_status, readiness_reason = _evaluate_decision_readiness(synthesis)

    lines = [
        "# Investment Committee Brief",
        "",
        f"**Recommendation:** {synthesis.recommendation.posture}",
        "",
        "## Overall Read",
        "",
        overall_read,
        "",
        "## Reasons",
        "",
    ]
    lines.extend(f"- {reason}" for reason in synthesis.recommendation.reasons[:3] or ["No reason line was generated."])
    lines.extend(
        [
            "",
            "## Conditions / Asks",
            "",
        ]
    )
    lines.extend(f"- {condition}" for condition in synthesis.recommendation.conditions[:3] or ["No condition line was generated."])
    lines.extend(
        [
            "",
            "## What I Would Verify Personally",
            "",
        ]
    )
    lines.extend(f"- {item}" for item in verify_points[:3] or ["Personally verify the highest-ranked issue sources."])
    lines.extend(
        [
            "",
            "## Decision Readiness",
            "",
        ]
    )
    lines.append(f"- Status: {readiness_status}")
    lines.append(f"- Why: {readiness_reason}")
    if synthesis.challenge_findings:
        lines.extend(["", "## Likely IC Pushback", ""])
        lines.extend(_render_challenge_findings(synthesis.challenge_findings, limit=3))
    return "\n".join(lines) + "\n"


def _build_issue_registry_debug_markdown(synthesis: DealSynthesis) -> str:
    registry = synthesis.canonical_issue_registry
    lines = ["# Issue Registry Debug", ""]
    lines.extend(
        [
            "## Summary",
            "",
            f"- Fragments: {len(registry.fragments)}",
            f"- Canonical Issues: {len(registry.issues)}",
            f"- Merge Decisions: {len(registry.merge_decisions)}",
            f"- Arbitration Records: {len(registry.arbitration_records)}",
            "",
        ]
    )

    lines.extend(["## Canonical Issue Registry", ""])
    for issue in registry.issues:
        lines.append(f"### {issue.title}")
        lines.append(f"- Issue ID: `{issue.issue_id}`")
        lines.append(f"- Category: {issue.category}")
        lines.append(f"- Status: {issue.status}")
        lines.append(f"- Priority Score: {issue.priority_score.total}")
        lines.append(f"- Materiality: {issue.materiality}")
        lines.append(f"- Evidence Basis: {issue.evidence_basis}")
        lines.append(f"- Issue Strength: {issue.issue_strength}")
        lines.append(f"- False-Positive Risk: {issue.false_positive_risk}")
        lines.append(f"- Normal Friction: {issue.normal_friction_flag}")
        lines.append(f"- Decision Relevant: {issue.decision_relevant}")
        lines.append(f"- Top-Line Eligible: {issue.top_line_eligible}")
        if issue.top_line_filter_reasons:
            lines.append(f"- Filter Reasons: {', '.join(issue.top_line_filter_reasons)}")
        lines.append(f"- Output Bucket: {issue.output_bucket}")
        lines.append(f"- Decision Action: {issue.decision_action}")
        lines.append(f"- Source: {_format_citations(issue.citations[:3]) or ', '.join(issue.source_documents[:3]) or 'None'}")
        lines.append(f"- Merged Fragments: {', '.join(issue.merged_fragment_ids) or 'None'}")
        if issue.calibration_notes:
            lines.append(f"- Calibration Notes: {' | '.join(issue.calibration_notes)}")
        if issue.precedent_references:
            lines.append(
                f"- Precedent Hooks: {', '.join(reference.title for reference in issue.precedent_references[:3])}"
            )
        lines.append("")

    lines.extend(["## Merge Decisions", ""])
    if registry.merge_decisions:
        for decision in registry.merge_decisions:
            lines.append(f"- `{decision.canonical_issue_id}` <- {', '.join(decision.fragment_ids)}")
            lines.append(f"  Rationale: {decision.rationale}")
    else:
        lines.append("- No merge decisions were recorded.")
    lines.append("")

    lines.extend(["## Merge Arbitration", ""])
    if registry.arbitration_records:
        for record in registry.arbitration_records:
            lines.append(
                f"- `{record.left_key}` vs `{record.right_key}` -> {record.final_relation}"
                f" (deterministic={record.deterministic_relation}, confidence={record.deterministic_confidence}, used_arbiter={record.used_arbiter})"
            )
            if record.rationale:
                lines.append(f"  Rationale: {record.rationale}")
    else:
        lines.append("- No ambiguous merge arbitration was triggered.")
    lines.append("")

    lines.extend(["## Output Selections", ""])
    if registry.output_selections:
        for selection in registry.output_selections:
            lines.append(
                f"- `{selection.output_name}` rank {selection.rank}: `{selection.issue_id}` ({selection.reason})"
            )
    else:
        lines.append("- No output selections were recorded.")
    lines.append("")

    return "\n".join(lines)


def _build_reviewer_feedback_template_json(synthesis: DealSynthesis) -> str:
    rows = []
    for issue in synthesis.canonical_issue_registry.issues:
        rows.append(
            {
                "issue_id": issue.issue_id,
                "real_issue": None,
                "materiality": issue.materiality,
                "decision_relevant": issue.decision_relevant,
                "duplicate_of": None,
                "overstated": False,
                "understated": False,
                "correct_action": issue.decision_action,
                "notes": "",
            }
        )
    return json.dumps(rows, indent=2) + "\n"


def _selected_issues(
    synthesis: DealSynthesis,
    output_name: str,
    *,
    default_count: int,
) -> list[CanonicalIssue]:
    registry = synthesis.canonical_issue_registry
    if not registry.issues:
        return []
    if registry.output_selections:
        selected_ids = [
            selection.issue_id
            for selection in sorted(
                registry.output_selections,
                key=lambda item: (item.output_name, item.rank),
            )
            if selection.output_name == output_name
        ]
        if selected_ids:
            issue_by_id = {issue.issue_id: issue for issue in registry.issues}
            return [issue_by_id[issue_id] for issue_id in selected_ids if issue_id in issue_by_id]
    if output_name in {"01_executive_summary.md", "02_key_risks.md", "09_investment_committee_brief.md"}:
        return [issue for issue in registry.issues if issue.top_line_eligible][:default_count]
    return registry.issues[:default_count]


def _render_canonical_issue_risk_block(issue: CanonicalIssue, *, index: int) -> list[str]:
    lines = [f"### {index}. {issue.title}"]
    lines.append(f"- Why It Matters: {issue.why_it_matters}")
    lines.append(f"- Likely Implication: {issue.likely_implication}")
    lines.append(f"- What Would Resolve It: {issue.what_would_resolve_it}")
    lines.append(f"- Decision Action: {issue.decision_action}")
    if issue.gating_flags:
        lines.append(f"- Gating Impact: {', '.join(issue.gating_flags)}")
    lines.append(f"- Confidence: {issue.confidence}")
    source = _format_citations(issue.citations[:3]) or ", ".join(issue.source_documents[:3])
    if source:
        lines.append(f"- Source: {source}")
    lines.append("")
    return lines


def _build_executive_bullets(synthesis: DealSynthesis, issues: list[CanonicalIssue]) -> list[str]:
    bullets = [
        f"Recommendation posture: {synthesis.recommendation.posture}. {synthesis.recommendation.rationale}",
    ]
    for issue in issues[:4]:
        bullets.append(_with_light_citation(f"{issue.title}. {issue.likely_implication}", issue))
    if synthesis.contradictions:
        bullets.append(_with_light_citation(synthesis.contradictions[0].description, synthesis.contradictions[0]))
    return _unique_list(bullets)[:6]


def _build_pattern_lines(synthesis: DealSynthesis, issues: list[CanonicalIssue]) -> list[str]:
    if not issues:
        return ["No concentrated issue pattern was elevated from the current package."]

    categories = [issue.category for issue in issues]
    dominant_category = max(set(categories), key=categories.count)
    dominant_count = categories.count(dominant_category)
    pattern_lines = []
    if dominant_count >= 2:
        pattern_lines.append(
            f"Risk is concentrated around {dominant_category.lower()}, which suggests one underlying dependency is driving multiple downstream concerns."
        )
    else:
        pattern_lines.append(
            "Risk is concentrated in a small number of separate issues rather than across every diligence lane."
        )

    if any(issue.category in {"Title / Access Concerns", "Entitlement Status", "Offsite Obligations"} for issue in issues[:2]):
        pattern_lines.append(
            "This reads more like a land-control and pre-close scope-closure problem than a routine clean-up exercise."
        )
    else:
        pattern_lines.append(
            "This reads closer to a normal diligence package, but the top issue set is still strong enough to control basis or schedule."
        )

    posture = synthesis.recommendation.posture
    if posture in {"pause", "retrade", "no-go"}:
        pattern_lines.append(
            f"The current pattern is structurally fragile enough that the recommendation stays at '{posture}' until the lead issues are closed."
        )
    else:
        pattern_lines.append(
            f"The deal can continue under a '{posture}' posture, but only if the lead issues are resolved in the order shown."
        )
    return pattern_lines[:3]


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
    ocr_used_results = _ocr_used_results(run_summary)

    lines.append("## OCR Fallback Activity")
    lines.append("")
    if ocr_used_results:
        lines.append(
            f"- OCR fallback was required on {len(ocr_used_results)} file(s) across {sum(len(result.ocr_pages) for result in ocr_used_results)} page(s)."
        )
        lines.extend(
            _format_ocr_result_line(result, include_warning_summary=False)
            for result in ocr_used_results
        )
    else:
        lines.append("- OCR fallback was not used on this run.")

    lines.append("")
    lines.append("## OCR / Low Confidence Documents")
    lines.append("")
    if ocr_results:
        lines.extend(
            _format_ocr_result_line(result)
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
        if result.ocr_pages or any(_is_ocr_warning(warning) for warning in result.warnings)
    ]


def _is_ocr_warning(warning: str) -> bool:
    warning_lower = warning.lower()
    return (
        "ocr fallback" in warning_lower
        or "no pdf text extracted" in warning_lower
        or "normalized text is empty" in warning_lower
    )


def _ocr_used_results(run_summary: RunSummary) -> list:
    return [result for result in run_summary.file_results if result.ocr_pages]


def _format_page_list(pages: list[int]) -> str:
    return ", ".join(str(page) for page in pages)


def _format_ocr_result_line(result, *, include_warning_summary: bool = True) -> str:
    detail = f"- `{result.relative_path}`"
    if result.ocr_pages:
        detail += f": OCR pages {_format_page_list(result.ocr_pages)}"
        if result.ocr_recovered_pages:
            detail += f" | recovered {_format_page_list(result.ocr_recovered_pages)}"
    if include_warning_summary and result.warnings:
        detail += f" | warnings: {'; '.join(result.warnings)}"
    elif not result.ocr_pages and result.warnings:
        detail += f": {'; '.join(result.warnings)}"
    return detail


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

    if run_summary.analysis_mode == "fast":
        limitations.append("This run used fast mode, so document-level LLM refinement, contradiction detection, deep synthesis, and the IC brief were skipped.")

    if run_summary.llm_provider == "heuristic":
        limitations.append("This run used heuristic mode only; no OpenAI refinement was applied.")

    ocr_results = _ocr_affected_results(run_summary)
    if ocr_results:
        limitations.append(f"OCR-related extraction warnings affected {len(ocr_results)} document(s).")
    ocr_used_results = _ocr_used_results(run_summary)
    if ocr_used_results:
        limitations.append(
            f"OCR fallback was required on {len(ocr_used_results)} document(s) across {sum(len(result.ocr_pages) for result in ocr_used_results)} page(s)."
        )

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
    if risk.citations:
        lines.append(f"- Source: {_format_citations(risk.citations)}")
    elif risk.source_documents:
        lines.append(f"- Source: {', '.join(risk.source_documents)}")
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


def _render_fast_risk_block(risk) -> list[str]:
    lines = [f"### {risk.category}"]
    risk_text = " ".join(part for part in [risk.issue, risk.likely_implication] if part).strip() or risk.summary
    lines.append(f"- {risk_text}")
    if risk.citations:
        lines.append(f"- Source: {_format_citations(risk.citations[:2])}")
    elif risk.source_documents:
        lines.append(f"- Source: {', '.join(risk.source_documents[:2])}")
    if risk.gating_flags:
        lines.append(f"- Affects: {', '.join(risk.gating_flags)}")
    lines.append("")
    return lines


def _render_contradictions(contradictions: list) -> list[str]:
    if not contradictions:
        return ["- No material cross-document contradiction was isolated from the current package."]

    lines: list[str] = []
    for index, finding in enumerate(contradictions, start=1):
        lines.append(f"### Tension {index}")
        lines.append(f"- Description: {finding.description}")
        if finding.citations:
            lines.append(f"- Documents: {_format_citations(finding.citations)}")
        elif finding.source_documents:
            lines.append(f"- Documents: {', '.join(finding.source_documents)}")
        lines.append(f"- Why It Matters: {finding.why_it_matters}")
        lines.append("")
    return lines


def _render_challenge_findings(challenge_findings: list, *, limit: int) -> list[str]:
    if not challenge_findings:
        return ["- No adversarial challenge point was elevated from the current package."]

    lines: list[str] = []
    for finding in challenge_findings[:limit]:
        lines.append(f"- **{finding.heading}:** {finding.concern}")
        lines.append(f"  Why it matters: {finding.why_it_matters}")
        lines.append(f"  Likely pushback: {finding.likely_pushback}")
        if finding.citations:
            lines.append(f"  Source: {_format_citations(finding.citations[:2])}")
    return lines


def _build_priority_call_lines(synthesis: DealSynthesis) -> list[str]:
    assessment = synthesis.priority_assessment
    lines: list[str] = []

    for index, callout in enumerate(assessment.top_deal_shaping_issues[:3], start=1):
        lines.append(f"- Top deal-shaping issue {index}: {_priority_call_text(callout)}")
    if assessment.top_cost_risk is not None:
        lines.append(f"- Top cost risk: {_priority_call_text(assessment.top_cost_risk)}")
    if assessment.top_timing_risk is not None:
        lines.append(f"- Top timing risk: {_priority_call_text(assessment.top_timing_risk)}")
    if assessment.top_closability_risk is not None:
        lines.append(f"- Top closability risk: {_priority_call_text(assessment.top_closability_risk)}")

    if not lines:
        lines.append("- No priority callout was elevated beyond the current key-risk list.")
    return lines


def _priority_call_text(callout) -> str:
    if callout is None:
        return "No callout was built."
    text = f"{callout.statement} {callout.why_it_matters}".strip()
    if callout.citations:
        return f"{text} [Source: {_format_citations(callout.citations[:2])}]"
    return text


def _build_decision_framing_lines(synthesis: DealSynthesis) -> list[str]:
    readiness_status, readiness_reason = _evaluate_decision_readiness(synthesis)
    lines = [
        "### Top Decision Drivers",
        "",
    ]
    lines.extend(f"- {item}" for item in _build_top_decision_drivers(synthesis))
    lines.extend(
        [
            "",
            "### Gating Conditions",
            "",
        ]
    )
    lines.extend(f"- {item}" for item in _build_decision_gate_lines(synthesis))
    lines.extend(
        [
            "",
            "### Deal Breakers",
            "",
        ]
    )
    lines.extend(f"- {item}" for item in _build_deal_breakers(synthesis))
    lines.extend(
        [
            "",
            "### What Must Be Verified Personally",
            "",
        ]
    )
    lines.extend(f"- {item}" for item in _build_personal_verification_items(synthesis))
    lines.extend(
        [
            "",
            "### Decision Readiness",
            "",
            f"- Status: {readiness_status}",
            f"- Why: {readiness_reason}",
        ]
    )
    return lines


def _build_top_decision_drivers(synthesis: DealSynthesis) -> list[str]:
    issues = _selected_issues(synthesis, "01_executive_summary.md", default_count=4)
    if not issues:
        return ["No single decision driver clearly dominates the current package."]
    return [
        _with_light_citation(f"{issue.title}. {issue.why_it_matters}", issue)
        for issue in issues[:5]
    ]


def _build_decision_gate_lines(synthesis: DealSynthesis) -> list[str]:
    issues = synthesis.canonical_issue_registry.issues
    lines: list[str] = []
    for gate_name in ("Closing", "Underwriting confidence", "Vertical start"):
        gate_issues = [issue for issue in issues if gate_name in issue.gating_flags]
        contradictions = _contradictions_for_gate(synthesis, gate_name)
        actions = [_build_gate_action_text_from_issue(issue) for issue in gate_issues[:2]]
        actions.extend(_build_gate_action_from_contradiction(finding) for finding in contradictions[:1])
        if gate_name == "Underwriting confidence" and any(
            analysis.confidence == "low" for analysis in synthesis.document_analyses
        ):
            actions.append("replace unreadable budget or support files")

        actions = _unique_list(actions)
        if not actions:
            continue

        citations = _collect_gate_citations(gate_issues, contradictions)
        source_suffix = f" [Source: {_format_citations(citations)}]" if citations else ""
        lines.append(f"Before {gate_name.lower()}: {'; '.join(actions)}.{source_suffix}")

    if not lines:
        lines.append("No specific gating condition was isolated beyond the current diligence gaps.")
    return lines[:3]


def _build_deal_breakers(synthesis: DealSynthesis) -> list[str]:
    breakers: list[str] = []
    title_issue = _find_issue(synthesis, "title-access-clearance")
    offsite_issue = _find_issue(synthesis, "offsite-frontage")
    geotech_budget_issue = _find_issue(synthesis, "geotech-budget-alignment")
    title_tension = _find_contradiction_by_category(synthesis, {"Title / Access Concerns"})

    if title_issue is not None:
        breakers.append(
            _with_light_citation(
                "If the title and access exceptions cannot be cured, insured over, or designed around, the deal changes materially because closing and buildability are impaired.",
                title_tension or title_issue,
            )
        )
    if offsite_issue is not None:
        breakers.append(
            _with_light_citation(
                "If frontage, dedication, or offsite obligations stay buyer-facing on terms not reflected in basis, the deal changes materially on cost and schedule.",
                _find_contradiction_by_category(synthesis, {"Offsite Obligations"}) or offsite_issue,
            )
        )
    if geotech_budget_issue is not None:
        breakers.append(
            _with_light_citation(
                "If soils-driven grading, retaining, or foundation scope is not fully carried into cost, current underwriting is not reliable enough for approval.",
                geotech_budget_issue,
            )
        )

    if not breakers:
        breakers.append("No clear deal breaker is isolated from the current text, but the package is still too open for a clean approval.")

    return _unique_list(breakers)[:3]


def _build_personal_verification_items(synthesis: DealSynthesis) -> list[str]:
    items: list[str] = []
    for finding in synthesis.contradictions[:2]:
        items.append(_build_verify_point_from_contradiction(finding))

    covered_ids = {
        issue.issue_id
        for issue in synthesis.canonical_issue_registry.issues
        if any(issue.category in finding.related_categories for finding in synthesis.contradictions)
    }
    for issue in _selected_issues(synthesis, "09_investment_committee_brief.md", default_count=3):
        if issue.issue_id in covered_ids:
            continue
        items.append(_build_verify_point_from_issue(issue))
        if len(items) >= 4:
            break

    if not items:
        items.append("Personally review the highest-priority documents in the recommended reading order.")

    return _unique_list(items)[:4]


def _evaluate_decision_readiness(synthesis: DealSynthesis) -> tuple[str, str]:
    issues = synthesis.canonical_issue_registry.issues
    if (
        synthesis.contradictions
        or any("Closing" in issue.gating_flags for issue in issues)
        or any(assessment.status in {"not found", "unclear whether present"} for assessment in synthesis.omission_assessments)
        or any(
        analysis.confidence == "low" for analysis in synthesis.document_analyses
        )
    ):
        return (
            "Not ready",
            "Core documents still conflict on scope, access, or cost assumptions, and the package still has pre-closing or support gaps that change the recommendation.",
        )
    if any(issue.gating_flags for issue in issues):
        return (
            "Partially complete",
            "The package is substantive, but basis, permit, or execution items are still open enough that leadership should not treat it as fully underwritten.",
        )
    return (
        "Decision-ready",
        "The current package supports a clean view on closing, basis, and execution with no material contradiction still driving the recommendation.",
    )


def _build_gate_action_from_contradiction(finding) -> str:
    related = set(finding.related_categories)
    if "Title / Access Concerns" in related:
        return "confirm the access layout shown in the plans is fully supported by title"
    if "Offsite Obligations" in related:
        return "confirm whether frontage and offsite work are actually complete or still buyer-facing"
    if {"Geotechnical Risks", "Budget / Cost Reliability"}.issubset(related):
        return "confirm soils-driven scope is fully priced into the current cost package"
    if "Entitlement Status" in related:
        return "reconcile approval status against the remaining conditions of approval"
    return "reconcile the conflicting document assumptions"


def _contradictions_for_gate(synthesis: DealSynthesis, gate_name: str) -> list:
    gate_categories = {
        issue.category
        for issue in synthesis.canonical_issue_registry.issues
        if gate_name in issue.gating_flags
    }
    return [
        finding
        for finding in synthesis.contradictions
        if gate_categories.intersection(finding.related_categories)
    ]


def _collect_gate_citations(risks: list, contradictions: list) -> list:
    citations = []
    for finding in contradictions[:1]:
        citations.extend(finding.citations[:2])
    for risk in risks[:2]:
        citations.extend(risk.citations[:1])
    return _unique_citation_objects(citations)[:3]


def _build_verify_point_from_contradiction(finding) -> str:
    if finding.citations:
        source_text = _format_citations(finding.citations[:2])
        return f"Read {source_text} and decide which assumption controls underwriting: {finding.description}"
    if finding.source_documents:
        return f"Read {', '.join(finding.source_documents[:2])} and decide which assumption controls underwriting: {finding.description}"
    return f"Personally verify the contradiction: {finding.description}"


def _build_verify_point_from_risk(risk) -> str:
    source_text = _format_citations(risk.citations[:2]) or ", ".join(risk.source_documents[:2])
    return (
        f"Read {source_text or risk.category} and confirm whether the current underwriting treatment is actually supported for {risk.category.lower()}."
    )


def _build_verify_point_from_issue(issue: CanonicalIssue) -> str:
    source_text = _format_citations(issue.citations[:2]) or ", ".join(issue.source_documents[:2])
    return f"Read {source_text or issue.title} and confirm the current underwriting treatment for {issue.title.lower()}."


def _find_risk(synthesis: DealSynthesis, category: str):
    return next((risk for risk in synthesis.key_risks if risk.category == category), None)


def _find_issue(synthesis: DealSynthesis, issue_id: str):
    return next((issue for issue in synthesis.canonical_issue_registry.issues if issue.issue_id == issue_id), None)


def _find_contradiction_by_category(synthesis: DealSynthesis, categories: set[str]):
    return next((finding for finding in synthesis.contradictions if categories.intersection(finding.related_categories)), None)


def _unique_list(items: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        ordered.append(item)
    return ordered


def _unique_citation_objects(citations: list) -> list:
    seen = set()
    ordered = []
    for citation in citations:
        if citation in seen:
            continue
        seen.add(citation)
        ordered.append(citation)
    return ordered


def _with_light_citation(text: str, risk) -> str:
    citation_text = _format_citations(risk.citations[:1])
    if not citation_text:
        return text
    return f"{text} [Source: {citation_text}]"


def _format_citations(citations: list) -> str:
    if not citations:
        return ""
    parts: list[str] = []
    for citation in citations[:3]:
        if citation.page_number is not None:
            parts.append(f"{citation.document_name} p. {citation.page_number}")
        else:
            parts.append(citation.document_name)
    return "; ".join(parts)


def _build_executive_conclusions(synthesis: DealSynthesis) -> list[str]:
    conclusions: list[str] = []
    covered_categories: set[str] = set()

    for callout in synthesis.priority_assessment.top_deal_shaping_issues[:3]:
        conclusions.append(_priority_call_text(callout))
        if callout.category:
            covered_categories.add(callout.category)

    closability_callout = synthesis.priority_assessment.top_closability_risk
    if (
        closability_callout is not None
        and closability_callout.category
        and closability_callout.category not in covered_categories
        and len(conclusions) < 4
    ):
        conclusions.append(_priority_call_text(closability_callout))
        covered_categories.add(closability_callout.category)

    conclusions.extend(
        _with_light_citation(finding.description, finding)
        for finding in synthesis.contradictions[:2]
        if not covered_categories.intersection(finding.related_categories)
    )
    if any(analysis.confidence == "low" for analysis in synthesis.document_analyses):
        conclusions.append("At least one key cost or support file still requires manual review because extraction quality was weak.")
    if not conclusions:
        conclusions.append(synthesis.entitlement_status)
    return _unique_list(conclusions)[:5]


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
    points = [_with_light_citation(finding.description, finding) for finding in synthesis.contradictions[:2]]
    points.extend(_with_light_citation(risk.issue, risk) for risk in primary_risks[:3] if risk.issue)
    for issue in synthesis.issue_analyses[:2]:
        if issue.unresolved_questions:
            points.append(f"{issue.label}: {issue.unresolved_questions[0]}")
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
    if synthesis.contradictions:
        points.append("Where documents conflict, underwrite to the more conservative assumption until the contradiction is reconciled with direct support.")
    if any(analysis.confidence == "low" for analysis in synthesis.document_analyses):
        points.append("Do not treat the current cost package as fully decision-grade until unreadable or budgetary files are replaced with native support.")
    return points[:5]


def _build_ic_overall_read(synthesis: DealSynthesis) -> str:
    issues = _selected_issues(synthesis, "09_investment_committee_brief.md", default_count=3)
    if not issues:
        return "The package does not surface a concentrated issue, but it still needs a completeness check before it is treated as decision-ready."

    lead = issues[0]
    text = (
        f"The recommendation is '{synthesis.recommendation.posture}' because {lead.title.lower()} is still open. "
        f"{lead.likely_implication}"
    )
    if len(issues) > 1:
        text += f" The next issue is {issues[1].title.lower()}."
    if synthesis.challenge_findings:
        text += f" Expected IC pushback: {synthesis.challenge_findings[0].likely_pushback}"
    return text


def _build_ic_biggest_risks(synthesis: DealSynthesis) -> list[str]:
    risks = [_priority_call_text(callout) for callout in synthesis.priority_assessment.top_deal_shaping_issues[:3]]
    if synthesis.priority_assessment.top_cost_risk is not None:
        risks.append(_priority_call_text(synthesis.priority_assessment.top_cost_risk))
    return _unique_list(risks)[:4] or ["No concentrated issue was elevated into a top risk."]


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
    unknowns.extend(f"{finding.heading}: {finding.concern}" for finding in synthesis.challenge_findings[:2])
    unknowns.extend(_with_light_citation(finding.description, finding) for finding in synthesis.contradictions[:1])
    primary_risks, _ = _split_risk_tiers(synthesis.key_risks)
    unknowns.extend(
        f"{risk.category}: {risk.uncertainty_reason}"
        for risk in primary_risks[:3]
        if risk.uncertainty_reason
    )
    return unknowns[:4] or ["No major unknown was surfaced from the current package."]


def _build_ic_verify_points(synthesis: DealSynthesis) -> list[str]:
    return _build_personal_verification_items(synthesis)


def _build_decision_ready_assessment(synthesis: DealSynthesis) -> str:
    status, reason = _evaluate_decision_readiness(synthesis)
    return f"{status}. {reason}"


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


def _build_gate_action_text_from_issue(issue: CanonicalIssue) -> str:
    if issue.what_would_resolve_it:
        return issue.what_would_resolve_it[0].lower() + issue.what_would_resolve_it[1:]
    return _build_gate_action_text(issue)
