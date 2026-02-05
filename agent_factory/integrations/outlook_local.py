"""Local Outlook Desktop (COM) integration for mailbox and calendar automation."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

try:
    import win32com.client  # type: ignore[import-untyped]
except ImportError:  # pragma: no cover - runtime environment dependent
    win32com = None
else:
    win32com = win32com.client

OL_FOLDER_INBOX = 6
OL_APPOINTMENT_ITEM = 1
OL_MAIL_ITEM_CLASS = 43


def _normalize_datetime(value: str) -> datetime:
    raw = value.strip()
    if not raw:
        raise ValueError("Datetime value cannot be empty.")
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    parsed = datetime.fromisoformat(raw)
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone().replace(tzinfo=None)
    return parsed


def _sender_email(item: Any) -> str:
    email = str(getattr(item, "SenderEmailAddress", "") or "").strip()
    if email and not email.upper().startswith("/O="):
        return email
    try:
        sender = getattr(item, "Sender", None)
        if sender is None:
            return email
        exchange_user = sender.GetExchangeUser()
        if exchange_user is None:
            return email
        return str(getattr(exchange_user, "PrimarySmtpAddress", "") or email).strip()
    except Exception:
        return email


def _body_preview(item: Any, max_chars: int = 280) -> str:
    preview = str(getattr(item, "Body", "") or "")
    preview = " ".join(preview.split())
    return preview[:max_chars]


def _received_iso(item: Any) -> Optional[str]:
    received = getattr(item, "ReceivedTime", None)
    if received is None:
        return None
    try:
        return received.isoformat()
    except Exception:
        return str(received)


def _mail_to_graph_like_dict(item: Any) -> Dict[str, Any]:
    return {
        "id": str(getattr(item, "EntryID", "")),
        "subject": str(getattr(item, "Subject", "") or ""),
        "from": {
            "emailAddress": {
                "name": str(getattr(item, "SenderName", "") or ""),
                "address": _sender_email(item),
            }
        },
        "receivedDateTime": _received_iso(item),
        "isRead": not bool(getattr(item, "UnRead", False)),
        "bodyPreview": _body_preview(item),
        "webLink": None,
    }


class OutlookLocalClient:
    """Use the local Outlook desktop profile via COM (no Graph credentials needed)."""

    def __init__(self) -> None:
        if win32com is None:
            raise RuntimeError("pywin32 is not installed. Install dependencies from agent_factory/requirements.txt.")
        try:
            self._application = win32com.Dispatch("Outlook.Application")
            self._namespace = self._application.GetNamespace("MAPI")
        except Exception as error:
            raise RuntimeError(
                "Unable to start Outlook COM automation. Ensure Outlook Desktop is installed and signed in."
            ) from error

    def get_inbox_messages(self, *, top: int = 10, unread_only: bool = False) -> List[Dict[str, Any]]:
        top = max(1, min(top, 100))
        inbox = self._namespace.GetDefaultFolder(OL_FOLDER_INBOX)
        items = inbox.Items
        items.Sort("[ReceivedTime]", True)

        results: List[Dict[str, Any]] = []
        for item in items:
            try:
                if int(getattr(item, "Class", 0)) != OL_MAIL_ITEM_CLASS:
                    continue
                if unread_only and not bool(getattr(item, "UnRead", False)):
                    continue
                results.append(_mail_to_graph_like_dict(item))
                if len(results) >= top:
                    break
            except Exception:
                continue
        return results

    def get_message(self, message_id: str) -> Dict[str, Any]:
        message_id = message_id.strip()
        if not message_id:
            raise ValueError("message_id cannot be empty.")
        try:
            item = self._namespace.GetItemFromID(message_id)
        except Exception as error:
            raise RuntimeError(f"Unable to find Outlook item with id: {message_id}") from error
        if int(getattr(item, "Class", 0)) != OL_MAIL_ITEM_CLASS:
            raise RuntimeError("Item was found but is not an Outlook mail item.")
        return _mail_to_graph_like_dict(item)

    def create_reply_draft(self, message_id: str, body_text: str) -> Dict[str, Any]:
        message_id = message_id.strip()
        body_text = body_text.strip()
        if not message_id:
            raise ValueError("message_id cannot be empty.")
        if not body_text:
            raise ValueError("body_text cannot be empty.")

        try:
            item = self._namespace.GetItemFromID(message_id)
            reply = item.Reply()
            original_body = str(getattr(reply, "Body", "") or "")
            reply.Body = f"{body_text}\n\n{original_body}"
            reply.Save()
        except Exception as error:
            raise RuntimeError("Failed to create Outlook draft reply.") from error

        return {
            "draft_id": str(getattr(reply, "EntryID", "")),
            "subject": str(getattr(reply, "Subject", "") or ""),
            "web_link": None,
        }

    def create_calendar_event(
        self,
        *,
        subject: str,
        start_datetime: str,
        end_datetime: str,
        attendees: Optional[List[str]] = None,
        body_text: str = "",
    ) -> Dict[str, Any]:
        subject = subject.strip()
        if not subject:
            raise ValueError("subject cannot be empty.")

        start = _normalize_datetime(start_datetime)
        end = _normalize_datetime(end_datetime)
        if end <= start:
            raise ValueError("Event end time must be later than start time.")

        attendees = attendees or []
        try:
            event = self._application.CreateItem(OL_APPOINTMENT_ITEM)
            event.Subject = subject
            event.Start = start
            event.End = end
            event.Body = body_text
            if attendees:
                event.RequiredAttendees = ";".join(attendees)
            event.Save()
        except Exception as error:
            raise RuntimeError("Failed to create Outlook calendar event.") from error

        return {
            "event_id": str(getattr(event, "EntryID", "")),
            "subject": str(getattr(event, "Subject", "") or ""),
            "start": str(getattr(event, "Start", "")),
            "end": str(getattr(event, "End", "")),
            "web_link": None,
        }
