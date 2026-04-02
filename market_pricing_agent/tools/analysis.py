"""Pricing analysis logic for recommended positioning."""
from __future__ import annotations

import math
from datetime import date
from statistics import median, pstdev
from typing import Dict, Iterable, List, Sequence

from ..schemas import AnalysisResult, BenchmarkSummary, ComparableRecord, PricingRecommendation, SourceStatus, SubjectProject

_BASE_WEIGHTS = {
    "community": 0.6,
    "resale": 0.4,
}
_QUALITY_ADJUSTMENTS = {
    "value": -0.04,
    "market": 0.0,
    "premium": 0.04,
}
_POSITION_ADJUSTMENTS = {
    "value": -0.03,
    "market": 0.0,
    "premium": 0.03,
}
_NEW_HOME_RESALE_UPLIFT = 1.05


def analyze_pricing(
    project: SubjectProject,
    records: Sequence[ComparableRecord],
    source_status: Sequence[SourceStatus],
) -> AnalysisResult:
    usable_records = [record for record in records if record.effective_price is not None]
    if not usable_records:
        raise ValueError("No comparable pricing records were extracted from the provided sources.")

    ppsf_records = [record for record in usable_records if record.price_per_sqft is not None]
    if not ppsf_records:
        raise ValueError("No records included both price and living area, so price-per-sqft could not be calculated.")

    grouped_records = {
        "community": [record for record in usable_records if record.source_kind == "community"],
        "resale": [record for record in usable_records if record.source_kind == "resale"],
    }
    benchmark_summaries = [_build_benchmark_summary(kind, items) for kind, items in grouped_records.items() if items]

    market_anchor_ppsf = _build_market_anchor(project, grouped_records)
    strategy_adjustment = _QUALITY_ADJUSTMENTS[project.quality_tier] + _POSITION_ADJUSTMENTS[project.target_position]
    suggested_price_psf = market_anchor_ppsf * (1.0 + strategy_adjustment)
    band = _estimate_range_band(ppsf_records)
    suggested_price_psf_low = suggested_price_psf * (1.0 - band)
    suggested_price_psf_high = suggested_price_psf * (1.0 + band)

    suggested_base_price = suggested_price_psf * project.avg_living_area_sqft
    suggested_base_price_low = suggested_price_psf_low * project.avg_living_area_sqft
    suggested_base_price_high = suggested_price_psf_high * project.avg_living_area_sqft

    position_delta_vs_market = (suggested_price_psf / market_anchor_ppsf) - 1.0
    position_label = _classify_position(position_delta_vs_market)

    warnings = _build_warnings(records, grouped_records, source_status)
    confidence_score = _estimate_confidence(ppsf_records, grouped_records, source_status, warnings)

    rationale = _build_rationale(
        project=project,
        grouped_records=grouped_records,
        market_anchor_ppsf=market_anchor_ppsf,
        suggested_price_psf=suggested_price_psf,
        position_delta_vs_market=position_delta_vs_market,
    )

    recommendation = PricingRecommendation(
        position_label=position_label,
        market_anchor_price_psf=round(market_anchor_ppsf, 2),
        suggested_price_psf=round(suggested_price_psf, 2),
        suggested_price_psf_low=round(suggested_price_psf_low, 2),
        suggested_price_psf_high=round(suggested_price_psf_high, 2),
        suggested_base_price=round(suggested_base_price, 0),
        suggested_base_price_low=round(suggested_base_price_low, 0),
        suggested_base_price_high=round(suggested_base_price_high, 0),
        position_delta_vs_market=round(position_delta_vs_market, 4),
        confidence_score=round(confidence_score, 3),
        rationale=rationale,
    )

    top_comps = _select_top_comps(project, ppsf_records)
    return AnalysisResult(
        project=project,
        extracted_comp_count=len(records),
        benchmark_summaries=benchmark_summaries,
        recommendation=recommendation,
        warnings=warnings,
        source_status=list(source_status),
        normalized_comps=list(records),
        top_comps=top_comps,
    )


