"""Interactive orchestration layer for the Outlook agent panel."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from .constants import REGISTRY_FILE
from .integrations.outlook_local import OutlookLocalClient
from .outlook_workflow import suggest_reply_body, triage_messages
from .specialist_agent import SpecialistAgent


@dataclass(frozen=True)
class AgentReply:
    text: str
    data: Dict[str, Any] | None = None

    def to_dict(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {"reply": self.text}
        if self.data is not None:
            payload["data"] = self.data
        return payload


def _parse_int(value: str, fallback: int) -> int:
    try:
        return int(value)
    except ValueError:
        return fallback


def _top_confidence(item: Dict[str, Any]) -> Optional[float]:
    classes = item.get("top_classes", [])
    if not classes:
        return None
    return float(classes[0].get("confidence", 0))


def _find_outlook_agent_path(output_root: Path, explicit_path: Optional[Path]) -> Optional[Path]:
    if explicit_path:
        return explicit_path

    registry_path = output_root / REGISTRY_FILE
    if not registry_path.exists():
        return None

    try:
        entries = json.loads(registry_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None

    outlook_entries = [entry for entry in entries if entry.get("name") == "OutlookEmailManager"]
    if not outlook_entries:
        return None

    latest = sorted(
        outlook_entries,
        key=lambda item: item.get("created_at_utc", ""),
        reverse=True,
    )[0]
    path = latest.get("agent_dir")
    if not path:
        return None
    return Path(path)


class OutlookAgentOrchestrator:
    """Single-chat orchestration interface for the Outlook agent."""

    def __init__(
        self,
        *,
        output_root: Path | str = "generated_agents",
        outlook_agent_dir: Path | str | None = None,
    ) -> None:
        self.output_root = Path(output_root)
        self.client = OutlookLocalClient()

        explicit = Path(outlook_agent_dir) if outlook_agent_dir else None
        resolved_agent_path = _find_outlook_agent_path(self.output_root, explicit)
        self.specialist: Optional[SpecialistAgent] = None
        self.specialist_path: Optional[Path] = None
        if resolved_agent_path and resolved_agent_path.exists():
            self.specialist = SpecialistAgent.load(resolved_agent_path)
            self.specialist_path = resolved_agent_path

        self.cached_messages: List[Dict[str, Any]] = []
        self.cached_source = "none"

    def start(self) -> AgentReply:
        if self.specialist_path:
            specialist_hint = f"Loaded agent: {self.specialist_path.name}"
        else:
            specialist_hint = "No OutlookEmailManager model loaded; triage and auto-draft are disabled."
        text = (
            "Outlook Agent ready.\n"
            f"{specialist_hint}\n"
            "Type 'help' for commands."
        )
        return AgentReply(text=text)

    def handle_message(self, raw_message: str) -> AgentReply:
        message = raw_message.strip()
        if not message:
            return AgentReply("Send a command. Type 'help' to see available commands.")

        lower = message.lower()
        try:
            if lower in {"help", "?"}:
                return self._help_reply()
            if lower in {"status", "agent"}:
                return self._status_reply()

            if lower.startswith("inbox"):
                return self._inbox_command(message, unread_only=False)
            if lower.startswith("unread"):
                return self._inbox_command(message, unread_only=True)
            if lower.startswith("drafts"):
                return self._drafts_command(message)
            if lower.startswith("folders"):
                return self._folders_command(message)
            if lower.startswith("read "):
                return self._read_command(message)
            if lower.startswith("triage"):
                return self._triage_command(message)
            if lower.startswith("draft "):
                return self._draft_command(message)
            if lower.startswith("send draft "):
                return self._send_draft_command(message)
            if lower.startswith("mark "):
                return self._mark_command(message)
            if lower.startswith("move "):
                return self._move_command(message)
            if lower.startswith("event "):
                return self._event_command(message)
        except Exception as error:  # noqa: BLE001
            return AgentReply(f"Error: {error}")

        return AgentReply("Command not recognized. Type 'help' for command examples.")

    def _help_reply(self) -> AgentReply:
        text = (
            "Commands:\n"
            "- inbox [count]               (example: inbox 10)\n"
            "- unread [count]              (example: unread 10)\n"
            "- triage [count] [unread]     (example: triage 10 unread)\n"
            "- read <index>                (example: read 2)\n"
            "- draft <index> [send]        (example: draft 1)\n"
            "- send draft <index>          (example: send draft 1)\n"
            "- mark read <index>           (example: mark read 3)\n"
            "- mark unread <index>         (example: mark unread 3)\n"
            "- move <index> to <folder>    (example: move 2 to Inbox/Archive)\n"
            "- folders [query]             (example: folders inbox)\n"
            "- drafts [count]              (example: drafts 20)\n"
            '- event "<subject>" <start> <end> [attendees=a@x.com,b@y.com]\n'
            '  example: event "Deal Call" 2026-02-10T14:00:00 2026-02-10T15:00:00 attendees=analyst@company.com\n'
            "- status"
        )
        return AgentReply(text=text)

    def _status_reply(self) -> AgentReply:
        if self.specialist_path:
            model = self.specialist_path.name
        else:
            model = "not loaded"
        text = (
            f"Model: {model}\n"
            f"Cached source: {self.cached_source}\n"
            f"Cached items: {len(self.cached_messages)}"
        )
        return AgentReply(text=text)

    def _format_message_rows(self, messages: List[Dict[str, Any]], with_prediction: bool = False) -> List[Dict[str, Any]]:
        rows: List[Dict[str, Any]] = []
        for index, item in enumerate(messages, start=1):
            row = {
                "index": index,
                "subject": item.get("subject"),
                "from": item.get("from", {}).get("emailAddress", {}).get("address", ""),
                "received": item.get("receivedDateTime"),
                "isRead": item.get("isRead"),
                "preview": item.get("bodyPreview"),
            }
            if with_prediction:
                row["prediction"] = item.get("prediction")
                confidence = _top_confidence(item)
                if confidence is not None:
                    row["confidence"] = round(confidence, 3)
            rows.append(row)
        return rows

    def _cache_messages(self, messages: List[Dict[str, Any]], source: str) -> None:
        self.cached_messages = messages
        self.cached_source = source

    def _get_cached(self, index: int) -> Dict[str, Any]:
        if not self.cached_messages:
            raise ValueError("No cached messages. Run inbox, unread, drafts, or triage first.")
        if index < 1 or index > len(self.cached_messages):
            raise ValueError(f"Index out of range: {index}. Cached items: {len(self.cached_messages)}")
        return self.cached_messages[index - 1]

    def _inbox_command(self, message: str, unread_only: bool) -> AgentReply:
        parts = message.split()
        top = 10
        if len(parts) >= 2:
            top = _parse_int(parts[1], 10)
        messages = self.client.get_inbox_messages(top=top, unread_only=unread_only)
        self._cache_messages(messages, "unread" if unread_only else "inbox")

        rows = self._format_message_rows(messages)
        return AgentReply(
            text=f"Loaded {len(messages)} messages from {self.cached_source}.",
            data={"messages": rows},
        )

    def _drafts_command(self, message: str) -> AgentReply:
        parts = message.split()
        top = 20
        if len(parts) >= 2:
            top = _parse_int(parts[1], 20)
        messages = self.client.list_draft_messages(top=top)
        self._cache_messages(messages, "drafts")

        rows = self._format_message_rows(messages)
        return AgentReply(
            text=f"Loaded {len(messages)} draft messages.",
            data={"messages": rows},
        )

    def _folders_command(self, message: str) -> AgentReply:
        query = ""
        parts = message.split(maxsplit=1)
        if len(parts) == 2:
            query = parts[1].strip()
        folders = self.client.list_folders(query=query or None, top=200)
        rows = [{"index": index, "path": path} for index, path in enumerate(folders, start=1)]
        return AgentReply(
            text=f"Found {len(rows)} folders.",
            data={"folders": rows},
        )

    def _read_command(self, message: str) -> AgentReply:
        match = re.match(r"^read\s+(\d+)$", message, flags=re.IGNORECASE)
        if not match:
            return AgentReply("Invalid read command. Example: read 2")
        index = int(match.group(1))
        cached = self._get_cached(index)
        detail = self.client.get_message(str(cached["id"]), include_body=True)
        return AgentReply(
            text=f"Message {index}: {detail.get('subject', '')}",
            data={"message": detail},
        )

    def _ensure_specialist(self) -> SpecialistAgent:
        if self.specialist is None:
            raise ValueError("OutlookEmailManager model is not loaded.")
        return self.specialist

    def _triage_command(self, message: str) -> AgentReply:
        specialist = self._ensure_specialist()
        match = re.match(r"^triage(?:\s+(\d+))?(?:\s+(unread))?$", message, flags=re.IGNORECASE)
        if not match:
            return AgentReply("Invalid triage command. Example: triage 10 unread")

        top = int(match.group(1) or 10)
        unread_only = (match.group(2) or "").lower() == "unread"
        messages = self.client.get_inbox_messages(top=top, unread_only=unread_only)
        triaged = triage_messages(specialist, messages)

        enriched: List[Dict[str, Any]] = []
        for message_item, triage_item in zip(messages, triaged):
            enriched.append({**message_item, **triage_item})

        self._cache_messages(messages, "triage")
        rows = self._format_message_rows(enriched, with_prediction=True)
        return AgentReply(
            text=f"Triaged {len(rows)} messages.",
            data={"messages": rows},
        )

    def _draft_command(self, message: str) -> AgentReply:
        specialist = self._ensure_specialist()
        match = re.match(r"^draft\s+(\d+)(?:\s+(send))?$", message, flags=re.IGNORECASE)
        if not match:
            return AgentReply("Invalid draft command. Example: draft 1  OR  draft 1 send")

        index = int(match.group(1))
        send_now = (match.group(2) or "").lower() == "send"
        cached = self._get_cached(index)

        label, body = suggest_reply_body(specialist, cached)
        result = self.client.create_reply_draft(str(cached["id"]), body, send_now=send_now)

        state = "sent" if send_now else "saved as draft"
        return AgentReply(
            text=f"Reply for message {index} was {state}.",
            data={
                "classification": label,
                "result": result,
                "body_preview": body,
            },
        )

    def _send_draft_command(self, message: str) -> AgentReply:
        match = re.match(r"^send\s+draft\s+(\d+)$", message, flags=re.IGNORECASE)
        if not match:
            return AgentReply("Invalid command. Example: send draft 1")
        index = int(match.group(1))
        cached = self._get_cached(index)
        result = self.client.send_draft(str(cached["id"]))
        return AgentReply(
            text=f"Draft {index} sent.",
            data={"result": result},
        )

    def _mark_command(self, message: str) -> AgentReply:
        match = re.match(r"^mark\s+(read|unread)\s+(\d+)$", message, flags=re.IGNORECASE)
        if not match:
            return AgentReply("Invalid mark command. Examples: mark read 2, mark unread 2")
        state = match.group(1).lower()
        index = int(match.group(2))
        cached = self._get_cached(index)
        read = state == "read"
        result = self.client.set_message_read_state(str(cached["id"]), read=read)
        return AgentReply(
            text=f"Message {index} marked as {'read' if read else 'unread'}.",
            data={"result": result},
        )

    def _move_command(self, message: str) -> AgentReply:
        match = re.match(r"^move\s+(\d+)\s+to\s+(.+)$", message, flags=re.IGNORECASE)
        if not match:
            return AgentReply("Invalid move command. Example: move 2 to Inbox/Archive")
        index = int(match.group(1))
        folder = match.group(2).strip()
        cached = self._get_cached(index)
        result = self.client.move_message(str(cached["id"]), folder)
        return AgentReply(
            text=f"Moved message {index} to {result.get('destination_folder')}.",
            data={"result": result},
        )

    def _event_command(self, message: str) -> AgentReply:
        pattern = r'^event\s+"([^"]+)"\s+(\S+)\s+(\S+)(?:\s+attendees=(.+))?$'
        match = re.match(pattern, message, flags=re.IGNORECASE)
        if not match:
            return AgentReply(
                'Invalid event command. Example: event "Deal Call" 2026-02-10T14:00:00 2026-02-10T15:00:00 attendees=a@x.com,b@y.com'
            )

        subject, start, end, attendees_raw = match.groups()
        attendees = []
        if attendees_raw:
            attendees = [item.strip() for item in attendees_raw.split(",") if item.strip()]

        result = self.client.create_calendar_event(
            subject=subject,
            start_datetime=start,
            end_datetime=end,
            attendees=attendees,
            body_text="Created by Outlook Agent Panel.",
        )
        return AgentReply(
            text=f"Event created: {subject}",
            data={"result": result},
        )
