"""OpenAI-backed summary refinement provider."""

from __future__ import annotations

from openai import OpenAI

from land_due_diligence_agent.llm.base import LLMProvider
from land_due_diligence_agent.models import ContradictionFinding, DocumentRecord, RiskFinding
from land_due_diligence_agent.utils.text import clip_text

_DOCUMENT_TEXT_LIMIT = 6000
_DOCUMENT_TEXT_RETRY_LIMIT = 2500
_EXECUTIVE_SECTION_LIMIT = 4000
_EXECUTIVE_SECTION_RETRY_LIMIT = 1800


class OpenAIProvider(LLMProvider):
    """Refine heuristic summaries with an OpenAI text model."""

    provider_name = "openai"

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        base_url: str | None = None,
    ) -> None:
        if base_url and not base_url.startswith(("http://", "https://")):
            raise ValueError("OPENAI_BASE_URL must start with http:// or https:// when it is set.")

        self.client = OpenAI(api_key=api_key, base_url=base_url)
        self.model = model
        self.base_url = base_url

    def refine_document_summary(
        self,
        document: DocumentRecord,
        draft_summary: str,
        risks: list[RiskFinding],
        missing_items: list[str],
    ) -> str:
        primary_prompt = self._build_document_prompt(
            document=document,
            draft_summary=draft_summary,
            risks=risks,
            missing_items=missing_items,
            text_limit=_DOCUMENT_TEXT_LIMIT,
        )
        retry_prompt = self._build_document_prompt(
            document=document,
            draft_summary=draft_summary,
            risks=risks[:3],
            missing_items=missing_items[:3],
            text_limit=_DOCUMENT_TEXT_RETRY_LIMIT,
            compact=True,
        )
        return self._generate_with_retry(
            primary_prompt=primary_prompt,
            retry_prompt=retry_prompt,
            stage="document_summary",
            target=document.relative_path.as_posix(),
            max_output_tokens=350,
        )

    def refine_executive_summary(
        self,
        deal_name: str,
        draft_summary: str,
        category_rollup: dict[str, str],
        key_risks: list[RiskFinding],
        contradictions: list[ContradictionFinding],
        missing_items: list[str],
    ) -> str:
        primary_prompt = self._build_executive_prompt(
            deal_name=deal_name,
            draft_summary=draft_summary,
            category_rollup=category_rollup,
            key_risks=key_risks,
            contradictions=contradictions,
            missing_items=missing_items,
            section_limit=_EXECUTIVE_SECTION_LIMIT,
        )
        retry_prompt = self._build_executive_prompt(
            deal_name=deal_name,
            draft_summary=draft_summary,
            category_rollup=category_rollup,
            key_risks=key_risks[:5],
            contradictions=contradictions[:3],
            missing_items=missing_items[:5],
            section_limit=_EXECUTIVE_SECTION_RETRY_LIMIT,
            compact=True,
        )
        return self._generate_with_retry(
            primary_prompt=primary_prompt,
            retry_prompt=retry_prompt,
            stage="executive_summary",
            target=deal_name,
            max_output_tokens=450,
        )

    def _build_document_prompt(
        self,
        *,
        document: DocumentRecord,
        draft_summary: str,
        risks: list[RiskFinding],
        missing_items: list[str],
        text_limit: int,
        compact: bool = False,
    ) -> str:
        risk_text = "\n".join(f"- {risk.category} ({risk.severity}): {risk.summary}" for risk in risks)
        if not risk_text:
            risk_text = "- No concentrated risk signals detected."
        missing_text = "\n".join(f"- {item}" for item in missing_items)
        if not missing_text:
            missing_text = "- No document-specific missing items detected."
        prompt_intro = (
            "Rewrite the following land acquisition diligence document summary into two concise paragraphs. "
            "Keep the tone factual, avoid hype, and emphasize implications for an acquisitions reviewer."
        )
        if compact:
            prompt_intro = (
                "Rewrite the following land acquisition diligence document summary into one short, factual paragraph. "
                "Prioritize the highest-value risks and caveats only."
            )
        return (
            f"{prompt_intro}\n\n"
            f"Document: {document.title}\n"
            f"Source: {document.relative_path.as_posix()}\n"
            f"Warnings: {', '.join(document.warnings) or 'None'}\n"
            f"Current summary:\n{clip_text(draft_summary, 1500)}\n\n"
            f"Detected risks:\n{clip_text(risk_text, 2000)}\n\n"
            f"Potential missing items:\n{clip_text(missing_text, 1000)}\n\n"
            f"Extracted text sample:\n{clip_text(document.normalized_text, text_limit)}"
        )

    def _build_executive_prompt(
        self,
        *,
        deal_name: str,
        draft_summary: str,
        category_rollup: dict[str, str],
        key_risks: list[RiskFinding],
        contradictions: list[ContradictionFinding],
        missing_items: list[str],
        section_limit: int,
        compact: bool = False,
    ) -> str:
        rollup_text = "\n".join(f"- {category}: {summary}" for category, summary in category_rollup.items())
        risk_text = "\n".join(
            f"- {risk.category} ({risk.severity}, tier={risk.priority_tier or 'unspecified'})\n"
            f"  anchor: {risk.anchor or 'Not specified'}\n"
            f"  source: {'; '.join(f'{citation.document_name} p. {citation.page_number}' if citation.page_number is not None else citation.document_name for citation in risk.citations[:2]) or 'Not specified'}\n"
            f"  issue: {risk.issue or risk.summary}\n"
            f"  why it matters: {risk.why_it_matters or 'Not specified'}\n"
            f"  likely implication: {risk.likely_implication or 'Not specified'}\n"
            f"  gating: {', '.join(risk.gating_flags) or 'None'}\n"
            f"  uncertainty: {risk.uncertainty_reason or 'None'}"
            for risk in key_risks
        )
        if not risk_text:
            risk_text = "- No concentrated risk signals detected."
        contradiction_text = "\n".join(
            f"- description: {finding.description}\n"
            f"  why it matters: {finding.why_it_matters}\n"
            f"  sources: {'; '.join(f'{citation.document_name} p. {citation.page_number}' if citation.page_number is not None else citation.document_name for citation in finding.citations[:2]) or 'Not specified'}"
            for finding in contradictions
        )
        if not contradiction_text:
            contradiction_text = "- No material cross-document contradictions were isolated."
        missing_text = "\n".join(f"- {item}" for item in missing_items)
        if not missing_text:
            missing_text = "- No obvious diligence gaps detected from keyword coverage."
        prompt_intro = (
            "Write a concise overall read for a land acquisition manager preparing a recommendation. "
            "Use two short paragraphs at most. Lead with the top 2-3 deal-shaping issues. Anchor each issue to the cited document or document type when possible. "
            "Do not use generic phrases like 'mixed picture' or 'the package suggests'. Avoid 'may' and 'could' unless uncertainty comes from missing data, OCR limits, or incomplete reports. "
            "Where the documents conflict or pull in different directions, call out the contradiction directly and explain why it changes underwriting or execution confidence. "
            "Make clear what is known, what remains unresolved, and what is gating before closing, underwriting confidence, or vertical start. "
            "Do not simply list diligence categories."
        )
        if compact:
            prompt_intro = (
                "Write one short, decisive overall read for a land acquisition decision-maker. "
                "Keep only the highest-priority, document-anchored conclusions and unresolved gating issues. Do not use generic filler."
            )
        return (
            f"{prompt_intro}\n\n"
            f"Deal: {deal_name}\n"
            f"Current summary:\n{clip_text(draft_summary, 1800)}\n\n"
            f"Category rollup:\n{clip_text(rollup_text, section_limit)}\n\n"
            f"Key risks:\n{clip_text(risk_text, 1800)}\n\n"
            f"Potential contradictions / tensions:\n{clip_text(contradiction_text, 1400)}\n\n"
            f"Missing items:\n{clip_text(missing_text, 1000)}"
        )

    def _generate_with_retry(
        self,
        *,
        primary_prompt: str,
        retry_prompt: str,
        stage: str,
        target: str,
        max_output_tokens: int,
    ) -> str:
        attempts = [(1, primary_prompt)]
        if retry_prompt != primary_prompt:
            attempts.append((2, retry_prompt))

        failure_messages: list[str] = []
        last_exception: Exception | None = None

        for attempt_number, prompt in attempts:
            try:
                response = self.client.responses.create(
                    model=self.model,
                    input=prompt,
                    max_output_tokens=max_output_tokens,
                )
                text = (response.output_text or "").strip()
                if not text:
                    raise RuntimeError("OpenAI provider returned an empty response.")
                return text
            except Exception as exc:  # pragma: no cover - network/provider failure path
                last_exception = exc
                failure_messages.append(
                    self._format_failure_detail(
                        exc,
                        stage=stage,
                        target=target,
                        attempt_number=attempt_number,
                        prompt_chars=len(prompt),
                    )
                )

        raise RuntimeError(" | ".join(failure_messages)) from last_exception

    def _format_failure_detail(
        self,
        exc: Exception,
        *,
        stage: str,
        target: str,
        attempt_number: int,
        prompt_chars: int,
    ) -> str:
        chain: list[str] = []
        current: BaseException | None = exc
        while current is not None:
            detail = str(current).strip() or "<no message>"
            chain.append(f"{type(current).__name__}: {detail}")
            current = current.__cause__

        return (
            f"{stage} attempt {attempt_number} failed for {target} "
            f"(model={self.model}, prompt_chars={prompt_chars}): {' <- '.join(chain)}"
        )
