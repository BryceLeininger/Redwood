"""Workflow for screening residential subdivision parcels and monitoring planning activity."""
from __future__ import annotations

import csv
import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from html import unescape
from pathlib import Path
from typing import Any, Dict, Iterable, List, Sequence
from urllib.parse import quote_plus, urlparse
from xml.etree import ElementTree as ET

import requests

from .specialist_agent import SpecialistAgent

SEARCH_TIMEOUT_SECONDS = 20
DEFAULT_USER_AGENT = "RedwoodSubdivisionScout/1.0"

POSITIVE_SIGNALS: Dict[str, int] = {
    "by right": 10,
    "entitled": 16,
    "tentative map approved": 16,
    "vesting tentative map": 12,
    "adjacent to existing subdivision": 10,
    "utilities at site": 12,
    "utilities stubbed": 10,
    "shovel ready": 18,
    "growth corridor": 10,
    "strong builder interest": 10,
    "strong school demand": 8,
    "infill": 10,
    "subdivision": 8,
    "single family": 8,
    "townhome": 6,
    "completed traffic study": 6,
    "arterial frontage": 6,
    "sewer nearby": 6,
    "water nearby": 6,
    "existing utilities": 10,
    "finished lots": 18,
    "lot take down": 8,
}

RISK_SIGNALS: Dict[str, int] = {
    "floodplain": 18,
    "wetlands": 16,
    "mitigation": 8,
    "brownfield": 20,
    "remediation": 18,
    "annexation": 14,
    "septic": 14,
    "raw land": 10,
    "no sewer": 18,
    "utility extension": 14,
    "rezone": 14,
    "zoning variance": 10,
    "entitlement risk": 14,
    "steep": 12,
    "grading": 10,
    "retaining wall": 12,
    "environmental review": 10,
    "offsite improvement": 10,
    "endangered species": 18,
    "title issue": 14,
    "easement": 8,
    "fire flow": 8,
    "litigation": 18,
    "high impact fees": 8,
}

APPROVED_QUERY_TEMPLATES = [
    '"{jurisdiction}" "tentative map" approved',
    '"{jurisdiction}" "vesting tentative map" approved',
    '"{jurisdiction}" subdivision approved "planning commission"',
]

UPCOMING_QUERY_TEMPLATES = [
    '"{jurisdiction}" "tentative map" agenda',
    '"{jurisdiction}" subdivision "planning commission" agenda',
    '"{jurisdiction}" "recommended approval" subdivision',
]


@dataclass(frozen=True)
class ParcelScreeningResult:
    parcel_id: str
    market: str
    priority_score: float
    recommendation: str
    model_prediction: str
    model_confidence: float | None
    positive_signals: List[str]
    risk_signals: List[str]
    rationale: str
    source_text: str
    top_classes: List[Dict[str, Any]]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PlanningWatchItem:
    stage: str
    jurisdiction: str
    title: str
    url: str
    source_domain: str
    published_at: str | None
    snippet: str
    matched_query: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _clean_text(value: str) -> str:
    text = unescape(value or "")
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _parse_pub_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError, IndexError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _default_market(row: Dict[str, str], parcel_id: str) -> str:
    for key in ("market", "jurisdiction", "city", "county", "state"):
        value = (row.get(key) or "").strip()
        if value:
            return value
    return parcel_id


def _compose_parcel_text(row: Dict[str, str]) -> str:
    ordered_keys = [
        "description",
        "zoning",
        "status",
        "utilities",
        "notes",
        "market",
        "jurisdiction",
        "city",
        "county",
        "state",
        "acres",
        "planned_lots",
        "density",
    ]
    parts: List[str] = []
    seen = set()
    for key in ordered_keys:
        value = (row.get(key) or "").strip()
        if value:
            seen.add(key)
            parts.append(value)
    for key, raw_value in row.items():
        if key in seen:
            continue
        value = (raw_value or "").strip()
        if value:
            parts.append(value)
    return " | ".join(parts).strip()


def _extract_signal_hits(text: str, catalog: Dict[str, int]) -> List[str]:
    lowered = text.lower()
    hits = [phrase for phrase in catalog if phrase in lowered]
    return sorted(hits, key=lambda phrase: (-catalog[phrase], phrase))


