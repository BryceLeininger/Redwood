"""SQLite-backed local storage for the Outlook Email Secretary agent."""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from .models import (
    ApprovalActionType,
    ApprovalItem,
    ApprovalStatus,
    CalendarEventSummary,
    MessageSummary,
    Priority,
    ReminderItem,
    ReminderStatus,
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class LocalStore:
    def __init__(self, db_path: Path | str) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def ensure_ready(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS messages (
                    message_id TEXT PRIMARY KEY,
                    subject TEXT NOT NULL,
                    sender_name TEXT NOT NULL,
                    sender_email TEXT NOT NULL,
                    received_at TEXT NOT NULL,
                    body_preview TEXT NOT NULL,
                    is_read INTEGER NOT NULL,
                    categories_json TEXT NOT NULL,
                    triage_label TEXT NOT NULL,
                    priority TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    draft_reply TEXT NOT NULL,
                    action_items_json TEXT NOT NULL,
                    suggested_actions_json TEXT NOT NULL,
                    raw_payload_json TEXT NOT NULL,
                    synced_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS calendar_events (
                    event_id TEXT PRIMARY KEY,
                    subject TEXT NOT NULL,
                    start_at TEXT NOT NULL,
                    end_at TEXT NOT NULL,
                    organizer_name TEXT NOT NULL,
                    organizer_email TEXT NOT NULL,
                    location TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    action_items_json TEXT NOT NULL,
                    raw_payload_json TEXT NOT NULL,
                    synced_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS approval_items (
                    approval_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    action_type TEXT NOT NULL,
                    target_type TEXT NOT NULL,
                    target_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    details_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS reminders (
                    reminder_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    due_at TEXT,
                    notes TEXT NOT NULL,
                    source_type TEXT NOT NULL,
                    source_id TEXT,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS sync_state (
                    state_key TEXT PRIMARY KEY,
                    state_value TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                """
            )

    def upsert_message(self, message: MessageSummary) -> None:
        payload = message.to_record()
        synced_at = _utc_now()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO messages (
                    message_id,
                    subject,
                    sender_name,
                    sender_email,
                    received_at,
                    body_preview,
                    is_read,
                    categories_json,
                    triage_label,
                    priority,
                    summary,
                    draft_reply,
                    action_items_json,
                    suggested_actions_json,
                    raw_payload_json,
                    synced_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(message_id) DO UPDATE SET
                    subject=excluded.subject,
                    sender_name=excluded.sender_name,
                    sender_email=excluded.sender_email,
                    received_at=excluded.received_at,
                    body_preview=excluded.body_preview,
                    is_read=excluded.is_read,
                    categories_json=excluded.categories_json,
                    triage_label=excluded.triage_label,
                    priority=excluded.priority,
                    summary=excluded.summary,
                    draft_reply=excluded.draft_reply,
                    action_items_json=excluded.action_items_json,
                    suggested_actions_json=excluded.suggested_actions_json,
                    raw_payload_json=excluded.raw_payload_json,
                    synced_at=excluded.synced_at
                """,
                (
                    payload["message_id"],
                    payload["subject"],
                    payload["sender_name"],
                    payload["sender_email"],
                    payload["received_at"],
                    payload["body_preview"],
                    1 if payload["is_read"] else 0,
                    json.dumps(payload["categories"]),
                    payload["triage_label"],
                    payload["priority"],
                    payload["summary"],
                    payload["draft_reply"],
                    json.dumps(payload["action_items"]),
                    json.dumps(payload["suggested_actions"]),
                    json.dumps(payload["raw_payload"]),
                    synced_at,
                ),
            )

    def list_messages(self, limit: int = 50) -> list[MessageSummary]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT *
                FROM messages
                ORDER BY received_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [self._message_from_row(row) for row in rows]

    def upsert_event(self, event: CalendarEventSummary) -> None:
        payload = event.to_record()
        synced_at = _utc_now()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO calendar_events (
                    event_id,
                    subject,
                    start_at,
                    end_at,
                    organizer_name,
                    organizer_email,
                    location,
                    summary,
                    action_items_json,
                    raw_payload_json,
                    synced_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(event_id) DO UPDATE SET
                    subject=excluded.subject,
                    start_at=excluded.start_at,
                    end_at=excluded.end_at,
                    organizer_name=excluded.organizer_name,
                    organizer_email=excluded.organizer_email,
                    location=excluded.location,
                    summary=excluded.summary,
                    action_items_json=excluded.action_items_json,
                    raw_payload_json=excluded.raw_payload_json,
                    synced_at=excluded.synced_at
                """,
                (
                    payload["event_id"],
                    payload["subject"],
                    payload["start_at"],
                    payload["end_at"],
                    payload["organizer_name"],
                    payload["organizer_email"],
                    payload["location"],
                    payload["summary"],
                    json.dumps(payload["action_items"]),
                    json.dumps(payload["raw_payload"]),
                    synced_at,
                ),
            )

    def list_events(self, limit: int = 25) -> list[CalendarEventSummary]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT *
                FROM calendar_events
                ORDER BY start_at ASC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [self._event_from_row(row) for row in rows]

    def add_approval(self, approval: ApprovalItem) -> ApprovalItem:
        payload = approval.to_record()
        timestamp = _utc_now()
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO approval_items (
                    action_type,
                    target_type,
                    target_id,
                    title,
                    details_json,
                    status,
                    created_at,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    payload["action_type"],
                    payload["target_type"],
                    payload["target_id"],
                    payload["title"],
                    json.dumps(payload["details"]),
                    payload["status"],
                    timestamp,
                    timestamp,
                ),
            )
        approval.approval_id = int(cursor.lastrowid)
        approval.created_at = timestamp
        approval.updated_at = timestamp
        return approval

    def update_approval_status(self, approval_id: int, status: ApprovalStatus) -> None:
        self.update_approval(approval_id, status=status)

    def update_approval(
        self,
        approval_id: int,
        status: ApprovalStatus | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        timestamp = _utc_now()
        with self._connect() as connection:
            row = connection.execute(
                "SELECT status, details_json FROM approval_items WHERE approval_id = ?",
                (approval_id,),
            ).fetchone()
            if row is None:
                return

            next_status = status.value if status is not None else str(row["status"])
            next_details = details if details is not None else dict(json.loads(str(row["details_json"])))
            connection.execute(
                """
                UPDATE approval_items
                SET status = ?, details_json = ?, updated_at = ?
                WHERE approval_id = ?
                """,
                (next_status, json.dumps(next_details), timestamp, approval_id),
            )

    def list_approvals(self, status: ApprovalStatus = ApprovalStatus.PENDING) -> list[ApprovalItem]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT *
                FROM approval_items
                WHERE status = ?
                ORDER BY created_at ASC
                """,
                (status.value,),
            ).fetchall()
        return [self._approval_from_row(row) for row in rows]

    def get_approval(self, approval_id: int) -> ApprovalItem | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM approval_items WHERE approval_id = ?",
                (approval_id,),
            ).fetchone()
        return None if row is None else self._approval_from_row(row)

    def has_pending_approval(self, action_type: ApprovalActionType, target_id: str) -> bool:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT 1
                FROM approval_items
                WHERE action_type = ? AND target_id = ? AND status = ?
                LIMIT 1
                """,
                (action_type.value, target_id, ApprovalStatus.PENDING.value),
            ).fetchone()
        return row is not None

    def add_reminder(self, reminder: ReminderItem) -> ReminderItem:
        payload = reminder.to_record()
        timestamp = _utc_now()
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO reminders (
                    title,
                    due_at,
                    notes,
                    source_type,
                    source_id,
                    status,
                    created_at,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    payload["title"],
                    payload["due_at"],
                    payload["notes"],
                    payload["source_type"],
                    payload["source_id"],
                    payload["status"],
                    timestamp,
                    timestamp,
                ),
            )
        reminder.reminder_id = int(cursor.lastrowid)
        reminder.created_at = timestamp
        reminder.updated_at = timestamp
        return reminder

    def update_reminder_status(self, reminder_id: int, status: ReminderStatus) -> None:
        timestamp = _utc_now()
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE reminders
                SET status = ?, updated_at = ?
                WHERE reminder_id = ?
                """,
                (status.value, timestamp, reminder_id),
            )

    def list_reminders(self, status: ReminderStatus = ReminderStatus.OPEN) -> list[ReminderItem]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT *
                FROM reminders
                WHERE status = ?
                ORDER BY COALESCE(due_at, created_at) ASC, created_at ASC
                """,
                (status.value,),
            ).fetchall()
        return [self._reminder_from_row(row) for row in rows]

    def has_open_reminder(self, source_type: str, source_id: str | None, title: str) -> bool:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT 1
                FROM reminders
                WHERE source_type = ?
                  AND COALESCE(source_id, '') = COALESCE(?, '')
                  AND title = ?
                  AND status = ?
                LIMIT 1
                """,
                (source_type, source_id, title, ReminderStatus.OPEN.value),
            ).fetchone()
        return row is not None

    def set_sync_state(self, key: str, value: str) -> None:
        timestamp = _utc_now()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO sync_state (state_key, state_value, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(state_key) DO UPDATE SET
                    state_value = excluded.state_value,
                    updated_at = excluded.updated_at
                """,
                (key, value, timestamp),
            )

    def get_sync_state(self, key: str) -> str | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT state_value FROM sync_state WHERE state_key = ?",
                (key,),
            ).fetchone()
        return None if row is None else str(row["state_value"])

    def _message_from_row(self, row: sqlite3.Row) -> MessageSummary:
        return MessageSummary(
            message_id=str(row["message_id"]),
            subject=str(row["subject"]),
            sender_name=str(row["sender_name"]),
            sender_email=str(row["sender_email"]),
            received_at=str(row["received_at"]),
            body_preview=str(row["body_preview"]),
            is_read=bool(row["is_read"]),
            categories=list(json.loads(str(row["categories_json"]))),
            triage_label=str(row["triage_label"]),
            priority=Priority(str(row["priority"])),
            summary=str(row["summary"]),
            draft_reply=str(row["draft_reply"]),
            action_items=list(json.loads(str(row["action_items_json"]))),
            suggested_actions=list(json.loads(str(row["suggested_actions_json"]))),
            raw_payload=dict(json.loads(str(row["raw_payload_json"]))),
        )

    def _event_from_row(self, row: sqlite3.Row) -> CalendarEventSummary:
        return CalendarEventSummary(
            event_id=str(row["event_id"]),
            subject=str(row["subject"]),
            start_at=str(row["start_at"]),
            end_at=str(row["end_at"]),
            organizer_name=str(row["organizer_name"]),
            organizer_email=str(row["organizer_email"]),
            location=str(row["location"]),
            summary=str(row["summary"]),
            action_items=list(json.loads(str(row["action_items_json"]))),
            raw_payload=dict(json.loads(str(row["raw_payload_json"]))),
        )

    def _approval_from_row(self, row: sqlite3.Row) -> ApprovalItem:
        return ApprovalItem(
            approval_id=int(row["approval_id"]),
            action_type=ApprovalActionType(str(row["action_type"])),
            target_type=str(row["target_type"]),
            target_id=str(row["target_id"]),
            title=str(row["title"]),
            details=dict(json.loads(str(row["details_json"]))),
            status=ApprovalStatus(str(row["status"])),
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
        )

    def _reminder_from_row(self, row: sqlite3.Row) -> ReminderItem:
        return ReminderItem(
            reminder_id=int(row["reminder_id"]),
            title=str(row["title"]),
            due_at=None if row["due_at"] is None else str(row["due_at"]),
            notes=str(row["notes"]),
            source_type=str(row["source_type"]),
            source_id=None if row["source_id"] is None else str(row["source_id"]),
            status=ReminderStatus(str(row["status"])),
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
        )