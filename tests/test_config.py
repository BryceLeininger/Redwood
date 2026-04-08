"""Tests for environment-backed settings."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from land_due_diligence_agent.config import Settings


class ConfigTests(unittest.TestCase):
    def test_blank_openai_base_url_is_sanitized(self) -> None:
        original_env = os.environ.copy()
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                env_path = Path(temp_dir) / ".env"
                env_path.write_text(
                    "LLM_PROVIDER=openai\n"
                    "OPENAI_API_KEY=test-key\n"
                    "OPENAI_MODEL=gpt-4.1\n"
                    "AUTONOMOUS_LEARNING_ENABLED=true\n"
                    "WEB_RESEARCH_ENABLED=true\n"
                    "WEB_RESEARCH_MODEL=gpt-4.1\n"
                    "WEB_RESEARCH_MAX_QUERIES=3\n"
                    "OPENAI_BASE_URL=\n",
                    encoding="utf-8",
                )
                os.environ.clear()
                settings = Settings.from_env_path(env_path)
                self.assertEqual(settings.llm_provider, "openai")
                self.assertEqual(settings.openai_model, "gpt-4.1")
                self.assertTrue(settings.autonomous_learning_enabled)
                self.assertTrue(settings.web_research_enabled)
                self.assertEqual(settings.web_research_model, "gpt-4.1")
                self.assertEqual(settings.web_research_max_queries, 3)
                self.assertIsNone(settings.openai_base_url)
                self.assertNotIn("OPENAI_BASE_URL", os.environ)
        finally:
            os.environ.clear()
            os.environ.update(original_env)

    def test_autonomous_and_web_research_settings_are_loaded(self) -> None:
        original_env = os.environ.copy()
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                env_path = Path(temp_dir) / ".env"
                env_path.write_text(
                    "AUTONOMOUS_LEARNING_ENABLED=true\n"
                    "WEB_RESEARCH_ENABLED=false\n"
                    "WEB_RESEARCH_MAX_QUERIES=6\n",
                    encoding="utf-8",
                )
                os.environ.clear()
                settings = Settings.from_env_path(env_path)
                self.assertTrue(settings.autonomous_learning_enabled)
                self.assertFalse(settings.web_research_enabled)
                self.assertEqual(settings.web_research_max_queries, 6)
        finally:
            os.environ.clear()
            os.environ.update(original_env)


if __name__ == "__main__":
    unittest.main()
