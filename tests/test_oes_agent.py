"""Tests for the Outlook Email Secretary agent."""

from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from oes_agent.agent import OESAgent
from oes_agent.config import DEFAULT_GRAPH_SCOPES, OESConfig
from oes_agent.scheduler import OESBackgroundScheduler
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
        background_sync_enabled=True,
        background_sync_minutes=15,
        morning_summary_enabled=True,
        morning_summary_hour=7,
        morning_summary_minute=0,
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


def _write_low_risk_live_inbox(path: Path) -> None:
    payload = {
        "source": "test-live-sample",
        "count": 1,
        "messages": [
            {
                "id": "live-message-1",
                "subject": "Thanks for the update",
                "from": {
                    "emailAddress": {
                        "name": "Dean Mills",
                        "address": "dean@example.com",
                    }
                },
                "receivedDateTime": "2026-05-01T16:00:00+00:00",
                "isRead": False,
                "categories": [],
                "bodyPreview": "Thank you for confirming the presentation is ready. I appreciate the quick turnaround.",
                "sourceProvider": "outlook_desktop",
                "storeId": "store-123",
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

    def test_generate_morning_summary_persists_summary_text(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            sample_path = root / "sample_inbox.json"
            _write_sample_inbox(sample_path)

            config = _build_test_config(root)
            store = LocalStore(config.db_path)
            agent = OESAgent(config=config, store=store)

            agent.sync(sample_json_path=sample_path)
            result = agent.generate_morning_summary(force=True)
            dashboard = agent.dashboard()

            self.assertTrue(result["generated"])
            self.assertIn("Morning summary for", result["summary_text"])
            self.assertEqual(result["summary_text"], dashboard["morning_summary_text"])

    def test_scheduler_generates_summary_once_due(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            sample_path = root / "sample_inbox.json"
            _write_sample_inbox(sample_path)

            config = _build_test_config(root)
            config = OESConfig(
                data_dir=config.data_dir,
                db_path=config.db_path,
                token_cache_path=config.token_cache_path,
                host=config.host,
                port=config.port,
                graph_client_id=config.graph_client_id,
                graph_tenant_id=config.graph_tenant_id,
                graph_scopes=config.graph_scopes,
                openai_api_key=config.openai_api_key,
                openai_model=config.openai_model,
                background_sync_enabled=False,
                background_sync_minutes=15,
                morning_summary_enabled=True,
                morning_summary_hour=7,
                morning_summary_minute=0,
            )
            store = LocalStore(config.db_path)
            agent = OESAgent(config=config, store=store)
            agent.sync(sample_json_path=sample_path)
            scheduler = OESBackgroundScheduler(agent=agent, config=config)

            result = scheduler.run_once(now=datetime.fromisoformat("2026-05-02T07:05:00+00:00"))

            self.assertFalse(result["sync_triggered"])
            self.assertTrue(result["summary_triggered"])
            self.assertIsNotNone(agent.dashboard()["morning_summary_text"])

    def test_low_risk_live_message_is_auto_drafted_without_pending_approval(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            sample_path = root / "live_inbox.json"
            _write_low_risk_live_inbox(sample_path)

            config = _build_test_config(root)
            store = LocalStore(config.db_path)
            agent = OESAgent(config=config, store=store)

            with patch("oes_agent.agent.LocalOutlookProvider") as provider_class:
                provider = provider_class.return_value
                result = agent.sync(sample_json_path=sample_path)

            dashboard = agent.dashboard()

            provider.create_reply_draft.assert_called_once()
            self.assertEqual(result["auto_drafted_replies"], 1)
            self.assertEqual(len(dashboard["approvals"]), 0)
            self.assertTrue(dashboard["messages"][0].raw_payload.get("autoDrafted"))


if __name__ == "__main__":
    unittest.main()