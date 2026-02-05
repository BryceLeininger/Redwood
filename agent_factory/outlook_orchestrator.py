"""Interactive orchestration layer for the Outlook agent panel."""
from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from .constants import REGISTRY_FILE
from .integrations.outlook_local import OutlookLocalClient
from .learning_store import LearningStore
from .outlook_workflow import suggest_reply_body, triage_messages
from .specialist_agent import SpecialistAgent

_STOP_WORDS = {
    "the",
    "and",
    "for",
    "with",
    "from",
    "your",
    "you",
    "this",
    "that",
    "have",
    "has",
    "are",
    "was",
    "were",
    "will",
    "all",
    "our",
    "can",
    "not",
    "but",
    "please",
    "thanks",
    "thank",
    "re",
    "fw",
}

_ORDINAL_MAP = {
    "first": 1,
    "1st": 1,
    "one": 1,
    "second": 2,
    "2nd": 2,
    "two": 2,
    "third": 3,
    "3rd": 3,
    "three": 3,
    "fourth": 4,
    "4th": 4,
    "four": 4,
    "fifth": 5,
    "5th": 5,
    "five": 5,
}


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


def _extract_first_number(text: str) -> Optional[int]:
    match = re.search(r"\b(\d+)\b", text)
    if not match:
        return None
    return int(match.group(1))


def _extract_index(text: str) -> Optional[int]:
    lowered = text.lower()
    number = _extract_first_number(lowered)
    if number is not None:
        return number
    for token, value in _ORDINAL_MAP.items():
        if re.search(rf"\b{re.escape(token)}\b", lowered):
            return value
    return None


