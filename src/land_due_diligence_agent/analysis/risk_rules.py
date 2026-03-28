"""Keyword rules for deterministic due diligence heuristics."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RiskRule:
    """Keyword-driven rule for a diligence risk category."""

    category: str
    keywords: tuple[str, ...]
    severe_keywords: tuple[str, ...]
    seller_question: str


CATEGORY_RULES: tuple[RiskRule, ...] = (
    RiskRule(
        category="Entitlement Status",
        keywords=(
            "zoning",
            "entitlement",
            "annexation",
            "plat",
            "specific plan",
            "permit",
            "rezoning",
            "approval",
        ),
        severe_keywords=("denied", "unapproved", "pending", "variance required", "rezoning required"),
        seller_question="What approvals are already secured, which remain outstanding, and what is the current entitlement schedule?",
    ),
    RiskRule(
        category="Environmental Risks",
        keywords=(
            "phase i",
            "phase ii",
            "environmental",
            "wetlands",
            "contamination",
            "hazardous",
            "recognized environmental condition",
        ),
        severe_keywords=("phase ii", "recognized environmental condition", "remediation", "contamination", "hazardous"),
        seller_question="What environmental issues have been identified, what follow-up work is outstanding, and who is responsible for remediation or mitigation?",
    ),
    RiskRule(
        category="Flood / Drainage Issues",
        keywords=(
            "flood",
            "fema",
            "floodplain",
            "drainage",
            "stormwater",
            "detention",
            "retention",
            "inundation",
        ),
        severe_keywords=("100-year", "floodway", "detention basin", "offsite drainage", "capacity deficiency"),
        seller_question="Please confirm current floodplain status, required drainage facilities, and any offsite stormwater obligations still unresolved.",
    ),
    RiskRule(
        category="Geotechnical Risks",
        keywords=(
            "geotechnical",
            "geotech",
            "expansive soil",
            "liquefaction",
            "fault",
            "fill",
            "seismic",
            "settlement",
        ),
        severe_keywords=("liquefaction", "expansive soil", "fault rupture", "settlement", "overexcavation"),
        seller_question="What geotechnical constraints materially affect pad yields, grading costs, or foundation design assumptions?",
    ),
    RiskRule(
        category="Offsite Obligations",
        keywords=(
            "offsite",
            "improvement agreement",
            "impact fee",
            "reimbursement",
            "participation agreement",
            "regional improvement",
            "proportionate share",
        ),
        severe_keywords=("reimbursement", "frontage", "regional improvement", "participation agreement", "offsite sewer"),
        seller_question="Which offsite improvements, frontage work, fees, or reimbursement obligations remain with the buyer or landowner?",
    ),
    RiskRule(
        category="Utilities / Infrastructure Issues",
        keywords=(
            "water",
            "sewer",
            "utility",
            "infrastructure",
            "capacity",
            "lift station",
            "substation",
            "will serve",
        ),
        severe_keywords=("capacity deficiency", "moratorium", "lift station", "upsizing", "will-serve unavailable"),
        seller_question="What utility capacity constraints, offsite extensions, or will-serve contingencies could affect timing or cost?",
    ),
    RiskRule(
        category="Title / Access Concerns",
        keywords=(
            "title",
            "access",
            "ingress",
            "egress",
            "easement",
            "encroachment",
            "exception",
            "right-of-way",
        ),
        severe_keywords=("lack of access", "encroachment", "exception", "uninsured", "exclusive easement"),
        seller_question="Please identify all title exceptions, access constraints, easements, and third-party rights that could impair development or marketability.",
    ),
    RiskRule(
        category="Schedule Risks",
        keywords=(
            "schedule",
            "timeline",
            "delay",
            "phasing",
            "backlog",
            "moratorium",
            "long lead",
            "critical path",
        ),
        severe_keywords=("delay", "moratorium", "backlog", "critical path", "long lead"),
        seller_question="What are the remaining critical path items, realistic approval or construction dates, and the top schedule slip risks?",
    ),
)


EXPECTED_DILIGENCE_ITEMS: dict[str, tuple[str, ...]] = {
    "Current title commitment or title report": ("title commitment", "preliminary title", "title report"),
    "ALTA or boundary survey": ("alta", "boundary survey", "topographic survey", "topo survey"),
    "Environmental report (Phase I / wetlands)": ("phase i", "environmental", "wetlands"),
    "Geotechnical report": ("geotechnical", "geotech", "soil boring", "soil report"),
    "Floodplain or drainage study": ("fema", "floodplain", "drainage study", "stormwater"),
    "Utility availability / will-serve documentation": ("will serve", "utility", "water", "sewer"),
    "Entitlement or zoning support": ("zoning", "plat", "annexation", "entitlement"),
}


DOCUMENT_GAP_HINTS: dict[str, tuple[str, ...]] = {
    "Referenced materials appear pending or incomplete in this document": (
        "to be provided",
        "tbd",
        "pending",
        "forthcoming",
        "not provided",
        "draft",
        "placeholder",
        "unknown",
    ),
}
