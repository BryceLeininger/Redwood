"""Factory agent that creates specialized machine-learning agents."""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, List

import joblib

from .constants import KNOWLEDGE_FILE, METADATA_FILE, MODEL_FILE, REGISTRY_FILE
from .knowledge_base import build_knowledge_index, collect_text_files
from .ml_toolkit import train_task_model
from .schemas import AgentBlueprint
from .specialist_agent import SpecialistAgent


def _slugify(name: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "_", name.strip().lower())
    return slug.strip("_") or "agent"


class AgentFactory:
    """Meta-agent responsible for creating and loading specialist agents."""

    def __init__(self, output_root: Path | str = "generated_agents") -> None:
        self.output_root = Path(output_root)
        self.output_root.mkdir(parents=True, exist_ok=True)

    def create_specialist_agent(
        self,
        blueprint: AgentBlueprint,
        dataset_path: Path | str,
        knowledge_paths: Iterable[Path | str],
    ) -> Path:
        """Train and persist a specialist agent from blueprint + training assets."""

        blueprint.validate()
        dataset_file = Path(dataset_path)
        resolved_knowledge = collect_text_files(Path(item) for item in knowledge_paths)

        model, training_summary = train_task_model(dataset_file, blueprint)
        knowledge_index = build_knowledge_index(resolved_knowledge)

        agent_dir = self._new_agent_dir(blueprint.name)
        joblib.dump(model, agent_dir / MODEL_FILE)
        joblib.dump(knowledge_index, agent_dir / KNOWLEDGE_FILE)

        metadata = {
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
            "artifact_paths": {
                "model": str(agent_dir / MODEL_FILE),
                "knowledge_index": str(agent_dir / KNOWLEDGE_FILE),
            },
            "training_dataset": str(dataset_file.resolve()),
            "knowledge_files": [str(item.resolve()) for item in resolved_knowledge],
            "blueprint": blueprint.to_dict(),
            "training": training_summary.to_dict(),
        }
        (agent_dir / METADATA_FILE).write_text(json.dumps(metadata, indent=2), encoding="utf-8")

        self._append_registry_record(
            {
                "name": blueprint.name,
                "topic": blueprint.topic,
                "task_type": blueprint.task_type,
                "agent_dir": str(agent_dir.resolve()),
                "created_at_utc": metadata["created_at_utc"],
                "metric_name": training_summary.metric_name,
                "metric_value": training_summary.metric_value,
            }
        )
        return agent_dir

    def load_specialist_agent(self, agent_dir: Path | str) -> SpecialistAgent:
        return SpecialistAgent.load(agent_dir)

    def list_registered_agents(self) -> List[dict]:
        registry_path = self.output_root / REGISTRY_FILE
        if not registry_path.exists():
            return []
        return json.loads(registry_path.read_text(encoding="utf-8"))

    def _new_agent_dir(self, name: str) -> Path:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        base_name = f"{_slugify(name)}_{timestamp}"
        candidate = self.output_root / base_name

        suffix = 1
        while candidate.exists():
            candidate = self.output_root / f"{base_name}_{suffix}"
            suffix += 1

        candidate.mkdir(parents=True, exist_ok=False)
        return candidate

    def _append_registry_record(self, record: dict) -> None:
        registry_path = self.output_root / REGISTRY_FILE
        if registry_path.exists():
            registry = json.loads(registry_path.read_text(encoding="utf-8"))
        else:
            registry = []
        registry.append(record)
        registry_path.write_text(json.dumps(registry, indent=2), encoding="utf-8")
