"""Heuristic DD document classification for the local workflow."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from land_due_diligence_agent.deal_models import ClassificationResult
from land_due_diligence_agent.utils.files import humanize_filename
from land_due_diligence_agent.utils.text import normalize_text, unique_preserve_order


DD_CATEGORIES = (
    "Purchase / Sale / Contract",
    "Title",
    "Vesting / Legal",
    "Map / Plat / Improvement Plans",
    "Entitlement / Planning / Conditions",
    "Environmental",
    "Geotech / Soils",
    "Utilities",
    "Fees / Taxes / CFD / Assessments",
    "HOA / CC&Rs",
    "Seller correspondence",
    "Financial / underwriting support",
    "Miscellaneous",
)


@dataclass(frozen=True, slots=True)
class _Rule:
    category: str
    document_type: str
    path_keywords: tuple[str, ...]
    text_keywords: tuple[str, ...] = ()


_RULES: tuple[_Rule, ...] = (
    _Rule(
        category="Purchase / Sale / Contract",
        document_type="purchase agreement",
        path_keywords=("purchase agreement", "purchase and sale", "psa", "sale agreement", "loi", "letter of intent", "amendment", "addendum"),
        text_keywords=("purchase price", "close of escrow", "buyer", "seller", "due diligence period"),
    ),
    _Rule(
        category="Title",
        document_type="preliminary title report",
        path_keywords=("title", "prelim", "commitment", "schedule b", "exception", "alta"),
        text_keywords=("preliminary title report", "title commitment", "schedule b", "exception", "title insurance"),
    ),
    _Rule(
        category="Vesting / Legal",
        document_type="vesting or legal document",
        path_keywords=("vesting", "grant deed", "deed", "legal description", "easement", "covenant"),
        text_keywords=("legal description", "grant deed", "vesting", "easement", "recorded"),
    ),
    _Rule(
        category="Map / Plat / Improvement Plans",
        document_type="map or improvement plan",
        path_keywords=("map", "plat", "parcel map", "tract map", "site plan", "grading", "improvement plan", "survey"),
        text_keywords=("tract map", "parcel map", "grading plan", "improvement plans", "boundary", "survey"),
    ),
    _Rule(
        category="Entitlement / Planning / Conditions",
        document_type="entitlement or planning document",
        path_keywords=("entitlement", "planning", "condition", "approval", "zoning", "tentative map", "annexation", "development agreement"),
        text_keywords=("conditions of approval", "planning commission", "city council", "zoning", "rezone", "tentative map", "annexation"),
    ),
    _Rule(
        category="Environmental",
        document_type="environmental report",
        path_keywords=("environmental", "phase i", "phase ii", "esa", "wetland", "biological", "hazmat", "remediation"),
        text_keywords=("recognized environmental condition", "wetlands", "floodplain", "hazardous", "remediation", "phase i environmental"),
    ),
    _Rule(
        category="Geotech / Soils",
        document_type="geotechnical report",
        path_keywords=("geotech", "geotechnical", "soils", "geologic", "geo"),
        text_keywords=("liquefaction", "expansive soil", "settlement", "geotechnical", "soils report"),
    ),
    _Rule(
        category="Utilities",
        document_type="utility availability document",
        path_keywords=("utility", "utilities", "will serve", "will-serve", "sewer", "water", "storm drain", "dry utility"),
        text_keywords=("will serve", "utility capacity", "water capacity", "sewer capacity", "service letter"),
    ),
    _Rule(
        category="Fees / Taxes / CFD / Assessments",
        document_type="fee or tax support",
        path_keywords=("tax", "taxes", "cfd", "assessment", "fee", "fees", "mello-roos"),
        text_keywords=("special tax", "community facilities district", "assessment district", "impact fee", "school fee"),
    ),
    _Rule(
        category="HOA / CC&Rs",
        document_type="hoa or cc&r document",
        path_keywords=("hoa", "cc&r", "ccrs", "association", "declaration", "rules"),
        text_keywords=("covenants, conditions", "homeowners association", "declaration", "association"),
    ),
    _Rule(
        category="Seller correspondence",
        document_type="seller correspondence",
        path_keywords=("correspondence", "email", "memo", "notes", "q&a", "seller responses", "seller questions"),
        text_keywords=("from:", "sent:", "subject:", "seller response", "q&a"),
    ),
    _Rule(
        category="Financial / underwriting support",
        document_type="financial support",
        path_keywords=("budget", "financial", "underwriting", "pro forma", "pricing", "rent", "revenue", "schedule"),
        text_keywords=("budgetary", "underwriting", "pro forma", "pricing", "revenue", "contingency"),
    ),
)


def classify_document(path: Path, text: str = "") -> ClassificationResult:
    """Classify a document into a DD category and practical document type guess."""

    path_text = path.as_posix().lower()
    text_sample = normalize_text(text).lower()[:12000]
    best_rule: _Rule | None = None
    best_score = 0
    best_matches: list[str] = []

    for rule in _RULES:
        score = 0
        matches: list[str] = []

        for keyword in rule.path_keywords:
            if keyword in path_text:
                score += 3
                matches.append(keyword)

        for keyword in rule.text_keywords:
            if keyword in text_sample:
                score += 1
                matches.append(keyword)

        if score > best_score:
            best_rule = rule
            best_score = score
            best_matches = matches

    if best_rule is None or best_score == 0:
        return ClassificationResult(
            category="Miscellaneous",
            document_type_guess=humanize_filename(path.stem),
            confidence="low",
            matched_keywords=[],
        )

    confidence = "high" if best_score >= 6 else "medium" if best_score >= 3 else "low"
    return ClassificationResult(
        category=best_rule.category,
        document_type_guess=best_rule.document_type,
        confidence=confidence,
        matched_keywords=unique_preserve_order(best_matches),
    )