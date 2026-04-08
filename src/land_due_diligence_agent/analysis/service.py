"""Orchestration for document and deal-level analysis."""

from __future__ import annotations

import logging
from pathlib import Path

from land_due_diligence_agent.analysis.autonomous_agent import (
    default_autonomous_store_path,
    load_autonomous_learning_records,
    persist_autonomous_learning_records,
)
from land_due_diligence_agent.analysis.front_end import apply_front_end_assessment
from land_due_diligence_agent.analysis.heuristics import (
    aggregate_risks,
    analyze_document,
    detect_contradictions,
    identify_missing_items,
    infer_entitlement_status,
)
from land_due_diligence_agent.analysis.learning import build_learning_engine, default_learning_snapshot_path
from land_due_diligence_agent.analysis.issue_registry import (
    build_adversarial_challenges_from_registry,
    build_canonical_issue_registry,
    build_category_rollup_from_registry,
    build_issue_analyses_from_registry,
    build_omission_assessments,
    build_overall_read_draft,
    build_priority_assessment_from_registry,
    build_recommendation_from_registry,
    build_section_selections,
    build_seller_questions_from_registry,
)
from land_due_diligence_agent.analysis.multi_pass import (
    build_structured_facts,
)
from land_due_diligence_agent.analysis.precedents import build_precedent_engine
from land_due_diligence_agent.analysis.web_research import OpenAIWebResearcher
from land_due_diligence_agent.llm.base import LLMProvider
from land_due_diligence_agent.models import (
    AutonomousLearningSummary,
    DealSynthesis,
    DocumentRecord,
    LLMCallFailure,
    PrecedentIssueRecord,
    PriorityAssessment,
)


