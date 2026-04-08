"""Public-web fallback for unresolved diligence questions."""

from __future__ import annotations

import logging

from openai import OpenAI

from land_due_diligence_agent.models import CanonicalIssueRegistry, DocumentAnalysis, WebResearchResult
from land_due_diligence_agent.utils.text import clip_text, normalize_text, unique_preserve_order

_WEB_SEARCH_LOCATION = {
    "type": "approximate",
    "country": "US",
}


class OpenAIWebResearcher:
    """Use the OpenAI web search tool to answer unresolved public-facing questions."""

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        base_url: str | None = None,
        max_queries: int = 4,
        logger: logging.Logger | None = None,
    ) -> None:
        self.client = OpenAI(api_key=api_key, base_url=base_url)
        self.model = model
        self.max_queries = max_queries
        self.logger = logger

    def research(
        self,
        *,
        deal_name: str,
        registry: CanonicalIssueRegistry,
        document_analyses: list[DocumentAnalysis],
    ) -> list[WebResearchResult]:
        findings: list[WebResearchResult] = []
        for issue in _select_web_research_issues(registry)[: self.max_queries]:
            question = issue.open_questions[0] if issue.open_questions else issue.missing_confirmation or issue.what_would_resolve_it
            if not question:
                question = f"What public information resolves whether {issue.title.lower()}?"
            query_hint = _query_hint(issue, deal_name, document_analyses)
            try:
                response = self.client.responses.create(
                    model=self.model,
                    tools=[{"type": "web_search", "user_location": _WEB_SEARCH_LOCATION}],
                    input=_web_prompt(
                        deal_name=deal_name,
                        issue_title=issue.title,
                        category=issue.category,
                        question=question,
                        query_hint=query_hint,
                        package_context=issue.site_specific_trigger or issue.why_it_matters or issue.likely_implication,
                    ),
                    max_output_tokens=280,
                )
                findings.append(
                    _result_from_response(
                        response=response,
                        issue_id=issue.issue_id,
                        title=issue.title,
                        question=question,
                    )
                )
            except Exception as exc:  # pragma: no cover - network/provider failure path
                detail = normalize_text(str(exc) or "<no message>")
                if self.logger is not None:
                    self.logger.warning("Web research failed for %s: %s", issue.issue_id, detail)
                findings.append(
                    WebResearchResult(
                        issue_id=issue.issue_id,
                        title=issue.title,
                        question=question,
                        query=query_hint,
                        status="failed",
                        confidence="low",
                        note=f"Web research failed: {detail}",
                    )
                )
        return findings


def _select_web_research_issues(registry: CanonicalIssueRegistry):
    return sorted(
        [
            issue
            for issue in registry.issues
            if issue.why_now in {"investigate now", "investigate after initial read", "investigate before underwriting"}
            and (
                issue.front_end_flag in {"document gap", "stale-information concern", "conflict / contradiction concern"}
                or issue.information_status in {"missing and important", "stale and potentially unreliable", "conflicting across documents"}
                or issue.evidence_basis in {"omission_only", "routine_missing_support", "weak_inference"}
            )
        ],
        key=lambda issue: (
            {"investigate now": 0, "investigate after initial read": 1, "investigate before underwriting": 2}.get(issue.why_now, 3),
            -int(issue.blocking_flag),
            -issue.priority_score.total,
            issue.title,
        ),
    )


def _query_hint(issue, deal_name: str, document_analyses: list[DocumentAnalysis]) -> str:
    source_titles = [
        analysis.document.title
        for analysis in document_analyses
        if analysis.document.title in issue.source_documents
    ]
    hint_parts = [
        deal_name,
        issue.title,
        issue.site_specific_trigger,
        issue.category,
        source_titles[0] if source_titles else "",
    ]
    query = " ".join(part for part in hint_parts if part)
    return clip_text(normalize_text(query), 220)


def _web_prompt(
    *,
    deal_name: str,
    issue_title: str,
    category: str,
    question: str,
    query_hint: str,
    package_context: str,
) -> str:
    return (
        "Research the unresolved land diligence question using public web sources.\n"
        "Use the query hint as search context, but only answer from public sources actually found.\n"
        "If the web does not answer the question, say so directly.\n"
        "Return exactly four lines:\n"
        "status: answered|partial|not_found\n"
        "answer: <one short sentence>\n"
        "confidence: high|medium|low\n"
        "next_step: <one short sentence>\n\n"
        f"Deal: {deal_name}\n"
        f"Issue: {issue_title}\n"
        f"Category: {category}\n"
        f"Question: {question}\n"
        f"Query hint: {query_hint}\n"
        f"Package context: {clip_text(normalize_text(package_context), 260)}"
    )


def _result_from_response(*, response, issue_id: str, title: str, question: str) -> WebResearchResult:
    text = normalize_text(getattr(response, "output_text", "") or "")
    parsed = _parse_response_lines(text)
    source_titles: list[str] = []
    source_urls: list[str] = []

    for item in getattr(response, "output", []) or []:
        if getattr(item, "type", "") == "web_search_call":
            action = getattr(item, "action", None)
            if getattr(action, "type", "") == "search":
                for source in getattr(action, "sources", []) or []:
                    url = getattr(source, "url", "")
                    if url:
                        source_urls.append(url)
        for content in getattr(item, "content", []) or []:
            for annotation in getattr(content, "annotations", []) or []:
                if getattr(annotation, "type", "") == "url_citation":
                    title_text = getattr(annotation, "title", "") or getattr(annotation, "url", "")
                    url = getattr(annotation, "url", "")
                    if title_text:
                        source_titles.append(title_text)
                    if url:
                        source_urls.append(url)

    unique_urls = unique_preserve_order(source_urls)[:6]
    unique_titles = unique_preserve_order(source_titles)[:6]
    status = parsed.get("status", "not_found")
    answer = parsed.get("answer", "")
    if not answer and status != "not_found":
        status = "not_found"

    return WebResearchResult(
        issue_id=issue_id,
        title=title,
        question=question,
        query=_last_search_query(response) or "",
        status=status,
        answer=answer,
        confidence=parsed.get("confidence", "low"),
        next_step=parsed.get("next_step", ""),
        source_titles=unique_titles,
        source_urls=unique_urls,
        note="" if unique_urls else "No cited public source was returned.",
    )


def _parse_response_lines(text: str) -> dict[str, str]:
    parsed = {"status": "not_found", "answer": "", "confidence": "low", "next_step": ""}
    for line in text.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        normalized_key = key.strip().lower()
        normalized_value = normalize_text(value)
        if normalized_key in {"status", "answer", "confidence", "next_step"}:
            parsed[normalized_key] = normalized_value
    if parsed["status"] not in {"answered", "partial", "not_found"}:
        parsed["status"] = "not_found"
    if parsed["confidence"] not in {"high", "medium", "low"}:
        parsed["confidence"] = "low"
    return parsed


def _last_search_query(response) -> str:
    queries: list[str] = []
    for item in getattr(response, "output", []) or []:
        if getattr(item, "type", "") != "web_search_call":
            continue
        action = getattr(item, "action", None)
        if getattr(action, "type", "") == "search":
            query = normalize_text(getattr(action, "query", "") or "")
            if query:
                queries.append(query)
    return queries[-1] if queries else ""


WebResearchAgent = OpenAIWebResearcher
