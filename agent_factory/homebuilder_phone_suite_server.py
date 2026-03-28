"""Single mobile entry point that mounts the homebuilder land apps."""
from __future__ import annotations

import argparse
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from .land_underwriter_mobile_server import create_app as create_underwriter_app
from .residential_land_due_diligence_panel_server import create_app as create_diligence_app
from .subdivision_scout_panel_server import create_app as create_subdivision_app

SUITE_DIR = Path(__file__).resolve().parent / "homebuilder_phone_suite"
SUITE_API_VERSION = 1


def _asset_version() -> str:
    asset_paths = [SUITE_DIR / "index.html", SUITE_DIR / "styles.css", SUITE_DIR / "app.js"]
    mtimes = [int(path.stat().st_mtime) for path in asset_paths if path.exists()]
    latest_mtime = max(mtimes, default=0)
    return f"{SUITE_API_VERSION}-{latest_mtime}"


def _render_index() -> str:
    index_html = (SUITE_DIR / "index.html").read_text(encoding="utf-8")
    return index_html.replace("__ASSET_VERSION__", _asset_version())


def create_app(
    *,
    output_root: Path,
    subdivision_agent_dir: Path | None,
    diligence_agent_dir: Path | None,
    underwriter_agent_dir: Path | None,
) -> FastAPI:
    app = FastAPI(title="Homebuilder Phone Suite")
    app.mount("/suite", StaticFiles(directory=str(SUITE_DIR)), name="suite")
    app.mount(
        "/subdivision",
        create_subdivision_app(output_root=output_root, subdivision_agent_dir=subdivision_agent_dir),
    )
    app.mount(
        "/diligence",
        create_diligence_app(output_root=output_root, agent_dir=diligence_agent_dir),
    )
    app.mount(
        "/underwrite",
        create_underwriter_app(output_root=output_root, agent_dir=underwriter_agent_dir),
    )

    @app.get("/")
    def root() -> HTMLResponse:
        return HTMLResponse(content=_render_index())

    return app


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the phone suite for the land apps.")
    parser.add_argument("--host", default="0.0.0.0", help="Bind host.")
    parser.add_argument("--port", type=int, default=8790, help="Bind port.")
    parser.add_argument("--output-root", default="generated_agents", help="Generated agents folder path.")
    parser.add_argument("--subdivision-agent-dir", help="Optional explicit ResidentialSubdivisionScout directory path.")
    parser.add_argument("--diligence-agent-dir", help="Optional explicit ResidentialLandDueDiligenceAdvisor directory path.")
    parser.add_argument("--underwriter-agent-dir", help="Optional explicit LandDealUnderwriter directory path.")
    args = parser.parse_args()

    app = create_app(
        output_root=Path(args.output_root),
        subdivision_agent_dir=Path(args.subdivision_agent_dir) if args.subdivision_agent_dir else None,
        diligence_agent_dir=Path(args.diligence_agent_dir) if args.diligence_agent_dir else None,
        underwriter_agent_dir=Path(args.underwriter_agent_dir) if args.underwriter_agent_dir else None,
    )

    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
