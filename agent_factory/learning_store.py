"""Persistent memory store for improving Outlook agent behavior over time."""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Dict, List, Optional


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_phrase(value: str) -> str:
    return " ".join(value.strip().lower().split())


@dataclass
class LearningMatch:
    phrase: str
    command: str
    score: float
    source: str


class LearningStore:
    """Simple JSON-backed store for learned natural-language mappings and history."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.data = self._load()

    def _default(self) -> Dict[str, Any]:
        return {
            "mappings": [],
            "history": [],
            "preferences": {
                "default_inbox_count": 10,
                "default_triage_count": 10,
            },
            "last_job_profile": {},
            "updated_at_utc": _utc_now(),
        }

    def _load(self) -> Dict[str, Any]:
        if not self.path.exists():
            return self._default()
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                return self._default()
            for key, value in self._default().items():
                payload.setdefault(key, value)
            return payload
        except json.JSONDecodeError:
            return self._default()

    def _save(self) -> None:
        self.data["updated_at_utc"] = _utc_now()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.data, indent=2), encoding="utf-8")

    def get_preference(self, key: str, default: Any) -> Any:
        return self.data.get("preferences", {}).get(key, default)

    def set_preference(self, key: str, value: Any) -> None:
        self.data.setdefault("preferences", {})[key] = value
        self._save()

    def learn_mapping(self, phrase: str, command: str) -> None:
        phrase_norm = _normalize_phrase(phrase)
        if not phrase_norm:
            return

        mappings: List[Dict[str, Any]] = self.data.setdefault("mappings", [])
        for item in mappings:
            if item.get("phrase_norm") == phrase_norm:
                item["command"] = command
                item["uses"] = int(item.get("uses", 0)) + 1
                item["last_used_utc"] = _utc_now()
                self._save()
                return

        mappings.append(
            {
                "phrase": phrase.strip(),
                "phrase_norm": phrase_norm,
                "command": command.strip(),
                "uses": 1,
                "last_used_utc": _utc_now(),
            }
        )
        self._save()

    def forget_mapping(self, phrase: str) -> bool:
        phrase_norm = _normalize_phrase(phrase)
        mappings: List[Dict[str, Any]] = self.data.setdefault("mappings", [])
        before = len(mappings)
        filtered = [item for item in mappings if item.get("phrase_norm") != phrase_norm]
        self.data["mappings"] = filtered
        if len(filtered) != before:
            self._save()
            return True
        return False

    def resolve_mapping(self, phrase: str) -> Optional[LearningMatch]:
        phrase_norm = _normalize_phrase(phrase)
        if not phrase_norm:
            return None

        mappings: List[Dict[str, Any]] = self.data.get("mappings", [])
        for item in mappings:
            if item.get("phrase_norm") == phrase_norm:
                return LearningMatch(
                    phrase=item.get("phrase", ""),
                    command=item.get("command", ""),
                    score=1.0,
                    source="exact",
                )

        best_score = 0.0
        best_item: Optional[Dict[str, Any]] = None
        for item in mappings:
            candidate = item.get("phrase_norm", "")
            if not candidate:
                continue
            score = SequenceMatcher(a=phrase_norm, b=candidate).ratio()
            if score > best_score:
                best_score = score
                best_item = item

        if best_item and best_score >= 0.9:
            return LearningMatch(
                phrase=best_item.get("phrase", ""),
                command=best_item.get("command", ""),
                score=best_score,
                source="fuzzy",
            )
        return None

    def list_mappings(self, top: int = 20) -> List[Dict[str, Any]]:
        mappings = list(self.data.get("mappings", []))
        mappings.sort(key=lambda item: item.get("last_used_utc", ""), reverse=True)
        return mappings[: max(1, top)]

    def record_history(self, *, phrase: str, command: str, source: str, success: bool) -> None:
        history: List[Dict[str, Any]] = self.data.setdefault("history", [])
        history.append(
            {
                "timestamp_utc": _utc_now(),
                "phrase": phrase.strip(),
                "command": command.strip(),
                "source": source,
                "success": bool(success),
            }
        )
        # Keep file bounded.
        self.data["history"] = history[-400:]
        self._save()

    def set_job_profile(self, payload: Dict[str, Any]) -> None:
        self.data["last_job_profile"] = payload
        self._save()

    def get_job_profile(self) -> Dict[str, Any]:
        value = self.data.get("last_job_profile", {})
        if isinstance(value, dict):
            return value
        return {}
