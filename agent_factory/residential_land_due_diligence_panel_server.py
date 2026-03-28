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
PANEL_API_VERSION = 1

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

        return {
            "agent": agent.metadata["blueprint"]["name"],
            "intake_text": intake_text,
            "result": result,
            "posture": prediction,
            "posture_label": details["label"],
            "tone": details["tone"],
            "summary": details["summary"],
            "next_step": details["next_step"],
            "confidence_pct": _prediction_confidence(result),
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