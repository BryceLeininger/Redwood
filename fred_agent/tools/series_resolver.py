"""Series resolver utilities for FRED queries without LLM assistance."""
from __future__ import annotations

import calendar
import re
from dataclasses import dataclass
from datetime import date, datetime
from functools import lru_cache
from typing import Dict, Iterable, List, Optional, Pattern, Tuple

import requests

_SEARCH_ENDPOINT = "https://api.stlouisfed.org/fred/series/search"
_SERIES_ENDPOINT = "https://api.stlouisfed.org/fred/series"
_DATE_TOKEN = r"\d{4}(?:-\d{2}){0,2}"
_DEFAULT_SEARCH_LIMIT = 5


@dataclass(frozen=True)
class SeriesCandidate:
    """Normalized representation of a FRED series search result."""

    series_id: str
    title: str
    frequency: Optional[str] = None
    units: Optional[str] = None
    score: Optional[float] = None


@dataclass(frozen=True)
class Resolution:
    """Resolver output including detected dates and ranked candidates."""

    candidates: List[SeriesCandidate]
    start_date: Optional[str]
    end_date: Optional[str]
    raw_query: str
    cleaned_query: str


@dataclass(frozen=True)
class SeriesAliasEntry:
    series_id: str
    search_text: Optional[str] = None


@dataclass(frozen=True)
class CountyAliasEntry:
    county: str
    metric_phrase: str
    search_text: str


class SeriesResolutionError(RuntimeError):
    """Raised when the resolver cannot complete due to external factors."""


def parse_date_range(text: str) -> Tuple[Optional[str], Optional[str], str]:
    """Extract a date range from free-form text.

    Returns a tuple of (start_date, end_date, cleaned_text) where detected date
    phrases are removed from the text and dates are ISO formatted.
    """

    if not text:
        return None, None, ""

    original_text = text
    normalized = text.lower()

    def _strip_span(value: str, start: int, end: int) -> str:
        return f"{value[:start]} {value[end:]}"

    start_date: Optional[str] = None
    end_date: Optional[str] = None
    cleaned_text = original_text

    patterns = [
        re.compile(rf"from\s+({_DATE_TOKEN})\s+(?:to|-)\s+({_DATE_TOKEN})"),
        re.compile(rf"({_DATE_TOKEN})\s+(?:to)\s+({_DATE_TOKEN})"),
        re.compile(rf"({_DATE_TOKEN})\s*-\s*({_DATE_TOKEN})"),
    ]

    for pattern in patterns:
        match = pattern.search(normalized)
        if match:
            start_token = match.group(1)
            end_token = match.group(2)
            start_date = _normalize_start_date_token(start_token)
            end_date = _normalize_end_date_token(end_token)
            cleaned_text = _strip_span(cleaned_text, match.start(), match.end())
            normalized = _strip_span(normalized, match.start(), match.end())
            return start_date, end_date, _normalize_whitespace(cleaned_text)

    since_pattern = re.compile(rf"since\s+({_DATE_TOKEN})")
    match = since_pattern.search(normalized)
    if match:
        token = match.group(1)
        start_date = _normalize_start_date_token(token)
        cleaned_text = _strip_span(cleaned_text, match.start(), match.end())
        return start_date, None, _normalize_whitespace(cleaned_text)

    last_years_pattern = re.compile(r"last\s+(\d+)\s+years?")
    match = last_years_pattern.search(normalized)
    if match:
        years = int(match.group(1))
        if years > 0:
            today = date.today()
            start = _subtract_years(today, years)
            start_date = start.isoformat()
            end_date = today.isoformat()
            cleaned_text = _strip_span(cleaned_text, match.start(), match.end())
            return start_date, end_date, _normalize_whitespace(cleaned_text)

    return None, None, _normalize_whitespace(cleaned_text)


