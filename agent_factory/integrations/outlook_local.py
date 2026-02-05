"""Local Outlook Desktop (COM) integration for mailbox and calendar automation."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

try:
    import win32com.client  # type: ignore[import-untyped]
except ImportError:  # pragma: no cover - runtime environment dependent
    win32com = None
else:
    win32com = win32com.client

OL_FOLDER_INBOX = 6
OL_FOLDER_DRAFTS = 16
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

    def _get_mail_item(self, message_id: str) -> Any:
        message_id = message_id.strip()
        if not message_id:
            raise ValueError("message_id cannot be empty.")
        try:
            item = self._namespace.GetItemFromID(message_id)
        except Exception as error:
            raise RuntimeError(f"Unable to find Outlook item with id: {message_id}") from error
        if int(getattr(item, "Class", 0)) != OL_MAIL_ITEM_CLASS:
            raise RuntimeError("Item was found but is not an Outlook mail item.")
        return item

    def _collect_folders(self) -> List[Tuple[str, Any]]:
        results: List[Tuple[str, Any]] = []

        def walk(folder: Any, path: str) -> None:
            results.append((path, folder))
            try:
                children = folder.Folders
                for idx in range(1, children.Count + 1):
                    child = children.Item(idx)
                    child_path = f"{path}/{child.Name}"
                    walk(child, child_path)
            except Exception:
                return

        stores = self._namespace.Folders
        for idx in range(1, stores.Count + 1):
            store = stores.Item(idx)
            walk(store, str(store.Name))
        return results

    def _resolve_folder(self, folder_path: str) -> Tuple[str, Any]:
        folder_path = folder_path.strip()
        if not folder_path:
            raise ValueError("folder_path cannot be empty.")

        all_folders = self._collect_folders()
        exact_matches = [(path, folder) for path, folder in all_folders if path.lower() == folder_path.lower()]
        if len(exact_matches) == 1:
            return exact_matches[0]

        suffix = f"/{folder_path.lower()}"
        partial_matches = [
            (path, folder)
            for path, folder in all_folders
            if path.lower().endswith(suffix) or path.lower() == folder_path.lower()
        ]
        if not partial_matches:
            options = [path for path, _ in all_folders][:20]
            raise RuntimeError(
                f"Folder was not found: '{folder_path}'. Use outlook-local-folders to find a valid path. "
                f"Sample folders: {options}"
            )
        if len(partial_matches) > 1:
            names = [path for path, _ in partial_matches]
            raise RuntimeError(f"Folder path is ambiguous: '{folder_path}'. Matches: {names}")
        return partial_matches[0]

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

    def get_message(self, message_id: str, *, include_body: bool = False) -> Dict[str, Any]:
        item = self._get_mail_item(message_id)
        payload = _mail_to_graph_like_dict(item)
        if include_body:
            payload["body"] = str(getattr(item, "Body", "") or "")
            payload["to"] = str(getattr(item, "To", "") or "")
            payload["cc"] = str(getattr(item, "CC", "") or "")
        return payload

    def create_reply_draft(self, message_id: str, body_text: str, *, send_now: bool = False) -> Dict[str, Any]:
        item = self._get_mail_item(message_id)
        body_text = body_text.strip()
        if not body_text:
            raise ValueError("body_text cannot be empty.")

        try:
            reply = item.Reply()
            original_body = str(getattr(reply, "Body", "") or "")
            reply.Body = f"{body_text}\n\n{original_body}"
            if send_now:
                reply.Send()
            else:
                reply.Save()
        except Exception as error:
            raise RuntimeError("Failed to create Outlook reply.") from error

        return {
            "draft_id": str(getattr(reply, "EntryID", "")),
            "subject": str(getattr(reply, "Subject", "") or ""),
            "sent": send_now,
            "web_link": None,
        }

    def set_message_read_state(self, message_id: str, *, read: bool) -> Dict[str, Any]:
        item = self._get_mail_item(message_id)
        try:
            item.UnRead = not read
            item.Save()
        except Exception as error:
            raise RuntimeError("Failed to update read/unread state.") from error
        return {
            "id": str(getattr(item, "EntryID", "")),
            "subject": str(getattr(item, "Subject", "") or ""),
            "isRead": read,
        }

    def move_message(self, message_id: str, destination_folder_path: str) -> Dict[str, Any]:
        item = self._get_mail_item(message_id)
        resolved_path, destination = self._resolve_folder(destination_folder_path)
        try:
            moved = item.Move(destination)
        except Exception as error:
            raise RuntimeError(f"Failed to move message to folder '{resolved_path}'.") from error
        return {
            "id": str(getattr(moved, "EntryID", "")),
            "subject": str(getattr(moved, "Subject", "") or ""),
            "destination_folder": resolved_path,
        }

    def list_folders(self, *, query: Optional[str] = None, top: int = 200) -> List[str]:
        top = max(1, top)
        folders = [path for path, _ in self._collect_folders()]
        folders.sort()
        if query:
            needle = query.strip().lower()
            folders = [path for path in folders if needle in path.lower()]
        return folders[:top]

    def list_draft_messages(self, *, top: int = 20) -> List[Dict[str, Any]]:
        top = max(1, min(top, 100))
        drafts = self._namespace.GetDefaultFolder(OL_FOLDER_DRAFTS)
        items = drafts.Items
        items.Sort("[LastModificationTime]", True)

        results: List[Dict[str, Any]] = []
        for item in items:
            try:
                if int(getattr(item, "Class", 0)) != OL_MAIL_ITEM_CLASS:
                    continue
                message = _mail_to_graph_like_dict(item)
                message["to"] = str(getattr(item, "To", "") or "")
                results.append(message)
                if len(results) >= top:
                    break
            except Exception:
                continue
        return results

    def send_draft(self, message_id: str) -> Dict[str, Any]:
        item = self._get_mail_item(message_id)
        try:
            item.Send()
        except Exception as error:
            raise RuntimeError("Failed to send Outlook draft.") from error
        return {
            "id": str(getattr(item, "EntryID", "")),
            "subject": str(getattr(item, "Subject", "") or ""),
            "status": "sent",
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
