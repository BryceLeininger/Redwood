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
    '"{jurisdiction}" "tentative map" "planning commission"',
    '"{jurisdiction}" "vesting tentative map"',
    '"{jurisdiction}" subdivision "staff report"',
]

UPCOMING_QUERY_TEMPLATES = [
    '"{jurisdiction}" "tentative map" agenda',
    '"{jurisdiction}" "recommended approval" "tentative map"',
    '"{jurisdiction}" subdivision "public hearing"',
]

LAND_USE_TERMS: Sequence[str] = (
    "tentative map",
    "vesting tentative map",
    "subdivision",
    "tract map",
)

PROCESS_TERMS_BY_STAGE: Dict[str, Sequence[str]] = {
    "approved_recently": (
        "planning commission",
        "city council",
        "staff report",
        "approved",
        "approval",
    ),
    "approaching_approval": (
        "planning commission",
        "agenda",
        "public hearing",
        "staff report",
        "recommended approval",
    ),
}

EXCLUDED_DOMAIN_KEYWORDS = (
    "queenonline",
    "hunting-",
    "rokslide",
    "tripadvisor",
    "wikipedia",
    "mapquest",
    "tourist",
    "facebook",
    "instagram",
    "youtube",
)

SINGLE_FAMILY_TERMS: Sequence[str] = (
    "single family",
    "single-family",
    "sfd",
    "sfr",
    "detached home",
    "detached homes",
    "detached housing",
    "single family detached",
)

PROMPT_STAGE_TERMS: Dict[str, Sequence[str]] = {
    "approved_recently": (
        "approved",
        "approval",
        "entitled",
        "adopted",
        "city council",
        "planning commission",
    ),
    "approaching_approval": (
        "agenda",
        "public hearing",
        "recommended approval",
        "hearing",
        "staff report",
        "planning commission",
    ),
}

PROMPT_AREA_EXPANSIONS: Dict[str, Sequence[str]] = {
    "central valley": ("Fresno", "Modesto", "Merced", "Madera", "Stockton", "Visalia"),
    "sacramento": ("Sacramento", "Sacramento County", "Elk Grove", "Roseville", "Placer County"),
    "greater sacramento": ("Sacramento", "Sacramento County", "Elk Grove", "Roseville", "Placer County"),
    "sacramento area": ("Sacramento", "Sacramento County", "Elk Grove", "Roseville", "Placer County"),
}


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
class WatchTarget:
    jurisdiction: str
    approved_queries: List[str]
    upcoming_queries: List[str]
    approved_urls: List[str]
    upcoming_urls: List[str]

    def queries_for_stage(self, stage: str, templates: Sequence[str]) -> List[str]:
        if stage == "approved_recently" and self.approved_queries:
            return list(self.approved_queries)
        if stage == "approaching_approval" and self.upcoming_queries:
            return list(self.upcoming_queries)
        return [template.format(jurisdiction=self.jurisdiction) for template in templates]

    def urls_for_stage(self, stage: str) -> List[str]:
        if stage == "approved_recently":
            return list(self.approved_urls)
        if stage == "approaching_approval":
            return list(self.upcoming_urls)
        return []


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


@dataclass(frozen=True)
class OpportunitySearchSpec:
    raw_query: str
    requested_areas: List[str]
    search_areas: List[str]
    min_acres: float | None
    min_lots: int | None
    housing_type: str
    stages: List[str]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class OpportunitySearchItem:
    requested_area: str
    search_area: str
    stage: str
    title: str
    url: str
    source_domain: str
    published_at: str | None
    snippet: str
    matched_query: str
    extracted_acres: float | None
    extracted_lots: int | None
    qualification: str
    qualification_notes: List[str]
    score: float

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


def _extract_html_title(html: str) -> str:
    match = re.search(r"<title[^>]*>(.*?)</title>", html, flags=re.IGNORECASE | re.DOTALL)
    if not match:
        return ""
    return _clean_text(match.group(1))


def _extract_relevant_snippet(text: str) -> str:
    lowered = text.lower()
    anchors = list(LAND_USE_TERMS) + list(PROCESS_TERMS_BY_STAGE["approved_recently"]) + list(
        PROCESS_TERMS_BY_STAGE["approaching_approval"]
    )
    for anchor in anchors:
        index = lowered.find(anchor)
        if index >= 0:
            start = max(0, index - 120)
            end = min(len(text), index + 280)
            return text[start:end].strip()
    return text[:320].strip()


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
        "not_ready": 34.0,
    }.get(model_prediction, 42.0)

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
    if score >= 45:
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


