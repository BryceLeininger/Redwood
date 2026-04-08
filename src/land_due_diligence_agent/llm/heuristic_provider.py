"""Local-only provider that returns deterministic draft summaries unchanged."""

from __future__ import annotations

from land_due_diligence_agent.llm.base import LLMProvider
from land_due_diligence_agent.models import ContradictionFinding, DocumentRecord, RiskFinding


class HeuristicProvider(LLMProvider):
    """No-upload fallback provider."""

    provider_name = "heuristic"

    def refine_document_summary(
        self,
        document: DocumentRecord,
        draft_summary: str,
        risks: list[RiskFinding],
        missing_items: list[str],
    ) -> str:
        return draft_summary

    def refine_executive_summary(
        self,
        deal_name: str,
        draft_summary: str,
        category_rollup: dict[str, str],
        key_risks: list[RiskFinding],
        contradictions: list[ContradictionFinding],
        missing_items: list[str],
    ) -> str:
        return draft_summary
