"""Local precedent retrieval and outcome-aware calibration helpers."""

from __future__ import annotations

import hashlib
import json
import logging
import math
import re
from collections import Counter
from pathlib import Path

from land_due_diligence_agent.models import (
    CanonicalIssue,
    DealMetadata,
    DocumentRecord,
    PrecedentCalibration,
    PrecedentIssueRecord,
    PrecedentReference,
    PrecedentSummary,
    ReviewerIssueFeedback,
)
from land_due_diligence_agent.utils.files import ensure_directory, slugify
from land_due_diligence_agent.utils.text import clip_text, normalize_text, unique_preserve_order

_TOKEN_PATTERN = re.compile(r"[a-z0-9]+")
_EMBEDDING_DIMENSIONS = 192
_DEFAULT_STAGE = "acquisition-dd"
_MATCH_LIMIT = 5
_OUTCOME_ORDER = ("cost", "delay", "redesign", "none", "unknown")
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
                    confidence_adjustment="neutral",
                    reasoning="No local precedent records are available, so calibration is driven by current deal evidence only.",
                )
            )

        query_vector = _hashed_embedding(_issue_query_text(issue))
        scored_matches: list[tuple[float, PrecedentIssueRecord, dict[str, bool]]] = []
        for record in self.records:
            flags = _match_flags(issue, record, self.deal_metadata)
            semantic_similarity = _cosine_similarity(query_vector, _hashed_embedding(_record_text(record)))
            total_score = (
                semantic_similarity * 0.62
                + (0.20 if flags["issue_id_match"] else 0.0)
                + (0.08 if flags["category_match"] else 0.0)
                + (0.05 if flags["stage_match"] else 0.0)
                + (0.03 if flags["region_match"] else 0.0)
                + (0.02 if flags["product_match"] else 0.0)
            )
            if flags["issue_id_match"] or flags["category_match"] or semantic_similarity >= 0.22:
                scored_matches.append((total_score, record, flags))

        scored_matches.sort(
            key=lambda item: (
                -item[0],
                _record_issue_id(item[1]),
                item[1].canonical_title,
                _record_precedent_id(item[1]),
            )
        )
        top_matches = [
            _to_reference(score, record, flags)
            for score, record, flags in scored_matches[:_MATCH_LIMIT]
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
        logger.info("Loaded %d issue-memory record(s) from %s.", len(records), resolved_path)
    else:
        logger.info("No issue-memory records were found at %s; precedent calibration will stay neutral.", resolved_path)
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
        region = str(metadata.get("geography", metadata.get("region", ""))).strip()
        notes = normalize_text(str(data.get("notes", data.get("resolution_notes", ""))).strip())
        records.append(
            _normalize_record(
                PrecedentIssueRecord(
                    precedent_id=str(data.get("precedent_id", "")).strip(),
                    deal_name=str(data.get("deal_name", "")).strip()
                    or str(data.get("deal_id", "")).strip()
                    or str(data.get("precedent_id", "")).strip(),
                    issue_type=str(data.get("issue_type", data.get("issue_id", ""))).strip(),
                    canonical_title=str(data.get("canonical_title", "")).strip()
                    or str(data.get("issue_id", "")).strip(),
                    category=str(data.get("category", "")).strip(),
                    issue_id=str(data.get("issue_id", data.get("issue_type", ""))).strip(),
                    deal_id=str(data.get("deal_id", "")).strip()
                    or slugify(str(data.get("deal_name", "")).strip() or "deal"),
                    description=normalize_text(str(data.get("description", notes)).strip()),
                    deal_metadata=DealMetadata(
                        stage=str(metadata.get("stage", "")).strip(),
                        region=region,
                        product=str(metadata.get("product", "")).strip(),
                    ),
                    evidence_basis=str(data.get("evidence_basis", "")).strip(),
                    issue_strength=str(data.get("issue_strength", "")).strip(),
                    real_issue=data.get("real_issue"),
                    materiality=_normalize_materiality(data.get("materiality", "medium")),
                    decision_relevant=_optional_bool(data.get("decision_relevant")),
                    actual_outcome=_normalize_outcome(str(data.get("actual_outcome", "unknown")).strip()),
                    false_positive_flag=bool(data.get("false_positive_flag", False)),
                    resolved_by=_normalize_resolved_by(str(data.get("resolved_by", "unknown")).strip()),
                    notes=notes,
                    resolution_notes=notes,
                )
            )
        )
    return records


def save_precedent_records(records: list[PrecedentIssueRecord], path: Path | None = None) -> Path:
    """Persist precedent records back to the local JSONL store."""

    resolved_path = path or _default_precedent_store_path()
    ensure_directory(resolved_path.parent)
    ordered = sorted(
        (_normalize_record(record) for record in records),
        key=lambda record: (
            record.deal_id,
            _record_issue_id(record),
            record.canonical_title,
            _record_precedent_id(record),
        ),
    )
    lines = [json.dumps(_serialize_precedent_record(record), sort_keys=True) for record in ordered]
    resolved_path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
    return resolved_path


def upsert_precedent_records(
    records: list[PrecedentIssueRecord],
    *,
    path: Path | None = None,
) -> Path:
    """Upsert issue-memory records into the local JSONL store."""

    resolved_path = path or _default_precedent_store_path()
    indexed = {_record_store_key(record): record for record in load_precedent_records(resolved_path)}
    for record in records:
        normalized = _normalize_record(record)
        indexed[_record_store_key(normalized)] = normalized
    return save_precedent_records(list(indexed.values()), resolved_path)


def load_reviewer_feedback_rows(path: Path) -> list[ReviewerIssueFeedback]:
    """Load reviewer feedback rows from a JSON template file."""

    if not path.exists():
        return []

    rows: list[ReviewerIssueFeedback] = []
    for raw in json.loads(path.read_text(encoding="utf-8")):
        metadata = raw.get("deal_metadata", {})
        rows.append(
            ReviewerIssueFeedback(
                issue_id=str(raw.get("issue_id", "")).strip(),
                canonical_title=str(raw.get("canonical_title", "")).strip(),
                category=str(raw.get("category", "")).strip(),
                deal_id=str(raw.get("deal_id", "")).strip(),
                deal_name=str(raw.get("deal_name", "")).strip(),
                deal_metadata=DealMetadata(
                    stage=str(metadata.get("stage", "")).strip(),
                    region=str(metadata.get("geography", metadata.get("region", ""))).strip(),
                    product=str(metadata.get("product", "")).strip(),
                ),
                evidence_basis=str(raw.get("evidence_basis", "")).strip(),
                issue_strength=str(raw.get("issue_strength", "")).strip(),
                false_positive_risk=str(raw.get("false_positive_risk", "")).strip(),
                model_materiality=_normalize_materiality(raw.get("model_materiality", raw.get("materiality", "medium"))),
                model_decision_relevant=_optional_bool(raw.get("model_decision_relevant", raw.get("decision_relevant"))),
                model_action=str(raw.get("model_action", raw.get("correct_action", ""))).strip(),
                real_issue=_optional_bool(raw.get("real_issue")),
                false_positive_flag=bool(raw.get("false_positive_flag", False)),
                materiality=_normalize_materiality(raw.get("materiality", "medium")),
                decision_relevant=_optional_bool(raw.get("decision_relevant")),
                duplicate_of=_blank_to_none(raw.get("duplicate_of")),
                overstated=bool(raw.get("overstated", False)),
                understated=bool(raw.get("understated", False)),
                actual_outcome=_normalize_outcome(str(raw.get("actual_outcome", "unknown")).strip()),
                resolved_by=_normalize_resolved_by(str(raw.get("resolved_by", "unknown")).strip()),
                correct_action=str(raw.get("correct_action", "")).strip(),
                notes=normalize_text(str(raw.get("notes", "")).strip()),
            )
        )
    return rows


def ingest_reviewer_feedback_files(
    *,
    feedback_paths: list[Path],
    store_path: Path | None = None,
    logger: logging.Logger | None = None,
) -> dict[str, int]:
    """Read reviewer feedback files and upsert issue-memory records."""

    resolved_paths = [path for path in feedback_paths if path.exists()]
    records_to_upsert: list[PrecedentIssueRecord] = []
    files_ingested = 0
    for path in resolved_paths:
        meaningful_rows = [row for row in load_reviewer_feedback_rows(path) if _feedback_row_has_signal(row)]
        if not meaningful_rows:
            continue
        files_ingested += 1
        records_to_upsert.extend(_record_from_feedback_row(row) for row in meaningful_rows)

    if records_to_upsert:
        saved_path = upsert_precedent_records(records_to_upsert, path=store_path)
        if logger is not None:
            logger.info(
                "Ingested %d reviewer feedback row(s) from %d file(s) into %s.",
                len(records_to_upsert),
                files_ingested,
                saved_path,
            )
    elif logger is not None and resolved_paths:
        logger.info("Reviewer feedback files were found, but none had meaningful annotations to ingest.")

    return {
        "files_scanned": len(resolved_paths),
        "files_ingested": files_ingested,
        "records_upserted": len(records_to_upsert),
    }


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
                _record_issue_id(record),
                record.canonical_title,
                record.category,
                record.description,
                record.evidence_basis,
                record.issue_strength,
                record.actual_outcome,
                record.resolved_by,
                record.notes or record.resolution_notes,
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
        "issue_id_match": bool(normalized_issue_type and _record_issue_id(record) == normalized_issue_type),
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
    if flags["issue_id_match"]:
        relevance_parts.append("same issue id")
    elif flags["category_match"]:
        relevance_parts.append("same category")
    if flags["stage_match"]:
        relevance_parts.append("same stage")
    if flags["region_match"]:
        relevance_parts.append("same geography")
    if flags["product_match"]:
        relevance_parts.append("same product")

    return PrecedentReference(
        precedent_id=_record_precedent_id(record),
        title=f"{record.deal_name}: {record.canonical_title}",
        issue_id=_record_issue_id(record),
        deal_id=record.deal_id,
        deal_name=record.deal_name,
        issue_type=record.issue_type or _record_issue_id(record),
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
        decision_relevant=record.decision_relevant,
        resolved_by=record.resolved_by,
        resolution_notes=record.notes or record.resolution_notes,
        relevance=", ".join(relevance_parts) or "semantic match",
        note=_reference_note(record),
    )


def _reference_note(record: PrecedentIssueRecord) -> str:
    parts = [f"outcome={record.actual_outcome}"]
    if record.real_issue is not None:
        parts.append(f"real_issue={record.real_issue}")
    if record.resolved_by and record.resolved_by != "unknown":
        parts.append(f"resolved_by={record.resolved_by}")
    if record.false_positive_flag:
        parts.append("flagged false positive")
    return ", ".join(parts)


def _summarize_precedents(
    *,
    issue: CanonicalIssue,
    records: list[PrecedentIssueRecord],
    top_matches: list[PrecedentReference],
) -> PrecedentSummary:
    issue_id = issue.issue_type or issue.issue_id
    exact_type_records = [record for record in records if _record_issue_id(record) == issue_id]
    category_records = [record for record in records if record.category == issue.category]
    if exact_type_records:
        population = exact_type_records
        historical_frequency = len(exact_type_records)
    elif top_matches:
        matched_ids = {match.precedent_id for match in top_matches}
        population = [record for record in records if _record_precedent_id(record) in matched_ids]
        historical_frequency = len(population)
    else:
        population = category_records
        historical_frequency = len(category_records)

    if not population:
        return PrecedentSummary(
            confidence_adjustment="neutral",
            reasoning="No close historical analogue was found, so precedent does not adjust the current issue.",
        )

    false_positive_rate = round(
        sum(1 for record in population if record.false_positive_flag) / len(population),
        2,
    )
    resolved_real_values = [record.real_issue for record in population if record.real_issue is not None]
    real_issue_rate = (
        round(sum(1 for value in resolved_real_values if value) / len(resolved_real_values), 2)
        if resolved_real_values
        else None
    )
    outcome_stats = _outcome_stats(population)
    typical_impact = _typical_impact(outcome_stats)
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
        historical_frequency=historical_frequency,
        real_rate=real_issue_rate,
        false_positive_rate=false_positive_rate,
        outcome_stats=outcome_stats,
        typical_impact=typical_impact,
        resolution_pattern=resolution_pattern,
        confidence_adjustment=confidence_adjustment,
        score_adjustment=score_adjustment,
        sample_size=len(population),
        sparse_data=len(population) < 3,
        reasoning=_precedent_reasoning(
            false_positive_rate=false_positive_rate,
            real_issue_rate=real_issue_rate,
            typical_impact=typical_impact,
            confidence_adjustment=confidence_adjustment,
            resolution_pattern=resolution_pattern,
            sample_size=len(population),
        ),
    )


