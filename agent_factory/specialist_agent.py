"""Runtime specialist agent produced by the factory agent."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

import joblib
import numpy as np

from .constants import KNOWLEDGE_FILE, METADATA_FILE, MODEL_FILE
from .knowledge_base import search_knowledge


def _serialize_value(value: Any) -> Any:
    if isinstance(value, (np.floating, np.integer)):
        return value.item()
    return value


class SpecialistAgent:
    """Executes learned task predictions and topic knowledge retrieval."""

    def __init__(self, agent_dir: Path, metadata: Dict[str, Any], model: Any, knowledge_index: Dict[str, Any]) -> None:
        self.agent_dir = agent_dir
        self.metadata = metadata
        self.model = model
        self.knowledge_index = knowledge_index

    @classmethod
    def load(cls, agent_dir: Path | str) -> "SpecialistAgent":
        resolved_dir = Path(agent_dir)
        if not resolved_dir.exists():
            raise ValueError(f"Agent directory does not exist: {resolved_dir}")

        metadata_path = resolved_dir / METADATA_FILE
        model_path = resolved_dir / MODEL_FILE
        knowledge_path = resolved_dir / KNOWLEDGE_FILE

        for required in (metadata_path, model_path, knowledge_path):
            if not required.exists():
                raise ValueError(f"Missing specialist artifact: {required}")

        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        model = joblib.load(model_path)
        knowledge_index = joblib.load(knowledge_path)
        return cls(resolved_dir, metadata, model, knowledge_index)

    def describe(self) -> Dict[str, Any]:
        return self.metadata

    def predict(self, task_input: str) -> Dict[str, Any]:
        task_input = task_input.strip()
        if not task_input:
            raise ValueError("Input text cannot be empty.")

        prediction = self.model.predict([task_input])[0]
        result: Dict[str, Any] = {
            "agent": self.metadata["blueprint"]["name"],
            "task_type": self.metadata["blueprint"]["task_type"],
            "input": task_input,
            "prediction": _serialize_value(prediction),
        }

        if self.metadata["blueprint"]["task_type"] == "classification" and hasattr(self.model, "predict_proba"):
            probabilities = self.model.predict_proba([task_input])[0]
            classes = getattr(self.model, "classes_", None)
            if classes is not None:
                ranked_indexes = np.argsort(probabilities)[::-1][: min(3, len(classes))]
                top_classes: List[Dict[str, Any]] = []
                for index in ranked_indexes:
                    top_classes.append(
                        {
                            "label": _serialize_value(classes[index]),
                            "confidence": float(probabilities[index]),
                        }
                    )
                result["top_classes"] = top_classes

        return result

    def ask_topic_question(self, question: str, top_k: int = 3) -> Dict[str, Any]:
        hits = search_knowledge(self.knowledge_index, question, top_k=top_k)
        if not hits:
            return {
                "agent": self.metadata["blueprint"]["name"],
                "topic": self.metadata["blueprint"]["topic"],
                "question": question,
                "answer": "No relevant topic knowledge was found in this agent index.",
                "sources": [],
            }

        excerpts = [f"{idx}. {hit.text}" for idx, hit in enumerate(hits, start=1)]
        answer = "Relevant knowledge excerpts:\n" + "\n".join(excerpts)

        return {
            "agent": self.metadata["blueprint"]["name"],
            "topic": self.metadata["blueprint"]["topic"],
            "question": question,
            "answer": answer,
            "sources": [
                {
                    "source": hit.source,
                    "score": hit.score,
                }
                for hit in hits
            ],
        }
