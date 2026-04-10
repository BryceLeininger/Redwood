"""Write structured Markdown outputs for a diligence run."""

from __future__ import annotations

import re
from collections import Counter
import json
from pathlib import Path

from land_due_diligence_agent.analysis.front_end import (
    cost_exposure_band_for_issue,
    deal_impact_magnitude_for_issue,
    deal_impact_mechanism_for_issue,
    deal_impact_summary_issues,
    deal_impact_type_for_issue,
    fixability_classification_for_issue,
    if_wrong_line_for_issue,
    timing_exposure_band_for_issue,
    underwrite_confidence_level,
    underwrite_confidence_limiters,
    underwrite_confidence_reason,
)
from land_due_diligence_agent.analysis.issue_registry import build_reviewer_feedback_template
from land_due_diligence_agent.models import CanonicalIssue, DealSynthesis, RunSummary
from land_due_diligence_agent.utils.text import normalize_text


_ACQUISITION_BUCKETS = (
    "True Deal Killers",
    "Primary Drivers of Price",
    "Secondary Execution Risks",
    "Noise",
)


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
        executive_summary_content = _build_executive_summary_markdown(
            synthesis,
            run_summary.llm_provider,
            run_summary,
        )
        key_risks_content = _build_key_risks_markdown(synthesis, run_summary.analysis_mode)
        seller_questions_content = _build_seller_questions_markdown(synthesis, run_summary.analysis_mode)
        files.extend(
            [
                (output_dir / "01_executive_summary.md", executive_summary_content),
                (output_dir / "02_key_risks.md", key_risks_content),
                (output_dir / "04_seller_questions.md", seller_questions_content),
            ]
        )
        if run_summary.analysis_mode == "full":
            reading_order_content = _build_reading_order_markdown(synthesis)
            document_summaries_content = _build_document_summaries_markdown(synthesis)
            missing_items_content = _build_missing_items_markdown(synthesis)
            deal_synthesis_content = _build_deal_synthesis_markdown(synthesis)
            ic_brief_content = _build_investment_committee_brief_markdown(synthesis)
            issue_analysis_content = _build_issue_analysis_markdown(synthesis)
            roadmap_content = _build_further_diligence_roadmap_markdown(synthesis)
            web_research_content = _build_web_research_markdown(synthesis)
            debug_content = _build_issue_registry_debug_markdown(
                synthesis,
                section_texts={
                    "01_executive_summary.md": executive_summary_content,
                    "02_key_risks.md": key_risks_content,
                    "07_deal_synthesis.md": deal_synthesis_content,
                    "13_further_diligence_roadmap.md": roadmap_content,
                },
            )
            files.extend(
                [
                    (output_dir / "03_recommended_reading_order.md", reading_order_content),
                    (output_dir / "05_document_summaries.md", document_summaries_content),
                    (output_dir / "06_missing_diligence_items.md", missing_items_content),
                    (output_dir / "07_deal_synthesis.md", deal_synthesis_content),
                    (output_dir / "09_investment_committee_brief.md", ic_brief_content),
                    (output_dir / "10_issue_analysis.md", issue_analysis_content),
                    (output_dir / "11_issue_registry_debug.md", debug_content),
                    (output_dir / "12_reviewer_feedback_template.json", _build_reviewer_feedback_template_json(synthesis)),
                    (output_dir / "13_further_diligence_roadmap.md", roadmap_content),
                    (output_dir / "14_web_research.md", web_research_content),
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
        "13_further_diligence_roadmap.md",
        "14_web_research.md",
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
                f"- Web fallback queries: {run_summary.web_research_queries}",
                f"- Autonomous learning records: {run_summary.autonomous_learning_records}",
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
    registry = synthesis.canonical_issue_registry
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
        "## Conclusions",
        "",
    ]
    lines.extend(
        [
            f"- Package read: {registry.package_quality or 'adequate'}.",
            f"- Confidence in initial read: {registry.confidence_in_initial_read}.",
            f"- Overall read: {_compress_statement(synthesis.executive_summary or synthesis.entitlement_status, max_words=26, max_sentences=2, single_idea=False)}",
        ]
    )
    lines.extend(["", "## Deal Impact Summary", ""])
    impact_issues = deal_impact_summary_issues(top_issues or registry.issues, limit=3)
    if impact_issues:
        for issue in impact_issues:
            lines.append(
                "- "
                + _compress_statement(
                    (
                        f"{issue.title}: impact type {deal_impact_type_for_issue(issue)}; "
                        f"magnitude {deal_impact_magnitude_for_issue(issue)}; "
                        f"cost {cost_exposure_band_for_issue(issue)}; "
                        f"timing {timing_exposure_band_for_issue(issue)}"
                    ),
                    max_words=26,
                    single_idea=False,
                )
            )
    else:
        lines.append("- No CRITICAL or HIGH issue currently rises high enough to reshape the deal beyond routine diligence judgment.")
    lines.extend(["", "## Underwrite Confidence", ""])
    confidence_level = underwrite_confidence_level(
        registry=registry,
        omission_assessments=synthesis.omission_assessments,
        contradictions=synthesis.contradictions,
        document_analyses=synthesis.document_analyses,
        issues=top_issues or registry.issues,
    )
    confidence_reason = underwrite_confidence_reason(
        registry=registry,
        omission_assessments=synthesis.omission_assessments,
        contradictions=synthesis.contradictions,
        document_analyses=synthesis.document_analyses,
        issues=top_issues or registry.issues,
    )
    lines.append(f"- Current level: {confidence_level}.")
    lines.append(f"- Why: {_compress_statement(confidence_reason, max_words=26, single_idea=False)}")
    for line in underwrite_confidence_limiters(
        registry=registry,
        omission_assessments=synthesis.omission_assessments,
        contradictions=synthesis.contradictions,
        document_analyses=synthesis.document_analyses,
        issues=top_issues or registry.issues,
        limit=2,
    ):
        lines.append(f"- Assumption carrying the underwrite: {_compress_statement(line, max_words=24, single_idea=False)}")
    lines.extend(["", "### If Wrong, What Happens?", ""])
    if impact_issues:
        for issue in impact_issues:
            lines.append(
                f"- {issue.title}: {_compress_statement(f'The downside is a worse {deal_impact_type_for_issue(issue)} outcome than the current basis implies.', max_words=18, single_idea=False)}"
            )
    else:
        lines.append("- If the remaining assumptions break, the deal can still move on price, timing, or closability faster than the current package implies.")
    lines.extend(["", "## Biggest Flags", ""])
    if top_issues:
        for issue in top_issues:
            lines.append(f"- [{_front_end_flag_label(issue)}] {issue.title}.")
    else:
        lines.append("- No concentrated red or yellow flag was elevated from the current package.")
    lines.extend(["", "## Biggest Blind Spots", ""])
    lines.extend(
        f"- {_compress_statement(item, max_words=24, single_idea=False)}"
        for item in (
            registry.front_end_unresolved_points
            or ["No major blind spot was isolated beyond the current issue set."]
        )[:5]
    )
    if run_summary.analysis_mode == "full":
        lines.extend(
            [
                "",
                "## Read First",
                "",
            ]
        )
        lines.extend(
            f"- {_read_first_line(item)}"
            for item in synthesis.recommended_reading_order
            if item.bucket == "must read personally"
        )
        if not any(item.bucket == "must read personally" for item in synthesis.recommended_reading_order):
            lines.append("- No single document was elevated to a must-read personally tier.")
    lines.extend(
        [
            "",
            "## Known Limitations Of This Run",
            "",
        ]
    )
    lines.extend(f"- {_compress_statement(item, max_words=18)}" for item in limitations)
    return "\n".join(lines) + "\n"


def _build_key_risks_markdown(synthesis: DealSynthesis, analysis_mode: str) -> str:
    lines = ["# Key Risks", ""]
    issues = _selected_issues(
        synthesis,
        "02_key_risks.md",
        default_count=3 if analysis_mode == "fast" else 5,
    )
    if not issues:
        lines.append("No concentrated red or yellow flag was elevated from the current package.")
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
    for bucket in ("must read personally", "should skim", "safe to rely on agent"):
        recommendations = [
            recommendation
            for recommendation in synthesis.recommended_reading_order
            if recommendation.bucket == bucket
        ]
        if not recommendations:
            continue
        lines.append(f"## {bucket.title()}")
        lines.append("")
        for index, recommendation in enumerate(recommendations, start=1):
            lines.append(f"{index}. **{recommendation.title}** (`{recommendation.relative_path}`)")
            lines.append(f"   Priority Score: {recommendation.priority}")
            lines.append(f"   Role: {recommendation.document_role}")
            lines.append(f"   Reason: {recommendation.reason}")
            lines.append(f"   Confidence: {recommendation.confidence}")
            if recommendation.focus_areas:
                lines.append(f"   Focus Areas: {', '.join(recommendation.focus_areas)}")
            if recommendation.rationale_factors:
                lines.append(f"   Why This Bucket: {', '.join(recommendation.rationale_factors)}")
            lines.append("")
    lines.extend(
        [
            "## Package Read",
            "",
            f"- Package Quality: {synthesis.canonical_issue_registry.package_quality or 'adequate'}",
            f"- Confidence In Initial Read: {synthesis.canonical_issue_registry.confidence_in_initial_read}",
        ]
    )
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
        lines.append(f"- Review Bucket: {analysis.reading_bucket}")
        lines.append(f"- Document Role: {analysis.document_role}")
        lines.append(f"- Reading Priority: {analysis.reading_priority}")
        lines.append(f"- Reading Rationale: {analysis.reading_reason}")
        lines.append(f"- Confidence: {analysis.confidence} ({analysis.confidence_reason})")
        lines.append(f"- Staleness: {analysis.staleness_status} ({analysis.staleness_reason})")
        lines.append(f"- Contradiction Count: {analysis.contradiction_count}")
        if analysis.focus_areas:
            lines.append(f"- Focus Areas: {', '.join(analysis.focus_areas)}")
        if analysis.reading_rationale_factors:
            lines.append(f"- Reading Factors: {', '.join(analysis.reading_rationale_factors)}")
        if analysis.document.ocr_pages:
            lines.append(f"- OCR Pages: {_format_page_list(analysis.document.ocr_pages)}")
        if analysis.document.warnings:
            lines.append(f"- Extraction Warnings: {'; '.join(analysis.document.warnings)}")
        lines.append("")
        lines.append("### Front-End Read")
        lines.append(f"- {_compress_statement(analysis.document_takeaway or analysis.summary, max_words=22, max_sentences=2, single_idea=False)}")
        lines.append("")

        if analysis.key_points:
            lines.append("### What It Establishes")
            lines.extend(
                f"- {_compress_statement(point, max_words=22, max_sentences=1, single_idea=False)}"
                for point in analysis.key_points[:3]
            )
            lines.append("")

        if analysis.open_loops:
            lines.append("### What It Still Leaves Open")
            lines.extend(
                f"- {_compress_statement(point, max_words=22, max_sentences=1, single_idea=False)}"
                for point in analysis.open_loops[:3]
            )
            lines.append("")

        linked_issues = _linked_issues_for_document(synthesis, analysis)
        if linked_issues:
            lines.append("### Linked Deal Issues")
            for issue in linked_issues[:3]:
                basis = issue.site_specific_trigger or (issue.core_facts[0] if issue.core_facts else issue.why_it_matters)
                lines.append(
                    f"- {issue.title} [{_front_end_flag_label(issue).lower()}]: {_compress_statement(basis, max_words=20, single_idea=False)}"
                )
            lines.append("")

        specific_risks = [risk for risk in analysis.risks if not getattr(risk, "generic_signal_only", False)]
        if specific_risks:
            lines.append("### Document-Specific Signals")
            for risk in specific_risks[:4]:
                lines.append(
                    f"- {risk.category} ({risk.severity}): {_compress_statement(risk.summary, max_words=20, max_sentences=1, single_idea=False)}"
                )
            lines.append("")

        if analysis.seller_questions:
            lines.append("### Next Questions")
            for question in analysis.seller_questions[:5]:
                lines.append(f"- {_compress_statement(question, max_words=20, max_sentences=1, single_idea=False)}")
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _linked_issues_for_document(synthesis: DealSynthesis, analysis) -> list[CanonicalIssue]:
    aliases = {
        analysis.document.title.lower(),
        analysis.document.relative_path.name.lower(),
        analysis.document.relative_path.as_posix().lower(),
    }
    linked: list[CanonicalIssue] = []
    for issue in synthesis.canonical_issue_registry.issues:
        source_aliases = {name.lower() for name in issue.source_documents}
        source_aliases.update(citation.document_name.lower() for citation in issue.citations)
        if not aliases.intersection(source_aliases):
            continue
        linked.append(issue)
    linked.sort(
        key=lambda issue: (
            -int(issue.top_line_eligible),
            -int(issue.front_end_flag in {"red flag", "yellow flag", "conflict / contradiction concern"}),
            -int(issue.specificity_level == "clearly site-specific"),
            -issue.priority_score.total,
            issue.title,
        )
    )
    return linked


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
        lines.append(f"- Front-End Flag: {issue.front_end_flag}")
        lines.append(f"- Information Status: {issue.information_status}")
        lines.append(f"- Normality: {issue.normality_classification}")
        lines.append(f"- Why Now: {issue.why_now}")
        if issue.citations:
            lines.append(f"- Source: {_format_citations(issue.citations)}")
        elif issue.source_documents:
            lines.append(f"- Source: {', '.join(issue.source_documents)}")
        lines.append("")
        lines.append("### Front-End Read")
        lines.append(f"- Status: {_issue_status_line(issue)}")
        lines.append(f"- Flag Reason: {_compress_statement(issue.front_end_flag_reason, max_words=20)}")
        lines.append(f"- Information Read: {_compress_statement(issue.information_status_reason, max_words=20)}")
        lines.append(f"- Routine vs Unusual Read: {_compress_statement(issue.unusualness_rationale, max_words=18)}")
        lines.append(f"- Process Friction: {'Yes' if issue.process_friction_flag else 'No'}")
        if issue.blocking_reason:
            lines.append(f"- Blocking Read: {_compress_statement(issue.blocking_reason, max_words=20)}")
        lines.append("")
        lines.append("### Core Facts")
        if issue.core_facts:
            lines.extend(f"- {_compress_statement(fact, max_words=18)}" for fact in issue.core_facts[:4])
        else:
            lines.append("- No concentrated fact pattern was isolated in this lane.")
        lines.append("")
        lines.append("### Best Evidence")
        if issue.best_evidence:
            lines.extend(f"- {_compress_statement(evidence, max_words=18)}" for evidence in issue.best_evidence[:3])
        else:
            lines.append("- No short-form evidence snippet was captured.")
        lines.append("")
        lines.append("### Unresolved Questions")
        if issue.open_questions:
            lines.extend(f"- {_compress_statement(question, max_words=18)}" for question in issue.open_questions[:4])
        else:
            lines.append("- No unresolved question was isolated beyond the current cited facts.")
        lines.append("")
        lines.append("### Missing Document / Confirmation")
        lines.append(
            f"- {_compress_statement(issue.missing_confirmation, max_words=18) if issue.missing_confirmation else 'No additional missing confirmation was isolated beyond the cited support.'}"
        )
        lines.append("")
        lines.append("### Suggested Next Research Step")
        if issue.research_agenda:
            for step in issue.research_agenda[:2]:
                lines.append(f"- Verify: {_compress_statement(step.verify_what, max_words=16)}")
                lines.append(f"- Request: {_compress_statement(_request_action_text(step.request_item), max_words=16)}")
                lines.append(f"- Best Source: {_compress_statement(step.likely_source, max_words=12)}")
                lines.append(f"- When: {step.timing}")
        else:
            lines.append("- No separate research step was elevated for this issue.")
        lines.append("")
        lines.append("### Why It Matters")
        lines.append(f"- {_compress_statement(issue.why_it_matters, max_words=18)}")
        lines.append("")
        lines.append("### Likely Implication")
        lines.append(f"- {_compress_statement(issue.likely_implication, max_words=18)}")
        lines.append("")
        lines.append("### What Would Resolve It")
        lines.append(f"- {_compress_statement(issue.what_would_resolve_it, max_words=18)}")
        lines.append("")
        lines.append("### Dependency Read")
        lines.append(f"- Dependency Type: {issue.dependency_type or 'n/a'}")
        lines.append(f"- Classification: {issue.blocker_classification} | {issue.schedule_impact_classification}")
        lines.append(f"- Critical Path: {'Yes' if issue.critical_path_flag else 'No'}")
        lines.append(f"- Blocking: {'Yes' if issue.blocking_flag else 'No'}")
        if issue.upstream_dependencies:
            lines.append("- Upstream Dependencies: " + ", ".join(link.title for link in issue.upstream_dependencies[:3]))
        else:
            lines.append("- Upstream Dependencies: None")
        if issue.downstream_dependencies:
            lines.append("- Downstream Dependencies: " + ", ".join(link.title for link in issue.downstream_dependencies[:3]))
        else:
            lines.append("- Downstream Dependencies: None")
        if issue.blocking_reason:
            lines.append(f"- Blocking Read: {issue.blocking_reason}")
        if issue.critical_path_reason:
            lines.append(f"- Critical Path Read: {issue.critical_path_reason}")
        lines.append("")
        lines.append("### Downstream Consequences")
        lines.append(f"- Cost: {_compress_statement(issue.likely_cost_effect, max_words=16) if issue.likely_cost_effect else 'None isolated.'}")
        lines.append(f"- Schedule: {_compress_statement(issue.likely_schedule_effect, max_words=16) if issue.likely_schedule_effect else 'None isolated.'}")
        lines.append(f"- Yield / Product: {_compress_statement(issue.likely_yield_or_product_effect, max_words=16) if issue.likely_yield_or_product_effect else 'None isolated.'}")
        lines.append(f"- Closing: {_compress_statement(issue.likely_closing_effect, max_words=16) if issue.likely_closing_effect else 'None isolated.'}")
        lines.append(f"- Structure: {_compress_statement(issue.likely_structure_effect, max_words=16) if issue.likely_structure_effect else 'None isolated.'}")
        lines.append(f"- Underwriting: {_compress_statement(issue.likely_underwriting_effect, max_words=16) if issue.likely_underwriting_effect else 'None isolated.'}")
        lines.append("")
        lines.append("### Deal Impact")
        lines.append(f"- Impact Type: {deal_impact_type_for_issue(issue)}")
        lines.append(f"- Magnitude: {deal_impact_magnitude_for_issue(issue)}")
        lines.append(f"- Mechanism: {_compress_statement(deal_impact_mechanism_for_issue(issue), max_words=18, single_idea=False)}")
        lines.append(f"- Cost Exposure: {cost_exposure_band_for_issue(issue)}")
        lines.append(f"- Timing Exposure: {timing_exposure_band_for_issue(issue)}")
        lines.append(f"- Fixability: {fixability_classification_for_issue(issue)}")
        lines.append("")
        lines.append("### If Wrong, What Happens?")
        lines.append(f"- {_compress_statement(if_wrong_line_for_issue(issue), max_words=18, single_idea=False)}")
        lines.append("")
        if issue.precedent_summary.sample_size:
            lines.append("### Precedent Read")
            lines.append(f"- Historical Frequency: {issue.precedent_summary.historical_frequency}")
            lines.append(f"- Real Rate: {_format_percentage(issue.precedent_summary.real_rate)}")
            lines.append(f"- False-Positive Rate: {_format_percentage(issue.precedent_summary.false_positive_rate)}")
            if issue.precedent_summary.outcome_stats:
                lines.append(
                    "- Outcome Stats: "
                    + ", ".join(
                        f"{label}={count}"
                        for label, count in sorted(issue.precedent_summary.outcome_stats.items())
                    )
                )
            lines.append(f"- Typical Impact: {_compress_statement(issue.precedent_summary.typical_impact, max_words=12)}")
            lines.append(f"- Resolution Pattern: {_compress_statement(issue.precedent_summary.resolution_pattern, max_words=16)}")
            lines.append(
                f"- Calibration: {issue.precedent_summary.confidence_adjustment} "
                f"({issue.precedent_summary.score_adjustment:+d} priority points)"
            )
            lines.append(f"- Read: {_compress_statement(issue.precedent_summary.reasoning, max_words=18)}")
            lines.append("")
        if issue.learning_summary.sample_size:
            lines.append("### Learned Read")
            lines.append(f"- Sample Size: {issue.learning_summary.sample_size}")
            lines.append(f"- Real-Issue Rate: {_format_percentage(issue.learning_summary.real_issue_rate)}")
            lines.append(f"- False-Positive Rate: {_format_percentage(issue.learning_summary.false_positive_rate)}")
            lines.append(f"- Material-Issue Rate: {_format_percentage(issue.learning_summary.material_issue_rate)}")
            lines.append(f"- Decision-Relevant Rate: {_format_percentage(issue.learning_summary.decision_relevant_rate)}")
            lines.append(f"- Impact Rate: {_format_percentage(issue.learning_summary.impact_rate)}")
            if issue.learning_summary.matched_features:
                lines.append(
                    "- Matched Features: "
                    + ", ".join(issue.learning_summary.matched_features[:4])
                )
            lines.append(
                f"- Calibration: {issue.learning_summary.confidence_adjustment} "
                f"({issue.learning_summary.score_adjustment:+d} priority points)"
            )
            lines.append(f"- Read: {_compress_statement(issue.learning_summary.reasoning, max_words=20)}")
            lines.append("")
        web_result = _web_research_by_issue_id(synthesis, issue.issue_id)
        if web_result is not None:
            lines.append("### Public Web Check")
            lines.append(f"- Status: {web_result.status} | Confidence: {web_result.confidence}")
            lines.append(f"- Question: {_compress_statement(web_result.question, max_words=18)}")
            lines.append(f"- Answer: {_compress_statement(web_result.answer or 'No public answer was isolated.', max_words=22)}")
            if web_result.next_step:
                lines.append(f"- Next Step: {_compress_statement(web_result.next_step, max_words=18)}")
            if web_result.source_titles:
                lines.append("- Sources: " + ", ".join(web_result.source_titles[:3]))
            if web_result.note:
                lines.append(f"- Note: {_compress_statement(web_result.note, max_words=18)}")
            lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def _build_missing_items_markdown(synthesis: DealSynthesis) -> str:
    lines = ["# Missing Diligence Items", ""]
    grouped = {
        "missing and important": [],
        "missing but normally expected": [],
        "stale and potentially unreliable": [],
        "conflicting across documents": [],
        "present and adequate": [],
    }
    for assessment in synthesis.omission_assessments:
        grouped.setdefault(assessment.front_end_status or assessment.status, []).append(assessment)

    for status in (
        "missing and important",
        "missing but normally expected",
        "stale and potentially unreliable",
        "conflicting across documents",
        "present and adequate",
    ):
        assessments = grouped.get(status, [])
        if not assessments:
            continue
        lines.append(f"## {status.title()}")
        lines.append("")
        for assessment in assessments:
            source = _format_citations(assessment.citations[:2]) or ", ".join(assessment.source_documents[:2])
            suffix = f" [Source: {source}]" if source else ""
            lines.append(f"- **{assessment.item}:** {assessment.front_end_reason or assessment.rationale}{suffix}")
            if assessment.recommended_request:
                lines.append(f"  Request Next: {assessment.recommended_request}")
        lines.append("")

    if not synthesis.omission_assessments:
        lines.append("- No omission assessment was generated.")

    if synthesis.extraction_errors:
        lines.append("")
        lines.append("## Extraction Errors")
        lines.extend(f"- {error}" for error in synthesis.extraction_errors)
    return "\n".join(lines) + "\n"


def _build_deal_synthesis_markdown(synthesis: DealSynthesis) -> str:
    judgment = synthesis.acquisition_judgment
    risk_groups = {
        bucket: [item for item in judgment.risk_items if item.bucket == bucket]
        for bucket in _ACQUISITION_BUCKETS
    }
    lines = [
        "# Deal Synthesis",
        "",
        "## Sanity Check / Corrections",
        "",
    ]
    if judgment.sanity_corrections:
        for correction in judgment.sanity_corrections:
            lines.append(
                f"- {correction.fact_type.replace('_', ' ').title()}: corrected to {correction.corrected_value}. Prior read: {correction.prior_value}. Why prior read was wrong: {correction.why_prior_was_wrong} Credible interpretation: {correction.credible_interpretation}"
            )
    else:
        lines.append("- No controlling fact required a second-pass sanity correction beyond the current readable package.")

    lines.extend([
        "",
        "## Controlling Facts",
        "",
    ])
    if judgment.controlling_facts:
        for fact in judgment.controlling_facts:
            rejected = f" Rejected alternatives: {', '.join(fact.rejected_alternatives[:3])}." if fact.rejected_alternatives else ""
            lines.append(
                f"- {fact.label}: {fact.controlling_value}. Control document: {fact.controlling_document}. Why it controls: {fact.why_it_controls}.{rejected}"
            )
    else:
        lines.append("- The second pass did not isolate a controlling answer for the core underwriting descriptors from the current readable package.")

    lines.extend(["", "## Real Risk Classification", ""])
    for bucket in _ACQUISITION_BUCKETS:
        lines.extend([f"### {bucket}", ""])
        items = risk_groups[bucket]
        if not items:
            lines.append(f"- No item currently lands in {bucket.lower()}.")
            lines.append("")
            continue
        for item in items[:5]:
            lines.append(f"- {_acquisition_risk_markdown_line(item)}")
        lines.append("")

    lines.extend(["## Critical Path / Gating Chain", ""])
    for target in ("Final Map", "Grading Permit", "Vertical Start"):
        lines.extend([f"### {target}", ""])
        steps = [step for step in judgment.critical_path if step.target == target]
        if not steps:
            lines.append(f"- No stage-specific blocker was isolated for {target.lower()} beyond the current general issue set.")
            lines.append("")
            continue
        for step in steps:
            lines.append(f"- Step {step.sequence}: {step.blocker}. {step.why_it_blocks}")
        lines.append("")

    decision = judgment.investment_decision
    lines.extend(["## Investment Decision", ""])
    lines.append(f"- Decision: {decision.posture}. {decision.rationale}")
    lines.append("- Top 3 real risks:")
    lines.extend(f"- {item}" for item in (decision.top_real_risks or ["No real risk currently rises above routine diligence noise in the second-pass classification."]))
    lines.append("- Price / structure changes:")
    lines.extend(f"- {item}" for item in (decision.price_or_structure_changes or ["No specific price or structure change currently rises above routine contingency management."]))
    lines.append(f"- Single biggest unknown: {decision.biggest_unknown or 'No single unknown currently stands above the rest of the issue set.'}")
    lines.append("- What has to be true:")
    lines.extend(f"- {item}" for item in (decision.what_has_to_be_true or ["No additional gating condition rises above the current reset risk ranking."]))
    lines.append("- Risks underwritten:")
    lines.extend(f"- {item}" for item in (decision.risks_underwritten or ["No execution risk is currently being affirmatively underwritten beyond routine project friction."]))
    lines.append("- Treated as solved:")
    lines.extend(f"- {item}" for item in (decision.treated_as_solved or ["No lane should currently be treated as solved beyond document-backed descriptors."]))

    lines.extend(["", "## What A Weak Acquisitions Person Would Miss", ""])
    if judgment.weak_acquisition_misses:
        for insight in judgment.weak_acquisition_misses:
            lines.append(f"- {insight.title}: {insight.detail}")
    else:
        lines.append("- The second pass did not isolate three non-obvious points beyond the existing issue ranking.")

    lines.extend(["", "## Initial Judgment", ""])
    lines.extend(f"- {item}" for item in _build_synthesis_judgment_lines(synthesis))
    lines.extend(["", "## Routine Vs Elevated", ""])
    lines.extend(f"- {item}" for item in _build_routine_vs_elevated_lines(synthesis))
    lines.extend(["", "## Critical Path", ""])
    lines.extend(f"- {item}" for item in _build_synthesis_critical_path_lines(synthesis))
    lines.extend(["", "## What Changes Confidence", ""])
    lines.extend(f"- {item}" for item in _build_confidence_change_lines(synthesis))

    return "\n".join(lines) + "\n"


def _build_investment_committee_brief_markdown(synthesis: DealSynthesis) -> str:
    judgment = synthesis.acquisition_judgment
    readiness_status, readiness_reason = _evaluate_decision_readiness(synthesis)
    registry = synthesis.canonical_issue_registry
    impact_issues = deal_impact_summary_issues(_selected_issues(synthesis, "09_investment_committee_brief.md", default_count=3), limit=3)
    confidence_level = underwrite_confidence_level(
        registry=registry,
        omission_assessments=synthesis.omission_assessments,
        contradictions=synthesis.contradictions,
        document_analyses=synthesis.document_analyses,
        issues=impact_issues or registry.issues,
    )
    confidence_reason = underwrite_confidence_reason(
        registry=registry,
        omission_assessments=synthesis.omission_assessments,
        contradictions=synthesis.contradictions,
        document_analyses=synthesis.document_analyses,
        issues=impact_issues or registry.issues,
    )
    risk_groups = {
        bucket: [item for item in judgment.risk_items if item.bucket == bucket]
        for bucket in _ACQUISITION_BUCKETS
    }
    decision = judgment.investment_decision

    lines = [
        "# Investment Committee Brief",
        "",
        f"**Recommendation:** {decision.posture}",
        f"**Package Read:** {registry.package_quality or 'credible'}",
        f"**Confidence In Initial Read:** {registry.confidence_in_initial_read}",
        f"**Underwrite Confidence:** {confidence_level}",
        "",
        "## Sanity Check / Corrections",
        "",
    ]
    if judgment.sanity_corrections:
        for correction in judgment.sanity_corrections:
            lines.append(
                f"- {correction.fact_type.replace('_', ' ').title()}: corrected to {correction.corrected_value}. Prior read: {correction.prior_value}. Why prior read was wrong: {correction.why_prior_was_wrong} Credible interpretation: {correction.credible_interpretation}"
            )
    else:
        lines.append("- No controlling fact required a second-pass sanity correction beyond the current readable package.")

    lines.extend([
        "",
        "## Controlling Facts",
        "",
    ])
    if judgment.controlling_facts:
        for fact in judgment.controlling_facts:
            rejected = f" Rejected alternatives: {', '.join(fact.rejected_alternatives[:3])}." if fact.rejected_alternatives else ""
            lines.append(f"- {fact.label}: {fact.controlling_value}. Control document: {fact.controlling_document}. Why it controls: {fact.why_it_controls}.{rejected}")
    else:
        lines.append("- The second pass did not isolate a controlling answer for the core underwriting descriptors from the current readable package.")

    lines.extend(["", "## Real Risk Classification", ""])
    for bucket in _ACQUISITION_BUCKETS:
        lines.extend([f"### {bucket}", ""])
        items = risk_groups[bucket]
        if not items:
            lines.append(f"- No item currently lands in {bucket.lower()}.")
            lines.append("")
            continue
        for item in items[:4]:
            lines.append(f"- {_acquisition_risk_markdown_line(item)}")
        lines.append("")

    lines.extend(["## Critical Path / Gating Chain", ""])
    for target in ("Final Map", "Grading Permit", "Vertical Start"):
        lines.extend([f"### {target}", ""])
        steps = [step for step in judgment.critical_path if step.target == target]
        if not steps:
            lines.append(f"- No stage-specific blocker was isolated for {target.lower()} beyond the current general issue set.")
            lines.append("")
            continue
        for step in steps:
            lines.append(f"- Step {step.sequence}: {step.blocker}. {step.why_it_blocks}")
        lines.append("")

    lines.extend(["## Investment Decision", ""])
    lines.append(f"- Decision: {decision.posture}. {decision.rationale}")
    lines.append(f"- Underwrite confidence: {confidence_level}. {_compress_statement(confidence_reason, max_words=24, single_idea=False)}")
    lines.append("- Top 3 real risks:")
    lines.extend(f"- {item}" for item in (decision.top_real_risks or ["No real risk currently rises above routine diligence noise in the second-pass classification."]))
    lines.append("- Price / structure changes:")
    lines.extend(f"- {item}" for item in (decision.price_or_structure_changes or ["No specific price or structure change currently rises above routine contingency management."]))
    lines.append(f"- Single biggest unknown: {decision.biggest_unknown or 'No single unknown currently stands above the rest of the issue set.'}")
    lines.append("- What has to be true:")
    lines.extend(f"- {item}" for item in (decision.what_has_to_be_true or ["No additional gating condition rises above the current reset risk ranking."]))
    lines.append("- Risks underwritten:")
    lines.extend(f"- {item}" for item in (decision.risks_underwritten or ["No execution risk is currently being affirmatively underwritten beyond routine project friction."]))
    lines.append("- Treated as solved:")
    lines.extend(f"- {item}" for item in (decision.treated_as_solved or ["No lane should currently be treated as solved beyond document-backed descriptors."]))

    lines.extend(["", "## What A Weak Acquisitions Person Would Miss", ""])
    if judgment.weak_acquisition_misses:
        for insight in judgment.weak_acquisition_misses:
            lines.append(f"- {insight.title}: {insight.detail}")
    else:
        lines.append("- The second pass did not isolate three non-obvious points beyond the existing issue ranking.")

    lines.extend(["", "## Supporting Read", ""])
    lines.append(f"- Package read: {registry.package_quality or 'credible'}.")
    lines.append(f"- Confidence in initial read: {registry.confidence_in_initial_read}.")
    lines.extend(["", "## Deal Impact Summary", ""])
    if impact_issues:
        for issue in impact_issues:
            lines.append(
                "- "
                + _compress_statement(
                    (
                        f"{issue.title}: impact type {deal_impact_type_for_issue(issue)}; "
                        f"magnitude {deal_impact_magnitude_for_issue(issue)}; "
                        f"mechanism {deal_impact_mechanism_for_issue(issue)}"
                    ),
                    max_words=24,
                    single_idea=False,
                )
            )
    else:
        lines.append("- No CRITICAL or HIGH issue currently rises high enough to reshape the deal beyond routine diligence judgment.")

    lines.extend(["", "## Underwrite Confidence", ""])
    lines.append(f"- Current level: {confidence_level}.")
    lines.append(f"- Why: {_compress_statement(confidence_reason, max_words=24, single_idea=False)}")
    lines.extend(
        f"- Assumption carrying the underwrite: {_compress_statement(line, max_words=22, single_idea=False)}"
        for line in underwrite_confidence_limiters(
            registry=registry,
            omission_assessments=synthesis.omission_assessments,
            contradictions=synthesis.contradictions,
            document_analyses=synthesis.document_analyses,
            issues=impact_issues or registry.issues,
            limit=2,
        )
    )

    lines.extend(["", "### If Wrong, What Happens?", ""])
    if impact_issues:
        for issue in impact_issues:
            lines.append(f"- {issue.title}: {_compress_statement(if_wrong_line_for_issue(issue), max_words=20, single_idea=False)}")
    else:
        lines.append("- If the remaining assumptions break, the deal can still move on price, timing, or closability faster than the current package implies.")

    lines.extend(["", "## Top 3 Gating Issues", ""])
    lines.extend(f"- {item}" for item in _build_gating_issue_lines(synthesis, limit=3))

    lines.extend(["", "## Biggest Blind Spots", ""])
    lines.extend(
        f"- {item}"
        for item in (registry.front_end_unresolved_points[:4] or ["No large blind spot was isolated beyond the current package."])
    )

    lines.extend(["", "## What I Would Verify Personally", ""])
    lines.extend(
        f"- {item}"
        for item in (_build_personal_verification_items(synthesis)[:3] or ["Personally verify the highest-ranked issue sources."])
    )
    lines.extend(["", "## Decision Readiness", ""])
    lines.append(f"- Status: {readiness_status}")
    lines.append(f"- Why: {readiness_reason}")
    return "\n".join(lines) + "\n"


def _acquisition_risk_markdown_line(item) -> str:
    segments = [
        f"{item.title}: {item.summary}",
        f"Impact={item.impact}; timing={item.timing}; curability={item.curability}.",
    ]
    economic_segments = [
        segment
        for segment in (
            f"Cost={item.cost_impact}" if item.cost_impact else "",
            f"Land value={item.land_value_impact}" if item.land_value_impact else "",
            f"Margin={item.margin_impact}" if item.margin_impact else "",
            f"IRR={item.irr_impact}" if item.irr_impact else "",
            f"Timing impact={item.timing_impact}" if item.timing_impact else "",
        )
        if segment
    ]
    if economic_segments:
        segments.append("Economics: " + " ".join(economic_segments))
    structure_segments = [
        segment
        for segment in (
            f"Price={item.price_response}" if item.price_response else "",
            f"Terms={item.terms_response}" if item.terms_response else "",
            f"Timing={item.timing_response}" if item.timing_response else "",
            f"Contingency={item.contingency_response}" if item.contingency_response else "",
        )
        if segment
    ]
    if structure_segments:
        segments.append("Structure response: " + " ".join(structure_segments))
    return " ".join(segments)


def _build_issue_registry_debug_markdown(
    synthesis: DealSynthesis,
    *,
    section_texts: dict[str, str] | None = None,
) -> str:
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
            f"- Deal Metadata: stage={registry.deal_metadata.stage or 'n/a'}, region={registry.deal_metadata.region or 'n/a'}, product={registry.deal_metadata.product or 'n/a'}",
            f"- Package Quality: {registry.package_quality or 'n/a'}",
            f"- Package Quality Reason: {registry.package_quality_reason or 'n/a'}",
            f"- Confidence In Initial Read: {registry.confidence_in_initial_read}",
            f"- Concern Pattern: {registry.concern_pattern or 'n/a'}",
            "",
        ]
    )

    lines.extend(["## Canonical Issue Registry", ""])
    for issue in registry.issues:
        original_title = issue.merged_fragment_titles[0] if issue.merged_fragment_titles else issue.title
        normalization_occurred = any(
            merged_title.strip().lower() != issue.title.strip().lower()
            for merged_title in (issue.merged_fragment_titles or [issue.title])
        )
        lines.append(f"### {issue.title}")
        lines.append(f"- Issue ID: `{issue.issue_id}`")
        lines.append(f"- Original Extracted Title: {original_title}")
        lines.append(f"- Normalized Title: {issue.title}")
        lines.append(f"- Title Normalized: {normalization_occurred}")
        lines.append(
            "- Title Similarity Cluster: "
            + (", ".join(issue.merged_fragment_titles) if issue.merged_fragment_titles else issue.title)
        )
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
        lines.append(f"- Front-End Flag: {issue.front_end_flag}")
        lines.append(f"- Front-End Flag Reason: {issue.front_end_flag_reason}")
        lines.append(f"- Information Status: {issue.information_status}")
        lines.append(f"- Information Status Reason: {issue.information_status_reason}")
        lines.append(f"- Normality Classification: {issue.normality_classification}")
        lines.append(f"- Process Friction Flag: {issue.process_friction_flag}")
        lines.append(f"- Unusualness Rationale: {issue.unusualness_rationale}")
        lines.append(f"- Why Now: {issue.why_now}")
        lines.append(f"- Specificity Level: {issue.specificity_level}")
        lines.append(f"- Abnormality Basis: {issue.abnormality_basis}")
        lines.append(f"- Site-Specific Trigger: {issue.site_specific_trigger or 'n/a'}")
        lines.append(f"- Genericity Penalty: {issue.genericity_penalty}")
        lines.append(f"- Missing Confirmation: {issue.missing_confirmation or 'n/a'}")
        lines.append(f"- Dependency Type: {issue.dependency_type or 'n/a'}")
        lines.append(f"- Critical Path: {issue.critical_path_flag}")
        lines.append(f"- Blocking: {issue.blocking_flag}")
        lines.append(f"- Blocker Classification: {issue.blocker_classification}")
        lines.append(f"- Schedule Impact: {issue.schedule_impact_classification}")
        if issue.blocking_reason:
            lines.append(f"- Blocking Reason: {issue.blocking_reason}")
        if issue.critical_path_reason:
            lines.append(f"- Critical Path Reason: {issue.critical_path_reason}")
        lines.append(f"- Decision Action: {issue.decision_action}")
        lines.append(
            f"- Score Adjustments: calibration={issue.priority_score.calibration_adjustment:+d}, "
            f"precedent={issue.priority_score.precedent_adjustment:+d}, "
            f"learning={issue.priority_score.learning_adjustment:+d}, "
            f"evaluator={issue.priority_score.evaluator_adjustment:+d}"
        )
        lines.append(f"- Consequence Cost: {issue.likely_cost_effect or 'n/a'}")
        lines.append(f"- Consequence Schedule: {issue.likely_schedule_effect or 'n/a'}")
        lines.append(f"- Consequence Yield/Product: {issue.likely_yield_or_product_effect or 'n/a'}")
        lines.append(f"- Consequence Closing: {issue.likely_closing_effect or 'n/a'}")
        lines.append(f"- Consequence Structure: {issue.likely_structure_effect or 'n/a'}")
        lines.append(f"- Consequence Underwriting: {issue.likely_underwriting_effect or 'n/a'}")
        lines.append(f"- Deal Impact Type: {deal_impact_type_for_issue(issue)}")
        lines.append(f"- Deal Impact Magnitude: {deal_impact_magnitude_for_issue(issue)}")
        lines.append(f"- Deal Impact Mechanism: {deal_impact_mechanism_for_issue(issue)}")
        lines.append(f"- Cost Exposure Band: {cost_exposure_band_for_issue(issue)}")
        lines.append(f"- Timing Exposure Band: {timing_exposure_band_for_issue(issue)}")
        lines.append(f"- Fixability Classification: {fixability_classification_for_issue(issue)}")
        lines.append(f"- If Wrong: {if_wrong_line_for_issue(issue)}")
        lines.append(f"- Source: {_format_citations(issue.citations[:3]) or ', '.join(issue.source_documents[:3]) or 'None'}")
        lines.append(f"- Merged Fragments: {', '.join(issue.merged_fragment_ids) or 'None'}")
        if issue.upstream_dependencies:
            lines.append(
                "- Upstream Dependencies: "
                + " | ".join(
                    f"{link.title} [{link.dependency_type}] ({link.mechanism})"
                    for link in issue.upstream_dependencies[:4]
                )
            )
        if issue.downstream_dependencies:
            lines.append(
                "- Downstream Dependencies: "
                + " | ".join(
                    f"{link.title} [{link.dependency_type}] ({link.effect})"
                    for link in issue.downstream_dependencies[:4]
                )
            )
        if issue.research_agenda:
            lines.append("- Research Agenda:")
            for step in issue.research_agenda[:2]:
                lines.append(
                    "  - "
                    f"verify={step.verify_what} | request={step.request_item} | "
                    f"source={step.likely_source} | timing={step.timing}"
                )
        if issue.calibration_notes:
            lines.append(f"- Calibration Notes: {' | '.join(issue.calibration_notes)}")
        if issue.precedent_summary.sample_size:
            lines.append(
                f"- Precedent Summary: frequency={issue.precedent_summary.historical_frequency}, "
                f"sample={issue.precedent_summary.sample_size}, "
                f"real rate={_format_percentage(issue.precedent_summary.real_rate)}, "
                f"false-positive rate={_format_percentage(issue.precedent_summary.false_positive_rate)}, "
                f"outcomes={', '.join(f'{label}={count}' for label, count in sorted(issue.precedent_summary.outcome_stats.items())) or 'none'}, "
                f"typical impact={issue.precedent_summary.typical_impact}, "
                f"confidence adjustment={issue.precedent_summary.confidence_adjustment}, "
                f"score adjustment={issue.precedent_summary.score_adjustment:+d}"
            )
            lines.append(f"- Precedent Read: {issue.precedent_summary.reasoning}")
        if issue.learning_summary.sample_size:
            lines.append(
                f"- Learning Summary: sample={issue.learning_summary.sample_size}, "
                f"real rate={_format_percentage(issue.learning_summary.real_issue_rate)}, "
                f"false-positive rate={_format_percentage(issue.learning_summary.false_positive_rate)}, "
                f"material rate={_format_percentage(issue.learning_summary.material_issue_rate)}, "
                f"decision-relevant rate={_format_percentage(issue.learning_summary.decision_relevant_rate)}, "
                f"impact rate={_format_percentage(issue.learning_summary.impact_rate)}, "
                f"confidence adjustment={issue.learning_summary.confidence_adjustment}, "
                f"score adjustment={issue.learning_summary.score_adjustment:+d}"
            )
            if issue.learning_summary.matched_features:
                lines.append(
                    "- Learning Features: "
                    + ", ".join(issue.learning_summary.matched_features[:6])
                )
            lines.append(f"- Learning Read: {issue.learning_summary.reasoning}")
        if issue.precedent_references:
            lines.append("- Retrieved Precedent Matches:")
            for reference in issue.precedent_references[:5]:
                lines.append(
                    "  - "
                    f"{reference.title} | score={reference.similarity_score:.3f} | "
                    f"{reference.relevance} | outcome={reference.actual_outcome} | "
                    f"resolved_by={reference.resolved_by} | false_positive={reference.false_positive_flag}"
                )
                if reference.resolution_notes:
                    lines.append(f"    Resolution: {reference.resolution_notes}")
        web_result = _web_research_by_issue_id(synthesis, issue.issue_id)
        if web_result is not None:
            lines.append(
                f"- Web Research: status={web_result.status} | confidence={web_result.confidence} | "
                f"answer={web_result.answer or 'n/a'}"
            )
            if web_result.source_urls:
                lines.append("- Web Sources: " + " | ".join(web_result.source_urls[:3]))
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

    lines.extend(["## Dependency Graph", ""])
    if registry.issues:
        for issue in registry.issues:
            upstream = ", ".join(link.issue_id for link in issue.upstream_dependencies) or "None"
            downstream = ", ".join(link.issue_id for link in issue.downstream_dependencies) or "None"
            lines.append(
                f"- `{issue.issue_id}` [{issue.dependency_type or 'n/a'}] | upstream: {upstream} | downstream: {downstream}"
            )
    else:
        lines.append("- No dependency graph was built.")
    lines.append("")

    lines.extend(["## Critical Path Summary", ""])
    lines.append(f"- Central Risk Pattern: {registry.central_risk_pattern or 'None'}")
    lines.append(f"- Cluster Pattern: {registry.cluster_pattern or 'None'}")
    lines.append(f"- Fragility Classification: {registry.fragility_classification or 'None'}")
    lines.append(f"- Critical Path Summary: {registry.critical_path_summary or 'None'}")
    lines.append(f"- Blocking Issues: {', '.join(registry.blocker_issue_ids) or 'None'}")
    lines.append(f"- Sequencing Issues: {', '.join(registry.sequencing_issue_ids) or 'None'}")
    lines.append(f"- Confirmatory Issues: {', '.join(registry.confirmatory_issue_ids) or 'None'}")
    lines.append(f"- Monitoring Issues: {', '.join(registry.monitoring_issue_ids) or 'None'}")
    lines.append("")

    lines.extend(["## Causal Clusters", ""])
    if registry.issue_clusters:
        for cluster in registry.issue_clusters:
            lines.append(f"- {cluster.tier} cluster: {cluster.label}")
            lines.append(f"  Root Issue: {cluster.root_issue_id}")
            lines.append(f"  Members: {', '.join(cluster.issue_ids)}")
            lines.append(f"  Downstream Effects: {', '.join(cluster.downstream_effects) or 'None'}")
            lines.append(
                f"  Key Confirmations: {', '.join(cluster.key_unresolved_confirmations) or 'None'}"
            )
            lines.append(f"  Decision Implication: {cluster.decision_implication or 'None'}")
    else:
        lines.append("- No causal clusters were built.")
    lines.append("")

    lines.extend(["## Front-End Package Read", ""])
    lines.append(
        "- Known Points: "
        + (", ".join(registry.front_end_known_points) if registry.front_end_known_points else "None")
    )
    lines.append(
        "- Elevated / Unusual Points: "
        + (", ".join(registry.front_end_elevated_points) if registry.front_end_elevated_points else "None")
    )
    lines.append(
        "- Attention Now Points: "
        + (", ".join(registry.front_end_attention_now_points) if registry.front_end_attention_now_points else "None")
    )
    lines.append(
        "- Unresolved Points: "
        + (", ".join(registry.front_end_unresolved_points) if registry.front_end_unresolved_points else "None")
    )
    lines.append(
        "- Routine Points: "
        + (", ".join(registry.front_end_routine_points) if registry.front_end_routine_points else "None")
    )
    lines.append(
        "- Deeper Work: "
        + (", ".join(registry.front_end_deeper_work) if registry.front_end_deeper_work else "None")
    )
    lines.append(
        "- Package Quality Inputs: "
        + (", ".join(registry.package_quality_inputs) if registry.package_quality_inputs else "None")
    )
    lines.append("")

    lines.extend(["## Omission Front-End Classification", ""])
    if synthesis.omission_assessments:
        for assessment in synthesis.omission_assessments:
            lines.append(
                f"- {assessment.item}: status={assessment.status} | front-end={assessment.front_end_status or 'n/a'} | "
                f"importance={assessment.importance} | request={assessment.recommended_request or 'n/a'}"
            )
            lines.append(f"  Read: {assessment.front_end_reason or assessment.rationale}")
    else:
        lines.append("- No omission assessment was generated.")
    lines.append("")

    lines.extend(["## Reading Priority Debug", ""])
    if synthesis.document_analyses:
        for analysis in synthesis.document_analyses:
            lines.append(
                f"- {analysis.document.title}: bucket={analysis.reading_bucket} | role={analysis.document_role} | "
                f"priority={analysis.reading_priority} | staleness={analysis.staleness_status} | "
                f"contradictions={analysis.contradiction_count}"
            )
            lines.append(
                "  Rationale: "
                + (", ".join(analysis.reading_rationale_factors) if analysis.reading_rationale_factors else analysis.reading_reason)
            )
    else:
        lines.append("- No document analyses were available.")
    lines.append("")

    lines.extend(["## Autonomous Learning", ""])
    lines.append(f"- Enabled: {synthesis.autonomous_learning_summary.enabled}")
    lines.append(f"- Store Path: {synthesis.autonomous_learning_summary.store_path or 'n/a'}")
    lines.append(f"- Records Generated: {synthesis.autonomous_learning_summary.records_generated}")
    lines.append(f"- Positive Records: {synthesis.autonomous_learning_summary.positive_records}")
    lines.append(f"- Negative Records: {synthesis.autonomous_learning_summary.negative_records}")
    lines.append(f"- Skipped Issues: {synthesis.autonomous_learning_summary.skipped_issues}")
    lines.append(f"- Read: {synthesis.autonomous_learning_summary.reasoning or 'None'}")
    if synthesis.autonomous_learning_summary.events:
        lines.append("- Events:")
        for event in synthesis.autonomous_learning_summary.events[:8]:
            lines.append(f"  - {event}")
    lines.append("")

    lines.extend(["## Web Research Debug", ""])
    if synthesis.web_research_results:
        for result in synthesis.web_research_results:
            lines.append(
                f"- {result.issue_id}: status={result.status} | confidence={result.confidence} | query={result.query}"
            )
            lines.append(f"  Answer: {result.answer or 'No answer'}")
            if result.source_urls:
                lines.append(f"  Sources: {' | '.join(result.source_urls[:3])}")
    else:
        lines.append("- No web fallback queries were run.")
    lines.append("")

    if section_texts:
        discipline = _output_discipline_snapshot(section_texts)
        lines.extend(["## Output Discipline", ""])
        lines.append(f"- Repeated Phrases Across Sections: {discipline['repeated_phrase_count']}")
        lines.append(f"- Average Sentence Length: {discipline['avg_sentence_length']} words")
        lines.append(f"- Hedge Density: {discipline['hedge_density']} per 100 words")
        lines.append(f"- Compression Score: {discipline['compression_score']}")
        repeated_phrases = discipline["repeated_phrases"]
        if repeated_phrases:
            lines.append("- Repeated Phrases:")
            for phrase, section_names in list(repeated_phrases.items())[:5]:
                lines.append(f"  - {phrase} | sections={', '.join(section_names)}")
        else:
            lines.append("- Repeated Phrases: None")
        lines.append("- By Section:")
        for section_name, metrics in discipline["by_section"].items():
            lines.append(
                "  - "
                f"{section_name}: avg sentence length={metrics['avg_sentence_length']} | "
                f"hedge density={metrics['hedge_density']} | "
                f"compression score={metrics['compression_score']}"
            )
        lines.append("")

    evaluator = registry.evaluator_result
    lines.extend(["## Evaluator", ""])
    lines.append(f"- Redundancy Score: {evaluator.redundancy_score}")
    lines.append(f"- False-Positive Score: {evaluator.false_positive_score}")
    lines.append(f"- Missed Issue Risk: {evaluator.missed_issue_risk}")
    lines.append(f"- Ranking Quality: {evaluator.ranking_quality}")
    lines.append(
        "- Suggested Top Issues: "
        + (", ".join(evaluator.top_issues_should_be) if evaluator.top_issues_should_be else "None")
    )
    lines.append(
        "- Issues To Remove: "
        + (", ".join(evaluator.issues_to_remove) if evaluator.issues_to_remove else "None")
    )
    if evaluator.issues_to_merge:
        lines.append("- Issues To Merge:")
        for suggestion in evaluator.issues_to_merge:
            lines.append(
                f"  - {suggestion.primary_issue_id} <- {suggestion.secondary_issue_id}"
                f" ({suggestion.rationale})"
            )
    else:
        lines.append("- Issues To Merge: None")
    lines.append(f"- Revision Applied: {evaluator.revision_applied}")
    if evaluator.revision_reason:
        lines.append(f"- Revision Reason: {evaluator.revision_reason}")
    lines.append(
        "- Initial Ranking: "
        + (", ".join(registry.initial_issue_order) if registry.initial_issue_order else "None")
    )
    lines.append(
        "- Final Ranking: "
        + (", ".join(registry.final_issue_order or registry.initial_issue_order) if (registry.final_issue_order or registry.initial_issue_order) else "None")
    )
    lines.append("")

    return "\n".join(lines)


