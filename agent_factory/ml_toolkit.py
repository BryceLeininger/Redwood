"""Model training utilities used by the factory agent."""
from __future__ import annotations

from pathlib import Path
from typing import Tuple

import numpy as np
import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression, Ridge
from sklearn.metrics import accuracy_score, mean_squared_error
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline

from .schemas import AgentBlueprint, TrainingSummary


def _build_pipeline(task_type: str) -> Pipeline:
    if task_type == "classification":
        estimator = LogisticRegression(max_iter=1000)
    else:
        estimator = Ridge(alpha=1.0)
    return Pipeline(
        [
            (
                "vectorizer",
                TfidfVectorizer(stop_words="english", ngram_range=(1, 2), max_features=5000),
            ),
            ("model", estimator),
        ]
    )


def _load_dataset(dataset_path: Path, blueprint: AgentBlueprint) -> pd.DataFrame:
    if not dataset_path.exists():
        raise ValueError(f"Dataset was not found: {dataset_path}")
    if dataset_path.suffix.lower() != ".csv":
        raise ValueError("Dataset must be a CSV file.")

    dataframe = pd.read_csv(dataset_path)
    required = {blueprint.input_column, blueprint.target_column}
    missing = required.difference(dataframe.columns)
    if missing:
        missing_list = ", ".join(sorted(missing))
        raise ValueError(f"Dataset is missing required columns: {missing_list}")

    cleaned = dataframe[[blueprint.input_column, blueprint.target_column]].dropna().copy()
    cleaned[blueprint.input_column] = cleaned[blueprint.input_column].astype(str).str.strip()
    cleaned = cleaned[cleaned[blueprint.input_column] != ""]

    if cleaned.empty:
        raise ValueError("Dataset contains no valid training rows after cleaning.")
    if len(cleaned) < 2:
        raise ValueError("At least 2 valid rows are required for training.")
    if blueprint.task_type == "classification" and cleaned[blueprint.target_column].nunique() < 2:
        raise ValueError("Classification requires at least two target classes.")
    return cleaned


def _split_data(
    dataframe: pd.DataFrame,
    input_column: str,
    target_column: str,
    task_type: str,
) -> Tuple[pd.Series, pd.Series, pd.Series, pd.Series, bool]:
    features = dataframe[input_column]
    targets = dataframe[target_column]

    # Small datasets are trained and evaluated on the same data.
    if len(dataframe) < 10:
        return features, features, targets, targets, False

    stratify = None
    if task_type == "classification":
        counts = targets.value_counts()
        if counts.min() >= 2:
            stratify = targets

    try:
        x_train, x_eval, y_train, y_eval = train_test_split(
            features,
            targets,
            test_size=0.2,
            random_state=42,
            stratify=stratify,
        )
    except ValueError:
        # Fallback for edge-case class distributions.
        return features, features, targets, targets, False

    return x_train, x_eval, y_train, y_eval, True


def train_task_model(dataset_path: Path, blueprint: AgentBlueprint) -> Tuple[Pipeline, TrainingSummary]:
    """Train a specialist task model from a CSV dataset."""

    dataframe = _load_dataset(dataset_path, blueprint)
    x_train, x_eval, y_train, y_eval, used_holdout = _split_data(
        dataframe,
        blueprint.input_column,
        blueprint.target_column,
        blueprint.task_type,
    )

    model = _build_pipeline(blueprint.task_type)
    model.fit(x_train, y_train)
    predictions = model.predict(x_eval)

    if blueprint.task_type == "classification":
        metric_name = "accuracy"
        metric_value = float(accuracy_score(y_eval, predictions))
    else:
        metric_name = "rmse"
        metric_value = float(np.sqrt(mean_squared_error(y_eval, predictions)))

    summary = TrainingSummary(
        total_rows=int(len(dataframe)),
        train_rows=int(len(x_train)),
        evaluation_rows=int(len(x_eval)),
        used_holdout_split=used_holdout,
        metric_name=metric_name,
        metric_value=metric_value,
        task_type=blueprint.task_type,
    )
    return model, summary
