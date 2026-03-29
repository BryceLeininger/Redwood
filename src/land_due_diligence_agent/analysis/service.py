"""Orchestration for document and deal-level analysis."""

from __future__ import annotations

import logging

from land_due_diligence_agent.analysis.heuristics import (
    aggregate_risks,
    analyze_document,
    build_executive_summary_draft,
    collect_seller_questions,
    detect_contradictions,
    identify_missing_items,
    infer_entitlement_status,
    recommend_reading_order,
)
from land_due_diligence_agent.analysis.multi_pass import (
    build_adversarial_challenges,
    build_category_rollup_from_issue_analyses,
    build_issue_analyses,
    build_priority_assessment,
    build_structured_facts,
    enrich_issue_analyses_with_contradictions,
)
from land_due_diligence_agent.llm.base import LLMProvider
from land_due_diligence_agent.models import DealSynthesis, DocumentRecord, LLMCallFailure, PriorityAssessment


def run_analysis(
    *,
    deal_name: str,
    documents: list[DocumentRecord],
    llm_provider: LLMProvider,
    logger: logging.Logger,
    extraction_errors: list[str] | None = None,
    mode: str = "full",
) -> DealSynthesis:
    """Run document summaries plus a deal-level synthesis."""

    extraction_errors = extraction_errors or []
    analysis_mode = mode.lower()
    if analysis_mode not in {"fast", "full"}:
        raise ValueError(f"Unsupported analysis mode: {mode}")

    document_analyses = []
    llm_failures: list[LLMCallFailure] = []
    llm_calls_attempted = 0
    use_external_llm = llm_provider.provider_name != "heuristic"

    for document in documents:
        analysis = analyze_document(document)
        if analysis_mode == "full":
            if use_external_llm:
                llm_calls_attempted += 1
            try:
                analysis.summary = llm_provider.refine_document_summary(
                    document=document,
                    draft_summary=analysis.summary,
                    risks=analysis.risks,
                    missing_items=analysis.missing_items,
                )
            except Exception as exc:  # pragma: no cover - network/provider failure path
                detail = _format_llm_exception(exc)
                logger.warning("LLM refinement failed for %s: %s", document.relative_path.as_posix(), detail)
                llm_failures.append(
                    LLMCallFailure(
                        stage="document_summary",
                        target=document.relative_path.as_posix(),
                        model=getattr(llm_provider, "model", llm_provider.provider_name),
                        detail=detail,
                    )
                )
        document_analyses.append(analysis)

    structured_facts = build_structured_facts(document_analyses)
    key_risks = aggregate_risks(document_analyses)
    if analysis_mode == "fast":
        primary_risks = [risk for risk in key_risks if risk.priority_tier == "primary"] or key_risks[:3]
        key_risks = primary_risks[:3]

    missing_items = identify_missing_items(documents, document_analyses)
    entitlement_status = infer_entitlement_status(documents)
    issue_analyses = []
    if analysis_mode == "full":
        issue_analyses = build_issue_analyses(
            structured_facts=structured_facts,
            document_analyses=document_analyses,
            key_risks=key_risks,
            missing_items=missing_items,
        )
    contradictions = (
        detect_contradictions(document_analyses, key_risks, missing_items)
        if analysis_mode == "full"
        else []
    )
    if analysis_mode == "full":
        issue_analyses = enrich_issue_analyses_with_contradictions(issue_analyses, contradictions)

    priority_assessment = build_priority_assessment(issue_analyses, contradictions) if analysis_mode == "full" else None
    challenge_findings = (
        build_adversarial_challenges(
            issue_analyses=issue_analyses,
            contradictions=contradictions,
            missing_items=missing_items,
            document_analyses=document_analyses,
            priority_assessment=priority_assessment,
        )
        if analysis_mode == "full" and priority_assessment is not None
        else []
    )
    category_rollup = (
        {risk.category: risk.summary for risk in key_risks}
        if analysis_mode == "fast"
        else build_category_rollup_from_issue_analyses(issue_analyses)
    )
    seller_questions = collect_seller_questions(
        document_analyses,
        missing_items,
        key_risks,
        contradictions,
        issue_analyses=issue_analyses,
    )
    if analysis_mode == "fast":
        seller_questions = seller_questions[:6]
    executive_summary = build_executive_summary_draft(
        deal_name=deal_name,
        document_analyses=document_analyses,
        key_risks=key_risks,
        issue_analyses=issue_analyses,
        challenge_findings=challenge_findings,
        priority_assessment=priority_assessment,
        contradictions=contradictions,
        entitlement_status=entitlement_status,
        missing_items=missing_items,
        extraction_errors=extraction_errors,
    )

    if use_external_llm:
        llm_calls_attempted += 1
    try:
        executive_summary = llm_provider.refine_executive_summary(
            deal_name=deal_name,
            draft_summary=executive_summary,
            category_rollup=category_rollup,
            key_risks=key_risks,
            contradictions=contradictions,
            missing_items=missing_items,
        )
    except Exception as exc:  # pragma: no cover - network/provider failure path
        detail = _format_llm_exception(exc)
        logger.warning("Deal-level LLM refinement failed: %s", detail)
        llm_failures.append(
            LLMCallFailure(
                stage="executive_summary",
                target=deal_name,
                model=getattr(llm_provider, "model", llm_provider.provider_name),
                detail=detail,
            )
        )

    return DealSynthesis(
        deal_name=deal_name,
        executive_summary=executive_summary,
        entitlement_status=entitlement_status,
        key_risks=key_risks,
        recommended_reading_order=recommend_reading_order(document_analyses),
        seller_questions=seller_questions,
        missing_items=missing_items,
        category_rollup=category_rollup,
        document_analyses=document_analyses,
        structured_facts=structured_facts,
        issue_analyses=issue_analyses,
        challenge_findings=challenge_findings,
        priority_assessment=priority_assessment or PriorityAssessment(),
        contradictions=contradictions,
        extraction_errors=extraction_errors,
        llm_failures=llm_failures,
        analysis_mode=analysis_mode,
        llm_calls_attempted=llm_calls_attempted,
    )


def _format_llm_exception(exc: Exception) -> str:
    parts: list[str] = []
    current: BaseException | None = exc
    while current is not None:
        detail = str(current).strip() or "<no message>"
        parts.append(f"{type(current).__name__}: {detail}")
        current = current.__cause__
    return " <- ".join(parts)
