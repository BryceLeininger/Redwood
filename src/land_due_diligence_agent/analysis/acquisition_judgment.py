"""Deterministic acquisition-grade sanity and economic reality pass."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re

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
from land_due_diligence_agent.utils.text import clip_text, unique_preserve_order

_FACT_LABELS = {
    "lot_count": "Lot Count",
    "unit_count": "Unit Count",
    "entitlement_status": "Entitlement Status",
    "zoning": "Zoning / Land Use",
    "jurisdiction": "Jurisdiction",
    "owner_name": "Ownership",
}
_CONFIDENCE_RANK = {"low": 1, "medium": 2, "high": 3}
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
_ZONING_REJECT_TERMS = {
    "approval",
    "condition",
    "conditions",
    "development standards",
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
_PRODUCT_HINTS = (
    ("single-family detached", ("single family detached", "single-family detached", "detached home", "detached homes"), True),
    ("single-family attached / townhome", ("townhome", "town home", "townhouse", "single-family attached"), True),
    ("multifamily", ("multifamily", "multi-family", "apartment", "apartments", "stacked flat"), False),
)
_COUNT_SUBCOMPONENT_TERMS = ("building", "phase", "product type", "plan type", "model", "stacked")
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
_DOC_AUTHORITY_TERMS = {
    "lot_count": (("tentative map", 4), ("staff report", 3), ("tract", 3), ("approval", 2), ("plan", 2)),
    "unit_count": (("tentative map", 4), ("staff report", 3), ("design review", 3), ("site plan", 2), ("approval", 2)),
    "zoning": (("resolution", 4), ("conditions", 4), ("staff report", 3), ("approval", 3), ("zoning", 3), ("general plan", 1)),
    "jurisdiction": (("city of", 4), ("county of", 3), ("staff report", 2), ("title", 1)),
    "owner_name": (("vested in", 5), ("title", 4), ("preliminary report", 4), ("commitment", 4), ("fee owner", 3), ("owner", 1)),
    "entitlement_status": (("resolution", 5), ("conditions", 5), ("planning commission", 4), ("city council", 4), ("tentative map", 4), ("approval", 3)),
}
_DOC_NEGATIVE_TERMS = (("summary", -2), ("overview", -2), ("matrix", -2), ("tracker", -1), ("draft", -1))


@dataclass(slots=True, frozen=True)
class _FactCandidate:
    fact_type: str
    value: str
    normalized_value: str
    relative_path: str
    excerpt: str
    page_number: int | None = None
    chunk_id: str = ""
    confidence: str = "medium"
    subtype: str = ""
    quality_note: str = ""


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

    fact_candidates = _extract_control_fact_candidates(documents)
    product = _infer_product_type(documents)
    controlling_facts, sanity_corrections = _build_controlling_facts(
        fact_candidates=fact_candidates,
        documents=documents,
        contradictions=contradictions,
        entitlement_status=entitlement_status,
        product=product,
    )
    lot_count = _fact_count_value(controlling_facts, "lot_count")
    risk_items = _build_risk_items(registry.issues, lot_count=lot_count)
    critical_path = _build_clean_gating_chain(registry.issues)
    decision = _build_investment_decision(
        controlling_facts=controlling_facts,
        sanity_corrections=sanity_corrections,
        risk_items=risk_items,
        critical_path=critical_path,
        omission_assessments=omission_assessments,
        contradictions=contradictions,
        recommendation=recommendation,
    )
    weak_misses = _build_weak_acquisition_misses(
        sanity_corrections=sanity_corrections,
        risk_items=risk_items,
        omission_assessments=omission_assessments,
        decision=decision,
    )
    return AcquisitionJudgment(
        sanity_corrections=sanity_corrections,
        controlling_facts=controlling_facts,
        risk_items=risk_items,
        critical_path=critical_path,
        investment_decision=decision,
        weak_acquisition_misses=weak_misses,
    )


def _extract_control_fact_candidates(documents: list[DocumentRecord]) -> dict[str, list[_FactCandidate]]:
    candidates: dict[str, list[_FactCandidate]] = {key: [] for key in _FACT_LABELS}
    seen: set[tuple[str, str, str, str, str | None]] = set()

    for document in documents:
        for chunk in _iter_document_chunks(document):
            text = chunk.text or ""

            for regex in (
                re.compile(r"\b(\d{1,4})\s+(?:single[- ]family\s+)?lots?\b", re.IGNORECASE),
                re.compile(r"\b(?:into|subdivide(?:d)?\s+into)\s+(\d{1,4})\s+(?:parcels?|lots?)\b", re.IGNORECASE),
            ):
                for match in regex.finditer(text):
                    _append_candidate(
                        candidates["lot_count"],
                        seen,
                        _FactCandidate(
                            fact_type="lot_count",
                            value=match.group(1),
                            normalized_value=_normalize_numeric(match.group(1)),
                            relative_path=document.relative_path.as_posix(),
                            excerpt=_excerpt(text, match.start(), match.end()),
                            page_number=chunk.page_number,
                            chunk_id=chunk.chunk_id,
                            confidence=_count_candidate_confidence(_excerpt(text, match.start(), match.end())),
                        ),
                    )

            for regex in (
                re.compile(r"\b(\d{1,5})\s+(?:dwelling\s+)?units?\b", re.IGNORECASE),
                re.compile(r"\b(\d{1,5})\s+(?:single[- ]family\s+)?homes?\b", re.IGNORECASE),
            ):
                for match in regex.finditer(text):
                    excerpt = _excerpt(text, match.start(), match.end())
                    if "du/ac" in excerpt.lower() or "per acre" in excerpt.lower():
                        continue
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
                            chunk_id=chunk.chunk_id,
                            confidence=_count_candidate_confidence(excerpt),
                        ),
                    )

            for regex in (
                re.compile(r"\b(?:current\s+)?zoning(?:\s+designation|\s+district)?\s*(?:is|as|=|:)?\s*([A-Za-z0-9\-/ ()]{2,50}?)(?=[.;,\n]|$)", re.IGNORECASE),
                re.compile(r"\b(?:zoned|zone(?:\s+district)?)\s*(?:is|as|=|:)?\s*([A-Za-z0-9\-/ ()]{2,50}?)(?=[.;,\n]|$)", re.IGNORECASE),
            ):
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
                            chunk_id=chunk.chunk_id,
                            confidence=confidence,
                            subtype=subtype,
                            quality_note=note,
                        ),
                    )
            for match in re.finditer(r"\b(?:general\s+plan\s+)?land use(?:\s+designation)?\s*(?:is|as|=|:)?\s*([A-Za-z0-9\-/ ()]{2,60}?)(?=[.;,\n]|$)", text, re.IGNORECASE):
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
                        chunk_id=chunk.chunk_id,
                        confidence=confidence,
                        subtype=subtype,
                        quality_note=note,
                    ),
                )

            for match in re.finditer(r"\bCity of\s+([A-Z][A-Za-z .-]{2,40})", text):
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
                        chunk_id=chunk.chunk_id,
                        confidence="high",
                        quality_note="City reference is typically the operative land-use jurisdiction.",
                    ),
                )
            for match in re.finditer(r"\bCounty of\s+([A-Z][A-Za-z .-]{2,40})", text):
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
                        chunk_id=chunk.chunk_id,
                        confidence="medium",
                        quality_note="County references can be geographic but not always the operative planning jurisdiction.",
                    ),
                )

            for regex in (
                re.compile(r"\bvested in\s*:?\s*([A-Z][A-Za-z0-9 ,.()&-]{3,100}?)(?=[.;\n]|$)"),
                re.compile(r"\b(?:fee owner|record owner|owner)\s*(?:is|:)?\s*([A-Z][A-Za-z0-9 ,.()&-]{3,100}?)(?=[.;\n]|$)", re.IGNORECASE),
            ):
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
                            chunk_id=chunk.chunk_id,
                            confidence=confidence,
                            quality_note=note,
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
) -> tuple[list[AcquisitionControllingFact], list[AcquisitionSanityCorrection]]:
    lot_fact = _build_standard_controlling_fact("lot_count", fact_candidates.get("lot_count", []))
    unit_fact = _build_standard_controlling_fact("unit_count", fact_candidates.get("unit_count", []))
    jurisdiction_fact = _build_standard_controlling_fact("jurisdiction", fact_candidates.get("jurisdiction", []))
    owner_fact, owner_correction = _build_owner_controlling_fact(fact_candidates.get("owner_name", []))
    zoning_fact, zoning_correction = _build_zoning_controlling_fact(fact_candidates.get("zoning", []))
    entitlement_fact = _build_entitlement_controlling_fact(
        documents=documents,
        contradictions=contradictions,
        entitlement_status=entitlement_status,
    )
    unit_fact, unit_correction = _reconcile_unit_count(
        lot_fact=lot_fact,
        unit_fact=unit_fact,
        unit_candidates=fact_candidates.get("unit_count", []),
        product=product,
    )

    controlling_facts = [
        lot_fact,
        unit_fact,
        entitlement_fact,
        zoning_fact,
        jurisdiction_fact,
        owner_fact,
    ]
    corrections = [
        correction
        for correction in (unit_correction, zoning_correction, owner_correction)
        if correction is not None
    ]
    return controlling_facts, corrections


def _build_standard_controlling_fact(fact_type: str, candidates: list[_FactCandidate]) -> AcquisitionControllingFact:
    label = _FACT_LABELS[fact_type]
    viable = [candidate for candidate in candidates if candidate.confidence != "low"]
    if not viable:
        return AcquisitionControllingFact(
            fact_type=fact_type,
            label=label,
            controlling_value="Not cleanly established from the current readable package.",
            controlling_document="No controlling source isolated",
            why_it_controls="No medium- or high-confidence candidate was extracted strongly enough to control this lane.",
            rejected_alternatives=_candidate_alt_labels(candidates),
            citations=_candidate_citations(candidates[:1]),
        )

    support_counts = _support_counts(candidates)
    chosen = sorted(viable, key=lambda item: _fact_sort_key(fact_type, item, support_counts))[0]
    return AcquisitionControllingFact(
        fact_type=fact_type,
        label=label,
        controlling_value=_format_fact_value(fact_type, chosen.value),
        controlling_document=_source_label(chosen.relative_path, chosen.page_number),
        why_it_controls=_why_fact_controls(fact_type, chosen, support_counts.get(chosen.normalized_value, 1)),
        rejected_alternatives=_candidate_alt_labels(candidates, chosen),
        citations=[_citation_from_candidate(chosen)],
    )


def _build_owner_controlling_fact(
    candidates: list[_FactCandidate],
) -> tuple[AcquisitionControllingFact, AcquisitionSanityCorrection | None]:
    fact = _build_standard_controlling_fact("owner_name", candidates)
    suspicious = [candidate for candidate in candidates if candidate.confidence == "low"]
    if not suspicious or fact.controlling_value.startswith("Not cleanly established"):
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
) -> tuple[AcquisitionControllingFact, AcquisitionSanityCorrection | None]:
    real_zoning = [candidate for candidate in candidates if candidate.subtype == "zoning" and candidate.confidence != "low"]
    land_use = [candidate for candidate in candidates if candidate.subtype == "land_use"]
    noisy = [candidate for candidate in candidates if candidate.confidence == "low" and candidate.subtype != "land_use"]

    if real_zoning:
        support_counts = _support_counts(candidates)
        chosen = sorted(real_zoning, key=lambda item: _fact_sort_key("zoning", item, support_counts))[0]
        controlling_value = chosen.value
        citations = [_citation_from_candidate(chosen)]
        if land_use:
            chosen_land_use = sorted(land_use, key=lambda item: _fact_sort_key("zoning", item, support_counts))[0]
            if chosen_land_use.normalized_value != chosen.normalized_value:
                controlling_value = f"Zoning {chosen.value}; land use {chosen_land_use.value}"
                citations.append(_citation_from_candidate(chosen_land_use))
        fact = AcquisitionControllingFact(
            fact_type="zoning",
            label=_FACT_LABELS["zoning"],
            controlling_value=controlling_value,
            controlling_document=_source_label(chosen.relative_path, chosen.page_number),
            why_it_controls=_why_fact_controls("zoning", chosen, support_counts.get(chosen.normalized_value, 1)),
            rejected_alternatives=_candidate_alt_labels(candidates, chosen),
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
            rejected_alternatives=_candidate_alt_labels(candidates, chosen),
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

    fact = AcquisitionControllingFact(
        fact_type="zoning",
        label=_FACT_LABELS["zoning"],
        controlling_value="Zoning / land use is not cleanly established from the current readable package.",
        controlling_document="No controlling source isolated",
        why_it_controls="The package does not contain a clean zoning or land-use reference strong enough to control underwriting.",
        rejected_alternatives=_candidate_alt_labels(candidates),
        citations=_candidate_citations(candidates[:1]),
    )
    return fact, None


def _build_entitlement_controlling_fact(
    *,
    documents: list[DocumentRecord],
    contradictions: list[ContradictionFinding],
    entitlement_status: str,
) -> AcquisitionControllingFact:
    candidates = [document for document in documents if _document_is_entitlement_relevant(document)]
    chosen = sorted(candidates, key=_entitlement_document_sort_key)[0] if candidates else None
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


def _infer_product_type(documents: list[DocumentRecord]) -> _ProductInference:
    scores: dict[str, int] = {}
    evidences: dict[str, list[str]] = {}
    for document in documents:
        path_text = document.relative_path.as_posix().lower()
        text = document.normalized_text.lower()
        for label, terms, one_unit_per_lot in _PRODUCT_HINTS:
            score = 0
            if any(term in path_text for term in terms):
                score += 2
            score += sum(text.count(term) for term in terms)
            if score <= 0:
                continue
            scores[label] = scores.get(label, 0) + score
            evidences.setdefault(label, []).append(Path(document.relative_path).name)
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


def _build_risk_items(issues: list[CanonicalIssue], *, lot_count: int | None) -> list[AcquisitionRiskItem]:
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
    primary_driver_id = _primary_driver_id(ranked_issues)
    secondary_driver_ids = _secondary_driver_ids(ranked_issues, primary_driver_id)

    items: list[AcquisitionRiskItem] = []
    for issue in ranked_issues:
        bucket = _risk_bucket_for_issue(issue, primary_driver_id, secondary_driver_ids)
        primary_lever = _primary_lever_for_issue(issue)
        scope_read = _scope_read_for_issue(issue, primary_lever=primary_lever, lot_count=lot_count)
        items.append(
            AcquisitionRiskItem(
                bucket=bucket,
                title=issue.title,
                summary=clip_text(
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
                deal_shaping=bucket in {"Primary Deal Driver", "Secondary Drivers"},
                primary_lever=primary_lever,
                cost_impact=scope_read.cost_detail,
                land_value_impact=scope_read.land_value_detail,
                margin_impact=scope_read.margin_detail,
                irr_impact=scope_read.irr_detail,
                timing_impact=scope_read.timing_detail,
                price_response=_price_response_text(primary_lever=primary_lever, scope_read=scope_read),
                terms_response=_terms_response_text(issue, primary_lever=primary_lever, bucket=bucket, scope_read=scope_read),
                timing_response=_timing_response_text(issue, primary_lever=primary_lever, scope_read=scope_read),
                contingency_response=_contingency_response_text(issue, primary_lever=primary_lever, bucket=bucket),
            )
        )
    items.sort(key=lambda item: (_BUCKET_ORDER.get(item.bucket, 9), 0 if item.deal_shaping else 1, item.title.lower()))
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


def _primary_lever_for_issue(issue: CanonicalIssue) -> str:
    signal_text = _issue_signal_text(issue)
    if issue.decision_action == "treat as fatal":
        return "closeability"
    if issue.category in {"Title / Access Concerns", "Entitlement Status"} and (issue.blocking_flag or issue.gating_item):
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
    if issue.category in {"Title / Access Concerns", "Entitlement Status"}:
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


def _build_clean_gating_chain(issues: list[CanonicalIssue]) -> list[AcquisitionCriticalPathStep]:
    ranked = [
        issue
        for issue in issues
        if not _noise_issue(issue)
        and (
            issue.blocking_flag
            or issue.critical_path_flag
            or issue.schedule_impact_classification != "non-blocking"
        )
    ]
    ranked.sort(
        key=lambda issue: (
            0 if issue.blocking_flag else 1,
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
            if issue.issue_id not in used_issue_ids and _stage_match_score(issue, rule) > 0
        ]
        for sequence, issue in enumerate(stage_candidates[:3], start=1):
            used_issue_ids.add(issue.issue_id)
            steps.append(
                AcquisitionCriticalPathStep(
                    target=target,
                    sequence=sequence,
                    blocker=issue.title,
                    why_it_blocks=clip_text(
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


def _stage_match_score(issue: CanonicalIssue, rule: dict[str, object]) -> int:
    signal_text = _issue_signal_text(issue)
    categories = rule["categories"]
    schedule_classes = rule["schedule_classes"]
    terms = rule["terms"]
    score = 0
    if issue.category in categories:
        score += 2
    if issue.schedule_impact_classification in schedule_classes:
        score += 3
    if issue.blocking_flag:
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
) -> AcquisitionDecision:
    primary = next((item for item in risk_items if item.bucket == "Primary Deal Driver"), None)
    secondary = [item for item in risk_items if item.bucket == "Secondary Drivers"]
    supporting = [item for item in risk_items if item.bucket == "Supporting Risks"]

    posture = _normalize_posture(recommendation.posture)
    if primary is not None and primary.primary_lever == "closeability" and (primary.curability == "low" or primary.timing == "immediate blocker"):
        posture = "Do Not Advance"
    elif primary is not None or secondary or _material_unknowns(omission_assessments) or contradictions:
        posture = "Advance Only If"
    else:
        posture = "Advance"

    biggest_unknown_text, biggest_unknown_citations = _biggest_unknown(omission_assessments, contradictions, sanity_corrections)
    primary_driver = f"{primary.title} ({primary.primary_lever})" if primary is not None else ""
    secondary_drivers = [f"{item.title} ({item.primary_lever})" for item in secondary[:2]]
    top_real_risks = []
    if primary is not None:
        top_real_risks.append(f"Primary driver - {primary.title} [{primary.primary_lever}]: {primary.cost_impact} {primary.timing_impact}")
    top_real_risks.extend(
        f"Secondary driver - {item.title} [{item.primary_lever}]: {item.cost_impact} {item.timing_impact}"
        for item in secondary[:2]
    )
    price_or_structure_changes = [
        f"{item.title}: Lever={item.primary_lever}. "
        + " ".join(
            part
            for part in (
                f"Price={item.price_response}" if item.price_response else "",
                f"Terms={item.terms_response}" if item.terms_response else "",
                f"Timing={item.timing_response}" if item.timing_response else "",
                f"Contingency={item.contingency_response}" if item.contingency_response else "",
            )
            if part
        )
        for item in ([primary] if primary is not None else []) + secondary[:2]
    ]
    rationale_parts = []
    if posture == "Do Not Advance" and primary is not None:
        rationale_parts.append(f"Do not advance until {primary.title.lower()} is cured or papered; it is a closeability issue, not routine execution noise.")
    elif primary is not None:
        rationale_parts.append(
            f"Advance only if {primary.title.lower()} is handled through its main lever ({primary.primary_lever}) and the secondary drivers are kept out of the blind side of the close."
        )
    else:
        rationale_parts.append("The current package resolves the core land descriptor lanes well enough that the remaining issues should be underwritten as normal execution risk.")

    what_has_to_be_true = []
    if primary is not None:
        what_has_to_be_true.append(
            f"Primary driver: {primary.title} must be handled through {primary.primary_lever} before the deal is treated as approved."
        )
    for item in secondary[:2]:
        what_has_to_be_true.append(
            f"Secondary driver: {item.title} should be carried through {item.primary_lever}, not treated as solved by narrative alone."
        )
    if not what_has_to_be_true:
        what_has_to_be_true.extend(
            f"{fact.label} stays as currently read: {fact.controlling_value}."
            for fact in controlling_facts[:2]
            if not fact.controlling_value.startswith("Not cleanly established")
        )

    close_requirements = _requirements_for_target(critical_path, "Final Map")
    grading_requirements = _requirements_for_target(critical_path, "Grading Permit")
    vertical_requirements = _requirements_for_target(critical_path, "Vertical Start")

    risks_underwritten = [
        f"{item.title}: lever={item.primary_lever}. {item.cost_impact} {item.timing_impact}"
        for item in supporting[:3]
    ] or ["No supporting risk currently rises above routine diligence friction."]
    corrected_fact_types = {correction.fact_type for correction in sanity_corrections}
    treated_as_solved = [
        f"{fact.label}: {fact.controlling_value}."
        for fact in controlling_facts
        if not fact.controlling_value.startswith("Not cleanly established") and fact.fact_type not in corrected_fact_types
    ][:3]
    if not treated_as_solved:
        treated_as_solved = ["No lane should be treated as fully solved beyond the current document-backed descriptors."]

    return AcquisitionDecision(
        posture=posture,
        rationale=clip_text(" ".join(rationale_parts), 260),
        primary_driver=primary_driver,
        secondary_drivers=secondary_drivers,
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
        f"{step.blocker}: {clip_text(step.why_it_blocks, 170)}"
        for step in critical_path
        if step.target == target
    ]
    return requirements[:3] or [f"No blocker is currently isolated on the path to {target.lower()}."]


def _count_candidate_confidence(excerpt: str) -> str:
    lowered = excerpt.lower()
    if any(term in lowered for term in ("tentative map", "staff report", "approved", "project", "design review", "subdivide")):
        return "high"
    if any(term in lowered for term in _COUNT_SUBCOMPONENT_TERMS):
        return "low"
    return "medium"


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
    tokens = [token for token in re.split(r"[ ,()&/-]+", value) if token]
    if len(tokens) < 2:
        return None, ""
    if any(term in lowered for term in _OWNER_REJECT_TERMS):
        return "low", "The rejected text reads like a plan label or drawing note, not a vesting entity."
    if any(term in lowered for term in _OWNER_ENTITY_TERMS):
        return "high", "The chosen text includes an entity suffix and reads like a vesting party."
    capitalized = sum(token[:1].isupper() for token in tokens if token[:1].isalpha())
    if capitalized >= max(2, len(tokens) - 1):
        return "medium", "The chosen text reads like an owner name even without an entity suffix."
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


def _candidate_alt_labels(candidates: list[_FactCandidate], chosen: _FactCandidate | None = None) -> list[str]:
    labels = []
    for candidate in candidates:
        if chosen is not None and candidate.normalized_value == chosen.normalized_value:
            continue
        labels.append(f"{candidate.value} ({_source_label(candidate.relative_path, candidate.page_number)})")
    return unique_preserve_order(labels)[:4]


def _candidate_citations(candidates: list[_FactCandidate]) -> list[Citation]:
    return _dedupe_citations([_citation_from_candidate(candidate) for candidate in candidates])[:3]


def _support_counts(candidates: list[_FactCandidate]) -> dict[str, int]:
    counts: dict[str, set[str]] = {}
    for candidate in candidates:
        counts.setdefault(candidate.normalized_value, set()).add(candidate.relative_path)
    return {key: len(paths) for key, paths in counts.items()}


def _fact_sort_key(fact_type: str, candidate: _FactCandidate, support_counts: dict[str, int]) -> tuple[int, int, int, str]:
    return (
        -_CONFIDENCE_RANK.get(candidate.confidence, 2),
        -_authority_score(fact_type, candidate),
        -support_counts.get(candidate.normalized_value, 1),
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


def _why_fact_controls(fact_type: str, candidate: _FactCandidate, support_count: int) -> str:
    document_label = _source_label(candidate.relative_path, candidate.page_number)
    reasons = [f"{document_label} is the highest-authority readable source in this lane"]
    if support_count > 1:
        reasons.append(f"{support_count} readable documents repeat the same value")
    if candidate.quality_note:
        reasons.append(candidate.quality_note)
    return clip_text("; ".join(reasons) + ".", 220)


def _document_is_entitlement_relevant(document: DocumentRecord) -> bool:
    text = document.normalized_text.lower()
    path = document.relative_path.as_posix().lower()
    return any(term in text or term in path for term, _ in _DOC_AUTHORITY_TERMS["entitlement_status"])


def _entitlement_document_sort_key(document: DocumentRecord) -> tuple[int, str]:
    text = f"{document.relative_path.as_posix().lower()} {document.normalized_text.lower()}"
    score = 0
    for term, weight in _DOC_AUTHORITY_TERMS["entitlement_status"]:
        if term in text:
            score -= weight
    return (score, document.relative_path.as_posix().lower())


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
    if fact_type == "lot_count":
        return f"{value} lots"
    if fact_type == "unit_count":
        return f"{value} units"
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