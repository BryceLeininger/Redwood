"""Primary orchestration layer for the Outlook Email Secretary agent."""

from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from typing import Any

from .config import OESConfig, load_config
from .graph_client import GraphConfigurationError, MicrosoftGraphClient
from .intelligence import OESIntelligence
from .local_outlook import LocalOutlookProvider
from .models import ApprovalActionType, ApprovalItem, ApprovalStatus, Priority, ReminderItem
from .storage import LocalStore


class OESAgent:
    AUTO_DRAFT_STATE_KEY_PREFIX = "message_auto_draft:"
    AUTO_DRAFT_RESTRICTED_TERMS = (
        "closing",
        "escrow",
        "wire",
        "deposit",
        "settlement",
        "invoice",
        "budget",
        "contract",
        "approval",
        "signature",
        "urgent",
        "asap",
        "lawsuit",
        "legal",
    )
    AUTO_DRAFT_ACKNOWLEDGEMENT_TERMS = (
        "thank you",
        "thanks",
        "appreciate the update",
        "for your awareness",
        "for awareness",
        "announcement",
        "announcing",
        "confirmed",
        "confirmation",
        "is open",
        "now open",
        "good news",
        "fyi",
    )

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
        auto_drafted_replies = 0
        reminders_created = 0

        for raw_message in raw_messages:
            message = self.intelligence.analyze_message(raw_message)
            queued_approvals, auto_drafts = self._queue_message_actions(message)
            approvals_created += queued_approvals
            auto_drafted_replies += auto_drafts
            self.store.upsert_message(message)
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
            "auto_drafted_replies": auto_drafted_replies,
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

    def generate_morning_summary(self, force: bool = False, target_date: date | None = None) -> dict[str, Any]:
        summary_date = (target_date or datetime.now().astimezone().date()).isoformat()
        if not force and self.store.get_sync_state("morning_summary_for_date") == summary_date:
            return {
                "generated": False,
                "summary_date": summary_date,
                "summary_text": self.store.get_sync_state("morning_summary_text") or "",
            }

        messages = self.store.list_messages(limit=5)
        events = self.store.list_events(limit=5)
        approvals = self.store.list_approvals()
        reminders = self.store.list_reminders()

        message_lines = [
            f"- {message.priority.value.upper()}: {message.subject} ({message.sender_name})"
            for message in messages[:3]
        ]
        event_lines = [
            f"- {event.start_at}: {event.subject}"
            for event in events[:3]
        ]
        reminder_lines = [
            f"- {reminder.title}"
            for reminder in reminders[:3]
        ]

        summary_parts = [f"Morning summary for {summary_date}."]
        summary_parts.append(f"Pending approvals: {len(approvals)}. Open reminders: {len(reminders)}.")
        if message_lines:
            summary_parts.append("Top inbox items:\n" + "\n".join(message_lines))
        if event_lines:
            summary_parts.append("Upcoming calendar:\n" + "\n".join(event_lines))
        if reminder_lines:
            summary_parts.append("Priority reminders:\n" + "\n".join(reminder_lines))

        summary_text = "\n\n".join(summary_parts)
        self.store.set_sync_state("morning_summary_for_date", summary_date)
        self.store.set_sync_state("morning_summary_text", summary_text)
        self.store.set_sync_state("morning_summary_generated_at", datetime.now().astimezone().isoformat())
        return {
            "generated": True,
            "summary_date": summary_date,
            "summary_text": summary_text,
        }

    def dashboard(self) -> dict[str, Any]:
        messages = self.store.list_messages()
        return {
            "messages": messages,
            "events": self.store.list_events(),
            "approvals": self.store.list_approvals(),
            "reminders": self.store.list_reminders(),
            "auto_drafted_count": sum(1 for message in messages if message.raw_payload.get("autoDrafted")),
            "graph_configured": self.config.has_graph_config,
            "local_outlook_available": self._local_outlook_status()["available"],
            "ai_configured": self.config.has_ai_config,
            "last_sync_source": self.store.get_sync_state("last_sync_source"),
            "morning_summary_text": self.store.get_sync_state("morning_summary_text"),
            "morning_summary_generated_at": self.store.get_sync_state("morning_summary_generated_at"),
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
            for raw_message in raw_messages:
                raw_message.setdefault("sourceProvider", "graph")
            for raw_event in raw_events:
                raw_event.setdefault("sourceProvider", "graph")
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

    def _queue_message_actions(self, message) -> tuple[int, int]:
        created = 0
        auto_drafted = 0
        auto_draft_state_key = f"{self.AUTO_DRAFT_STATE_KEY_PREFIX}{message.message_id}"
        if self.store.get_sync_state(auto_draft_state_key):
            message.raw_payload["autoDrafted"] = True
            message.raw_payload["oesActionMode"] = "auto_drafted"

        if message.draft_reply and not message.raw_payload.get("autoDrafted") and self._should_auto_draft(message):
            if self._auto_draft_message(message):
                self.store.set_sync_state(auto_draft_state_key, datetime.now().astimezone().isoformat())
                message.raw_payload["autoDrafted"] = True
                message.raw_payload["oesActionMode"] = "auto_drafted"
                auto_drafted += 1

        if message.draft_reply and not message.raw_payload.get("autoDrafted") and not self.store.has_pending_approval(ApprovalActionType.DRAFT_REPLY, message.message_id):
            message.raw_payload["oesActionMode"] = "approval_required"
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
            message.raw_payload["oesActionMode"] = "approval_required"
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
        return created, auto_drafted

    def _should_auto_draft(self, message) -> bool:
        if not message.draft_reply:
            return False
        if message.raw_payload.get("sourceProvider") not in {"graph", "outlook_desktop"}:
            return False
        if message.action_items:
            return False

        text = f"{message.subject}\n{message.body_preview}".lower()
        if any(term in text for term in self.AUTO_DRAFT_RESTRICTED_TERMS):
            return False

        if message.priority in {Priority.NORMAL, Priority.LOW} and message.triage_label == "review":
            return True

        if any(term in text for term in self.AUTO_DRAFT_ACKNOWLEDGEMENT_TERMS):
            return True

        subject = message.subject.lower().strip()
        return subject.startswith(("fw:", "fwd:")) and any(term in text for term in ("announcement", "open", "confirmed", "fyi"))

    def _auto_draft_message(self, message) -> bool:
        source_provider = message.raw_payload.get("sourceProvider")
        store_id = message.raw_payload.get("storeId")

        if source_provider == "graph":
            if not self.config.has_graph_config:
                return False
            client = self._graph_client()
            try:
                client.create_reply_draft(message.message_id, comment=message.draft_reply)
            finally:
                client.close()
        elif source_provider == "outlook_desktop":
            provider = self._local_outlook_provider()
            provider.create_reply_draft(
                message.message_id,
                comment=message.draft_reply,
                store_id=None if store_id is None else str(store_id),
            )
        else:
            return False

        approval = ApprovalItem(
            action_type=ApprovalActionType.DRAFT_REPLY,
            target_type="message",
            target_id=message.message_id,
            title=f"Auto-drafted reply: {message.subject}",
            details={
                "subject": message.subject,
                "draft_reply": message.draft_reply,
                "priority": message.priority.value,
                "store_id": store_id,
                "source_provider": source_provider,
                "auto_drafted": True,
            },
            status=ApprovalStatus.EXECUTED,
        )
        self.store.add_approval(approval)
        return True

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