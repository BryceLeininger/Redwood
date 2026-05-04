"""FastAPI web UI for the Outlook Email Secretary agent."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Form, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .agent import OESAgent
from .config import load_config
from .scheduler import OESBackgroundScheduler
from .storage import LocalStore


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
                "reminders": data["reminders"],
                "graph_configured": data["graph_configured"],
                "local_outlook_available": data["local_outlook_available"],
                "ai_configured": data["ai_configured"],
                "last_sync_source": data["last_sync_source"],
                "morning_summary_text": data["morning_summary_text"],
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