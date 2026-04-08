"""Storage utilities for persisting FRED observations."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Tuple

import pandas as pd

_TIMESTAMP_FORMAT = "%Y%m%d_%H%M%S"


def save_raw_csv(data: pd.DataFrame, series_id: str, destination: Path) -> Path:
    """Persist observations to a timestamped CSV under the raw outputs directory."""

    destination.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.utcnow().strftime(_TIMESTAMP_FORMAT)
    safe_series = series_id.replace("/", "-").replace(" ", "_")
    filename = f"{safe_series}_{timestamp}.csv"
    output_path = destination / filename
    data.to_csv(output_path, index=False)
    return output_path


def update_master_dataset(data: pd.DataFrame, master_path: Path) -> Tuple[Path, int]:
    """Append observations to the master dataset, creating it when absent."""

    master_path.parent.mkdir(parents=True, exist_ok=True)

    if master_path.exists():
        existing = pd.read_csv(master_path, parse_dates=["date", "realtime_start", "realtime_end"])
        combined = pd.concat([existing, data], ignore_index=True)
        combined = combined.drop_duplicates(subset=["series_id", "date"]).sort_values("date")
    else:
        combined = data.sort_values("date")

    combined.to_csv(master_path, index=False)
    return master_path, len(combined)
