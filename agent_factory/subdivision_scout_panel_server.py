"""Local web server for the Residential Subdivision Scout dashboard."""
from __future__ import annotations

import argparse
import csv
import json
from io import StringIO
from pathlib import Path
from typing import Any, Optional

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .constants import METADATA_FILE
from .factory_agent import AgentFactory
from .specialist_agent import SpecialistAgent
from .subdivision_scout import SubdivisionScout, load_watch_targets_from_text

PANEL_DIR = Path(__file__).resolve().parent / "subdivision_scout_panel"
EXAMPLE_DIR = Path(__file__).resolve().parent / "examples" / "subdivision_opportunity_scout"
SAMPLE_PARCELS_PATH = EXAMPLE_DIR / "sample_parcels.csv"
SAMPLE_WATCHLIST_PATH = EXAMPLE_DIR / "sample_watchlist.json"
SAMPLE_SINGLE_PARCEL_TEXT = (
    "12 acres adjacent to an existing subdivision with by-right single-family zoning, "
    "utilities stubbed to site, arterial frontage, and completed traffic study."
)


class ScreenTextRequest(BaseModel):
    agent_dir: str | None = None
    text: str
    market: str = "unknown"
    parcel_id: str = "parcel-1"


class ScreenCsvRequest(BaseModel):
    agent_dir: str | None = None
    csv_text: str
    top: int = 12
    min_score: float = 0.0


class WatchRequest(BaseModel):
    agent_dir: str | None = None
    watchlist_text: str
    lookback_days: int = 120
    max_results_per_query: int = 5


class FullSweepRequest(BaseModel):
    agent_dir: str | None = None
    csv_text: str | None = None
    single_parcel_text: str | None = None
    market: str = "unknown"
    parcel_id: str = "parcel-1"
    watchlist_text: str | None = None
    top: int = 12
    min_score: float = 0.0
    lookback_days: int = 120
    max_results_per_query: int = 5


def _list_scout_agents(output_root: Path) -> list[dict[str, Any]]:
    factory = AgentFactory(output_root=output_root)
    registry_items = factory.list_registered_agents()

    scouts = [
        item
        for item in registry_items
        if str(item.get("name", "")).strip().lower() == "residentialsubdivisionscout"
    ]

    if scouts:
        scouts.sort(key=lambda item: str(item.get("created_at_utc", "")), reverse=True)
        return scouts

    fallback: list[dict[str, Any]] = []
    for agent_dir in sorted(output_root.glob("residentialsubdivisionscout_*"), reverse=True):
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

    agents = _list_scout_agents(output_root)
    if not agents:
        return None
    return Path(str(agents[0]["agent_dir"])).resolve()


def _load_scout(output_root: Path, explicit_agent_dir: Optional[Path], requested_agent_dir: str | None) -> SubdivisionScout:
    resolved_agent_dir = Path(requested_agent_dir).resolve() if requested_agent_dir else _default_agent_dir(
        output_root, explicit_agent_dir
    )
    if resolved_agent_dir is None:
        raise HTTPException(
            status_code=404,
            detail="No ResidentialSubdivisionScout agent was found. Create one first or pass --agent-dir.",
        )
    if not resolved_agent_dir.exists():
        raise HTTPException(status_code=404, detail=f"Agent directory was not found: {resolved_agent_dir}")
    return SubdivisionScout(SpecialistAgent.load(resolved_agent_dir))


def _rows_from_csv_text(csv_text: str) -> list[dict[str, str]]:
    csv_text = csv_text.strip()
    if not csv_text:
        raise HTTPException(status_code=400, detail="Parcel CSV text cannot be empty.")
    reader = csv.DictReader(StringIO(csv_text))
    if not reader.fieldnames:
        raise HTTPException(status_code=400, detail="Parcel CSV must include a header row.")
    return [{key.strip(): (value or "").strip() for key, value in row.items()} for row in reader]


def _trim_ranked(results: list[dict[str, Any]], top: int, min_score: float) -> list[dict[str, Any]]:
    filtered = [item for item in results if float(item.get("priority_score", 0.0)) >= min_score]
    return filtered[: max(1, top)]


def _parse_watch_targets(raw_text: str) -> list[Any]:
    try:
        return load_watch_targets_from_text(raw_text)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail=f"Watchlist JSON is invalid: {exc.msg}") from exc


