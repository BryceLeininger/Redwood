"""FRED API interaction utilities."""
from __future__ import annotations

import time
from typing import Any, Dict, Optional

import pandas as pd
import requests

API_BASE_URL = "https://api.stlouisfed.org/fred/series/observations"


class FredAPIError(RuntimeError):
    """Raised when the FRED API cannot satisfy a request."""


def _build_params(
    series_id: str,
    api_key: str,
    start_date: Optional[str],
    end_date: Optional[str],
) -> Dict[str, str]:
    params: Dict[str, str] = {
        "series_id": series_id,
        "api_key": api_key,
        "file_type": "json",
        "observation_start": start_date or "",
        "observation_end": end_date or "",
        "sort_order": "asc",
    }
    # Remove empty optional parameters
    return {k: v for k, v in params.items() if v}


def fetch_observations(
    series_id: str,
    api_key: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    *,
    max_retries: int = 3,
    backoff_seconds: float = 1.5,
    session: Optional[requests.Session] = None,
) -> pd.DataFrame:
    """Fetch and normalize series observations from the FRED API."""

    if not series_id:
        raise ValueError("series_id must be provided")

    params = _build_params(series_id, api_key, start_date, end_date)
    attempt = 0
    last_error: Optional[Exception] = None
    http_session = session or requests.Session()

    while attempt < max_retries:
        try:
            response = http_session.get(API_BASE_URL, params=params, timeout=30)
            response.raise_for_status()
            payload: Dict[str, Any] = response.json()
            if "observations" not in payload:
                raise FredAPIError("Unexpected API response: missing 'observations' field")
            return _normalize_observations(payload, series_id)
        except (requests.RequestException, ValueError) as error:
            last_error = error
            attempt += 1
            if attempt >= max_retries:
                break
            delay = backoff_seconds * (2 ** (attempt - 1))
            time.sleep(delay)

    error_detail = str(last_error) if last_error else "Unknown error"
    raise FredAPIError(f"Failed to fetch data for series '{series_id}': {error_detail}")


def _normalize_observations(payload: Dict[str, Any], series_id: str) -> pd.DataFrame:
    observations = payload.get("observations", [])
    df = pd.DataFrame(observations)

    if df.empty:
        df = pd.DataFrame(columns=["date", "value", "realtime_start", "realtime_end"])

    df["value"] = pd.to_numeric(df.get("value"), errors="coerce")
    df["date"] = pd.to_datetime(df.get("date"), errors="coerce", format="%Y-%m-%d")
    df["realtime_start"] = pd.to_datetime(df.get("realtime_start"), errors="coerce")
    df["realtime_end"] = pd.to_datetime(df.get("realtime_end"), errors="coerce")

    df.insert(0, "series_id", series_id)
    df = df[["series_id", "date", "value", "realtime_start", "realtime_end"]]
    df = df.sort_values("date").reset_index(drop=True)

    return df
