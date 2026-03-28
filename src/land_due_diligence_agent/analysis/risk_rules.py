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
    path_hints: tuple[str, ...] = ()
    reading_priority: int = 50


CATEGORY_RULES: tuple[RiskRule, ...] = (
    RiskRule(
        category="Entitlement Status",
        keywords=(
            "zoning",
            "entitlement",
            "annexation",
            "plat",
            "tentative map",
            "vesting",
            "design permit",
            "planning commission",
            "city council",
            "conditions of approval",
            "rezoning",
            "general plan",
        ),
        severe_keywords=("denied", "unapproved", "pending", "variance required", "rezoning required"),
        seller_question="What approvals are already secured, which remain outstanding, and what is the current entitlement schedule?",
        path_hints=("entitlement", "hearing", "resolution", "map", "plan set", "pc", "design permit", "subdivision"),
        reading_priority=92,
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
        path_hints=("environment", "phase i", "phase ii", "habitat", "biological", "mitigation"),
        reading_priority=96,
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
        path_hints=("stormwater", "drainage", "flood", "swcp", "hydrology"),
        reading_priority=90,
    ),
    RiskRule(
        category="Geotechnical Risks",
        keywords=(
            "geotechnical",
            "geotech",
            "soil",
            "soils",
            "expansive soil",
            "liquefaction",
            "fault",
            "fill",
            "seismic",
            "settlement",
            "grading",
            "foundation",
        ),
        severe_keywords=("liquefaction", "expansive soil", "fault rupture", "settlement", "overexcavation"),
        seller_question="What geotechnical constraints materially affect pad yields, grading costs, or foundation design assumptions?",
        path_hints=("geotechnical", "soils", "pavement", "grading", "geotech"),
        reading_priority=91,
    ),
    RiskRule(
        category="Offsite Obligations",
        keywords=(
            "offsite",
            "improvement agreement",
            "reimbursement",
            "participation agreement",
            "regional improvement",
            "proportionate share",
            "frontage",
            "encroachment permit",
        ),
        severe_keywords=("reimbursement", "frontage", "regional improvement", "participation agreement", "offsite sewer"),
        seller_question="Which offsite improvements, frontage work, fees, or reimbursement obligations remain with the buyer or landowner?",
        path_hints=("offsite", "frontage", "improvement agreement", "encroachment permit", "participation"),
        reading_priority=84,
    ),
    RiskRule(
        category="Fee / Exaction Burden",
        keywords=(
            "fee schedule",
            "impact fee",
            "capacity fee",
            "school fee",
            "building department fees",
            "public works fees",
            "park fee",
            "traffic impact fee",
            "exaction",
        ),
        severe_keywords=("fee increase", "impact fee", "capacity fee", "school fee", "special tax"),
        seller_question="Please provide the full fee and exaction matrix, note what is already confirmed, and identify which fee assumptions could still move materially.",
        path_hints=("fee", "fees", "exaction"),
        reading_priority=88,
    ),
    RiskRule(
        category="Budget / Cost Reliability",
        keywords=(
            "budget",
            "budgetary pricing",
            "pricing",
            "bid form",
            "proposal",
            "unit cost",
            "cost estimate",
            "cost opinion",
        ),
        severe_keywords=("budgetary", "allowance", "contingency", "conceptual", "preliminary"),
        seller_question="Which site-development cost assumptions remain preliminary, what bids are binding, and where are the largest unresolved cost risks?",
        path_hints=("budget", "pricing", "bid", "estimate", "cost"),
        reading_priority=87,
    ),
    RiskRule(
        category="Utilities / Infrastructure Issues",
        keywords=(
            "water capacity",
            "water service",
            "sewer capacity",
            "sewer service",
            "utility",
            "infrastructure",
            "lift station",
            "substation",
            "will serve",
            "joint trench",
            "dry utility",
        ),
        severe_keywords=("capacity deficiency", "moratorium", "lift station", "upsizing", "will-serve unavailable"),
        seller_question="What utility capacity constraints, offsite extensions, or will-serve contingencies could affect timing or cost?",
        path_hints=("utility", "joint trench", "water", "sewer", "infrastructure"),
        reading_priority=89,
    ),
    RiskRule(
        category="Title / Access Concerns",
        keywords=(
            "title report",
            "title commitment",
            "preliminary title",
            "access",
            "ingress",
            "egress",
            "easement",
            "encroachment",
            "title exception",
            "right-of-way",
        ),
        severe_keywords=("lack of access", "encroachment", "title exception", "uninsured", "exclusive easement"),
        seller_question="Please identify all title exceptions, access constraints, easements, and third-party rights that could impair development or marketability.",
        path_hints=("title", "survey", "access", "easement"),
        reading_priority=97,
    ),
    RiskRule(
        category="Schedule Risks",
        keywords=(
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
        path_hints=("schedule", "timeline", "resolution", "hearing"),
        reading_priority=80,
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
    "Fee schedule or exaction matrix": ("fee schedule", "impact fee", "capacity fee", "school fee"),
    "Site development budget or bid backup": ("budget", "pricing", "bid form", "estimate", "proposal"),
}


EXPECTED_DILIGENCE_PATH_HINTS: dict[str, tuple[str, ...]] = {
    "Current title commitment or title report": ("title",),
    "ALTA or boundary survey": ("survey",),
    "Environmental report (Phase I / wetlands)": ("environment", "phase i", "wetland"),
    "Geotechnical report": ("geotechnical", "geotech", "soils"),
    "Floodplain or drainage study": ("stormwater", "drainage", "flood"),
    "Utility availability / will-serve documentation": ("utility", "joint trench", "water", "sewer"),
    "Entitlement or zoning support": ("entitlement", "hearing", "resolution", "map", "plan set"),
    "Fee schedule or exaction matrix": ("fee", "fees"),
    "Site development budget or bid backup": ("budget", "pricing", "bid", "cost"),
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
