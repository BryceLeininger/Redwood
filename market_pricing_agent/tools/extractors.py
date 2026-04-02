"""Normalization and extraction logic for pricing comps."""
from __future__ import annotations

import json
import re
from datetime import date
from typing import Any, Dict, Iterable, List, Sequence

import pandas as pd
from bs4 import BeautifulSoup

from ..schemas import ComparableRecord, DataSource
from .fetcher import FetchedSource

_MONEY_VALUE_RE = re.compile(r"\$\s*([\d,]+(?:\.\d+)?)")
_SQFT_RANGE_RE = re.compile(
    r"(\d{3,5}(?:,\d{3})?(?:\.\d+)?)\s*(?:-|to)\s*(\d{3,5}(?:,\d{3})?(?:\.\d+)?)\s*(?:sq\.?\s*ft|sqft|square feet)",
    flags=re.IGNORECASE,
)
_SQFT_SINGLE_RE = re.compile(
    r"(\d{3,5}(?:,\d{3})?(?:\.\d+)?)\s*(?:sq\.?\s*ft|sqft|square feet)",
    flags=re.IGNORECASE,
)
_FIELD_ALIASES = {
    "price": ["price", "list_price", "asking_price", "close_price", "sale_price", "sold_price", "current_price"],
    "price_low": ["price_low", "min_price", "starting_price", "low_price", "from_price"],
    "price_high": ["price_high", "max_price", "ending_price", "high_price", "to_price"],
    "living_area_sqft": ["living_area_sqft", "sqft", "square_feet", "living_sqft", "livingarea", "area"],
    "sqft_low": ["sqft_low", "min_sqft", "from_sqft", "low_sqft"],
    "sqft_high": ["sqft_high", "max_sqft", "to_sqft", "high_sqft"],
    "address": ["address", "street_address", "property_address", "full_address"],
    "community_name": ["community_name", "community", "subdivision", "neighborhood", "development", "project", "name"],
    "sale_date": ["sale_date", "close_date", "closed_on", "closed_date", "sold_date", "contract_date"],
    "submarket": ["submarket", "market_area"],
    "bedrooms": ["bedrooms", "beds", "bed"],
    "bathrooms": ["bathrooms", "baths", "bath"],
    "year_built": ["year_built", "built_year", "yearbuilt"],
    "notes": ["notes", "remarks", "description", "summary"],
}


def extract_records(fetched: FetchedSource) -> List[ComparableRecord]:
    source = fetched.source
    if source.source_type == "csv":
        dataframe = fetched.payload
        if not isinstance(dataframe, pd.DataFrame):
            raise ValueError("CSV source did not resolve to a DataFrame.")
        return _deduplicate_records(_normalize_tabular_rows(dataframe.to_dict(orient="records"), source))

    if source.source_type == "json":
        return _deduplicate_records(_extract_json_records(source, fetched.payload))

    html = fetched.payload
    if not isinstance(html, str):
        raise ValueError("HTML source did not resolve to text.")
    return _deduplicate_records(_extract_html_records(source, html))


def _extract_json_records(source: DataSource, payload: Any) -> List[ComparableRecord]:
    if isinstance(payload, list):
        rows = [item for item in payload if isinstance(item, dict)]
        return _normalize_tabular_rows(rows, source)

    if isinstance(payload, dict):
        for key in ("records", "items", "data", "results"):
            maybe_rows = payload.get(key)
            if isinstance(maybe_rows, list):
                rows = [item for item in maybe_rows if isinstance(item, dict)]
                return _normalize_tabular_rows(rows, source)

        flattened_rows = []
        for item in _walk_json_dicts(payload):
            row = _flatten_ld_item(item)
            if row:
                flattened_rows.append(row)
        normalized = _normalize_tabular_rows(flattened_rows, source)
        if normalized:
            return normalized

        if any(key in payload for key in ("price", "price_low", "price_high", "close_price", "sale_price")):
            return _normalize_tabular_rows([payload], source)

    raise ValueError(f"JSON source '{source.name}' did not contain any usable records.")


def _extract_html_records(source: DataSource, html: str) -> List[ComparableRecord]:
    soup = BeautifulSoup(html, "html.parser")

    table_rows = _extract_table_rows(soup)
    if table_rows:
        normalized_table_rows = _normalize_tabular_rows(table_rows, source)
        if normalized_table_rows:
            return normalized_table_rows

    ld_rows = []
    for script in soup.find_all("script", attrs={"type": re.compile("ld\+json", flags=re.IGNORECASE)}):
        raw_text = script.string or script.get_text(strip=True)
        if not raw_text:
            continue
        try:
            parsed = json.loads(raw_text)
        except json.JSONDecodeError:
            continue
        for item in _walk_json_dicts(parsed):
            row = _flatten_ld_item(item)
            if row:
                ld_rows.append(row)

    normalized_ld_rows = _normalize_tabular_rows(ld_rows, source)
    if normalized_ld_rows:
        return normalized_ld_rows

    summary = _extract_text_summary(source, soup)
    if summary is None:
        return []
    return [summary]


