"""FastAPI web UI for the Outlook Email Secretary agent."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .agent import OESAgent
from .config import load_config
from .models import DraftAttachment
from .scheduler import OESBackgroundScheduler
from .storage import LocalStore


def _build_morning_summary_sections(summary_text: str | None) -> list[dict[str, Any]]:
    if not summary_text:
        return []

    sections: list[dict[str, Any]] = []
    for block in [item.strip() for item in summary_text.split("\n\n") if item.strip()]:
        title, separator, remainder = block.partition(":\n")
        if separator:
            sections.append(
                {
                    "title": title,
                    "kind": "list",
                    "items": [line.lstrip("- ").strip() for line in remainder.splitlines() if line.strip()],
                }
            )
            continue

        sections.append(
            {
                "title": None,
                "kind": "text",
                "items": [line.strip() for line in block.splitlines() if line.strip()],
            }
        )
    return sections


def create_app() -> FastAPI:
    config = load_config()
    store = LocalStore(config.db_path)
    store.ensure_ready()
    agent = OESAgent(config=config, store=store)
    scheduler = OESBackgroundScheduler(agent=agent, config=config)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.agent = agent
        app.state.scheduler = scheduler
        scheduler.start()
        try:
            yield
        finally:
            scheduler.stop()

    app = FastAPI(title="Outlook Email Secretary", lifespan=lifespan)

    base_dir = Path(__file__).resolve().parent
    templates = Jinja2Templates(directory=str(base_dir / "templates"))
    app.mount("/static", StaticFiles(directory=str(base_dir / "static")), name="static")

    @app.get("/")
    async def dashboard(request: Request):
        data = agent.dashboard()
        return templates.TemplateResponse(
            request,
            "dashboard.html",
            {
                "messages": data["messages"],
                "events": data["events"],
                "approvals": data["approvals"],
                "draft_items": data["draft_items"],
                "reminders": data["reminders"],
                "auto_drafted_count": data["auto_drafted_count"],
                "response_profile": data["response_profile"],
                "graph_configured": data["graph_configured"],
                "local_outlook_available": data["local_outlook_available"],
                "ai_configured": data["ai_configured"],
                "last_sync_source": data["last_sync_source"],
                "morning_summary_text": data["morning_summary_text"],
                "morning_summary_sections": _build_morning_summary_sections(data["morning_summary_text"]),
                "morning_summary_generated_at": data["morning_summary_generated_at"],
                "scheduler_status": scheduler.status(),
            },
        )

    @app.post("/actions/sync-sample")
    async def sync_sample() -> RedirectResponse:
        agent.sync(sample_json_path=Path("generated_agents/outlook_local_cache.json"))
        return RedirectResponse(url="/", status_code=303)

    @app.post("/actions/sync-live")
    async def sync_live() -> RedirectResponse:
        agent.sync(sample_json_path=None)
        return RedirectResponse(url="/", status_code=303)

    @app.post("/actions/generate-summary")
    async def generate_summary() -> RedirectResponse:
        agent.generate_morning_summary(force=True)
        return RedirectResponse(url="/", status_code=303)

    @app.post("/actions/approve/{approval_id}")
    async def approve(approval_id: int) -> RedirectResponse:
        agent.approve(approval_id)
        return RedirectResponse(url="/", status_code=303)

    @app.post("/actions/reject/{approval_id}")
    async def reject(approval_id: int) -> RedirectResponse:
        agent.reject(approval_id)
        return RedirectResponse(url="/", status_code=303)

    @app.post("/actions/drafts/{approval_id}/attachments")
    async def attach_draft_files(
        approval_id: int,
        attachments: list[UploadFile] = File(...),
        relative_paths: list[str] = Form(default=[]),
    ) -> RedirectResponse:
        draft_attachments: list[DraftAttachment] = []
        for index, upload in enumerate(attachments):
            if not upload.filename:
                continue
            content = await upload.read()
            if not content:
                continue
            relative_path = relative_paths[index] if index < len(relative_paths) else upload.filename
            draft_attachments.append(
                DraftAttachment(
                    file_name=upload.filename,
                    content=content,
                    content_type=upload.content_type,
                    relative_path=relative_path,
                )
            )

        if not draft_attachments:
            raise HTTPException(status_code=400, detail="Select at least one file or folder before attaching.")

        try:
            agent.attach_files_to_draft(approval_id, draft_attachments)
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        return RedirectResponse(url="/", status_code=303)

    @app.post("/actions/reminders")
    async def add_reminder(
        title: str = Form(...),
        due_at: str = Form(""),
        notes: str = Form(""),
    ) -> RedirectResponse:
        normalized_due_at = due_at.strip() or None
        agent.create_manual_reminder(title=title.strip(), due_at=normalized_due_at, notes=notes.strip())
        return RedirectResponse(url="/", status_code=303)

    return app