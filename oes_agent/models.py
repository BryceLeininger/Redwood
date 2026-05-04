"""Domain models for the Outlook Email Secretary agent."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any


class Priority(StrEnum):
    CRITICAL = "critical"
    HIGH = "high"
    NORMAL = "normal"
    LOW = "low"


class ApprovalStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXECUTED = "executed"
    FAILED = "failed"


class ReminderStatus(StrEnum):
    OPEN = "open"
    COMPLETED = "completed"
    DISMISSED = "dismissed"


class ApprovalActionType(StrEnum):
    DRAFT_REPLY = "draft_reply"
    SEND_REPLY = "send_reply"
    DELETE_MESSAGE = "delete_message"
    MOVE_MESSAGE = "move_message"
    CREATE_TASK = "create_task"
    CREATE_EVENT = "create_event"
    RESPOND_TO_EVENT = "respond_to_event"


@dataclass(slots=True)
class MessageSummary:
    message_id: str
    subject: str
    sender_name: str
    sender_email: str
    received_at: str
    body_preview: str
    is_read: bool
    categories: list[str] = field(default_factory=list)
    triage_label: str = "needs_review"
    priority: Priority = Priority.NORMAL
    summary: str = ""
    draft_reply: str = ""
    action_items: list[str] = field(default_factory=list)
    suggested_actions: list[str] = field(default_factory=list)
    raw_payload: dict[str, Any] = field(default_factory=dict)

    def to_record(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["priority"] = self.priority.value
        return payload


@dataclass(slots=True)
class CalendarEventSummary:
    event_id: str
    subject: str
    start_at: str
    end_at: str
    organizer_name: str
    organizer_email: str
    location: str = ""
    summary: str = ""
    action_items: list[str] = field(default_factory=list)
    raw_payload: dict[str, Any] = field(default_factory=dict)

    def to_record(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ApprovalItem:
    action_type: ApprovalActionType
    target_type: str
    target_id: str
    title: str
    details: dict[str, Any] = field(default_factory=dict)
    status: ApprovalStatus = ApprovalStatus.PENDING
    approval_id: int | None = None
    created_at: str | None = None
    updated_at: str | None = None

    def to_record(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["action_type"] = self.action_type.value
        payload["status"] = self.status.value
        return payload


@dataclass(slots=True)
class ReminderItem:
    title: str
    due_at: str | None
    notes: str = ""
    source_type: str = "manual"
    source_id: str | None = None
    status: ReminderStatus = ReminderStatus.OPEN
    reminder_id: int | None = None
    created_at: str | None = None
    updated_at: str | None = None

    def to_record(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["status"] = self.status.value
        return payload