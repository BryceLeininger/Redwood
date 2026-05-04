"""Primary orchestration layer for the Outlook Email Secretary agent."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .config import OESConfig, load_config
from .graph_client import GraphConfigurationError, MicrosoftGraphClient
from .intelligence import OESIntelligence
from .local_outlook import LocalOutlookProvider
from .models import ApprovalActionType, ApprovalItem, ApprovalStatus, ReminderItem
from .storage import LocalStore


class OESAgent:
    def __init__(self, config: OESConfig | None = None, store: LocalStore | None = None) -> None:
        self.config = config or load_config()
        self.store = store or LocalStore(self.config.db_path)
        self.store.ensure_ready()
        self.intelligence = OESIntelligence(self.config)

    def authenticate_graph(self) -> dict[str, Any]:
        client = self._graph_client()
        try:
            result = client.authenticate(interactive=True)
            return {
                "authenticated": True,
                "account_username": result.account_username,
                "token_source": result.token_source,
                "scopes": result.scopes,
            }
        finally:
            client.close()

    def sync(
        self,
        sample_json_path: Path | None = None,
        mail_limit: int = 25,
        calendar_days: int = 14,
    ) -> dict[str, Any]:
        if sample_json_path is not None:
            raw_messages = self._load_sample_messages(sample_json_path)
            raw_events: list[dict[str, Any]] = []
            source = f"sample:{sample_json_path}"
        else:
            raw_messages, raw_events, source = self._load_live_mailbox(mail_limit=mail_limit, calendar_days=calendar_days)

        approvals_created = 0
        reminders_created = 0

        for raw_message in raw_messages:
            message = self.intelligence.analyze_message(raw_message)
            self.store.upsert_message(message)
            approvals_created += self._queue_message_actions(message)
            reminders_created += self._queue_message_reminders(message)

        for raw_event in raw_events:
            event = self.intelligence.analyze_event(raw_event)
            self.store.upsert_event(event)
            reminders_created += self._queue_event_reminders(event)

        self.store.set_sync_state("last_sync_source", source)
        return {
            "source": source,
            "messages_synced": len(raw_messages),
            "calendar_events_synced": len(raw_events),
            "pending_approvals": len(self.store.list_approvals()),
            "open_reminders": len(self.store.list_reminders()),
            "approvals_created": approvals_created,
            "reminders_created": reminders_created,
        }

    def approve(self, approval_id: int) -> dict[str, Any]:
        approval = self.store.get_approval(approval_id)
        if approval is None:
            raise ValueError(f"Approval item {approval_id} does not exist.")

        execution = {"approval_id": approval_id, "status": ApprovalStatus.APPROVED.value, "executed": False}
        if self.config.has_graph_config and approval.action_type in {
            ApprovalActionType.DRAFT_REPLY,
            ApprovalActionType.SEND_REPLY,
            ApprovalActionType.DELETE_MESSAGE,
            ApprovalActionType.CREATE_TASK,
        }:
            client = self._graph_client()
            try:
                if approval.action_type == ApprovalActionType.DRAFT_REPLY:
                    client.create_reply_draft(
                        approval.target_id,
                        comment=str(approval.details.get("draft_reply") or ""),
                    )
                elif approval.action_type == ApprovalActionType.SEND_REPLY:
                    client.send_message(approval.target_id)
                elif approval.action_type == ApprovalActionType.DELETE_MESSAGE:
                    client.delete_message(approval.target_id)
                elif approval.action_type == ApprovalActionType.CREATE_TASK:
                    client.create_task(
                        title=str(approval.details.get("title") or approval.title),
                        due_at=approval.details.get("due_at"),
                        body=str(approval.details.get("notes") or ""),
                    )
            finally:
                client.close()
            self.store.update_approval_status(approval_id, ApprovalStatus.EXECUTED)
            execution["status"] = ApprovalStatus.EXECUTED.value
            execution["executed"] = True
            return execution

        if approval.details.get("source_provider") == "outlook_desktop" and approval.action_type in {
            ApprovalActionType.DRAFT_REPLY,
            ApprovalActionType.SEND_REPLY,
            ApprovalActionType.DELETE_MESSAGE,
            ApprovalActionType.CREATE_TASK,
        }:
            provider = self._local_outlook_provider()
            store_id = approval.details.get("store_id")
            if approval.action_type == ApprovalActionType.DRAFT_REPLY:
                provider.create_reply_draft(
                    approval.target_id,
                    comment=str(approval.details.get("draft_reply") or ""),
                    store_id=None if store_id is None else str(store_id),
                )
            elif approval.action_type == ApprovalActionType.SEND_REPLY:
                provider.send_reply(
                    approval.target_id,
                    store_id=None if store_id is None else str(store_id),
                    comment=str(approval.details.get("draft_reply") or ""),
                )
            elif approval.action_type == ApprovalActionType.DELETE_MESSAGE:
                provider.delete_message(
                    approval.target_id,
                    store_id=None if store_id is None else str(store_id),
                )
            elif approval.action_type == ApprovalActionType.CREATE_TASK:
                provider.create_task(
                    title=str(approval.details.get("title") or approval.title),
                    due_at=approval.details.get("due_at"),
                    body=str(approval.details.get("notes") or ""),
                )
            self.store.update_approval_status(approval_id, ApprovalStatus.EXECUTED)
            execution["status"] = ApprovalStatus.EXECUTED.value
            execution["executed"] = True
            return execution

        self.store.update_approval_status(approval_id, ApprovalStatus.APPROVED)
        return execution

    def reject(self, approval_id: int) -> dict[str, Any]:
        approval = self.store.get_approval(approval_id)
        if approval is None:
            raise ValueError(f"Approval item {approval_id} does not exist.")
        self.store.update_approval_status(approval_id, ApprovalStatus.REJECTED)
        return {"approval_id": approval_id, "status": ApprovalStatus.REJECTED.value}

    def create_manual_reminder(self, title: str, due_at: str | None, notes: str = "") -> dict[str, Any]:
        reminder = ReminderItem(title=title, due_at=due_at, notes=notes, source_type="manual")
        self.store.add_reminder(reminder)
        return {"reminder_id": reminder.reminder_id, "status": reminder.status.value}

    def dashboard(self) -> dict[str, Any]:
        return {
            "messages": self.store.list_messages(),
            "events": self.store.list_events(),
            "approvals": self.store.list_approvals(),
            "reminders": self.store.list_reminders(),
            "graph_configured": self.config.has_graph_config,
            "local_outlook_available": self._local_outlook_status()["available"],
            "ai_configured": self.config.has_ai_config,
            "last_sync_source": self.store.get_sync_state("last_sync_source"),
        }

    def _graph_client(self) -> MicrosoftGraphClient:
        return MicrosoftGraphClient(self.config)

    def _local_outlook_provider(self) -> LocalOutlookProvider:
        return LocalOutlookProvider()

    def _local_outlook_status(self) -> dict[str, Any]:
        return LocalOutlookProvider.detect().to_dict()

    def _load_live_mailbox(self, mail_limit: int, calendar_days: int) -> tuple[list[dict[str, Any]], list[dict[str, Any]], str]:
        if self.config.has_graph_config:
            client = self._graph_client()
            try:
                raw_messages = client.list_inbox_messages(limit=mail_limit)
                raw_events = client.list_calendar_events(days=calendar_days)
            finally:
                client.close()
            return raw_messages, raw_events, "graph"

        outlook_status = LocalOutlookProvider.detect()
        if not outlook_status.available:
            raise GraphConfigurationError(
                "Live sync requires either OES_GRAPH_CLIENT_ID for Microsoft Graph or a working local Outlook desktop client. "
                f"Local Outlook status: {outlook_status.reason}"
            )

        provider = self._local_outlook_provider()
        raw_messages = provider.list_inbox_messages(limit=mail_limit)
        raw_events = provider.list_calendar_events(days=calendar_days)
        return raw_messages, raw_events, "outlook_desktop"

    def _load_sample_messages(self, sample_json_path: Path) -> list[dict[str, Any]]:
        if not sample_json_path.exists():
            raise FileNotFoundError(f"Sample inbox JSON not found: {sample_json_path}")
        payload = json.loads(sample_json_path.read_text(encoding="utf-8"))
        return list(payload.get("messages", []))

    def _queue_message_actions(self, message) -> int:
        created = 0
        if message.draft_reply and not self.store.has_pending_approval(ApprovalActionType.DRAFT_REPLY, message.message_id):
            approval = ApprovalItem(
                action_type=ApprovalActionType.DRAFT_REPLY,
                target_type="message",
                target_id=message.message_id,
                title=f"Create reply draft: {message.subject}",
                details={
                    "subject": message.subject,
                    "draft_reply": message.draft_reply,
                    "priority": message.priority.value,
                    "store_id": message.raw_payload.get("storeId"),
                    "source_provider": message.raw_payload.get("sourceProvider"),
                },
            )
            self.store.add_approval(approval)
            created += 1

        if message.action_items and not self.store.has_pending_approval(ApprovalActionType.CREATE_TASK, message.message_id):
            task_title = f"Task from email: {message.subject}"
            approval = ApprovalItem(
                action_type=ApprovalActionType.CREATE_TASK,
                target_type="message",
                target_id=message.message_id,
                title=task_title,
                details={
                    "title": task_title,
                    "notes": message.action_items[0],
                    "due_at": None,
                    "store_id": message.raw_payload.get("storeId"),
                    "source_provider": message.raw_payload.get("sourceProvider"),
                },
            )
            self.store.add_approval(approval)
            created += 1
        return created

    def _queue_message_reminders(self, message) -> int:
        created = 0
        for index, action_item in enumerate(message.action_items, start=1):
            reminder_title = f"Email follow-up: {message.subject}"
            reminder_source_id = f"{message.message_id}:{index}"
            if not self.store.has_open_reminder("message_action_item", reminder_source_id, reminder_title):
                self.store.add_reminder(
                    ReminderItem(
                        title=reminder_title,
                        due_at=None,
                        notes=action_item,
                        source_type="message_action_item",
                        source_id=reminder_source_id,
                    )
                )
                created += 1
        return created

    def _queue_event_reminders(self, event) -> int:
        reminder_title = f"Prepare for: {event.subject}"
        if self.store.has_open_reminder("calendar_event", event.event_id, reminder_title):
            return 0
        self.store.add_reminder(
            ReminderItem(
                title=reminder_title,
                due_at=event.start_at,
                notes=event.summary,
                source_type="calendar_event",
                source_id=event.event_id,
            )
        )
        return 1