def resolve_series_candidates(
    query: str,
    api_key: str,
    *,
    limit: int = _DEFAULT_SEARCH_LIMIT,
) -> List[SeriesCandidate]:
    """Call the FRED search endpoint and return candidate series."""

    if not query.strip():
        return []

    params = {
        "search_text": query,
        "api_key": api_key,
        "file_type": "json",
        "limit": limit,
        "sort_order": "desc",
    }

    try:
        response = requests.get(_SEARCH_ENDPOINT, params=params, timeout=30)
        response.raise_for_status()
        payload = response.json()
    except requests.RequestException as error:
        raise SeriesResolutionError(f"FRED search request failed: {error}") from error

    series_items = payload.get("seriess", [])
    seen_ids: set[str] = set()
    candidates: List[SeriesCandidate] = []

    for item in series_items:
        series_id = item.get("id")
        if not series_id or series_id in seen_ids:
            continue
        seen_ids.add(series_id)
        score_raw = item.get("search_rank")
        score = float(score_raw) if isinstance(score_raw, (int, float, str)) and score_raw not in (None, "") else None
        candidates.append(
            SeriesCandidate(
                series_id=series_id,
                title=item.get("title", series_id),
                frequency=item.get("frequency"),
                units=item.get("units"),
                score=score,
            )
        )
        if len(candidates) >= limit:
            break

    return candidates


def resolve(query_text: str, api_key: str, *, limit: int = _DEFAULT_SEARCH_LIMIT) -> Resolution:
    """Resolve a free-form query into FRED series candidates and date bounds."""

    if not query_text.strip():
        raise ValueError("Please describe which FRED data you want.")

    start_date, end_date, cleaned_text = parse_date_range(query_text)
    normalized_cleaned = _normalize_query(cleaned_text)

    series_alias = _find_series_alias(normalized_cleaned)
    if series_alias:
        candidate = _get_candidate_for_series(series_alias.series_id, api_key)
        return Resolution(
            candidates=[candidate],
            start_date=start_date,
            end_date=end_date,
            raw_query=query_text.strip(),
            cleaned_query=cleaned_text.strip(),
        )

    county_alias = _find_county_alias(normalized_cleaned)
    if county_alias:
        candidates = resolve_series_candidates(county_alias.search_text, api_key, limit=limit)
        if not candidates:
            raise ValueError(f"No series found for {county_alias.search_text}.")
        ranked = _rank_county_candidates(candidates, county_alias)
        return Resolution(
            candidates=ranked,
            start_date=start_date,
            end_date=end_date,
            raw_query=query_text.strip(),
            cleaned_query=cleaned_text.strip() or county_alias.search_text,
        )

    search_text = cleaned_text.strip() or query_text.strip()
    normalized_search = _normalize_whitespace(search_text)
    if not normalized_search:
        raise ValueError("Unable to determine a search query. Please provide more detail.")

    candidates = resolve_series_candidates(normalized_search, api_key, limit=limit)
    if not candidates:
        raise ValueError("No FRED series matched the provided description.")

    return Resolution(
        candidates=candidates,
        start_date=start_date,
        end_date=end_date,
        raw_query=query_text.strip(),
        cleaned_query=normalized_search,
    )


def _normalize_query(text: str) -> str:
    cleaned = re.sub(r"[^\w\s]", " ", text.lower())
    return _normalize_whitespace(cleaned)


def _normalize_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _normalize_start_date_token(token: str) -> str:
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", token):
        return datetime.strptime(token, "%Y-%m-%d").date().isoformat()
    if re.fullmatch(r"\d{4}-\d{2}", token):
        year, month = map(int, token.split("-"))
        return date(year, month, 1).isoformat()
    if re.fullmatch(r"\d{4}", token):
        return f"{token}-01-01"
    raise ValueError(f"Unrecognized date token: {token}")