def run_analysis(
    *,
    deal_name: str,
    documents: list[DocumentRecord],
    llm_provider: LLMProvider,
    logger: logging.Logger,
    extraction_errors: list[str] | None = None,
    mode: str = "full",
    autonomous_learning_enabled: bool = False,
    autonomous_store_path: Path | None = None,
    web_researcher: OpenAIWebResearcher | None = None,
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
    contradictions = (
        detect_contradictions(document_analyses, key_risks, missing_items)
        if analysis_mode == "full"
        else []
    )
    omission_assessments = build_omission_assessments(document_analyses)
    precedent_engine = build_precedent_engine(
        deal_name=deal_name,
        documents=documents,
        logger=logger,
    )
    resolved_autonomous_store_path = autonomous_store_path or default_autonomous_store_path(precedent_engine.store_path)
    autonomous_learning_records = (
        load_autonomous_learning_records(resolved_autonomous_store_path)
        if autonomous_learning_enabled and resolved_autonomous_store_path.exists()
        else []
    )
    learning_records = [
        *precedent_engine.records,
        *autonomous_learning_records,
    ]
    learning_engine = build_learning_engine(
        records=learning_records,
        deal_metadata=precedent_engine.deal_metadata,
        snapshot_path=default_learning_snapshot_path(precedent_engine.store_path),
    )
    registry = build_canonical_issue_registry(
        key_risks=key_risks,
        contradictions=contradictions,
        omission_assessments=omission_assessments,
        document_analyses=document_analyses,
        merge_arbiter=_merge_arbiter_for_provider(llm_provider, logger) if analysis_mode == "full" else None,
        precedent_retriever=precedent_engine.retrieve,
        learning_retriever=learning_engine.retrieve,
        deal_metadata=precedent_engine.deal_metadata,
    )
    reading_order, further_diligence_roadmap = apply_front_end_assessment(
        registry=registry,
        document_analyses=document_analyses,
        omission_assessments=omission_assessments,
        contradictions=contradictions,
    )
    recommendation = build_recommendation_from_registry(registry)
    web_research_results = []
    if analysis_mode == "full" and web_researcher is not None:
        try:
            web_research_results = web_researcher.research(
                deal_name=deal_name,
                registry=registry,
                document_analyses=document_analyses,
            )
            llm_calls_attempted += len(web_research_results)
            _apply_web_research_to_registry(registry, web_research_results)
        except Exception as exc:  # pragma: no cover - network/provider failure path
            logger.warning("Web research fallback failed: %s", _format_llm_exception(exc))
    registry.output_selections = build_section_selections(
        registry,
        recommendation,
        analysis_mode=analysis_mode,
    )
    issue_analyses = build_issue_analyses_from_registry(registry)
    priority_assessment = build_priority_assessment_from_registry(registry) if registry.issues else None
    challenge_findings = (
        build_adversarial_challenges_from_registry(
            registry=registry,
            document_analyses=document_analyses,
        )
        if analysis_mode == "full"
        else []
    )
    category_rollup = build_category_rollup_from_registry(registry)
    seller_questions = build_seller_questions_from_registry(registry)
    if analysis_mode == "fast":
        seller_questions = seller_questions[:6]
    executive_summary = build_overall_read_draft(
        deal_name=deal_name,
        registry=registry,
        recommendation=recommendation,
        entitlement_status=entitlement_status,
        challenge_findings=challenge_findings,
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

    autonomous_learning_records_out: list[PrecedentIssueRecord] = []
    autonomous_learning_summary = AutonomousLearningSummary(
        enabled=autonomous_learning_enabled,
        store_path=str(resolved_autonomous_store_path),
        reasoning="Autonomous learning is disabled for this run.",
    )
    if analysis_mode == "full" and autonomous_learning_enabled:
        autonomous_learning_records_out, autonomous_learning_summary = persist_autonomous_learning_records(
            deal_name=deal_name,
            registry=registry,
            store_path=resolved_autonomous_store_path,
            logger=logger,
        )

    return DealSynthesis(
        deal_name=deal_name,
        executive_summary=executive_summary,
        entitlement_status=entitlement_status,
        key_risks=key_risks,
        recommended_reading_order=reading_order,
        seller_questions=seller_questions,
        missing_items=missing_items,
        category_rollup=category_rollup,
        document_analyses=document_analyses,
        structured_facts=structured_facts,
        omission_assessments=omission_assessments,
        issue_analyses=issue_analyses,
        canonical_issue_registry=registry,
        challenge_findings=challenge_findings,
        priority_assessment=priority_assessment or PriorityAssessment(),
        recommendation=recommendation,
        contradictions=contradictions,
        further_diligence_roadmap=further_diligence_roadmap,
        web_research_results=web_research_results,
        autonomous_learning_summary=autonomous_learning_summary,
        autonomous_learning_records=autonomous_learning_records_out,
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


def _merge_arbiter_for_provider(llm_provider: LLMProvider, logger: logging.Logger):
    provider_method = getattr(llm_provider, "arbitrate_issue_merge", None)
    if provider_method is None:
        return None

    def _arbiter(left_fragment, right_fragment):
        try:
            return provider_method(
                left_issue=_fragment_for_arbiter(left_fragment),
                right_issue=_fragment_for_arbiter(right_fragment),
            )
        except Exception as exc:  # pragma: no cover - provider/network failure path
            logger.warning("Merge arbitration failed for %s vs %s: %s", left_fragment.fragment_id, right_fragment.fragment_id, _format_llm_exception(exc))
            return None

    return _arbiter


def _fragment_for_arbiter(fragment) -> dict[str, str]:
    return {
        "title": fragment.title,
        "category": fragment.category,
        "why_it_matters": fragment.why_it_matters,
        "likely_implication": fragment.likely_implication,
        "evidence_basis": fragment.source_type,
        "citations": "; ".join(fragment.source_documents[:3]),
    }


def _apply_web_research_to_registry(registry, web_research_results) -> None:
    for result in web_research_results:
        if result.status in {"answered", "partial"} and result.answer:
            registry.front_end_known_points.append(f"Public-file check on {result.title}: {result.answer}")
        elif result.status == "not_found":
            registry.front_end_unresolved_points.append(f"Public web search did not resolve {result.title.lower()}.")
