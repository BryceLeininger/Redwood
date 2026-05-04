"""Background polling and morning summary scheduler for OES."""

from __future__ import annotations

import threading
from datetime import date, datetime, time, timedelta
from typing import Any

from .agent import OESAgent
from .config import OESConfig


class OESBackgroundScheduler:
    def __init__(self, agent: OESAgent, config: OESConfig) -> None:
        self.agent = agent
        self.config = config
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._run, name="oes-background-scheduler", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=5)

    def status(self) -> dict[str, Any]:
        return {
            "enabled": self.config.background_sync_enabled,
            "interval_minutes": self.config.background_sync_minutes,
            "morning_summary_enabled": self.config.morning_summary_enabled,
            "morning_summary_time": f"{self.config.morning_summary_hour:02d}:{self.config.morning_summary_minute:02d}",
            "last_background_sync_at": self.agent.store.get_sync_state("last_background_sync_at"),
            "last_background_error": self.agent.store.get_sync_state("last_background_error"),
        }

    def run_once(self, now: datetime | None = None) -> dict[str, Any]:
        current_time = now or datetime.now().astimezone()
        result = {"sync_triggered": False, "summary_triggered": False}
        with self._lock:
            if self.config.background_sync_enabled and self._is_sync_due(current_time):
                try:
                    self.agent.sync(sample_json_path=None)
                    self.agent.store.set_sync_state("last_background_sync_at", current_time.isoformat())
                    self.agent.store.set_sync_state("last_background_error", "")
                except Exception as error:  # noqa: BLE001
                    self.agent.store.set_sync_state("last_background_error", str(error))
                result["sync_triggered"] = True

            if self.config.morning_summary_enabled and self._is_summary_due(current_time):
                self.agent.generate_morning_summary(force=True, target_date=current_time.date())
                result["summary_triggered"] = True
        return result

    def _run(self) -> None:
        while not self._stop_event.is_set():
            self.run_once()
            self._stop_event.wait(60)

    def _is_sync_due(self, now: datetime) -> bool:
        last_sync_raw = self.agent.store.get_sync_state("last_background_sync_at")
        if not last_sync_raw:
            return True
        last_sync = datetime.fromisoformat(last_sync_raw)
        return now - last_sync >= timedelta(minutes=max(self.config.background_sync_minutes, 1))

    def _is_summary_due(self, now: datetime) -> bool:
        scheduled = datetime.combine(
            now.date(),
            time(hour=self.config.morning_summary_hour, minute=self.config.morning_summary_minute),
            tzinfo=now.tzinfo,
        )
        if now < scheduled:
            return False
        return self.agent.store.get_sync_state("morning_summary_for_date") != now.date().isoformat()