def _normalize_end_date_token(token: str) -> str:
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", token):
        return datetime.strptime(token, "%Y-%m-%d").date().isoformat()
    if re.fullmatch(r"\d{4}-\d{2}", token):
        year, month = map(int, token.split("-"))
        last_day = calendar.monthrange(year, month)[1]
        return date(year, month, last_day).isoformat()
    if re.fullmatch(r"\d{4}", token):
        return f"{token}-12-31"
    raise ValueError(f"Unrecognized date token: {token}")


def _subtract_years(value: date, years: int) -> date:
    try:
        return value.replace(year=value.year - years)
    except ValueError:
        # Handles February 29th by normalizing to February 28th.
        return value.replace(year=value.year - years, day=28)


@lru_cache(maxsize=128)
def _cached_series_metadata(series_id: str, api_key: str) -> SeriesCandidate:
    params = {
        "series_id": series_id,
        "api_key": api_key,
        "file_type": "json",
    }
    try:
        response = requests.get(_SERIES_ENDPOINT, params=params, timeout=30)
        response.raise_for_status()
        payload = response.json()
    except requests.RequestException as error:
        raise SeriesResolutionError(f"Failed to fetch metadata for {series_id}: {error}") from error

    series_list = payload.get("seriess", [])
    if not series_list:
        raise SeriesResolutionError(f"Metadata for series '{series_id}' not found.")

    entry = series_list[0]
    return SeriesCandidate(
        series_id=entry.get("id", series_id),
        title=entry.get("title", series_id),
        frequency=entry.get("frequency"),
        units=entry.get("units"),
    )


def _get_candidate_for_series(series_id: str, api_key: str) -> SeriesCandidate:
    try:
        return _cached_series_metadata(series_id, api_key)
    except SeriesResolutionError:
        raise
    except RuntimeError as error:  # pragma: no cover - safeguard
        raise SeriesResolutionError(str(error)) from error


def _build_series_alias_patterns() -> List[Tuple[Pattern[str], SeriesAliasEntry]]:
    alias_sources: Dict[str, Tuple[str, Optional[str]]] = {
        "mortgage rate": ("MORTGAGE30US", None),
        "mortgage rates": ("MORTGAGE30US", None),
        "30 year mortgage": ("MORTGAGE30US", None),
        "30y mortgage": ("MORTGAGE30US", None),
        "15 year mortgage": ("MORTGAGE15US", None),
        "15y mortgage": ("MORTGAGE15US", None),
        "fed funds": ("FEDFUNDS", None),
        "federal funds": ("FEDFUNDS", None),
        "cpi": ("CPIAUCSL", None),
        "inflation": ("CPIAUCSL", None),
        "unemployment": ("UNRATE", None),
        "unemployment rate": ("UNRATE", None),
        "10 year treasury": ("DGS10", None),
        "10y treasury": ("DGS10", None),
        "2 year treasury": ("DGS2", None),
        "2y treasury": ("DGS2", None),
        "prime rate": ("DPRIME", None),
    }

    items: List[Tuple[str, Pattern[str], SeriesAliasEntry]] = []
    for phrase, (series_id, search_text) in alias_sources.items():
        normalized = _normalize_query(phrase)
        if not normalized:
            continue
        pattern = _compile_alias_pattern(normalized)
        items.append((normalized, pattern, SeriesAliasEntry(series_id=series_id, search_text=search_text)))

    items.sort(key=lambda item: len(item[0]), reverse=True)
    return [(pattern, entry) for _, pattern, entry in items]


