"""Topic knowledge indexing and retrieval utilities."""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Sequence

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

SUPPORTED_EXTENSIONS = {".txt", ".md", ".rst", ".csv", ".json", ".log"}


@dataclass(frozen=True)
class KnowledgeHit:
    source: str
    text: str
    score: float

    def to_dict(self) -> Dict[str, Any]:
        return {"source": self.source, "text": self.text, "score": self.score}


def collect_text_files(paths: Iterable[Path]) -> List[Path]:
    """Expand directories and return readable files supported for indexing."""

    collected: List[Path] = []
    for path in paths:
        if path.is_dir():
            files = [item for item in path.rglob("*") if item.is_file()]
            collected.extend(files)
        elif path.is_file():
            collected.append(path)
        else:
            raise ValueError(f"Knowledge path was not found: {path}")

    unique: List[Path] = []
    seen = set()
    for file_path in sorted(collected):
        if file_path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            continue
        key = str(file_path.resolve()).lower()
        if key in seen:
            continue
        seen.add(key)
        unique.append(file_path)

    if not unique:
        raise ValueError("No supported knowledge files were found.")
    return unique


def _chunk_text(text: str, max_chars: int = 450) -> List[str]:
    blocks = [block.strip() for block in re.split(r"\n\s*\n", text) if block.strip()]
    if not blocks:
        blocks = [line.strip() for line in text.splitlines() if line.strip()]

    chunks: List[str] = []
    for block in blocks:
        if len(block) <= max_chars:
            chunks.append(block)
            continue
        parts = re.split(r"(?<=[.!?])\s+", block)
        running: List[str] = []
        running_len = 0
        for part in parts:
            part = part.strip()
            if not part:
                continue
            projected = running_len + len(part) + (1 if running else 0)
            if projected > max_chars and running:
                chunks.append(" ".join(running))
                running = [part]
                running_len = len(part)
            else:
                running.append(part)
                running_len = projected
        if running:
            chunks.append(" ".join(running))
    return chunks


def build_knowledge_index(knowledge_files: Sequence[Path]) -> Dict[str, Any]:
    """Build an in-memory TF-IDF index of topic knowledge files."""

    chunks: List[str] = []
    sources: List[str] = []

    for file_path in knowledge_files:
        text = file_path.read_text(encoding="utf-8", errors="ignore")
        file_chunks = _chunk_text(text)
        for chunk in file_chunks:
            chunks.append(chunk)
            sources.append(str(file_path))

    if not chunks:
        raise ValueError("Knowledge files were loaded but no text chunks were generated.")

    vectorizer = TfidfVectorizer(stop_words="english", ngram_range=(1, 2), max_features=6000)
    matrix = vectorizer.fit_transform(chunks)

    return {
        "vectorizer": vectorizer,
        "matrix": matrix,
        "chunks": chunks,
        "sources": sources,
    }


def search_knowledge(index: Dict[str, Any], question: str, top_k: int = 3) -> List[KnowledgeHit]:
    """Query the indexed knowledge for the best matching text chunks."""

    question = question.strip()
    if not question:
        raise ValueError("Question cannot be empty.")

    vectorizer = index["vectorizer"]
    matrix = index["matrix"]
    chunks = index["chunks"]
    sources = index["sources"]

    query_vector = vectorizer.transform([question])
    scores = cosine_similarity(query_vector, matrix).ravel()

    if not np.any(scores > 0):
        return []

    top_k = max(1, min(top_k, len(chunks)))
    ranked_indexes = np.argsort(scores)[::-1][:top_k]

    hits: List[KnowledgeHit] = []
    for idx in ranked_indexes:
        score = float(scores[idx])
        if score <= 0:
            continue
        hits.append(
            KnowledgeHit(
                source=sources[idx],
                text=chunks[idx],
                score=score,
            )
        )
    return hits
