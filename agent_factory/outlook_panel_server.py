"""Local web server backing the Outlook one-button agent panel."""
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Optional

import uvicorn
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .outlook_orchestrator import OutlookAgentOrchestrator

PANEL_DIR = Path(__file__).resolve().parent / "outlook_panel"


class MessageRequest(BaseModel):
    message: str


def create_app(
    *,
    output_root: Path,
    outlook_agent_dir: Optional[Path],
) -> FastAPI:
    app = FastAPI(title="Outlook Agent Panel")
    orchestrator = OutlookAgentOrchestrator(
        output_root=output_root,
        outlook_agent_dir=outlook_agent_dir,
    )

    app.mount("/panel", StaticFiles(directory=str(PANEL_DIR)), name="panel")

    @app.get("/")
    def root() -> FileResponse:
        return FileResponse(PANEL_DIR / "index.html")

    @app.post("/api/start")
    def start() -> dict:
        return orchestrator.start().to_dict()

    @app.post("/api/message")
    def message(payload: MessageRequest) -> dict:
        return orchestrator.handle_message(payload.message).to_dict()

    return app


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Outlook agent panel server.")
    parser.add_argument("--host", default="127.0.0.1", help="Bind host.")
    parser.add_argument("--port", type=int, default=8765, help="Bind port.")
    parser.add_argument("--output-root", default="generated_agents", help="Generated agents folder path.")
    parser.add_argument("--agent-dir", help="Optional explicit OutlookEmailManager directory path.")
    parser.add_argument("--ssl-certfile", help="Optional SSL cert path for HTTPS.")
    parser.add_argument("--ssl-keyfile", help="Optional SSL key path for HTTPS.")
    args = parser.parse_args()

    app = create_app(
        output_root=Path(args.output_root),
        outlook_agent_dir=Path(args.agent_dir) if args.agent_dir else None,
    )

    uvicorn.run(
        app,
        host=args.host,
        port=args.port,
        ssl_certfile=args.ssl_certfile,
        ssl_keyfile=args.ssl_keyfile,
        log_level="info",
    )


if __name__ == "__main__":
    main()