def _build_county_alias_patterns() -> List[Tuple[Pattern[str], CountyAliasEntry]]:
    counties = [
        "Alameda",
        "Contra Costa",
        "Marin",
        "Napa",
        "San Francisco",
        "San Mateo",
        "Santa Clara",
        "Solano",
        "Sonoma",
        "Sacramento",
        "Placer",
        "El Dorado",
        "Yolo",
        "Sutter",
        "Yuba",
        "San Joaquin",
        "Stanislaus",
        "Merced",
        "Fresno",
        "Kings",
        "Tulare",
        "Madera",
        "Kern",
    ]

    metric_definitions = [
        {
            "phrases": [
                "median income",
                "median household income",
                "median household income",
                "mhi",
            ],
            "template": "Median Household Income in {county} County, CA",
            "metric_phrase": "Median Household Income",
        },
        {
            "phrases": [
                "population",
                "resident population",
            ],
            "template": "Resident Population in {county} County, CA",
            "metric_phrase": "Resident Population",
        },
        {
            "phrases": [
                "housing prices",
                "house prices",
                "housing price index",
                "house price index",
                "hpi",
            ],
            "template": "All-Transactions House Price Index for {county} County, CA",
            "metric_phrase": "House Price Index",
        },
    ]

    entries: List[Tuple[str, Pattern[str], CountyAliasEntry]] = []

    for county in counties:
        county_forms = _generate_county_forms(county)
        for metric in metric_definitions:
            template = metric["template"].format(county=county)
            metric_phrase = metric["metric_phrase"]
            phrases = metric["phrases"]
            alias = CountyAliasEntry(county=county, metric_phrase=metric_phrase, search_text=template)
            phrase_forms = _generate_phrase_forms(phrases)

            for phrase_form in phrase_forms:
                for county_form in county_forms:
                    combinations = _generate_combined_forms(phrase_form, county_form)
                    for combo in combinations:
                        normalized = _normalize_query(combo)
                        if not normalized:
                            continue
                        pattern = _compile_alias_pattern(normalized)
                        entries.append((normalized, pattern, alias))

    entries.sort(key=lambda item: len(item[0]), reverse=True)
    return [(pattern, alias) for _, pattern, alias in entries]


def _generate_phrase_forms(phrases: Iterable[str]) -> List[str]:
    forms: List[str] = []
    for phrase in phrases:
        normalized = _normalize_query(phrase)
        if normalized:
            forms.append(normalized)
    return forms


def _generate_county_forms(county: str) -> List[str]:
    base = _normalize_query(county)
    components = [
        base,
        f"{base} county",
        f"{base} county ca",
        f"{base} county california",
        f"{base} ca",
        f"{base} california",
    ]
    return components


def _generate_combined_forms(phrase: str, county: str) -> List[str]:
    return [
        f"{phrase} {county}",
        f"{phrase} in {county}",
        f"{phrase} for {county}",
        f"{county} {phrase}",
        f"{county} for {phrase}",
        f"{county} {phrase} ca",
    ]


def _compile_alias_pattern(normalized_phrase: str) -> Pattern[str]:
    parts = [re.escape(part) for part in normalized_phrase.split()]
    pattern = r"\b" + r"\s+".join(parts) + r"\b"
    return re.compile(pattern)


_SERIES_ALIAS_PATTERNS = _build_series_alias_patterns()
_COUNTY_ALIAS_PATTERNS = _build_county_alias_patterns()


def _find_series_alias(normalized_text: str) -> Optional[SeriesAliasEntry]:
    for pattern, alias in _SERIES_ALIAS_PATTERNS:
        if pattern.search(normalized_text):
            return alias
    return None


def _find_county_alias(normalized_text: str) -> Optional[CountyAliasEntry]:
    for pattern, alias in _COUNTY_ALIAS_PATTERNS:
        if pattern.search(normalized_text):
            return alias
    return None


def _rank_county_candidates(
    candidates: List[SeriesCandidate],
    alias: CountyAliasEntry,
) -> List[SeriesCandidate]:
    target_county = f"{alias.county} County, CA".lower()
    metric_phrase = alias.metric_phrase.lower()

    def rank(item: Tuple[int, SeriesCandidate]) -> Tuple[int, int]:
        index, candidate = item
        title_lower = candidate.title.lower()
        score = 0
        if target_county in title_lower:
            score -= 100
        if metric_phrase in title_lower:
            score -= 10
        return score, index

    ordered = sorted(enumerate(candidates), key=rank)
    return [candidate for _, candidate in ordered]
