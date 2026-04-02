"""Report rendering and persistence for pricing recommendations."""
from __future__ import annotations

import csv
import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from ..schemas import AnalysisResult


@dataclass(frozen=True)
class OutputArtifacts:
    run_dir: Path
    report_path: Path
    analysis_path: Path
    comps_path: Path


def write_outputs(result: AnalysisResult, output_root: Path | str) -> OutputArtifacts:
    output_root_path = Path(output_root)
    output_root_path.mkdir(parents=True, exist_ok=True)

    slug = _slugify(result.project.name)
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    run_dir = output_root_path / f"{slug}_{timestamp}"
    run_dir.mkdir(parents=True, exist_ok=False)

    report_path = run_dir / "pricing_report.md"
    analysis_path = run_dir / "analysis.json"
    comps_path = run_dir / "normalized_comps.csv"

    report_path.write_text(render_markdown_report(result), encoding="utf-8")
    analysis_path.write_text(json.dumps(result.to_dict(), indent=2), encoding="utf-8")
    _write_comps_csv(result, comps_path)

    return OutputArtifacts(
        run_dir=run_dir,
        report_path=report_path,
        analysis_path=analysis_path,
        comps_path=comps_path,
    )


def render_markdown_report(result: AnalysisResult) -> str:
    recommendation = result.recommendation
    project = result.project

    lines = [
        f"# Pricing Position Recommendation: {project.name}",
        "",
        "## Project",
        f"- Submarket: {project.submarket}",
        f"- Product type: {project.product_type}",
        f"- Average living area: {project.avg_living_area_sqft:,.0f} sqft",
        f"- Quality tier: {project.quality_tier}",
        f"- Target position: {project.target_position}",
        "",
        "## Recommendation",
        f"- Suggested pricing position: {recommendation.position_label}",
        f"- Market anchor: ${recommendation.market_anchor_price_psf:,.2f} per sqft",
        f"- Recommended range: ${recommendation.suggested_price_psf_low:,.2f} to ${recommendation.suggested_price_psf_high:,.2f} per sqft",
        f"- Recommended base price: ${recommendation.suggested_base_price_low:,.0f} to ${recommendation.suggested_base_price_high:,.0f}",
        f"- Point estimate: ${recommendation.suggested_base_price:,.0f}",
        f"- Confidence score: {recommendation.confidence_score * 100:,.0f} / 100",
        "",
        "## Rationale",
    ]

    for item in recommendation.rationale:
        lines.append(f"- {item}")

    lines.extend([
        "",
        "## Benchmarks",
        "| Segment | Comp count | Usable ppsf count | Weighted avg ppsf | Median ppsf | Median price | Range |",
        "| --- | ---: | ---: | ---: | ---: | ---: | --- |",
    ])
    for benchmark in result.benchmark_summaries:
        price_range = "n/a"
        if benchmark.min_price is not None and benchmark.max_price is not None:
            price_range = f"${benchmark.min_price:,.0f} to ${benchmark.max_price:,.0f}"
        lines.append(
            "| {segment} | {comp_count} | {ppsf_count} | {weighted_avg} | {median_psf} | {median_price} | {price_range} |".format(
                segment=benchmark.source_kind,
                comp_count=benchmark.comp_count,
                ppsf_count=benchmark.usable_ppsf_count,
                weighted_avg=_format_float(benchmark.weighted_avg_price_psf),
                median_psf=_format_float(benchmark.median_price_psf),
                median_price=_format_currency(benchmark.median_price),
                price_range=price_range,
            )
        )

    lines.extend(["", "## Top Comps"])
    if result.top_comps:
        lines.extend([
            "| Source | Record | Kind | Price | Sqft | Price/sqft | Sale date |",
            "| --- | --- | --- | ---: | ---: | ---: | --- |",
        ])
        for comp in result.top_comps:
            lines.append(
                "| {source} | {record} | {kind} | {price} | {sqft} | {ppsf} | {sale_date} |".format(
                    source=comp.source_name,
                    record=comp.record_name,
                    kind=comp.source_kind,
                    price=_format_currency(comp.effective_price),
                    sqft=_format_float(comp.effective_sqft),
                    ppsf=_format_currency(comp.price_per_sqft),
                    sale_date=comp.sale_date.isoformat() if comp.sale_date else "n/a",
                )
            )
    else:
        lines.append("- No top comps were selected.")

    if result.warnings:
        lines.extend(["", "## Warnings"])
        for warning in result.warnings:
            lines.append(f"- {warning}")

    lines.extend(["", "## Source Status"])
    for status in result.source_status:
        status_line = f"- {status.name}: {status.status} ({status.records_extracted} records)"
        if status.error:
            status_line += f" - {status.error}"
        lines.append(status_line)

    return "\n".join(lines) + "\n"


def _write_comps_csv(result: AnalysisResult, path: Path) -> None:
    rows = [item.to_dict() for item in result.normalized_comps]
    if not rows:
        path.write_text("", encoding="utf-8")
        return

    headers = list(rows[0].keys())
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=headers)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "_", value.strip().lower())
    return slug.strip("_") or "pricing_run"


def _format_float(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:,.2f}"


def _format_currency(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"${value:,.2f}"