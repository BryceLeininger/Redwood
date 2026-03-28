"""Desktop launcher for the Building Fee Budget Advisor workflow."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from tkinter import Tk, filedialog, messagebox


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _default_request_path() -> Path:
    return _repo_root() / "agent_factory" / "examples" / "building_fee_budgeter" / "sample_request.json"


def _pick_request_file() -> Path | None:
    root = Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    default_path = _default_request_path()
    selected = filedialog.askopenfilename(
        title="Select fee budget request JSON",
        initialdir=str(default_path.parent),
        initialfile=default_path.name,
        filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
        parent=root,
    )
    root.destroy()
    if not selected:
        return None
    return Path(selected)


def _run_fee_budget(request_path: Path) -> Path:
    output_dir = _repo_root() / "generated_agents" / "fee_budget_reports"
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = output_dir / f"{request_path.stem}_budget_{timestamp}.json"

    completed = subprocess.run(
        [
            str(Path(sys.executable)),
            "-m",
            "agent_factory.cli",
            "fee-budget",
            "--request-file",
            str(request_path),
        ],
        cwd=str(_repo_root()),
        capture_output=True,
        text=True,
        check=False,
    )

    if completed.returncode != 0:
        error_text = completed.stderr.strip() or completed.stdout.strip() or "Unknown error"
        raise RuntimeError(error_text)

    payload = json.loads(completed.stdout)
    output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return output_path


def main() -> None:
    request_path = _pick_request_file()
    if request_path is None:
        return

    root = Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    try:
        output_path = _run_fee_budget(request_path)
    except Exception as error:
        messagebox.showerror("Building Fee Budget Advisor", str(error), parent=root)
        root.destroy()
        return

    messagebox.showinfo(
        "Building Fee Budget Advisor",
        f"Fee budget created:\n{output_path}",
        parent=root,
    )
    root.destroy()

    if sys.platform.startswith("win"):
        os.startfile(str(output_path))  # type: ignore[attr-defined]


if __name__ == "__main__":
    main()
