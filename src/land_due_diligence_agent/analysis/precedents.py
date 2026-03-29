"""Local precedent retrieval and outcome-aware calibration helpers."""

from __future__ import annotations

import hashlib
import json
import logging
import math
import re
from pathlib import Path

from land_due_diligence_agent.models import (
    CanonicalIssue,
    DealMetadata,
    DocumentRecord,
    PrecedentCalibration,
    PrecedentIssueRecord,
    PrecedentReference,
    PrecedentSummary,
)
from land_due_diligence_agent.utils.text import clip_text, normalize_text, unique_preserve_order

_TOKEN_PATTERN = re.compile(r"[a-z0-9]+")
_EMBEDDING_DIMENSIONS = 192
_DEFAULT_STAGE = "acquisition-dd"
_PRODUCT_HINTS = {
    "multifamily": ("apartment", "apartments", "multifamily", "multi-family"),
    "single-family": ("single family", "single-family", "tract", "subdivision", "lots"),
    "townhome": ("townhome", "townhomes", "townhome product"),
    "industrial": ("industrial", "warehouse", "logistics"),
    "retail": ("retail", "shopping center"),
    "mixed-use": ("mixed use", "mixed-use"),
}
_STATE_TO_REGION = {
    "california": "west",
    "nevada": "west",
    "arizona": "west",
    "washington": "west",
    "oregon": "west",
    "texas": "south",
    "florida": "south",
    "georgia": "south",
    "north carolina": "south",
    "south carolina": "south",
    "tennessee": "south",
    "virginia": "south",
    "colorado": "mountain",
    "utah": "mountain",
    "idaho": "mountain",
}


class PrecedentEngine:
    """Retrieve and summarize local precedent matches for canonical issues."""

    def __init__(
        self,
        *,
        records: list[PrecedentIssueRecord],
        deal_metadata: DealMetadata,
        store_path: Path | None = None,
    ) -> None:
        self.records = records
        self.deal_metadata = deal_metadata
        self.store_path = store_path

    def retrieve(self, issue: CanonicalIssue) -> PrecedentCalibration:
        """Return precedent matches and a summary for one canonical issue."""

        if not self.records:
            return PrecedentCalibration(
                summary=PrecedentSummary(
                    reasoning="No local precedent records are available, so calibration is driven by current deal evidence only.",
                )
            )

        query_vector = _hashed_embedding(_issue_query_text(issue))
        scored_matches: list[tuple[float, PrecedentIssueRecord, dict[str, bool]]] = []
        for record in self.records:
            flags = _match_flags(issue, record, self.deal_metadata)
            semantic_similarity = _cosine_similarity(query_vector, _hashed_embedding(_record_text(record)))
            total_score = (
                semantic_similarity * 0.68
                + (0.20 if flags["issue_type_match"] else 0.0)
                + (0.08 if flags["category_match"] else 0.0)
                + (0.04 if flags["stage_match"] else 0.0)
                + (0.03 if flags["region_match"] else 0.0)
                + (0.02 if flags["product_match"] else 0.0)
            )
            if flags["issue_type_match"] or flags["category_match"] or semantic_similarity >= 0.22:
                scored_matches.append((total_score, record, flags))

        scored_matches.sort(key=lambda item: (-item[0], item[1].canonical_title, item[1].precedent_id))
        top_matches = [
            _to_reference(score, record, flags)
            for score, record, flags in scored_matches[:5]
        ]
        summary = _summarize_precedents(
            issue=issue,
            records=self.records,
            top_matches=top_matches,
        )
        return PrecedentCalibration(matches=top_matches, summary=summary)


def build_precedent_engine(
    *,
    deal_name: str,
    documents: list[DocumentRecord],
    logger: logging.Logger,
    store_path: Path | None = None,
) -> PrecedentEngine:
    """Build the local precedent engine from the default or explicit store."""

    resolved_path = store_path or _default_precedent_store_path()
    records = load_precedent_records(resolved_path)
    deal_metadata = infer_deal_metadata(deal_name, documents)
    if records:
        logger.info("Loaded %d precedent issue record(s) from %s.", len(records), resolved_path)
    else:
        logger.info("No precedent issue records were found at %s; precedent calibration will stay neutral.", resolved_path)
    return PrecedentEngine(records=records, deal_metadata=deal_metadata, store_path=resolved_path)