def _outcome_stats(records: list[PrecedentIssueRecord]) -> dict[str, int]:
    counts = Counter(_normalize_outcome(record.actual_outcome) for record in records)
    return {outcome: counts.get(outcome, 0) for outcome in _OUTCOME_ORDER if counts.get(outcome, 0)}


def _typical_impact(outcome_stats: dict[str, int]) -> str:
    if not outcome_stats:
        return "unknown"
    non_unknown = {key: value for key, value in outcome_stats.items() if key != "unknown"}
    ranked = sorted((non_unknown or outcome_stats).items(), key=lambda item: (-item[1], item[0]))
    if len(ranked) > 1 and ranked[0][1] == ranked[1][1]:
        top_outcomes = [label for label, count in ranked if count == ranked[0][1]]
        if "none" in top_outcomes and len(top_outcomes) > 1:
            return "mixed"
        return " / ".join(top_outcomes[:2])
    return ranked[0][0]


def _resolution_pattern(records: list[PrecedentIssueRecord], issue: CanonicalIssue) -> str:
    resolved_by_counts = Counter(
        record.resolved_by
        for record in records
        if record.resolved_by and record.resolved_by != "unknown"
    )
    lead_resolution = ""
    if resolved_by_counts:
        ranked = sorted(resolved_by_counts.items(), key=lambda item: (-item[1], item[0]))
        if len(ranked) > 1 and ranked[0][1] == ranked[1][1]:
            lead_resolution = "mixed ownership"
        else:
            lead_resolution = f"{ranked[0][0]}-led"

    notes = unique_preserve_order(
        clip_text(record.notes or record.resolution_notes, 120)
        for record in records
        if (record.notes or record.resolution_notes)
    )
    if lead_resolution and notes:
        return f"{lead_resolution}; {notes[0]}"
    if lead_resolution:
        return lead_resolution
    if notes:
        return " | ".join(notes[:2])
    return issue.what_would_resolve_it


