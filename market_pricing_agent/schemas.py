"""Shared schemas for the market pricing agent."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any, Dict, List, Literal, Optional

SourceKind = Literal["community", "resale"]
SourceType = Literal["html", "csv", "json"]
PricingPosition = Literal["value", "market", "premium"]


def _validate_position(value: str, field_name: str) -> None:
    if value not in {"value", "market", "premium"}:
        raise ValueError(f"{field_name} must be one of: value, market, premium")


@dataclass(frozen=True)
class SubjectProject:
    name: str
    submarket: str
    product_type: str
    avg_living_area_sqft: float
    quality_tier: PricingPosition = "market"
    target_position: PricingPosition = "market"
    bedrooms: Optional[float] = None
    bathrooms: Optional[float] = None
    garage_spaces: Optional[float] = None
    lot_width_ft: Optional[float] = None
    notes: str = ""

    def validate(self) -> None:
        if not self.name.strip():
            raise ValueError("Project name cannot be empty.")
        if not self.submarket.strip():
            raise ValueError("Project submarket cannot be empty.")
        if not self.product_type.strip():
            raise ValueError("Project product_type cannot be empty.")
        if self.avg_living_area_sqft <= 0:
            raise ValueError("avg_living_area_sqft must be greater than zero.")
        _validate_position(self.quality_tier, "quality_tier")
        _validate_position(self.target_position, "target_position")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "submarket": self.submarket,
            "product_type": self.product_type,
            "avg_living_area_sqft": self.avg_living_area_sqft,
            "quality_tier": self.quality_tier,
            "target_position": self.target_position,
            "bedrooms": self.bedrooms,
            "bathrooms": self.bathrooms,
            "garage_spaces": self.garage_spaces,
            "lot_width_ft": self.lot_width_ft,
            "notes": self.notes,
        }


@dataclass(frozen=True)
class DataSource:
    name: str
    kind: SourceKind
    source_type: SourceType
    location: str
    submarket: str = ""
    field_map: Dict[str, str] = field(default_factory=dict)
    headers: Dict[str, str] = field(default_factory=dict)

    def validate(self) -> None:
        if not self.name.strip():
            raise ValueError("Source name cannot be empty.")
        if self.kind not in {"community", "resale"}:
            raise ValueError("Source kind must be either 'community' or 'resale'.")
        if self.source_type not in {"html", "csv", "json"}:
            raise ValueError("Source type must be html, csv, or json.")
        if not self.location.strip():
            raise ValueError("Source location cannot be empty.")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "kind": self.kind,
            "source_type": self.source_type,
            "location": self.location,
            "submarket": self.submarket,
            "field_map": dict(self.field_map),
            "headers": dict(self.headers),
        }


@dataclass(frozen=True)
class ComparableRecord:
    source_name: str
    source_kind: SourceKind
    record_name: str
    submarket: str
    address: Optional[str] = None
    price: Optional[float] = None
    price_low: Optional[float] = None
    price_high: Optional[float] = None
    living_area_sqft: Optional[float] = None
    sqft_low: Optional[float] = None
    sqft_high: Optional[float] = None
    bedrooms: Optional[float] = None
    bathrooms: Optional[float] = None
    sale_date: Optional[date] = None
    year_built: Optional[int] = None
    is_new_construction: bool = False
    extracted_from: str = ""
    notes: str = ""

    @property
    def effective_price(self) -> Optional[float]:
        if self.price is not None:
            return self.price
        if self.price_low is not None and self.price_high is not None:
            return (self.price_low + self.price_high) / 2.0
        if self.price_low is not None:
            return self.price_low
        if self.price_high is not None:
            return self.price_high
        return None

    @property
    def effective_sqft(self) -> Optional[float]:
        if self.living_area_sqft is not None:
            return self.living_area_sqft
        if self.sqft_low is not None and self.sqft_high is not None:
            return (self.sqft_low + self.sqft_high) / 2.0
        if self.sqft_low is not None:
            return self.sqft_low
        if self.sqft_high is not None:
            return self.sqft_high
        return None

    @property
    def price_per_sqft(self) -> Optional[float]:
        price_value = self.effective_price
        sqft_value = self.effective_sqft
        if price_value is None or sqft_value is None or sqft_value <= 0:
            return None
        return price_value / sqft_value

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source_name": self.source_name,
            "source_kind": self.source_kind,
            "record_name": self.record_name,
            "submarket": self.submarket,
            "address": self.address,
            "price": self.price,
            "price_low": self.price_low,
            "price_high": self.price_high,
            "living_area_sqft": self.living_area_sqft,
            "sqft_low": self.sqft_low,
            "sqft_high": self.sqft_high,
            "bedrooms": self.bedrooms,
            "bathrooms": self.bathrooms,
            "sale_date": self.sale_date.isoformat() if self.sale_date else None,
            "year_built": self.year_built,
            "is_new_construction": self.is_new_construction,
            "extracted_from": self.extracted_from,
            "notes": self.notes,
            "effective_price": self.effective_price,
            "effective_sqft": self.effective_sqft,
            "price_per_sqft": self.price_per_sqft,
        }


@dataclass(frozen=True)
class SourceStatus:
    name: str
    kind: SourceKind
    location: str
    status: str
    records_extracted: int
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "kind": self.kind,
            "location": self.location,
            "status": self.status,
            "records_extracted": self.records_extracted,
            "error": self.error,
        }


@dataclass(frozen=True)
class BenchmarkSummary:
    source_kind: SourceKind
    comp_count: int
    usable_ppsf_count: int
    weighted_avg_price_psf: Optional[float]
    median_price_psf: Optional[float]
    median_price: Optional[float]
    min_price: Optional[float]
    max_price: Optional[float]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source_kind": self.source_kind,
            "comp_count": self.comp_count,
            "usable_ppsf_count": self.usable_ppsf_count,
            "weighted_avg_price_psf": self.weighted_avg_price_psf,
            "median_price_psf": self.median_price_psf,
            "median_price": self.median_price,
            "min_price": self.min_price,
            "max_price": self.max_price,
        }


@dataclass(frozen=True)
class PricingRecommendation:
    position_label: PricingPosition
    market_anchor_price_psf: float
    suggested_price_psf: float
    suggested_price_psf_low: float
    suggested_price_psf_high: float
    suggested_base_price: float
    suggested_base_price_low: float
    suggested_base_price_high: float
    position_delta_vs_market: float
    confidence_score: float
    rationale: List[str]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "position_label": self.position_label,
            "market_anchor_price_psf": self.market_anchor_price_psf,
            "suggested_price_psf": self.suggested_price_psf,
            "suggested_price_psf_low": self.suggested_price_psf_low,
            "suggested_price_psf_high": self.suggested_price_psf_high,
            "suggested_base_price": self.suggested_base_price,
            "suggested_base_price_low": self.suggested_base_price_low,
            "suggested_base_price_high": self.suggested_base_price_high,
            "position_delta_vs_market": self.position_delta_vs_market,
            "confidence_score": self.confidence_score,
            "rationale": list(self.rationale),
        }


@dataclass(frozen=True)
class AnalysisResult:
    project: SubjectProject
    extracted_comp_count: int
    benchmark_summaries: List[BenchmarkSummary]
    recommendation: PricingRecommendation
    warnings: List[str]
    source_status: List[SourceStatus]
    normalized_comps: List[ComparableRecord]
    top_comps: List[ComparableRecord]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "project": self.project.to_dict(),
            "extracted_comp_count": self.extracted_comp_count,
            "benchmark_summaries": [item.to_dict() for item in self.benchmark_summaries],
            "recommendation": self.recommendation.to_dict(),
            "warnings": list(self.warnings),
            "source_status": [item.to_dict() for item in self.source_status],
            "normalized_comps": [item.to_dict() for item in self.normalized_comps],
            "top_comps": [item.to_dict() for item in self.top_comps],
        }