def load_precedent_records(path: Path | None = None) -> list[PrecedentIssueRecord]:
    """Load precedent records from a local JSONL file."""

    resolved_path = path or _default_precedent_store_path()
    if not resolved_path.exists():
        return []

    records: list[PrecedentIssueRecord] = []
    for line in resolved_path.read_text(encoding="utf-8").splitlines():
        raw = line.strip()
        if not raw:
            continue
        data = json.loads(raw)
        metadata = data.get("deal_metadata", {})
        records.append(
            PrecedentIssueRecord(
                precedent_id=str(data.get("precedent_id", "")).strip(),
                deal_name=str(data.get("deal_name", "")).strip() or str(data.get("precedent_id", "")).strip(),
                issue_type=str(data.get("issue_type", "")).strip(),
                canonical_title=str(data.get("canonical_title", "")).strip(),
                category=str(data.get("category", "")).strip(),
                description=normalize_text(str(data.get("description", "")).strip()),
                deal_metadata=DealMetadata(
                    stage=str(metadata.get("stage", "")).strip(),
                    region=str(metadata.get("region", "")).strip(),
                    product=str(metadata.get("product", "")).strip(),
                ),
                real_issue=data.get("real_issue"),
                materiality=str(data.get("materiality", "medium")).strip().lower() or "medium",
                actual_outcome=str(data.get("actual_outcome", "none")).strip().lower() or "none",
                false_positive_flag=bool(data.get("false_positive_flag", False)),
                resolution_notes=normalize_text(str(data.get("resolution_notes", "")).strip()),
            )
        )
    return records


def infer_deal_metadata(deal_name: str, documents: list[DocumentRecord]) -> DealMetadata:
    """Infer lightweight deal metadata for precedent matching."""

    sample_text = " ".join(
        [
            deal_name,
            " ".join(document.title for document in documents[:8]),
            " ".join(clip_text(document.normalized_text, 600) for document in documents[:4]),
        ]
    ).lower()

    product = ""
    for label, hints in _PRODUCT_HINTS.items():
        if any(hint in sample_text for hint in hints):
            product = label
            break

    region = ""
    for state_name, mapped_region in _STATE_TO_REGION.items():
        if state_name in sample_text:
            region = mapped_region
            break

    return DealMetadata(
        stage=_DEFAULT_STAGE,
        region=region,
        product=product,
    )


def _default_precedent_store_path() -> Path:
    return Path(__file__).resolve().parents[3] / "data" / "precedents" / "issue_memory.jsonl"


def _issue_query_text(issue: CanonicalIssue) -> str:
    return normalize_text(
        " ".join(
            part
            for part in [
                issue.issue_type or issue.issue_id,
                issue.title,
                issue.category,
                issue.why_it_matters,
                issue.likely_implication,
                " ".join(issue.core_facts[:3]),
                " ".join(issue.best_evidence[:2]),
            ]
            if part
        )
    )


def _record_text(record: PrecedentIssueRecord) -> str:
    return normalize_text(
        " ".join(
            part
            for part in [
                record.issue_type,
                record.canonical_title,
                record.category,
                record.description,
                record.actual_outcome,
                record.resolution_notes,
                record.deal_metadata.stage,
                record.deal_metadata.region,
                record.deal_metadata.product,
            ]
            if part
        )
    )


def _hashed_embedding(text: str) -> list[float]:
    features = _features_for_text(text)
    vector = [0.0] * _EMBEDDING_DIMENSIONS
    if not features:
        return vector

    for feature in features:
        digest = hashlib.sha1(feature.encode("utf-8")).digest()
        index = int.from_bytes(digest[:4], "big") % _EMBEDDING_DIMENSIONS
        vector[index] += 1.0

    magnitude = math.sqrt(sum(value * value for value in vector))
    if magnitude == 0:
        return vector
    return [value / magnitude for value in vector]


