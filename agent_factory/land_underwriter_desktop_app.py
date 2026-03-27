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

COLORS = {
    "bg": "#F3EFE7",
    "card": "#FCFAF5",
    "card_alt": "#F7F2EA",
    "navy": "#183B4E",
    "navy_soft": "#2D556B",
    "ink": "#16222D",
    "muted": "#6D7A86",
    "line": "#D7D0C3",
    "accent": "#C66C3B",
    "accent_soft": "#F4E2D6",
    "green": "#2D6A4F",
    "green_soft": "#DDEDE5",
    "amber": "#A86418",
    "amber_soft": "#F7E7D1",
    "red": "#8E3B3B",
    "red_soft": "#F4DEDE",
}

SERIES_ROW_COUNT = 5

SERIES_FIELDS = (
    ("name", "Series"),
    ("lots", "Lots"),
    ("avg_sqft", "Avg Sqft"),
    ("base_house_price", "Base Price"),
    ("lot_premium", "Premium"),
    ("direct_cost_psf", "Direct $/SF"),
    ("permit_fees_per_unit", "Permit"),
    ("tap_fees_per_unit", "Tap"),
)

PERCENT_KEYS = {
    "options_pct",
    "price_incentives_pct",
    "mortgage_incentives_pct",
    "direct_cost_contingency_pct",
    "sales_commission_pct",
    "corporate_charge_pct",
    "home_sale_excise_tax_pct",
    "target_gross_margin_pct",
    "target_pre_gna_margin_pct",
    "target_irr_pct",
    "downside_sales_price_delta_pct",
    "downside_cost_delta_pct",
    "downside_absorption_delta_pct",
    "severe_downside_sales_price_delta_pct",
    "severe_downside_cost_delta_pct",
    "severe_downside_absorption_delta_pct",
}


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


def _clean_number_text(value: str) -> str:
    return value.strip().replace("$", "").replace(",", "").replace("%", "")


def _parse_optional_float(value: str) -> float | None:
    cleaned = _clean_number_text(value)
    if not cleaned:
        return None
    return float(cleaned)


def _parse_optional_int(value: str) -> int | None:
    parsed = _parse_optional_float(value)
    if parsed is None:
        return None
    return int(round(parsed))


def _format_currency(value: Any) -> str:
    if value in (None, ""):
        return "-"
    return f"${float(value):,.0f}"


def _format_number(value: Any, digits: int = 1) -> str:
    if value in (None, ""):
        return "-"
    return f"{float(value):,.{digits}f}"


def _format_pct(value: Any) -> str:
    if value in (None, ""):
        return "-"
    return f"{float(value) * 100:.1f}%"


class ScrollableFrame(tk.Frame):
    def __init__(self, parent: tk.Widget, *, bg: str) -> None:
        super().__init__(parent, bg=bg)
        self.canvas = tk.Canvas(self, bg=bg, highlightthickness=0, bd=0)
        self.scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.content = tk.Frame(self.canvas, bg=bg)
        self.window_id = self.canvas.create_window((0, 0), window=self.content, anchor="nw")

        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.scrollbar.pack(side="right", fill="y")

        self.content.bind("<Configure>", self._on_content_configure)
        self.canvas.bind("<Configure>", self._on_canvas_configure)
        self.canvas.bind("<Enter>", self._bind_mousewheel)
        self.canvas.bind("<Leave>", self._unbind_mousewheel)

    def _on_content_configure(self, event: tk.Event) -> None:
        _ = event
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _on_canvas_configure(self, event: tk.Event) -> None:
        self.canvas.itemconfigure(self.window_id, width=event.width)

    def _bind_mousewheel(self, event: tk.Event) -> None:
        _ = event
        self.canvas.bind_all("<MouseWheel>", self._on_mousewheel)

    def _unbind_mousewheel(self, event: tk.Event) -> None:
        _ = event
        self.canvas.unbind_all("<MouseWheel>")

    def _on_mousewheel(self, event: tk.Event) -> None:
        delta = int(-1 * (event.delta / 120))
        self.canvas.yview_scroll(delta, "units")