def _confidence_adjustment(
    *,
    population_size: int,
    false_positive_rate: float,
    real_issue_rate: float | None,
    typical_impact: str,
) -> str:
    if population_size < 2:
        return "neutral"
    if false_positive_rate >= 0.45 and (real_issue_rate is None or real_issue_rate <= 0.5):
        return "down"
    if (real_issue_rate or 0.0) >= 0.75 and typical_impact not in {"none", "unknown", "mixed"}:
        return "up"
    if typical_impact == "none" and false_positive_rate >= 0.25:
        return "down"
    return "neutral"


def _score_adjustment(
    *,
    population_size: int,
    false_positive_rate: float,
    real_issue_rate: float | None,
    typical_impact: str,
    confidence_adjustment: str,
) -> int:
    if population_size == 0:
        return 0

    impact_points = {
        "cost": 5,
        "delay": 5,
        "redesign": 4,
        "mixed": 1,
        "none": -4,
        "unknown": 0,
    }.get(typical_impact, 0)
    if " / " in typical_impact:
        impact_points = 3
    raw = impact_points
    if real_issue_rate is not None:
        if real_issue_rate >= 0.75:
            raw += 3
        elif real_issue_rate <= 0.25:
            raw -= 3
    raw -= round(false_positive_rate * 8)
    if confidence_adjustment == "up":
        raw += 2
    elif confidence_adjustment == "down":
        raw -= 2

    support_factor = min(population_size, _MATCH_LIMIT) / _MATCH_LIMIT
    adjustment = round(raw * support_factor)
    if population_size < 2:
        adjustment = max(min(adjustment, 2), -2)
    return max(min(adjustment, 10), -10)


