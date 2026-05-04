"""Heuristic and AI-assisted triage helpers for OES."""

from __future__ import annotations

from collections import Counter
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
SUBJECT_STOPWORDS = {
    "a",
    "an",
    "and",
    "for",
    "from",
    "fwd",
    "fw",
    "in",
    "is",
    "of",
    "on",
    "re",
    "regarding",
    "the",
    "to",
    "update",
    "with",
}
LOW_SIGNAL_TOKENS = (
    "newsletter",
    "digest",
    "marketing",
    "promotion",
    "unsubscribe",
    "recap",
    "webinar",
    "announcement",
)
GREETING_TEMPLATES = {
    "good morning": "Good morning {first_name},",
    "good afternoon": "Good afternoon {first_name},",
    "good evening": "Good evening {first_name},",
    "dear": "Dear {first_name},",
    "hello": "Hello {first_name},",
    "hi": "Hi {first_name},",
}
SIGNOFF_PREFIXES = (
    "best regards",
    "regards",
    "best",
    "thanks",
    "thank you",
    "sincerely",
)


class OESIntelligence:
    def __init__(self, config: OESConfig) -> None:
        self.config = config
        self._client = OpenAI(api_key=config.openai_api_key) if config.has_ai_config else None

    def analyze_message(self, raw_message: dict[str, Any], response_profile: dict[str, Any] | None = None) -> MessageSummary:
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

        self._apply_heuristics(summary, response_profile or {})
        if self._client is not None:
            self._apply_ai_overrides(summary, response_profile or {})
        return summary

    def build_response_profile(self, sent_messages: list[dict[str, Any]]) -> dict[str, Any]:
        if not sent_messages:
            return {}

        greeting_counter: Counter[str] = Counter()
        closing_counter: Counter[str] = Counter()
        signature_counter: Counter[str] = Counter()
        acknowledgement_counter: Counter[str] = Counter()
        follow_up_counter: Counter[str] = Counter()
        recipient_counter: Counter[str] = Counter()
        domain_counter: Counter[str] = Counter()
        keyword_counter: Counter[str] = Counter()

        for raw_message in sent_messages:
            for recipient in self._extract_recipients(raw_message):
                recipient_counter[recipient] += 1
                domain = self._email_domain(recipient)
                if domain:
                    domain_counter[domain] += 1

            for token in self._subject_keywords(str(raw_message.get("subject") or "")):
                keyword_counter[token] += 1

            cleaned_body = self._clean_message_body(str(raw_message.get("bodyPreview") or raw_message.get("body") or ""))
            lines = [line.strip() for line in cleaned_body.splitlines() if line.strip()]
            if not lines:
                continue

            greeting = self._detect_greeting_template(lines[0])
            if greeting:
                greeting_counter[greeting] += 1

            acknowledgement = self._extract_acknowledgement(lines)
            if acknowledgement:
                acknowledgement_counter[acknowledgement] += 1

            follow_up = self._extract_follow_up_phrase(lines)
            if follow_up:
                follow_up_counter[follow_up] += 1

            closing, signature = self._extract_closing(lines)
            if closing:
                closing_counter[closing] += 1
            if signature:
                signature_counter[signature] += 1

        return {
            "sample_size": len(sent_messages),
            "greeting_style": self._most_common(greeting_counter) or "Hi {first_name},",
            "closing_style": self._most_common(closing_counter) or "Best regards,",
            "signature_name": self._most_common(signature_counter),
            "acknowledgement_phrase": self._most_common(acknowledgement_counter) or "Thank you for the update.",
            "follow_up_phrase": self._most_common(follow_up_counter) or "I will review this and follow up shortly.",
            "priority_contacts": [address for address, count in recipient_counter.most_common(12) if count >= 2],
            "priority_domains": [domain for domain, count in domain_counter.most_common(8) if count >= 3],
            "priority_subject_keywords": [token for token, count in keyword_counter.most_common(15) if count >= 2],
        }

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

    def _apply_heuristics(self, summary: MessageSummary, response_profile: dict[str, Any]) -> None:
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

        self._apply_response_habits(summary, response_profile)

        summary.summary = self._first_sentence(summary.body_preview) or summary.subject
        summary.action_items = self._extract_action_items(text=summary.body_preview)
        summary.suggested_actions = self._suggest_actions(summary)
        summary.draft_reply = self._draft_reply(summary, response_profile)

    def _apply_ai_overrides(self, summary: MessageSummary, response_profile: dict[str, Any]) -> None:
        try:
            prompt_payload = {
                "subject": summary.subject,
                "sender_name": summary.sender_name,
                "sender_email": summary.sender_email,
                "body_preview": summary.body_preview,
                "categories": summary.categories,
                "response_profile": response_profile,
            }
            response = self._client.responses.create(
                model=self.config.openai_model,
                input=[
                    {
                        "role": "system",
                        "content": (
                            "You are an executive email secretary. Respond with strict JSON containing: "
                            "summary, triage_label, priority, action_items, suggested_actions, draft_reply. "
                            "Use response_profile to match the user's tone and historical response habits when it is present. "
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
        if summary.raw_payload.get("habitSignal") == "low_signal":
            actions.append("No response likely needed")
        return actions

    def _draft_reply(self, summary: MessageSummary, response_profile: dict[str, Any]) -> str:
        greeting = summary.sender_name.split()[0] if summary.sender_name and summary.sender_name != "Unknown sender" else "there"
        greeting_template = str(response_profile.get("greeting_style") or "Hi {first_name},")
        acknowledgement = str(response_profile.get("acknowledgement_phrase") or "Thanks for the note.")
        follow_up = summary.action_items[0] if summary.action_items else str(
            response_profile.get("follow_up_phrase") or "I will review this and follow up shortly."
        )
        closing = str(response_profile.get("closing_style") or "Best regards,")
        signature_name = response_profile.get("signature_name")

        lines = [
            greeting_template.format(first_name=greeting),
            "",
            acknowledgement,
            f"My understanding is: {summary.summary}",
            "",
            f"Next step: {follow_up}",
            "",
            closing,
        ]
        if signature_name:
            lines.append(str(signature_name))
        return "\n".join(lines)

    def _apply_response_habits(self, summary: MessageSummary, response_profile: dict[str, Any]) -> None:
        if not response_profile:
            return

        sender_email = summary.sender_email.lower()
        sender_domain = self._email_domain(sender_email)
        subject_keywords = set(self._subject_keywords(summary.subject))
        priority_contacts = set(response_profile.get("priority_contacts") or [])
        priority_domains = set(response_profile.get("priority_domains") or [])
        priority_keywords = set(response_profile.get("priority_subject_keywords") or [])
        text = f"{summary.subject}\n{summary.body_preview}".lower()

        if sender_email in priority_contacts or sender_domain in priority_domains or subject_keywords.intersection(priority_keywords):
            summary.priority = self._bump_priority(summary.priority)
            if summary.triage_label == "review":
                summary.triage_label = "priority_contact"
            summary.raw_payload["habitSignal"] = "priority_contact"
            return

        if self._is_low_signal_message(sender_email, text):
            summary.priority = Priority.LOW
            if summary.triage_label == "review":
                summary.triage_label = "low_signal"
            summary.raw_payload["habitSignal"] = "low_signal"

    def _clean_message_body(self, text: str) -> str:
        if not text:
            return ""
        separators = (
            "-----Original Message-----",
            "From:",
            "Sent from my",
        )
        cleaned = text
        for separator in separators:
            if separator in cleaned:
                cleaned = cleaned.split(separator, maxsplit=1)[0]
        return cleaned.strip()

    def _extract_recipients(self, raw_message: dict[str, Any]) -> list[str]:
        recipients = []
        for recipient in raw_message.get("toRecipients") or []:
            email = ((recipient or {}).get("emailAddress") or {}).get("address")
            if email:
                recipients.append(str(email).lower())
        return recipients

    def _subject_keywords(self, subject: str) -> list[str]:
        tokens = []
        for token in re.findall(r"[A-Za-z][A-Za-z0-9']{2,}", subject.lower()):
            if token not in SUBJECT_STOPWORDS:
                tokens.append(token)
        return tokens

    def _detect_greeting_template(self, line: str) -> str | None:
        normalized = line.strip().rstrip(":")
        lower = normalized.lower()
        for prefix, template in GREETING_TEMPLATES.items():
            if lower.startswith(prefix):
                return template
        return None

    def _extract_acknowledgement(self, lines: list[str]) -> str | None:
        for line in lines[:4]:
            lower = line.lower()
            if lower.startswith(("thank you", "thanks", "appreciate")):
                return line.strip()
        return None

    def _extract_follow_up_phrase(self, lines: list[str]) -> str | None:
        for line in lines[:6]:
            lower = line.lower()
            if "i will" in lower or "we will" in lower or "follow up" in lower:
                return line.strip()
        return None

    def _extract_closing(self, lines: list[str]) -> tuple[str | None, str | None]:
        tail = lines[-4:]
        for index, line in enumerate(tail):
            lower = line.lower().rstrip(",")
            if lower in SIGNOFF_PREFIXES:
                signature = None
                if index + 1 < len(tail):
                    candidate = tail[index + 1].strip()
                    if candidate and len(candidate.split()) <= 3 and "@" not in candidate:
                        signature = candidate
                return line.strip(), signature
        return None, None

    def _is_low_signal_message(self, sender_email: str, text: str) -> bool:
        local_part = sender_email.split("@", maxsplit=1)[0]
        if local_part in {"noreply", "no-reply", "donotreply", "notifications"}:
            return True
        return any(token in text for token in LOW_SIGNAL_TOKENS)

    def _email_domain(self, email: str) -> str:
        if "@" not in email:
            return ""
        return email.split("@", maxsplit=1)[1].lower()

    def _bump_priority(self, priority: Priority) -> Priority:
        if priority == Priority.LOW:
            return Priority.NORMAL
        if priority == Priority.NORMAL:
            return Priority.HIGH
        return priority

    def _most_common(self, counter: Counter[str]) -> str | None:
        if not counter:
            return None
        return counter.most_common(1)[0][0]

    def _first_sentence(self, text: str) -> str:
        match = re.split(r"(?<=[.!?])\s+", text.strip(), maxsplit=1)
        if not match:
            return ""
        return match[0].strip()

    def _summarize_event(self, event: CalendarEventSummary) -> str:
        if event.location:
            return f"{event.subject} with {event.organizer_name} at {event.location}."
        return f"{event.subject} with {event.organizer_name}."