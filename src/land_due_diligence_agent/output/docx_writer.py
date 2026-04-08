"""DOCX reporting for the local due diligence workflow."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from docx import Document
from docx.shared import Pt

from land_due_diligence_agent.classification import DD_CATEGORIES
from land_due_diligence_agent.deal_models import ConflictRecord, DealRunResult, FactRecord, MissingItem, ProcessedDocument, SellerQuestion, SourceReference
from land_due_diligence_agent.utils.files import ensure_directory


_CATEGORY_PRIORITY = {
    "Purchase / Sale / Contract": 96,
    "Title": 94,
    "Vesting / Legal": 88,
    "Entitlement / Planning / Conditions": 92,
    "Environmental": 90,
    "Geotech / Soils": 89,
    "Utilities": 86,
    "Map / Plat / Improvement Plans": 80,
    "Fees / Taxes / CFD / Assessments": 72,
    "HOA / CC&Rs": 58,
    "Financial / underwriting support": 60,
    "Seller correspondence": 52,
    "Miscellaneous": 20,
}

_FACT_CATEGORY_MAP = {
    "apn": "Title",
    "gross_acreage": "Map / Plat / Improvement Plans",
    "net_acreage": "Map / Plat / Improvement Plans",
    "site_acreage": "Map / Plat / Improvement Plans",
    "zoning": "Entitlement / Planning / Conditions",
    "jurisdiction": "Entitlement / Planning / Conditions",
    "owner_name": "Vesting / Legal",
    "purchase_price": "Purchase / Sale / Contract",
    "lot_count": "Map / Plat / Improvement Plans",
    "unit_count": "Financial / underwriting support",
}

_SIGNAL_ISSUES = {
    "signal_environmental": "Environmental materials reference site constraints, environmental follow-up, or remediation exposure.",
    "signal_geotech": "Geotechnical materials reference soil or seismic conditions that can affect design, cost, or schedule.",
    "signal_title": "Title or legal materials reference exceptions, easements, encumbrances, or access concerns that require direct review.",
    "signal_utilities": "Utilities materials indicate service availability or capacity remains an active diligence item.",
    "signal_entitlement": "Entitlement materials indicate discretionary approvals, conditions, or planning path items remain material to the deal.",
}

_KEY_DOC_REASON = {
    "Purchase / Sale / Contract": "Controls economic terms, diligence timing, and closing mechanics.",
    "Title": "Carries title, easement, and exception risk that should be reviewed directly.",
    "Vesting / Legal": "Controls vesting, legal description, and ownership chain assumptions.",
    "Entitlement / Planning / Conditions": "Controls zoning, approvals, and conditions that drive closability and schedule.",
    "Environmental": "Can change cost, scope, and risk allocation materially.",
    "Geotech / Soils": "Can affect site design, grading, foundations, and budget materially.",
    "Utilities": "Can change offsite scope, schedule, and project feasibility.",
    "Map / Plat / Improvement Plans": "Defines site layout, parcel assumptions, and engineering constraints.",
}

_BAD_ZONING_VALUES = {"setbacks", "development standards", "provided", "designation", "base zoning"}
_BAD_OWNER_FRAGMENTS = ("tentative map", "site plan", "grading", "streetscape", "colors", "materials", "demolition")


@dataclass(slots=True)
class _CriticalIssue:
    title: str
    detail: str
    category: str
    priority: int
    sources: list[SourceReference] = field(default_factory=list)


@dataclass(slots=True)
class _KeyDocument:
    relative_path: str
    category: str
    reason: str
    priority: int


def write_due_diligence_report_docx(path: Path, result: DealRunResult) -> Path:
    """Write the primary due diligence report as a Word document."""

    ensure_directory(path.parent)
    document = Document()
    _configure_document(document)

    document.add_heading("Due Diligence Review", level=0)
    document.add_paragraph(f"Deal: {result.deal_name}")
    document.add_paragraph(f"Generated: {datetime.now().astimezone().isoformat(timespec='minutes')}")

    critical_issues = _build_critical_issues(result)
    findings_by_category = _build_findings_by_category(result, critical_issues)
    key_documents = _build_key_documents(result, critical_issues)

    _add_section(document, "Executive Summary")
    for item in _build_executive_summary(result, critical_issues, key_documents):
        _add_bullet(document, item)

    _add_section(document, "Top Critical Issues")
    if critical_issues:
        for issue in critical_issues:
            _add_numbered_issue(document, issue.title, issue.detail, issue.sources)
    else:
        document.add_paragraph("No concentrated critical issue was isolated from the current extracted package.")

    _add_section(document, "Detailed Findings by Category")
    if findings_by_category:
        for category in _ordered_categories(set(findings_by_category)):
            findings = findings_by_category.get(category)
            if not findings:
                continue
            document.add_heading(category, level=2)
            for paragraph in findings["summary"]:
                document.add_paragraph(paragraph)

            _add_subsection_list(document, "Facts", findings["facts"])
            _add_subsection_list(document, "Conflicts", findings["conflicts"])
            _add_subsection_list(document, "Not found", findings["missing"])
            _add_subsection_list(document, "Material concerns", findings["concerns"])
    else:
        document.add_paragraph("No category-level findings were synthesized from the current extracted package.")

    _add_section(document, "Contradictions / Tensions")
    if result.issue_registry.conflicts:
        for conflict in result.issue_registry.conflicts:
            _add_bullet(document, f"{conflict.description} Sources: {_format_sources(conflict.sources)}")
            if conflict.uncertainty:
                _add_indented(document, f"Uncertainty: {conflict.uncertainty}")
    else:
        document.add_paragraph("No explicit contradiction was isolated from the extracted fact set. That does not confirm the package is internally consistent.")

    _add_section(document, "Not Found in Provided Documents")
    if result.issue_registry.missing_items:
        for item in result.issue_registry.missing_items:
            _add_bullet(document, f"{item.label}: {item.reason}")
            _add_indented(document, f"Request: {item.suggested_request}")
    else:
        document.add_paragraph("No major missing DD lane was flagged by the current rule set.")

    _add_section(document, "Key Documents to Review Personally")
    if key_documents:
        for item in key_documents:
            _add_bullet(document, f"{item.relative_path} ({item.category})")
            _add_indented(document, item.reason)
    else:
        document.add_paragraph("No specific document was elevated above the rest for direct personal review.")

    _add_section(document, "Questions for Seller")
    if result.issue_registry.seller_questions:
        for question in result.issue_registry.seller_questions:
            _add_numbered_question(document, question)
    else:
        document.add_paragraph("No seller follow-up question was generated from the current rule set.")

    document.save(path)
    return path


def _configure_document(document: Document) -> None:
    style = document.styles["Normal"]
    style.font.name = "Calibri"
    style.font.size = Pt(10.5)


def _build_executive_summary(
    result: DealRunResult,
    critical_issues: list[_CriticalIssue],
    key_documents: list[_KeyDocument],
) -> list[str]:
    present_categories = ", ".join(sorted(result.category_counts)) if result.category_counts else "none isolated"
    summary = [
        (
            f"Package review processed {result.extracted_files} of {result.supported_files} supported document(s) "
            f"across these classified lanes: {present_categories}."
        ),
    ]

    if critical_issues:
        top_titles = "; ".join(issue.title for issue in critical_issues[:3])
        summary.append(f"Most material current concerns: {top_titles}.")

    if result.issue_registry.missing_items:
        summary.append(
            "Important missing or weakly supported lanes remain: "
            + "; ".join(item.label for item in result.issue_registry.missing_items[:4])
            + "."
        )

    if result.failed_files or result.ocr_files:
        summary.append(
            f"Reliability watchlist: {result.failed_files} file(s) failed extraction and OCR fallback was used on {result.ocr_files} file(s)."
        )

    if key_documents:
        summary.append(
            "The files that warrant direct personal review first are: "
            + "; ".join(item.relative_path for item in key_documents[:4])
            + "."
        )

    return summary


def _build_critical_issues(result: DealRunResult) -> list[_CriticalIssue]:
    issues: list[_CriticalIssue] = []
    seen: set[tuple[str, str]] = set()

    for conflict in result.issue_registry.conflicts:
        category = _FACT_CATEGORY_MAP.get(conflict.fact_type, "Miscellaneous")
        key = (category, conflict.description)
        if key in seen:
            continue
        seen.add(key)
        issues.append(
            _CriticalIssue(
                title=conflict.label,
                detail=conflict.description,
                category=category,
                priority=100,
                sources=conflict.sources,
            )
        )

    for item in result.issue_registry.missing_items:
        title = f"Missing {item.label}"
        detail = f"{item.reason} Request: {item.suggested_request}"
        key = (item.category, title)
        if key in seen:
            continue
        seen.add(key)
        issues.append(
            _CriticalIssue(
                title=title,
                detail=detail,
                category=item.category,
                priority=_CATEGORY_PRIORITY.get(item.category, 40) + 4,
            )
        )

    for fact in result.issue_registry.facts:
        if not fact.fact_type.startswith("signal_"):
            continue
        detail = _SIGNAL_ISSUES.get(fact.fact_type)
        if not detail:
            continue
        key = (fact.category, detail)
        if key in seen:
            continue
        seen.add(key)
        issues.append(
            _CriticalIssue(
                title=fact.label,
                detail=detail,
                category=fact.category,
                priority=_CATEGORY_PRIORITY.get(fact.category, 40),
                sources=fact.sources,
            )
        )

    for entry in result.manifest_entries:
        if entry.extraction_status != "failed":
            continue
        title = f"Extraction failure in {entry.file_name}"
        detail = (
            f"This file did not parse successfully, which may leave a material gap in the review. "
            f"Errors: {'; '.join(entry.errors or entry.notes)}"
        )
        key = (entry.category, title)
        if key in seen:
            continue
        seen.add(key)
        issues.append(
            _CriticalIssue(
                title=title,
                detail=detail,
                category=entry.category,
                priority=_CATEGORY_PRIORITY.get(entry.category, 40) + 3,
            )
        )

    issues.sort(key=lambda item: (-item.priority, item.category, item.title))
    return issues[:8]


def _build_findings_by_category(
    result: DealRunResult,
    critical_issues: list[_CriticalIssue],
) -> dict[str, dict[str, list[str]]]:
    category_docs: dict[str, list[ProcessedDocument]] = defaultdict(list)
    for processed in result.processed_documents:
        category_docs[processed.classification.category].append(processed)

    facts_by_category: dict[str, list[FactRecord]] = defaultdict(list)
    seen_fact_keys: set[tuple[str, str]] = set()
    for fact in result.issue_registry.facts:
        if not _is_report_worthy_fact(fact):
            continue
        fact_key = (fact.category, f"{fact.fact_type}:{fact.normalized_value}")
        if fact_key in seen_fact_keys:
            continue
        seen_fact_keys.add(fact_key)
        facts_by_category[fact.category].append(fact)

    conflicts_by_category: dict[str, list[ConflictRecord]] = defaultdict(list)
    for conflict in result.issue_registry.conflicts:
        conflicts_by_category[_FACT_CATEGORY_MAP.get(conflict.fact_type, "Miscellaneous")].append(conflict)

    missing_by_category: dict[str, list[MissingItem]] = defaultdict(list)
    for item in result.issue_registry.missing_items:
        missing_by_category[item.category].append(item)

    concerns_by_category: dict[str, list[_CriticalIssue]] = defaultdict(list)
    for issue in critical_issues:
        concerns_by_category[issue.category].append(issue)

    category_results: dict[str, dict[str, list[str]]] = {}
    category_keys = set(category_docs) | set(facts_by_category) | set(conflicts_by_category) | set(missing_by_category) | set(concerns_by_category)

    for category in category_keys:
        docs = category_docs.get(category, [])
        facts = facts_by_category.get(category, [])[:5]
        conflicts = conflicts_by_category.get(category, [])[:4]
        missing = missing_by_category.get(category, [])[:4]
        concerns = concerns_by_category.get(category, [])[:4]

        summary = []
        if docs:
            summary.append(f"Processed {len(docs)} document(s) classified in this lane.")
        if facts:
            summary.append(
                "Most useful extracted facts in this lane: " + "; ".join(_format_fact_for_summary(fact) for fact in facts[:3]) + "."
            )
        if conflicts:
            summary.append("Conflicts remain open in this lane and should not be treated as reconciled.")
        if missing:
            summary.append("The package still lacks at least one important item or confirmation in this lane.")
        if not summary:
            summary.append("No decision-useful finding was synthesized from the current extracted text in this lane.")

        category_results[category] = {
            "summary": summary,
            "facts": [f"{_format_fact_sentence(fact)} Sources: {_format_sources(fact.sources)}" for fact in facts] or ["No high-value factual point was isolated in this category."],
            "conflicts": [f"{conflict.description} Sources: {_format_sources(conflict.sources)}" for conflict in conflicts] or ["No explicit contradiction was isolated in this category."],
            "missing": [f"{item.label}: {item.reason} Request: {item.suggested_request}" for item in missing] or ["No specific missing-item flag was raised in this category."],
            "concerns": [f"{issue.title}: {issue.detail}" + (f" Sources: {_format_sources(issue.sources)}" if issue.sources else "") for issue in concerns] or ["No additional material concern was elevated in this category."],
        }

    return category_results


def _build_key_documents(result: DealRunResult, critical_issues: list[_CriticalIssue]) -> list[_KeyDocument]:
    conflict_paths = {
        source.relative_path
        for conflict in result.issue_registry.conflicts
        for source in conflict.sources
    }
    issue_paths = {
        source.relative_path
        for issue in critical_issues
        for source in issue.sources
    }

    ranked: list[_KeyDocument] = []
    seen: set[str] = set()
    for processed in result.processed_documents:
        relative_path = processed.document.relative_path.as_posix()
        if relative_path in seen:
            continue
        seen.add(relative_path)

        category = processed.classification.category
        priority = _CATEGORY_PRIORITY.get(category, 25)
        reasons = [_KEY_DOC_REASON.get(category, "This file contributes to a material diligence lane.")]

        if relative_path in conflict_paths:
            priority += 20
            reasons.append("It is cited in an identified contradiction or tension.")
        if relative_path in issue_paths:
            priority += 15
            reasons.append("It supports a top critical issue in the current report.")
        if processed.document.ocr_pages:
            priority += 6
            reasons.append(f"OCR was required on page(s) {', '.join(str(page) for page in processed.document.ocr_pages)}.")
        if processed.document.warnings:
            priority += 6
            reasons.append("Extraction warnings suggest the file warrants direct review.")
        if processed.classification.confidence == "high":
            priority += 4
        if category not in _KEY_DOC_REASON and relative_path not in issue_paths and relative_path not in conflict_paths:
            continue

        ranked.append(
            _KeyDocument(
                relative_path=relative_path,
                category=category,
                reason=" ".join(reasons),
                priority=priority,
            )
        )

    ranked.sort(key=lambda item: (-item.priority, item.category, item.relative_path))
    return ranked[:8]


def _ordered_categories(categories: set[str] | list[str]) -> list[str]:
    order = {category: index for index, category in enumerate(DD_CATEGORIES)}
    return sorted(categories, key=lambda category: (order.get(category, 999), category))


def _is_report_worthy_fact(fact: FactRecord) -> bool:
    if fact.fact_type.startswith("signal_"):
        return False

    normalized = fact.normalized_value.lower()
    if fact.fact_type == "zoning":
        return any(character.isalpha() for character in fact.value) and not normalized.isdigit() and normalized not in _BAD_ZONING_VALUES

    if fact.fact_type == "owner_name":
        if any(fragment in normalized for fragment in _BAD_OWNER_FRAGMENTS):
            return False
        return any(token in normalized for token in ("llc", "inc", "lp", "trust", "company", "corp")) or len(fact.value.split()) >= 3

    if fact.fact_type == "unit_count":
        count = _coerce_int(fact.normalized_value)
        excerpt = " ".join(source.excerpt.lower() for source in fact.sources)
        return count is not None and (count >= 20 or "proposed units" in excerpt or "base units" in excerpt or "total units" in excerpt)

    if fact.fact_type == "lot_count":
        count = _coerce_int(fact.normalized_value)
        excerpt = " ".join(source.excerpt.lower() for source in fact.sources)
        return count is not None and (count >= 20 or "proposed lots" in excerpt or "tentative map" in excerpt or "lot count" in excerpt)

    return True


def _format_fact_for_summary(fact: FactRecord) -> str:
    return _format_fact_sentence(fact).rstrip(".")


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


def _format_sources(sources: list[SourceReference]) -> str:
    if not sources:
        return "not available"

    formatted: list[str] = []
    seen: set[tuple[str, int | None, str | None]] = set()
    for source in sources:
        key = (source.relative_path, source.page_number, source.chunk_id)
        if key in seen:
            continue
        seen.add(key)
        detail = source.relative_path
        if source.page_number is not None:
            detail += f" | page {source.page_number}"
        elif source.chunk_id:
            detail += f" | {source.chunk_id}"
        if source.excerpt:
            detail += f" | \"{source.excerpt}\""
        formatted.append(detail)
        if len(formatted) >= 3:
            break
    return "; ".join(formatted)


def _format_currency(normalized_value: str) -> str:
    amount = float(normalized_value)
    return f"{amount:,.0f}" if amount.is_integer() else f"{amount:,.2f}"


def _coerce_int(value: str) -> int | None:
    try:
        return int(float(value))
    except ValueError:
        return None


def _add_section(document: Document, title: str) -> None:
    document.add_heading(title, level=1)


def _add_subsection_list(document: Document, title: str, items: list[str]) -> None:
    document.add_heading(title, level=3)
    for item in items:
        _add_bullet(document, item)


def _add_bullet(document: Document, text: str) -> None:
    document.add_paragraph(text, style="List Bullet")


def _add_indented(document: Document, text: str) -> None:
    paragraph = document.add_paragraph(text)
    paragraph.paragraph_format.left_indent = Pt(18)


def _add_numbered_issue(document: Document, title: str, detail: str, sources: list[SourceReference]) -> None:
    document.add_paragraph(title, style="List Number")
    _add_indented(document, detail)
    if sources:
        _add_indented(document, f"Sources: {_format_sources(sources)}")


def _add_numbered_question(document: Document, question: SellerQuestion) -> None:
    document.add_paragraph(question.question, style="List Number")
    _add_indented(document, f"Reason: {question.reason}")
    if question.sources:
        _add_indented(document, f"Sources: {_format_sources(question.sources)}")