def _jurisdiction_tokens(jurisdiction: str) -> List[str]:
    words = re.findall(r"[a-z0-9]+", jurisdiction.lower())
    stop_words = {"city", "county", "of", "ca", "az", "nv", "tx", "ut", "usa"}
    return [word for word in words if word not in stop_words]


def _result_is_relevant(stage: str, jurisdiction: str, title: str, url: str, snippet: str) -> bool:
    haystack = f"{title} {snippet} {url}".lower()
    domain = urlparse(url).netloc.lower()

    if any(fragment in domain for fragment in EXCLUDED_DOMAIN_KEYWORDS):
        return False

    tokens = _jurisdiction_tokens(jurisdiction)
    if tokens and not all(token in haystack for token in tokens):
        return False

    if not any(term in haystack for term in LAND_USE_TERMS):
        return False

    process_terms = PROCESS_TERMS_BY_STAGE.get(stage, ())
    if process_terms and not any(term in haystack for term in process_terms):
        return False

    return True


def _split_area_phrase(value: str) -> List[str]:
    parts = re.split(r",|/|&|\band\b", value, flags=re.IGNORECASE)
    cleaned: List[str] = []
    for part in parts:
        item = re.sub(r"\b(?:areas?|markets?|regions?)\b", " ", part, flags=re.IGNORECASE)
        item = re.sub(r"\s+", " ", item).strip(" ,.")
        if item:
            cleaned.append(item)
    return cleaned


def _extract_requested_areas(query: str) -> List[str]:
    patterns = (
        r"(?:search|scan|find|look(?:\s+for)?)\s+(?:the\s+)?(.+?)\s+(?:areas?|markets?|regions?)\s+for\b",
        r"(?:search|scan|find|look(?:\s+for)?)\s+(?:the\s+)?(.+?)\s+for\b",
        r"\bin\s+(.+?)\s+(?:for|with|that)\b",
    )
    for pattern in patterns:
        match = re.search(pattern, query, flags=re.IGNORECASE)
        if not match:
            continue
        areas = _split_area_phrase(match.group(1))
        if areas:
            return areas
    return []


def _extract_threshold_number(query: str, unit_pattern: str) -> float | None:
    patterns = (
        rf"(?:at\s+least|min(?:imum)?(?:\s+of)?|>=|over)\s+(\d+(?:\.\d+)?)\s*(?:\+)?\s*{unit_pattern}",
        rf"\b(\d+(?:\.\d+)?)\+\s*{unit_pattern}",
        rf"\b(\d+(?:\.\d+)?)\s*{unit_pattern}\s*(?:or\s+more|minimum|min\b)",
    )
    for pattern in patterns:
        match = re.search(pattern, query, flags=re.IGNORECASE)
        if match:
            try:
                return float(match.group(1))
            except ValueError:
                return None
    return None


def _detect_housing_type(query: str) -> str:
    lowered = query.lower()
    if any(term in lowered for term in SINGLE_FAMILY_TERMS):
        return "single_family_detached"
    return "residential"


def _detect_requested_stages(query: str) -> List[str]:
    lowered = query.lower()
    wants_approved = any(
        phrase in lowered
        for phrase in (
            "already approved",
            "approved for",
            "approved subdivision",
            "approved map",
            "entitled",
            "vested",
        )
    )
    wants_upcoming = any(
        phrase in lowered
        for phrase in (
            "in the process of being approved",
            "being approved",
            "about to be approved",
            "pending approval",
            "upcoming approval",
            "public hearing",
            "agenda",
            "recommended approval",
            "in process",
        )
    )
    if wants_approved and wants_upcoming:
        return ["approved_recently", "approaching_approval"]
    if wants_approved:
        return ["approved_recently"]
    if wants_upcoming:
        return ["approaching_approval"]
    return ["approved_recently", "approaching_approval"]


def _expand_requested_areas(requested_areas: Sequence[str]) -> List[str]:
    expanded: List[str] = []
    seen = set()
    for area in requested_areas:
        candidates = PROMPT_AREA_EXPANSIONS.get(area.lower(), (area,))
        for candidate in candidates:
            key = candidate.lower()
            if key in seen:
                continue
            seen.add(key)
            expanded.append(candidate)
    return expanded


