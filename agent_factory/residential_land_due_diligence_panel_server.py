"""Local web server for the Residential Land Due Diligence intake panel."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Optional

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .constants import METADATA_FILE
from .factory_agent import AgentFactory
from .specialist_agent import SpecialistAgent

PANEL_DIR = Path(__file__).resolve().parent / "residential_land_due_diligence_panel"
PANEL_API_VERSION = 2
NEGATION_MARKERS = ("no ", "not ", "without ", "free of ", "clear of ")

SAMPLE_QUESTION = "What should we verify first if title looks clean but sewer capacity and offsite obligations are still uncertain?"
SAMPLE_INTAKES: dict[str, dict[str, str]] = {
    "advance": {
        "opportunity_name": "Roseville North Lots",
        "market": "Roseville, CA",
        "transaction_stage": "PSA diligence",
        "opportunity_summary": "Approved detached lot opportunity adjacent to active builder phases with a near-term takedown path.",
        "entitlement_and_zoning": "By-right single-family zoning with vesting tentative map approved and conditions of approval already understood.",
        "utilities_and_agencies": "Sewer and water capacity confirmed, utilities at site, and fire flow comments appear routine.",
        "title_and_access": "Title review is clean so far, legal access is straightforward, and frontage dedication appears manageable.",
        "environmental_and_site": "No wetlands, floodplain, remediation, or unusual grading issues identified in the seller package.",
        "contract_and_seller_items": "Seller is delivering topo, Phase I, soils, and civil files with enough diligence time before deposits go hard.",
        "key_open_items": "Confirm final utility will-serve timing and update impact fee underwriting before final approval to proceed.",
    },
    "follow_up": {
        "opportunity_name": "Central Valley Edge Tract",
        "market": "Merced, CA",
        "transaction_stage": "Initial screen",
        "opportunity_summary": "Good detached housing location with builder demand, but a few material diligence items still need to clear.",
        "entitlement_and_zoning": "Residential path looks plausible, though entitlement timing and exact density assumptions still need agency confirmation.",
        "utilities_and_agencies": "Utilities are nearby, but sewer capacity and offsite improvement scope are not yet documented.",
        "title_and_access": "Access appears workable, though the team still needs a closer read on ALTA exceptions and easement language.",
        "environmental_and_site": "No obvious fatal flaw, but wetlands screening and final geotech assumptions still need validation.",
        "contract_and_seller_items": "Seller package is helpful, though the contract needs better extension rights before any hard money exposure.",
        "key_open_items": "Validate utility will-serve, wetlands, title exceptions, and final lot yield assumptions.",
    },
    "fatal": {
        "opportunity_name": "County Island Raw Land",
        "market": "Placer County, CA",
        "transaction_stage": "Early marketing",
        "opportunity_summary": "Large raw land parcel being pitched for residential use, but the execution path looks long-dated and risky.",
        "entitlement_and_zoning": "Outside city limits and likely requires annexation, rezone, and a politically uncertain processing path.",
        "utilities_and_agencies": "No sewer path is confirmed and utility delivery depends on future backbone improvements outside the site.",
        "title_and_access": "Access still depends on unresolved easement questions and seller has not delivered a clean title story.",
        "environmental_and_site": "Wetlands pockets, drainage burden, and grading issues could materially reduce lot yield and increase cost.",
        "contract_and_seller_items": "Seller wants hard money early despite major unknowns still unresolved.",
        "key_open_items": "Annexation, sewer, title, wetlands, and lot yield each remain major diligence concerns.",
    },
}

SECTION_CONFIGS: list[dict[str, Any]] = [
    {
        "key": "opportunity_summary",
        "label": "Opportunity summary",
        "healthy": [
            ("Near-term lot delivery", ("approved lot", "lot opportunity", "near-term", "near term", "finished lot")),
            ("Builder demand evidence", ("builder demand", "adjacent to active builder", "active builder phases", "speed to market")),
        ],
        "warning": [
            ("Long-dated land play", ("raw land", "long-dated", "speculative", "early marketing", "future play")),
            ("Unclear execution timing", ("uncertain timing", "execution path", "still being pitched")),
        ],
        "blocker": [("No defined residential path", ("no residential path", "unclear product strategy"))],
        "request_items": [
            "One-page deal brief with product, lot yield, basis, and schedule assumptions",
            "Clear statement of why this site fits the intended builder or buyer profile",
        ],
        "follow_up_prompt": "What deal facts still need to be proven before this opportunity should stay on the acquisition board?",
    },
    {
        "key": "entitlement_and_zoning",
        "label": "Entitlement and zoning",
        "healthy": [
            ("By-right zoning", ("by-right", "by right", "single-family zoning")),
            ("Map approvals already in hand", ("tentative map approved", "vesting tentative map", "final map", "entitled")),
        ],
        "warning": [
            ("Density still needs confirmation", ("density assumptions", "agency confirmation", "processing path")),
            ("Political or timing uncertainty", ("political support", "timing uncertainty", "approval timing")),
        ],
        "blocker": [
            ("Annexation risk", ("annexation", "annex")),
            ("Rezone or general plan risk", ("rezone", "general plan amendment", "gpa")),
            ("Moratorium or queue exposure", ("moratoria", "moratorium", "allocation queue")),
            ("Outside city processing risk", ("outside city limits", "county island")),
        ],
        "request_items": [
            "Zoning letter, entitlement schedule, and written agency feedback",
            "Map status, conditions of approval, and any political process notes",
        ],
        "follow_up_prompt": "What written agency evidence should we require before trusting the entitlement path and density assumptions on this site?",
    },
    {
        "key": "utilities_and_agencies",
        "label": "Utilities and agencies",
        "healthy": [
            ("Sewer capacity confirmed", ("sewer capacity confirmed", "sewer confirmed", "will-serve")),
            ("Water capacity confirmed", ("water capacity confirmed", "water service available", "utilities at site")),
        ],
        "warning": [
            ("Nearby-but-unproven utilities", ("utilities are nearby", "not yet documented", "agency comments remain verbal")),
            ("Offsite scope still unclear", ("offsite improvement scope", "offsite obligations", "impact fee underwriting")),
        ],
        "blocker": [
            ("No sewer path confirmed", ("no sewer path", "sewer is not confirmed", "sewer uncertain")),
            ("Backbone or regional dependency", ("future backbone", "future regional project", "backbone improvements")),
            ("Major lift station or booster exposure", ("lift station", "booster", "oversized backbone")),
            ("No capacity confirmation", ("no capacity", "capacity is not confirmed")),
        ],
        "request_items": [
            "Will-serve letters, utility studies, and written agency correspondence",
            "Offsite scope, reimbursement obligations, and timing assumptions in writing",
        ],
        "follow_up_prompt": "What utility evidence would actually prove sewer, water, drainage, and offsite timing instead of relying on seller language?",
    },
    {
        "key": "title_and_access",
        "label": "Title and access",
        "healthy": [
            ("Clean title posture", ("clean title", "title review is clean", "clean preliminary title")),
            ("Legal access appears straightforward", ("legal access", "straightforward access", "frontage")),
        ],
        "warning": [
            ("Easement review still open", ("easement language", "title exceptions", "alta exceptions")),
            ("Access still needs confirmation", ("access appears workable", "frontage dedication")),
        ],
        "blocker": [
            ("Unclear legal access", ("unclear legal access", "access still depends", "no legal access")),
            ("Title defect or lien exposure", ("title defect", "liens", "ownership issues")),
            ("Litigation or unresolved easement conflict", ("litigation", "unresolved easement", "boundary dispute")),
        ],
        "request_items": [
            "Preliminary title, ALTA or survey exhibits, and legal access backup",
            "Written cure path for title objections, easements, and frontage issues",
        ],
        "follow_up_prompt": "Which title or access issues would be a real stop sign here, and what cure evidence should we ask for immediately?",
    },
    {
        "key": "environmental_and_site",
        "label": "Environmental and site",
        "healthy": [
            ("No obvious environmental fatal flaw", ("no wetlands", "no floodplain", "no remediation")),
            ("Routine grading posture", ("routine grading", "no unusual grading")),
        ],
        "warning": [
            ("Screening still incomplete", ("wetlands screening", "geotech assumptions", "still need validation")),
            ("Civil cost or yield pressure", ("drainage burden", "grading issues", "lot yield assumptions")),
        ],
        "blocker": [
            ("Wetlands exposure", ("wetland", "wetlands pockets", "waters of the u.s")),
            ("Floodplain exposure", ("floodplain",)),
            ("Remediation or contamination risk", ("remediation", "brownfield", "contamination")),
            ("Species or habitat risk", ("endangered species", "protected habitat")),
            ("Material grading or retaining exposure", ("steep grading", "retaining wall", "major drainage")),
        ],
        "request_items": [
            "Phase I, wetlands or floodplain screens, and geotech or topo support",
            "Civil backup on grading, drainage, pad yield, and offsite scope",
        ],
        "follow_up_prompt": "What site or environmental issue is most likely to break lot yield, timing, or cost, and what third-party backup would settle it fastest?",
    },
    {
        "key": "contract_and_seller_items",
        "label": "Contract and seller items",
        "healthy": [
            ("Enough diligence time", ("enough diligence time", "diligence period", "extension rights")),
            ("Seller deliverables are identified", ("seller is delivering", "seller cooperation", "topo, phase i, soils")),
            ("Hard money held back", ("before deposits go hard", "hard money only after", "deposits go hard later")),
        ],
        "warning": [
            ("Contract structure still needs work", ("contract needs better extension rights", "seller package is helpful", "diligence time is tight")),
            ("Deliverables still incomplete", ("file completeness", "seller package", "deliver utility information")),
        ],
        "blocker": [
            ("Hard money too early", ("hard money early", "quick hard money", "deposits go hard early")),
            ("No extension or consultant protection", ("no extension rights", "limited access for consultants", "limited access for third-party consultants")),
            ("Heavy reliance on seller statements", ("verbal seller statements", "seller wants hard money early")),
        ],
        "request_items": [
            "PSA draft with deposit schedule, extension rights, and closing conditions tied to key risks",
            "Seller deliverables checklist covering title, studies, approvals, and utility backup",
        ],
        "follow_up_prompt": "How should the PSA protect the buyer if utility, title, or entitlement assumptions still fail during diligence?",
    },
    {
        "key": "key_open_items",
        "label": "Key open items",
        "healthy": [
            ("Mostly routine close-out items", ("confirm final utility will-serve", "update impact fee underwriting", "final approval to proceed")),
        ],
        "warning": [
            ("Material diligence still open", ("utility will-serve", "title exceptions", "geotech", "lot yield assumptions", "wetlands screening")),
        ],
        "blocker": [
            ("Stacked fatal-risk items still unresolved", ("annexation", "sewer", "title", "wetlands", "remediation", "floodplain")),
        ],
        "request_items": [
            "Open-item tracker with owner, deadline, and explicit kill criteria",
            "Prioritized diligence sequence showing which unresolved item gets answered first",
        ],
        "follow_up_prompt": "What is the highest-leverage open item to clear first if the team wants to decide quickly whether this site is still financeable?",
    },
]


class DiligenceIntakeRequest(BaseModel):
    agent_dir: str | None = None
    opportunity_name: str = "Unnamed opportunity"
    market: str = "Unknown market"
    transaction_stage: str = "Initial review"
    opportunity_summary: str = ""
    entitlement_and_zoning: str = ""
    utilities_and_agencies: str = ""
    title_and_access: str = ""
    environmental_and_site: str = ""
    contract_and_seller_items: str = ""
    key_open_items: str = ""


class AskQuestionRequest(BaseModel):
    agent_dir: str | None = None
    question: str
    top_k: int = 3


def _panel_cache_headers() -> dict[str, str]:
    return {
        "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
        "Pragma": "no-cache",
        "Expires": "0",
    }


def _panel_asset_version() -> str:
    asset_paths = [PANEL_DIR / "index.html", PANEL_DIR / "styles.css", PANEL_DIR / "app.js"]
    mtimes = [int(path.stat().st_mtime) for path in asset_paths if path.exists()]
    latest_mtime = max(mtimes, default=0)
    return f"{PANEL_API_VERSION}-{latest_mtime}"


def _render_panel_index() -> str:
    asset_version = _panel_asset_version()
    index_html = (PANEL_DIR / "index.html").read_text(encoding="utf-8")
    return (
        index_html.replace('href="/diligence/styles.css"', f'href="/diligence/styles.css?v={asset_version}"')
        .replace('src="/diligence/app.js"', f'src="/diligence/app.js?v={asset_version}"')
    )


def _dedupe_preserve_order(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        normalized = item.strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
    return result


def _list_due_diligence_agents(output_root: Path) -> list[dict[str, Any]]:
    factory = AgentFactory(output_root=output_root)
    registry_items = factory.list_registered_agents()

    agents = [
        item
        for item in registry_items
        if str(item.get("name", "")).strip().lower() == "residentiallandduediligenceadvisor"
    ]
    if agents:
        agents.sort(key=lambda item: str(item.get("created_at_utc", "")), reverse=True)
        return agents

    fallback: list[dict[str, Any]] = []
    for agent_dir in sorted(output_root.glob("residentiallandduediligenceadvisor_*"), reverse=True):
        metadata_path = agent_dir / METADATA_FILE
        if not metadata_path.exists():
            continue
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        fallback.append(
            {
                "name": metadata.get("blueprint", {}).get("name"),
                "topic": metadata.get("blueprint", {}).get("topic"),
                "task_type": metadata.get("blueprint", {}).get("task_type"),
                "agent_dir": str(agent_dir.resolve()),
                "created_at_utc": metadata.get("created_at_utc"),
                "metric_name": metadata.get("training", {}).get("metric_name"),
                "metric_value": metadata.get("training", {}).get("metric_value"),
            }
        )
    return fallback


def _default_agent_dir(output_root: Path, explicit_agent_dir: Optional[Path]) -> Path | None:
    if explicit_agent_dir is not None:
        return explicit_agent_dir.resolve()

    agents = _list_due_diligence_agents(output_root)
    if not agents:
        return None
    return Path(str(agents[0]["agent_dir"])).resolve()


def _load_agent(output_root: Path, explicit_agent_dir: Optional[Path], requested_agent_dir: str | None) -> SpecialistAgent:
    resolved_agent_dir = Path(requested_agent_dir).resolve() if requested_agent_dir else _default_agent_dir(
        output_root, explicit_agent_dir
    )
    if resolved_agent_dir is None:
        raise HTTPException(
            status_code=404,
            detail="No ResidentialLandDueDiligenceAdvisor agent was found. Create one first or pass --agent-dir.",
        )
    if not resolved_agent_dir.exists():
        raise HTTPException(status_code=404, detail=f"Agent directory was not found: {resolved_agent_dir}")
    return SpecialistAgent.load(resolved_agent_dir)


def _intake_has_content(payload: DiligenceIntakeRequest) -> bool:
    return any(
        value.strip()
        for value in (
            payload.opportunity_summary,
            payload.entitlement_and_zoning,
            payload.utilities_and_agencies,
            payload.title_and_access,
            payload.environmental_and_site,
            payload.contract_and_seller_items,
            payload.key_open_items,
        )
    )


def _compose_intake_text(payload: DiligenceIntakeRequest) -> str:
    sections = [
        ("Opportunity name", payload.opportunity_name),
        ("Market", payload.market),
        ("Transaction stage", payload.transaction_stage),
        ("Opportunity summary", payload.opportunity_summary),
        ("Entitlement and zoning", payload.entitlement_and_zoning),
        ("Utilities and agencies", payload.utilities_and_agencies),
        ("Title and access", payload.title_and_access),
        ("Environmental and site", payload.environmental_and_site),
        ("Contract and seller items", payload.contract_and_seller_items),
        ("Key open items", payload.key_open_items),
    ]
    return " | ".join(f"{label}: {value.strip()}" for label, value in sections if value.strip())


def _prediction_confidence(result: dict[str, Any]) -> float | None:
    top_classes = result.get("top_classes") or []
    if not top_classes:
        return None
    try:
        return round(float(top_classes[0].get("confidence", 0.0)) * 100.0, 1)
    except (TypeError, ValueError):
        return None


def _confidence_band(confidence_pct: float | None) -> str:
    if confidence_pct is None:
        return "Unscored"
    if confidence_pct >= 75.0:
        return "High conviction"
    if confidence_pct >= 55.0:
        return "Moderate conviction"
    return "Low conviction"


def _posture_details(prediction: str) -> dict[str, str]:
    mapping = {
        "advance": {
            "label": "Advance",
            "tone": "success",
            "summary": "The intake reads like a deal that can keep moving, assuming the remaining standard diligence items stay clean.",
            "next_step": "Push into detailed underwriting, confirm third-party reports, and keep contract timing aligned with the final open items.",
        },
        "targeted_follow_up": {
            "label": "Targeted Follow-Up",
            "tone": "warning",
            "summary": "The opportunity still looks alive, but one or more material diligence items need a focused second pass before advancing.",
            "next_step": "Keep the deal alive while resolving the highest-risk items first, especially utilities, title/access, entitlement timing, and offsite scope.",
        },
        "fatal_flaw_risk": {
            "label": "Fatal Flaw Risk",
            "tone": "danger",
            "summary": "The intake suggests stacked diligence issues that likely break timing, yield, cost, or certainty for a disciplined residential land buyer.",
            "next_step": "Pause the acquisition or materially reset basis and structure unless a specific fatal item is disproven quickly.",
        },
    }
    return mapping.get(
        prediction,
        {
            "label": prediction.replace("_", " ").title() or "Unknown",
            "tone": "idle",
            "summary": "The diligence posture is unclear from the current notes.",
            "next_step": "Add more concrete detail on entitlement, utilities, title, environmental, and contract issues.",
        },
    )


def _normalized_text(value: str) -> str:
    return " ".join(value.lower().split())


def _term_present(text: str, term: str) -> bool:
    start = text.find(term)
    while start != -1:
        prefix = text[max(0, start - 18):start]
        if not any(marker in prefix for marker in NEGATION_MARKERS):
            return True
        start = text.find(term, start + len(term))
    return False


def _find_hits(text: str, patterns: list[tuple[str, tuple[str, ...]]]) -> list[str]:
    normalized = _normalized_text(text)
    hits: list[str] = []
    for label, phrases in patterns:
        if any(_term_present(normalized, phrase) for phrase in phrases):
            hits.append(label)
    return hits


def _coverage_band(text: str) -> str:
    word_count = len(text.strip().split())
    if word_count == 0:
        return "Missing"
    if word_count < 10:
        return "Thin"
    if word_count < 22:
        return "Usable"
    return "Detailed"


def _status_label(status: str) -> str:
    return {
        "success": "De-risked",
        "warning": "Follow up",
        "danger": "Material risk",
        "missing": "Missing",
        "idle": "Thin signal",
    }.get(status, "Unknown")


def _analyze_section(config: dict[str, Any], text: str) -> dict[str, Any]:
    stripped = text.strip()
    positive_hits = _find_hits(stripped, config["healthy"])
    warning_hits = _find_hits(stripped, config["warning"])
    blocker_hits = _find_hits(stripped, config["blocker"])
    coverage = _coverage_band(stripped)

    if not stripped:
        status = "missing"
        headline = f"No {config['label'].lower()} notes captured yet."
        detail = "Confidence stays lower until someone records concrete facts, documents, or agency backup here."
    elif blocker_hits or (len(warning_hits) >= 2 and not positive_hits):
        status = "danger"
        focus_hits = blocker_hits or warning_hits
        headline = f"Material diligence risk is visible in {config['label'].lower()}."
        detail = f"Current notes point to {', '.join(focus_hits[:3])}. Request stronger backup before treating this section as financeable."
    elif warning_hits:
        status = "warning"
        headline = f"{config['label']} still needs targeted follow-up."
        detail = f"The notes reference {', '.join(warning_hits[:3])}. This looks workable only if the supporting evidence closes quickly."
    elif positive_hits:
        status = "success"
        headline = f"{config['label']} looks comparatively de-risked."
        detail = f"The notes reference {', '.join(positive_hits[:3])}, which usually supports a cleaner execution path."
    else:
        status = "idle"
        headline = f"{config['label']} has some notes, but they are not decision-grade yet."
        detail = "Add more specifics, dates, agency sources, and document references so the team can lean on this section."

    return {
        "key": config["key"],
        "label": config["label"],
        "status": status,
        "status_label": _status_label(status),
        "coverage_band": coverage,
        "headline": headline,
        "detail": detail,
        "positive_hits": positive_hits,
        "warning_hits": warning_hits,
        "blocker_hits": blocker_hits,
        "request_items": config["request_items"],
        "follow_up_prompt": config["follow_up_prompt"],
    }


def _coverage_summary(section_reviews: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(section_reviews)
    filled = sum(1 for review in section_reviews if review["status"] != "missing")
    detailed = sum(1 for review in section_reviews if review["coverage_band"] == "Detailed")
    missing_labels = [review["label"] for review in section_reviews if review["status"] == "missing"]
    return {
        "filled_sections": filled,
        "total_sections": total,
        "coverage_pct": round((filled / total) * 100.0, 1) if total else 0.0,
        "detailed_sections": detailed,
        "missing_sections": missing_labels,
    }


def _signal_summary(section_reviews: list[dict[str, Any]]) -> dict[str, Any]:
    strengths: list[str] = []
    watch_items: list[str] = []
    critical_risks: list[str] = []

    for review in section_reviews:
        strengths.extend(review["positive_hits"])
        if review["status"] == "warning":
            watch_items.extend(review["warning_hits"] or [review["label"]])
        if review["status"] == "danger":
            critical_risks.extend(review["blocker_hits"] or review["warning_hits"] or [review["label"]])

    for review in section_reviews:
        if review["status"] == "missing":
            watch_items.append(f"Missing notes for {review['label'].lower()}")

    return {
        "strengths": _dedupe_preserve_order(strengths)[:6],
        "watch_items": _dedupe_preserve_order(watch_items)[:6],
        "critical_risks": _dedupe_preserve_order(critical_risks)[:6],
    }


def _document_requests(section_reviews: list[dict[str, Any]]) -> list[str]:
    requested: list[str] = []
    for review in section_reviews:
        if review["status"] in {"missing", "warning", "danger", "idle"}:
            requested.extend(review["request_items"])
    return _dedupe_preserve_order(requested)[:8]


def _follow_up_prompts(section_reviews: list[dict[str, Any]], prediction: str) -> list[str]:
    prompts: list[str] = []
    for review in section_reviews:
        if review["status"] in {"danger", "warning", "missing"}:
            prompts.append(review["follow_up_prompt"])

    if prediction == "fatal_flaw_risk":
        prompts.append("Which issue would have to be disproven first before this site deserves more acquisition time?")
    elif prediction == "targeted_follow_up":
        prompts.append("What is the single highest-leverage diligence item to close before advancing the deal again?")
    else:
        prompts.append("What third-party reports or written agency backup should we confirm before releasing more deposits?")

    return _dedupe_preserve_order(prompts)[:5]


def _readiness_score(
    *,
    prediction: str,
    confidence_pct: float | None,
    coverage_pct: float,
    section_reviews: list[dict[str, Any]],
) -> dict[str, Any]:
    posture_base = {
        "advance": 48,
        "targeted_follow_up": 30,
        "fatal_flaw_risk": 8,
    }.get(prediction, 20)
    score = posture_base
    score += int(coverage_pct * 0.22)
    score += sum(6 for review in section_reviews if review["status"] == "success")
    score -= sum(5 for review in section_reviews if review["status"] == "warning")
    score -= sum(11 for review in section_reviews if review["status"] == "danger")
    score -= sum(4 for review in section_reviews if review["status"] == "missing")
    if confidence_pct is not None:
        score += int(confidence_pct / 14.0)
    score = max(0, min(100, score))

    if score >= 80:
        band = "Strong"
    elif score >= 60:
        band = "Workable"
    elif score >= 40:
        band = "Fragile"
    else:
        band = "Red flag"

    return {"score": score, "band": band}


def _build_diligence_brief(
    *,
    payload: DiligenceIntakeRequest,
    posture_label: str,
    confidence_pct: float | None,
    readiness: dict[str, Any],
    details: dict[str, str],
    coverage: dict[str, Any],
    signal_summary: dict[str, Any],
    document_requests: list[str],
) -> str:
    confidence_text = f"{confidence_pct:.1f}%" if confidence_pct is not None else "unscored"
    lines = [
        f"{payload.opportunity_name} | {payload.market} | {payload.transaction_stage}",
        f"Posture: {posture_label} | Model confidence: {confidence_text} | Readiness: {readiness['score']}/100 ({readiness['band']})",
        "",
        details["summary"],
        "",
        f"Coverage: {coverage['filled_sections']}/{coverage['total_sections']} sections filled ({coverage['coverage_pct']:.1f}%).",
    ]

    if signal_summary["critical_risks"]:
        lines.extend(["", "Critical risks:"])
        lines.extend(f"- {item}" for item in signal_summary["critical_risks"])

    if signal_summary["watch_items"]:
        lines.extend(["", "Targeted follow-up:"])
        lines.extend(f"- {item}" for item in signal_summary["watch_items"])

    if signal_summary["strengths"]:
        lines.extend(["", "De-risking signals:"])
        lines.extend(f"- {item}" for item in signal_summary["strengths"])

    lines.extend(["", "Immediate next step:", f"- {details['next_step']}"])

    if document_requests:
        lines.extend(["", "Documents or backup to request:"])
        lines.extend(f"- {item}" for item in document_requests[:6])

    return "\n".join(lines)


def _analyze_intake(payload: DiligenceIntakeRequest, prediction: str, confidence_pct: float | None) -> dict[str, Any]:
    section_reviews = [_analyze_section(config, getattr(payload, config["key"])) for config in SECTION_CONFIGS]
    coverage = _coverage_summary(section_reviews)
    signal_summary = _signal_summary(section_reviews)
    document_requests = _document_requests(section_reviews)
    follow_up_prompts = _follow_up_prompts(section_reviews, prediction)
    readiness = _readiness_score(
        prediction=prediction,
        confidence_pct=confidence_pct,
        coverage_pct=float(coverage["coverage_pct"]),
        section_reviews=section_reviews,
    )
    details = _posture_details(prediction)
    brief = _build_diligence_brief(
        payload=payload,
        posture_label=details["label"],
        confidence_pct=confidence_pct,
        readiness=readiness,
        details=details,
        coverage=coverage,
        signal_summary=signal_summary,
        document_requests=document_requests,
    )

    return {
        "coverage": coverage,
        "signal_summary": signal_summary,
        "section_reviews": section_reviews,
        "document_requests": document_requests,
        "follow_up_prompts": follow_up_prompts,
        "readiness": readiness,
        "brief": brief,
        "confidence_band": _confidence_band(confidence_pct),
    }


def create_app(*, output_root: Path, agent_dir: Optional[Path]) -> FastAPI:
    app = FastAPI(title="Residential Land Due Diligence Intake")

    @app.middleware("http")
    async def disable_cache_for_panel_assets(request: Request, call_next):
        response = await call_next(request)
        if request.url.path == "/" or request.url.path.startswith("/diligence/"):
            for key, value in _panel_cache_headers().items():
                response.headers[key] = value
        return response

    app.mount("/diligence", StaticFiles(directory=str(PANEL_DIR)), name="diligence")

    @app.get("/")
    def root() -> HTMLResponse:
        return HTMLResponse(content=_render_panel_index(), headers=_panel_cache_headers())

    @app.get("/api/start")
    def start() -> dict[str, Any]:
        agents = _list_due_diligence_agents(output_root)
        default_agent = _default_agent_dir(output_root, agent_dir)
        return {
            "reply": "Residential Land Due Diligence Intake ready.",
            "api_version": PANEL_API_VERSION,
            "default_agent_dir": str(default_agent) if default_agent else None,
            "agents": agents,
            "sample_intakes": SAMPLE_INTAKES,
            "sample_question": SAMPLE_QUESTION,
            "follow_up_starters": [config["follow_up_prompt"] for config in SECTION_CONFIGS[:4]],
        }

    @app.get("/api/agents")
    def agents() -> dict[str, Any]:
        return {"agents": _list_due_diligence_agents(output_root)}

    @app.post("/api/intake")
    def intake(payload: DiligenceIntakeRequest) -> dict[str, Any]:
        if not _intake_has_content(payload):
            raise HTTPException(status_code=400, detail="Provide diligence notes in at least one intake section.")

        agent = _load_agent(output_root, agent_dir, payload.agent_dir)
        intake_text = _compose_intake_text(payload)
        result = agent.predict(intake_text)
        prediction = str(result.get("prediction", "")).strip()
        details = _posture_details(prediction)
        confidence_pct = _prediction_confidence(result)
        analysis = _analyze_intake(payload, prediction, confidence_pct)

        return {
            "agent": agent.metadata["blueprint"]["name"],
            "intake_text": intake_text,
            "result": result,
            "posture": prediction,
            "posture_label": details["label"],
            "tone": details["tone"],
            "summary": details["summary"],
            "next_step": details["next_step"],
            "confidence_pct": confidence_pct,
            **analysis,
        }

    @app.post("/api/ask")
    def ask_question(payload: AskQuestionRequest) -> dict[str, Any]:
        if not payload.question.strip():
            raise HTTPException(status_code=400, detail="Question cannot be empty.")

        agent = _load_agent(output_root, agent_dir, payload.agent_dir)
        result = agent.ask_topic_question(payload.question, top_k=max(1, payload.top_k))
        return result

    return app


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Residential Land Due Diligence intake panel.")
    parser.add_argument("--host", default="127.0.0.1", help="Bind host.")
    parser.add_argument("--port", type=int, default=8786, help="Bind port.")
    parser.add_argument("--output-root", default="generated_agents", help="Generated agents folder path.")
    parser.add_argument("--agent-dir", help="Optional explicit ResidentialLandDueDiligenceAdvisor directory path.")
    args = parser.parse_args()

    app = create_app(
        output_root=Path(args.output_root),
        agent_dir=Path(args.agent_dir) if args.agent_dir else None,
    )

    uvicorn.run(
        app,
        host=args.host,
        port=args.port,
        log_level="info",
    )


if __name__ == "__main__":
    main()