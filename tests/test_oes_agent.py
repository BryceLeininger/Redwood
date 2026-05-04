"""Tests for the Outlook Email Secretary agent."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from oes_agent.agent import OESAgent
from oes_agent.config import DEFAULT_GRAPH_SCOPES, OESConfig
from oes_agent.storage import LocalStore


def _build_test_config(root: Path) -> OESConfig:
    data_dir = root / "oes_state"
    data_dir.mkdir(parents=True, exist_ok=True)
    return OESConfig(
        data_dir=data_dir,
        db_path=data_dir / "oes_agent.db",
        token_cache_path=data_dir / "graph_token_cache.bin",
        host="127.0.0.1",
        port=8787,
        graph_client_id=None,
        graph_tenant_id="common",
        graph_scopes=DEFAULT_GRAPH_SCOPES,
        openai_api_key=None,
        openai_model="gpt-4.1-mini",
    )


def _write_sample_inbox(path: Path) -> None:
    payload = {
        "source": "test-sample",
        "count": 1,
        "messages": [
            {
                "id": "sample-message-1",
                "subject": "Deposit analysis needed by tomorrow",
                "from": {
                    "emailAddress": {
                        "name": "Holly Cordova",
                        "address": "holly@example.com",
                    }
                },
                "receivedDateTime": "2026-05-01T14:00:00+00:00",
                "isRead": False,
                "categories": [],
                "bodyPreview": (
                    "Please review the deposit analysis and send the settlement comments tomorrow. "
                    "We need your feedback before escrow can finalize the statement."
                ),
            }
        ],
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


class OESAgentTests(unittest.TestCase):
    def test_sample_sync_creates_messages_approvals_and_reminders(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            sample_path = root / "sample_inbox.json"
            _write_sample_inbox(sample_path)

            config = _build_test_config(root)
            store = LocalStore(config.db_path)
            agent = OESAgent(config=config, store=store)

            result = agent.sync(sample_json_path=sample_path)
            dashboard = agent.dashboard()

            self.assertEqual(result["messages_synced"], 1)
            self.assertEqual(len(dashboard["messages"]), 1)
            self.assertGreaterEqual(len(dashboard["approvals"]), 1)
            self.assertGreaterEqual(len(dashboard["reminders"]), 1)

    def test_repeat_sync_does_not_duplicate_pending_approvals_or_reminders(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            sample_path = root / "sample_inbox.json"
            _write_sample_inbox(sample_path)

            config = _build_test_config(root)
            store = LocalStore(config.db_path)
            agent = OESAgent(config=config, store=store)

            agent.sync(sample_json_path=sample_path)
            first_dashboard = agent.dashboard()
            agent.sync(sample_json_path=sample_path)
            second_dashboard = agent.dashboard()

            self.assertEqual(len(first_dashboard["approvals"]), len(second_dashboard["approvals"]))
            self.assertEqual(len(first_dashboard["reminders"]), len(second_dashboard["reminders"]))

    def test_approve_without_graph_marks_item_approved_without_execution(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            sample_path = root / "sample_inbox.json"
            _write_sample_inbox(sample_path)

            config = _build_test_config(root)
            store = LocalStore(config.db_path)
            agent = OESAgent(config=config, store=store)

            agent.sync(sample_json_path=sample_path)
            approval = agent.dashboard()["approvals"][0]

            result = agent.approve(int(approval.approval_id))

            self.assertEqual(result["status"], "approved")
            self.assertFalse(result["executed"])


if __name__ == "__main__":
    unittest.main()