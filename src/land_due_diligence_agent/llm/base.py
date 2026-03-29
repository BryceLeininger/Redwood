"""Abstract LLM provider contract."""

from __future__ import annotations

from abc import ABC, abstractmethod

from land_due_diligence_agent.models import ContradictionFinding, DocumentRecord, RiskFinding


class LLMProvider(ABC):
    """Base class for provider-specific summary refinement."""

    provider_name = "base"

    @abstractmethod
    def refine_document_summary(
        self,
        document: DocumentRecord,
        draft_summary: str,
        risks: list[RiskFinding],
        missing_items: list[str],
    ) -> str:
        """Return a polished per-document summary."""

    @abstractmethod
    def refine_executive_summary(
        self,
        deal_name: str,
        draft_summary: str,
        category_rollup: dict[str, str],
        key_risks: list[RiskFinding],
        contradictions: list[ContradictionFinding],
        missing_items: list[str],
    ) -> str:
        """Return a polished deal-level executive summary."""

    def arbitrate_issue_merge(
        self,
        *,
        left_issue: dict[str, str],
        right_issue: dict[str, str],
    ) -> tuple[str, str] | None:
        """Optionally classify an ambiguous issue-merge relationship.

        Returns a tuple of `(relation, rationale)` where relation is one of
        `same_issue`, `parent_child`, `related_but_distinct`, or `separate`.
        Providers may return `None` to skip arbitration.
        """

        return None