def _features_for_text(text: str) -> list[str]:
    tokens = [token for token in _TOKEN_PATTERN.findall(text.lower()) if len(token) > 2]
    bigrams = [f"{tokens[index]}_{tokens[index + 1]}" for index in range(len(tokens) - 1)]
    return tokens + bigrams


def _cosine_similarity(left: list[float], right: list[float]) -> float:
    if not left or not right:
        return 0.0
    return round(sum(left_value * right_value for left_value, right_value in zip(left, right)), 4)


def _match_flags(issue: CanonicalIssue, record: PrecedentIssueRecord, deal_metadata: DealMetadata) -> dict[str, bool]:
    normalized_issue_type = issue.issue_type or issue.issue_id
    return {
        "issue_type_match": bool(normalized_issue_type and record.issue_type == normalized_issue_type),
        "category_match": bool(issue.category and record.category == issue.category),
        "stage_match": bool(deal_metadata.stage and record.deal_metadata.stage == deal_metadata.stage),
        "region_match": bool(deal_metadata.region and record.deal_metadata.region == deal_metadata.region),
        "product_match": bool(deal_metadata.product and record.deal_metadata.product == deal_metadata.product),
    }


def _to_reference(
    score: float,
    record: PrecedentIssueRecord,
    flags: dict[str, bool],
) -> PrecedentReference:
    relevance_parts = []
    if flags["issue_type_match"]:
        relevance_parts.append("same issue type")
    elif flags["category_match"]:
        relevance_parts.append("same category")
    if flags["stage_match"]:
        relevance_parts.append("same stage")
    if flags["region_match"]:
        relevance_parts.append("same region")
    if flags["product_match"]:
        relevance_parts.append("same product")

    return PrecedentReference(
        precedent_id=record.precedent_id,
        title=f"{record.deal_name}: {record.canonical_title}",
        issue_type=record.issue_type,
        canonical_title=record.canonical_title,
        category=record.category,
        deal_metadata=record.deal_metadata,
        similarity_score=round(score, 3),
        category_match=flags["category_match"],
        stage_match=flags["stage_match"],
        region_match=flags["region_match"],
        product_match=flags["product_match"],
        real_issue=record.real_issue,
        materiality=record.materiality,
        actual_outcome=record.actual_outcome,
        false_positive_flag=record.false_positive_flag,
        resolution_notes=record.resolution_notes,
        relevance=", ".join(relevance_parts) or "semantic match",
        note=_reference_note(record),
    )


def _reference_note(record: PrecedentIssueRecord) -> str:
    parts = [f"outcome={record.actual_outcome}"]
    if record.real_issue is not None:
        parts.append(f"real_issue={record.real_issue}")
    if record.false_positive_flag:
        parts.append("flagged false positive")
    return ", ".join(parts)


def _summarize_precedents(
    *,
    issue: CanonicalIssue,
    records: list[PrecedentIssueRecord],
    top_matches: list[PrecedentReference],
) -> PrecedentSummary:
    exact_type_records = [record for record in records if record.issue_type == (issue.issue_type or issue.issue_id)]
    category_records = [record for record in records if record.category == issue.category]
    if exact_type_records:
        population = exact_type_records
    elif top_matches:
        matched_ids = {match.precedent_id for match in top_matches}
        population = [record for record in records if record.precedent_id in matched_ids]
    else:
        population = category_records

    if not population:
        return PrecedentSummary(
            reasoning="No close historical analogue was found, so precedence does not adjust the current issue.",
        )

    false_positive_rate = round(
        sum(1 for record in population if record.false_positive_flag) / len(population),
        2,
    )
    resolved_real_values = [record.real_issue for record in population if record.real_issue is not None]
    real_issue_rate = (
        sum(1 for value in resolved_real_values if value) / len(resolved_real_values)
        if resolved_real_values
        else 0.0
    )
    typical_impact = _typical_impact(population)
    resolution_pattern = _resolution_pattern(population, issue)
    confidence_adjustment = _confidence_adjustment(
        population_size=len(population),
        false_positive_rate=false_positive_rate,
        real_issue_rate=real_issue_rate,
        typical_impact=typical_impact,
    )
    score_adjustment = _score_adjustment(
        population_size=len(population),
        false_positive_rate=false_positive_rate,
        real_issue_rate=real_issue_rate,
        typical_impact=typical_impact,
        confidence_adjustment=confidence_adjustment,
    )
    return PrecedentSummary(
        historical_frequency=len(exact_type_records or category_records or population),
        false_positive_rate=false_positive_rate,
        typical_impact=typical_impact,
        resolution_pattern=resolution_pattern,
        confidence_adjustment=confidence_adjustment,
        score_adjustment=score_adjustment,
        sample_size=len(population),
        sparse_data=len(population) < 2,
        reasoning=_precedent_reasoning(
            false_positive_rate=false_positive_rate,
            typical_impact=typical_impact,
            confidence_adjustment=confidence_adjustment,
            resolution_pattern=resolution_pattern,
            sample_size=len(population),
        ),
    )


