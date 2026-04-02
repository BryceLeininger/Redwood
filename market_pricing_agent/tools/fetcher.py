"""Source fetching utilities for pricing comps."""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from io import StringIO
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlparse

import pandas as pd
import requests

from ..schemas import DataSource

_DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) RedwoodMarketPricingAgent/1.0",
    "Accept": "text/html,application/json,text/csv;q=0.9,*/*;q=0.8",
}


@dataclass(frozen=True)
class FetchedSource:
    source: DataSource
    payload: Any
    resolved_location: str


def _is_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"}


def _request_text(
    url: str,
    headers: dict[str, str],
    *,
    timeout: int = 30,
    max_retries: int = 3,
    backoff_seconds: float = 1.5,
) -> str:
    attempt = 0
    last_error: Optional[Exception] = None
    session = requests.Session()

    while attempt < max_retries:
        try:
            response = session.get(url, headers=headers, timeout=timeout)
            response.raise_for_status()
            response.encoding = response.encoding or "utf-8"
            return response.text
        except requests.RequestException as error:
            last_error = error
            attempt += 1
            if attempt >= max_retries:
                break
            time.sleep(backoff_seconds * (2 ** (attempt - 1)))

    detail = str(last_error) if last_error else "Unknown error"
    raise RuntimeError(f"Failed to fetch {url}: {detail}")


def fetch_source(source: DataSource) -> FetchedSource:
    headers = {**_DEFAULT_HEADERS, **source.headers}

    if source.source_type == "html":
        text = _read_text(source.location, headers)
        return FetchedSource(source=source, payload=text, resolved_location=source.location)

    if source.source_type == "csv":
        csv_text = _read_text(source.location, headers)
        dataframe = pd.read_csv(StringIO(csv_text))
        return FetchedSource(source=source, payload=dataframe, resolved_location=source.location)

    if source.source_type == "json":
        json_text = _read_text(source.location, headers)
        try:
            payload = json.loads(json_text)
        except json.JSONDecodeError as error:
            raise ValueError(f"Invalid JSON payload from {source.location}: {error}") from error
        return FetchedSource(source=source, payload=payload, resolved_location=source.location)

    raise ValueError(f"Unsupported source type: {source.source_type}")


def _read_text(location: str, headers: dict[str, str]) -> str:
    if _is_url(location):
        return _request_text(location, headers)
    return Path(location).read_text(encoding="utf-8")