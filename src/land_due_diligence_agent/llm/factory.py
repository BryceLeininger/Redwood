"""Factory for LLM provider selection."""

from __future__ import annotations

import logging

from land_due_diligence_agent.config import Settings
from land_due_diligence_agent.llm.base import LLMProvider
from land_due_diligence_agent.llm.heuristic_provider import HeuristicProvider
from land_due_diligence_agent.llm.openai_provider import OpenAIProvider


def build_llm_provider(settings: Settings, logger: logging.Logger) -> LLMProvider:
    """Return the configured provider, falling back safely when needed."""

    if settings.llm_provider == "openai":
        if not settings.openai_api_key:
            logger.warning("LLM_PROVIDER=openai but OPENAI_API_KEY is not set. Falling back to heuristic mode.")
            return HeuristicProvider()
        return OpenAIProvider(
            api_key=settings.openai_api_key,
            model=settings.openai_model,
            base_url=settings.openai_base_url,
        )

    if settings.llm_provider != "heuristic":
        logger.warning("Unknown LLM provider '%s'. Falling back to heuristic mode.", settings.llm_provider)

    return HeuristicProvider()
