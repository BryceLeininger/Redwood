"""DOCX reporting for the local due diligence workflow."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from docx import Document
from docx.shared import Pt

from land_due_diligence_agent.deal_models import ConflictRecord, DealRunResult, FactRecord, MissingItem, SourceReference
from land_due_diligence_agent.models import CanonicalIssue, Citation, DealSynthesis, OmissionAssessment
from land_due_diligence_agent.utils.files import ensure_directory
from land_due_diligence_agent.utils.text import clip_text, unique_preserve_order

_MATERIAL_ISSUE_CATEGORIES = {
    "Title / Access Concerns",
    "Entitlement Status",
    "Environmental Risks",
    "Geotechnical Risks",
    "Flood / Drainage Issues",
    "Utilities / Infrastructure Issues",
    "Offsite Obligations",
    "Fee / Exaction Burden",
    "Budget / Cost Reliability",
    "Schedule Risks",
}
_CONFLICT_TYPE_ORDER = {
    "purchase_price": 0,
    "gross_acreage": 1,
    "net_acreage": 2,
    "site_acreage": 3,
    "lot_count": 4,
    "unit_count": 5,
    "zoning": 6,
    "jurisdiction": 7,
    "owner_name": 8,
    "apn": 9,
}
_PRODUCT_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("single-family detached product", ("single family", "single-family", "detached")),
    ("townhome product", ("townhome", "town house")),
    ("multifamily product", ("multifamily", "apartment", "stacked flat")),
    ("industrial product", ("industrial", "warehouse", "distribution")),
    ("commercial product", ("commercial", "retail", "office")),
)
_SECTION_EMPTY_TEXT = {
    "Entitlement & Zoning": "Current zoning, jurisdiction, and approval status are not cleanly established from readable planning support.",
    "Site & Product": "Controlling acreage, yield, and layout support are not cleanly established from the current package.",
    "Title & Ownership": "Title, vesting, and access support are not complete enough to treat ownership and closability as closed.",
    "Environmental & Geotech": "No decision-grade environmental, geotechnical, or drainage support currently closes this lane.",
    "Utilities & Infrastructure": "Utility, frontage, and infrastructure support remain incomplete or only partially established.",
    "Fees / Cost Drivers": "Fee, budget, and site-cost support are not current enough to lock basis with confidence.",
}
_MISSING_STATUS_ORDER = {
    "missing and important": 0,
    "conflicting across documents": 1,
    "stale and potentially unreliable": 2,
    "missing but normally expected": 3,
}
_FRONT_END_PRIORITY = {
    "red flag": 0,
    "conflict / contradiction concern": 1,
    "yellow flag": 2,
    "stale-information concern": 3,
    "document gap": 4,
    "routine item": 5,
}
_ACQUISITION_SEVERITY_PRIORITY = {
    "CRITICAL": 0,
    "HIGH": 1,
    "MODERATE": 2,
    "LOW": 3,
}


@dataclass(slots=True)
class _SectionBullet:
    text: str
    references: list[str] = field(default_factory=list)
    note: str = ""


def write_due_diligence_report_docx(path: Path, result: DealRunResult) -> Path:
    """Write the primary due diligence report as a Word document."""

    ensure_directory(path.parent)
    document = Document()
    _configure_document(document)

    document.add_heading("Land Due Diligence Memo", level=0)
    document.add_paragraph(f"Deal: {result.deal_name}")
    document.add_paragraph(f"Generated: {datetime.now().astimezone().isoformat(timespec='minutes')}")

    if result.deal_synthesis is None:
        _write_minimal_report(document, result)
    else:
        _write_structured_report(document, result, result.deal_synthesis)

    document.save(path)
    return path


def _configure_document(document: Document) -> None:
    normal = document.styles["Normal"]
    normal.font.name = "Calibri"
    normal.font.size = Pt(10.5)
    normal.paragraph_format.space_after = Pt(4)

    heading_1 = document.styles["Heading 1"]
    heading_1.font.name = "Calibri"
    heading_1.font.size = Pt(14)
    heading_1.paragraph_format.space_before = Pt(14)
    heading_1.paragraph_format.space_after = Pt(4)

    heading_2 = document.styles["Heading 2"]
    heading_2.font.name = "Calibri"
    heading_2.font.size = Pt(11.5)
    heading_2.paragraph_format.space_before = Pt(10)
    heading_2.paragraph_format.space_after = Pt(2)

    list_bullet = document.styles["List Bullet"]
    list_bullet.font.name = "Calibri"
    list_bullet.font.size = Pt(10.5)
    list_bullet.paragraph_format.space_after = Pt(2)

    list_number = document.styles["List Number"]
    list_number.font.name = "Calibri"
    list_number.font.size = Pt(10.5)
    list_number.paragraph_format.space_after = Pt(2)


def _write_minimal_report(document: Document, result: DealRunResult) -> None:
    _add_section(document, "Executive Summary")
    _add_bullet_items(
        document,
        [
            _SectionBullet(
                text="No readable document set was available for decision-grade analysis, so the deal facts and risk profile remain unresolved.",
            )
        ],
    )

    _add_section(document, "Missing Information")
    if result.failed_files:
        _add_bullet_items(
            document,
            [
                _SectionBullet(
                    text=f"{result.failed_files} file(s) failed extraction and require direct manual review before relying on the package.",
                )
            ],
        )
    else:
        _add_bullet_items(
            document,
            [
                _SectionBullet(
                    text="The report could not assemble decision-grade support from the current package.",
                )
            ],
        )


def _write_structured_report(document: Document, result: DealRunResult, synthesis: DealSynthesis) -> None:
    fact_index = _build_fact_index(result.issue_registry.facts)
    material_issues = _material_issues(synthesis)
    material_conflicts = _material_conflicts(result.issue_registry.conflicts)
    critical_missing = _critical_missing_assessments(synthesis)

    _add_executive_summary(
        document=document,
        result=result,
        synthesis=synthesis,
        fact_index=fact_index,
        material_issues=material_issues,
        critical_missing=critical_missing,
    )
    _add_deal_overview(document, result, synthesis, fact_index)
    _add_gating_items_section(document, synthesis, material_issues)
    _add_category_section(
        document=document,
        title="Entitlement & Zoning",
        synthesis=synthesis,
        result=result,
        fact_index=fact_index,
        material_conflicts=material_conflicts,
        fact_types=("jurisdiction", "zoning"),
        issue_categories={"Entitlement Status"},
        omission_categories={"Entitlement Status"},
        first_pass_missing_categories={"Entitlement / Planning / Conditions"},
        conflict_types={"zoning", "jurisdiction"},
    )
    _add_category_section(
        document=document,
        title="Site & Product",
        synthesis=synthesis,
        result=result,
        fact_index=fact_index,
        material_conflicts=material_conflicts,
        fact_types=("gross_acreage", "net_acreage", "site_acreage", "lot_count", "unit_count"),
        issue_categories=set(),
        omission_categories=set(),
        first_pass_missing_categories={"Map / Plat / Improvement Plans", "Financial / underwriting support"},
        conflict_types={"gross_acreage", "net_acreage", "site_acreage", "lot_count", "unit_count"},
    )
    _add_category_section(
        document=document,
        title="Title & Ownership",
        synthesis=synthesis,
        result=result,
        fact_index=fact_index,
        material_conflicts=material_conflicts,
        fact_types=("apn", "owner_name"),
        issue_categories={"Title / Access Concerns"},
        omission_categories={"Title / Access Concerns"},
        first_pass_missing_categories={"Title", "Vesting / Legal"},
        conflict_types={"apn", "owner_name"},
    )
    _add_category_section(
        document=document,
        title="Environmental & Geotech",
        synthesis=synthesis,
        result=result,
        fact_index=fact_index,
        material_conflicts=material_conflicts,
        fact_types=(),
        issue_categories={"Environmental Risks", "Geotechnical Risks", "Flood / Drainage Issues"},
        omission_categories={"Environmental Risks", "Geotechnical Risks", "Flood / Drainage Issues"},
        first_pass_missing_categories={"Environmental", "Geotech / Soils"},
        conflict_types=set(),
    )
    _add_category_section(
        document=document,
        title="Utilities & Infrastructure",
        synthesis=synthesis,
        result=result,
        fact_index=fact_index,
        material_conflicts=material_conflicts,
        fact_types=(),
        issue_categories={"Utilities / Infrastructure Issues", "Offsite Obligations"},
        omission_categories={"Utilities / Infrastructure Issues"},
        first_pass_missing_categories={"Utilities", "Map / Plat / Improvement Plans"},
        conflict_types=set(),
    )
    _add_category_section(
        document=document,
        title="Fees / Cost Drivers",
        synthesis=synthesis,
        result=result,
        fact_index=fact_index,
        material_conflicts=material_conflicts,
        fact_types=("purchase_price",),
        issue_categories={"Fee / Exaction Burden", "Budget / Cost Reliability"},
        omission_categories={"Fee / Exaction Burden", "Budget / Cost Reliability"},
        first_pass_missing_categories={"Purchase / Sale / Contract"},
        conflict_types={"purchase_price"},
    )
    _add_key_risks_section(document, material_issues)
    _add_recommended_next_steps_section(document, synthesis, material_issues, critical_missing)
    _add_missing_information_section(document, result, synthesis, critical_missing)
    _add_questions_for_seller_section(document, material_issues, critical_missing)


def _add_executive_summary(
    *,
    document: Document,
    result: DealRunResult,
    synthesis: DealSynthesis,
    fact_index: dict[str, list[FactRecord]],
    material_issues: list[CanonicalIssue],
    critical_missing: list[OmissionAssessment],
) -> None:
    _add_section(document, "Executive Summary")

    _add_subsection(document, "IC Read")
    _add_bullet_items(
        document,
        [
            _SectionBullet(text=clip_text(synthesis.executive_summary, 420)),
            _SectionBullet(
                text=(
                    f"Current recommendation posture: {synthesis.recommendation.posture}. "
                    f"This is being driven by {', '.join(issue.title for issue in material_issues[:2]) or 'the current package quality and unresolved diligence items'}.")
            ),
        ],
    )

    _add_subsection(document, "Deal Snapshot")
    _add_bullet_items(
        document,
        [
            _build_snapshot_bullet(result, synthesis, fact_index),
            _SectionBullet(
                text=(
                    f"Package quality currently reads as {synthesis.canonical_issue_registry.package_quality or 'mixed'} "
                    f"with {synthesis.canonical_issue_registry.confidence_in_initial_read} confidence on initial read."
                ),
            ),
        ],
    )

    _add_subsection(document, "Known With High Confidence")
    high_confidence = _build_high_confidence_bullets(fact_index, material_issues)
    if not high_confidence:
        high_confidence = [
            _SectionBullet(
                text="No core deal descriptor appears clearly in multiple readable documents; location, scale, and product should still be treated as provisional.",
            )
        ]
    _add_bullet_items(document, high_confidence)

    _add_subsection(document, "Top Risks")
    top_risks = [
        _SectionBullet(
            text=f"{issue.title}: {_issue_summary_line(issue)}",
            references=_issue_reference_labels(issue),
        )
        for issue in material_issues[:5]
    ]
    _add_bullet_items(
        document,
        top_risks or [_SectionBullet(text="No material risk was isolated above routine diligence noise in the current package.")],
    )

    _add_subsection(document, "Missing Critical Inputs")
    missing_summary = _missing_summary_bullets(result, critical_missing)
    _add_bullet_items(
        document,
        missing_summary or [_SectionBullet(text="No additional critical missing item was isolated beyond the current issue set.")],
    )


def _add_gating_items_section(
    document: Document,
    synthesis: DealSynthesis,
    material_issues: list[CanonicalIssue],
) -> None:
    _add_section(document, "Deal Killers / Gating Items")
    roadmap_items = synthesis.further_diligence_roadmap.deal_killers_or_gating_items[:6]
    if roadmap_items:
        _add_bullet_items(document, [_SectionBullet(text=item) for item in roadmap_items])
        return

    gating_issues = [issue for issue in material_issues if issue.gating_item][:5]
    if not gating_issues:
        _add_bullet_items(
            document,
            [_SectionBullet(text="No current issue reads as a clear deal killer, but the deal still depends on resolving the highest-severity open items.")],
        )
        return

    _add_bullet_items(
        document,
        [
            _SectionBullet(
                text=f"{issue.title} [{issue.acquisition_severity}]: {_issue_deal_impact(issue)}",
                references=_issue_reference_labels(issue),
            )
            for issue in gating_issues
        ],
    )


def _add_deal_overview(
    document: Document,
    result: DealRunResult,
    synthesis: DealSynthesis,
    fact_index: dict[str, list[FactRecord]],
) -> None:
    _add_section(document, "Deal Overview")
    bullets = [
        _build_location_bullet(fact_index),
        _build_scale_bullet(fact_index),
        _build_product_bullet(result, fact_index),
        _build_price_bullet(fact_index),
        _SectionBullet(
            text=f"Entitlement stage: {clip_text(synthesis.entitlement_status, 180)}",
        ),
    ]
    _add_bullet_items(document, [bullet for bullet in bullets if bullet.text])


def _add_category_section(
    *,
    document: Document,
    title: str,
    synthesis: DealSynthesis,
    result: DealRunResult,
    fact_index: dict[str, list[FactRecord]],
    material_conflicts: list[ConflictRecord],
    fact_types: tuple[str, ...],
    issue_categories: set[str],
    omission_categories: set[str],
    first_pass_missing_categories: set[str],
    conflict_types: set[str],
) -> None:
    _add_section(document, title)
    bullets = _build_category_bullets(
        synthesis=synthesis,
        result=result,
        fact_index=fact_index,
        material_conflicts=material_conflicts,
        fact_types=fact_types,
        issue_categories=issue_categories,
        omission_categories=omission_categories,
        first_pass_missing_categories=first_pass_missing_categories,
        conflict_types=conflict_types,
    )
    _add_bullet_items(
        document,
        bullets or [_SectionBullet(text=_SECTION_EMPTY_TEXT[title])],
    )


def _add_key_risks_section(document: Document, material_issues: list[CanonicalIssue]) -> None:
    _add_section(document, "Key Risks & Open Issues")
    if not material_issues:
        _add_bullet_items(
            document,
            [_SectionBullet(text="No material issue rose above routine diligence noise in the current package.")],
        )
        return

    for issue in material_issues[:5]:
        _add_subsection(document, issue.title)
        _add_bullet_items(
            document,
            [
                _SectionBullet(text=f"Severity / gating: {_issue_severity_line(issue)}"),
                _SectionBullet(text=f"What it is: {_issue_what_line(issue)}"),
                _SectionBullet(text=f"Likely explanation: {_issue_likely_explanation(issue)}"),
                _SectionBullet(text=f"Deal impact: {_issue_deal_impact(issue)}", references=_issue_reference_labels(issue)),
                _SectionBullet(text=f"Likely reality vs noise: {_issue_reality_vs_noise(issue)}"),
                _SectionBullet(text=f"Needed to clear: {_issue_request_text(issue)}"),
            ],
        )


def _add_recommended_next_steps_section(
    document: Document,
    synthesis: DealSynthesis,
    material_issues: list[CanonicalIssue],
    critical_missing: list[OmissionAssessment],
) -> None:
    _add_section(document, "Recommended Next Steps")
    roadmap_steps = synthesis.further_diligence_roadmap.recommended_next_steps[:8]
    if roadmap_steps:
        for step in roadmap_steps:
            document.add_paragraph(step, style="List Number")
        return

    fallback_steps = _build_seller_request_items(material_issues, critical_missing)[:8]
    if not fallback_steps:
        _add_bullet_items(document, [_SectionBullet(text="No additional concrete next step was isolated from the current package.")])
        return

    for item in fallback_steps:
        document.add_paragraph(item.text, style="List Number")
        if item.note:
            _add_note_line(document, f"Why: {item.note}")
        if item.references:
            _add_reference_line(document, item.references)


def _add_missing_information_section(
    document: Document,
    result: DealRunResult,
    synthesis: DealSynthesis,
    critical_missing: list[OmissionAssessment],
) -> None:
    _add_section(document, "Missing Information")
    bullets = _missing_summary_bullets(result, critical_missing)

    if result.failed_files:
        bullets.append(
            _SectionBullet(
                text=f"{result.failed_files} file(s) failed extraction, so manual review is still required before treating the package as complete.",
            )
        )

    if synthesis.extraction_errors:
        bullets.append(
            _SectionBullet(
                text="Some source files produced extraction errors; any conclusion that depends on those files should be confirmed manually.",
            )
        )

    _add_bullet_items(
        document,
        bullets or [_SectionBullet(text="No additional missing-information item was isolated from the current package.")],
    )


def _add_questions_for_seller_section(
    document: Document,
    material_issues: list[CanonicalIssue],
    critical_missing: list[OmissionAssessment],
) -> None:
    _add_section(document, "Questions for Seller")
    questions = _build_seller_request_items(material_issues, critical_missing)
    if not questions:
        _add_bullet_items(
            document,
            [_SectionBullet(text="No additional seller follow-up question was isolated from the current package.")],
        )
        return

    for item in questions:
        document.add_paragraph(item.text, style="List Number")
        if item.note:
            _add_note_line(document, f"Why: {item.note}")
        if item.references:
            _add_reference_line(document, item.references)


def _build_snapshot_bullet(
    result: DealRunResult,
    synthesis: DealSynthesis,
    fact_index: dict[str, list[FactRecord]],
) -> _SectionBullet:
    location = _location_text(fact_index)
    scale = _scale_text(fact_index)
    product = _product_text(result, fact_index)
    entitlement = clip_text(synthesis.entitlement_status, 140)
    text = f"{result.deal_name}: {location}; {scale}; {product}; entitlement stage currently reads as {entitlement}."

    references: list[str] = []
    for fact_type in ("jurisdiction", "gross_acreage", "net_acreage", "site_acreage", "lot_count", "unit_count"):
        references.extend(_reference_labels_for_fact_bundle(fact_index, fact_type))

    return _SectionBullet(text=text, references=references[:3])


def _build_high_confidence_bullets(
    fact_index: dict[str, list[FactRecord]],
    material_issues: list[CanonicalIssue],
) -> list[_SectionBullet]:
    bullets: list[_SectionBullet] = []
    for fact_type in (
        "jurisdiction",
        "zoning",
        "purchase_price",
        "gross_acreage",
        "net_acreage",
        "site_acreage",
        "lot_count",
        "unit_count",
        "owner_name",
        "apn",
    ):
        fact, supporting_facts = _best_fact_bundle(fact_index, fact_type, require_high=True)
        if fact is None:
            continue
        bullets.append(
            _SectionBullet(
                text=f"{_format_fact_sentence(fact)} This appears consistently across multiple readable documents.",
                references=_reference_labels_from_facts(supporting_facts),
            )
        )
        if len(bullets) >= 3:
            break

    for issue in material_issues:
        if issue.confidence != "high" or issue.information_status != "present and adequate":
            continue
        bullets.append(
            _SectionBullet(
                text=f"{issue.title}: {_issue_known_line(issue)}",
                references=_issue_reference_labels(issue),
            )
        )
        if len(bullets) >= 4:
            break

    return _dedupe_bullets(bullets)[:4]


def _missing_summary_bullets(
    result: DealRunResult,
    critical_missing: list[OmissionAssessment],
) -> list[_SectionBullet]:
    bullets = [
        _SectionBullet(
            text=_omission_text(assessment),
            references=_omission_reference_labels(assessment),
        )
        for assessment in critical_missing[:4]
    ]

    first_pass_items = [
        _SectionBullet(text=_missing_item_text(item))
        for item in result.issue_registry.missing_items[:4]
    ]
    return _dedupe_bullets([*bullets, *first_pass_items])[:5]


def _build_category_bullets(
    *,
    synthesis: DealSynthesis,
    result: DealRunResult,
    fact_index: dict[str, list[FactRecord]],
    material_conflicts: list[ConflictRecord],
    fact_types: tuple[str, ...],
    issue_categories: set[str],
    omission_categories: set[str],
    first_pass_missing_categories: set[str],
    conflict_types: set[str],
) -> list[_SectionBullet]:
    bullets: list[_SectionBullet] = []

    for fact_type in fact_types:
        fact, supporting_facts = _best_fact_bundle(fact_index, fact_type)
        if fact is None:
            continue
        bullets.append(
            _SectionBullet(
                text=_fact_section_text(fact, supporting_facts),
                references=_reference_labels_from_facts(supporting_facts),
            )
        )

    issues = [issue for issue in _material_issues(synthesis) if issue.category in issue_categories]
    for issue in issues[:3]:
        bullets.append(
            _SectionBullet(
                text=f"{issue.title}: {_issue_section_detail(issue)}",
                references=_issue_reference_labels(issue),
            )
        )

    for conflict in material_conflicts:
        if conflict.fact_type not in conflict_types:
            continue
        bullets.append(
            _SectionBullet(
                text=conflict.description,
                references=_source_reference_labels(conflict.sources),
                note=conflict.uncertainty,
            )
        )

    omissions = [
        assessment
        for assessment in _critical_missing_assessments(synthesis)
        if assessment.category in omission_categories
    ]
    for assessment in omissions[:2]:
        bullets.append(
            _SectionBullet(
                text=_omission_text(assessment),
                references=_omission_reference_labels(assessment),
            )
        )

    for item in result.issue_registry.missing_items:
        if item.category not in first_pass_missing_categories:
            continue
        bullets.append(_SectionBullet(text=_missing_item_text(item)))

    return _dedupe_bullets(bullets)[:6]


def _build_seller_request_items(
    material_issues: list[CanonicalIssue],
    critical_missing: list[OmissionAssessment],
) -> list[_SectionBullet]:
    items: list[_SectionBullet] = []

    ordered_issues = sorted(
        material_issues,
        key=lambda issue: (
            _ACQUISITION_SEVERITY_PRIORITY.get(issue.acquisition_severity, 4),
            0 if issue.gating_item else 1,
            -issue.priority_score.total,
            issue.title,
        ),
    )

    for issue in ordered_issues[:5]:
        items.append(
            _SectionBullet(
                text=_issue_request_text(issue),
                note=_issue_deal_impact(issue),
                references=_issue_reference_labels(issue),
            )
        )

    for assessment in critical_missing[:3]:
        items.append(
            _SectionBullet(
                text=_omission_request_text(assessment),
                note=_omission_text(assessment),
                references=_omission_reference_labels(assessment),
            )
        )

    return _dedupe_bullets(items)[:8]


def _build_fact_index(facts: list[FactRecord]) -> dict[str, list[FactRecord]]:
    fact_index: dict[str, list[FactRecord]] = defaultdict(list)
    for fact in facts:
        if fact.fact_type.startswith("signal_") or fact.confidence == "low":
            continue
        fact_index[fact.fact_type].append(fact)
    return fact_index


def _best_fact_bundle(
    fact_index: dict[str, list[FactRecord]],
    fact_type: str,
    *,
    require_high: bool = False,
) -> tuple[FactRecord | None, list[FactRecord]]:
    candidates = fact_index.get(fact_type, [])
    if require_high:
        candidates = [fact for fact in candidates if fact.confidence == "high"]
    if not candidates:
        return None, []

    best = max(
        candidates,
        key=lambda fact: (
            _confidence_rank(fact.confidence),
            _support_count(candidates, fact.normalized_value),
            len(fact.sources),
        ),
    )
    supporting_facts = [fact for fact in candidates if fact.normalized_value == best.normalized_value]
    return best, supporting_facts


def _support_count(facts: list[FactRecord], normalized_value: str) -> int:
    paths: set[str] = set()
    for fact in facts:
        if fact.normalized_value != normalized_value:
            continue
        for source in fact.sources:
            paths.add(source.relative_path)
    return len(paths)


def _material_issues(synthesis: DealSynthesis) -> list[CanonicalIssue]:
    issues = [issue for issue in synthesis.canonical_issue_registry.issues if _issue_is_material(issue)]
    issues.sort(
        key=lambda issue: (
            _ACQUISITION_SEVERITY_PRIORITY.get(issue.acquisition_severity, 4),
            _FRONT_END_PRIORITY.get(issue.front_end_flag, 9),
            0 if issue.gating_item else 1,
            0 if issue.blocking_flag else 1,
            0 if issue.critical_path_flag else 1,
            -issue.priority_score.total,
            issue.title,
        )
    )
    return issues


def _issue_is_material(issue: CanonicalIssue) -> bool:
    if issue.category not in _MATERIAL_ISSUE_CATEGORIES:
        return False
    if issue.front_end_flag == "routine item":
        return False
    if issue.blocking_flag or issue.critical_path_flag:
        return True
    if issue.top_line_eligible:
        return True
    return max(
        issue.priority_score.cost_exposure,
        issue.priority_score.schedule_exposure,
        issue.priority_score.entitlement_fragility,
        issue.priority_score.closing_risk,
        issue.priority_score.yield_exposure,
    ) >= 4


def _critical_missing_assessments(synthesis: DealSynthesis) -> list[OmissionAssessment]:
    assessments = [
        assessment
        for assessment in synthesis.omission_assessments
        if assessment.front_end_status and assessment.front_end_status != "present and adequate"
    ]
    assessments.sort(
        key=lambda assessment: (
            _MISSING_STATUS_ORDER.get(assessment.front_end_status, 9),
            assessment.category,
            assessment.item,
        )
    )
    return assessments


def _material_conflicts(conflicts: list[ConflictRecord]) -> list[ConflictRecord]:
    return sorted(
        conflicts,
        key=lambda conflict: (_CONFLICT_TYPE_ORDER.get(conflict.fact_type, 99), conflict.label),
    )


def _build_location_bullet(fact_index: dict[str, list[FactRecord]]) -> _SectionBullet:
    fact, supporting_facts = _best_fact_bundle(fact_index, "jurisdiction")
    if fact is None:
        return _SectionBullet(text="Location / jurisdiction is not clearly established from the readable package.")
    return _SectionBullet(
        text=f"Location / jurisdiction: {fact.value}.",
        references=_reference_labels_from_facts(supporting_facts),
    )


def _build_scale_bullet(fact_index: dict[str, list[FactRecord]]) -> _SectionBullet:
    return _SectionBullet(
        text=f"Scale: {_scale_text(fact_index)}.",
        references=_scale_references(fact_index),
    )


def _build_product_bullet(result: DealRunResult, fact_index: dict[str, list[FactRecord]]) -> _SectionBullet:
    references = [
        *_reference_labels_for_fact_bundle(fact_index, "lot_count"),
        *_reference_labels_for_fact_bundle(fact_index, "unit_count"),
    ]
    return _SectionBullet(
        text=f"Product: {_product_text(result, fact_index)}.",
        references=references[:3],
    )


def _build_price_bullet(fact_index: dict[str, list[FactRecord]]) -> _SectionBullet:
    fact, supporting_facts = _best_fact_bundle(fact_index, "purchase_price")
    if fact is None:
        return _SectionBullet(text="Purchase price is not cleanly established from the readable contract support in the package.")
    qualifier = "multiple readable documents" if _support_count(fact_index.get("purchase_price", []), fact.normalized_value) >= 2 else "one clear contract document"
    return _SectionBullet(
        text=f"Purchase price: {_format_fact_sentence(fact)} This currently appears in {qualifier}.",
        references=_reference_labels_from_facts(supporting_facts),
    )


def _location_text(fact_index: dict[str, list[FactRecord]]) -> str:
    fact, _ = _best_fact_bundle(fact_index, "jurisdiction")
    return fact.value if fact is not None else "jurisdiction not clearly established"


def _scale_text(fact_index: dict[str, list[FactRecord]]) -> str:
    parts: list[str] = []
    gross, _ = _best_fact_bundle(fact_index, "gross_acreage")
    net, _ = _best_fact_bundle(fact_index, "net_acreage")
    site, _ = _best_fact_bundle(fact_index, "site_acreage")
    lots, _ = _best_fact_bundle(fact_index, "lot_count")
    units, _ = _best_fact_bundle(fact_index, "unit_count")

    if gross is not None:
        parts.append(f"gross acreage referenced at {gross.normalized_value} acres")
    if net is not None:
        parts.append(f"net acreage referenced at {net.normalized_value} acres")
    elif site is not None and gross is None:
        parts.append(f"site acreage referenced at {site.normalized_value} acres")
    if lots is not None:
        parts.append(f"{lots.normalized_value} lots")
    if units is not None:
        parts.append(f"{units.normalized_value} units")
    return ", ".join(parts) if parts else "scale not clearly established"


def _product_text(result: DealRunResult, fact_index: dict[str, list[FactRecord]]) -> str:
    lot_fact, _ = _best_fact_bundle(fact_index, "lot_count")
    unit_fact, _ = _best_fact_bundle(fact_index, "unit_count")
    document_text = " ".join(processed.document.normalized_text.lower() for processed in result.processed_documents[:12])

    for label, terms in _PRODUCT_KEYWORDS:
        if any(term in document_text for term in terms):
            if lot_fact is not None:
                return f"{label} with {lot_fact.normalized_value} lots referenced"
            if unit_fact is not None:
                return f"{label} with {unit_fact.normalized_value} units referenced"
            return label

    if lot_fact is not None:
        return f"lot-based residential subdivision with {lot_fact.normalized_value} lots referenced"
    if unit_fact is not None:
        return f"unit-based residential project with {unit_fact.normalized_value} units referenced"
    return "product type not clearly established from the readable package"


def _scale_references(fact_index: dict[str, list[FactRecord]]) -> list[str]:
    references: list[str] = []
    for fact_type in ("gross_acreage", "net_acreage", "site_acreage", "lot_count", "unit_count"):
        references.extend(_reference_labels_for_fact_bundle(fact_index, fact_type))
    return references[:3]


def _fact_section_text(fact: FactRecord, supporting_facts: list[FactRecord]) -> str:
    support_phrase = "multiple readable documents" if len(_reference_labels_from_facts(supporting_facts)) >= 2 else "one clear document"
    return f"{_format_fact_sentence(fact)} This currently appears in {support_phrase}."


def _issue_known_line(issue: CanonicalIssue) -> str:
    basis = issue.best_evidence[0] if issue.best_evidence else issue.why_it_matters or issue.likely_implication
    return clip_text(basis, 180)


def _issue_summary_line(issue: CanonicalIssue) -> str:
    affects = ", ".join(issue.affects[:2]) or "deal execution"
    summary = issue.practical_impact or issue.likely_implication or issue.why_it_matters or issue.title
    return clip_text(f"{issue.acquisition_severity}; affects {affects}. {summary}", 200)


def _issue_section_detail(issue: CanonicalIssue) -> str:
    affects = ", ".join(issue.affects[:2]) or "deal execution"
    detail = issue.practical_impact or issue.why_it_matters or issue.likely_implication or issue.what_would_resolve_it
    return clip_text(f"{issue.acquisition_severity}; affects {affects}. {detail}", 200)


def _issue_what_line(issue: CanonicalIssue) -> str:
    if issue.best_evidence:
        return clip_text(issue.best_evidence[0], 200)
    if issue.core_facts:
        return clip_text(issue.core_facts[0], 200)
    return issue.title


def _issue_likely_explanation(issue: CanonicalIssue) -> str:
    if issue.likely_explanation:
        return clip_text(issue.likely_explanation, 220)
    if issue.status == "conflicted":
        return "Different documents appear to be using different assumptions or plan versions, and no controlling source has been established."
    if issue.status in {"not found", "unclear whether present", "present but weak"}:
        return "The package does not contain a current controlling document that cleanly closes this issue."
    category_explanations = {
        "Title / Access Concerns": "Title exceptions, easements, or access rights have not yet been reconciled to the current plan and closing structure.",
        "Entitlement Status": "Approvals may be farther along than the underlying condition closeout or supporting tracker.",
        "Environmental Risks": "Environmental follow-up remains open or not fully priced into the current underwriting assumptions.",
        "Geotechnical Risks": "Soils recommendations exist, but the current plan and budget do not clearly show they are fully carried through.",
        "Flood / Drainage Issues": "Drainage or flood-control requirements still depend on civil confirmation or permit-stage design work.",
        "Utilities / Infrastructure Issues": "Provider confirmation and offsite utility scope are still not fully locked for the current plan.",
        "Offsite Obligations": "Frontage or offsite obligations remain buyer-facing, or the cost owner is still not fixed.",
        "Fee / Exaction Burden": "Current fee support is preliminary, stale, or not fully confirmed by the governing agency.",
        "Budget / Cost Reliability": "Current cost support remains budgetary, incomplete, or not auditable enough to lock basis.",
        "Schedule Risks": "The current schedule still depends on assumptions that are not fully confirmed in the package.",
    }
    return category_explanations.get(issue.category, "The package still lacks a clean controlling basis for this issue.")


def _issue_deal_impact(issue: CanonicalIssue) -> str:
    if issue.practical_impact:
        return clip_text(issue.practical_impact, 220)
    impact_lines = unique_preserve_order(
        [
            issue.likely_underwriting_effect,
            issue.likely_cost_effect if issue.priority_score.cost_exposure >= 4 else "",
            issue.likely_schedule_effect if issue.priority_score.schedule_exposure >= 4 else "",
            issue.likely_closing_effect if issue.priority_score.closing_risk >= 4 else "",
            issue.likely_yield_or_product_effect if issue.priority_score.yield_exposure >= 3 else "",
            issue.why_it_matters,
        ]
    )
    filtered = [line for line in impact_lines if line]
    return clip_text(" ".join(filtered) if filtered else issue.title, 220)


def _omission_text(assessment: OmissionAssessment) -> str:
    if assessment.front_end_status == "stale and potentially unreliable":
        return f"{assessment.item} appears stale, so this lane should not be treated as current until refreshed."
    if assessment.front_end_status == "conflicting across documents":
        return f"{assessment.item} is not controlled by one current source, so this lane remains unresolved."
    return f"{assessment.item} is missing or not decision-grade in the current package."


def _missing_item_text(item: MissingItem) -> str:
    return f"{item.label}: {item.reason.rstrip('.')} Needed next: {item.suggested_request.rstrip('.')}."


def _issue_request_text(issue: CanonicalIssue) -> str:
    if issue.what_would_resolve_it:
        return issue.what_would_resolve_it.rstrip(".") + "."
    if issue.open_questions:
        return issue.open_questions[0].rstrip("?") + "?"
    return f"Please confirm how {issue.title.lower()} is being resolved and provide the controlling support."


def _issue_severity_line(issue: CanonicalIssue) -> str:
    affects = ", ".join(issue.affects[:3]) or "deal execution"
    gating = "gating item" if issue.gating_item else "non-gating item"
    return f"{issue.acquisition_severity}; {gating}; affects {affects}."


def _issue_reality_vs_noise(issue: CanonicalIssue) -> str:
    if issue.reality_vs_noise:
        return clip_text(issue.reality_vs_noise, 220)
    if issue.information_status == "conflicting across documents":
        return "Likely real inconsistency because readable documents conflict on a controlling assumption."
    if issue.information_status == "stale and potentially unreliable":
        return "Likely stale support rather than a true contradiction."
    if issue.confidence == "low":
        return "Signal remains weak and should not be over-weighted until confirmed."
    return "Likely real issue because the current readable support is specific enough to merit attention."


def _omission_request_text(assessment: OmissionAssessment) -> str:
    if assessment.recommended_request:
        request = assessment.recommended_request.rstrip(".")
        if request.lower().startswith("please "):
            return request + "."
        return f"Please provide {request}."
    return f"Please provide current, readable support for {assessment.item.lower()}."


def _reference_labels_for_fact_bundle(
    fact_index: dict[str, list[FactRecord]],
    fact_type: str,
) -> list[str]:
    fact, supporting_facts = _best_fact_bundle(fact_index, fact_type)
    if fact is None:
        return []
    return _reference_labels_from_facts(supporting_facts)


def _reference_labels_from_facts(facts: list[FactRecord]) -> list[str]:
    references: list[str] = []
    for fact in facts:
        references.extend(_source_reference_labels(fact.sources))
    return unique_preserve_order(references)[:3]


def _source_reference_labels(sources: list[SourceReference]) -> list[str]:
    labels: list[str] = []
    for source in sources:
        label = Path(source.relative_path).name
        if source.page_number is not None:
            label += f" p. {source.page_number}"
        labels.append(label)
    return unique_preserve_order(labels)[:3]


def _issue_reference_labels(issue: CanonicalIssue) -> list[str]:
    labels = [_citation_label(citation) for citation in issue.citations]
    labels.extend(issue.source_documents)
    return unique_preserve_order(labels)[:3]


def _omission_reference_labels(assessment: OmissionAssessment) -> list[str]:
    labels = [_citation_label(citation) for citation in assessment.citations]
    labels.extend(assessment.source_documents)
    return unique_preserve_order(labels)[:3]


def _citation_label(citation: Citation) -> str:
    label = citation.document_name
    if citation.page_number is not None:
        label += f" p. {citation.page_number}"
    return label


def _confidence_rank(confidence: str) -> int:
    return {"low": 0, "medium": 1, "high": 2}.get(confidence, 0)


def _add_section(document: Document, title: str) -> None:
    document.add_heading(title, level=1)


def _add_subsection(document: Document, title: str) -> None:
    document.add_heading(title, level=2)


def _add_bullet_items(document: Document, items: list[_SectionBullet]) -> None:
    for item in _dedupe_bullets(items):
        document.add_paragraph(item.text, style="List Bullet")
        if item.note:
            _add_note_line(document, item.note)
        if item.references:
            _add_reference_line(document, item.references)


def _add_note_line(document: Document, text: str) -> None:
    paragraph = document.add_paragraph(text)
    paragraph.paragraph_format.left_indent = Pt(18)


def _add_reference_line(document: Document, references: list[str]) -> None:
    paragraph = document.add_paragraph(f"Ref: {'; '.join(unique_preserve_order(references)[:3])}")
    paragraph.paragraph_format.left_indent = Pt(18)


def _dedupe_bullets(items: list[_SectionBullet]) -> list[_SectionBullet]:
    seen: set[str] = set()
    deduped: list[_SectionBullet] = []
    for item in items:
        key = item.text.strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def _format_fact_sentence(fact: FactRecord) -> str:
    if fact.fact_type == "purchase_price":
        return f"Purchase price referenced at ${_format_currency(fact.normalized_value)}."
    if fact.fact_type in {"gross_acreage", "net_acreage", "site_acreage"}:
        return f"{fact.label} referenced at {fact.normalized_value} acres."
    if fact.fact_type in {"lot_count", "unit_count"}:
        count = _coerce_int(fact.normalized_value)
        count_text = str(count) if count is not None else fact.value
        noun = "lots" if fact.fact_type == "lot_count" else "units"
        return f"{fact.label} referenced at {count_text} {noun}."
    if fact.fact_type == "apn":
        return f"APN referenced as {fact.value}."
    if fact.fact_type == "owner_name":
        return f"Owner or seller referenced as {fact.value}."
    if fact.fact_type == "jurisdiction":
        return f"Jurisdiction referenced as {fact.value}."
    if fact.fact_type == "zoning":
        return f"Zoning referenced as {fact.value}."
    return fact.statement


def _format_currency(normalized_value: str) -> str:
    amount = float(normalized_value)
    return f"{amount:,.0f}" if amount.is_integer() else f"{amount:,.2f}"


def _coerce_int(value: str) -> int | None:
    try:
        return int(float(value))
    except ValueError:
        return None
