"""OpenAI-backed summary refinement provider."""

from __future__ import annotations

from openai import OpenAI

from land_due_diligence_agent.llm.base import LLMProvider
from land_due_diligence_agent.models import DocumentRecord, RiskFinding
from land_due_diligence_agent.utils.text import clip_text


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
        self.client = OpenAI(api_key=api_key, base_url=base_url)
        self.model = model

    def refine_document_summary(
        self,
        document: DocumentRecord,
        draft_summary: str,
        risks: list[RiskFinding],
        missing_items: list[str],
    ) -> str:
        risk_text = "\n".join(f"- {risk.category} ({risk.severity}): {risk.summary}" for risk in risks) or "- No concentrated risk signals detected."
        missing_text = "\n".join(f"- {item}" for item in missing_items) or "- No document-specific missing items detected."
        prompt = (
            "Rewrite the following land acquisition diligence document summary into two concise paragraphs. "
            "Keep the tone factual, avoid hype, and emphasize implications for an acquisitions reviewer.\n\n"
            f"Document: {document.title}\n"
            f"Source: {document.relative_path.as_posix()}\n"
            f"Warnings: {', '.join(document.warnings) or 'None'}\n"
            f"Current summary:\n{draft_summary}\n\n"
            f"Detected risks:\n{risk_text}\n\n"
            f"Potential missing items:\n{missing_text}\n\n"
            f"Extracted text sample:\n{clip_text(document.normalized_text, 6000)}"
        )
        return self._generate(prompt)

    def refine_executive_summary(
        self,
        deal_name: str,
        draft_summary: str,
        category_rollup: dict[str, str],
        key_risks: list[RiskFinding],
        missing_items: list[str],
    ) -> str:
        rollup_text = "\n".join(f"- {category}: {summary}" for category, summary in category_rollup.items())
        risk_text = "\n".join(f"- {risk.category} ({risk.severity}): {risk.summary}" for risk in key_risks) or "- No concentrated risk signals detected."
        missing_text = "\n".join(f"- {item}" for item in missing_items) or "- No obvious diligence gaps detected from keyword coverage."
        prompt = (
            "Rewrite the following deal-level diligence synthesis into two short paragraphs. "
            "Keep it concise, factual, and framed for a land acquisition decision-maker.\n\n"
            f"Deal: {deal_name}\n"
            f"Current summary:\n{draft_summary}\n\n"
            f"Category rollup:\n{rollup_text}\n\n"
            f"Key risks:\n{risk_text}\n\n"
            f"Missing items:\n{missing_text}"
        )
        return self._generate(prompt)

    def _generate(self, prompt: str) -> str:
        response = self.client.responses.create(
            model=self.model,
            input=prompt,
        )
        text = (response.output_text or "").strip()
        if not text:
            raise RuntimeError("OpenAI provider returned an empty response.")
        return text