def _build_benchmark_summary(kind: str, records: Sequence[ComparableRecord]) -> BenchmarkSummary:
    priced = [record.effective_price for record in records if record.effective_price is not None]
    ppsf_values = [record.price_per_sqft for record in records if record.price_per_sqft is not None]

    weighted_avg_psf = None
    if ppsf_values:
        weights = [_record_weight(record, None) for record in records if record.price_per_sqft is not None]
        weighted_avg_psf = _weighted_average([value for value in ppsf_values if value is not None], weights)

    return BenchmarkSummary(
        source_kind=kind,
        comp_count=len(records),
        usable_ppsf_count=len(ppsf_values),
        weighted_avg_price_psf=round(weighted_avg_psf, 2) if weighted_avg_psf is not None else None,
        median_price_psf=round(float(median(ppsf_values)), 2) if ppsf_values else None,
        median_price=round(float(median(priced)), 0) if priced else None,
        min_price=round(min(priced), 0) if priced else None,
        max_price=round(max(priced), 0) if priced else None,
    )


def _build_market_anchor(project: SubjectProject, grouped_records: Dict[str, List[ComparableRecord]]) -> float:
    component_values: Dict[str, float] = {}
    component_weights: Dict[str, float] = {}

    community_records = [record for record in grouped_records["community"] if record.price_per_sqft is not None]
    if community_records:
        community_weights = [_record_weight(record, project) for record in community_records]
        component_values["community"] = _weighted_average(
            [record.price_per_sqft for record in community_records if record.price_per_sqft is not None],
            community_weights,
        )
        component_weights["community"] = _BASE_WEIGHTS["community"]

    resale_records = [record for record in grouped_records["resale"] if record.price_per_sqft is not None]
    if resale_records:
        resale_weights = [_record_weight(record, project) for record in resale_records]
        resale_anchor = _weighted_average(
            [record.price_per_sqft for record in resale_records if record.price_per_sqft is not None],
            resale_weights,
        )
        component_values["resale"] = resale_anchor * _NEW_HOME_RESALE_UPLIFT
        component_weights["resale"] = _BASE_WEIGHTS["resale"]

    if not component_values:
        raise ValueError("Unable to compute a market anchor because no price-per-sqft comps were available.")

    total_weight = sum(component_weights.values())
    return sum(component_values[key] * component_weights[key] for key in component_values) / total_weight


def _record_weight(record: ComparableRecord, project: SubjectProject | None) -> float:
    weight = 1.0
    if project is not None and record.effective_sqft is not None and project.avg_living_area_sqft > 0:
        diff_ratio = abs(record.effective_sqft - project.avg_living_area_sqft) / project.avg_living_area_sqft
        weight *= max(0.35, 1.0 - diff_ratio)

    if record.source_kind == "resale":
        if record.sale_date is None:
            weight *= 0.6
        else:
            age_days = max(0, (date.today() - record.sale_date).days)
            weight *= max(0.25, math.exp(-age_days / 210.0))

    return weight


def _weighted_average(values: Sequence[float | None], weights: Sequence[float]) -> float:
    pairs = [(value, weight) for value, weight in zip(values, weights) if value is not None and weight > 0]
    if not pairs:
        raise ValueError("Weighted average requires at least one positive-weight value.")
    numerator = sum(value * weight for value, weight in pairs)
    denominator = sum(weight for _, weight in pairs)
    return numerator / denominator


def _estimate_range_band(records: Sequence[ComparableRecord]) -> float:
    ppsf_values = [record.price_per_sqft for record in records if record.price_per_sqft is not None]
    if len(ppsf_values) < 2:
        return 0.05
    mean_value = sum(ppsf_values) / len(ppsf_values)
    if mean_value <= 0:
        return 0.05
    normalized_dispersion = pstdev(ppsf_values) / mean_value
    return min(0.08, max(0.03, normalized_dispersion * 0.75))


def _classify_position(position_delta_vs_market: float) -> str:
    if position_delta_vs_market <= -0.025:
        return "value"
    if position_delta_vs_market >= 0.025:
        return "premium"
    return "market"