def _extract_count(text: str, default: int, *, max_value: int = 100) -> int:
    lowered = text.lower()
    if "all" in lowered:
        return min(max_value, 50)
    number = _extract_first_number(lowered)
    if number is None:
        return default
    return max(1, min(max_value, number))


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
        self.learning = LearningStore(self.output_root / "outlook_agent_learning.json")

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
            "Natural language is enabled. Type 'help' for examples."
        )
        return AgentReply(text=text)

    def handle_message(self, raw_message: str) -> AgentReply:
        message = raw_message.strip()
        if not message:
            return AgentReply("Send a command. Type 'help' to see available commands.")

        learning_reply = self._handle_learning_directive(message)
        if learning_reply is not None:
            return learning_reply

        direct = self._dispatch_command(message)
        if direct is not None:
            self.learning.record_history(phrase=message, command=message, source="direct", success=True)
            return direct

        learned_match = self.learning.resolve_mapping(message)
        if learned_match is not None:
            learned_reply = self._dispatch_command(learned_match.command)
            if learned_reply is not None:
                self.learning.record_history(
                    phrase=message,
                    command=learned_match.command,
                    source=f"memory:{learned_match.source}",
                    success=True,
                )
                return AgentReply(
                    text=(
                        f"Using learned mapping ({learned_match.source}, score {learned_match.score:.2f}): "
                        f"`{learned_match.command}`\n{learned_reply.text}"
                    ),
                    data=learned_reply.data,
                )

        translated = self._translate_natural(message)
        if translated is not None:
            translated_reply = self._dispatch_command(translated)
            if translated_reply is not None:
                self.learning.learn_mapping(message, translated)
                self.learning.record_history(phrase=message, command=translated, source="nl", success=True)
                return AgentReply(
                    text=f"Interpreted as: `{translated}`\n{translated_reply.text}",
                    data=translated_reply.data,
                )

        self.learning.record_history(phrase=message, command="<unrecognized>", source="none", success=False)
        return AgentReply(
            "I could not map that request yet. Try natural phrases like 'check unread emails', "
            "'draft a reply to the first email', or type 'help'."
        )

    def _dispatch_command(self, message: str) -> Optional[AgentReply]:
        lower = message.lower().strip()
        if lower in {"help", "?"}:
            return self._help_reply()
        if lower in {"status", "agent"}:
            return self._status_reply()
        if lower in {"memory", "what have you learned", "show memory"}:
            return self._memory_reply()

        if lower.startswith("inbox"):
            return self._inbox_command(message, unread_only=False)
        if lower.startswith("unread"):
            return self._inbox_command(message, unread_only=True)
        if lower.startswith("drafts"):
            return self._drafts_command(message)
        if lower.startswith("folders"):
            return self._folders_command(message)
        if re.match(r"^read\s+\d+$", lower):
            return self._read_command(message)
        if lower.startswith("triage"):
            return self._triage_command(message)
        if re.match(r"^draft\s+\d+(?:\s+send)?$", lower):
            return self._draft_command(message)
        if re.match(r"^send\s+draft\s+\d+$", lower):
            return self._send_draft_command(message)
        if re.match(r"^mark\s+(?:read|unread)\s+\d+$", lower):
            return self._mark_command(message)
        if re.match(r"^move\s+\d+\s+to\s+.+$", lower):
            return self._move_command(message)
        if lower.startswith("event "):
            return self._event_command(message)
        if lower.startswith("profile"):
            return self._profile_command(message)
        if lower.startswith("set archive folder "):
            return self._set_archive_folder_command(message)

        return None

    def _handle_learning_directive(self, message: str) -> Optional[AgentReply]:
        learn_match = re.match(r'^learn\s+"?(.+?)"?\s*=>\s*(.+)$', message, flags=re.IGNORECASE)
        if learn_match:
            phrase = learn_match.group(1).strip()
            command = learn_match.group(2).strip()
            if self._dispatch_command(command) is None:
                return AgentReply(
                    f"I cannot learn that mapping yet because this command is unknown: `{command}`"
                )
            self.learning.learn_mapping(phrase, command)
            return AgentReply(f"Learned mapping: `{phrase}` -> `{command}`")

        remember_match = re.match(
            r"^when\s+i\s+say\s+(.+?)\s+(?:run|do)\s+(.+)$",
            message,
            flags=re.IGNORECASE,
        )
        if remember_match:
            phrase = remember_match.group(1).strip().strip('"')
            command = remember_match.group(2).strip().strip('"')
            if self._dispatch_command(command) is None:
                return AgentReply(
                    f"I cannot learn that mapping yet because this command is unknown: `{command}`"
                )
            self.learning.learn_mapping(phrase, command)
            return AgentReply(f"Learned mapping: `{phrase}` -> `{command}`")

        forget_match = re.match(r'^forget\s+"?(.+?)"?$', message, flags=re.IGNORECASE)
        if forget_match:
            phrase = forget_match.group(1).strip()
            removed = self.learning.forget_mapping(phrase)
            if removed:
                return AgentReply(f"Forgot mapping for: `{phrase}`")
            return AgentReply(f"No learned mapping found for: `{phrase}`")

        return None

    def _translate_natural(self, message: str) -> Optional[str]:
        lower = " ".join(message.lower().split())
        inbox_default = int(self.learning.get_preference("default_inbox_count", 10))
        triage_default = int(self.learning.get_preference("default_triage_count", 10))

        if any(token in lower for token in {"help", "what can you do", "commands"}):
            return "help"
        if any(token in lower for token in {"status", "how are you configured"}):
            return "status"
        if "what have you learned" in lower:
            return "memory"

        if (
            "learn about my job" in lower
            or "understand my job" in lower
            or "what do i do" in lower
            or ("summarize" in lower and "email" in lower)
        ):
            count = _extract_count(lower, default=40)
            return f"profile {count}"

        triage_hint = any(
            token in lower
            for token in {
                "triage",
                "prioritize",
                "priority",
                "what should i focus",
                "most important",
            }
        )
        unread_hint = "unread" in lower
        mail_hint = any(token in lower for token in {"inbox", "email", "emails", "message", "messages"})
        list_hint = any(token in lower for token in {"show", "check", "review", "list", "load", "scan", "see"})

        if triage_hint:
            count = _extract_count(lower, default=triage_default)
            suffix = " unread" if unread_hint else ""
            return f"triage {count}{suffix}"

        if mail_hint and list_hint:
            count = _extract_count(lower, default=inbox_default)
            if unread_hint:
                return f"unread {count}"
            return f"inbox {count}"

        if any(token in lower for token in {"open email", "read email", "open message", "read message"}):
            index = _extract_index(lower) or 1
            return f"read {index}"

        if any(token in lower for token in {"reply", "draft a response", "draft reply", "respond to"}):
            index = _extract_index(lower) or 1
            send_now = any(token in lower for token in {"send now", "send it", "and send", "send immediately"})
            if send_now:
                return f"draft {index} send"
            return f"draft {index}"

        if "send draft" in lower:
            index = _extract_index(lower) or 1
            return f"send draft {index}"

        if "show drafts" in lower or "list drafts" in lower or "my drafts" in lower:
            count = _extract_count(lower, default=20)
            return f"drafts {count}"

        if "show folders" in lower or "list folders" in lower:
            match = re.search(r"(?:folders|folder list)\s+(.+)$", message, flags=re.IGNORECASE)
            if match:
                query = match.group(1).strip()
                return f"folders {query}"
            return "folders"

        if "mark" in lower and ("read" in lower or "unread" in lower):
            index = _extract_index(lower) or 1
            state = "unread" if "unread" in lower else "read"
            return f"mark {state} {index}"

        if "archive" in lower:
            index = _extract_index(lower) or 1
            folder = str(self.learning.get_preference("archive_folder", "Inbox/Archive"))
            return f"move {index} to {folder}"

        move_match = re.search(
            r"move(?:\s+(?:email|message))?\s+(.+?)\s+(?:to|into)\s+(.+)$",
            message,
            flags=re.IGNORECASE,
        )
        if move_match:
            index_text = move_match.group(1).strip()
            folder = move_match.group(2).strip()
            index = _extract_index(index_text) or 1
            return f"move {index} to {folder}"

        return None

    def _help_reply(self) -> AgentReply:
        text = (
            "Commands:\n"
            "- inbox [count]                      (example: inbox 10)\n"
            "- unread [count]                     (example: unread 10)\n"
            "- triage [count] [unread]            (example: triage 10 unread)\n"
            "- read <index>                       (example: read 2)\n"
            "- draft <index> [send]               (example: draft 1)\n"
            "- send draft <index>                 (example: send draft 1)\n"
            "- mark read <index>                  (example: mark read 3)\n"
            "- mark unread <index>                (example: mark unread 3)\n"
            "- move <index> to <folder>           (example: move 2 to Inbox/Archive)\n"
            "- folders [query]                    (example: folders inbox)\n"
            "- drafts [count]                     (example: drafts 20)\n"
            "- profile [count]                    (example: profile 40)\n"
            '- event "<subject>" <start> <end> [attendees=a@x.com,b@y.com]\n'
            '  example: event "Deal Call" 2026-02-10T14:00:00 2026-02-10T15:00:00 attendees=analyst@company.com\n'
            "- set archive folder <path>\n"
            '- learn "phrase" => command          (example: learn "check priorities" => triage 15 unread)\n'
            '- when i say <phrase> do <command>   (example: when i say quick inbox do inbox 8)\n'
            '- forget "phrase"\n'
            "- memory\n"
            "- status\n\n"
            "Natural language examples:\n"
            "- check unread emails\n"
            "- draft a reply to the second message\n"
            "- archive the first email\n"
            "- review all my emails to learn about my job"
        )
        return AgentReply(text=text)

    def _status_reply(self) -> AgentReply:
        if self.specialist_path:
            model = self.specialist_path.name
        else:
            model = "not loaded"
        mapping_count = len(self.learning.list_mappings(top=1000))
        text = (
            f"Model: {model}\n"
            f"Cached source: {self.cached_source}\n"
            f"Cached items: {len(self.cached_messages)}\n"
            f"Learned mappings: {mapping_count}\n"
            f"Learning file: {self.learning.path}"
        )
        return AgentReply(text=text)

    def _memory_reply(self) -> AgentReply:
        mappings = self.learning.list_mappings(top=20)
        if not mappings:
            return AgentReply("No learned phrase mappings yet.")

        rows = []
        for item in mappings:
            rows.append(
                {
                    "phrase": item.get("phrase"),
                    "command": item.get("command"),
                    "uses": item.get("uses"),
                    "last_used_utc": item.get("last_used_utc"),
                }
            )
        return AgentReply(
            text=f"Showing {len(rows)} learned mappings.",
            data={"mappings": rows},
        )

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
            fallback = self.client.get_inbox_messages(top=20, unread_only=False)
            if fallback:
                self._cache_messages(fallback, "inbox-auto")
            else:
                raise ValueError("No cached messages. Run inbox, unread, drafts, or triage first.")
        if index < 1 or index > len(self.cached_messages):
            raise ValueError(f"Index out of range: {index}. Cached items: {len(self.cached_messages)}")
        return self.cached_messages[index - 1]

    def _inbox_command(self, message: str, unread_only: bool) -> AgentReply:
        parts = message.split()
        default = int(self.learning.get_preference("default_inbox_count", 10))
        top = default
        if len(parts) >= 2:
            top = _parse_int(parts[1], default)
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

        top = int(match.group(1) or self.learning.get_preference("default_triage_count", 10))
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
            body_text="Created by Outlook Agent Desktop.",
        )
        return AgentReply(
            text=f"Event created: {subject}",
            data={"result": result},
        )

    def _set_archive_folder_command(self, message: str) -> AgentReply:
        folder = message[len("set archive folder ") :].strip()
        if not folder:
            return AgentReply("Specify a folder path. Example: set archive folder Inbox/Archive")
        self.learning.set_preference("archive_folder", folder)
        return AgentReply(f"Archive folder preference saved: {folder}")

    def _profile_command(self, message: str) -> AgentReply:
        parts = message.split()
        count = 40
        if len(parts) >= 2:
            count = _parse_int(parts[1], 40)
        count = max(5, min(100, count))

        messages = self.client.get_inbox_messages(top=count, unread_only=False)
        if not messages:
            return AgentReply("No messages found to build profile summary.")

        sender_counts: Counter[str] = Counter()
        token_counts: Counter[str] = Counter()
        joined_text_parts: List[str] = []

        for item in messages:
            sender = item.get("from", {}).get("emailAddress", {}).get("address", "")
            if sender:
                sender_counts[sender] += 1

            subject = str(item.get("subject", "") or "")
            preview = str(item.get("bodyPreview", "") or "")
            combined = f"{subject} {preview}"
            joined_text_parts.append(combined.lower())

            tokens = re.findall(r"[a-zA-Z][a-zA-Z0-9'-]{2,}", combined.lower())
            for token in tokens:
                if token in _STOP_WORDS:
                    continue
                token_counts[token] += 1

        joined_text = " ".join(joined_text_parts)
        focus_map = {
            "Land Acquisition": ["land", "parcel", "acquisition", "ranch", "takedown", "phase", "escrow", "title"],
            "Underwriting/Proforma": ["proforma", "underwrite", "pricing", "proposal", "budget", "cost", "deposit"],
            "Legal/Contracts": ["agreement", "contract", "legal", "counsel", "policy", "notice", "commitment"],
            "Operations/IT": ["incident", "access", "citrix", "system", "ticket", "support", "outage"],
        }

        focus_scores: Dict[str, int] = {}
        for focus, terms in focus_map.items():
            score = sum(joined_text.count(term) for term in terms)
            focus_scores[focus] = score

        ranked_focus = sorted(focus_scores.items(), key=lambda item: item[1], reverse=True)
        top_focus = [item[0] for item in ranked_focus if item[1] > 0][:3]
        if not top_focus:
            top_focus = ["General Operations"]

        top_senders = [{"sender": sender, "count": count} for sender, count in sender_counts.most_common(5)]
        top_keywords = [{"keyword": token, "count": count} for token, count in token_counts.most_common(15)]

        summary = {
            "analyzed_messages": len(messages),
            "focus_areas": top_focus,
            "top_senders": top_senders,
            "top_keywords": top_keywords,
        }
        self.learning.set_job_profile(summary)

        text = (
            f"Profile summary from {len(messages)} recent emails: likely focus areas are "
            f"{', '.join(top_focus)}."
        )
        return AgentReply(text=text, data=summary)
