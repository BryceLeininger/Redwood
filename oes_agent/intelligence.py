"""Heuristic and AI-assisted triage helpers for OES."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any

from openai import OpenAI

from .config import OESConfig
from .models import CalendarEventSummary, MessageSummary, Priority

MONTH_PATTERN = (
    r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|"
    r"jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
)


class OESIntelligence:
    def __init__(self, config: OESConfig) -> None:
        self.config = config
        self._client = OpenAI(api_key=config.openai_api_key) if config.has_ai_config else None

    def analyze_message(self, raw_message: dict[str, Any]) -> MessageSummary:
        sender = raw_message.get("from") or {}
        sender_address = sender.get("emailAddress") or {}
        summary = MessageSummary(
            message_id=str(raw_message.get("id", "")),
            subject=str(raw_message.get("subject") or "(no subject)"),
            sender_name=str(sender_address.get("name") or "Unknown sender"),
            sender_email=str(sender_address.get("address") or ""),
            received_at=str(raw_message.get("receivedDateTime") or datetime.now(timezone.utc).isoformat()),
            body_preview=str(raw_message.get("bodyPreview") or ""),
            is_read=bool(raw_message.get("isRead", False)),
            categories=list(raw_message.get("categories") or []),
            raw_payload=raw_message,
        )

        self._apply_heuristics(summary)
        if self._client is not None:
            self._apply_ai_overrides(summary)
        return summary

    def analyze_event(self, raw_event: dict[str, Any]) -> CalendarEventSummary:
        organizer = raw_event.get("organizer") or {}
        organizer_email = organizer.get("emailAddress") or {}
        start = raw_event.get("start") or {}
        end = raw_event.get("end") or {}
        location = raw_event.get("location") or {}
        event = CalendarEventSummary(
            event_id=str(raw_event.get("id", "")),
            subject=str(raw_event.get("subject") or "Untitled event"),
            start_at=str(start.get("dateTime") or ""),
            end_at=str(end.get("dateTime") or ""),
            organizer_name=str(organizer_email.get("name") or "Unknown organizer"),
            organizer_email=str(organizer_email.get("address") or ""),
            location=str(location.get("displayName") or ""),
            raw_payload=raw_event,
        )
        event.summary = self._summarize_event(event)
        if event.start_at:
            event.action_items.append(f"Prepare for {event.subject}.")
        return event

    def _apply_heuristics(self, summary: MessageSummary) -> None:
        text = f"{summary.subject}\n{summary.body_preview}".lower()
        if any(token in text for token in ("urgent", "asap", "immediately", "wire", "escrow", "closing today")):
            summary.priority = Priority.CRITICAL
            summary.triage_label = "urgent_response"
        elif any(token in text for token in ("follow up", "review", "please", "deadline", "tomorrow", "deposit")):
            summary.priority = Priority.HIGH
            summary.triage_label = "action_required"
        elif any(token in text for token in ("meeting", "calendar", "invite", "schedule")):
            summary.priority = Priority.NORMAL
            summary.triage_label = "calendar_related"
        else:
            summary.priority = Priority.NORMAL
            summary.triage_label = "review"

        summary.summary = self._first_sentence(summary.body_preview) or summary.subject
        summary.action_items = self._extract_action_items(text=summary.body_preview)
        summary.suggested_actions = self._suggest_actions(summary)
        summary.draft_reply = self._draft_reply(summary)

    def _apply_ai_overrides(self, summary: MessageSummary) -> None:
        try:
            prompt_payload = {
                "subject": summary.subject,
                "sender_name": summary.sender_name,
                "sender_email": summary.sender_email,
                "body_preview": summary.body_preview,
                "categories": summary.categories,
            }
            response = self._client.responses.create(
                model=self.config.openai_model,
                input=[
                    {
                        "role": "system",
                        "content": (
                            "You are an executive email secretary. Respond with strict JSON containing: "
                            "summary, triage_label, priority, action_items, suggested_actions, draft_reply. "
                            "Do not wrap the JSON in markdown."
                        ),
                    },
                    {"role": "user", "content": json.dumps(prompt_payload)},
                ],
            )
            parsed = json.loads(response.output_text)
        except Exception:
            return

        if parsed.get("summary"):
            summary.summary = str(parsed["summary"])
        if parsed.get("triage_label"):
            summary.triage_label = str(parsed["triage_label"])
        if parsed.get("priority") in {item.value for item in Priority}:
            summary.priority = Priority(str(parsed["priority"]))
        if isinstance(parsed.get("action_items"), list):
            summary.action_items = [str(item) for item in parsed["action_items"] if str(item).strip()]
        if isinstance(parsed.get("suggested_actions"), list):
            summary.suggested_actions = [str(item) for item in parsed["suggested_actions"] if str(item).strip()]
        if parsed.get("draft_reply"):
            summary.draft_reply = str(parsed["draft_reply"])

    def _extract_action_items(self, text: str) -> list[str]:
        candidates = []
        cleaned = re.sub(r"\s+", " ", text).strip()
        if not cleaned:
            return candidates

        for sentence in re.split(r"(?<=[.!?])\s+", cleaned):
            lower = sentence.lower()
            if any(token in lower for token in ("please", "need", "can you", "follow up", "review", "send", "prepare")):
                candidates.append(sentence.strip())
        due_phrase = self._find_due_phrase(cleaned)
        if due_phrase:
            candidates.append(f"Due timing noted: {due_phrase}.")
        deduped = []
        for item in candidates:
            if item and item not in deduped:
                deduped.append(item)
        return deduped[:3]

    def _find_due_phrase(self, text: str) -> str | None:
        patterns = [
            r"\b\d{4}-\d{2}-\d{2}\b",
            rf"\b{MONTH_PATTERN}\s+\d{{1,2}}(?:,\s*\d{{4}})?\b",
            r"\b(?:today|tomorrow|this afternoon|this morning|next week|end of day)\b",
        ]
        for pattern in patterns:
            match = re.search(pattern, text, flags=re.IGNORECASE)
            if match:
                return match.group(0)
        return None

    def _suggest_actions(self, summary: MessageSummary) -> list[str]:
        actions = ["Review message"]
        if summary.draft_reply:
            actions.append("Create draft reply")
        if summary.action_items:
            actions.append("Create reminder")
        if summary.triage_label == "calendar_related":
            actions.append("Review calendar impact")
        return actions

    def _draft_reply(self, summary: MessageSummary) -> str:
        greeting = summary.sender_name.split()[0] if summary.sender_name and summary.sender_name != "Unknown sender" else "there"
        next_step = summary.action_items[0] if summary.action_items else "I will review this and follow up shortly."
        return (
            f"Hi {greeting},\n\n"
            f"Thanks for the note. My understanding is: {summary.summary}\n\n"
            f"Next step: {next_step}\n\n"
            "Best,"
        )

    def _first_sentence(self, text: str) -> str:
        match = re.split(r"(?<=[.!?])\s+", text.strip(), maxsplit=1)
        if not match:
            return ""
        return match[0].strip()

    def _summarize_event(self, event: CalendarEventSummary) -> str:
        if event.location:
            return f"{event.subject} with {event.organizer_name} at {event.location}."
        return f"{event.subject} with {event.organizer_name}."