def _precedent_reasoning(
    *,
    false_positive_rate: float,
    real_issue_rate: float | None,
    typical_impact: str,
    confidence_adjustment: str,
    resolution_pattern: str,
    sample_size: int,
) -> str:
    if sample_size == 0:
        return "No precedent data is available."

    if confidence_adjustment == "down":
        base = "Historical analogues often resolved as noise or routine support clean-up unless direct deal evidence proved otherwise."
    elif confidence_adjustment == "up":
        base = f"Historical analogues were usually real and more often led to {typical_impact} than a harmless clean-up item."
    else:
        base = "Historical outcomes are mixed, so the current issue should stay anchored to the cited deal evidence first."

    if real_issue_rate is not None:
        base += f" Real issue rate is {real_issue_rate:.0%}."
    if false_positive_rate >= 0.4:
        base += " False-positive history is high enough that omission-only versions should be treated cautiously."
    if resolution_pattern:
        base += f" Typical resolution: {resolution_pattern.rstrip('.')}."
    return normalize_text(base)


def _record_store_key(record: PrecedentIssueRecord) -> tuple[str, str]:
    return (
        record.deal_id or slugify(record.deal_name or "deal"),
        _record_issue_id(record) or slugify(record.canonical_title or "issue"),
    )


def _record_issue_id(record: PrecedentIssueRecord) -> str:
    return (record.issue_id or record.issue_type or slugify(record.canonical_title or "issue")).strip()