def _build_warnings(
    records: Sequence[ComparableRecord],
    grouped_records: Dict[str, List[ComparableRecord]],
    source_status: Sequence[SourceStatus],
) -> List[str]:
    warnings: List[str] = []
    community_count = len([record for record in grouped_records["community"] if record.price_per_sqft is not None])
    resale_count = len([record for record in grouped_records["resale"] if record.price_per_sqft is not None])

    if community_count < 2:
        warnings.append("Fewer than two usable new-community comps were available; builder benchmark depth is light.")
    if resale_count < 3:
        warnings.append("Fewer than three usable resale comps were available; resale benchmark depth is light.")

    missing_sqft = len([record for record in records if record.effective_price is not None and record.price_per_sqft is None])
    if missing_sqft:
        warnings.append(f"{missing_sqft} extracted records had pricing but no living area, so they were excluded from the price-per-sqft anchor.")

    failed_sources = [item for item in source_status if item.status == "error"]
    for item in failed_sources:
        warnings.append(f"Source '{item.name}' failed: {item.error}")

    empty_sources = [item for item in source_status if item.status == "warning"]
    for item in empty_sources:
        warnings.append(f"Source '{item.name}' returned no usable records.")

    return warnings


def _estimate_confidence(
    ppsf_records: Sequence[ComparableRecord],
    grouped_records: Dict[str, List[ComparableRecord]],
    source_status: Sequence[SourceStatus],
    warnings: Sequence[str],
) -> float:
    score = 0.45
    score += min(0.2, len(ppsf_records) * 0.03)
    if grouped_records["community"]:
        score += 0.12
    if grouped_records["resale"]:
        score += 0.12
    score -= min(0.18, len(warnings) * 0.04)
    error_count = len([item for item in source_status if item.status == "error"])
    score -= min(0.1, error_count * 0.05)
    return max(0.2, min(0.95, score))


def _build_rationale(
    project: SubjectProject,
    grouped_records: Dict[str, List[ComparableRecord]],
    market_anchor_ppsf: float,
    suggested_price_psf: float,
    position_delta_vs_market: float,
) -> List[str]:
    rationale = [
        f"Blended market anchor is ${market_anchor_ppsf:,.2f} per sqft for {project.submarket}.",
        f"Recommended pricing is ${suggested_price_psf:,.2f} per sqft, or {position_delta_vs_market * 100:.1f}% versus the current market anchor.",
    ]

    community_records = [record for record in grouped_records["community"] if record.price_per_sqft is not None]
    if community_records:
        community_avg = sum(record.price_per_sqft for record in community_records if record.price_per_sqft is not None) / len(community_records)
        rationale.append(
            f"New-home community comps average about ${community_avg:,.2f} per sqft across {len(community_records)} usable records."
        )

    resale_records = [record for record in grouped_records["resale"] if record.price_per_sqft is not None]
    if resale_records:
        resale_avg = sum(record.price_per_sqft for record in resale_records if record.price_per_sqft is not None) / len(resale_records)
        rationale.append(
            f"Recent resales average about ${resale_avg:,.2f} per sqft before the new-construction uplift."
        )

    if project.target_position != "market":
        rationale.append(
            f"Target positioning was set to '{project.target_position}', so the recommendation intentionally shifts away from pure market parity."
        )
    if project.quality_tier != "market":
        rationale.append(
            f"Project quality tier was set to '{project.quality_tier}', and the pricing recommendation reflects that product-level premium or discount."
        )

    return rationale


def _select_top_comps(project: SubjectProject, records: Sequence[ComparableRecord]) -> List[ComparableRecord]:
    def score(record: ComparableRecord) -> tuple[float, int]:
        size_gap = abs((record.effective_sqft or project.avg_living_area_sqft) - project.avg_living_area_sqft)
        days_old = (date.today() - record.sale_date).days if record.sale_date else 0
        return (size_gap, days_old)

    return sorted(records, key=score)[:5]