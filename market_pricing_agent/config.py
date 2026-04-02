"""Configuration loading for the market pricing agent."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, List
from urllib.parse import urlparse

from .schemas import DataSource, SubjectProject


def _is_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"}


def _load_json(file_path: Path) -> Any:
    try:
        return json.loads(file_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ValueError(f"Invalid JSON in {file_path}: {error}") from error


def load_project_config(project_config_path: Path | str) -> SubjectProject:
    path = Path(project_config_path).resolve()
    payload = _load_json(path)

    project = SubjectProject(
        name=str(payload.get("name", "")).strip(),
        submarket=str(payload.get("submarket", "")).strip(),
        product_type=str(payload.get("product_type", "single_family_detached")).strip(),
        avg_living_area_sqft=float(payload.get("avg_living_area_sqft", 0) or 0),
        quality_tier=str(payload.get("quality_tier", "market")).strip(),
        target_position=str(payload.get("target_position", payload.get("quality_tier", "market"))).strip(),
        bedrooms=_to_optional_float(payload.get("bedrooms")),
        bathrooms=_to_optional_float(payload.get("bathrooms")),
        garage_spaces=_to_optional_float(payload.get("garage_spaces")),
        lot_width_ft=_to_optional_float(payload.get("lot_width_ft")),
        notes=str(payload.get("notes", "")).strip(),
    )
    project.validate()
    return project


def load_sources_config(sources_config_path: Path | str) -> List[DataSource]:
    path = Path(sources_config_path).resolve()
    payload = _load_json(path)
    raw_sources = payload.get("sources", payload)
    if not isinstance(raw_sources, list) or not raw_sources:
        raise ValueError("Sources config must contain a non-empty 'sources' list.")

    default_submarket = str(payload.get("submarket", "")).strip() if isinstance(payload, dict) else ""
    base_dir = path.parent

    resolved_sources: List[DataSource] = []
    for item in raw_sources:
        if not isinstance(item, dict):
            raise ValueError("Each source entry must be a JSON object.")

        raw_location = str(item.get("location", "")).strip()
        if not raw_location:
            raise ValueError("Every source requires a location.")
        if _is_url(raw_location):
            location = raw_location
        else:
            location = str((base_dir / raw_location).resolve())

        source = DataSource(
            name=str(item.get("name", "")).strip(),
            kind=str(item.get("kind", "")).strip(),
            source_type=str(item.get("source_type", "")).strip(),
            location=location,
            submarket=str(item.get("submarket", default_submarket)).strip(),
            field_map={str(key): str(value) for key, value in dict(item.get("field_map", {})).items()},
            headers={str(key): str(value) for key, value in dict(item.get("headers", {})).items()},
        )
        source.validate()
        resolved_sources.append(source)

    return resolved_sources


def _to_optional_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    return float(value)