class LandUnderwriterDesktopApp:
    def __init__(self) -> None:
        self.root = tk.Tk()
        self.root.title("Land Deal Underwriter")
        self.root.geometry("1540x940")
        self.root.minsize(1180, 760)
        self.root.configure(bg=COLORS["bg"])

        self.request_queue: queue.Queue[dict[str, Any] | None] = queue.Queue()
        self.response_queue: queue.Queue[tuple[str, Any]] = queue.Queue()
        self.current_file: Path | None = None
        self.latest_agent_dir: Path | None = None
        self.refresh_job: str | None = None
        self.run_inflight = False

        self.form_vars: dict[str, tk.Variable] = {}
        self.series_rows: list[dict[str, tk.Variable]] = []

        self._configure_theme()
        self._build_ui()
        self._bind_shortcuts()
        self._start_worker()
        self._load_sample_request()
        self._poll_responses()

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _configure_theme(self) -> None:
        style = ttk.Style(self.root)
        style.theme_use("clam")
        style.configure("TNotebook", background=COLORS["bg"], borderwidth=0)
        style.configure(
            "TNotebook.Tab",
            background=COLORS["card_alt"],
            foreground=COLORS["navy"],
            padding=(14, 8),
            font=("Segoe UI", 10, "bold"),
        )
        style.map(
            "TNotebook.Tab",
            background=[("selected", COLORS["card"])],
            foreground=[("selected", COLORS["ink"])],
        )
        style.configure("Treeview", rowheight=28, font=("Segoe UI", 10))
        style.configure("Treeview.Heading", font=("Segoe UI", 10, "bold"))

    def _build_ui(self) -> None:
        shell = tk.Frame(self.root, bg=COLORS["bg"], padx=16, pady=16)
        shell.pack(fill="both", expand=True)
        shell.grid_columnconfigure(0, weight=1)
        shell.grid_rowconfigure(2, weight=1)

        self._build_header(shell)
        self._build_status_strip(shell)

        self.notebook = ttk.Notebook(shell)
        self.notebook.grid(row=2, column=0, sticky="nsew", pady=(14, 0))

        self.builder_tab = tk.Frame(self.notebook, bg=COLORS["bg"])
        self.results_tab = tk.Frame(self.notebook, bg=COLORS["bg"])
        self.json_tab = tk.Frame(self.notebook, bg=COLORS["bg"])

        self.notebook.add(self.builder_tab, text="Deal Builder")
        self.notebook.add(self.results_tab, text="Results Dashboard")
        self.notebook.add(self.json_tab, text="Advanced JSON")

        self._build_builder_tab()
        self._build_results_tab()
        self._build_json_tab()

    def _build_header(self, parent: tk.Widget) -> None:
        header = tk.Frame(parent, bg=COLORS["navy"], padx=22, pady=20)
        header.grid(row=0, column=0, sticky="ew")
        header.grid_columnconfigure(0, weight=1)

        title_col = tk.Frame(header, bg=COLORS["navy"])
        title_col.grid(row=0, column=0, sticky="w")

        tk.Label(
            title_col,
            text="Land Deal Underwriter",
            bg=COLORS["navy"],
            fg="white",
            font=("Aptos Display", 22, "bold"),
        ).pack(anchor="w")
        tk.Label(
            title_col,
            text="Build the deal, pressure-test the land basis, and decide whether to pursue, negotiate, or pass.",
            bg=COLORS["navy"],
            fg="#D8E6EF",
            font=("Segoe UI", 10),
        ).pack(anchor="w", pady=(4, 0))

        actions = tk.Frame(header, bg=COLORS["navy"])
        actions.grid(row=0, column=1, sticky="e")

        self.load_button = self._make_button(actions, "Load Sample", self._load_sample_request, "secondary")
        self.load_button.grid(row=0, column=0, padx=(0, 8))
        self.open_button = self._make_button(actions, "Open JSON", self._open_request_file, "secondary")
        self.open_button.grid(row=0, column=1, padx=(0, 8))
        self.save_button = self._make_button(actions, "Save Request", self._save_request_file, "secondary")
        self.save_button.grid(row=0, column=2, padx=(0, 8))
        self.run_button = self._make_button(actions, "Run Underwrite", self._run_active_request, "primary")
        self.run_button.grid(row=0, column=3)

    def _build_status_strip(self, parent: tk.Widget) -> None:
        strip = tk.Frame(parent, bg=COLORS["bg"], pady=10)
        strip.grid(row=1, column=0, sticky="ew")
        strip.grid_columnconfigure(1, weight=1)

        self.file_var = tk.StringVar(value="Request: sample_request.json")
        self.agent_var = tk.StringVar(value="Agent: detecting latest generated model...")
        self.status_var = tk.StringVar(value="Ready.")

        self._make_info_chip(strip, self.file_var).grid(row=0, column=0, sticky="w", padx=(0, 8))
        self._make_info_chip(strip, self.agent_var).grid(row=0, column=1, sticky="w", padx=(0, 8))
        self._make_info_chip(strip, self.status_var, accent=True).grid(row=0, column=2, sticky="e")

