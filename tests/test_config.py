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
                    "OPENAI_BASE_URL=\n",
                    encoding="utf-8",
                )
                os.environ.clear()
                settings = Settings.from_env_path(env_path)
                self.assertEqual(settings.llm_provider, "openai")
                self.assertEqual(settings.openai_model, "gpt-4.1")
                self.assertIsNone(settings.openai_base_url)
                self.assertNotIn("OPENAI_BASE_URL", os.environ)
        finally:
            os.environ.clear()
            os.environ.update(original_env)


if __name__ == "__main__":
    unittest.main()
