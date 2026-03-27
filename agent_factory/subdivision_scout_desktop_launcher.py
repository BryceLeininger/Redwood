"""Desktop launcher for the Residential Subdivision Scout dashboard."""
from __future__ import annotations

import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

HOST = "127.0.0.1"
PORT = 8785
START_URL = f"http://{HOST}:{PORT}"
HEALTH_URL = f"{START_URL}/api/start"
STARTUP_WAIT_SECONDS = 12.0
POLL_INTERVAL_SECONDS = 0.4


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _healthcheck() -> bool:
    try:
        with urllib.request.urlopen(HEALTH_URL, timeout=1.5) as response:
            return 200 <= response.status < 300
    except (urllib.error.URLError, TimeoutError):
        return False


def _start_server() -> None:
    python_executable = Path(sys.executable)
    log_path = _repo_root() / "generated_agents" / "subdivision_scout_panel.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_handle = log_path.open("a", encoding="utf-8")

    creationflags = 0
    if sys.platform.startswith("win"):
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS  # type: ignore[attr-defined]

    subprocess.Popen(
        [
            str(python_executable),
            "-m",
            "agent_factory.subdivision_scout_panel_server",
            "--host",
            HOST,
            "--port",
            str(PORT),
        ],
        cwd=str(_repo_root()),
        stdout=log_handle,
        stderr=subprocess.STDOUT,
        creationflags=creationflags,
        close_fds=False,
    )


def _wait_for_server() -> None:
    deadline = time.time() + STARTUP_WAIT_SECONDS
    while time.time() < deadline:
        if _healthcheck():
            return
        time.sleep(POLL_INTERVAL_SECONDS)


def main() -> None:
    if not _healthcheck():
        _start_server()
        _wait_for_server()

    webbrowser.open(START_URL)


if __name__ == "__main__":
    main()