def _extract_table_rows(soup: BeautifulSoup) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for table in soup.find_all("table"):
        header_cells = table.find_all("th")
        headers = [_clean_header(cell.get_text(" ", strip=True)) for cell in header_cells]
        if not headers:
            first_row = table.find("tr")
            if first_row:
                headers = [_clean_header(cell.get_text(" ", strip=True)) for cell in first_row.find_all(["td", "th"])]
        if not headers:
            continue

        for tr in table.find_all("tr"):
            values = [cell.get_text(" ", strip=True) for cell in tr.find_all("td")]
            if not values or len(values) != len(headers):
                continue
            row = {header: value for header, value in zip(headers, values)}
            rows.append(row)
    return rows


def _clean_header(value: str) -> str:
    return value.strip().lower().replace(" ", "_")


def _flatten_ld_item(item: Dict[str, Any]) -> Dict[str, Any] | None:
    offer = item.get("offers") if isinstance(item.get("offers"), dict) else {}
    context_name = _coerce_text(item.get("name")) or _coerce_text(offer.get("name"))
    context_address = _format_address(item.get("address")) or _format_address(offer.get("address"))
    living_area_sqft = _extract_floor_size(item.get("floorSize")) or _extract_floor_size(offer.get("floorSize"))
    row = {
        "community_name": context_name,
        "address": context_address,
        "price": _extract_number(item.get("price")) or _extract_number(offer.get("price")),
        "price_low": _extract_number(item.get("lowPrice")) or _extract_number(offer.get("lowPrice")),
        "price_high": _extract_number(item.get("highPrice")) or _extract_number(offer.get("highPrice")),
        "living_area_sqft": living_area_sqft,
        "sqft_low": _extract_number(item.get("minValue")),
        "sqft_high": _extract_number(item.get("maxValue")),
        "bedrooms": _extract_number(item.get("numberOfBedrooms")) or _extract_number(item.get("numberOfRooms")),
        "bathrooms": _extract_number(item.get("numberOfBathroomsTotal")) or _extract_number(item.get("numberOfBathrooms")),
        "sale_date": _coerce_text(item.get("soldDate")) or _coerce_text(item.get("datePosted")),
        "year_built": _extract_int(item.get("yearBuilt")),
        "notes": _coerce_text(item.get("description")),
    }

    if not any(row.get(field) for field in ("price", "price_low", "price_high")):
        return None
    if not any((context_name, context_address, living_area_sqft, row["sqft_low"], row["sqft_high"])):
        return None
    return row


def _extract_text_summary(source: DataSource, soup: BeautifulSoup) -> ComparableRecord | None:
    raw_text = soup.get_text(" ", strip=True)
    prices = _extract_money_values(raw_text)
    sqfts = _extract_sqft_values(raw_text)
    if not prices:
        return None

    title = _coerce_text(source.name)
    heading = soup.find(["h1", "title"])
    if heading:
        title = heading.get_text(" ", strip=True) or title

    return ComparableRecord(
        source_name=source.name,
        source_kind=source.kind,
        record_name=title,
        submarket=source.submarket,
        address=None,
        price=None if len(prices) > 1 else prices[0],
        price_low=min(prices) if len(prices) > 1 else None,
        price_high=max(prices) if len(prices) > 1 else None,
        living_area_sqft=None if len(sqfts) != 1 else sqfts[0],
        sqft_low=min(sqfts) if len(sqfts) > 1 else None,
        sqft_high=max(sqfts) if len(sqfts) > 1 else None,
        is_new_construction=source.kind == "community",
        extracted_from=source.location,
        notes="summary extracted from html text",
    )


def _normalize_tabular_rows(rows: Sequence[Dict[str, Any]], source: DataSource) -> List[ComparableRecord]:
    normalized_records: List[ComparableRecord] = []

    for row in rows:
        if not isinstance(row, dict):
            continue
        normalized_map = {_canonicalize(key): value for key, value in row.items()}
        field_values = {
            target: _resolve_field_value(normalized_map, source, target)
            for target in _FIELD_ALIASES
        }

        effective_price = _parse_money(field_values["price"])
        price_low = _parse_money(field_values["price_low"])
        price_high = _parse_money(field_values["price_high"])
        if effective_price is None and price_low is None and price_high is None:
            continue

        living_area_sqft = _parse_number(field_values["living_area_sqft"])
        sqft_low = _parse_number(field_values["sqft_low"])
        sqft_high = _parse_number(field_values["sqft_high"])

        record_name = _coerce_text(field_values["community_name"]) or _coerce_text(field_values["address"]) or source.name
        normalized_records.append(
            ComparableRecord(
                source_name=source.name,
                source_kind=source.kind,
                record_name=record_name,
                submarket=_coerce_text(field_values["submarket"]) or source.submarket,
                address=_coerce_text(field_values["address"]),
                price=effective_price,
                price_low=price_low,
                price_high=price_high,
                living_area_sqft=living_area_sqft,
                sqft_low=sqft_low,
                sqft_high=sqft_high,
                bedrooms=_parse_number(field_values["bedrooms"]),
                bathrooms=_parse_number(field_values["bathrooms"]),
                sale_date=_parse_date(field_values["sale_date"]),
                year_built=_extract_int(field_values["year_built"]),
                is_new_construction=source.kind == "community",
                extracted_from=source.location,
                notes=_coerce_text(field_values["notes"]) or "",
            )
        )

    return normalized_records