def _build_further_diligence_roadmap_markdown(synthesis: DealSynthesis) -> str:
    roadmap = synthesis.further_diligence_roadmap
    lines = ["# Further Diligence Roadmap", ""]
    lines.extend(["## Investigate Immediately", ""])
    lines.extend(f"- {item}" for item in _roadmap_investigate_lines(synthesis, roadmap))
    lines.extend(["", "## Request / Verify Soon", ""])
    lines.extend(f"- {item}" for item in _roadmap_request_lines(synthesis, roadmap))
    lines.extend(["", "## Read Personally", ""])
    lines.extend(f"- {item}" for item in _roadmap_read_lines(synthesis, roadmap))
    lines.extend(["", "## Monitor Later", ""])
    lines.extend(f"- {item}" for item in _roadmap_monitor_lines(synthesis, roadmap))
    lines.extend(["", "## Likely Routine Unless Other Evidence Changes View", ""])
    lines.extend(f"- {item}" for item in _roadmap_routine_lines(synthesis, roadmap))
    return "\n".join(lines) + "\n"


def _build_web_research_markdown(synthesis: DealSynthesis) -> str:
    lines = ["# Web Research Fallback", ""]
    if not synthesis.web_research_results:
        lines.append("- No public-web fallback was triggered.")
        return "\n".join(lines) + "\n"

    answered = [result for result in synthesis.web_research_results if result.status == "answered"]
    partial = [result for result in synthesis.web_research_results if result.status == "partial"]
    unresolved = [result for result in synthesis.web_research_results if result.status in {"not_found", "failed"}]

    for label, results in (
        ("Answered", answered),
        ("Partial", partial),
        ("No Public Answer", unresolved),
    ):
        if not results:
            continue
        lines.extend([f"## {label}", ""])
        for result in results:
            lines.append(f"### {result.title}")
            lines.append(f"- Question: {_compress_statement(result.question, max_words=18)}")
            lines.append(f"- Query: `{result.query}`")
            lines.append(f"- Answer: {_compress_statement(result.answer or 'No public answer was isolated.', max_words=24)}")
            lines.append(f"- Confidence: {result.confidence}")
            if result.next_step:
                lines.append(f"- Next Step: {_compress_statement(result.next_step, max_words=18)}")
            if result.source_urls:
                for index, url in enumerate(result.source_urls[:3]):
                    title = result.source_titles[index] if index < len(result.source_titles) else url
                    lines.append(f"- Source: [{title}]({url})")
            if result.note:
                lines.append(f"- Note: {_compress_statement(result.note, max_words=20)}")
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _build_reviewer_feedback_template_json(synthesis: DealSynthesis) -> str:
    rows = []
    for row in build_reviewer_feedback_template(
        synthesis.canonical_issue_registry,
        deal_name=synthesis.deal_name,
    ):
        rows.append(
            {
                "issue_id": row.issue_id,
                "canonical_title": row.canonical_title,
                "category": row.category,
                "deal_id": row.deal_id,
                "deal_name": row.deal_name,
                "deal_metadata": {
                    "stage": row.deal_metadata.stage,
                    "geography": row.deal_metadata.region,
                    "product": row.deal_metadata.product,
                },
                "evidence_basis": row.evidence_basis,
                "issue_strength": row.issue_strength,
                "false_positive_risk": row.false_positive_risk,
                "model_materiality": row.model_materiality,
                "model_decision_relevant": row.model_decision_relevant,
                "model_action": row.model_action,
                "real_issue": row.real_issue,
                "false_positive_flag": row.false_positive_flag,
                "materiality": row.materiality,
                "decision_relevant": row.decision_relevant,
                "duplicate_of": row.duplicate_of,
                "overstated": row.overstated,
                "understated": row.understated,
                "actual_outcome": row.actual_outcome,
                "resolved_by": row.resolved_by,
                "correct_action": row.correct_action,
                "notes": row.notes,
            }
        )
    return json.dumps(rows, indent=2) + "\n"