def _record_precedent_id(record: PrecedentIssueRecord) -> str:
    if record.precedent_id:
        return record.precedent_id
    deal_id, issue_id = _record_store_key(record)
    return f"{deal_id}:{issue_id}"


def _normalize_record(record: PrecedentIssueRecord) -> PrecedentIssueRecord:
    record.issue_id = _record_issue_id(record)
    record.issue_type = record.issue_type or record.issue_id
    record.deal_id = record.deal_id or slugify(record.deal_name or "deal")
    record.precedent_id = _record_precedent_id(record)
    record.canonical_title = record.canonical_title or record.issue_id
    record.materiality = _normalize_materiality(record.materiality)
    record.actual_outcome = _normalize_outcome(record.actual_outcome)
    record.resolved_by = _normalize_resolved_by(record.resolved_by)
    record.notes = normalize_text(record.notes or record.resolution_notes or record.description)
    record.resolution_notes = record.notes
    record.description = normalize_text(record.description or record.notes)
    return record


def _serialize_precedent_record(record: PrecedentIssueRecord) -> dict[str, object]:
    return {
        "precedent_id": _record_precedent_id(record),
        "issue_id": _record_issue_id(record),
        "canonical_title": record.canonical_title,
        "category": record.category,
        "deal_id": record.deal_id,
        "deal_name": record.deal_name,
        "deal_metadata": {
            "stage": record.deal_metadata.stage,
            "geography": record.deal_metadata.region,
            "product": record.deal_metadata.product,
            "region": record.deal_metadata.region,
        },
        "evidence_basis": record.evidence_basis,
        "issue_strength": record.issue_strength,
        "false_positive_flag": record.false_positive_flag,
        "materiality": record.materiality,
        "decision_relevant": record.decision_relevant,
        "actual_outcome": record.actual_outcome,
        "resolved_by": record.resolved_by,
        "notes": record.notes,
        "real_issue": record.real_issue,
        "issue_type": record.issue_type or _record_issue_id(record),
        "description": record.description,
        "resolution_notes": record.notes,
    }


def _record_from_feedback_row(row: ReviewerIssueFeedback) -> PrecedentIssueRecord:
    false_positive_flag = bool(
        row.false_positive_flag
        or row.overstated
        or row.duplicate_of
        or row.real_issue is False
    )
    deal_id = row.deal_id or slugify(row.deal_name or "deal")
    description = normalize_text(
        " ".join(
            part
            for part in [
                row.canonical_title,
                row.category,
                row.evidence_basis,
                row.notes,
            ]
            if part
        )
    )
    return _normalize_record(
        PrecedentIssueRecord(
            precedent_id=f"{deal_id}:{row.issue_id}",
            deal_name=row.deal_name or deal_id,
            issue_type=row.issue_id,
            canonical_title=row.canonical_title or row.issue_id,
            category=row.category,
            issue_id=row.issue_id,
            deal_id=deal_id,
            description=description,
            deal_metadata=row.deal_metadata,
            evidence_basis=row.evidence_basis,
            issue_strength=row.issue_strength,
            real_issue=row.real_issue,
            materiality=row.materiality,
            decision_relevant=row.decision_relevant,
            actual_outcome=row.actual_outcome,
            false_positive_flag=false_positive_flag,
            resolved_by=row.resolved_by,
            notes=row.notes,
            resolution_notes=row.notes,
        )
    )


def _feedback_row_has_signal(row: ReviewerIssueFeedback) -> bool:
    if row.real_issue is not None:
        return True
    if row.false_positive_flag or row.duplicate_of or row.overstated or row.understated:
        return True
    if row.actual_outcome != "unknown" or row.resolved_by != "unknown":
        return True
    if row.notes:
        return True
    if row.materiality != row.model_materiality:
        return True
    if row.decision_relevant != row.model_decision_relevant:
        return True
    if row.correct_action and row.correct_action != row.model_action:
        return True
    return False


def _normalize_materiality(value: object) -> str:
    text = str(value or "medium").strip().lower()
    return text if text in {"low", "medium", "high"} else "medium"


def _normalize_outcome(value: str) -> str:
    text = value.strip().lower() or "unknown"
    return text if text in set(_OUTCOME_ORDER) else "unknown"


def _normalize_resolved_by(value: str) -> str:
    text = value.strip().lower() or "unknown"
    return text if text in {"seller", "buyer", "unknown"} else "unknown"


def _optional_bool(value: object) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"true", "yes", "1"}:
        return True
    if text in {"false", "no", "0"}:
        return False
    return None


def _blank_to_none(value: object) -> str | None:
    text = str(value or "").strip()
    return text or None
