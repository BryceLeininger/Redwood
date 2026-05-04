"""Local Outlook desktop integration for OES using Windows COM automation."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Iterator

try:
    import pythoncom
    from win32com.client import Dispatch
except ImportError:  # pragma: no cover - optional dependency at runtime
    pythoncom = None
    Dispatch = None


OL_FOLDER_INBOX = 6
OL_FOLDER_CALENDAR = 9
OL_MAIL_ITEM = 43
OL_APPOINTMENT_ITEM = 26
OL_TASK_ITEM = 3


@dataclass(frozen=True)
class LocalOutlookStatus:
    available: bool
    reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"available": self.available, "reason": self.reason}


class LocalOutlookProvider:
    @classmethod
    def detect(cls) -> LocalOutlookStatus:
        if Dispatch is None or pythoncom is None:
            return LocalOutlookStatus(available=False, reason="pywin32 is not installed.")
        try:
            with cls()._session() as _session:
                return LocalOutlookStatus(available=True, reason=None)
        except Exception as error:  # noqa: BLE001
            return LocalOutlookStatus(available=False, reason=str(error))

    @contextmanager
    def _session(self) -> Iterator[Any]:
        if Dispatch is None or pythoncom is None:
            raise RuntimeError("pywin32 is not available.")
        pythoncom.CoInitialize()
        try:
            app = Dispatch("Outlook.Application")
            namespace = app.GetNamespace("MAPI")
            yield namespace
        finally:
            pythoncom.CoUninitialize()

    def list_inbox_messages(self, limit: int = 25) -> list[dict[str, Any]]:
        with self._session() as namespace:
            inbox = namespace.GetDefaultFolder(OL_FOLDER_INBOX)
            items = inbox.Items
            items.Sort("[ReceivedTime]", True)

            messages: list[dict[str, Any]] = []
            total_items = int(items.Count)
            index = 1
            while len(messages) < limit and index <= total_items:
                item = items.Item(index)
                index += 1
                if getattr(item, "Class", None) != OL_MAIL_ITEM:
                    continue
                categories_raw = str(getattr(item, "Categories", "") or "")
                folder = getattr(item, "Parent", None)
                store_id = getattr(folder, "StoreID", None)
                messages.append(
                    {
                        "id": str(getattr(item, "EntryID", "")),
                        "subject": str(getattr(item, "Subject", "") or "(no subject)"),
                        "receivedDateTime": self._to_iso(getattr(item, "ReceivedTime", None)),
                        "bodyPreview": str(getattr(item, "Body", "") or "")[:1200],
                        "isRead": bool(getattr(item, "UnRead", False) is False),
                        "categories": [part.strip() for part in categories_raw.split(",") if part.strip()],
                        "from": {
                            "emailAddress": {
                                "name": str(getattr(item, "SenderName", "") or "Unknown sender"),
                                "address": str(getattr(item, "SenderEmailAddress", "") or ""),
                            }
                        },
                        "storeId": None if store_id is None else str(store_id),
                        "sourceProvider": "outlook_desktop",
                    }
                )
            return messages

    def list_calendar_events(self, days: int = 14, limit: int = 25) -> list[dict[str, Any]]:
        end_window = datetime.now().astimezone() + timedelta(days=days)
        with self._session() as namespace:
            calendar = namespace.GetDefaultFolder(OL_FOLDER_CALENDAR)
            items = calendar.Items
            items.Sort("[Start]")
            items.IncludeRecurrences = True

            events: list[dict[str, Any]] = []
            total_items = min(int(items.Count), 500)
            index = 1
            while len(events) < limit and index <= total_items:
                item = items.Item(index)
                index += 1
                if getattr(item, "Class", None) != OL_APPOINTMENT_ITEM:
                    continue

                start = self._to_datetime(getattr(item, "Start", None))
                end = self._to_datetime(getattr(item, "End", None))
                if start is None or end is None:
                    continue
                if end < datetime.now().astimezone() or start > end_window:
                    continue

                organizer_email = str(getattr(item, "Organizer", "") or "")
                events.append(
                    {
                        "id": str(getattr(item, "EntryID", "")),
                        "subject": str(getattr(item, "Subject", "") or "Untitled event"),
                        "start": {"dateTime": start.isoformat()},
                        "end": {"dateTime": end.isoformat()},
                        "organizer": {
                            "emailAddress": {
                                "name": organizer_email or "Unknown organizer",
                                "address": organizer_email,
                            }
                        },
                        "location": {"displayName": str(getattr(item, "Location", "") or "")},
                        "sourceProvider": "outlook_desktop",
                    }
                )
            return events

    def create_reply_draft(self, message_id: str, comment: str = "", store_id: str | None = None) -> None:
        with self._session() as namespace:
            item = namespace.GetItemFromID(message_id, store_id) if store_id else namespace.GetItemFromID(message_id)
            reply = item.Reply()
            if comment:
                original_body = str(getattr(reply, "Body", "") or "")
                reply.Body = f"{comment}\n\n{original_body}"
            reply.Save()

    def create_task(self, title: str, due_at: str | None = None, body: str = "") -> None:
        with self._session() as namespace:
            app = namespace.Application
            task = app.CreateItem(OL_TASK_ITEM)
            task.Subject = title
            if body:
                task.Body = body
            if due_at:
                due_dt = self._parse_datetime(due_at)
                if due_dt is not None:
                    task.DueDate = due_dt
            task.Save()

    def delete_message(self, message_id: str, store_id: str | None = None) -> None:
        with self._session() as namespace:
            item = namespace.GetItemFromID(message_id, store_id) if store_id else namespace.GetItemFromID(message_id)
            item.Delete()

    def send_reply(self, message_id: str, store_id: str | None = None, comment: str = "") -> None:
        with self._session() as namespace:
            item = namespace.GetItemFromID(message_id, store_id) if store_id else namespace.GetItemFromID(message_id)
            reply = item.Reply()
            if comment:
                original_body = str(getattr(reply, "Body", "") or "")
                reply.Body = f"{comment}\n\n{original_body}"
            reply.Send()

    def _to_iso(self, value: Any) -> str:
        parsed = self._to_datetime(value)
        if parsed is None:
            return datetime.now(timezone.utc).isoformat()
        return parsed.isoformat()

    def _to_datetime(self, value: Any) -> datetime | None:
        if value is None:
            return None
        if isinstance(value, datetime):
            if value.tzinfo is None:
                return value.replace(tzinfo=datetime.now().astimezone().tzinfo)
            return value
        try:
            return datetime.fromisoformat(str(value))
        except ValueError:
            return None

    def _parse_datetime(self, value: str) -> datetime | None:
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            return None
        if parsed.tzinfo is not None:
            return parsed.astimezone().replace(tzinfo=None)
        return parsed