def _parse_opportunity_search_query(query: str) -> OpportunitySearchSpec:
    requested_areas = _extract_requested_areas(query)
    search_areas = _expand_requested_areas(requested_areas) if requested_areas else []
    min_acres = _extract_threshold_number(query, r"acres?\b")
    min_lots = _extract_threshold_number(
        query,
        r"(?:(?:sfd|sfr)\s+|single[- ]family\s+|detached\s+)?(?:lots|homes|units)\b",
    )
    return OpportunitySearchSpec(
        raw_query=query.strip(),
        requested_areas=requested_areas,
        search_areas=search_areas,
        min_acres=min_acres,
        min_lots=int(min_lots) if min_lots is not None else None,
        housing_type=_detect_housing_type(query),
        stages=_detect_requested_stages(query),
    )


def _query_variants_for_prompt(spec: OpportunitySearchSpec, area: str, stage: str) -> List[str]:
    stage_fragments = {
        "approved_recently": [
            ["subdivision", '"tentative map"', "approved"],
            ["subdivision", '"vesting tentative map"', "approved"],
            ["subdivision", '"staff report"', "approved"],
        ],
        "approaching_approval": [
            ["subdivision", '"tentative map"', "agenda"],
            ["subdivision", '"public hearing"', '"tentative map"'],
            ["subdivision", '"recommended approval"', '"tentative map"'],
        ],
    }
    housing_fragment = ['"single family"'] if spec.housing_type == "single_family_detached" else []
    number_fragment = []
    if spec.min_lots is not None:
        number_fragment.append(f'"{spec.min_lots} lots"')
    if spec.min_acres is not None:
        acres_label = int(spec.min_acres) if float(spec.min_acres).is_integer() else spec.min_acres
        number_fragment.append(f'"{acres_label} acres"')

    queries: List[str] = []
    for fragments in stage_fragments.get(stage, []):
        parts = [f'"{area}"', *fragments, *housing_fragment]
        if number_fragment:
            queries.append(" ".join(parts + number_fragment[:1]))
        queries.append(" ".join(parts))
    deduped: List[str] = []
    seen = set()
    for item in queries:
        key = item.lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def _fetch_result_page_text(url: str) -> str:
    try:
        response = requests.get(
            url,
            timeout=SEARCH_TIMEOUT_SECONDS,
            headers={"User-Agent": DEFAULT_USER_AGENT},
        )
        response.raise_for_status()
    except requests.RequestException:
        return ""

    content_type = response.headers.get("content-type", "").lower()
    if "pdf" in content_type:
        return ""

    return _clean_text(response.text)[:18000]


def _extract_acres(text: str) -> float | None:
    candidates = []
    for pattern in (r"\b(\d+(?:\.\d+)?)\s*acres?\b", r"\b(\d+(?:\.\d+)?)\s*-\s*acre\b"):
        for match in re.finditer(pattern, text, flags=re.IGNORECASE):
            try:
                value = float(match.group(1))
            except ValueError:
                continue
            if 0.25 <= value <= 10000:
                candidates.append(value)
    return max(candidates) if candidates else None


def _extract_lots(text: str) -> int | None:
    candidates = []
    patterns = (
        r"\b(\d{1,4})\s*-\s*lots?\b",
        r"\b(\d{1,4})\s+lots?\b",
        r"\b(\d{1,4})\s+(?:single[- ]family|detached|sfd|sfr)\s+(?:lots|homes|units)\b",
        r"\b(\d{1,4})\s+(?:single[- ]family|detached)\s+homes\b",
        r"\b(\d{1,4})\s+residential\s+lots?\b",
    )
    for pattern in patterns:
        for match in re.finditer(pattern, text, flags=re.IGNORECASE):
            try:
                value = int(match.group(1))
            except ValueError:
                continue
            if 2 <= value <= 2000:
                candidates.append(value)
    return max(candidates) if candidates else None


def _area_tokens_for_prompt(area: str) -> List[str]:
    tokens = _jurisdiction_tokens(area)
    return [token for token in tokens if len(token) >= 4]


