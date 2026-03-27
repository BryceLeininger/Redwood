"""Standalone desktop UI for the Land Deal Underwriter."""
from __future__ import annotations

import json
import queue
import threading
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, ttk
from tkinter.scrolledtext import ScrolledText
from typing import Any

from .factory_agent import AgentFactory
from .land_underwriter import LandDealUnderwriter


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _sample_request_path() -> Path:
    return _repo_root() / "agent_factory" / "examples" / "land_underwriter" / "sample_request.json"


def _latest_land_underwriter_agent_dir(output_root: Path) -> Path | None:
    factory = AgentFactory(output_root=output_root)
    candidates = [
        item
        for item in factory.list_registered_agents()
        if str(item.get("name", "")).strip().lower() == "landdealunderwriter"
    ]
    candidates.sort(key=lambda item: str(item.get("created_at_utc", "")), reverse=True)

    for item in candidates:
        agent_dir = Path(str(item.get("agent_dir", "")))
        if agent_dir.exists():
            return agent_dir.resolve()

    for agent_dir in sorted(output_root.glob("landdealunderwriter_*"), reverse=True):
        if agent_dir.is_dir():
            return agent_dir.resolve()
    return None


class LandUnderwriterDesktopApp:
    def __init__(self) -> None:
        self.root = tk.Tk()
        self.root.title("Land Deal Underwriter")
        self.root.geometry("1360x860")
        self.root.minsize(980, 700)

        self.request_queue: queue.Queue[str | None] = queue.Queue()
        self.response_queue: queue.Queue[tuple[str, Any]] = queue.Queue()
        self.current_file: Path | None = None

        self._build_ui()
        self._load_sample_request()
        self._start_worker()
        self._poll_responses()

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build_ui(self) -> None:
        root = self.root
        style = ttk.Style(root)
        style.theme_use("clam")
        style.configure("TFrame", background="#eef2f8")
        style.configure("Header.TLabel", background="#eef2f8", foreground="#1d2530", font=("Segoe UI", 15, "bold"))
        style.configure("Sub.TLabel", background="#eef2f8", foreground="#4e6077", font=("Segoe UI", 10))
        style.configure("Status.TLabel", background="#eef2f8", foreground="#405163", font=("Segoe UI", 9))
        style.configure("TButton", font=("Segoe UI", 10))

        shell = ttk.Frame(root, padding=12)
        shell.pack(fill="both", expand=True)
        shell.columnconfigure(0, weight=1)
        shell.rowconfigure(1, weight=1)

        header = ttk.Frame(shell)
        header.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        header.columnconfigure(0, weight=1)

        ttk.Label(header, text="Land Deal Underwriter", style="Header.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(
            header,
            text="Edit a deal JSON request, run workbook-aligned underwriting, and review scenarios.",
            style="Sub.TLabel",
        ).grid(row=1, column=0, sticky="w")

        actions = ttk.Frame(header)
        actions.grid(row=0, column=1, rowspan=2, sticky="e")

        ttk.Button(actions, text="Load Sample", command=self._load_sample_request).grid(row=0, column=0, padx=(0, 6))
        ttk.Button(actions, text="Open JSON", command=self._open_request_file).grid(row=0, column=1, padx=(0, 6))
        ttk.Button(actions, text="Save JSON", command=self._save_request_file).grid(row=0, column=2, padx=(0, 6))
        ttk.Button(actions, text="Run Underwrite", command=self._submit_request).grid(row=0, column=3)

        self.file_var = tk.StringVar(value="Request: sample_request.json")
        self.agent_var = tk.StringVar(value="Agent: starting...")
        self.status_var = tk.StringVar(value="Ready.")

        meta = ttk.Frame(shell)
        meta.grid(row=2, column=0, sticky="ew", pady=(8, 0))
        meta.columnconfigure(0, weight=1)

        ttk.Label(meta, textvariable=self.file_var, style="Status.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(meta, textvariable=self.agent_var, style="Status.TLabel").grid(row=1, column=0, sticky="w")
        ttk.Label(meta, textvariable=self.status_var, style="Status.TLabel").grid(row=2, column=0, sticky="w")

        panes = ttk.Panedwindow(shell, orient="horizontal")
        panes.grid(row=1, column=0, sticky="nsew")

        request_frame = ttk.Frame(panes, padding=(0, 0, 6, 0))
        result_frame = ttk.Frame(panes, padding=(6, 0, 0, 0))
        request_frame.columnconfigure(0, weight=1)
        request_frame.rowconfigure(1, weight=1)
        result_frame.columnconfigure(0, weight=1)
        result_frame.rowconfigure(1, weight=1)
        panes.add(request_frame, weight=1)
        panes.add(result_frame, weight=1)

        ttk.Label(request_frame, text="Request JSON", style="Sub.TLabel").grid(row=0, column=0, sticky="w", pady=(0, 6))
        ttk.Label(result_frame, text="Underwriting Result", style="Sub.TLabel").grid(row=0, column=0, sticky="w", pady=(0, 6))

        self.request_text = ScrolledText(
            request_frame,
            wrap="none",
            font=("Consolas", 10),
            bg="#fbfcfe",
            fg="#1f2733",
            insertbackground="#1f2733",
            relief="flat",
            borderwidth=1,
        )
        self.request_text.grid(row=1, column=0, sticky="nsew")
        self.request_text.bind("<Control-Return>", self._submit_request)

        self.result_text = ScrolledText(
            result_frame,
            wrap="none",
            font=("Consolas", 10),
            bg="#ffffff",
            fg="#1f2733",
            insertbackground="#1f2733",
            relief="flat",
            borderwidth=1,
        )
        self.result_text.grid(row=1, column=0, sticky="nsew")
        self.result_text.configure(state="disabled")

    def _timestamp(self) -> str:
        return datetime.now().strftime("%H:%M:%S")

    def _set_status(self, text: str) -> None:
        self.status_var.set(f"[{self._timestamp()}] {text}")

    def _load_sample_request(self) -> None:
        sample_path = _sample_request_path()
        if not sample_path.exists():
            self._set_status(f"Sample request not found: {sample_path}")
            return
        self.current_file = sample_path
        self.file_var.set(f"Request: {sample_path.name}")
        self.request_text.delete("1.0", "end")
        self.request_text.insert("1.0", sample_path.read_text(encoding="utf-8"))
        self._set_status("Loaded sample request.")

    def _open_request_file(self) -> None:
        selected = filedialog.askopenfilename(
            parent=self.root,
            title="Open Land Underwrite Request",
            filetypes=[("JSON Files", "*.json"), ("All Files", "*.*")],
            initialdir=str(_repo_root()),
        )
        if not selected:
            return
        path = Path(selected)
        self.current_file = path
        self.file_var.set(f"Request: {path.name}")
        self.request_text.delete("1.0", "end")
        self.request_text.insert("1.0", path.read_text(encoding="utf-8"))
        self._set_status(f"Loaded {path.name}.")

    def _save_request_file(self) -> None:
        initial_name = self.current_file.name if self.current_file else "land_underwrite_request.json"
        selected = filedialog.asksaveasfilename(
            parent=self.root,
            title="Save Land Underwrite Request",
            defaultextension=".json",
            filetypes=[("JSON Files", "*.json"), ("All Files", "*.*")],
            initialdir=str(_repo_root()),
            initialfile=initial_name,
        )
        if not selected:
            return

        path = Path(selected)
        content = self.request_text.get("1.0", "end").strip()
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError as error:
            self._set_status(f"Cannot save invalid JSON: {error.msg}")
            return

        path.write_text(json.dumps(parsed, indent=2), encoding="utf-8")
        self.current_file = path
        self.file_var.set(f"Request: {path.name}")
        self._set_status(f"Saved {path.name}.")

    def _submit_request(self, event: tk.Event | None = None) -> None:
        _ = event
        raw_request = self.request_text.get("1.0", "end").strip()
        if not raw_request:
            self._set_status("Request JSON cannot be empty.")
            return
        self._set_status("Running underwriting...")
        self.request_queue.put(raw_request)

    def _start_worker(self) -> None:
        thread = threading.Thread(target=self._worker_loop, daemon=True, name="land-underwriter-worker")
        thread.start()

    def _worker_loop(self) -> None:
        output_root = _repo_root() / "generated_agents"
        latest_agent_dir = _latest_land_underwriter_agent_dir(output_root)
        specialist = None
        if latest_agent_dir is not None:
            try:
                specialist = AgentFactory().load_specialist_agent(latest_agent_dir)
                self.response_queue.put(("agent", f"Agent: {latest_agent_dir.name}"))
            except Exception as error:  # noqa: BLE001
                self.response_queue.put(("agent", f"Agent load failed: {error}"))
        else:
            self.response_queue.put(("agent", "Agent: no generated LandDealUnderwriter found; running calculator only"))

        underwriter = LandDealUnderwriter(specialist)

        while True:
            raw_request = self.request_queue.get()
            if raw_request is None:
                break
            try:
                payload = json.loads(raw_request)
                if isinstance(payload, list):
                    result = underwriter.underwrite_many(payload)
                elif isinstance(payload, dict):
                    result = underwriter.underwrite(payload)
                else:
                    raise ValueError("Request JSON must be an object or an array of objects.")
                self.response_queue.put(("result", result))
            except Exception as error:  # noqa: BLE001
                self.response_queue.put(("error", str(error)))

    def _poll_responses(self) -> None:
        while True:
            try:
                kind, payload = self.response_queue.get_nowait()
            except queue.Empty:
                break

            if kind == "agent":
                self.agent_var.set(str(payload))
            elif kind == "result":
                self._render_result(payload)
                self._set_status("Underwriting complete.")
            elif kind == "error":
                self._render_result({"error": payload})
                self._set_status(f"Error: {payload}")

        self.root.after(120, self._poll_responses)

    def _render_result(self, payload: Any) -> None:
        rendered = json.dumps(payload, indent=2, ensure_ascii=False)
        self.result_text.configure(state="normal")
        self.result_text.delete("1.0", "end")
        self.result_text.insert("1.0", rendered)
        self.result_text.configure(state="disabled")

    def _on_close(self) -> None:
        self.request_queue.put(None)
        self.root.destroy()

    def run(self) -> None:
        self.root.mainloop()


def main() -> None:
    app = LandUnderwriterDesktopApp()
    app.run()


if __name__ == "__main__":
    main()