def _estimate_priority_score(
    model_prediction: str,
    model_confidence: float | None,
    positive_hits: Sequence[str],
    risk_hits: Sequence[str],
) -> float:
    baseline = {
        "high_probability": 72.0,
        "medium_probability": 52.0,
        "low_probability": 24.0,
    }.get(model_prediction, 50.0)

    confidence_bonus = 0.0
    if model_confidence is not None:
        confidence_bonus = max(0.0, min(model_confidence, 1.0)) * 14.0

    positive_bonus = sum(POSITIVE_SIGNALS[item] for item in positive_hits[:4]) / 2.5
    risk_penalty = sum(RISK_SIGNALS[item] for item in risk_hits[:4]) / 2.2

    score = baseline + confidence_bonus + positive_bonus - risk_penalty
    return round(max(0.0, min(100.0, score)), 1)


def _recommendation_from_score(score: float) -> str:
    if score >= 70:
        return "prioritize"
    if score >= 50:
        return "watch"
    return "pass"


def _build_rationale(
    recommendation: str,
    positive_hits: Sequence[str],
    risk_hits: Sequence[str],
    prediction: str,
) -> str:
    fragments: List[str] = [f"Model signal: {prediction.replace('_', ' ')}."]
    if positive_hits:
        fragments.append("Upside: " + ", ".join(positive_hits[:3]) + ".")
    if risk_hits:
        fragments.append("Risks: " + ", ".join(risk_hits[:3]) + ".")
    if recommendation == "prioritize":
        fragments.append("This parcel looks actionable for residential subdivision pursuit.")
    elif recommendation == "watch":
        fragments.append("This parcel needs targeted diligence before active pursuit.")
    else:
        fragments.append("This parcel carries enough entitlement or infrastructure risk to deprioritize.")
    return " ".join(fragments)