def _result_matches_prompt_search(
    spec: OpportunitySearchSpec,
    stage: str,
    search_area: str,
    title: str,
    url: str,
    snippet: str,
    page_text: str,
) -> bool:
    haystack = f"{title} {snippet} {page_text} {url}".lower()
    domain = urlparse(url).netloc.lower()

    if any(fragment in domain for fragment in EXCLUDED_DOMAIN_KEYWORDS):
        return False
    if not any(term in haystack for term in LAND_USE_TERMS):
        return False
    if not any(term in haystack for term in PROMPT_STAGE_TERMS.get(stage, ())):
        return False
    area_tokens = _area_tokens_for_prompt(search_area)
    if area_tokens and not any(token in haystack for token in area_tokens):
        return False
    if spec.housing_type == "single_family_detached" and not any(term in haystack for term in SINGLE_FAMILY_TERMS):
        return False
    return True


def _qualify_prompt_result(
    spec: OpportunitySearchSpec,
    extracted_acres: float | None,
    extracted_lots: int | None,
) -> tuple[str | None, List[str], float]:
    notes: List[str] = []
    score = 45.0

    if spec.min_acres is not None:
        if extracted_acres is None:
            notes.append(f"Site area not confirmed against {spec.min_acres} acres.")
        elif extracted_acres < spec.min_acres:
            return None, [f"Only {extracted_acres} acres found."], 0.0
        else:
            notes.append(f"{extracted_acres} acres found.")
            score += 18.0

    if spec.min_lots is not None:
        if extracted_lots is None:
            notes.append(f"Lot count not confirmed against {spec.min_lots} lots.")
        elif extracted_lots < spec.min_lots:
            return None, [f"Only {extracted_lots} lots found."], 0.0
        else:
            notes.append(f"{extracted_lots} lots found.")
            score += 22.0

    if spec.min_acres is not None and extracted_acres is None:
        return "needs_review", notes, score
    if spec.min_lots is not None and extracted_lots is None:
        return "needs_review", notes, score
    return "qualified", notes or ["Matches the requested filters."], min(score, 100.0)


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
        targets: Sequence[WatchTarget],
        lookback_days: int = 45,
        max_results_per_query: int = 6,
    ) -> Dict[str, Any]:
        cleaned_targets = [target for target in targets if target.jurisdiction.strip()]
        if not cleaned_targets:
            raise ValueError("At least one jurisdiction is required for planning activity monitoring.")

        lookback_days = max(1, lookback_days)
        max_results_per_query = max(1, max_results_per_query)
        cutoff = datetime.now(timezone.utc) - timedelta(days=lookback_days)

        approved_recently = self._search_stage(
            stage="approved_recently",
            targets=cleaned_targets,
            query_templates=APPROVED_QUERY_TEMPLATES,
            cutoff=cutoff,
            max_results_per_query=max_results_per_query,
        )
        approaching_approval = self._search_stage(
            stage="approaching_approval",
            targets=cleaned_targets,
            query_templates=UPCOMING_QUERY_TEMPLATES,
            cutoff=cutoff,
            max_results_per_query=max_results_per_query,
        )

        return {
            "agent": self.specialist.metadata["blueprint"]["name"],
            "lookback_days": lookback_days,
            "jurisdictions": [target.jurisdiction for target in cleaned_targets],
            "approved_recently": [item.to_dict() for item in approved_recently],
            "approaching_approval": [item.to_dict() for item in approaching_approval],
        }

    def search_opportunities(
        self,
        query: str,
        lookback_days: int = 365,
        max_results_per_query: int = 6,
    ) -> Dict[str, Any]:
        spec = _parse_opportunity_search_query(query)
        if not spec.search_areas:
            raise ValueError("Could not detect any search areas. Specify a city, county, or region in the request.")

        lookback_days = max(1, lookback_days)
        max_results_per_query = max(1, max_results_per_query)
        cutoff = datetime.now(timezone.utc) - timedelta(days=lookback_days)

        page_cache: Dict[str, str] = {}
        results: List[OpportunitySearchItem] = []
        seen = set()

        for requested_area in spec.requested_areas:
            expanded_areas = PROMPT_AREA_EXPANSIONS.get(requested_area.lower(), (requested_area,))
            for search_area in expanded_areas:
                for stage in spec.stages:
                    for prompt_query in _query_variants_for_prompt(spec, search_area, stage):
                        try:
                            search_results = self._search_rss(prompt_query, max_results=max_results_per_query)
                        except (requests.RequestException, ET.ParseError):
                            continue

                        for result in search_results:
                            url = result["url"]
                            dedupe_key = url.lower()
                            if dedupe_key in seen:
                                continue

                            published_at = _parse_pub_date(result.get("published_at"))
                            if published_at and published_at < cutoff:
                                continue

                            page_text = page_cache.get(url)
                            if page_text is None:
                                page_text = _fetch_result_page_text(url)
                                page_cache[url] = page_text

                            title = result["title"]
                            snippet = result["snippet"]
                            if not _result_matches_prompt_search(
                                spec=spec,
                                stage=stage,
                                search_area=search_area,
                                title=title,
                                url=url,
                                snippet=snippet,
                                page_text=page_text,
                            ):
                                continue

                            combined_text = f"{title} {snippet} {page_text}"
                            extracted_acres = _extract_acres(combined_text)
                            extracted_lots = _extract_lots(combined_text)
                            qualification, notes, score = _qualify_prompt_result(
                                spec=spec,
                                extracted_acres=extracted_acres,
                                extracted_lots=extracted_lots,
                            )
                            if qualification is None:
                                continue

                            seen.add(dedupe_key)
                            results.append(
                                OpportunitySearchItem(
                                    requested_area=requested_area,
                                    search_area=search_area,
                                    stage=stage,
                                    title=title,
                                    url=url,
                                    source_domain=urlparse(url).netloc.lower(),
                                    published_at=published_at.isoformat() if published_at else None,
                                    snippet=_extract_relevant_snippet(combined_text),
                                    matched_query=prompt_query,
                                    extracted_acres=extracted_acres,
                                    extracted_lots=extracted_lots,
                                    qualification=qualification,
                                    qualification_notes=notes,
                                    score=round(score, 1),
                                )
                            )

        results.sort(
            key=lambda item: (
                1 if item.qualification == "qualified" else 0,
                item.score,
                item.published_at or "",
                item.title.lower(),
            ),
            reverse=True,
        )

        qualified = [item.to_dict() for item in results if item.qualification == "qualified"]
        review = [item.to_dict() for item in results if item.qualification != "qualified"]
        return {
            "agent": self.specialist.metadata["blueprint"]["name"],
            "query": query.strip(),
            "interpreted_search": spec.to_dict(),
            "lookback_days": lookback_days,
            "qualified_results": qualified,
            "review_results": review,
        }

    def _search_stage(
        self,
        stage: str,
        targets: Sequence[WatchTarget],
        query_templates: Sequence[str],
        cutoff: datetime,
        max_results_per_query: int,
    ) -> List[PlanningWatchItem]:
        items: List[PlanningWatchItem] = []
        seen = set()
        for target in targets:
            jurisdiction = target.jurisdiction
            for result in self._scan_source_urls(stage=stage, target=target):
                dedupe_key = (stage, result.url.lower())
                if dedupe_key in seen:
                    continue
                seen.add(dedupe_key)
                items.append(result)

            for query in target.queries_for_stage(stage, query_templates):
                try:
                    search_results = self._search_rss(query, max_results=max_results_per_query)
                except (requests.RequestException, ET.ParseError):
                    continue

                for result in search_results:
                    dedupe_key = (stage, result["url"].lower())
                    if dedupe_key in seen:
                        continue

                    published_at = _parse_pub_date(result.get("published_at"))
                    if published_at and published_at < cutoff:
                        continue

                    if not _result_is_relevant(
                        stage=stage,
                        jurisdiction=jurisdiction,
                        title=result["title"],
                        url=result["url"],
                        snippet=result["snippet"],
                    ):
                        continue

                    seen.add(dedupe_key)

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

    def _scan_source_urls(self, stage: str, target: WatchTarget) -> List[PlanningWatchItem]:
        items: List[PlanningWatchItem] = []
        for url in target.urls_for_stage(stage):
            try:
                response = requests.get(
                    url,
                    timeout=SEARCH_TIMEOUT_SECONDS,
                    headers={"User-Agent": DEFAULT_USER_AGENT},
                )
                response.raise_for_status()
            except requests.RequestException:
                continue

            content_type = response.headers.get("content-type", "").lower()
            if "pdf" in content_type:
                continue

            html = response.text
            title = _extract_html_title(html) or url
            text = _clean_text(html)
            snippet = _extract_relevant_snippet(text)
            if not _result_is_relevant(
                stage=stage,
                jurisdiction=target.jurisdiction,
                title=title,
                url=url,
                snippet=snippet,
            ):
                continue

            items.append(
                PlanningWatchItem(
                    stage=stage,
                    jurisdiction=target.jurisdiction,
                    title=title,
                    url=url,
                    source_domain=urlparse(url).netloc.lower(),
                    published_at=None,
                    snippet=snippet,
                    matched_query="configured_source_url",
                )
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
    return [target.jurisdiction for target in load_watch_targets(jurisdictions, watchlist_file)]


def load_watch_targets(jurisdictions: Sequence[str], watchlist_file: str | None = None) -> List[WatchTarget]:
    values = [item.strip() for item in jurisdictions if item and item.strip()]
    targets: List[WatchTarget] = [
        WatchTarget(
            jurisdiction=item,
            approved_queries=[],
            upcoming_queries=[],
            approved_urls=[],
            upcoming_urls=[],
        )
        for item in values
    ]

    if watchlist_file:
        path = Path(watchlist_file)
        if not path.exists():
            raise ValueError(f"Watchlist file was not found: {path}")

        if path.suffix.lower() == ".json":
            payload = json.loads(path.read_text(encoding="utf-8"))
            targets.extend(_targets_from_payload(payload))
        else:
            for line in path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line:
                    targets.append(
                        WatchTarget(
                            jurisdiction=line,
                            approved_queries=[],
                            upcoming_queries=[],
                            approved_urls=[],
                            upcoming_urls=[],
                        )
                    )

    deduped: List[WatchTarget] = []
    seen = set()
    for item in targets:
        key = item.jurisdiction.lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def load_watch_targets_from_text(raw_text: str) -> List[WatchTarget]:
    raw_text = raw_text.strip()
    if not raw_text:
        return []

    if raw_text.startswith("{") or raw_text.startswith("["):
        payload = json.loads(raw_text)
        return _targets_from_payload(payload)

    return [
        WatchTarget(
            jurisdiction=line.strip(),
            approved_queries=[],
            upcoming_queries=[],
            approved_urls=[],
            upcoming_urls=[],
        )
        for line in raw_text.splitlines()
        if line.strip()
    ]


def _targets_from_payload(payload: Any) -> List[WatchTarget]:
    targets: List[WatchTarget] = []
    if isinstance(payload, list):
        for item in payload:
            targets.append(_parse_watch_target(item))
        return targets

    if isinstance(payload, dict):
        target_items = payload.get("targets")
        if target_items is not None:
            if not isinstance(target_items, list):
                raise ValueError("Watchlist JSON field 'targets' must be a list.")
            for item in target_items:
                targets.append(_parse_watch_target(item))
            return targets

        items = payload.get("jurisdictions", [])
        if not isinstance(items, list):
            raise ValueError("Watchlist JSON object must contain a 'jurisdictions' list or 'targets' list.")
        for item in items:
            targets.append(_parse_watch_target(item))
        return targets

    raise ValueError("Watchlist JSON must be an array of jurisdiction strings or an object.")


def _parse_watch_target(value: Any) -> WatchTarget:
    if isinstance(value, str):
        item = value.strip()
        if not item:
            raise ValueError("Watch target strings cannot be empty.")
        return WatchTarget(
            jurisdiction=item,
            approved_queries=[],
            upcoming_queries=[],
            approved_urls=[],
            upcoming_urls=[],
        )

    if not isinstance(value, dict):
        raise ValueError("Watch targets must be strings or objects.")

    jurisdiction = str(value.get("jurisdiction") or value.get("name") or "").strip()
    if not jurisdiction:
        raise ValueError("Watch target objects must include a jurisdiction or name.")

    approved_queries = value.get("approved_queries", [])
    upcoming_queries = value.get("upcoming_queries", [])
    approved_urls = value.get("approved_urls", [])
    upcoming_urls = value.get("upcoming_urls", [])
    if not isinstance(approved_queries, list) or not isinstance(upcoming_queries, list):
        raise ValueError("Watch target query overrides must be arrays of strings.")
    if not isinstance(approved_urls, list) or not isinstance(upcoming_urls, list):
        raise ValueError("Watch target source url lists must be arrays of strings.")

    return WatchTarget(
        jurisdiction=jurisdiction,
        approved_queries=[str(item).strip() for item in approved_queries if str(item).strip()],
        upcoming_queries=[str(item).strip() for item in upcoming_queries if str(item).strip()],
        approved_urls=[str(item).strip() for item in approved_urls if str(item).strip()],
        upcoming_urls=[str(item).strip() for item in upcoming_urls if str(item).strip()],
    )
