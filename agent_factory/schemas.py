"""Shared data models for the agent factory system."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Dict, Literal

TaskType = Literal["classification", "regression"]


@dataclass(frozen=True)
class AgentBlueprint:
    """Definition used by the factory agent to build a specialist agent."""

    name: str
    description: str
    topic: str
    task_type: TaskType
    input_column: str = "input"
    target_column: str = "target"

    def validate(self) -> None:
        """Validate blueprint fields before training."""

        if not self.name.strip():
            raise ValueError("Blueprint name cannot be empty.")
        if not self.description.strip():
            raise ValueError("Blueprint description cannot be empty.")
        if not self.topic.strip():
            raise ValueError("Blueprint topic cannot be empty.")
        if self.task_type not in ("classification", "regression"):
            raise ValueError("task_type must be 'classification' or 'regression'.")
        if not self.input_column.strip():
            raise ValueError("input_column cannot be empty.")
        if not self.target_column.strip():
            raise ValueError("target_column cannot be empty.")

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class TrainingSummary:
    """Summary produced after model training and evaluation."""

    total_rows: int
    train_rows: int
    evaluation_rows: int
    used_holdout_split: bool
    metric_name: str
    metric_value: float
    task_type: TaskType

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
