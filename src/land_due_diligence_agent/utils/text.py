"""Text cleanup and lightweight summarization helpers."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable


_SPACE_RE = re.compile(r"[ \t]+")
_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")
_MOJIBAKE_SENTINELS = ("Ã", "Â", "â€", "â€™", "â€œ", "â€", "�")
_MOJIBAKE_REPLACEMENTS = {
    "\u00a0": " ",
    "Ã‚ ": " ",
    "Ã‚": "",
    "Â·": "",
    "Â": "",
    "Ã¢â‚¬â„¢": "'",
    "Ã¢â‚¬Ëœ": "'",
    "Ã¢â‚¬Å“": '"',
    "Ã¢â‚¬\u009d": '"',
    "Ã¢â‚¬\x9d": '"',
    "Ã¢â‚¬â€": "-",
    "Ã¢â‚¬\"": "-",
    "Ã¢â‚¬\x94": "-",
    "Ã¢â‚¬â€œ": "-",
    "Ãƒâ€”": "x",
    "â€™": "'",
    "â€˜": "'",
    "â€œ": '"',
    "â€": '"',
    "â€“": "-",
    "â€”": "-",
    "â€‘": "-",
    "â€¢": "-",
    "Ã—": "x",
    "’": "'",
    "‘": "'",
    "“": '"',
    "”": '"',
    "–": "-",
    "—": "-",
}


def normalize_text(text: str) -> str:
    """Collapse noisy whitespace while keeping paragraph boundaries."""

    if not text:
        return ""

    text = repair_text_artifacts(text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = [_SPACE_RE.sub(" ", line).strip() for line in text.split("\n")]

    normalized_lines: list[str] = []
    previous_blank = False
    for line in lines:
        if not line:
            if not previous_blank:
                normalized_lines.append("")
            previous_blank = True
            continue
        normalized_lines.append(line)
        previous_blank = False

    return "\n".join(normalized_lines).strip()


def repair_text_artifacts(text: str) -> str:
    """Repair common OCR / mojibake artifacts without adding heavy dependencies."""

    if not text:
        return ""

    repaired = _maybe_redecode_mojibake(text)
    for source, target in _MOJIBAKE_REPLACEMENTS.items():
        repaired = repaired.replace(source, target)

    repaired = unicodedata.normalize("NFKC", repaired)
    repaired = re.sub(r"[\u200b-\u200d\u2060]", "", repaired)
    repaired = re.sub(r"\s+([,.;:!?])", r"\1", repaired)
    repaired = re.sub(r"([([{])\s+", r"\1", repaired)
    repaired = re.sub(r"\s+([)\]}])", r"\1", repaired)
    return repaired.strip()


def _maybe_redecode_mojibake(text: str) -> str:
    if _mojibake_score(text) < 2:
        return text
    try:
        candidate = text.encode("cp1252").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return text
    return candidate if _mojibake_score(candidate) < _mojibake_score(text) else text


def _mojibake_score(text: str) -> int:
    return sum(text.count(marker) for marker in _MOJIBAKE_SENTINELS)


def split_sentences(text: str) -> list[str]:
    """Split normalized text into sentence-like chunks."""

    if not text:
        return []

    compact = text.replace("\n", " ")
    parts = _SENTENCE_RE.split(compact)
    return [part.strip() for part in parts if part.strip()]


def clip_text(text: str, max_chars: int) -> str:
    """Trim text at a character boundary for prompts or concise output."""

    if len(text) <= max_chars:
        return text
    return text[: max_chars - 3].rstrip() + "..."


def extractive_summary(text: str, *, max_sentences: int = 4) -> str:
    """Build a deterministic summary from the first substantive sentences."""

    sentences = [sentence for sentence in split_sentences(text) if len(sentence) >= 40]
    if sentences:
        return " ".join(sentences[:max_sentences])
    return clip_text(text.strip(), 400) or "No substantive text extracted."


def unique_preserve_order(values: Iterable[str]) -> list[str]:
    """Deduplicate items without changing their original order."""

    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        ordered.append(value)
    return ordered