def _typical_impact(records: list[PrecedentIssueRecord]) -> str:
    impact_counter = {}
    for record in records:
        outcome = record.actual_outcome or "none"
        impact_counter[outcome] = impact_counter.get(outcome, 0) + 1
    if not impact_counter:
        return "none"
    ranked = sorted(impact_counter.items(), key=lambda item: (-item[1], item[0]))
    if len(ranked) > 1 and ranked[0][1] == ranked[1][1]:
        top_outcomes = [label for label, count in ranked if count == ranked[0][1] and label != "none"]
        if top_outcomes:
            return " / ".join(top_outcomes[:2])
        return "mixed"
    return ranked[0][0]


def _resolution_pattern(records: list[PrecedentIssueRecord], issue: CanonicalIssue) -> str:
    notes = unique_preserve_order(
        clip_text(record.resolution_notes, 120)
        for record in records
        if record.resolution_notes
    )
    if notes:
        return " | ".join(notes[:2])
    return issue.what_would_resolve_it


def _confidence_adjustment(
    *,
    population_size: int,
    false_positive_rate: float,
    real_issue_rate: float,
    typical_impact: str,
) -> str:
    if population_size < 2:
        return "none"
    if false_positive_rate >= 0.45:
        return "down"
    if real_issue_rate >= 0.75 and typical_impact != "none":
        return "up"
    if typical_impact == "none" and false_positive_rate >= 0.25:
        return "down"
    return "none"


def _score_adjustment(
    *,
    population_size: int,
    false_positive_rate: float,
    real_issue_rate: float,
    typical_impact: str,
    confidence_adjustment: str,
) -> int:
    if population_size == 0:
        return 0

    impact_points = {
        "cost": 6,
        "delay": 6,
        "redesign": 5,
        "mixed": 2,
        "none": -3,
    }.get(typical_impact, 0)
    if " / " in typical_impact:
        impact_points = 4
    raw = impact_points
    if real_issue_rate >= 0.75:
        raw += 3
    elif 0 < real_issue_rate <= 0.35:
        raw -= 3
    raw -= round(false_positive_rate * 10)
    if confidence_adjustment == "up":
        raw += 3
    elif confidence_adjustment == "down":
        raw -= 4

    support_factor = min(population_size, 4) / 4
    adjustment = round(raw * support_factor)
    if population_size < 2:
        adjustment = max(min(adjustment, 3), -3)
    return max(min(adjustment, 12), -12)


def _precedent_reasoning(
    *,
    false_positive_rate: float,
    typical_impact: str,
    confidence_adjustment: str,
    resolution_pattern: str,
    sample_size: int,
) -> str:
    if sample_size == 0:
        return "No precedent data is available."

    if confidence_adjustment == "down":
        base = "Historically this issue type often resolves as noise or routine friction unless direct deal-specific evidence is strong."
    elif confidence_adjustment == "up":
        base = f"Historically this issue type is usually real and has more often produced {typical_impact} than a harmless clean-up item."
    else:
        base = "Historical outcomes are mixed, so the current issue should stay anchored to the cited deal evidence first."

    if false_positive_rate >= 0.4:
        base += " False-positive history is high enough that omission-only versions should be treated cautiously."
    if resolution_pattern:
        base += f" Typical resolution: {resolution_pattern.rstrip('.')}."
    return normalize_text(base)