def _format_percentage(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:.0%}"


def _web_research_by_issue_id(synthesis: DealSynthesis, issue_id: str):
    for result in synthesis.web_research_results:
        if result.issue_id == issue_id:
            return result
    return None


HEDGE_WORDS = {"may", "could", "might", "possibly", "potentially", "appears", "seems", "suggests"}
TRIMMABLE_END_WORDS = {
    "a",
    "an",
    "and",
    "as",
    "at",
    "by",
    "for",
    "from",
    "if",
    "in",
    "into",
    "of",
    "on",
    "or",
    "that",
    "the",
    "to",
    "with",
}
FILLER_PHRASES = (
    "it is important to note that",
    "it is important to note",
    "this suggests that",
    "this indicates that",
    "the fact that",
)


def _clean_output_text(text: str) -> str:
    return re.sub(r"\s+", " ", normalize_text(text or "")).strip()


def _ensure_terminal_punctuation(text: str) -> str:
    text = text.strip()
    if not text:
        return ""
    if text.endswith((".", "!", "?")):
        return text
    return f"{text}."


def _trim_words(text: str, *, max_words: int) -> str:
    words = text.split()
    if len(words) <= max_words:
        return text

    hard_limit = min(len(words), max_words + max(2, max_words // 4))
    candidate = " ".join(words[:hard_limit])
    min_words = max(4, max_words // 2)

    for match in reversed(list(re.finditer(r"[.!?]", candidate))):
        prefix = candidate[: match.end()].strip()
        if len(prefix.split()) >= min_words:
            return prefix

    trimmed_words = words[:max_words]
    while (
        len(trimmed_words) > min_words
        and re.sub(r"[^a-z]", "", trimmed_words[-1].lower()) in TRIMMABLE_END_WORDS
    ):
        trimmed_words.pop()
    trimmed = " ".join(trimmed_words).rstrip(",;:")
    return f"{trimmed}..."


def _strip_markdown(text: str) -> str:
    text = re.sub(r"`([^`]*)`", r"\1", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    return re.sub(r"[*_#>-]", "", text).strip()


def _collapse_hedges(text: str) -> str:
    text = re.sub(r"\b(could|may|might)\s+(potentially|possibly)\b", r"\1", text, flags=re.IGNORECASE)
    text = re.sub(r"\b(possibly|potentially)\b", "", text, flags=re.IGNORECASE)
    words = text.split()
    if not words:
        return ""
    kept_words: list[str] = []
    hedge_seen = False
    for word in words:
        normalized = re.sub(r"[^a-z]", "", word.lower())
        if normalized in HEDGE_WORDS:
            if hedge_seen:
                continue
            hedge_seen = True
        kept_words.append(word)
    return re.sub(r"\s+", " ", " ".join(kept_words)).strip()


def _compress_statement(
    text: str,
    *,
    max_words: int,
    max_sentences: int = 1,
    single_idea: bool = True,
) -> str:
    compressed = _clean_output_text(text)
    if not compressed:
        return ""
    compressed = re.sub(r"\bp\.\s+(\d)", r"p.~\1", compressed, flags=re.IGNORECASE)
    for phrase in FILLER_PHRASES:
        compressed = re.sub(re.escape(phrase), "", compressed, flags=re.IGNORECASE)
    compressed = re.sub(r"\bwhich suggests\b", "and", compressed, flags=re.IGNORECASE)
    compressed = re.sub(r"\bappears to be\b", "is", compressed, flags=re.IGNORECASE)
    compressed = re.sub(r"\bseems to be\b", "is", compressed, flags=re.IGNORECASE)
    compressed = _collapse_hedges(compressed)
    sentences = [
        segment.strip()
        for segment in re.split(r"(?<=[.!?])\s+", compressed)
        if segment.strip()
    ]
    compressed = " ".join(sentences[:max_sentences]) if sentences else compressed
    if single_idea and ";" in compressed:
        compressed = compressed.split(";", 1)[0].strip()
    compressed = re.sub(r"\s+", " ", compressed).strip(" ,;:")
    compressed = compressed.replace("p.~", "p. ")
    compressed = _trim_words(compressed, max_words=max_words)
    return _ensure_terminal_punctuation(compressed)


def _request_action_text(request_text: str) -> str:
    action = _clean_output_text(request_text).rstrip(".")
    if not action:
        return ""
    if re.match(r"^provide\b", action, flags=re.IGNORECASE):
        action = re.sub(r"^provide\b", "Request", action, count=1, flags=re.IGNORECASE)
    elif re.match(r"^send\b", action, flags=re.IGNORECASE):
        action = re.sub(r"^send\b", "Request", action, count=1, flags=re.IGNORECASE)
    elif re.match(r"^share\b", action, flags=re.IGNORECASE):
        action = re.sub(r"^share\b", "Request", action, count=1, flags=re.IGNORECASE)
    elif re.match(
        r"^(allocate|clear|confirm|deliver|identify|lock|monitor|obtain|read|refresh|reconcile|replace|request|resolve|review|state|verify)\b",
        action,
        flags=re.IGNORECASE,
    ):
        action = action[0].upper() + action[1:]
    else:
        action = f"Request {action[0].lower() + action[1:]}"
    return _ensure_terminal_punctuation(action)


def _issue_status_line(issue: CanonicalIssue) -> str:
    if not issue.front_end_flag:
        return "Issue under review."
    if issue.front_end_flag == "document gap":
        return "Gap, not a confirmed risk."
    if issue.front_end_flag == "stale-information concern":
        return "Stale support; refresh before relying on it."
    if issue.front_end_flag == "conflict / contradiction concern":
        return "Conflict exists across the current documents."
    if issue.front_end_flag == "routine item" or issue.normality_classification == "routine":
        return "Routine process item."
    return f"{issue.front_end_flag.title()}."


def _issue_next_step(issue: CanonicalIssue) -> str:
    if issue.research_agenda:
        return _compress_statement(
            _request_action_text(issue.research_agenda[0].request_item),
            max_words=18,
        )
    if issue.missing_confirmation:
        return _compress_statement(_request_action_text(issue.missing_confirmation), max_words=18)
    return ""


def _front_end_flag_label(issue: CanonicalIssue) -> str:
    if issue.front_end_flag == "conflict / contradiction concern":
        return "CONFLICT"
    if issue.blocking_flag:
        return "BLOCKER"
    if issue.critical_path_flag:
        return "CRITICAL PATH"
    mapping = {
        "red flag": "RED FLAG",
        "yellow flag": "YELLOW FLAG",
        "document gap": "BLIND SPOT",
        "stale-information concern": "STALE SUPPORT",
        "routine item": "ROUTINE ITEM",
    }
    return mapping.get(issue.front_end_flag, issue.front_end_flag.upper())


def _read_first_line(recommendation) -> str:
    return _ensure_terminal_punctuation(
        _clean_output_text(f"Read {recommendation.title} (`{recommendation.relative_path}`) first.")
    )


def _body_sentences(text: str) -> list[str]:
    sentences: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        clean = _strip_markdown(line)
        if not clean:
            continue
        for segment in re.split(r"(?<=[.!?])\s+|;\s+", clean):
            segment = segment.strip()
            if segment:
                sentences.append(segment)
    return sentences


def _discipline_metrics(text: str) -> dict[str, float | int]:
    sentences = _body_sentences(text)
    word_counts = [len(re.findall(r"\b[\w/-]+\b", sentence)) for sentence in sentences if sentence]
    total_words = sum(word_counts)
    hedge_count = sum(
        1
        for sentence in sentences
        for word in re.findall(r"\b[a-z]+\b", sentence.lower())
        if word in HEDGE_WORDS
    )
    avg_sentence_length = round(total_words / len(word_counts), 1) if word_counts else 0.0
    long_sentence_count = sum(1 for count in word_counts if count > 24)
    hedge_density = round((hedge_count / total_words) * 100, 2) if total_words else 0.0
    compression_score = max(
        0,
        100
        - max(0, int(avg_sentence_length - 16) * 3)
        - min(24, hedge_count * 4)
        - min(20, long_sentence_count * 5),
    )
    return {
        "sentence_count": len(word_counts),
        "avg_sentence_length": avg_sentence_length,
        "hedge_count": hedge_count,
        "hedge_density": hedge_density,
        "compression_score": compression_score,
    }


def _repeated_explanatory_phrases(section_texts: dict[str, str]) -> dict[str, list[str]]:
    ignored_prefixes = (
        "deal:",
        "provider:",
        "mode:",
        "entitlement status:",
        "recommendation posture:",
        "flag:",
        "source:",
        "timing:",
        "package read:",
        "confidence in initial read:",
    )
    phrase_sections: dict[str, set[str]] = {}
    for section_name, text in section_texts.items():
        seen_in_section: set[str] = set()
        for raw_line in text.splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            clean = _strip_markdown(line)
            if not clean:
                continue
            for phrase in re.split(r"[.:;]", clean):
                normalized_phrase = _clean_output_text(phrase).lower()
                if len(normalized_phrase.split()) < 5:
                    continue
                if normalized_phrase.startswith("no "):
                    continue
                if normalized_phrase.startswith(ignored_prefixes):
                    continue
                seen_in_section.add(normalized_phrase)
        for phrase in seen_in_section:
            phrase_sections.setdefault(phrase, set()).add(section_name)
    return {
        phrase: sorted(section_names)
        for phrase, section_names in phrase_sections.items()
        if len(section_names) > 1
    }


def _output_discipline_snapshot(section_texts: dict[str, str]) -> dict[str, object]:
    metrics_by_section = {
        section_name: _discipline_metrics(text)
        for section_name, text in section_texts.items()
    }
    repeated_phrases = _repeated_explanatory_phrases(section_texts)
    aggregate_sentences = sum(metrics["sentence_count"] for metrics in metrics_by_section.values())
    aggregate_avg = (
        round(
            sum(metrics["avg_sentence_length"] * metrics["sentence_count"] for metrics in metrics_by_section.values())
            / aggregate_sentences,
            1,
        )
        if aggregate_sentences
        else 0.0
    )
    aggregate_hedges = sum(metrics["hedge_count"] for metrics in metrics_by_section.values())
    aggregate_words = sum(
        sum(len(re.findall(r"\b[\w/-]+\b", sentence)) for sentence in _body_sentences(text))
        for text in section_texts.values()
    )
    aggregate_hedge_density = round((aggregate_hedges / aggregate_words) * 100, 2) if aggregate_words else 0.0
    aggregate_score = max(
        0,
        round(
            (
                sum(metrics["compression_score"] for metrics in metrics_by_section.values())
                / max(len(metrics_by_section), 1)
            )
            - min(20, len(repeated_phrases) * 4)
        ),
    )
    return {
        "repeated_phrases": repeated_phrases,
        "repeated_phrase_count": len(repeated_phrases),
        "avg_sentence_length": aggregate_avg,
        "hedge_density": aggregate_hedge_density,
        "compression_score": aggregate_score,
        "by_section": metrics_by_section,
    }


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
        front_end_selected = [
            issue
            for issue in registry.issues
            if issue.top_line_eligible and issue.front_end_flag in {"red flag", "yellow flag"}
        ]
        return (front_end_selected or [issue for issue in registry.issues if issue.top_line_eligible])[:default_count]
    return registry.issues[:default_count]


def _render_canonical_issue_risk_block(issue: CanonicalIssue, *, index: int) -> list[str]:
    lines = [f"### {index}. {issue.title}"]
    lines.append(f"- Flag: {_issue_status_line(issue)}")
    lines.append(f"- Why It Matters: {_compress_statement(issue.why_it_matters, max_words=16)}")
    basis = issue.site_specific_trigger or (issue.core_facts[0] if issue.core_facts else "")
    if basis:
        lines.append(f"- Basis: {_compress_statement(basis, max_words=16)}")
    if issue.normality_classification not in {"routine", "unknown"} and issue.unusualness_rationale:
        lines.append(f"- Read: {_compress_statement(issue.unusualness_rationale, max_words=14)}")
    if issue.why_now and issue.why_now != "unclear":
        lines.append(f"- Timing: {_compress_statement(issue.why_now, max_words=8)}")
    lines.append(
        f"- Deal Impact: {deal_impact_type_for_issue(issue)}; {deal_impact_magnitude_for_issue(issue)}; {_compress_statement(deal_impact_mechanism_for_issue(issue), max_words=18, single_idea=False)}"
    )
    lines.append(
        f"- Exposure: cost {cost_exposure_band_for_issue(issue)}; timing {timing_exposure_band_for_issue(issue)}; fixability {fixability_classification_for_issue(issue)}"
    )
    lines.append(f"- If Wrong: {_compress_statement(if_wrong_line_for_issue(issue), max_words=18, single_idea=False)}")
    next_step = _issue_next_step(issue)
    if next_step:
        lines.append(f"- Next: {next_step}")
    elif issue.what_would_resolve_it:
        lines.append(f"- Next: {_compress_statement(issue.what_would_resolve_it, max_words=16)}")
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


def _build_synthesis_judgment_lines(synthesis: DealSynthesis) -> list[str]:
    registry = synthesis.canonical_issue_registry
    lines = [
        f"Package read: {registry.package_quality or 'adequate'}.",
        f"Confidence in initial read: {registry.confidence_in_initial_read}.",
    ]
    if registry.central_risk_pattern:
        lines.append(_compress_statement(registry.central_risk_pattern, max_words=18))
    elif synthesis.executive_summary:
        lines.append(_compress_statement(synthesis.executive_summary, max_words=18))
    if registry.package_quality_reason:
        lines.append(_compress_statement(registry.package_quality_reason, max_words=18))
    elif registry.concern_pattern:
        lines.append(_compress_statement(registry.concern_pattern, max_words=18))
    return _unique_list(lines)[:4]


def _build_routine_vs_elevated_lines(synthesis: DealSynthesis) -> list[str]:
    issues = synthesis.canonical_issue_registry.issues
    if not issues:
        return ["No routine or elevated pattern was isolated from the current package."]
    normality_counts = Counter(issue.normality_classification or "unknown" for issue in issues)
    elevated_count = sum(
        normality_counts.get(label, 0)
        for label in ("mildly elevated", "elevated", "unusual")
    )
    routine_count = normality_counts.get("routine", 0)
    lines: list[str] = []
    if elevated_count:
        if synthesis.canonical_issue_registry.issue_clusters:
            cluster_labels = ", ".join(cluster.label for cluster in synthesis.canonical_issue_registry.issue_clusters[:2])
            lines.append(_compress_statement(f"Elevated concern is concentrated in {cluster_labels}.", max_words=16))
        else:
            lines.append("Elevated concern is concentrated in a small issue set, not spread across every diligence lane.")
    else:
        lines.append("No unusually elevated issue set was isolated beyond routine package review.")
    if routine_count:
        lines.append("Routine friction is present, but it sits outside the real critical path.")
    else:
        lines.append("Routine process noise is not the main story in this package.")
    return _unique_list(lines)[:3]


def _build_synthesis_critical_path_lines(synthesis: DealSynthesis) -> list[str]:
    registry = synthesis.canonical_issue_registry
    lines = [
        _compress_statement(
            registry.critical_path_summary or "No critical-path issue was isolated from the current package.",
            max_words=18,
        )
    ]
    if registry.blocker_issue_ids:
        lines.append("The main gating path is the blocker set, not routine coordination.")
    elif registry.sequencing_issue_ids:
        lines.append("The main path is sequencing-driven rather than blocked outright.")
    if registry.fragility_classification:
        lines.append(_compress_statement(f"Deal type: {registry.fragility_classification}.", max_words=10))
    return _unique_list(lines)[:3]


def _build_confidence_change_lines(synthesis: DealSynthesis) -> list[str]:
    registry = synthesis.canonical_issue_registry
    lines = [
        _compress_statement(
            f"Confidence changes once {unlock}.",
            max_words=18,
        )
        for unlock in registry.confidence_unlocks[:3]
    ]
    if not lines and registry.front_end_unresolved_points:
        lines.extend(
            _compress_statement(f"Confidence changes once {point}.", max_words=18)
            for point in registry.front_end_unresolved_points[:2]
        )
    if synthesis.contradictions:
        lines.append("Confidence changes once the controlling document conflicts are resolved.")
    if not lines:
        lines.append("No single confirmation was isolated as the main confidence unlock.")
    return _unique_list(lines)[:4]


def _roadmap_investigate_lines(synthesis: DealSynthesis, roadmap) -> list[str]:
    items = [
        _compress_statement(
            f"Review public answer on {result.title.lower()}: {result.answer}",
            max_words=16,
        )
        for result in synthesis.web_research_results
        if result.status in {"answered", "partial"} and result.answer
    ]
    items.extend(
        _issue_next_step(issue)
        for issue in synthesis.canonical_issue_registry.issues
        if issue.why_now == "investigate now" and _issue_next_step(issue)
    )
    items.extend(
        _compress_statement(f"Resolve the conflict: {finding.description}", max_words=16)
        for finding in synthesis.contradictions[:2]
    )
    if not items:
        items = [
            _compress_statement(item, max_words=16)
            for item in roadmap.investigate_immediately[:4]
        ]
    return _unique_list(items)[:5] or ["No issue was elevated to immediate investigation."]


def _roadmap_request_lines(synthesis: DealSynthesis, roadmap) -> list[str]:
    items = [
        _compress_statement(
            result.next_step or f"Request direct support for {result.title.lower()}.",
            max_words=16,
        )
        for result in synthesis.web_research_results
        if result.status in {"not_found", "failed"}
    ]
    items.extend(
        _compress_statement(_request_action_text(assessment.recommended_request), max_words=16)
        for assessment in synthesis.omission_assessments
        if assessment.front_end_status in {"missing and important", "stale and potentially unreliable", "conflicting across documents"}
        and assessment.recommended_request
    )
    items.extend(
        _compress_statement(
            f"Verify whether {issue.title.lower()} is truly an issue here.",
            max_words=16,
        )
        if issue.specificity_level == "generic"
        else _issue_next_step(issue)
        for issue in synthesis.canonical_issue_registry.issues
        if issue.why_now in {"investigate after initial read", "investigate before underwriting"} and _issue_next_step(issue)
    )
    if not items:
        items = [
            _compress_statement(item, max_words=16)
            for item in roadmap.request_or_verify_soon[:4]
        ]
    return _unique_list(items)[:5] or ["No near-term request or verification item was isolated."]


def _roadmap_read_lines(synthesis: DealSynthesis, roadmap) -> list[str]:
    items = [
        _read_first_line(recommendation)
        for recommendation in synthesis.recommended_reading_order
        if recommendation.bucket == "must read personally"
    ]
    if not items:
        items = [_compress_statement(item, max_words=12) for item in roadmap.read_personally[:3]]
    return _unique_list(items)[:4] or ["No must-read document was isolated."]


def _roadmap_monitor_lines(synthesis: DealSynthesis, roadmap) -> list[str]:
    items = [
        _compress_statement(
            f"Verify whether {issue.title.lower()} is truly an issue here.",
            max_words=12,
        )
        if issue.specificity_level == "generic"
        else _compress_statement(f"Monitor {issue.title.lower()}.", max_words=12)
        for issue in synthesis.canonical_issue_registry.issues
        if issue.why_now == "monitor unless other signals worsen"
    ]
    if not items:
        items = [_compress_statement(item, max_words=12) for item in roadmap.monitor_later[:4]]
    return _unique_list(items)[:4] or ["No monitor-later item was isolated."]


def _roadmap_routine_lines(synthesis: DealSynthesis, roadmap) -> list[str]:
    items = [
        _compress_statement(
            f"Verify whether {issue.title.lower()} is truly an issue here."
            if issue.specificity_level == "generic"
            else f"Treat {issue.title.lower()} as routine unless the support is contradicted.",
            max_words=16,
        )
        for issue in synthesis.canonical_issue_registry.issues
        if issue.why_now == "likely routine unless contradicted" or issue.normality_classification == "routine"
    ]
    if not items:
        items = [
            _compress_statement(item, max_words=16)
            for item in roadmap.likely_routine_unless_changed[:4]
        ]
    return _unique_list(items)[:4] or ["No issue was explicitly classified as likely routine."]


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
        lines.append(f"- Conflict: {_compress_statement(finding.description, max_words=16)}")
        if finding.citations:
            lines.append(f"- Documents: {_format_citations(finding.citations)}")
        elif finding.source_documents:
            lines.append(f"- Documents: {', '.join(finding.source_documents)}")
        lines.append(f"- Why It Matters: {_compress_statement(finding.why_it_matters, max_words=14)}")
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
    registry = synthesis.canonical_issue_registry
    issue_by_id = {issue.issue_id: issue for issue in registry.issues}
    blocker_issues = [issue_by_id[issue_id] for issue_id in registry.blocker_issue_ids if issue_id in issue_by_id]
    issues = blocker_issues or _selected_issues(synthesis, "01_executive_summary.md", default_count=4)
    if not issues:
        return ["No single decision driver clearly dominates the current package."]
    return [
        _with_light_citation(f"{issue.title}. {_issue_blocks(issue) or issue.why_it_matters}", issue)
        for issue in issues[:5]
    ]


def _build_decision_gate_lines(synthesis: DealSynthesis) -> list[str]:
    return _build_gating_issue_lines(synthesis, limit=3)


def _build_gating_issue_lines(synthesis: DealSynthesis, *, limit: int = 3) -> list[str]:
    registry = synthesis.canonical_issue_registry
    issue_by_id = {issue.issue_id: issue for issue in registry.issues}
    gating_issues = [issue_by_id[issue_id] for issue_id in registry.blocker_issue_ids if issue_id in issue_by_id]
    if not gating_issues:
        gating_issues = [issue for issue in registry.issues if issue.critical_path_flag][:limit]

    lines: list[str] = []
    for issue in gating_issues[:limit]:
        unlock = issue.research_agenda[0].request_item if issue.research_agenda else issue.what_would_resolve_it
        lines.append(
            f"{issue.title}: blocks {_issue_blocks(issue) or 'the next decision gate'}; "
            f"unlock confirmation: {unlock or 'current support and owner confirmation'}."
        )

    if not lines:
        lines.append("No specific gating condition was isolated beyond the current diligence gaps.")
    return lines


def _issue_blocks(issue: CanonicalIssue) -> str:
    blocked: list[str] = []
    if issue.schedule_impact_classification == "immediate blocker":
        blocked.append("the current decision posture")
    elif issue.schedule_impact_classification == "pre-close blocker":
        blocked.append("closing")
    elif issue.schedule_impact_classification == "pre-underwriting blocker":
        blocked.append("underwriting confidence")
    elif issue.schedule_impact_classification == "pre-final-map blocker":
        blocked.append("final map / improvement-plan timing")
    elif issue.schedule_impact_classification == "pre-vertical-start blocker":
        blocked.append("vertical readiness")
    blocked.extend(link.title.lower() for link in issue.downstream_dependencies[:2])
    if issue.blocker_classification == "sequencing issue" and not blocked:
        blocked.append("downstream sequencing confidence")
    return ", ".join(_unique_list(blocked)[:3])


def _render_issue_clusters(synthesis: DealSynthesis) -> list[str]:
    registry = synthesis.canonical_issue_registry
    if not registry.issue_clusters:
        return ["- No causal cluster was isolated beyond the ranked issue list."]

    lines: list[str] = []
    for cluster in registry.issue_clusters[:3]:
        lines.append(f"- {cluster.tier} cluster: {cluster.label}")
        lines.append(f"  Root issue: {cluster.root_issue_id}")
        lines.append(f"  Downstream effects: {', '.join(cluster.downstream_effects) or 'None'}")
        lines.append(
            f"  Key unresolved confirmations: {', '.join(cluster.key_unresolved_confirmations) or 'None'}"
        )
        lines.append(f"  Decision implication: {cluster.decision_implication or 'None'}")
    return lines


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
    for recommendation in synthesis.recommended_reading_order:
        if recommendation.bucket != "must read personally":
            continue
        items.append(
            f"Read {recommendation.title} (`{recommendation.relative_path}`) because {recommendation.reason}"
        )
        if len(items) >= 2:
            break

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
    registry = synthesis.canonical_issue_registry
    issues = registry.issues
    if (
        synthesis.contradictions
        or registry.blocker_issue_ids
        or any(
            assessment.front_end_status in {"missing and important", "conflicting across documents"}
            for assessment in synthesis.omission_assessments
        )
        or any(
        analysis.confidence == "low" for analysis in synthesis.document_analyses
        )
        or registry.package_quality in {"thin", "stale", "mixed", "selectively presented", "unclear"}
    ):
        return (
            "Not ready",
            "One or more blocker issues, blind spots, or stale/conflicted materials still sit on the front-end critical path.",
        )
    if registry.critical_path_issue_ids or any(issue.gating_flags for issue in issues):
        return (
            "Partially complete",
            "The package is substantive, but sequencing and confirmation items still sit on the path to a clean front-end read.",
        )
    return (
        "Decision-ready",
        "The current package supports a credible front-end read with no material blind spot still driving the recommendation.",
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
    registry = synthesis.canonical_issue_registry
    issue_by_id = {issue.issue_id: issue for issue in registry.issues}
    blocking_issues = [issue_by_id[issue_id] for issue_id in registry.blocker_issue_ids if issue_id in issue_by_id]
    issues = blocking_issues or _selected_issues(synthesis, "09_investment_committee_brief.md", default_count=3)
    if not issues:
        return "The package does not surface a concentrated issue, but it still needs a completeness check before it is treated as decision-ready."

    lead = issues[0]
    text = (
        f"The recommendation is '{synthesis.recommendation.posture}' because {lead.title.lower()} is still open. "
        f"{registry.central_risk_pattern or lead.likely_implication}"
    )
    if len(issues) > 1:
        text += f" The next gating issue is {issues[1].title.lower()}."
    if registry.critical_path_summary:
        text += f" {registry.critical_path_summary}"
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
