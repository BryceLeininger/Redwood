"""Desktop launcher for the Residential Subdivision Scout dashboard."""
from __future__ import annotations

import subprocess
import sys
import time
import urllib.error
import json
import urllib.request
import webbrowser
from pathlib import Path

HOST = "127.0.0.1"
PORT = 8785
START_URL = f"http://{HOST}:{PORT}"
HEALTH_URL = f"{START_URL}/api/start"
STARTUP_WAIT_SECONDS = 12.0
POLL_INTERVAL_SECONDS = 0.4
REQUIRED_API_VERSION = 3


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _read_start_payload() -> dict[str, object] | None:
    try:
        with urllib.request.urlopen(HEALTH_URL, timeout=1.5) as response:
            if not (200 <= response.status < 300):
                return None
            return json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError):
        return None


def _healthcheck() -> bool:
    return _read_start_payload() is not None


def _server_is_current() -> bool:
    payload = _read_start_payload()
    if not payload:
        return False
    try:
        return int(payload.get("api_version", 0)) >= REQUIRED_API_VERSION
    except (TypeError, ValueError):
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
        if _server_is_current():
            return
        time.sleep(POLL_INTERVAL_SECONDS)


def _stop_server_on_port() -> None:
    if not sys.platform.startswith("win"):
        return

    command = (
        "$conn = Get-NetTCPConnection -LocalPort 8785 -State Listen -ErrorAction SilentlyContinue | "
        "Select-Object -First 1 -ExpandProperty OwningProcess; "
        "if ($conn) { Stop-Process -Id $conn -Force }"
    )
    subprocess.run(
        ["powershell", "-NoProfile", "-Command", command],
        cwd=str(_repo_root()),
        check=False,
        capture_output=True,
        text=True,
    )
    time.sleep(0.8)


def main() -> None:
    if not _server_is_current():
        if _healthcheck():
            _stop_server_on_port()
        _start_server()
        _wait_for_server()

    webbrowser.open(START_URL)


if __name__ == "__main__":
    main()
