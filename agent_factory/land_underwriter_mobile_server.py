"""Mobile web app for the Land Deal Underwriter."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Optional

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .constants import METADATA_FILE
from .factory_agent import AgentFactory
from .land_underwriter import LandDealUnderwriter
from .specialist_agent import SpecialistAgent

PANEL_DIR = Path(__file__).resolve().parent / "land_underwriter_mobile"
EXAMPLE_DIR = Path(__file__).resolve().parent / "examples" / "land_underwriter"
STARTER_DEAL_PATH = EXAMPLE_DIR / "starter_deal.landdeal"
PANEL_API_VERSION = 1


class UnderwriteRequest(BaseModel):
    agent_dir: str | None = None
    deal: dict[str, Any]


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
    return index_html.replace("__ASSET_VERSION__", asset_version)


def _root_prefix(request: Request) -> str:
    return str(request.scope.get("root_path") or "").rstrip("/")


def _manifest_payload(request: Request) -> dict[str, Any]:
    prefix = _root_prefix(request)
    start_url = f"{prefix}/" if prefix else "/"
    icon_prefix = prefix or ""
    return {
        "name": "Land Acquisition Studio",
        "short_name": "Underwrite",
        "id": start_url,
        "start_url": start_url,
        "scope": start_url,
        "display": "standalone",
        "orientation": "portrait",
        "background_color": "#f3efe7",
        "theme_color": "#153246",
        "description": "Mobile homebuilder land underwriting with phasing, CMA, and deal memos.",
        "icons": [
            {
                "src": f"{icon_prefix}/panel/assets/icon-192.png" or "/panel/assets/icon-192.png",
                "sizes": "192x192",
                "type": "image/png",
            },
            {
                "src": f"{icon_prefix}/panel/assets/icon-512.png" or "/panel/assets/icon-512.png",
                "sizes": "512x512",
                "type": "image/png",
            },
        ],
    }


def _list_underwriter_agents(output_root: Path) -> list[dict[str, Any]]:
    factory = AgentFactory(output_root=output_root)
    registry_items = factory.list_registered_agents()

    matches = [
        item
        for item in registry_items
        if str(item.get("name", "")).strip().lower() == "landdealunderwriter"
    ]
    if matches:
        matches.sort(key=lambda item: str(item.get("created_at_utc", "")), reverse=True)
        return matches

    fallback: list[dict[str, Any]] = []
    for agent_dir in sorted(output_root.glob("landdealunderwriter_*"), reverse=True):
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

    agents = _list_underwriter_agents(output_root)
    if not agents:
        return None
    return Path(str(agents[0]["agent_dir"])).resolve()


def _load_underwriter(
    *,
    output_root: Path,
    explicit_agent_dir: Optional[Path],
    requested_agent_dir: str | None,
) -> LandDealUnderwriter:
    resolved_agent_dir = Path(requested_agent_dir).resolve() if requested_agent_dir else _default_agent_dir(
        output_root,
        explicit_agent_dir,
    )
    specialist = None
    if resolved_agent_dir is not None:
        if not resolved_agent_dir.exists():
            raise HTTPException(status_code=404, detail=f"Agent directory was not found: {resolved_agent_dir}")
        specialist = SpecialistAgent.load(resolved_agent_dir)
    return LandDealUnderwriter(specialist)


def _load_starter_deal() -> dict[str, Any]:
    if not STARTER_DEAL_PATH.exists():
        raise FileNotFoundError(f"Starter deal file was not found: {STARTER_DEAL_PATH}")
    return json.loads(STARTER_DEAL_PATH.read_text(encoding="utf-8"))


def create_app(*, output_root: Path, agent_dir: Optional[Path]) -> FastAPI:
    app = FastAPI(title="Land Acquisition Studio Mobile")

    @app.middleware("http")
    async def disable_cache_for_panel_assets(request: Request, call_next):
        response = await call_next(request)
        if request.url.path == "/" or request.url.path.startswith("/panel/"):
            for key, value in _panel_cache_headers().items():
                response.headers[key] = value
        return response

    app.mount("/panel", StaticFiles(directory=str(PANEL_DIR)), name="panel")

    @app.get("/")
    def root() -> HTMLResponse:
        return HTMLResponse(content=_render_panel_index(), headers=_panel_cache_headers())

    @app.get("/manifest.webmanifest")
    def manifest(request: Request) -> Response:
        return Response(
            content=json.dumps(_manifest_payload(request)),
            media_type="application/manifest+json",
            headers=_panel_cache_headers(),
        )

    @app.get("/service-worker.js")
    def service_worker() -> Response:
        return Response(
            content=(PANEL_DIR / "service-worker.js").read_text(encoding="utf-8"),
            media_type="application/javascript",
            headers=_panel_cache_headers(),
        )

    @app.get("/api/start")
    def start() -> dict[str, Any]:
        agents = _list_underwriter_agents(output_root)
        default_agent = _default_agent_dir(output_root, agent_dir)
        return {
            "reply": "Land Acquisition Studio ready.",
            "api_version": PANEL_API_VERSION,
            "default_agent_dir": str(default_agent) if default_agent else None,
            "agents": agents,
            "starter_deal": _load_starter_deal(),
            "starter_file_name": STARTER_DEAL_PATH.name,
        }

    @app.get("/api/agents")
    def agents() -> dict[str, Any]:
        return {"agents": _list_underwriter_agents(output_root)}

    @app.post("/api/underwrite")
    def underwrite(payload: UnderwriteRequest) -> dict[str, Any]:
        if not payload.deal:
            raise HTTPException(status_code=400, detail="A deal draft is required before running the underwrite.")
        underwriter = _load_underwriter(
            output_root=output_root,
            explicit_agent_dir=agent_dir,
            requested_agent_dir=payload.agent_dir,
        )
        try:
            return underwriter.underwrite(payload.deal)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    return app


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Land Acquisition Studio mobile web app.")
    parser.add_argument("--host", default="127.0.0.1", help="Bind host.")
    parser.add_argument("--port", type=int, default=8787, help="Bind port.")
    parser.add_argument("--output-root", default="generated_agents", help="Generated agents folder path.")
    parser.add_argument("--agent-dir", help="Optional explicit LandDealUnderwriter directory path.")
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