class SubdivisionScout:
    """Operational agent that ranks parcels and monitors planning approvals."""

    def __init__(self, specialist: SpecialistAgent) -> None:
        self.specialist = specialist

    @classmethod
    def from_agent_dir(cls, agent_dir: Path | str) -> "SubdivisionScout":
        return cls(SpecialistAgent.load(agent_dir))

    def screen_parcel_text(self, text: str, parcel_id: str = "parcel-1", market: str = "unknown") -> Dict[str, Any]:
        payload = {"parcel_id": parcel_id, "market": market, "description": text}
        return self.screen_parcel_rows([payload])[0]

    def screen_parcel_rows(self, rows: Iterable[Dict[str, str]]) -> List[Dict[str, Any]]:
        results: List[ParcelScreeningResult] = []
        for index, row in enumerate(rows, start=1):
            parcel_id = (row.get("parcel_id") or row.get("id") or f"parcel-{index}").strip()
            market = _default_market(row, parcel_id)
            source_text = _compose_parcel_text(row)
            if not source_text:
                continue

            model_result = self.specialist.predict(source_text)
            top_classes = model_result.get("top_classes", [])
            model_prediction = str(model_result.get("prediction", "")).strip()
            model_confidence = None
            for item in top_classes:
                if str(item.get("label")) == model_prediction:
                    try:
                        model_confidence = float(item.get("confidence"))
                    except (TypeError, ValueError):
                        model_confidence = None
                    break

            positive_hits = _extract_signal_hits(source_text, POSITIVE_SIGNALS)
            risk_hits = _extract_signal_hits(source_text, RISK_SIGNALS)
            priority_score = _estimate_priority_score(model_prediction, model_confidence, positive_hits, risk_hits)
            recommendation = _recommendation_from_score(priority_score)
            rationale = _build_rationale(recommendation, positive_hits, risk_hits, model_prediction)

            results.append(
                ParcelScreeningResult(
                    parcel_id=parcel_id,
                    market=market,
                    priority_score=priority_score,
                    recommendation=recommendation,
                    model_prediction=model_prediction,
                    model_confidence=model_confidence,
                    positive_signals=positive_hits,
                    risk_signals=risk_hits,
                    rationale=rationale,
                    source_text=source_text,
                    top_classes=top_classes,
                )
            )

        ranked = sorted(results, key=lambda item: (-item.priority_score, item.parcel_id.lower()))
        return [item.to_dict() for item in ranked]

    def screen_parcel_file(self, parcel_file: Path | str) -> List[Dict[str, Any]]:
        path = Path(parcel_file)
        if not path.exists():
            raise ValueError(f"Parcel file was not found: {path}")
        if path.suffix.lower() != ".csv":
            raise ValueError("Parcel file must be a CSV file.")

        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            if not reader.fieldnames:
                raise ValueError("Parcel CSV is missing a header row.")
            rows = [{key.strip(): (value or "").strip() for key, value in row.items()} for row in reader]
        return self.screen_parcel_rows(rows)

    def watch_planning_activity(
        self,
        jurisdictions: Sequence[str],
        lookback_days: int = 45,
        max_results_per_query: int = 6,
    ) -> Dict[str, Any]:
        cleaned_jurisdictions = [item.strip() for item in jurisdictions if item and item.strip()]
        if not cleaned_jurisdictions:
            raise ValueError("At least one jurisdiction is required for planning activity monitoring.")

        lookback_days = max(1, lookback_days)
        max_results_per_query = max(1, max_results_per_query)
        cutoff = datetime.now(timezone.utc) - timedelta(days=lookback_days)

        approved_recently = self._search_stage(
            stage="approved_recently",
            jurisdictions=cleaned_jurisdictions,
            query_templates=APPROVED_QUERY_TEMPLATES,
            cutoff=cutoff,
            max_results_per_query=max_results_per_query,
        )
        approaching_approval = self._search_stage(
            stage="approaching_approval",
            jurisdictions=cleaned_jurisdictions,
            query_templates=UPCOMING_QUERY_TEMPLATES,
            cutoff=cutoff,
            max_results_per_query=max_results_per_query,
        )

        return {
            "agent": self.specialist.metadata["blueprint"]["name"],
            "lookback_days": lookback_days,
            "jurisdictions": cleaned_jurisdictions,
            "approved_recently": [item.to_dict() for item in approved_recently],
            "approaching_approval": [item.to_dict() for item in approaching_approval],
        }

    def _search_stage(
        self,
        stage: str,
        jurisdictions: Sequence[str],
        query_templates: Sequence[str],
        cutoff: datetime,
        max_results_per_query: int,
    ) -> List[PlanningWatchItem]:
        items: List[PlanningWatchItem] = []
        seen = set()
        for jurisdiction in jurisdictions:
            for template in query_templates:
                query = template.format(jurisdiction=jurisdiction)
                for result in self._search_rss(query, max_results=max_results_per_query):
                    dedupe_key = (stage, result["url"].lower())
                    if dedupe_key in seen:
                        continue
                    seen.add(dedupe_key)

                    published_at = _parse_pub_date(result.get("published_at"))
                    if published_at and published_at < cutoff:
                        continue

                    url = result["url"]
                    items.append(
                        PlanningWatchItem(
                            stage=stage,
                            jurisdiction=jurisdiction,
                            title=result["title"],
                            url=url,
                            source_domain=urlparse(url).netloc.lower(),
                            published_at=published_at.isoformat() if published_at else None,
                            snippet=result["snippet"],
                            matched_query=query,
                        )
                    )

        items.sort(
            key=lambda item: (
                item.published_at or "",
                item.jurisdiction.lower(),
                item.title.lower(),
            ),
            reverse=True,
        )
        return items

    def _search_rss(self, query: str, max_results: int) -> List[Dict[str, str]]:
        url = f"https://www.bing.com/search?format=rss&q={quote_plus(query)}&count={max_results}"
        response = requests.get(
            url,
            timeout=SEARCH_TIMEOUT_SECONDS,
            headers={"User-Agent": DEFAULT_USER_AGENT},
        )
        response.raise_for_status()

        root = ET.fromstring(response.content)
        items: List[Dict[str, str]] = []
        for item in root.findall("./channel/item"):
            title = _clean_text(item.findtext("title", default=""))
            link = _clean_text(item.findtext("link", default=""))
            snippet = _clean_text(item.findtext("description", default=""))
            published_at = _clean_text(item.findtext("pubDate", default=""))
            if not title or not link:
                continue
            items.append(
                {
                    "title": title,
                    "url": link,
                    "snippet": snippet,
                    "published_at": published_at,
                }
            )
        return items


def load_jurisdictions(jurisdictions: Sequence[str], watchlist_file: str | None = None) -> List[str]:
    values = [item.strip() for item in jurisdictions if item and item.strip()]
    if watchlist_file:
        path = Path(watchlist_file)
        if not path.exists():
            raise ValueError(f"Watchlist file was not found: {path}")

        if path.suffix.lower() == ".json":
            payload = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(payload, list):
                values.extend(str(item).strip() for item in payload if str(item).strip())
            elif isinstance(payload, dict):
                items = payload.get("jurisdictions", [])
                if not isinstance(items, list):
                    raise ValueError("Watchlist JSON object must contain a 'jurisdictions' list.")
                values.extend(str(item).strip() for item in items if str(item).strip())
            else:
                raise ValueError("Watchlist JSON must be an array of jurisdiction strings or an object.")
        else:
            for line in path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line:
                    values.append(line)

    deduped: List[str] = []
    seen = set()
    for item in values:
        key = item.lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped
