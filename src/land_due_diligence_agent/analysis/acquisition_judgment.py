"""Deterministic acquisition-grade sanity and economic reality pass."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
import re

from land_due_diligence_agent.analysis.fact_validation import (
    _coerce_float,
    _coerce_int,
    _contains_camelcase_artifact,
    _contains_non_alphanumeric_noise,
    _generic_text_issues,
    _looks_like_entity_name,
)
from land_due_diligence_agent.analysis.front_end import (
    deal_impact_mechanism_for_issue,
    deal_impact_type_for_issue,
    fixability_classification_for_issue,
    timing_exposure_band_for_issue,
)
from land_due_diligence_agent.models import (
    AcquisitionControllingFact,
    AcquisitionCriticalPathStep,
    AcquisitionDecision,
    AcquisitionInsight,
    AcquisitionJudgment,
    AcquisitionRiskItem,
    AcquisitionSanityCorrection,
    CanonicalIssue,
    CanonicalIssueRegistry,
    Citation,
    ContradictionFinding,
    DocumentRecord,
    ExtractedChunk,
    OmissionAssessment,
    RecommendationDecision,
)
from land_due_diligence_agent.utils.text import clip_text, tight_sentence, unique_preserve_order

_FACT_LABELS = {
    "gross_acreage": "Gross Acreage",
    "net_acreage": "Net Acreage",
    "site_acreage": "Site Acreage",
    "lot_count": "Lot Count",
    "unit_count": "Unit Count",
    "entitlement_status": "Entitlement Status",
    "zoning": "Zoning / Land Use",
    "jurisdiction": "Jurisdiction",
    "owner_name": "Ownership",
    "apn": "APN",
}
_CONFIDENCE_RANK = {"low": 1, "medium": 2, "high": 3}
_NO_RELIABLE_CONTROLLING_VALUE = "No reliable controlling value extracted"
_MAX_CREDIBLE_CANDIDATES = 3
_SECONDARY_DRIVER_LIMIT = 2
_RISK_BUCKETS = (
    "Primary Deal Driver",
    "Secondary Drivers",
    "Supporting Risks",
    "Noise",
)
_BUCKET_ORDER = {name: index for index, name in enumerate(_RISK_BUCKETS)}
_MONEY_SIGNAL_RE = re.compile(
    r"(?:\$\s?\d[\d,]*(?:\.\d+)?(?:\s*(?:million|mm|m|k|thousand))?|\b\d[\d,]*(?:\.\d+)?\s*(?:per lot|/lot|per unit|/unit)\b)",
    re.IGNORECASE,
)
_TIMING_SIGNAL_RE = re.compile(r"\b\d+\s*(?:business\s+days?|days?|weeks?|months?|quarters?)\b", re.IGNORECASE)
_SCOPE_HINTS = (
    ("impact fees or exactions", ("impact fee", "school fee", "fee", "fees", "exaction", "bond", "assessment district")),
    ("budget refresh or bid package", ("budgetary", "bid", "proposal", "estimate", "gmp", "cost opinion", "allowance")),
    ("offsite improvement scope", ("offsite", "frontage", "street improvement", "signal", "widening", "dedication", "public improvement")),
    ("utility capacity or extension scope", ("will serve", "capacity", "utility", "sewer", "water", "dry utility", "lift station", "booster")),
    ("environmental remediation scope", ("phase ii", "phase 2", "remediation", "mitigation", "cleanup", "contamination", "wetland")),
    ("geotechnical earthwork scope", ("geotechnical", "geotech", "overexcavation", "undercut", "retaining wall", "slope", "rock")),
    ("flood or drainage improvement scope", ("flood", "drainage", "storm drain", "detention", "basin", "hydrology")),
    ("title or access cure", ("title", "easement", "access", "vesting", "encroachment", "non-interference")),
    ("discretionary entitlement path", ("rezoning", "variance", "general plan amendment", "planning commission", "city council", "tentative map", "appeal")),
)
_OWNER_ENTITY_TERMS = (
    "llc",
    "lp",
    "l.p",
    "inc",
    "corp",
    "corporation",
    "company",
    "holdings",
    "ventures",
    "properties",
    "trust",
    "partners",
)
_OWNER_REJECT_TERMS = {
    "sheet",
    "plan",
    "note",
    "notes",
    "map",
    "lot",
    "block",
    "phase",
    "tract",
    "existing",
    "proposed",
    "civil",
    "landscape",
    "architectural",
    "architecture",
    "engineering",
    "utility",
    "legend",
    "north",
    "scale",
}
_LEGAL_PROSE_REJECT_TERMS = {
    "assigns",
    "grantee",
    "grantor",
    "herein",
    "lease",
    "leases",
    "subject to",
    "successors",
    "tenant",
    "undersigned",
    "whereas",
}
_UTILITY_PROVIDER_TERMS = {
    "electric",
    "energy",
    "gas",
    "power",
    "telephone",
    "utility",
    "water",
}
_ZONING_REJECT_TERMS = {
    "approval",
    "condition",
    "conditions",
    "development standards",
    "laws",
    "sheet",
    "setback",
    "setbacks",
    "note",
}
_LAND_USE_ONLY_TERMS = (
    "high density residential",
    "medium density residential",
    "low density residential",
    "residential",
    "commercial",
    "industrial",
    "mixed use",
    "mixed-use",
)
_COUNT_REJECT_CONTEXT_TERMS = (
    "closure calculation",
    "closure calculations",
    "general notes",
    "legend",
    "row",
    "sheet",
    "table",
)
_ACREAGE_FRAGMENT_TERMS = (
    "basin",
    "disturbed",
    "grading limits",
    "landscape",
    "offsite",
    "open space",
    "phase",
    "pocket park",
    "swppp",
)
_REAL_ZONING_CODE_RE = re.compile(
    r"^(?:"
    r"[A-Z]{1,4}-?\d{0,3}[A-Z]?"
    r"|PD-?\d{0,3}(?:\s+[A-Z]{1,3}(?:-?[A-Z])?)?"
    r"|PUD"
    r"|SP"
    r"|RM-?\d{0,2}"
    r"|RE-?\d{0,2}"
    r"|RS-?\d{0,2}"
    r"|RD-?\d{0,2}"
    r"|RC-?\d{0,2}"
    r"|MDR"
    r"|HDR"
    r"|MU"
    r"|A-?\d{0,2}"
    r"|C-?\d{0,2}"
    r"|I-?\d{0,2}"
    r")(?:[\s/-][A-Z0-9]{1,4})*$",
    re.IGNORECASE,
)
_APN_VALUE_RE = re.compile(r"^(?:[A-Z0-9]{2,6}(?:-[A-Z0-9]{1,6}){1,5}|\d{6,16})$", re.IGNORECASE)
_PRODUCT_HINTS = (
    ("single-family detached", ("single family detached", "single-family detached", "detached home", "detached homes"), True),
    ("single-family attached / townhome", ("townhome", "town home", "townhouse", "single-family attached"), True),
    ("multifamily", ("multifamily", "multi-family", "apartment", "apartments", "stacked flat"), False),
)
_COUNT_SUBCOMPONENT_TERMS = ("building", "phase", "product type", "plan type", "model", "stacked")
_JURISDICTION_CONTEXT_TERMS = (
    "city of",
    "county of",
    "jurisdiction",
    "staff report",
    "planning commission",
    "city council",
    "site description",
    "environmental site assessment",
    "esa",
)
_OWNER_SOURCE_TERMS = (
    "environmental site assessment",
    "fee owner",
    "owner:",
    "preliminary title",
    "record owner",
    "seller:",
    "seller is",
    "site description",
    "title report",
    "vested in",
    "vesting",
)
_ZONING_CONTEXT_TERMS = (
    "approval",
    "conditions of approval",
    "district",
    "general plan",
    "land use",
    "resolution",
    "staff report",
    "zoning",
    "zone",
)
_COUNT_CONTEXT_TERMS = {
    "lot_count": (
        "approval",
        "approved",
        "lots",
        "plan cover",
        "project proposes",
        "site plan",
        "staff report",
        "subdivide",
        "tentative map",
        "tract",
    ),
    "unit_count": (
        "approval",
        "approved",
        "design review",
        "dwelling units",
        "homes",
        "project proposes",
        "site plan",
        "staff report",
        "tentative map",
        "total units",
        "units",
    ),
}
_ACREAGE_CONTEXT_TERMS = {
    "gross_acreage": ("gross acreage", "gross site", "legal description", "parcel map", "site area", "staff report", "survey", "title"),
    "net_acreage": ("legal description", "net acreage", "parcel map", "site area", "staff report", "survey", "title"),
    "site_acreage": ("parcel acreage", "project acreage", "property acreage", "site acreage", "site area", "site plan", "staff report", "survey"),
}
_STAGE_RULES = (
    (
        "Final Map",
        {
            "categories": {
                "Title / Access Concerns",
                "Entitlement Status",
                "Offsite Obligations",
                "Utilities / Infrastructure Issues",
            },
            "schedule_classes": {"immediate blocker", "pre-close blocker", "pre-final-map blocker"},
            "terms": (
                "final map",
                "recordation",
                "record",
                "title",
                "vesting",
                "easement",
                "dedication",
                "annexation",
                "tentative map",
            ),
        },
    ),
    (
        "Grading Permit",
        {
            "categories": {
                "Geotechnical Risks",
                "Flood / Drainage Issues",
                "Utilities / Infrastructure Issues",
                "Offsite Obligations",
                "Entitlement Status",
            },
            "schedule_classes": {"pre-underwriting blocker", "pre-close blocker"},
            "terms": (
                "grading",
                "geotech",
                "geotechnical",
                "drainage",
                "storm",
                "civil",
                "utility",
                "improvement plan",
                "public works",
            ),
        },
    ),
    (
        "Vertical Start",
        {
            "categories": {
                "Entitlement Status",
                "Utilities / Infrastructure Issues",
                "Offsite Obligations",
                "Budget / Cost Reliability",
                "Fee / Exaction Burden",
                "Schedule Risks",
            },
            "schedule_classes": {"pre-vertical-start blocker", "pre-close blocker"},
            "terms": (
                "vertical",
                "building permit",
                "foundation",
                "product",
                "utility",
                "offsite",
                "schedule",
                "permit",
            ),
        },
    ),
)
_DEAL_STAGE_ORDER = (
    "early land / pre-approval",
    "approved horizontal land",
    "finished lot / near-finished lot",
    "vertical / builder-ready",
)
_DEAL_STAGE_TERMS = {
    "early land / pre-approval": (
        ("annexation", 4),
        ("discretionary", 3),
        ("general plan amendment", 4),
        ("not approved", 4),
        ("rezoning", 4),
        ("variance", 3),
    ),
    "approved horizontal land": (
        ("conditions of approval", 5),
        ("grading permit", 3),
        ("improvement plan", 3),
        ("mass grading", 3),
        ("tentative map approved", 5),
    ),
    "finished lot / near-finished lot": (
        ("acceptance", 2),
        ("cc&r", 2),
        ("closure calculations", 6),
        ("final map", 5),
        ("finished lot", 6),
        ("lot release", 4),
        ("recorded", 3),
    ),
    "vertical / builder-ready": (
        ("builder-ready", 6),
        ("building permit", 6),
        ("house plan", 3),
        ("lot takedown", 3),
        ("model home", 3),
        ("vertical start", 5),
    ),
}
_STAGE_CATEGORY_SCORES = {
    "early land / pre-approval": {
        "Title / Access Concerns": 2,
        "Entitlement Status": 4,
        "Environmental Risks": 2,
        "Geotechnical Risks": 2,
        "Flood / Drainage Issues": 2,
        "Utilities / Infrastructure Issues": 2,
        "Offsite Obligations": 2,
        "Fee / Exaction Burden": 1,
        "Budget / Cost Reliability": 1,
        "Schedule Risks": 1,
    },
    "approved horizontal land": {
        "Title / Access Concerns": 2,
        "Entitlement Status": 3,
        "Environmental Risks": 2,
        "Geotechnical Risks": 3,
        "Flood / Drainage Issues": 3,
        "Utilities / Infrastructure Issues": 3,
        "Offsite Obligations": 3,
        "Fee / Exaction Burden": 2,
        "Budget / Cost Reliability": 2,
        "Schedule Risks": 2,
    },
    "finished lot / near-finished lot": {
        "Title / Access Concerns": 1,
        "Entitlement Status": 1,
        "Environmental Risks": 1,
        "Geotechnical Risks": 2,
        "Flood / Drainage Issues": 2,
        "Utilities / Infrastructure Issues": 2,
        "Offsite Obligations": 2,
        "Fee / Exaction Burden": 2,
        "Budget / Cost Reliability": 2,
        "Schedule Risks": 2,
    },
    "vertical / builder-ready": {
        "Title / Access Concerns": 1,
        "Entitlement Status": 1,
        "Environmental Risks": 1,
        "Geotechnical Risks": 1,
        "Flood / Drainage Issues": 1,
        "Utilities / Infrastructure Issues": 2,
        "Offsite Obligations": 1,
        "Fee / Exaction Burden": 2,
        "Budget / Cost Reliability": 2,
        "Schedule Risks": 3,
    },
}
_STAGE_FACT_MATERIALITY = {
    "early land / pre-approval": {"gross_acreage", "net_acreage", "site_acreage", "lot_count", "unit_count", "entitlement_status", "zoning", "jurisdiction", "owner_name", "apn"},
    "approved horizontal land": {"gross_acreage", "net_acreage", "site_acreage", "lot_count", "unit_count", "entitlement_status", "zoning", "jurisdiction", "owner_name", "apn"},
    "finished lot / near-finished lot": {"unit_count", "entitlement_status", "jurisdiction", "owner_name", "apn"},
    "vertical / builder-ready": {"unit_count", "owner_name", "apn"},
}
_COUNT_STAGE_LIMITS = {
    "early land / pre-approval": {"lot_count": 2500, "unit_count": 4000},
    "approved horizontal land": {"lot_count": 1500, "unit_count": 2500},
    "finished lot / near-finished lot": {"lot_count": 1000, "unit_count": 1500},
    "vertical / builder-ready": {"lot_count": 600, "unit_count": 2000},
}
_ISSUE_CLASS_ORDER = {
    "true blocker": 0,
    "material but solvable execution risk": 1,
    "pricing / basis watch item": 2,
    "routine confirmation item": 3,
    "noise / ignore": 4,
}
_ISSUE_EVIDENCE_SCORES = {
    "direct_unresolved_risk": 3,
    "contradictory_evidence_present": 2,
    "direct_confirmed_risk": 2,
    "omission_only": 0,
    "routine_missing_support": -1,
    "weak_inference": -2,
}
_ISSUE_STRENGTH_SCORES = {"strong": 2, "moderate": 0, "weak": -2}
_ISSUE_FALSE_POSITIVE_SCORES = {"low": 1, "medium": 0, "high": -2}
_DIRECT_BLOCKER_TERMS = (
    "appeal pending",
    "cannot",
    "cannot close",
    "cannot record",
    "cannot start vertical",
    "close will not occur",
    "denied",
    "expired",
    "fatal",
    "final map cannot",
    "grading permit cannot",
    "no legal access",
    "not approved",
    "recordation blocked",
)
_NON_BLOCKER_TERMS = (
    "confirm",
    "refresh",
    "routine",
    "verify",
)
_YEAR_RE = re.compile(r"\b(19\d{2}|20\d{2})\b")
_APN_REGEX = re.compile(
    r"\b(?:A\.?P\.?N\.?|APN|Assessor(?:'s)? Parcel Number(?:\(s\))?)\s*(?:No\.?|#|:)?\s*([A-Z0-9-]{6,})",
    re.IGNORECASE,
)
_ACREAGE_REGEXES = {
    "gross_acreage": re.compile(r"\bgross(?:\s+site)?\s+(?:acreage|acres?)\s*(?:is|=|:)?\s*(\d+(?:\.\d+)?)\s*(?:acres?|ac\.?)", re.IGNORECASE),
    "net_acreage": re.compile(r"\bnet\s+(?:acreage|acres?)\s*(?:is|=|:)?\s*(\d+(?:\.\d+)?)\s*(?:acres?|ac\.?)", re.IGNORECASE),
    "site_acreage": re.compile(r"\b(?:site|property|parcel|project)\s+(?:acreage|area)\s*(?:is|=|:)?\s*(\d+(?:\.\d+)?)\s*(?:acres?|ac\.?)", re.IGNORECASE),
}
_LOT_COUNT_REGEXES = (
    re.compile(r"\b(\d{1,4})\s+(?:single[- ]family\s+)?lots?\b", re.IGNORECASE),
    re.compile(r"\b(?:into|subdivide(?:d)?\s+into)\s+(\d{1,4})\s+(?:parcels?|lots?)\b", re.IGNORECASE),
)
_UNIT_COUNT_REGEXES = (
    re.compile(r"\b(\d{1,5})\s+(?:dwelling\s+)?units?\b", re.IGNORECASE),
    re.compile(r"\b(\d{1,5})\s+(?:single[- ]family\s+)?homes?\b", re.IGNORECASE),
)
_ZONING_REGEXES = (
    re.compile(r"\b(?:current\s+)?zoning(?:\s+designation|\s+district)?\s*(?:is|as|=|:)?\s*([A-Za-z0-9\-/ ()]{2,50}?)(?=[.;,\n]|$)", re.IGNORECASE),
    re.compile(r"\b(?:zoned|zone(?:\s+district)?)\s*(?:is|as|=|:)?\s*([A-Za-z0-9\-/ ()]{2,50}?)(?=[.;,\n]|$)", re.IGNORECASE),
)
_LAND_USE_REGEX = re.compile(r"\b(?:general\s+plan\s+)?land use(?:\s+designation)?\s*(?:is|as|=|:)?\s*([A-Za-z0-9\-/ ()]{2,60}?)(?=[.;,\n]|$)", re.IGNORECASE)
_CITY_REGEX = re.compile(r"\bCity of\s+([A-Z][A-Za-z .-]{2,40}?)(?=[.;,\n]|$)")
_COUNTY_REGEX = re.compile(r"\bCounty of\s+([A-Z][A-Za-z .-]{2,40}?)(?=[.;,\n]|$)")
_OWNER_REGEXES = (
    re.compile(r"\bvested in\s*:?\s*([A-Z][A-Za-z0-9 ,.()&-]{3,100}?)(?=[.;\n]|$)"),
    re.compile(r"\bownership\s*(?:is|:)?\s*([A-Z][A-Za-z0-9 ,.()&-]{3,100}?)(?=[.;\n]|$)", re.IGNORECASE),
    re.compile(r"\b(?:fee owner|record owner|owner)\b\s*(?:is|:)?\s*([A-Z][A-Za-z0-9 ,.()&-]{3,100}?)(?=[.;\n]|$)", re.IGNORECASE),
    re.compile(r"\b(?:seller)\b\s*(?:is|:)?\s*([A-Z][A-Za-z0-9 ,.()&-]{3,100}?)(?=[.;\n]|$)", re.IGNORECASE),
)
_DOC_AUTHORITY_TERMS = {
    "gross_acreage": (("survey", 6), ("legal description", 5), ("title", 5), ("parcel map", 4), ("tract", 4), ("site plan", 3), ("staff report", 2), ("esa", 1)),
    "net_acreage": (("survey", 6), ("legal description", 5), ("title", 5), ("parcel map", 4), ("tract", 4), ("site plan", 3), ("staff report", 2), ("esa", 1)),
    "site_acreage": (("survey", 5), ("parcel map", 4), ("site plan", 4), ("tract", 4), ("title", 3), ("staff report", 2), ("esa", 1)),
    "lot_count": (("tentative map", 6), ("tract", 5), ("staff report", 5), ("approval", 4), ("resolution", 4), ("site plan", 3), ("cover sheet", 2), ("plan set", 2)),
    "unit_count": (("tentative map", 6), ("staff report", 5), ("design review", 4), ("approval", 4), ("resolution", 4), ("site plan", 3), ("cover sheet", 2), ("plan set", 2)),
    "zoning": (("staff report", 6), ("resolution", 5), ("conditions", 5), ("approval", 4), ("zoning", 4), ("general plan", 3), ("land use", 3)),
    "jurisdiction": (("city of", 6), ("county of", 5), ("staff report", 4), ("approval", 3), ("title", 2), ("esa", 1), ("site description", 1)),
    "owner_name": (("vested in", 7), ("title", 6), ("preliminary report", 5), ("commitment", 5), ("fee owner", 4), ("record owner", 4), ("seller", 2), ("esa", 1), ("site description", 1)),
    "apn": (("title", 7), ("preliminary report", 6), ("commitment", 6), ("parcel", 4), ("legal description", 4), ("vesting", 3), ("esa", 1), ("site description", 1)),
    "entitlement_status": (("resolution", 5), ("conditions", 5), ("planning commission", 4), ("city council", 4), ("tentative map", 4), ("approval", 3)),
}
_DOC_NEGATIVE_TERMS = (("summary", -2), ("overview", -2), ("matrix", -2), ("tracker", -1), ("draft", -1), ("legend", -3), ("general notes", -3), ("utility", -2), ("closure calculation", -3), ("swppp", -3))


@dataclass(slots=True, frozen=True)
class _FactCandidate:
    fact_type: str
    value: str
    normalized_value: str
    relative_path: str
    excerpt: str
    page_number: int | None = None
    ocr_used: bool = False
    chunk_id: str = ""
    confidence: str = "medium"
    subtype: str = ""
    quality_note: str = ""
    labeled_field: bool = False


@dataclass(slots=True, frozen=True)
class _ProductInference:
    label: str
    one_unit_per_lot: bool
    basis: str


@dataclass(slots=True, frozen=True)
class _ScopeRead:
    scope_label: str = ""
    cost_status: str = "unknown"
    cost_detail: str = ""
    land_value_detail: str = ""
    margin_detail: str = ""
    irr_detail: str = ""
    timing_status: str = "unknown"
    timing_detail: str = ""
    explicit_costs: tuple[str, ...] = ()
    explicit_timing: tuple[str, ...] = ()


@dataclass(slots=True, frozen=True)
class _DocumentProfile:
    document: DocumentRecord
    relative_path: str
    path_text: str
    text: str
    reliability: str
    reliability_note: str
    reliability_score: int
    recency_year: int | None
    recency_score: int
    role: str


@dataclass(slots=True, frozen=True)
class _DealProfile:
    stage: str
    basis: str


def _build_document_profiles(documents: list[DocumentRecord]) -> list[_DocumentProfile]:
    profiles: list[_DocumentProfile] = []
    for document in documents:
        relative_path = document.relative_path.as_posix()
        path_text = relative_path.lower()
        text = document.normalized_text.lower()
        reliability, reliability_note, reliability_score = _document_reliability(document)
        recency_year = _document_recency_year(document)
        recency_score = _document_recency_score(recency_year)
        role = _document_role(path_text, text)
        profiles.append(
            _DocumentProfile(
                document=document,
                relative_path=relative_path,
                path_text=path_text,
                text=text,
                reliability=reliability,
                reliability_note=reliability_note,
                reliability_score=reliability_score,
                recency_year=recency_year,
                recency_score=recency_score,
                role=role,
            )
        )
    return profiles


def _profile_lookup(document_profiles: list[_DocumentProfile]) -> dict[str, list[_DocumentProfile]]:
    lookup: dict[str, list[_DocumentProfile]] = {}
    for profile in document_profiles:
        aliases = {
            profile.document.title.lower(),
            Path(profile.relative_path).name.lower(),
            Path(profile.relative_path).stem.lower(),
        }
        for alias in aliases:
            lookup.setdefault(alias, []).append(profile)
    return lookup


def _document_reliability(document: DocumentRecord) -> tuple[str, str, int]:
    warnings_text = " ".join(document.warnings).lower()
    page_count = int(document.metadata.get("page_count", 0) or 0)
    ocr_pages = len(document.ocr_pages)
    unrecovered_ocr_pages = max(0, len(document.ocr_pages) - len(document.ocr_recovered_pages))
    text_length = len(document.normalized_text.strip())

    if "normalized text is empty" in warnings_text or text_length == 0:
        return "low", "No usable extracted text.", -3
    if unrecovered_ocr_pages and page_count and (unrecovered_ocr_pages / page_count) >= 0.15:
        return "low", "Meaningful pages remain weak after OCR fallback.", -3
    if ocr_pages and page_count and (ocr_pages / page_count) >= 0.4:
        return "low", "Heavy OCR fallback makes this document unreliable as a controlling source.", -2
    if unrecovered_ocr_pages or ocr_pages or text_length < 500:
        return "medium", "Readable, but not strong enough to outrank cleaner controlling support by itself.", 0
    return "high", "Clean extracted text with no material OCR warning.", 2


def _document_recency_year(document: DocumentRecord) -> int | None:
    sample = " ".join(
        part
        for part in (
            document.relative_path.as_posix(),
            document.title,
            document.normalized_text[:1600],
        )
        if part
    )
    years = [int(match.group(1)) for match in _YEAR_RE.finditer(sample) if 1990 <= int(match.group(1)) <= datetime.now().year + 1]
    if years:
        return max(years)
    try:
        return datetime.fromtimestamp(document.source_path.stat().st_mtime).year
    except OSError:
        return None


def _document_recency_score(recency_year: int | None) -> int:
    if recency_year is None:
        return 0
    age = max(0, datetime.now().year - recency_year)
    if age <= 2:
        return 1
    if age <= 5:
        return 0
    if age <= 8:
        return -1
    return -2


def _document_role(path_text: str, text: str) -> str:
    haystack = f"{path_text} {text[:3000]}"
    if any(term in haystack for term in ("title report", "preliminary report", "commitment", "vesting", "vested in")):
        return "control_title"
    if any(term in haystack for term in ("final map", "tract map", "parcel map", "recorded map", "survey", "plat")):
        return "control_map"
    if any(term in haystack for term in ("staff report", "resolution", "conditions of approval", "planning commission", "city council", "tentative map")):
        return "control_approval"
    if any(term in haystack for term in ("purchase agreement", "purchase and sale", "psa", "agreement")):
        return "control_agreement"
    if any(term in haystack for term in ("closure calculations", "matrix", "summary", "tracker", "swppp", "general notes")):
        return "secondary_narrative"
    return "supporting_execution"


def _classify_deal_profile(
    *,
    document_profiles: list[_DocumentProfile],
    registry: CanonicalIssueRegistry,
    entitlement_status: str,
    product: _ProductInference,
) -> _DealProfile:
    scores = {stage: 0 for stage in _DEAL_STAGE_ORDER}
    evidence: dict[str, list[str]] = {stage: [] for stage in _DEAL_STAGE_ORDER}

    for profile in document_profiles:
        haystack = f"{profile.path_text} {profile.text[:4000]}"
        for stage, terms in _DEAL_STAGE_TERMS.items():
            for term, weight in terms:
                if term in haystack:
                    scores[stage] += weight
                    evidence[stage].append(Path(profile.relative_path).name)

    entitlement_text = entitlement_status.lower()
    if "approved entitlement path" in entitlement_text:
        scores["approved horizontal land"] += 2
    if any(term in entitlement_text for term in ("condition closeout", "final map", "implementation steps")):
        scores["finished lot / near-finished lot"] += 2
    if any(term in entitlement_text for term in ("discretionary entitlement", "not show a fully approved executable entitlement path")):
        scores["early land / pre-approval"] += 3

    if registry.blocker_issue_ids:
        scores["approved horizontal land"] += 1
    if any(issue.category in {"Budget / Cost Reliability", "Schedule Risks"} for issue in registry.issues):
        scores["finished lot / near-finished lot"] += 1
    if any("building permit" in (issue.critical_path_reason or issue.blocking_reason or issue.title).lower() for issue in registry.issues):
        scores["vertical / builder-ready"] += 2

    chosen = sorted(_DEAL_STAGE_ORDER, key=lambda stage: (-scores[stage], _DEAL_STAGE_ORDER.index(stage)))[0]
    if scores[chosen] == 0:
        chosen = "approved horizontal land"

    supporting_docs = ", ".join(unique_preserve_order(evidence[chosen])[:3]) or product.label
    basis = tight_sentence(f"Classified as {chosen} based on the strongest readable stage signals in {supporting_docs}.", 220)
    return _DealProfile(stage=chosen, basis=basis)


def build_acquisition_judgment(
    *,
    documents: list[DocumentRecord],
    registry: CanonicalIssueRegistry,
    omission_assessments: list[OmissionAssessment],
    contradictions: list[ContradictionFinding],
    recommendation: RecommendationDecision,
    entitlement_status: str,
) -> AcquisitionJudgment:
    """Build a second-pass IC-ready synthesis from the analyzed deal package."""

    document_profiles = _build_document_profiles(documents)
    profile_by_path = {profile.relative_path: profile for profile in document_profiles}
    profile_lookup = _profile_lookup(document_profiles)
    fact_candidates = _extract_control_fact_candidates(document_profiles)
    product = _infer_product_type(document_profiles)
    deal_profile = _classify_deal_profile(
        document_profiles=document_profiles,
        registry=registry,
        entitlement_status=entitlement_status,
        product=product,
    )
    controlling_facts, sanity_corrections = _build_controlling_facts(
        fact_candidates=fact_candidates,
        documents=documents,
        contradictions=contradictions,
        entitlement_status=entitlement_status,
        product=product,
        profile_by_path=profile_by_path,
        deal_profile=deal_profile,
    )
    lot_count = _fact_count_value(controlling_facts, "lot_count")
    risk_items = _build_risk_items(
        registry.issues,
        lot_count=lot_count,
        deal_profile=deal_profile,
        profile_lookup=profile_lookup,
    )
    critical_path = _build_clean_gating_chain(registry.issues, risk_items)
    decision = _build_investment_decision(
        controlling_facts=controlling_facts,
        sanity_corrections=sanity_corrections,
        risk_items=risk_items,
        critical_path=critical_path,
        omission_assessments=omission_assessments,
        contradictions=contradictions,
        recommendation=recommendation,
        registry=registry,
        deal_profile=deal_profile,
    )
    weak_misses: list[AcquisitionInsight] = []
    return AcquisitionJudgment(
        sanity_corrections=sanity_corrections,
        controlling_facts=controlling_facts,
        risk_items=risk_items,
        critical_path=critical_path,
        investment_decision=decision,
        weak_acquisition_misses=weak_misses,
    )


def _extract_control_fact_candidates(document_profiles: list[_DocumentProfile]) -> dict[str, list[_FactCandidate]]:
    candidates: dict[str, list[_FactCandidate]] = {key: [] for key in _FACT_LABELS}
    seen: set[tuple[str, str, str, str, str | None]] = set()

    for profile in document_profiles:
        document = profile.document
        for chunk in _iter_document_chunks(document):
            text = chunk.text or ""

            for match in _APN_REGEX.finditer(text):
                value = _normalize_apn_value(match.group(1))
                _append_candidate(
                    candidates["apn"],
                    seen,
                    _FactCandidate(
                        fact_type="apn",
                        value=value,
                        normalized_value=value.lower(),
                        relative_path=document.relative_path.as_posix(),
                        excerpt=_excerpt(text, match.start(), match.end()),
                        page_number=chunk.page_number,
                        ocr_used=chunk.ocr_used,
                        chunk_id=chunk.chunk_id,
                        confidence="high",
                        quality_note="APN-style parcel number extracted from labeled parcel context.",
                        labeled_field=True,
                    ),
                )

            for fact_type, regex in _ACREAGE_REGEXES.items():
                for match in regex.finditer(text):
                    value = _normalize_numeric(match.group(1))
                    excerpt = _excerpt(text, match.start(), match.end())
                    _append_candidate(
                        candidates[fact_type],
                        seen,
                        _FactCandidate(
                            fact_type=fact_type,
                            value=value,
                            normalized_value=value,
                            relative_path=document.relative_path.as_posix(),
                            excerpt=excerpt,
                            page_number=chunk.page_number,
                            ocr_used=chunk.ocr_used,
                            chunk_id=chunk.chunk_id,
                            confidence="high" if any(term in excerpt.lower() for term in _ACREAGE_CONTEXT_TERMS[fact_type]) else "medium",
                            quality_note="Acreage candidate extracted from a labeled site-measurement reference.",
                            labeled_field=True,
                        ),
                    )

            for regex in _LOT_COUNT_REGEXES:
                for match in regex.finditer(text):
                    excerpt = _excerpt(text, match.start(), match.end())
                    labeled_field = any(term in excerpt.lower() for term in _COUNT_CONTEXT_TERMS["lot_count"])
                    _append_candidate(
                        candidates["lot_count"],
                        seen,
                        _FactCandidate(
                            fact_type="lot_count",
                            value=match.group(1),
                            normalized_value=_normalize_numeric(match.group(1)),
                            relative_path=document.relative_path.as_posix(),
                            excerpt=excerpt,
                            page_number=chunk.page_number,
                            ocr_used=chunk.ocr_used,
                            chunk_id=chunk.chunk_id,
                            confidence=_count_candidate_confidence(excerpt, labeled_field=labeled_field),
                            labeled_field=labeled_field,
                        ),
                    )

            for regex in _UNIT_COUNT_REGEXES:
                for match in regex.finditer(text):
                    excerpt = _excerpt(text, match.start(), match.end())
                    if "du/ac" in excerpt.lower() or "per acre" in excerpt.lower():
                        continue
                    labeled_field = any(term in excerpt.lower() for term in _COUNT_CONTEXT_TERMS["unit_count"])
                    _append_candidate(
                        candidates["unit_count"],
                        seen,
                        _FactCandidate(
                            fact_type="unit_count",
                            value=match.group(1),
                            normalized_value=_normalize_numeric(match.group(1)),
                            relative_path=document.relative_path.as_posix(),
                            excerpt=excerpt,
                            page_number=chunk.page_number,
                            ocr_used=chunk.ocr_used,
                            chunk_id=chunk.chunk_id,
                            confidence=_count_candidate_confidence(excerpt, labeled_field=labeled_field),
                            labeled_field=labeled_field,
                        ),
                    )

            for regex in _ZONING_REGEXES:
                for match in regex.finditer(text):
                    value = _normalize_named_value(match.group(1))
                    subtype, confidence, note = _classify_zoning_candidate(value)
                    if not subtype:
                        continue
                    _append_candidate(
                        candidates["zoning"],
                        seen,
                        _FactCandidate(
                            fact_type="zoning",
                            value=value,
                            normalized_value=value.lower(),
                            relative_path=document.relative_path.as_posix(),
                            excerpt=_excerpt(text, match.start(), match.end()),
                            page_number=chunk.page_number,
                            ocr_used=chunk.ocr_used,
                            chunk_id=chunk.chunk_id,
                            confidence=confidence,
                            subtype=subtype,
                            quality_note=note,
                            labeled_field=True,
                        ),
                    )
            for match in _LAND_USE_REGEX.finditer(text):
                value = _normalize_named_value(match.group(1))
                subtype, confidence, note = _classify_zoning_candidate(value, land_use_only=True)
                if not subtype:
                    continue
                _append_candidate(
                    candidates["zoning"],
                    seen,
                    _FactCandidate(
                        fact_type="zoning",
                        value=value,
                        normalized_value=value.lower(),
                        relative_path=document.relative_path.as_posix(),
                        excerpt=_excerpt(text, match.start(), match.end()),
                        page_number=chunk.page_number,
                        ocr_used=chunk.ocr_used,
                        chunk_id=chunk.chunk_id,
                        confidence=confidence,
                        subtype=subtype,
                        quality_note=note,
                        labeled_field=True,
                    ),
                )

            for match in _CITY_REGEX.finditer(text):
                value = _normalize_named_value(match.group(1))
                _append_candidate(
                    candidates["jurisdiction"],
                    seen,
                    _FactCandidate(
                        fact_type="jurisdiction",
                        value=value,
                        normalized_value=value.lower(),
                        relative_path=document.relative_path.as_posix(),
                        excerpt=_excerpt(text, match.start(), match.end()),
                        page_number=chunk.page_number,
                        ocr_used=chunk.ocr_used,
                        chunk_id=chunk.chunk_id,
                        confidence="high",
                        quality_note="City reference is typically the operative land-use jurisdiction.",
                        labeled_field=True,
                    ),
                )
            for match in _COUNTY_REGEX.finditer(text):
                value = _normalize_named_value(match.group(1))
                _append_candidate(
                    candidates["jurisdiction"],
                    seen,
                    _FactCandidate(
                        fact_type="jurisdiction",
                        value=value,
                        normalized_value=value.lower(),
                        relative_path=document.relative_path.as_posix(),
                        excerpt=_excerpt(text, match.start(), match.end()),
                        page_number=chunk.page_number,
                        ocr_used=chunk.ocr_used,
                        chunk_id=chunk.chunk_id,
                        confidence="medium",
                        quality_note="County references can be geographic but not always the operative planning jurisdiction.",
                        labeled_field=True,
                    ),
                )

            for regex in _OWNER_REGEXES:
                for match in regex.finditer(text):
                    value = _normalize_named_value(match.group(1))
                    confidence, note = _classify_owner_candidate(value)
                    if confidence is None:
                        continue
                    _append_candidate(
                        candidates["owner_name"],
                        seen,
                        _FactCandidate(
                            fact_type="owner_name",
                            value=value,
                            normalized_value=value.lower(),
                            relative_path=document.relative_path.as_posix(),
                            excerpt=_excerpt(text, match.start(), match.end()),
                            page_number=chunk.page_number,
                            ocr_used=chunk.ocr_used,
                            chunk_id=chunk.chunk_id,
                            confidence=confidence,
                            quality_note=note,
                            labeled_field=True,
                        ),
                    )

    return candidates


def _build_controlling_facts(
    *,
    fact_candidates: dict[str, list[_FactCandidate]],
    documents: list[DocumentRecord],
    contradictions: list[ContradictionFinding],
    entitlement_status: str,
    product: _ProductInference,
    profile_by_path: dict[str, _DocumentProfile],
    deal_profile: _DealProfile,
) -> tuple[list[AcquisitionControllingFact], list[AcquisitionSanityCorrection]]:
    gross_fact = _build_standard_controlling_fact("gross_acreage", fact_candidates.get("gross_acreage", []), profile_by_path=profile_by_path, deal_profile=deal_profile)
    net_fact = _build_standard_controlling_fact("net_acreage", fact_candidates.get("net_acreage", []), profile_by_path=profile_by_path, deal_profile=deal_profile)
    site_fact = _build_standard_controlling_fact("site_acreage", fact_candidates.get("site_acreage", []), profile_by_path=profile_by_path, deal_profile=deal_profile)
    lot_fact = _build_standard_controlling_fact("lot_count", fact_candidates.get("lot_count", []), profile_by_path=profile_by_path, deal_profile=deal_profile)
    unit_fact = _build_standard_controlling_fact("unit_count", fact_candidates.get("unit_count", []), profile_by_path=profile_by_path, deal_profile=deal_profile)
    jurisdiction_fact = _build_standard_controlling_fact("jurisdiction", fact_candidates.get("jurisdiction", []), profile_by_path=profile_by_path, deal_profile=deal_profile)
    owner_fact, owner_correction = _build_owner_controlling_fact(fact_candidates.get("owner_name", []), profile_by_path=profile_by_path, deal_profile=deal_profile)
    zoning_fact, zoning_correction = _build_zoning_controlling_fact(fact_candidates.get("zoning", []), profile_by_path=profile_by_path, deal_profile=deal_profile)
    apn_fact = _build_standard_controlling_fact("apn", fact_candidates.get("apn", []), profile_by_path=profile_by_path, deal_profile=deal_profile)
    entitlement_fact = _build_entitlement_controlling_fact(
        documents=documents,
        contradictions=contradictions,
        entitlement_status=entitlement_status,
        profile_by_path=profile_by_path,
    )
    unit_fact, unit_correction = _reconcile_unit_count(
        lot_fact=lot_fact,
        unit_fact=unit_fact,
        unit_candidates=fact_candidates.get("unit_count", []),
        product=product,
    )

    controlling_facts = [
        gross_fact,
        net_fact,
        site_fact,
        lot_fact,
        unit_fact,
        entitlement_fact,
        zoning_fact,
        jurisdiction_fact,
        owner_fact,
        apn_fact,
    ]
    corrections = [
        correction
        for correction in (unit_correction, zoning_correction, owner_correction)
        if correction is not None
    ]
    return controlling_facts, corrections


def _build_standard_controlling_fact(
    fact_type: str,
    candidates: list[_FactCandidate],
    *,
    profile_by_path: dict[str, _DocumentProfile],
    deal_profile: _DealProfile,
) -> AcquisitionControllingFact:
    label = _FACT_LABELS[fact_type]
    viable, rejected, support_counts = _review_fact_candidates(fact_type, candidates, profile_by_path=profile_by_path, deal_profile=deal_profile)
    if not viable:
        return _fallback_controlling_fact(
            fact_type,
            rejected or candidates,
            profile_by_path=profile_by_path,
            why_it_controls=f"No candidate passed the field-specific sanity filter for {label.lower()}.",
        )

    if _candidate_set_is_unresolved(fact_type, viable, support_counts, profile_by_path=profile_by_path):
        return _fallback_controlling_fact(
            fact_type,
            viable,
            profile_by_path=profile_by_path,
            why_it_controls=f"Multiple readable {label.lower()} candidates remain credible, but no single value clearly outranks the others.",
            controlling_document="Conflicting authoritative sources",
        )

    chosen = viable[0]
    return AcquisitionControllingFact(
        fact_type=fact_type,
        label=label,
        controlling_value=_format_fact_value(fact_type, chosen.value),
        controlling_document=_source_label(chosen.relative_path, chosen.page_number),
        why_it_controls=_why_fact_controls(fact_type, chosen, support_counts.get(chosen.normalized_value, 1), profile_by_path=profile_by_path),
        rejected_alternatives=_candidate_alt_labels([*viable, *rejected], chosen),
        citations=[_citation_from_candidate(chosen)],
    )


def _build_owner_controlling_fact(
    candidates: list[_FactCandidate],
    *,
    profile_by_path: dict[str, _DocumentProfile],
    deal_profile: _DealProfile,
) -> tuple[AcquisitionControllingFact, AcquisitionSanityCorrection | None]:
    fact = _build_standard_controlling_fact("owner_name", candidates, profile_by_path=profile_by_path, deal_profile=deal_profile)
    _, suspicious, _ = _review_fact_candidates("owner_name", candidates, profile_by_path=profile_by_path, deal_profile=deal_profile)
    if not suspicious or not _fact_has_reliable_value(fact):
        return fact, None

    prior = suspicious[0]
    correction = AcquisitionSanityCorrection(
        fact_type="owner_name",
        corrected_value=fact.controlling_value,
        prior_value=prior.value,
        why_prior_was_wrong=prior.quality_note or "The rejected text reads like a plan note or drawing label, not a vesting entity.",
        credible_interpretation=f"The more credible interpretation is {fact.controlling_value} because {fact.controlling_document} reads like title or vesting support rather than plan annotation.",
        citations=_dedupe_citations([*_candidate_citations([prior]), *fact.citations])[:3],
    )
    return fact, correction


def _build_zoning_controlling_fact(
    candidates: list[_FactCandidate],
    *,
    profile_by_path: dict[str, _DocumentProfile],
    deal_profile: _DealProfile,
) -> tuple[AcquisitionControllingFact, AcquisitionSanityCorrection | None]:
    viable, rejected, support_counts = _review_fact_candidates("zoning", candidates, profile_by_path=profile_by_path, deal_profile=deal_profile)
    real_zoning = [candidate for candidate in viable if candidate.subtype == "zoning"]
    land_use = [candidate for candidate in viable if candidate.subtype == "land_use"]
    noisy = rejected

    if real_zoning:
        if _candidate_set_is_unresolved("zoning", real_zoning, support_counts, profile_by_path=profile_by_path):
            return (
                _fallback_controlling_fact(
                    "zoning",
                    real_zoning,
                    profile_by_path=profile_by_path,
                    why_it_controls="Multiple zoning-style candidates passed validation, but the readable package does not establish one operative district cleanly enough to control.",
                    controlling_document="Conflicting authoritative sources",
                ),
                None,
            )
        chosen = real_zoning[0]
        controlling_value = chosen.value
        citations = [_citation_from_candidate(chosen)]
        if land_use:
            chosen_land_use = land_use[0]
            if chosen_land_use.normalized_value != chosen.normalized_value:
                controlling_value = f"Zoning {chosen.value}; land use {chosen_land_use.value}"
                citations.append(_citation_from_candidate(chosen_land_use))
        fact = AcquisitionControllingFact(
            fact_type="zoning",
            label=_FACT_LABELS["zoning"],
            controlling_value=controlling_value,
            controlling_document=_source_label(chosen.relative_path, chosen.page_number),
            why_it_controls=_why_fact_controls("zoning", chosen, support_counts.get(chosen.normalized_value, 1), profile_by_path=profile_by_path),
            rejected_alternatives=_candidate_alt_labels([*viable, *rejected], chosen),
            citations=_dedupe_citations(citations)[:3],
        )
        correction = None
        if land_use or noisy:
            prior = (land_use or noisy)[0]
            correction = AcquisitionSanityCorrection(
                fact_type="zoning",
                corrected_value=fact.controlling_value,
                prior_value=prior.value,
                why_prior_was_wrong=prior.quality_note or "The rejected label reads like land-use shorthand or OCR noise, not a real zoning district.",
                credible_interpretation=f"The more credible interpretation is {fact.controlling_value} because {fact.controlling_document} carries an actual zoning-style designation.",
                citations=_dedupe_citations([*_candidate_citations([prior]), *fact.citations])[:3],
            )
        return fact, correction

    if land_use:
        chosen = land_use[0]
        fact = AcquisitionControllingFact(
            fact_type="zoning",
            label=_FACT_LABELS["zoning"],
            controlling_value=f"Actual zoning not cleanly established; most credible land-use read is {chosen.value}",
            controlling_document=_source_label(chosen.relative_path, chosen.page_number),
            why_it_controls="The package yields a credible land-use designation, but not a clean zoning district label. Underwrite the land-use read and treat zoning as still needing confirmation.",
            rejected_alternatives=_candidate_alt_labels([*viable, *rejected], chosen),
            citations=[_citation_from_candidate(chosen)],
        )
        correction = AcquisitionSanityCorrection(
            fact_type="zoning",
            corrected_value=fact.controlling_value,
            prior_value=chosen.value,
            why_prior_was_wrong="The extracted label reads like a land-use designation, not an operative zoning district.",
            credible_interpretation=f"The more credible interpretation is to treat {chosen.value} as land use only and keep actual zoning unresolved until a zoning-style designation is confirmed.",
            citations=fact.citations[:3],
        )
        return fact, correction

    return (
        _fallback_controlling_fact(
            "zoning",
            rejected or candidates,
            profile_by_path=profile_by_path,
            why_it_controls="The package does not contain a zoning or land-use candidate that passes the sanity filter strongly enough to control underwriting.",
        ),
        None,
    )


def _build_entitlement_controlling_fact(
    *,
    documents: list[DocumentRecord],
    contradictions: list[ContradictionFinding],
    entitlement_status: str,
    profile_by_path: dict[str, _DocumentProfile],
) -> AcquisitionControllingFact:
    candidates = [document for document in documents if _document_is_entitlement_relevant(document)]
    chosen = sorted(candidates, key=lambda document: _entitlement_document_sort_key(document, profile_by_path))[0] if candidates else None
    controlling_document = _document_label(chosen) if chosen is not None else "No controlling source isolated"
    controlling_value = entitlement_status.strip() or "Entitlement status is not clearly established from the current readable package."

    if chosen is not None:
        lowered = chosen.normalized_text.lower()
        if any(term in lowered for term in ("rezoning required", "variance required", "not approved", "appeal")):
            controlling_value = "Discretionary entitlement still appears open; the current package does not show a fully approved executable entitlement path."
        elif any(term in lowered for term in ("tentative map", "planning commission", "approved", "resolution")) and any(
            term in lowered for term in ("conditions of approval", "prior to final map", "prior to grading permit", "condition of approval")
        ):
            controlling_value = "Approvals appear in place, but execution still runs through condition closeout before final map and permit release."
        elif any(term in lowered for term in ("approved", "resolution", "planning commission")):
            controlling_value = "Readable approval support shows an approved entitlement path, subject to normal implementation steps."

    rejected = [
        clip_text(finding.description, 140)
        for finding in contradictions
        if "Entitlement Status" in finding.related_categories
    ]
    citations = [_citation_for_entitlement_document(chosen)] if chosen is not None else []
    why_controls = (
        f"{controlling_document} controls because official approval and condition documents outrank downstream summaries or narrative references in the entitlement lane."
        if chosen is not None
        else "No official approval or condition document was isolated strongly enough to control this lane."
    )
    return AcquisitionControllingFact(
        fact_type="entitlement_status",
        label=_FACT_LABELS["entitlement_status"],
        controlling_value=controlling_value,
        controlling_document=controlling_document,
        why_it_controls=why_controls,
        rejected_alternatives=unique_preserve_order(rejected)[:4],
        citations=citations,
    )


def _reconcile_unit_count(
    *,
    lot_fact: AcquisitionControllingFact,
    unit_fact: AcquisitionControllingFact,
    unit_candidates: list[_FactCandidate],
    product: _ProductInference,
) -> tuple[AcquisitionControllingFact, AcquisitionSanityCorrection | None]:
    if not _fact_has_reliable_value(lot_fact):
        return unit_fact, None

    lot_count = _count_from_text(lot_fact.controlling_value)
    unit_count = _count_from_text(unit_fact.controlling_value)
    if not product.one_unit_per_lot or lot_count is None:
        return unit_fact, None

    competing_candidates = [candidate for candidate in unit_candidates if _count_from_text(candidate.value) not in {None, lot_count}]
    if unit_count == lot_count and not competing_candidates:
        return unit_fact, None

    corrected_fact = unit_fact
    if unit_count != lot_count:
        corrected_fact = AcquisitionControllingFact(
            fact_type="unit_count",
            label=_FACT_LABELS["unit_count"],
            controlling_value=f"{lot_count} units",
            controlling_document=lot_fact.controlling_document,
            why_it_controls=(
                f"{product.label.title()} usually carries one unit per lot, and the controlling lot program is {lot_count} lots. "
                f"The full-project yield should therefore reconcile to {lot_count} units unless a supporting document proves a different product mix."
            ),
            rejected_alternatives=unique_preserve_order([
                unit_fact.controlling_value,
                *unit_fact.rejected_alternatives,
            ])[:4],
            citations=lot_fact.citations[:3],
        )

    prior_value = unit_fact.controlling_value
    if competing_candidates:
        prior_value = _format_fact_value("unit_count", competing_candidates[0].value)
    correction = AcquisitionSanityCorrection(
        fact_type="unit_count",
        corrected_value=corrected_fact.controlling_value,
        prior_value=prior_value,
        why_prior_was_wrong=(
            f"The prior read conflicts with real-world {product.label} logic: on a one-unit-per-lot product, the full project unit count should reconcile to the controlling lot program, not a lower subplan, building count, or OCR fragment."
        ),
        credible_interpretation=(
            f"The more credible interpretation is {corrected_fact.controlling_value} because the controlling lot count is {lot_count} and the product reads as {product.label}."
        ),
        citations=_dedupe_citations([*corrected_fact.citations, *unit_fact.citations])[:3],
    )
    return corrected_fact, correction


def _infer_product_type(document_profiles: list[_DocumentProfile]) -> _ProductInference:
    scores: dict[str, int] = {}
    evidences: dict[str, list[str]] = {}
    for profile in document_profiles:
        path_text = profile.path_text
        text = profile.text
        for label, terms, one_unit_per_lot in _PRODUCT_HINTS:
            score = 0
            if any(term in path_text for term in terms):
                score += 2
            score += sum(text.count(term) for term in terms)
            if score <= 0:
                continue
            scores[label] = scores.get(label, 0) + score
            evidences.setdefault(label, []).append(Path(profile.relative_path).name)
    if not scores:
        return _ProductInference(
            label="for-sale horizontal product",
            one_unit_per_lot=True,
            basis="No product-specific term dominated the package, so the second pass is assuming a standard one-unit-per-lot horizontal product until the plan set says otherwise.",
        )
    chosen_label = sorted(scores, key=lambda item: (-scores[item], item))[0]
    one_unit_per_lot = next(flag for label, _, flag in _PRODUCT_HINTS if label == chosen_label)
    basis = f"Product-type terms were strongest for {chosen_label} in {', '.join(unique_preserve_order(evidences.get(chosen_label, []))[:3])}."
    return _ProductInference(label=chosen_label, one_unit_per_lot=one_unit_per_lot, basis=basis)


def _build_risk_items(
    issues: list[CanonicalIssue],
    *,
    lot_count: int | None,
    deal_profile: _DealProfile,
    profile_lookup: dict[str, list[_DocumentProfile]],
) -> list[AcquisitionRiskItem]:
    ranked_issues = sorted(
        issues,
        key=lambda issue: (
            0 if issue.acquisition_severity == "CRITICAL" else 1 if issue.acquisition_severity == "HIGH" else 2 if issue.acquisition_severity == "MODERATE" else 3,
            0 if issue.blocking_flag else 1,
            0 if issue.gating_item else 1,
            -issue.priority_score.total,
            issue.title.lower(),
        ),
    )
    items: list[AcquisitionRiskItem] = []
    for issue in ranked_issues:
        evidence_confidence = _issue_evidence_confidence(issue, profile_lookup)
        direct_blocker_evidence = _issue_has_direct_blocker_evidence(issue, deal_profile=deal_profile, profile_lookup=profile_lookup)
        stage_materiality = _issue_stage_materiality(issue, deal_profile=deal_profile, direct_blocker_evidence=direct_blocker_evidence)
        issue_class = _classify_issue_class(
            issue,
            deal_profile=deal_profile,
            evidence_confidence=evidence_confidence,
            direct_blocker_evidence=direct_blocker_evidence,
            stage_materiality=stage_materiality,
        )
        primary_lever = _primary_lever_for_issue(issue, deal_profile=deal_profile, direct_blocker_evidence=direct_blocker_evidence)
        scope_read = _scope_read_for_issue(issue, primary_lever=primary_lever, lot_count=lot_count)
        default_bucket = "Supporting Risks"
        items.append(
            AcquisitionRiskItem(
            bucket=default_bucket,
                issue_class=issue_class,
                title=issue.title,
                summary=tight_sentence(
                    deal_impact_mechanism_for_issue(issue)
                    or issue.practical_impact
                    or issue.likely_implication
                    or issue.why_it_matters
                    or issue.title,
                    220,
                ),
                impact=deal_impact_type_for_issue(issue),
                timing=issue.schedule_impact_classification or timing_exposure_band_for_issue(issue),
                curability=fixability_classification_for_issue(issue),
                issue_id=issue.issue_id,
                citations=issue.citations[:3],
                source_documents=issue.source_documents[:3],
                deal_shaping=issue_class in {"true blocker", "material but solvable execution risk", "pricing / basis watch item"},
                primary_lever=primary_lever,
                evidence_confidence=evidence_confidence,
                stage_materiality=stage_materiality,
                direct_blocker_evidence=direct_blocker_evidence,
                cost_impact=scope_read.cost_detail,
                land_value_impact=scope_read.land_value_detail,
                margin_impact=scope_read.margin_detail,
                irr_impact=scope_read.irr_detail,
                timing_impact=scope_read.timing_detail,
                price_response=_price_response_text(primary_lever=primary_lever, scope_read=scope_read),
                terms_response=_terms_response_text(issue, primary_lever=primary_lever, bucket=default_bucket, scope_read=scope_read),
                timing_response=_timing_response_text(issue, primary_lever=primary_lever, scope_read=scope_read),
                contingency_response=_contingency_response_text(issue, primary_lever=primary_lever, bucket=default_bucket),
            )
        )
    items.sort(key=lambda item: (_ISSUE_CLASS_ORDER.get(item.issue_class, 9), 0 if item.direct_blocker_evidence else 1, item.title.lower()))

    real_items = [item for item in items if item.issue_class in {"true blocker", "material but solvable execution risk", "pricing / basis watch item"}]
    primary_driver_id = real_items[0].issue_id if real_items else None
    secondary_driver_ids = {item.issue_id for item in real_items[1:1 + _SECONDARY_DRIVER_LIMIT]}

    for item in items:
        if item.issue_id == primary_driver_id:
            item.bucket = "Primary Deal Driver"
        elif item.issue_id in secondary_driver_ids:
            item.bucket = "Secondary Drivers"
        elif item.issue_class == "noise / ignore":
            item.bucket = "Noise"
        else:
            item.bucket = "Supporting Risks"
    items.sort(key=lambda item: (_BUCKET_ORDER.get(item.bucket, 9), _ISSUE_CLASS_ORDER.get(item.issue_class, 9), item.title.lower()))
    return items


def _primary_driver_id(ranked_issues: list[CanonicalIssue]) -> str | None:
    for issue in ranked_issues:
        if not _noise_issue(issue):
            return issue.issue_id
    return None


def _secondary_driver_ids(ranked_issues: list[CanonicalIssue], primary_driver_id: str | None) -> set[str]:
    selected: set[str] = set()
    for issue in ranked_issues:
        if issue.issue_id == primary_driver_id or _noise_issue(issue):
            continue
        if len(selected) >= _SECONDARY_DRIVER_LIMIT:
            break
        selected.add(issue.issue_id)
    return selected


def _risk_bucket_for_issue(issue: CanonicalIssue, primary_driver_id: str | None, secondary_driver_ids: set[str]) -> str:
    if issue.issue_id == primary_driver_id:
        return "Primary Deal Driver"
    if issue.issue_id in secondary_driver_ids:
        return "Secondary Drivers"
    if _noise_issue(issue):
        return "Noise"
    return "Supporting Risks"


def _noise_issue(issue: CanonicalIssue) -> bool:
    return (
        issue.front_end_flag == "routine item"
        and not issue.blocking_flag
        and issue.acquisition_severity == "LOW"
        and issue.priority_score.total < 35
    )


def _primary_lever_for_issue(issue: CanonicalIssue, *, deal_profile: _DealProfile, direct_blocker_evidence: bool) -> str:
    signal_text = _issue_signal_text(issue)
    if issue.decision_action == "treat as fatal":
        return "closeability"
    if issue.category in {"Title / Access Concerns", "Entitlement Status"} and direct_blocker_evidence:
        return "closeability"
    if issue.category in {"Fee / Exaction Burden", "Budget / Cost Reliability"}:
        return "price"
    if _MONEY_SIGNAL_RE.search(_issue_source_text(issue)) or any(
        term in signal_text
        for term in ("seller credit", "purchase price", "price adjustment", "basis", "cost stack", "fee", "fees", "bid", "proposal", "estimate")
    ):
        return "price"
    if issue.schedule_impact_classification != "non-blocking" or any(
        term in signal_text
        for term in ("delay", "backlog", "schedule", "timing", "permit", "final map", "grading", "vertical")
    ):
        return "timing"
    if issue.category in {"Title / Access Concerns", "Entitlement Status"} and deal_profile.stage in {"early land / pre-approval", "approved horizontal land"}:
        return "closeability"
    return "execution complexity"


def _scope_read_for_issue(issue: CanonicalIssue, *, primary_lever: str, lot_count: int | None) -> _ScopeRead:
    del lot_count
    signal_text = _issue_signal_text(issue)
    source_text = _issue_source_text(issue)
    scope_label = _scope_label_for_issue(signal_text)
    explicit_costs = tuple(unique_preserve_order(match.strip() for match in _MONEY_SIGNAL_RE.findall(source_text))[:2])
    explicit_timing = tuple(unique_preserve_order(match.strip() for match in _TIMING_SIGNAL_RE.findall(source_text))[:2])

    if explicit_costs:
        cost_status = "known"
        cost_detail = _status_line(
            "known",
            f"readable support cites {', '.join(explicit_costs)} tied to {scope_label or 'this issue'}.",
        )
    elif scope_label:
        cost_status = "estimable"
        cost_detail = _status_line(
            "estimable",
            f"the package identifies {scope_label}, but no current bid, fee backup, or seller-backed amount is attached.",
        )
    else:
        cost_status = "unknown"
        cost_detail = _status_line(
            "unknown",
            "the current readable package does not isolate a priced scope for this issue.",
        )

    if primary_lever == "price":
        if cost_status == "known":
            land_value_detail = _status_line("estimable", "land value should move with the cited cost once it is carried into basis.")
            margin_detail = _status_line("estimable", "margin moves directly with the cited scope, but no disciplined spread is supportable from the package alone.")
            irr_detail = _status_line("estimable", "IRR moves once the cited scope is carried through the current close date and business plan.")
        elif cost_status == "estimable":
            land_value_detail = _status_line("estimable", f"land value should move once {scope_label or 'the scope'} is refreshed with current pricing.")
            margin_detail = _status_line("estimable", "margin impact is real, but it should be sized only after the missing bid or fee support is loaded.")
            irr_detail = _status_line("unknown", "IRR should not be sized until the price-side scope is quantified and timed.")
        else:
            land_value_detail = _status_line("unknown", "land-basis impact cannot be sized from the current package.")
            margin_detail = _status_line("unknown", "price pressure is plausible, but no defensible amount is supported.")
            irr_detail = _status_line("unknown", "IRR impact is not supportable without a quantified price-side scope.")
    elif primary_lever == "timing":
        land_value_detail = _status_line("estimable", "land value changes only through carry if timing slips, but the duration is not defensible yet.")
        margin_detail = _status_line("estimable", "margin leakage comes through carry and overhead if the blocker slips, not through a fabricated cost range.")
        irr_detail = _status_line("estimable", "IRR is timing-sensitive here, but the package does not defend a specific duration yet.")
    elif primary_lever == "closeability":
        land_value_detail = _status_line("unknown", "value is binary until the closeability issue is cured or papered.")
        margin_detail = _status_line("unknown", "this is a closeability decision first, not a margin-tuning item.")
        irr_detail = _status_line("unknown", "IRR is not the right frame until the deal is actually closeable.")
    else:
        land_value_detail = _status_line("estimable", "value impact depends on how much of the execution scope converts into real field cost or redesign.")
        margin_detail = _status_line("estimable", "margin depends on whether the execution scope resolves through field cost, redesign, or coordination only.")
        irr_detail = _status_line("unknown", "IRR should not be sized until the execution scope is translated into actual cost or delay.")

    if explicit_timing:
        timing_status = "known"
        timing_detail = _status_line("known", f"readable support references {', '.join(explicit_timing)} of timing exposure.")
    elif primary_lever in {"timing", "closeability"} or issue.blocking_flag or issue.critical_path_flag:
        timing_status = "estimable"
        timing_detail = _status_line(
            "estimable",
            f"this is a blocker to {_close_milestone_for_issue(issue) or 'the next execution milestone'}, but the package does not support a defensible duration yet.",
        )
    else:
        timing_status = "unknown"
        timing_detail = _status_line("unknown", "no specific schedule duration is supported by the current package.")

    return _ScopeRead(
        scope_label=scope_label,
        cost_status=cost_status,
        cost_detail=cost_detail,
        land_value_detail=land_value_detail,
        margin_detail=margin_detail,
        irr_detail=irr_detail,
        timing_status=timing_status,
        timing_detail=timing_detail,
        explicit_costs=explicit_costs,
        explicit_timing=explicit_timing,
    )


def _status_line(status: str, detail: str) -> str:
    return f"{status.title()}: {detail}"


def _scope_label_for_issue(signal_text: str) -> str:
    for label, terms in _SCOPE_HINTS:
        if any(term in signal_text for term in terms):
            return label
    return ""


def _price_response_text(*, primary_lever: str, scope_read: _ScopeRead) -> str:
    if primary_lever != "price":
        return ""
    if scope_read.cost_status == "known":
        return f"Reset price or require seller credit against {scope_read.scope_label or 'the cited scope'}."
    if scope_read.cost_status == "estimable":
        return f"Keep price floating until {scope_read.scope_label or 'the scope'} is refreshed with current bids or fee support."
    return "Do not rely on a narrative reserve; quantify the missing scope before taking price credit."


def _terms_response_text(issue: CanonicalIssue, *, primary_lever: str, bucket: str, scope_read: _ScopeRead) -> str:
    del scope_read
    if primary_lever == "closeability":
        return "Make cure of this item a condition to close, with walk rights if the cure is not delivered."
    if primary_lever == "timing":
        return f"Use milestone-based closing or hard-money release tied to {_close_milestone_for_issue(issue) or 'the next execution milestone'}."
    if primary_lever == "price":
        return "Use seller credit, price reset, or a true-up mechanic rather than treating the issue as a soft reserve."
    if bucket != "Noise":
        return "Paper scope owner, reimbursement, and design responsibility explicitly so the issue does not drift post-close."
    return ""


def _timing_response_text(issue: CanonicalIssue, *, primary_lever: str, scope_read: _ScopeRead) -> str:
    milestone = _close_milestone_for_issue(issue) or "the next execution milestone"
    if primary_lever == "timing":
        if scope_read.timing_status == "known":
            return f"Carry the stated timing exposure to {milestone} in the business plan and outside dates."
        return f"Do not promise {milestone} timing until the blocker is converted from a stage gate into a cleared deliverable."
    if primary_lever == "closeability":
        return f"Do not schedule close ahead of the cure path for {milestone}."
    return ""


def _contingency_response_text(issue: CanonicalIssue, *, primary_lever: str, bucket: str) -> str:
    del issue
    if bucket == "Noise":
        return ""
    if primary_lever == "closeability":
        return "Keep the relevant closing contingency open until the cited cure is recorded, approved, or endorsed."
    if primary_lever == "timing":
        return "Keep the milestone contingency open until the blocker is removed from the stage path."
    if primary_lever == "price":
        return "Keep the cost or fee contingency open until the identified scope is backed by current third-party or agency support."
    return "Keep a scope-specific diligence contingency open until responsibility and execution path are documented."


def _close_milestone_for_issue(issue: CanonicalIssue) -> str | None:
    if issue.category in {"Title / Access Concerns", "Entitlement Status"}:
        return "close"
    if issue.category in {"Geotechnical Risks", "Flood / Drainage Issues", "Utilities / Infrastructure Issues", "Offsite Obligations"}:
        return "grading start"
    if issue.category in {"Fee / Exaction Burden", "Budget / Cost Reliability", "Schedule Risks"}:
        return "vertical start"
    return None


def _build_clean_gating_chain(
    issues: list[CanonicalIssue],
    risk_items: list[AcquisitionRiskItem],
) -> list[AcquisitionCriticalPathStep]:
    risk_by_id = {item.issue_id: item for item in risk_items}
    ranked = [
        issue
        for issue in issues
        if risk_by_id.get(issue.issue_id) is not None
        and risk_by_id[issue.issue_id].issue_class in {"true blocker", "material but solvable execution risk", "pricing / basis watch item"}
        and (
            risk_by_id[issue.issue_id].direct_blocker_evidence
            or issue.blocking_flag
            or issue.critical_path_flag
            or issue.schedule_impact_classification != "non-blocking"
        )
    ]
    ranked.sort(
        key=lambda issue: (
            _ISSUE_CLASS_ORDER.get(risk_by_id[issue.issue_id].issue_class, 9),
            0 if risk_by_id[issue.issue_id].direct_blocker_evidence else 1,
            0 if issue.critical_path_flag else 1,
            -issue.priority_score.total,
            issue.title.lower(),
        )
    )
    used_issue_ids: set[str] = set()
    steps: list[AcquisitionCriticalPathStep] = []
    for target, rule in _STAGE_RULES:
        stage_candidates = [
            issue
            for issue in ranked
            if issue.issue_id not in used_issue_ids and _stage_match_score(issue, rule, risk_by_id.get(issue.issue_id)) > 0
        ]
        for sequence, issue in enumerate(stage_candidates[:3], start=1):
            used_issue_ids.add(issue.issue_id)
            steps.append(
                AcquisitionCriticalPathStep(
                    target=target,
                    sequence=sequence,
                    blocker=issue.title,
                    why_it_blocks=tight_sentence(
                        issue.blocking_reason
                        or issue.critical_path_reason
                        or issue.likely_schedule_effect
                        or issue.practical_impact
                        or issue.likely_implication
                        or issue.why_it_matters,
                        220,
                    ),
                    issue_id=issue.issue_id,
                    citations=issue.citations[:3],
                    source_documents=issue.source_documents[:3],
                )
            )
    return steps


def _stage_match_score(issue: CanonicalIssue, rule: dict[str, object], risk_item: AcquisitionRiskItem | None) -> int:
    signal_text = _issue_signal_text(issue)
    categories = rule["categories"]
    schedule_classes = rule["schedule_classes"]
    terms = rule["terms"]
    score = 0
    if issue.category in categories:
        score += 2
    if issue.schedule_impact_classification in schedule_classes:
        score += 3
    if risk_item is not None and risk_item.direct_blocker_evidence:
        score += 4
    if issue.critical_path_flag:
        score += 3
    if any(term in signal_text for term in terms):
        score += 4
    return score


def _build_investment_decision(
    *,
    controlling_facts: list[AcquisitionControllingFact],
    sanity_corrections: list[AcquisitionSanityCorrection],
    risk_items: list[AcquisitionRiskItem],
    critical_path: list[AcquisitionCriticalPathStep],
    omission_assessments: list[OmissionAssessment],
    contradictions: list[ContradictionFinding],
    recommendation: RecommendationDecision,
    registry: CanonicalIssueRegistry,
    deal_profile: _DealProfile,
) -> AcquisitionDecision:
    del recommendation

    real_risks = [
        item
        for item in risk_items
        if item.issue_class in {"true blocker", "material but solvable execution risk", "pricing / basis watch item"}
    ]
    primary = real_risks[0] if real_risks else None
    secondary = real_risks[1:3]
    supporting = [item for item in risk_items if item.issue_class == "material but solvable execution risk"][2:]
    true_blockers = [item for item in risk_items if item.issue_class == "true blocker"]
    routine_items = [item for item in risk_items if item.issue_class == "routine confirmation item"]
    unsettled_facts = _unsettled_fact_lines(controlling_facts, deal_profile=deal_profile)
    material_unsettled_facts = [line for line, material in unsettled_facts if material]
    unsettled_fact_lines = [line for line, _ in unsettled_facts]
    material_missing = _material_missing_lines(
        omission_assessments,
        contradictions,
        controlling_facts,
        deal_profile=deal_profile,
    )
    mixed_evidence = (
        any(item.evidence_confidence == "low" for item in real_risks[:3])
        or any(term in (registry.package_quality or "").lower() for term in ("mixed", "weak", "thin", "incomplete"))
        or registry.confidence_in_initial_read == "low"
    )

    if true_blockers:
        posture = "Do Not Advance"
        rationale = tight_sentence(
            f"Direct evidence shows {true_blockers[0].title.lower()} can block execution for this {deal_profile.stage} deal. This is a real blocker, not routine closeout noise.",
            260,
        )
        risk_guardrail = "Risk elevation is supported by direct blocker evidence in a controlling source."
    elif real_risks or material_missing or material_unsettled_facts:
        posture = "Needs Targeted Confirmation"
        lead_item = (primary.title if primary is not None else material_missing[0] if material_missing else "the remaining material items").lower()
        if mixed_evidence:
            rationale = tight_sentence(
                f"Cannot conclude high-risk from provided documents. Needs targeted confirmation on {lead_item} before risk elevation.",
                260,
            )
        else:
            rationale = tight_sentence(
                f"The deal does not read as a proven blocker, but {lead_item} still needs targeted confirmation before the package is treated as clean.",
                260,
            )
        risk_guardrail = "Do not escalate beyond targeted confirmation unless a direct blocker is shown in a controlling document."
    else:
        posture = "Proceed With Routine Closeout"
        rationale = tight_sentence(
            f"The readable package supports a {deal_profile.stage} read, and the remaining items look like routine closeout rather than decision-changing risk.",
            260,
        )
        risk_guardrail = "Current open items do not justify a high-risk conclusion."

    biggest_unknown_text, biggest_unknown_citations = _biggest_unknown(omission_assessments, contradictions, sanity_corrections)
    primary_driver = f"{primary.title} ({primary.issue_class})" if primary is not None else "No direct blocker or material execution issue rises above routine closeout."
    secondary_drivers = [f"{item.title} ({item.issue_class})" for item in secondary]
    top_real_risks = [_risk_summary_line(item) for item in real_risks[:3]]
    price_or_structure_changes = [
        tight_sentence(f"{item.title}: {item.price_response or item.terms_response or item.timing_response or item.summary}", 220)
        for item in real_risks
        if item.issue_class == "pricing / basis watch item"
    ]

    what_has_to_be_true = []
    if true_blockers:
        what_has_to_be_true.extend(
            tight_sentence(f"{item.title} must be cured with direct closing, map, permit, or vertical-start support.", 200)
            for item in true_blockers[:2]
        )
    elif material_missing:
        what_has_to_be_true.extend(material_missing[:2])
    else:
        what_has_to_be_true.extend(
            tight_sentence(f"{fact.label} reads as {fact.controlling_value}.", 180)
            for fact in controlling_facts[:2]
            if _fact_has_reliable_value(fact)
        )

    close_requirements = _requirements_for_target(critical_path, "Final Map")
    grading_requirements = _requirements_for_target(critical_path, "Grading Permit")
    vertical_requirements = _requirements_for_target(critical_path, "Vertical Start")

    risks_underwritten = [
        tight_sentence(f"{item.title}: {item.summary}", 200)
        for item in supporting[:3]
    ] or ["No supporting risk currently rises above routine diligence friction."]
    corrected_fact_types = {correction.fact_type for correction in sanity_corrections}
    treated_as_solved = [
        tight_sentence(f"{fact.label}: {fact.controlling_value}.", 180)
        for fact in controlling_facts
        if _fact_has_reliable_value(fact) and fact.fact_type not in corrected_fact_types
    ][:3]
    if not treated_as_solved:
        treated_as_solved = ["No lane should be treated as fully solved beyond the current document-backed descriptors."]

    return AcquisitionDecision(
        posture=posture,
        rationale=rationale,
        deal_stage=deal_profile.stage,
        deal_stage_basis=deal_profile.basis,
        primary_driver=primary_driver,
        secondary_drivers=secondary_drivers,
        true_blockers=[_gating_line(item) for item in true_blockers[:3]],
        routine_items=[_routine_item_line(item, deal_profile=deal_profile) for item in routine_items[:3]],
        material_missing=material_missing,
        unsettled_facts=unsettled_fact_lines,
        material_unsettled_facts=material_unsettled_facts,
        risk_elevation_guardrail=risk_guardrail,
        top_real_risks=top_real_risks or ["No real risk currently rises above routine diligence noise in the reset ranking."],
        price_or_structure_changes=price_or_structure_changes or ["No specific price or structure change currently rises above routine contingency management."],
        biggest_unknown=biggest_unknown_text,
        what_has_to_be_true=what_has_to_be_true[:3],
        close_requirements=close_requirements,
        grading_requirements=grading_requirements,
        vertical_requirements=vertical_requirements,
        risks_underwritten=risks_underwritten[:3],
        treated_as_solved=treated_as_solved[:3],
        citations=_dedupe_citations(biggest_unknown_citations + [citation for item in ([primary] if primary is not None else []) + secondary[:2] for citation in item.citations])[:3],
    )


def _build_weak_acquisition_misses(
    *,
    sanity_corrections: list[AcquisitionSanityCorrection],
    risk_items: list[AcquisitionRiskItem],
    omission_assessments: list[OmissionAssessment],
    decision: AcquisitionDecision,
) -> list[AcquisitionInsight]:
    insights: list[AcquisitionInsight] = []

    for correction in sanity_corrections:
        insights.append(
            AcquisitionInsight(
                title=f"Do not let a bad extracted {correction.fact_type.replace('_', ' ')} drive underwriting",
                detail=clip_text(correction.credible_interpretation, 220),
                citations=correction.citations[:3],
            )
        )
        break

    primary = next((item for item in risk_items if item.bucket == "Primary Deal Driver"), None)
    if primary is not None:
        insights.append(
            AcquisitionInsight(
                title="The biggest issue should change paper, not just commentary",
                detail=clip_text(
                    f"{primary.title} is mainly a {primary.primary_lever} issue, so the recommendation should move that lever in paper rather than spreading the impact across everything.",
                    220,
                ),
                citations=primary.citations[:3],
                source_documents=primary.source_documents[:3],
            )
        )

    if decision.biggest_unknown:
        insights.append(
            AcquisitionInsight(
                title="The main blind spot belongs in the approval memo, not an appendix",
                detail=clip_text(decision.biggest_unknown, 220),
                citations=decision.citations[:3],
            )
        )

    if len(insights) < 3:
        for assessment in omission_assessments:
            if assessment.front_end_status not in {"missing and important", "conflicting across documents", "stale and potentially unreliable"}:
                continue
            insights.append(
                AcquisitionInsight(
                    title=f"{assessment.item} is an underwriting variable, not a housekeeping request",
                    detail=clip_text(assessment.front_end_reason or assessment.rationale, 220),
                    citations=assessment.citations[:3],
                    source_documents=assessment.source_documents[:3],
                )
            )
            if len(insights) >= 3:
                break

    unique: list[AcquisitionInsight] = []
    seen: set[str] = set()
    for insight in insights:
        key = insight.title.strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(insight)
        if len(unique) >= 3:
            break
    return unique


def _requirements_for_target(critical_path: list[AcquisitionCriticalPathStep], target: str) -> list[str]:
    requirements = [
        tight_sentence(f"{step.blocker}: {step.why_it_blocks}", 170)
        for step in critical_path
        if step.target == target
    ]
    return requirements[:3] or [f"No blocker is currently isolated on the path to {target.lower()}."]


def _count_candidate_confidence(excerpt: str, *, labeled_field: bool) -> str:
    lowered = excerpt.lower()
    if any(term in lowered for term in _COUNT_REJECT_CONTEXT_TERMS):
        return "low"
    if any(term in lowered for term in ("tentative map", "staff report", "approved", "project", "design review", "subdivide")):
        return "high"
    if any(term in lowered for term in _COUNT_SUBCOMPONENT_TERMS):
        return "low"
    return "medium" if labeled_field else "low"


def _classify_zoning_candidate(value: str, *, land_use_only: bool = False) -> tuple[str | None, str, str]:
    lowered = value.lower()
    if not lowered or any(term in lowered for term in _ZONING_REJECT_TERMS):
        return None, "low", "The rejected text reads like narrative or conditions language, not a zoning label."
    if land_use_only:
        return "land_use", "medium", "This reads like a land-use designation rather than a zoning district."
    if _REAL_ZONING_CODE_RE.fullmatch(value.strip()):
        return "zoning", "high", "This reads like a real zoning-style designation."
    if any(term in lowered for term in _LAND_USE_ONLY_TERMS):
        return "land_use", "low", "This reads like land-use terminology, not an operative zoning district."
    return "zoning", "low", "This does not clearly resemble a real zoning designation and should not control unless better support is absent."


def _classify_owner_candidate(value: str) -> tuple[str | None, str]:
    lowered = value.lower()
    if any(term in lowered for term in _OWNER_REJECT_TERMS):
        return "low", "The rejected text reads like a plan label or drawing note, not a vesting entity."
    if any(term in lowered for term in _LEGAL_PROSE_REJECT_TERMS):
        return "low", "The rejected text reads like legal prose rather than a vesting or seller name."
    if any(term in lowered for term in _OWNER_ENTITY_TERMS) or _looks_like_entity_name(value):
        return "high", "The chosen text includes an entity suffix and reads like a vesting party."
    return None, ""


def _material_unknowns(omission_assessments: list[OmissionAssessment]) -> list[OmissionAssessment]:
    return [
        assessment
        for assessment in omission_assessments
        if assessment.front_end_status in {"missing and important", "conflicting across documents", "stale and potentially unreliable"}
    ]


def _biggest_unknown(
    omission_assessments: list[OmissionAssessment],
    contradictions: list[ContradictionFinding],
    sanity_corrections: list[AcquisitionSanityCorrection],
) -> tuple[str, list[Citation]]:
    material_unknowns = _material_unknowns(omission_assessments)
    if material_unknowns:
        assessment = material_unknowns[0]
        return (
            clip_text(
                f"The biggest unknown is {assessment.item.lower()} because {assessment.front_end_reason or assessment.rationale}",
                220,
            ),
            assessment.citations[:3],
        )
    if contradictions:
        finding = contradictions[0]
        return (
            clip_text(
                f"The biggest unknown is the unresolved contradiction that {finding.description.lower()} {finding.why_it_matters}",
                220,
            ),
            finding.citations[:3],
        )
    if sanity_corrections:
        correction = sanity_corrections[0]
        return (
            clip_text(correction.credible_interpretation, 220),
            correction.citations[:3],
        )
    return ("No single unresolved unknown currently stands above the rest of the issue set.", [])


def _normalize_posture(raw_posture: str) -> str:
    lowered = (raw_posture or "").strip().lower()
    if lowered in {"do not advance", "do not proceed", "stop", "decline"}:
        return "Do Not Advance"
    if lowered in {"advance", "go"}:
        return "Advance"
    return "Advance Only If"


def _issue_profiles(issue: CanonicalIssue, profile_lookup: dict[str, list[_DocumentProfile]]) -> list[_DocumentProfile]:
    matches: list[_DocumentProfile] = []
    seen: set[str] = set()
    for alias in [*issue.source_documents, *(citation.document_name for citation in issue.citations)]:
        lowered = alias.lower().strip()
        for profile in profile_lookup.get(lowered, []):
            if profile.relative_path in seen:
                continue
            seen.add(profile.relative_path)
            matches.append(profile)
    return matches


def _issue_document_score(issue: CanonicalIssue, profile_lookup: dict[str, list[_DocumentProfile]]) -> float:
    profiles = _issue_profiles(issue, profile_lookup)
    if not profiles:
        return 0.0
    total = 0.0
    for profile in profiles:
        total += profile.reliability_score
        if issue.category == "Title / Access Concerns" and profile.role == "control_title":
            total += 2
        elif issue.category == "Entitlement Status" and profile.role in {"control_approval", "control_map"}:
            total += 2
        elif issue.category in {"Utilities / Infrastructure Issues", "Offsite Obligations", "Geotechnical Risks", "Flood / Drainage Issues"} and profile.role in {"control_map", "supporting_execution"}:
            total += 1
    return total / len(profiles)


def _issue_evidence_confidence(issue: CanonicalIssue, profile_lookup: dict[str, list[_DocumentProfile]]) -> str:
    score = 0.0
    score += _ISSUE_EVIDENCE_SCORES.get(issue.evidence_basis, 0)
    score += _ISSUE_STRENGTH_SCORES.get(issue.issue_strength, 0)
    score += _ISSUE_FALSE_POSITIVE_SCORES.get(issue.false_positive_risk, 0)
    score += {"high": 1, "medium": 0, "low": -1}.get(issue.confidence_level, 0)
    score += _issue_document_score(issue, profile_lookup)
    if score >= 4:
        return "high"
    if score >= 1:
        return "medium"
    return "low"


def _issue_has_direct_blocker_evidence(
    issue: CanonicalIssue,
    *,
    deal_profile: _DealProfile,
    profile_lookup: dict[str, list[_DocumentProfile]],
) -> bool:
    if issue.decision_action == "treat as fatal":
        return True
    if issue.false_positive_risk == "high" or _issue_evidence_confidence(issue, profile_lookup) == "low":
        return False
    if not (issue.blocking_flag or issue.gating_item or issue.critical_path_flag):
        return False

    signal_text = _issue_direct_evidence_text(issue)
    has_direct_term = any(term in signal_text for term in _DIRECT_BLOCKER_TERMS)
    has_blocker_schedule = issue.schedule_impact_classification in {"immediate blocker", "pre-close blocker", "pre-final-map blocker", "pre-vertical-start blocker"}
    has_hard_blocker_context = any(term in signal_text for term in ("appeal", "blocked", "cannot", "denied", "expired", "fatal", "no legal access", "not approved", "recordation"))
    if deal_profile.stage in {"finished lot / near-finished lot", "vertical / builder-ready"} and issue.category in {"Title / Access Concerns", "Entitlement Status"}:
        return has_direct_term or (has_blocker_schedule and has_hard_blocker_context)
    return has_direct_term or (has_blocker_schedule and has_hard_blocker_context)


def _issue_stage_materiality(
    issue: CanonicalIssue,
    *,
    deal_profile: _DealProfile,
    direct_blocker_evidence: bool,
) -> str:
    if direct_blocker_evidence:
        return "gating"
    if issue.category in {"Title / Access Concerns", "Entitlement Status"} and deal_profile.stage in {"finished lot / near-finished lot", "vertical / builder-ready"}:
        if issue.evidence_basis in {"omission_only", "routine_missing_support", "weak_inference"}:
            return "routine"
    score = _STAGE_CATEGORY_SCORES.get(deal_profile.stage, {}).get(issue.category, 1)
    if score >= 2 and issue.false_positive_risk != "high":
        return "material"
    if issue.false_positive_risk == "high" or issue.normal_friction_flag:
        return "immaterial"
    return "routine"


def _classify_issue_class(
    issue: CanonicalIssue,
    *,
    deal_profile: _DealProfile,
    evidence_confidence: str,
    direct_blocker_evidence: bool,
    stage_materiality: str,
) -> str:
    del deal_profile
    if direct_blocker_evidence:
        return "true blocker"
    if issue.category in {"Fee / Exaction Burden", "Budget / Cost Reliability"} and evidence_confidence != "low":
        return "pricing / basis watch item"
    if stage_materiality == "material" and evidence_confidence != "low":
        return "material but solvable execution risk"
    if stage_materiality == "routine":
        return "routine confirmation item"
    if issue.false_positive_risk == "high" or issue.evidence_basis in {"weak_inference", "routine_missing_support"}:
        return "noise / ignore"
    return "routine confirmation item"


def _risk_summary_line(item: AcquisitionRiskItem) -> str:
    return tight_sentence(f"{item.title} [{item.issue_class}]: {item.summary}", 220)


def _gating_line(item: AcquisitionRiskItem) -> str:
    return tight_sentence(f"{item.title}: direct evidence supports treating this as a real blocker, not routine closeout.", 220)


def _routine_item_line(item: AcquisitionRiskItem, *, deal_profile: _DealProfile) -> str:
    return tight_sentence(f"{item.title}: keep this as routine confirmation for a {deal_profile.stage} deal unless cleaner direct evidence changes the read.", 220)


def _category_material_to_stage(category: str, *, deal_profile: _DealProfile) -> bool:
    return _STAGE_CATEGORY_SCORES.get(deal_profile.stage, {}).get(category, 1) >= 2


def _fact_is_material_to_stage(
    fact: AcquisitionControllingFact,
    *,
    deal_profile: _DealProfile,
    controlling_facts: list[AcquisitionControllingFact],
) -> bool:
    if fact.fact_type in _STAGE_FACT_MATERIALITY.get(deal_profile.stage, set()):
        if fact.fact_type == "lot_count" and deal_profile.stage in {"finished lot / near-finished lot", "vertical / builder-ready"}:
            unit_fact = next((item for item in controlling_facts if item.fact_type == "unit_count"), None)
            return not _fact_has_reliable_value(unit_fact) if unit_fact is not None else False
        return True
    return False


def _unsettled_fact_lines(
    controlling_facts: list[AcquisitionControllingFact],
    *,
    deal_profile: _DealProfile,
) -> list[tuple[str, bool]]:
    lines: list[tuple[str, bool]] = []
    for fact in controlling_facts:
        if _fact_has_reliable_value(fact):
            continue
        material = _fact_is_material_to_stage(fact, deal_profile=deal_profile, controlling_facts=controlling_facts)
        qualifier = "material to this deal stage" if material else "not material to this deal stage"
        lines.append(
            (
                tight_sentence(f"{fact.label}: not reliably established from provided documents and {qualifier}.", 220),
                material,
            )
        )
    return lines


def _material_missing_lines(
    omission_assessments: list[OmissionAssessment],
    contradictions: list[ContradictionFinding],
    controlling_facts: list[AcquisitionControllingFact],
    *,
    deal_profile: _DealProfile,
) -> list[str]:
    lines: list[str] = []
    for assessment in _material_unknowns(omission_assessments):
        if not _category_material_to_stage(assessment.category, deal_profile=deal_profile):
            continue
        lines.append(tight_sentence(f"{assessment.item}: {assessment.front_end_reason or assessment.rationale}", 220))
    for finding in contradictions:
        if not any(_category_material_to_stage(category, deal_profile=deal_profile) for category in finding.related_categories):
            continue
        lines.append(tight_sentence(f"{finding.description}: {finding.why_it_matters}", 220))
    for fact in controlling_facts:
        if _fact_has_reliable_value(fact):
            continue
        if not _fact_is_material_to_stage(fact, deal_profile=deal_profile, controlling_facts=controlling_facts):
            continue
        lines.append(tight_sentence(f"{fact.label}: not reliably established from provided documents.", 180))
    return unique_preserve_order(lines)[:4]


def _candidate_alt_labels(candidates: list[_FactCandidate], chosen: _FactCandidate | None = None) -> list[str]:
    labels = []
    for candidate in candidates:
        if chosen is not None and candidate.normalized_value == chosen.normalized_value:
            continue
        labels.append(f"{_format_fact_value(candidate.fact_type, candidate.value)} ({_source_label(candidate.relative_path, candidate.page_number)})")
    return unique_preserve_order(labels)[:4]


def _candidate_citations(candidates: list[_FactCandidate]) -> list[Citation]:
    return _dedupe_citations([_citation_from_candidate(candidate) for candidate in candidates])[:3]


def _support_counts(candidates: list[_FactCandidate]) -> dict[str, int]:
    counts: dict[str, set[str]] = {}
    for candidate in candidates:
        counts.setdefault(candidate.normalized_value, set()).add(candidate.relative_path)
    return {key: len(paths) for key, paths in counts.items()}


def _fact_sort_key(
    fact_type: str,
    candidate: _FactCandidate,
    support_counts: dict[str, int],
    *,
    profile_by_path: dict[str, _DocumentProfile],
) -> tuple[int, int, int, int, int, str]:
    profile = profile_by_path.get(candidate.relative_path)
    reliability_score = profile.reliability_score if profile is not None else 0
    recency_score = profile.recency_score if profile is not None else 0
    role_score = _fact_role_score(fact_type, profile)
    return (
        -_candidate_total_score(fact_type, candidate, support_counts, profile_by_path=profile_by_path),
        -support_counts.get(candidate.normalized_value, 1),
        -reliability_score,
        -recency_score,
        -role_score,
        candidate.value.lower(),
    )


def _authority_score(fact_type: str, candidate: _FactCandidate) -> int:
    haystack = f"{Path(candidate.relative_path).name.lower()} {candidate.excerpt.lower()}"
    score = 0
    for term, weight in _DOC_AUTHORITY_TERMS.get(fact_type, ()): 
        if term in haystack:
            score += weight
    for term, weight in _DOC_NEGATIVE_TERMS:
        if term in haystack:
            score += weight
    return score


def _candidate_total_score(
    fact_type: str,
    candidate: _FactCandidate,
    support_counts: dict[str, int],
    *,
    profile_by_path: dict[str, _DocumentProfile],
) -> int:
    profile = profile_by_path.get(candidate.relative_path)
    score = _CONFIDENCE_RANK.get(candidate.confidence, 2) * 3
    score += _authority_score(fact_type, candidate)
    score += support_counts.get(candidate.normalized_value, 1) * 2
    score += 2 if candidate.labeled_field else 0
    if candidate.ocr_used:
        score -= 2
    if profile is not None:
        score += profile.reliability_score
        score += profile.recency_score
        score += _fact_role_score(fact_type, profile)
    return score


def _fact_role_score(fact_type: str, profile: _DocumentProfile | None) -> int:
    if profile is None:
        return 0
    if fact_type in {"owner_name", "apn"}:
        return {"control_title": 4, "control_agreement": 1, "secondary_narrative": -3}.get(profile.role, 0)
    if fact_type in {"gross_acreage", "net_acreage", "site_acreage", "lot_count", "unit_count"}:
        return {"control_map": 3, "control_approval": 2, "secondary_narrative": -3, "control_title": -1}.get(profile.role, 0)
    if fact_type in {"zoning", "jurisdiction", "entitlement_status"}:
        return {"control_approval": 3, "control_map": 1, "secondary_narrative": -2, "control_title": -2}.get(profile.role, 0)
    return 0


def _why_fact_controls(
    fact_type: str,
    candidate: _FactCandidate,
    support_count: int,
    *,
    profile_by_path: dict[str, _DocumentProfile],
) -> str:
    document_label = _source_label(candidate.relative_path, candidate.page_number)
    profile = profile_by_path.get(candidate.relative_path)
    reasons = [f"{document_label} is the strongest readable source in this lane"]
    if candidate.labeled_field:
        reasons.append("value comes from a labeled field or operative sentence")
    if support_count > 1:
        reasons.append(f"{support_count} readable documents repeat the same value")
    if profile is not None:
        reasons.append(f"document reliability reads {profile.reliability}")
        if profile.recency_year is not None:
            reasons.append(f"best reference year reads {profile.recency_year}")
    if candidate.quality_note:
        reasons.append(candidate.quality_note)
    return tight_sentence("; ".join(reasons), 220)


def _document_is_entitlement_relevant(document: DocumentRecord) -> bool:
    text = document.normalized_text.lower()
    path = document.relative_path.as_posix().lower()
    return any(term in text or term in path for term, _ in _DOC_AUTHORITY_TERMS["entitlement_status"])


def _entitlement_document_sort_key(
    document: DocumentRecord,
    profile_by_path: dict[str, _DocumentProfile],
) -> tuple[int, int, str]:
    text = f"{document.relative_path.as_posix().lower()} {document.normalized_text.lower()}"
    score = 0
    for term, weight in _DOC_AUTHORITY_TERMS["entitlement_status"]:
        if term in text:
            score -= weight
    profile = profile_by_path.get(document.relative_path.as_posix())
    reliability_score = -(profile.reliability_score if profile is not None else 0)
    return (score, reliability_score, document.relative_path.as_posix().lower())


def _iter_document_chunks(document: DocumentRecord) -> list[ExtractedChunk]:
    if document.chunks:
        return document.chunks
    text = document.normalized_text or document.raw_text
    if not text:
        return []
    return [
        ExtractedChunk(
            document_name=document.title,
            chunk_id=f"synthetic-{Path(document.relative_path).stem or 'chunk'}",
            text=text,
            page_number=None,
        )
    ]


def _append_candidate(
    items: list[_FactCandidate],
    seen: set[tuple[str, str, str, str, str | None]],
    candidate: _FactCandidate,
) -> None:
    dedupe_key = (
        candidate.fact_type,
        candidate.normalized_value,
        candidate.relative_path,
        candidate.chunk_id,
        str(candidate.page_number),
    )
    if dedupe_key in seen:
        return
    seen.add(dedupe_key)
    items.append(candidate)


def _source_label(relative_path: str, page_number: int | None) -> str:
    label = Path(relative_path).name
    if page_number is not None:
        label += f" p. {page_number}"
    return label


def _document_label(document: DocumentRecord | None) -> str:
    if document is None:
        return ""
    first_chunk = _iter_document_chunks(document)[0]
    return _source_label(document.relative_path.as_posix(), first_chunk.page_number)


def _citation_from_candidate(candidate: _FactCandidate) -> Citation:
    return Citation(
        document_name=Path(candidate.relative_path).name,
        chunk_id=candidate.chunk_id or f"fact-{candidate.fact_type}",
        page_number=candidate.page_number,
    )


def _citation_for_entitlement_document(document: DocumentRecord) -> Citation:
    first_chunk = _iter_document_chunks(document)[0]
    return Citation(
        document_name=Path(document.relative_path).name,
        chunk_id=first_chunk.chunk_id,
        page_number=first_chunk.page_number,
    )


def _format_fact_value(fact_type: str, value: str) -> str:
    if fact_type in {"gross_acreage", "net_acreage", "site_acreage"}:
        return f"{value} acres"
    if fact_type == "lot_count":
        return f"{value} lots"
    if fact_type == "unit_count":
        return f"{value} units"
    if fact_type == "apn":
        return value.upper()
    return value


def _fact_count_value(controlling_facts: list[AcquisitionControllingFact], fact_type: str) -> int | None:
    for fact in controlling_facts:
        if fact.fact_type == fact_type:
            return _count_from_text(fact.controlling_value)
    return None


def _count_from_text(text: str) -> int | None:
    match = re.search(r"\d+", text)
    return int(match.group(0)) if match else None


def _normalize_numeric(value: str) -> str:
    match = re.search(r"\d+(?:\.\d+)?", value)
    if match is None:
        return value.strip().lower()
    parsed = float(match.group(0))
    return str(int(parsed)) if parsed.is_integer() else f"{parsed:.2f}".rstrip("0").rstrip(".")


def _normalize_named_value(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip(" .;,:\"'")


def _normalize_apn_value(value: str) -> str:
    return re.sub(r"[^A-Z0-9-]", "", value.upper())


def _review_fact_candidates(
    fact_type: str,
    candidates: list[_FactCandidate],
    *,
    profile_by_path: dict[str, _DocumentProfile],
    deal_profile: _DealProfile,
) -> tuple[list[_FactCandidate], list[_FactCandidate], dict[str, int]]:
    support_counts = _support_counts(candidates)
    accepted: list[_FactCandidate] = []
    rejected: list[_FactCandidate] = []
    for candidate in candidates:
        rejection_note = _candidate_rejection_note(
            fact_type,
            candidate,
            support_counts,
            profile_by_path=profile_by_path,
            deal_profile=deal_profile,
        )
        reviewed = candidate
        if rejection_note:
            reviewed = replace(
                candidate,
                confidence="low",
                quality_note=_join_quality_notes(candidate.quality_note, rejection_note),
            )
        if reviewed.confidence == "low":
            rejected.append(reviewed)
        else:
            accepted.append(reviewed)

    accepted.sort(key=lambda item: _fact_sort_key(fact_type, item, support_counts, profile_by_path=profile_by_path))
    rejected.sort(key=lambda item: _fact_sort_key(fact_type, item, support_counts, profile_by_path=profile_by_path))
    return accepted, rejected, support_counts


def _candidate_rejection_note(
    fact_type: str,
    candidate: _FactCandidate,
    support_counts: dict[str, int],
    *,
    profile_by_path: dict[str, _DocumentProfile],
    deal_profile: _DealProfile,
) -> str | None:
    reasons: list[str] = []
    profile = profile_by_path.get(candidate.relative_path)
    if fact_type in {"jurisdiction", "zoning", "owner_name"}:
        reasons.extend(_generic_text_issues(candidate.value))
    elif fact_type in {"lot_count", "unit_count", "gross_acreage", "net_acreage", "site_acreage"}:
        if _contains_non_alphanumeric_noise(candidate.value):
            reasons.append("contains non-alphanumeric noise")

    if candidate.ocr_used and support_counts.get(candidate.normalized_value, 1) == 1 and _authority_score(fact_type, candidate) <= 0:
        reasons.append("OCR fragment is not corroborated by a preferred source")
    if profile is not None and profile.reliability == "low" and support_counts.get(candidate.normalized_value, 1) == 1:
        reasons.append("candidate only appears in a weakly extracted document")
    if profile is not None and profile.role == "secondary_narrative" and support_counts.get(candidate.normalized_value, 1) == 1:
        reasons.append("candidate comes from a secondary narrative source rather than a controlling document")
    if fact_type in {"lot_count", "unit_count", "zoning", "owner_name"} and not candidate.labeled_field:
        reasons.append(f"{_FACT_LABELS[fact_type].lower()} is not tied to a labeled field or operative sentence")

    field_specific = {
        "gross_acreage": _validate_acreage_candidate,
        "net_acreage": _validate_acreage_candidate,
        "site_acreage": _validate_acreage_candidate,
        "lot_count": _validate_count_candidate,
        "unit_count": _validate_count_candidate,
        "zoning": _validate_zoning_candidate,
        "jurisdiction": _validate_jurisdiction_candidate,
        "owner_name": _validate_owner_candidate,
        "apn": _validate_apn_candidate,
    }.get(fact_type)
    if field_specific is not None:
        note = field_specific(fact_type, candidate, deal_profile=deal_profile)
        if note:
            reasons.append(note)

    if not reasons:
        return None
    return "; ".join(dict.fromkeys(reasons))


def _validate_count_candidate(fact_type: str, candidate: _FactCandidate, *, deal_profile: _DealProfile) -> str | None:
    count = _coerce_int(candidate.normalized_value)
    if count is None:
        return f"{_FACT_LABELS[fact_type].lower()} is not numeric"
    if count < 1 or count > _COUNT_STAGE_LIMITS.get(deal_profile.stage, {}).get(fact_type, 2000):
        return f"{_FACT_LABELS[fact_type].lower()} falls outside a realistic project-scale range"
    if 1900 <= count <= 2100:
        return f"{_FACT_LABELS[fact_type].lower()} looks more like a year or sheet label than a project total"
    context = _candidate_context(candidate)
    if any(term in context for term in _COUNT_REJECT_CONTEXT_TERMS):
        return f"{_FACT_LABELS[fact_type].lower()} reads like table or closure-calculation noise, not a controlling project total"
    if any(term in context for term in _COUNT_SUBCOMPONENT_TERMS):
        return f"{_FACT_LABELS[fact_type].lower()} looks like a subplan or building count, not the controlling project total"
    if not any(term in context for term in _COUNT_CONTEXT_TERMS[fact_type]):
        return f"{_FACT_LABELS[fact_type].lower()} is not anchored to a staff report, map, plan, or approval context"
    return None


def _validate_acreage_candidate(fact_type: str, candidate: _FactCandidate, *, deal_profile: _DealProfile) -> str | None:
    del deal_profile
    acreage = _coerce_float(candidate.normalized_value)
    if acreage is None:
        return "acreage is not numeric"
    if acreage < 0.1 or acreage > 500:
        return "acreage falls outside a realistic site-scale range"
    context = _candidate_context(candidate)
    if any(term in context for term in _ACREAGE_FRAGMENT_TERMS):
        return "acreage reads like a phase, disturbed-area, or parcel-fragment measurement rather than the controlling site"
    if not any(term in context for term in _ACREAGE_CONTEXT_TERMS[fact_type]):
        return "acreage is not anchored to a survey, title, map, or site-area context"
    return None


def _validate_jurisdiction_candidate(_fact_type: str, candidate: _FactCandidate, *, deal_profile: _DealProfile) -> str | None:
    del deal_profile
    value = candidate.value
    context = _candidate_context(candidate)
    tokens = [token for token in re.split(r"[ .-]+", value) if token]
    if not tokens or len(tokens) > 4:
        return "jurisdiction does not resemble a city, county, or governing-agency name"
    if _contains_camelcase_artifact(value):
        return "jurisdiction includes concatenated OCR text"
    if any(any(character.isdigit() for character in token) for token in tokens):
        return "jurisdiction includes numeric noise"
    lowered_tokens = {token.lower() for token in tokens}
    if "and" in lowered_tokens or lowered_tokens & _UTILITY_PROVIDER_TERMS:
        return "jurisdiction reads like a utility/provider string rather than an official place name"
    if lowered_tokens & _LEGAL_PROSE_REJECT_TERMS:
        return "jurisdiction reads like legal prose rather than an official place name"
    if not any(term in context for term in _JURISDICTION_CONTEXT_TERMS):
        return "jurisdiction is not anchored to an official city, county, or governing-agency context"
    return None


def _validate_zoning_candidate(_fact_type: str, candidate: _FactCandidate, *, deal_profile: _DealProfile) -> str | None:
    del deal_profile
    value = candidate.value.strip()
    lowered = value.lower()
    context = _candidate_context(candidate)
    if _contains_camelcase_artifact(value):
        return "zoning value includes concatenated OCR text"
    if any(term in context for term in ("title report", "preliminary report", "exception")) and not any(term in context for term in _ZONING_CONTEXT_TERMS):
        return "zoning value comes from title or legal language, not a labeled zoning or land-use context"
    if any(term in lowered for term in _ZONING_REJECT_TERMS):
        return "zoning value reads like narrative or conditions language rather than a district label"
    if candidate.subtype == "land_use":
        if not any(term in lowered for term in _LAND_USE_ONLY_TERMS):
            return "land-use candidate does not resemble a recognized designation"
        if not any(term in context for term in _ZONING_CONTEXT_TERMS):
            return "land-use candidate is not anchored to a planning or entitlement context"
        return None
    if len(re.findall(r"[A-Za-z0-9]+", value)) > 4:
        return "zoning value is too long and reads like a sentence fragment"
    if not _REAL_ZONING_CODE_RE.fullmatch(value) and not _looks_like_zoning_phrase(value):
        return "zoning value does not resemble a real district designation"
    if not any(term in context for term in _ZONING_CONTEXT_TERMS):
        return "zoning value is not anchored to a zoning, land-use, or entitlement context"
    return None


def _validate_owner_candidate(_fact_type: str, candidate: _FactCandidate, *, deal_profile: _DealProfile) -> str | None:
    del deal_profile
    value = candidate.value
    lowered = value.lower()
    context = _candidate_context(candidate)
    if any(term in lowered for term in _OWNER_REJECT_TERMS):
        return "ownership candidate reads like a plan label or drawing note rather than a real entity"
    if any(term in lowered for term in _LEGAL_PROSE_REJECT_TERMS):
        return "ownership candidate reads like legal boilerplate rather than a real entity"
    if not _looks_like_entity_name(value):
        return "ownership candidate does not resemble a real person or entity name"
    if not any(term in context for term in _OWNER_SOURCE_TERMS):
        return "ownership candidate is not anchored to title, vesting, ESA ownership, or seller context"
    return None


def _validate_apn_candidate(_fact_type: str, candidate: _FactCandidate, *, deal_profile: _DealProfile) -> str | None:
    del deal_profile
    if not _APN_VALUE_RE.fullmatch(candidate.value):
        return "APN does not match a realistic parcel-number pattern"
    context = _candidate_context(candidate)
    if not any(term in context for term in ("apn", "assessor", "parcel number", "title", "legal description", "vesting")):
        return "APN is not anchored to parcel, title, or legal-description context"
    return None


def _candidate_context(candidate: _FactCandidate) -> str:
    return f"{candidate.excerpt.lower()} {candidate.relative_path.lower()}"


def _looks_like_zoning_phrase(value: str) -> bool:
    tokens = [token for token in re.split(r"[ /-]+", value.lower()) if token]
    allowed_words = {
        "agricultural",
        "agriculture",
        "commercial",
        "development",
        "industrial",
        "mixed",
        "planned",
        "residential",
        "specific",
        "use",
    }
    if not 1 <= len(tokens) <= 4:
        return False
    return all(token in allowed_words or bool(re.fullmatch(r"[a-z]{1,4}\d{0,2}[a-z]?", token)) for token in tokens)


def _candidate_set_is_unresolved(
    fact_type: str,
    candidates: list[_FactCandidate],
    support_counts: dict[str, int],
    *,
    profile_by_path: dict[str, _DocumentProfile],
) -> bool:
    unique_values = unique_preserve_order(candidate.normalized_value for candidate in candidates)
    if len(unique_values) < 2:
        return False

    top = candidates[0]
    runner_up = next((candidate for candidate in candidates if candidate.normalized_value != top.normalized_value), None)
    if runner_up is None:
        return False

    top_support = support_counts.get(top.normalized_value, 1)
    runner_support = support_counts.get(runner_up.normalized_value, 1)
    top_score = _candidate_total_score(fact_type, top, support_counts, profile_by_path=profile_by_path)
    runner_score = _candidate_total_score(fact_type, runner_up, support_counts, profile_by_path=profile_by_path)

    if top_support == runner_support and abs(top_score - runner_score) <= 2:
        return True
    if fact_type in {"gross_acreage", "net_acreage", "site_acreage", "lot_count", "unit_count", "apn"} and top_support == runner_support == 1 and abs(top_score - runner_score) <= 3:
        return True
    return False


def _fallback_controlling_fact(
    fact_type: str,
    candidates: list[_FactCandidate],
    *,
    profile_by_path: dict[str, _DocumentProfile],
    why_it_controls: str,
    controlling_document: str = "No controlling source isolated",
) -> AcquisitionControllingFact:
    support_counts = _support_counts(candidates)
    ordered = sorted(candidates, key=lambda item: _fact_sort_key(fact_type, item, support_counts, profile_by_path=profile_by_path))
    credible = ordered[:_MAX_CREDIBLE_CANDIDATES]
    return AcquisitionControllingFact(
        fact_type=fact_type,
        label=_FACT_LABELS[fact_type],
        controlling_value=_NO_RELIABLE_CONTROLLING_VALUE,
        controlling_document=controlling_document,
        why_it_controls=why_it_controls,
        rejected_alternatives=_candidate_alt_labels(credible),
        citations=_candidate_citations(credible),
    )


def _join_quality_notes(existing: str, new_note: str) -> str:
    if not existing:
        return new_note
    if not new_note:
        return existing
    return f"{existing} {new_note}"


def _fact_has_reliable_value(fact: AcquisitionControllingFact) -> bool:
    return fact.controlling_value != _NO_RELIABLE_CONTROLLING_VALUE


def _dedupe_citations(citations: list[Citation]) -> list[Citation]:
    deduped: list[Citation] = []
    seen: set[tuple[str, str, int | None]] = set()
    for citation in citations:
        key = (citation.document_name, citation.chunk_id, citation.page_number)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(citation)
    return deduped


def _format_money(value: int) -> str:
    return f"{value:,.0f}"


def _excerpt(text: str, start: int, end: int, *, max_chars: int = 180) -> str:
    left = max(0, start - 80)
    right = min(len(text), end + 80)
    snippet = re.sub(r"\s+", " ", text[left:right]).strip()
    return snippet if len(snippet) <= max_chars else snippet[: max_chars - 3].rstrip() + "..."


def _issue_signal_text(issue: CanonicalIssue) -> str:
    return _issue_source_text(issue).lower()


def _issue_direct_evidence_text(issue: CanonicalIssue) -> str:
    return " ".join(
        part
        for part in (
            issue.title,
            issue.category,
            " ".join(issue.best_evidence),
            " ".join(issue.core_facts),
            issue.site_specific_trigger,
        )
        if part
    ).lower()


def _issue_source_text(issue: CanonicalIssue) -> str:
    return " ".join(
        part
        for part in (
            issue.title,
            issue.category,
            " ".join(issue.best_evidence),
            " ".join(issue.core_facts),
            issue.blocking_reason,
            issue.critical_path_reason,
            issue.practical_impact,
            issue.likely_cost_effect,
            issue.likely_schedule_effect,
            issue.likely_closing_effect,
            issue.likely_structure_effect,
            issue.likely_underwriting_effect,
            issue.why_it_matters,
            issue.likely_implication,
            issue.what_would_resolve_it,
            " ".join(issue.open_questions),
            " ".join(issue.gating_flags),
        )
        if part
    )