def create_app(
    *,
    output_root: Path,
    subdivision_agent_dir: Optional[Path],
) -> FastAPI:
    app = FastAPI(title="Residential Subdivision Scout")
    app.mount("/scout", StaticFiles(directory=str(PANEL_DIR)), name="scout")

    @app.get("/")
    def root() -> FileResponse:
        return FileResponse(PANEL_DIR / "index.html")

    @app.get("/api/start")
    def start() -> dict[str, Any]:
        agents = _list_scout_agents(output_root)
        default_agent = _default_agent_dir(output_root, subdivision_agent_dir)
        return {
            "reply": "Residential Subdivision Scout ready.",
            "default_agent_dir": str(default_agent) if default_agent else None,
            "agents": agents,
            "sample_single_parcel_text": SAMPLE_SINGLE_PARCEL_TEXT,
            "sample_parcel_csv": SAMPLE_PARCELS_PATH.read_text(encoding="utf-8") if SAMPLE_PARCELS_PATH.exists() else "",
            "sample_watchlist": SAMPLE_WATCHLIST_PATH.read_text(encoding="utf-8") if SAMPLE_WATCHLIST_PATH.exists() else "",
        }

    @app.get("/api/agents")
    def agents() -> dict[str, Any]:
        return {"agents": _list_scout_agents(output_root)}

    @app.post("/api/screen-text")
    def screen_text(payload: ScreenTextRequest) -> dict[str, Any]:
        if not payload.text.strip():
            raise HTTPException(status_code=400, detail="Parcel notes cannot be empty.")
        scout = _load_scout(output_root, subdivision_agent_dir, payload.agent_dir)
        result = scout.screen_parcel_text(
            text=payload.text,
            parcel_id=payload.parcel_id,
            market=payload.market,
        )
        return {"agent": scout.specialist.metadata["blueprint"]["name"], "result": result}

    @app.post("/api/screen-csv")
    def screen_csv(payload: ScreenCsvRequest) -> dict[str, Any]:
        scout = _load_scout(output_root, subdivision_agent_dir, payload.agent_dir)
        rows = _rows_from_csv_text(payload.csv_text)
        ranked = scout.screen_parcel_rows(rows)
        return {
            "agent": scout.specialist.metadata["blueprint"]["name"],
            "results": _trim_ranked(ranked, top=payload.top, min_score=payload.min_score),
        }

    @app.post("/api/watch")
    def watch(payload: WatchRequest) -> dict[str, Any]:
        scout = _load_scout(output_root, subdivision_agent_dir, payload.agent_dir)
        targets = _parse_watch_targets(payload.watchlist_text)
        if not targets:
            raise HTTPException(status_code=400, detail="Provide at least one jurisdiction or watch target.")
        return scout.watch_planning_activity(
            targets=targets,
            lookback_days=payload.lookback_days,
            max_results_per_query=payload.max_results_per_query,
        )

    @app.post("/api/full-sweep")
    def full_sweep(payload: FullSweepRequest) -> dict[str, Any]:
        scout = _load_scout(output_root, subdivision_agent_dir, payload.agent_dir)

        screened: list[dict[str, Any]] = []
        if payload.csv_text and payload.csv_text.strip():
            screened = _trim_ranked(
                scout.screen_parcel_rows(_rows_from_csv_text(payload.csv_text)),
                top=payload.top,
                min_score=payload.min_score,
            )
        elif payload.single_parcel_text and payload.single_parcel_text.strip():
            single = scout.screen_parcel_text(
                text=payload.single_parcel_text,
                parcel_id=payload.parcel_id,
                market=payload.market,
            )
            if float(single.get("priority_score", 0.0)) >= payload.min_score:
                screened = [single]

        planning_activity = None
        if payload.watchlist_text and payload.watchlist_text.strip():
            targets = _parse_watch_targets(payload.watchlist_text)
            if targets:
                planning_activity = scout.watch_planning_activity(
                    targets=targets,
                    lookback_days=payload.lookback_days,
                    max_results_per_query=payload.max_results_per_query,
                )

        return {
            "agent": scout.specialist.metadata["blueprint"]["name"],
            "screened_parcels": screened,
            "planning_activity": planning_activity,
        }

    return app


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Residential Subdivision Scout dashboard.")
    parser.add_argument("--host", default="127.0.0.1", help="Bind host.")
    parser.add_argument("--port", type=int, default=8785, help="Bind port.")
    parser.add_argument("--output-root", default="generated_agents", help="Generated agents folder path.")
    parser.add_argument("--agent-dir", help="Optional explicit ResidentialSubdivisionScout directory path.")
    args = parser.parse_args()

    app = create_app(
        output_root=Path(args.output_root),
        subdivision_agent_dir=Path(args.agent_dir) if args.agent_dir else None,
    )

    uvicorn.run(
        app,
        host=args.host,
        port=args.port,
        log_level="info",
    )


if __name__ == "__main__":
    main()