def _resolve_field_value(normalized_map: Dict[str, Any], source: DataSource, target: str) -> Any:
    override = source.field_map.get(target)
    if override:
        return normalized_map.get(_canonicalize(override))

    for alias in _FIELD_ALIASES[target]:
        value = normalized_map.get(_canonicalize(alias))
        if value not in (None, ""):
            return value
    return None


def _canonicalize(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.strip().lower())


def _parse_money(value: Any) -> float | None:
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        numeric = float(value)
        return numeric if 50_000 <= numeric <= 20_000_000 else None

    text = str(value)
    match = _MONEY_VALUE_RE.search(text)
    if match:
        numeric = float(match.group(1).replace(",", ""))
        return numeric if 50_000 <= numeric <= 20_000_000 else None

    digits = re.sub(r"[^\d.]", "", text)
    if not digits:
        return None
    numeric = float(digits)
    return numeric if 50_000 <= numeric <= 20_000_000 else None


def _parse_number(value: Any) -> float | None:
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value)
    digits = re.sub(r"[^\d.]", "", text)
    if not digits:
        return None
    return float(digits)


def _extract_int(value: Any) -> int | None:
    parsed = _parse_number(value)
    if parsed is None:
        return None
    return int(parsed)


def _parse_date(value: Any) -> date | None:
    if value in (None, ""):
        return None
    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        return None
    return parsed.date()


def _extract_money_values(text: str) -> List[float]:
    values = []
    for match in _MONEY_VALUE_RE.finditer(text):
        numeric = float(match.group(1).replace(",", ""))
        if 50_000 <= numeric <= 20_000_000:
            values.append(numeric)
    return sorted(set(values))


def _extract_sqft_values(text: str) -> List[float]:
    values: List[float] = []
    for match in _SQFT_RANGE_RE.finditer(text):
        low = float(match.group(1).replace(",", ""))
        high = float(match.group(2).replace(",", ""))
        if 500 <= low <= 10_000:
            values.append(low)
        if 500 <= high <= 10_000:
            values.append(high)
    for match in _SQFT_SINGLE_RE.finditer(text):
        numeric = float(match.group(1).replace(",", ""))
        if 500 <= numeric <= 10_000:
            values.append(numeric)
    return sorted(set(values))


def _extract_number(value: Any) -> float | None:
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value)
    digits = re.sub(r"[^\d.]", "", text)
    if not digits:
        return None
    return float(digits)


def _extract_floor_size(value: Any) -> float | None:
    if value in (None, ""):
        return None
    if isinstance(value, dict):
        nested = value.get("value") or value.get("maxValue") or value.get("minValue")
        return _extract_number(nested)
    return _extract_number(value)


def _coerce_text(value: Any) -> str | None:
    if value in (None, ""):
        return None
    text = str(value).strip()
    return text or None


def _format_address(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value.strip() or None
    if isinstance(value, dict):
        parts = []
        for key in ("streetAddress", "addressLocality", "addressRegion", "postalCode"):
            segment = value.get(key)
            if segment:
                parts.append(str(segment).strip())
        return ", ".join(part for part in parts if part) or None
    return None


def _walk_json_dicts(value: Any) -> Iterable[Dict[str, Any]]:
    if isinstance(value, dict):
        yield value
        for nested in value.values():
            yield from _walk_json_dicts(nested)
    elif isinstance(value, list):
        for item in value:
            yield from _walk_json_dicts(item)


def _deduplicate_records(records: Sequence[ComparableRecord]) -> List[ComparableRecord]:
    unique: List[ComparableRecord] = []
    seen = set()
    for record in records:
        key = (
            record.source_name.lower(),
            record.record_name.lower(),
            record.address or "",
            round(record.effective_price or 0.0, 2),
            round(record.effective_sqft or 0.0, 2),
            record.sale_date.isoformat() if record.sale_date else "",
        )
        if key in seen:
            continue
        seen.add(key)
        unique.append(record)
    return unique