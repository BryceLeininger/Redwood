"""Orchestration for document and deal-level analysis."""

from __future__ import annotations

import logging

from land_due_diligence_agent.analysis.heuristics import (
    aggregate_risks,
    analyze_document,
    build_category_rollup,
    build_executive_summary_draft,
    collect_seller_questions,
    identify_missing_items,
    infer_entitlement_status,
    recommend_reading_order,
)
from land_due_diligence_agent.llm.base import LLMProvider
from land_due_diligence_agent.models import DealSynthesis, DocumentRecord, LLMCallFailure


def run_analysis(
    *,
    deal_name: str,
    documents: list[DocumentRecord],
    llm_provider: LLMProvider,
    logger: logging.Logger,
    extraction_errors: list[str] | None = None,
) -> DealSynthesis:
    """Run document summaries plus a deal-level synthesis."""

    extraction_errors = extraction_errors or []
    document_analyses = []
    llm_failures: list[LLMCallFailure] = []

    for document in documents:
        analysis = analyze_document(document)
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

    key_risks = aggregate_risks(document_analyses)
    missing_items = identify_missing_items(documents, document_analyses)
    entitlement_status = infer_entitlement_status(documents)
    category_rollup = build_category_rollup(document_analyses)
    seller_questions = collect_seller_questions(document_analyses, missing_items, key_risks)
    executive_summary = build_executive_summary_draft(
        deal_name=deal_name,
        document_analyses=document_analyses,
        key_risks=key_risks,
        entitlement_status=entitlement_status,
        missing_items=missing_items,
        extraction_errors=extraction_errors,
    )

    try:
        executive_summary = llm_provider.refine_executive_summary(
            deal_name=deal_name,
            draft_summary=executive_summary,
            category_rollup=category_rollup,
            key_risks=key_risks,
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
        extraction_errors=extraction_errors,
        llm_failures=llm_failures,
    )


def _format_llm_exception(exc: Exception) -> str:
    parts: list[str] = []
    current: BaseException | None = exc
    while current is not None:
        detail = str(current).strip() or "<no message>"
        parts.append(f"{type(current).__name__}: {detail}")
        current = current.__cause__
    return " <- ".join(parts)
