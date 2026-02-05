"""Standalone desktop UI for orchestrating the Outlook agent."""
from __future__ import annotations

import json
import queue
import threading
import tkinter as tk
from datetime import datetime
from tkinter import ttk
from tkinter.scrolledtext import ScrolledText
from typing import Any

from .outlook_orchestrator import OutlookAgentOrchestrator


class DesktopAgentApp:
    def __init__(self) -> None:
        self.root = tk.Tk()
        self.root.title("Outlook Agent Desktop")
        self.root.geometry("980x680")
        self.root.minsize(760, 520)

        self.command_queue: queue.Queue[str | None] = queue.Queue()
        self.response_queue: queue.Queue[tuple[str, str, Any | None]] = queue.Queue()

        self._build_ui()
        self._start_worker()
        self._poll_responses()

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build_ui(self) -> None:
        root = self.root

        style = ttk.Style(root)
        style.theme_use("clam")
        style.configure("TFrame", background="#eef2f8")
        style.configure("Header.TLabel", background="#eef2f8", foreground="#1d2530", font=("Segoe UI", 14, "bold"))
        style.configure("Sub.TLabel", background="#eef2f8", foreground="#4e6077", font=("Segoe UI", 10))
        style.configure("TButton", font=("Segoe UI", 10))

        shell = ttk.Frame(root, padding=12)
        shell.pack(fill="both", expand=True)
        shell.columnconfigure(0, weight=1)
        shell.rowconfigure(1, weight=1)

        header = ttk.Frame(shell)
        header.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        header.columnconfigure(0, weight=1)

        ttk.Label(header, text="Outlook Agent", style="Header.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(
            header,
            text="Use commands or natural language. Start with: help",
            style="Sub.TLabel",
        ).grid(row=1, column=0, sticky="w")

        self.chat = ScrolledText(
            shell,
            wrap="word",
            font=("Consolas", 10),
            bg="#ffffff",
            fg="#1f2733",
            insertbackground="#1f2733",
            relief="flat",
            borderwidth=1,
        )
        self.chat.grid(row=1, column=0, sticky="nsew")
        self.chat.configure(state="disabled")
        self.chat.tag_configure("agent", foreground="#0f3f75")
        self.chat.tag_configure("user", foreground="#245e17")
        self.chat.tag_configure("meta", foreground="#5d6d80")

        composer = ttk.Frame(shell)
        composer.grid(row=2, column=0, sticky="ew", pady=(10, 0))
        composer.columnconfigure(0, weight=1)

        self.input = ttk.Entry(composer, font=("Segoe UI", 10))
        self.input.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self.input.bind("<Return>", self._on_send)

        self.send_btn = ttk.Button(composer, text="Send", command=self._on_send)
        self.send_btn.grid(row=0, column=1, sticky="e")

        quickbar = ttk.Frame(shell)
        quickbar.grid(row=3, column=0, sticky="ew", pady=(10, 0))
        for idx, command in enumerate(("help", "inbox 10", "triage 10 unread", "review my unread emails", "memory")):
            btn = ttk.Button(quickbar, text=command, command=lambda c=command: self._send_command(c))
            btn.grid(row=0, column=idx, padx=(0, 6))

        self.input.focus_set()

    def _start_worker(self) -> None:
        thread = threading.Thread(target=self._worker_loop, daemon=True, name="outlook-agent-worker")
        thread.start()

    def _worker_loop(self) -> None:
        try:
            orchestrator = OutlookAgentOrchestrator()
            start = orchestrator.start()
            self.response_queue.put(("agent", start.text, start.data))
        except Exception as error:  # noqa: BLE001
            self.response_queue.put(("agent", f"Startup error: {error}", None))
            return

        while True:
            command = self.command_queue.get()
            if command is None:
                break
            try:
                reply = orchestrator.handle_message(command)
                self.response_queue.put(("agent", reply.text, reply.data))
            except Exception as error:  # noqa: BLE001
                self.response_queue.put(("agent", f"Error: {error}", None))

    def _poll_responses(self) -> None:
        while True:
            try:
                role, text, data = self.response_queue.get_nowait()
            except queue.Empty:
                break
            self._append_message(role, text, data)

        self.root.after(120, self._poll_responses)

    def _timestamp(self) -> str:
        return datetime.now().strftime("%H:%M:%S")

    def _append_message(self, role: str, text: str, data: Any | None) -> None:
        tag = "agent" if role == "agent" else "user"
        label = "Agent" if role == "agent" else "You"
        timestamp = self._timestamp()

        self.chat.configure(state="normal")
        self.chat.insert("end", f"[{timestamp}] {label}: {text}\n", tag)
        if data is not None:
            rendered = json.dumps(data, indent=2, ensure_ascii=False)
            self.chat.insert("end", f"{rendered}\n", "meta")
        self.chat.insert("end", "\n", "meta")
        self.chat.configure(state="disabled")
        self.chat.see("end")

    def _send_command(self, command: str) -> None:
        if not command.strip():
            return
        self._append_message("user", command, None)
        self.command_queue.put(command)

    def _on_send(self, event: tk.Event | None = None) -> None:
        _ = event
        command = self.input.get().strip()
        if not command:
            return
        self.input.delete(0, "end")
        self._send_command(command)

    def _on_close(self) -> None:
        self.command_queue.put(None)
        self.root.destroy()

    def run(self) -> None:
        self.root.mainloop()


def main() -> None:
    app = DesktopAgentApp()
    app.run()


if __name__ == "__main__":
    main()
