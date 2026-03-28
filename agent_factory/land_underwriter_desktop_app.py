"""Standalone desktop UI for the Land Deal Underwriter."""
from __future__ import annotations

import json
import math
import queue
import threading
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
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
PHASE_ROW_COUNT = 6
COMPETITOR_ROW_COUNT = 6
RESALE_ROW_COUNT = 8

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

PHASE_FIELDS = (
    ("name", "Phase"),
    ("month", "Close Mo"),
    ("lots", "Lots"),
    ("price_per_lot", "Price / Lot"),
)

COMPETITOR_FIELDS = (
    ("name", "Community"),
    ("monthly_absorption", "Pace / Mo"),
    ("avg_price", "Net Price"),
    ("avg_sqft", "Avg Sqft"),
    ("status", "Status"),
)

RESALE_FIELDS = (
    ("name", "Resale / Address"),
    ("close_price", "Close Price"),
    ("sqft", "Sqft"),
    ("distance_miles", "Miles"),
    ("close_date", "Close Date"),
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
    return _repo_root() / "agent_factory" / "examples" / "land_underwriter" / "starter_deal.landdeal"


def _deal_display_name(path: Path | None) -> str:
    if path is None:
        return "Unsaved Deal"
    stem = path.stem.replace("_", " ").replace("-", " ").strip()
    return stem.title() or "Deal"


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


def _parse_optional_ratio(value: str) -> float | None:
    parsed = _parse_optional_float(value)
    if parsed is None:
        return None
    return parsed / 100.0 if abs(parsed) > 1 else parsed


def _format_input_number(value: Any, digits: int = 4) -> str:
    if value in (None, ""):
        return ""
    number = float(value)
    if number.is_integer():
        return str(int(number))
    return f"{number:.{digits}f}".rstrip("0").rstrip(".")


def _format_input_ratio(value: Any, digits: int = 4) -> str:
    if value in (None, ""):
        return ""
    number = float(value) * 100.0
    if number.is_integer():
        return str(int(number))
    return f"{number:.{digits}f}".rstrip("0").rstrip(".")


def _scenario_label(name: str) -> str:
    return name.replace("_", " ").replace("case", "case").title()


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
        self.root.title("Land Acquisition Studio")
        self.root.geometry("1540x940")
        self.root.minsize(1180, 760)
        self.root.configure(bg=COLORS["bg"])

        self.request_queue: queue.Queue[dict[str, Any] | None] = queue.Queue()
        self.response_queue: queue.Queue[tuple[str, Any]] = queue.Queue()
        self.current_file: Path | None = None
        self.latest_agent_dir: Path | None = None
        self.refresh_job: str | None = None
        self.run_inflight = False
        self.current_result: Any = None
        self.hidden_payload_cache: Any = None

        self.form_vars: dict[str, tk.Variable] = {}
        self.series_rows: list[dict[str, tk.Variable]] = []
        self.phase_rows: list[dict[str, tk.Variable]] = []
        self.competitor_rows: list[dict[str, tk.Variable]] = []
        self.resale_rows: list[dict[str, tk.Variable]] = []

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

        self.notebook.add(self.builder_tab, text="Deal Workspace")
        self.notebook.add(self.results_tab, text="Decision Center")

        self._build_builder_tab()
        self._build_results_tab()

    def _build_header(self, parent: tk.Widget) -> None:
        header = tk.Frame(parent, bg=COLORS["navy"], padx=22, pady=20)
        header.grid(row=0, column=0, sticky="ew")
        header.grid_columnconfigure(0, weight=1)

        title_col = tk.Frame(header, bg=COLORS["navy"])
        title_col.grid(row=0, column=0, sticky="w")

        tk.Label(
            title_col,
            text="Land Acquisition Studio",
            bg=COLORS["navy"],
            fg="white",
            font=("Aptos Display", 22, "bold"),
        ).pack(anchor="w")
        tk.Label(
            title_col,
            text="Shape the deal, benchmark the market, and generate a clean acquisition decision packet.",
            bg=COLORS["navy"],
            fg="#D8E6EF",
            font=("Segoe UI", 10),
        ).pack(anchor="w", pady=(4, 0))

        actions = tk.Frame(header, bg=COLORS["navy"])
        actions.grid(row=0, column=1, sticky="e")

        self.load_button = self._make_button(actions, "Load Starter Deal", self._load_sample_request, "secondary")
        self.load_button.grid(row=0, column=0, padx=(0, 8))
        self.open_button = self._make_button(actions, "Open Deal", self._open_request_file, "secondary")
        self.open_button.grid(row=0, column=1, padx=(0, 8))
        self.save_button = self._make_button(actions, "Save Deal", self._save_request_file, "secondary")
        self.save_button.grid(row=0, column=2, padx=(0, 8))
        self.memo_button = self._make_button(actions, "Copy IC Memo", self._copy_ic_memo, "secondary")
        self.memo_button.grid(row=0, column=3, padx=(0, 8))
        self.run_button = self._make_button(actions, "Run Underwrite", self._run_active_request, "primary")
        self.run_button.grid(row=0, column=4)

    def _build_status_strip(self, parent: tk.Widget) -> None:
        strip = tk.Frame(parent, bg=COLORS["bg"], pady=10)
        strip.grid(row=1, column=0, sticky="ew")
        strip.grid_columnconfigure(1, weight=1)

        self.file_var = tk.StringVar(value="Deal: Starter Deal")
        self.agent_var = tk.StringVar(value="Underwriter: detecting latest model...")
        self.status_var = tk.StringVar(value="Ready.")

        self._make_info_chip(strip, self.file_var).grid(row=0, column=0, sticky="w", padx=(0, 8))
        self._make_info_chip(strip, self.agent_var).grid(row=0, column=1, sticky="w", padx=(0, 8))
        self._make_info_chip(strip, self.status_var, accent=True).grid(row=0, column=2, sticky="e")

    def _build_builder_tab(self) -> None:
        self.builder_tab.grid_columnconfigure(0, weight=1)
        self.builder_tab.grid_rowconfigure(0, weight=1)

        panes = ttk.Panedwindow(self.builder_tab, orient="horizontal")
        panes.grid(row=0, column=0, sticky="nsew")

        left_host = tk.Frame(self.builder_tab, bg=COLORS["bg"])
        right_host = tk.Frame(self.builder_tab, bg=COLORS["bg"], width=340)
        left_host.grid_columnconfigure(0, weight=1)
        left_host.grid_rowconfigure(0, weight=1)
        right_host.grid_propagate(False)

        panes.add(left_host, weight=3)
        panes.add(right_host, weight=1)

        scroller = ScrollableFrame(left_host, bg=COLORS["bg"])
        scroller.grid(row=0, column=0, sticky="nsew")
        body = scroller.content
        body.grid_columnconfigure(0, weight=1)

        self._build_identity_section(body)
        self._build_land_section(body)
        self._build_schedule_section(body)
        self._build_series_section(body)
        self._build_operations_section(body)
        self._build_targets_section(body)
        self._build_market_section(body)
        self._build_notes_section(body)

        self._build_sidebar(right_host)
        self._attach_live_refresh_bindings()

    def _build_identity_section(self, parent: tk.Widget) -> None:
        body = self._create_section(
            parent,
            title="1. Community Snapshot",
            subtitle="Anchor the screen with the deal identity before you start tuning assumptions.",
        )
        body.grid_columnconfigure((0, 1, 2), weight=1)

        self._labeled_entry(body, "Community Name", "community_name", 0, 0, width=24)
        self._labeled_entry(body, "Division", "division", 0, 1, width=18)
        self._labeled_entry(body, "Market", "market", 0, 2, width=18)
        self._labeled_entry(body, "Gross Acres", "gross_acres", 1, 0, width=10)
        self._labeled_entry(body, "Land Close Date", "land_close_date", 1, 1, width=14)
        self._labeled_combo(
            body,
            "Takedown Structure",
            "takedown_structure",
            ("bulk", "takedown", "rolling"),
            1,
            2,
            width=14,
        )

    def _build_land_section(self, parent: tk.Widget) -> None:
        body = self._create_section(
            parent,
            title="2. Land Basis And Horizontal Spend",
            subtitle="Use a flat land price for quick screening, or let the phase plan below build the staged takedown automatically.",
        )
        body.grid_columnconfigure((0, 1, 2), weight=1)

        self._labeled_entry(body, "Land Price / Lot", "land_purchase_price_per_lot", 0, 0, width=12)
        self._labeled_entry(
            body,
            "Broker + Closing Costs",
            "land_brokerage_and_closing_costs_total",
            0,
            1,
            width=14,
        )
        self._labeled_entry(body, "Earnest Deposit", "earnest_money_deposit", 0, 2, width=14)
        self._labeled_checkbox(body, "Deposit Credits At Close", "deposit_credit_at_close", 1, 0)
        self._labeled_entry(body, "Land Development", "land_development_cost_total", 1, 1, width=14)
        self._labeled_entry(body, "Project Management", "project_management_cost_total", 1, 2, width=14)
        self._labeled_entry(body, "Other Land Costs", "other_land_costs_total", 2, 0, width=14)

    def _build_schedule_section(self, parent: tk.Widget) -> None:
        body = self._create_section(
            parent,
            title="3. Phase Schedule Builder",
            subtitle="Use phases to plan lot takedowns and see the timeline before you underwrite. Month 0 is the land close.",
        )
        body.grid_columnconfigure(0, weight=1)

        grid = tk.Frame(
            body,
            bg=COLORS["card_alt"],
            padx=12,
            pady=12,
            highlightbackground=COLORS["line"],
            highlightthickness=1,
        )
        grid.grid(row=0, column=0, sticky="ew")
        for col in range(len(PHASE_FIELDS)):
            grid.grid_columnconfigure(col, weight=1)

        for col, (_, label) in enumerate(PHASE_FIELDS):
            tk.Label(
                grid,
                text=label,
                bg=COLORS["card_alt"],
                fg=COLORS["navy"],
                font=("Segoe UI", 9, "bold"),
                padx=4,
                pady=6,
            ).grid(row=0, column=col, sticky="ew")

        for row_index in range(PHASE_ROW_COUNT):
            row_vars: dict[str, tk.Variable] = {}
            for col_index, (field_name, _) in enumerate(PHASE_FIELDS):
                default = f"Phase {row_index + 1}" if field_name == "name" else ""
                var = tk.StringVar(value=default)
                row_vars[field_name] = var
                entry = tk.Entry(
                    grid,
                    textvariable=var,
                    font=("Segoe UI", 10),
                    bg="#FFFDFC",
                    fg=COLORS["ink"],
                    relief="flat",
                    highlightthickness=1,
                    highlightbackground=COLORS["line"],
                    highlightcolor=COLORS["accent"],
                    width=18 if field_name == "name" else 10,
                )
                entry.grid(row=row_index + 1, column=col_index, sticky="ew", padx=3, pady=3, ipady=5)
            self.phase_rows.append(row_vars)

        chart_frame = tk.Frame(body, bg=COLORS["card"])
        chart_frame.grid(row=1, column=0, sticky="ew", pady=(12, 0))
        chart_frame.grid_columnconfigure(0, weight=1)
        tk.Label(
            chart_frame,
            text="Schedule Preview",
            bg=COLORS["card"],
            fg=COLORS["navy"],
            font=("Segoe UI", 10, "bold"),
        ).grid(row=0, column=0, sticky="w")
        self.builder_schedule_canvas = tk.Canvas(
            chart_frame,
            bg=COLORS["card"],
            height=170,
            highlightthickness=1,
            highlightbackground=COLORS["line"],
        )
        self.builder_schedule_canvas.grid(row=1, column=0, sticky="ew", pady=(6, 0))

        raw_frame = tk.Frame(body, bg=COLORS["card"])
        raw_frame.grid(row=2, column=0, sticky="ew", pady=(12, 0))
        raw_frame.grid_columnconfigure(0, weight=1)
        tk.Label(
            raw_frame,
            text="Paste-In Schedule",
            bg=COLORS["card"],
            fg=COLORS["ink"],
            font=("Segoe UI", 10, "bold"),
        ).grid(row=0, column=0, sticky="w")
        tk.Label(
            raw_frame,
            text="Optional. Use only when you need a quick paste or a one-off override: month,lots,price_per_lot",
            bg=COLORS["card"],
            fg=COLORS["muted"],
            font=("Segoe UI", 9),
        ).grid(row=1, column=0, sticky="w", pady=(2, 6))
        self.events_text = ScrolledText(
            raw_frame,
            height=3,
            wrap="none",
            font=("Consolas", 10),
            bg="#FFFDFC",
            fg=COLORS["ink"],
            insertbackground=COLORS["ink"],
            relief="flat",
            borderwidth=1,
        )
        self.events_text.grid(row=2, column=0, sticky="ew")

    def _build_market_section(self, parent: tk.Widget) -> None:
        body = self._create_section(
            parent,
            title="7. Market Intelligence And CMA",
            subtitle="Benchmark price, pace, and resale support. This becomes part of the recommendation, not just a side note.",
        )
        body.grid_columnconfigure((0, 1), weight=1)

        competitor_frame = tk.Frame(
            body,
            bg=COLORS["card_alt"],
            padx=12,
            pady=12,
            highlightbackground=COLORS["line"],
            highlightthickness=1,
        )
        competitor_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        competitor_frame.grid_columnconfigure(0, weight=1)
        for col in range(len(COMPETITOR_FIELDS)):
            competitor_frame.grid_columnconfigure(col, weight=1)
        tk.Label(
            competitor_frame,
            text="Competitor Communities",
            bg=COLORS["card_alt"],
            fg=COLORS["navy"],
            font=("Segoe UI", 10, "bold"),
        ).grid(row=0, column=0, sticky="w", columnspan=len(COMPETITOR_FIELDS))

        for col, (_, label) in enumerate(COMPETITOR_FIELDS):
            tk.Label(
                competitor_frame,
                text=label,
                bg=COLORS["card_alt"],
                fg=COLORS["navy"],
                font=("Segoe UI", 9, "bold"),
                padx=3,
                pady=6,
            ).grid(row=1, column=col, sticky="ew")

        for row_index in range(COMPETITOR_ROW_COUNT):
            row_vars: dict[str, tk.Variable] = {}
            for col_index, (field_name, _) in enumerate(COMPETITOR_FIELDS):
                var = tk.StringVar()
                row_vars[field_name] = var
                entry = tk.Entry(
                    competitor_frame,
                    textvariable=var,
                    font=("Segoe UI", 9),
                    bg="#FFFDFC",
                    fg=COLORS["ink"],
                    relief="flat",
                    highlightthickness=1,
                    highlightbackground=COLORS["line"],
                    highlightcolor=COLORS["accent"],
                    width=16 if field_name in {"name", "status"} else 10,
                )
                entry.grid(row=row_index + 2, column=col_index, sticky="ew", padx=3, pady=3, ipady=4)
            self.competitor_rows.append(row_vars)

        resale_frame = tk.Frame(
            body,
            bg=COLORS["card_alt"],
            padx=12,
            pady=12,
            highlightbackground=COLORS["line"],
            highlightthickness=1,
        )
        resale_frame.grid(row=0, column=1, sticky="nsew", padx=(8, 0))
        resale_frame.grid_columnconfigure(0, weight=1)
        for col in range(len(RESALE_FIELDS)):
            resale_frame.grid_columnconfigure(col, weight=1)
        tk.Label(
            resale_frame,
            text="Resale Comps",
            bg=COLORS["card_alt"],
            fg=COLORS["navy"],
            font=("Segoe UI", 10, "bold"),
        ).grid(row=0, column=0, sticky="w", columnspan=len(RESALE_FIELDS))

        for col, (_, label) in enumerate(RESALE_FIELDS):
            tk.Label(
                resale_frame,
                text=label,
                bg=COLORS["card_alt"],
                fg=COLORS["navy"],
                font=("Segoe UI", 9, "bold"),
                padx=3,
                pady=6,
            ).grid(row=1, column=col, sticky="ew")

        for row_index in range(RESALE_ROW_COUNT):
            row_vars = {}
            for col_index, (field_name, _) in enumerate(RESALE_FIELDS):
                var = tk.StringVar()
                row_vars[field_name] = var
                entry = tk.Entry(
                    resale_frame,
                    textvariable=var,
                    font=("Segoe UI", 9),
                    bg="#FFFDFC",
                    fg=COLORS["ink"],
                    relief="flat",
                    highlightthickness=1,
                    highlightbackground=COLORS["line"],
                    highlightcolor=COLORS["accent"],
                    width=16 if field_name in {"name", "close_date"} else 10,
                )
                entry.grid(row=row_index + 2, column=col_index, sticky="ew", padx=3, pady=3, ipady=4)
            self.resale_rows.append(row_vars)

    def _build_series_section(self, parent: tk.Widget) -> None:
        body = self._create_section(
            parent,
            title="4. Product Mix Builder",
            subtitle="Rows with zero lots are ignored. Keep the mix focused and let the workspace handle the behind-the-scenes structure.",
        )
        body.grid_columnconfigure(0, weight=1)

        globals_frame = tk.Frame(body, bg=COLORS["card"])
        globals_frame.grid(row=0, column=0, sticky="ew")
        globals_frame.grid_columnconfigure((0, 1, 2), weight=1)

        self._labeled_entry(globals_frame, "Options %", "options_pct", 0, 0, width=10)
        self._labeled_entry(globals_frame, "Price Incentives %", "price_incentives_pct", 0, 1, width=10)
        self._labeled_entry(globals_frame, "Mortgage Incentives %", "mortgage_incentives_pct", 0, 2, width=10)
        self._labeled_entry(
            globals_frame,
            "Direct Cost Contingency %",
            "direct_cost_contingency_pct",
            1,
            0,
            width=10,
        )
        self._labeled_entry(
            globals_frame,
            "Other Vertical / Unit",
            "other_vertical_costs_per_unit",
            1,
            1,
            width=12,
        )
        self._labeled_entry(
            globals_frame,
            "Other House Costs / Unit",
            "other_house_costs_per_unit",
            1,
            2,
            width=12,
        )

        grid = tk.Frame(body, bg=COLORS["card_alt"], padx=12, pady=12, highlightbackground=COLORS["line"], highlightthickness=1)
        grid.grid(row=1, column=0, sticky="ew", pady=(14, 0))

        for col, (_, label) in enumerate(SERIES_FIELDS):
            tk.Label(
                grid,
                text=label,
                bg=COLORS["card_alt"],
                fg=COLORS["navy"],
                font=("Segoe UI", 9, "bold"),
                padx=4,
                pady=6,
            ).grid(row=0, column=col, sticky="ew")
        tk.Label(
            grid,
            text="Move-Up",
            bg=COLORS["card_alt"],
            fg=COLORS["navy"],
            font=("Segoe UI", 9, "bold"),
            padx=4,
            pady=6,
        ).grid(row=0, column=len(SERIES_FIELDS), sticky="ew")

        for row_index in range(SERIES_ROW_COUNT):
            row_vars: dict[str, tk.Variable] = {}
            for col_index, (field_name, _) in enumerate(SERIES_FIELDS):
                default = f"Series {chr(65 + row_index)}" if field_name == "name" else ""
                var = tk.StringVar(value=default)
                row_vars[field_name] = var
                entry = tk.Entry(
                    grid,
                    textvariable=var,
                    font=("Segoe UI", 10),
                    bg="#FFFDFC",
                    fg=COLORS["ink"],
                    relief="flat",
                    highlightthickness=1,
                    highlightbackground=COLORS["line"],
                    highlightcolor=COLORS["accent"],
                    width=12 if field_name == "name" else 10,
                )
                entry.grid(row=row_index + 1, column=col_index, sticky="ew", padx=3, pady=3, ipady=5)
            move_var = tk.BooleanVar(value=False)
            row_vars["move_up"] = move_var
            check = tk.Checkbutton(
                grid,
                variable=move_var,
                bg=COLORS["card_alt"],
                activebackground=COLORS["card_alt"],
                selectcolor=COLORS["card_alt"],
            )
            check.grid(row=row_index + 1, column=len(SERIES_FIELDS), padx=6)
            self.series_rows.append(row_vars)

    def _build_operations_section(self, parent: tk.Widget) -> None:
        body = self._create_section(
            parent,
            title="5. Operating Plan",
            subtitle="These timing assumptions drive the schedule, cash curve, and stress-case velocity.",
        )
        body.grid_columnconfigure((0, 1, 2), weight=1)

        self._labeled_entry(body, "Architecture + Engineering", "architecture_engineering_total", 0, 0, width=14)
        self._labeled_entry(body, "Indirect Overhead / Month", "indirect_field_overhead_per_month", 0, 1, width=14)
        self._labeled_entry(body, "Capitalized Marketing", "capitalized_marketing_total", 0, 2, width=14)
        self._labeled_entry(body, "Monthly Absorption", "monthly_absorption", 1, 0, width=10)
        self._labeled_entry(body, "Build Cycle (Months)", "build_cycle_months", 1, 1, width=10)
        self._labeled_entry(body, "Months To First Home Start", "months_to_first_home_start", 1, 2, width=10)
        self._labeled_entry(body, "Months To Sales Open", "months_to_sales_open", 2, 0, width=10)
        self._labeled_entry(body, "Months To First Close", "months_to_first_close", 2, 1, width=10)
        self._labeled_entry(body, "Site Spend Months", "site_improvement_spend_months", 2, 2, width=10)

    def _build_targets_section(self, parent: tk.Widget) -> None:
        body = self._create_section(
            parent,
            title="6. Returns And Stress Cases",
            subtitle="Set the decision hurdles and the downside assumptions you want the agent to pressure-test.",
        )
        body.grid_columnconfigure((0, 1, 2), weight=1)

        self._labeled_entry(body, "Sales Commission %", "sales_commission_pct", 0, 0, width=10)
        self._labeled_entry(body, "Corporate Charge %", "corporate_charge_pct", 0, 1, width=10)
        self._labeled_entry(body, "Excise Tax %", "home_sale_excise_tax_pct", 0, 2, width=10)
        self._labeled_entry(body, "Target Gross Margin %", "target_gross_margin_pct", 1, 0, width=10)
        self._labeled_entry(body, "Target Pre-G&A %", "target_pre_gna_margin_pct", 1, 1, width=10)
        self._labeled_entry(body, "Target IRR %", "target_irr_pct", 1, 2, width=10)

        tk.Label(
            body,
            text="Downside",
            bg=COLORS["card"],
            fg=COLORS["navy"],
            font=("Segoe UI", 10, "bold"),
        ).grid(row=2, column=0, sticky="w", pady=(12, 4))
        tk.Label(
            body,
            text="Severe Downside",
            bg=COLORS["card"],
            fg=COLORS["navy"],
            font=("Segoe UI", 10, "bold"),
        ).grid(row=2, column=1, sticky="w", pady=(12, 4))

        self._labeled_entry(body, "Sales Price %", "downside_sales_price_delta_pct", 3, 0, width=10)
        self._labeled_entry(body, "Cost %", "downside_cost_delta_pct", 4, 0, width=10)
        self._labeled_entry(body, "Absorption %", "downside_absorption_delta_pct", 5, 0, width=10)
        self._labeled_entry(body, "Sales Price %", "severe_downside_sales_price_delta_pct", 3, 1, width=10)
        self._labeled_entry(body, "Cost %", "severe_downside_cost_delta_pct", 4, 1, width=10)
        self._labeled_entry(body, "Absorption %", "severe_downside_absorption_delta_pct", 5, 1, width=10)

    def _build_notes_section(self, parent: tk.Widget) -> None:
        body = self._create_section(
            parent,
            title="8. Notes And Diligence Signals",
            subtitle="Paste the deal narrative, red flags, or broker notes. The agent scans this text for risk and upside cues.",
        )
        body.grid_columnconfigure(0, weight=1)
        self.notes_text = ScrolledText(
            body,
            height=7,
            wrap="word",
            font=("Segoe UI", 10),
            bg="#FFFDFC",
            fg=COLORS["ink"],
            insertbackground=COLORS["ink"],
            relief="flat",
            borderwidth=1,
        )
        self.notes_text.grid(row=0, column=0, sticky="ew")

    def _build_sidebar(self, parent: tk.Widget) -> None:
        parent.configure(bg=COLORS["bg"])
        panel = tk.Frame(parent, bg=COLORS["card"], padx=16, pady=16, highlightbackground=COLORS["line"], highlightthickness=1)
        panel.pack(fill="both", expand=True)

        tk.Label(
            panel,
            text="Live Deal Snapshot",
            bg=COLORS["card"],
            fg=COLORS["ink"],
            font=("Aptos", 14, "bold"),
        ).pack(anchor="w")
        tk.Label(
            panel,
            text="This updates as you build the deal so you can spot broken assumptions before you run the underwrite.",
            bg=COLORS["card"],
            fg=COLORS["muted"],
            font=("Segoe UI", 9),
            justify="left",
            wraplength=280,
        ).pack(anchor="w", pady=(4, 14))

        self.overview_cards: dict[str, tuple[tk.Label, tk.Label]] = {}
        for key, title in (
            ("lots", "Total Lots"),
            ("density", "Density"),
            ("revenue", "Rough Revenue"),
            ("land_basis", "Land Basis"),
            ("site_spend", "Horizontal Spend"),
            ("absorption", "Absorption"),
            ("market_price", "Price Position"),
            ("market_pace", "Pace Position"),
        ):
            card = tk.Frame(panel, bg=COLORS["card_alt"], padx=12, pady=10, highlightbackground=COLORS["line"], highlightthickness=1)
            card.pack(fill="x", pady=(0, 10))
            tk.Label(card, text=title, bg=COLORS["card_alt"], fg=COLORS["muted"], font=("Segoe UI", 9, "bold")).pack(anchor="w")
            value = tk.Label(card, text="-", bg=COLORS["card_alt"], fg=COLORS["ink"], font=("Aptos", 16, "bold"))
            value.pack(anchor="w", pady=(4, 0))
            note = tk.Label(card, text="", bg=COLORS["card_alt"], fg=COLORS["muted"], font=("Segoe UI", 9))
            note.pack(anchor="w")
            self.overview_cards[key] = (value, note)

        self.health_card = tk.Frame(
            panel,
            bg=COLORS["navy"],
            padx=12,
            pady=12,
            highlightbackground=COLORS["navy"],
            highlightthickness=1,
        )
        self.health_card.pack(fill="x", pady=(0, 10))
        tk.Label(
            self.health_card,
            text="Deal Readiness",
            bg=COLORS["navy"],
            fg="#D8E6EF",
            font=("Segoe UI", 9, "bold"),
        ).pack(anchor="w")
        self.health_value_label = tk.Label(
            self.health_card,
            text="0",
            bg=COLORS["navy"],
            fg="white",
            font=("Aptos Display", 28, "bold"),
        )
        self.health_value_label.pack(anchor="w", pady=(4, 0))
        self.health_note_label = tk.Label(
            self.health_card,
            text="Complete the core assumptions to get a live quality score.",
            bg=COLORS["navy"],
            fg="#D8E6EF",
            font=("Segoe UI", 9),
            justify="left",
            wraplength=280,
        )
        self.health_note_label.pack(anchor="w", pady=(2, 0))

        diagnostics = tk.Frame(
            panel,
            bg=COLORS["card_alt"],
            padx=12,
            pady=12,
            highlightbackground=COLORS["line"],
            highlightthickness=1,
        )
        diagnostics.pack(fill="x", pady=(0, 10))
        tk.Label(
            diagnostics,
            text="Live Diagnostics",
            bg=COLORS["card_alt"],
            fg=COLORS["navy"],
            font=("Segoe UI", 10, "bold"),
        ).pack(anchor="w")
        self.diagnostics_text = ScrolledText(
            diagnostics,
            height=8,
            wrap="word",
            font=("Segoe UI", 9),
            bg="#FFFDFC",
            fg=COLORS["ink"],
            relief="flat",
            borderwidth=1,
        )
        self.diagnostics_text.pack(fill="x", pady=(8, 0))
        self.diagnostics_text.configure(state="disabled")

        quick_actions = tk.Frame(
            panel,
            bg=COLORS["card_alt"],
            padx=12,
            pady=12,
            highlightbackground=COLORS["line"],
            highlightthickness=1,
        )
        quick_actions.pack(fill="x", pady=(0, 10))
        tk.Label(
            quick_actions,
            text="Quick Actions",
            bg=COLORS["card_alt"],
            fg=COLORS["navy"],
            font=("Segoe UI", 10, "bold"),
        ).pack(anchor="w")
        self._make_button(quick_actions, "Auto-Build Phases", self._auto_build_phases, "secondary").pack(fill="x", pady=(8, 6))
        self._make_button(quick_actions, "Match Pace To Market", self._balance_absorption_to_market, "secondary").pack(fill="x", pady=(0, 6))
        self._make_button(quick_actions, "Run Underwrite", self._run_active_request, "primary").pack(fill="x")

        tips = tk.Frame(panel, bg=COLORS["accent_soft"], padx=12, pady=12, highlightbackground="#E5C9B6", highlightthickness=1)
        tips.pack(fill="both", expand=True)
        tk.Label(tips, text="Workflow", bg=COLORS["accent_soft"], fg=COLORS["navy"], font=("Segoe UI", 10, "bold")).pack(anchor="w")
        guidance = (
            "1. Use the builder for fast screening.\n"
            "2. Use Auto-Build Phases when you want a quick takedown structure.\n"
            "3. Press Ctrl+R to run, Ctrl+S to save, Ctrl+O to open.\n"
            "4. Review the Decision Center before deciding whether to pursue, negotiate, or pass."
        )
        tk.Label(
            tips,
            text=guidance,
            bg=COLORS["accent_soft"],
            fg=COLORS["ink"],
            font=("Segoe UI", 9),
            justify="left",
            wraplength=280,
        ).pack(anchor="w", pady=(8, 0))

    def _build_results_tab(self) -> None:
        self.results_tab.grid_columnconfigure(0, weight=1)
        self.results_tab.grid_rowconfigure(2, weight=1)

        self.banner_frame = tk.Frame(self.results_tab, bg=COLORS["card"], padx=18, pady=16, highlightbackground=COLORS["line"], highlightthickness=1)
        self.banner_frame.grid(row=0, column=0, sticky="ew")
        self.banner_frame.grid_columnconfigure(0, weight=1)

        self.recommendation_label = tk.Label(
            self.banner_frame,
            text="Run an underwrite to see the decision.",
            bg=COLORS["card"],
            fg=COLORS["navy"],
            font=("Aptos Display", 20, "bold"),
        )
        self.recommendation_label.grid(row=0, column=0, sticky="w")
        self.recommendation_subtitle = tk.Label(
            self.banner_frame,
            text="The dashboard will summarize the recommendation, scenario spread, and key hurdle failures.",
            bg=COLORS["card"],
            fg=COLORS["muted"],
            font=("Segoe UI", 10),
        )
        self.recommendation_subtitle.grid(row=1, column=0, sticky="w", pady=(6, 0))

        metrics_row = tk.Frame(self.results_tab, bg=COLORS["bg"])
        metrics_row.grid(row=1, column=0, sticky="ew", pady=(12, 12))
        for idx in range(5):
            metrics_row.grid_columnconfigure(idx, weight=1)

        self.metric_cards: dict[str, tuple[tk.Frame, tk.Label, tk.Label]] = {}
        for idx, (key, title) in enumerate(
            (
                ("gross_margin", "Base Gross Margin"),
                ("pre_gna", "Base Pre-G&A"),
                ("irr", "Base IRR"),
                ("residual", "Residual Land / Lot"),
                ("peak", "Peak Investment"),
            )
        ):
            frame = tk.Frame(metrics_row, bg=COLORS["card"], padx=14, pady=12, highlightbackground=COLORS["line"], highlightthickness=1)
            frame.grid(row=0, column=idx, sticky="nsew", padx=(0 if idx == 0 else 8, 0))
            tk.Label(frame, text=title, bg=COLORS["card"], fg=COLORS["muted"], font=("Segoe UI", 9, "bold")).pack(anchor="w")
            value = tk.Label(frame, text="-", bg=COLORS["card"], fg=COLORS["ink"], font=("Aptos", 18, "bold"))
            value.pack(anchor="w", pady=(4, 0))
            note = tk.Label(frame, text="", bg=COLORS["card"], fg=COLORS["muted"], font=("Segoe UI", 9))
            note.pack(anchor="w")
            self.metric_cards[key] = (frame, value, note)

        main = ttk.Panedwindow(self.results_tab, orient="horizontal")
        main.grid(row=2, column=0, sticky="nsew")

        left = tk.Frame(self.results_tab, bg=COLORS["bg"])
        right = tk.Frame(self.results_tab, bg=COLORS["bg"])
        left.grid_columnconfigure(0, weight=1)
        left.grid_rowconfigure(1, weight=1)
        right.grid_columnconfigure(0, weight=1)
        right.grid_rowconfigure(0, weight=1)
        main.add(left, weight=3)
        main.add(right, weight=2)

        tk.Label(left, text="Scenario Spread", bg=COLORS["bg"], fg=COLORS["navy"], font=("Segoe UI", 11, "bold")).grid(row=0, column=0, sticky="w", pady=(0, 6))
        self.scenario_tree = ttk.Treeview(
            left,
            columns=("scenario", "gross", "pre_gna", "irr", "residual_gap", "peak"),
            show="headings",
            height=8,
        )
        for key, label, width in (
            ("scenario", "Scenario", 120),
            ("gross", "Gross Margin", 120),
            ("pre_gna", "Pre-G&A", 120),
            ("irr", "IRR", 100),
            ("residual_gap", "Land Gap", 120),
            ("peak", "Peak Inv.", 120),
        ):
            self.scenario_tree.heading(key, text=label)
            self.scenario_tree.column(key, width=width, anchor="center")
        self.scenario_tree.grid(row=1, column=0, sticky="nsew")

        tk.Label(left, text="Pre-G&A Margin Chart", bg=COLORS["bg"], fg=COLORS["navy"], font=("Segoe UI", 11, "bold")).grid(row=2, column=0, sticky="w", pady=(14, 6))
        self.chart_canvas = tk.Canvas(left, bg=COLORS["card"], height=220, highlightthickness=1, highlightbackground=COLORS["line"])
        self.chart_canvas.grid(row=3, column=0, sticky="ew")

        right_tabs = ttk.Notebook(right)
        right_tabs.grid(row=0, column=0, sticky="nsew")

        decision_tab = tk.Frame(right_tabs, bg=COLORS["bg"])
        series_tab = tk.Frame(right_tabs, bg=COLORS["bg"])
        market_tab = tk.Frame(right_tabs, bg=COLORS["bg"])
        sensitivity_tab = tk.Frame(right_tabs, bg=COLORS["bg"])
        memo_tab = tk.Frame(right_tabs, bg=COLORS["bg"])
        detail_tab = tk.Frame(right_tabs, bg=COLORS["bg"])
        right_tabs.add(decision_tab, text="Decision")
        right_tabs.add(series_tab, text="Series + Schedule")
        right_tabs.add(market_tab, text="Market / CMA")
        right_tabs.add(sensitivity_tab, text="Sensitivity")
        right_tabs.add(memo_tab, text="IC Memo")
        right_tabs.add(detail_tab, text="Deep Dive")

        self._build_decision_tab(decision_tab)
        self._build_series_tab(series_tab)
        self._build_market_tab(market_tab)
        self._build_sensitivity_tab(sensitivity_tab)
        self._build_memo_tab(memo_tab)
        self._build_raw_result_tab(detail_tab)

    def _build_decision_tab(self, parent: tk.Widget) -> None:
        parent.grid_columnconfigure(0, weight=1)
        parent.grid_rowconfigure(1, weight=1)
        parent.grid_rowconfigure(3, weight=1)

        tk.Label(parent, text="Recommendation Reasons", bg=COLORS["bg"], fg=COLORS["navy"], font=("Segoe UI", 10, "bold")).grid(row=0, column=0, sticky="w", pady=(6, 4))
        self.decision_text = ScrolledText(
            parent,
            height=8,
            wrap="word",
            font=("Segoe UI", 10),
            bg=COLORS["card"],
            fg=COLORS["ink"],
            relief="flat",
            borderwidth=1,
        )
        self.decision_text.grid(row=1, column=0, sticky="nsew")
        self.decision_text.configure(state="disabled")

        tk.Label(parent, text="Hurdle Grid", bg=COLORS["bg"], fg=COLORS["navy"], font=("Segoe UI", 10, "bold")).grid(row=2, column=0, sticky="w", pady=(12, 4))
        self.hurdle_tree = ttk.Treeview(
            parent,
            columns=("scenario", "gross", "pre_gna", "irr", "residual"),
            show="headings",
            height=6,
        )
        for key, label, width in (
            ("scenario", "Scenario", 120),
            ("gross", "Gross", 80),
            ("pre_gna", "Pre-G&A", 90),
            ("irr", "IRR", 80),
            ("residual", "Residual", 90),
        ):
            self.hurdle_tree.heading(key, text=label)
            self.hurdle_tree.column(key, width=width, anchor="center")
        self.hurdle_tree.grid(row=3, column=0, sticky="nsew")

    def _build_series_tab(self, parent: tk.Widget) -> None:
        parent.grid_columnconfigure(0, weight=1)
        parent.grid_rowconfigure(1, weight=1)
        parent.grid_rowconfigure(3, weight=0)
        parent.grid_rowconfigure(5, weight=1)

        tk.Label(parent, text="Base-Case Series Mix", bg=COLORS["bg"], fg=COLORS["navy"], font=("Segoe UI", 10, "bold")).grid(row=0, column=0, sticky="w", pady=(6, 4))
        self.series_tree = ttk.Treeview(
            parent,
            columns=("name", "lots", "mix", "asp", "build", "revenue"),
            show="headings",
            height=6,
        )
        for key, label, width in (
            ("name", "Series", 120),
            ("lots", "Lots", 70),
            ("mix", "Mix", 70),
            ("asp", "Net ASP", 110),
            ("build", "Build / Unit", 110),
            ("revenue", "Revenue", 120),
        ):
            self.series_tree.heading(key, text=label)
            self.series_tree.column(key, width=width, anchor="center")
        self.series_tree.grid(row=1, column=0, sticky="nsew")

        tk.Label(parent, text="Schedule Timeline", bg=COLORS["bg"], fg=COLORS["navy"], font=("Segoe UI", 10, "bold")).grid(row=2, column=0, sticky="w", pady=(12, 4))
        self.result_schedule_canvas = tk.Canvas(
            parent,
            bg=COLORS["card"],
            height=170,
            highlightthickness=1,
            highlightbackground=COLORS["line"],
        )
        self.result_schedule_canvas.grid(row=3, column=0, sticky="ew")

        tk.Label(parent, text="Base-Case Schedule Summary", bg=COLORS["bg"], fg=COLORS["navy"], font=("Segoe UI", 10, "bold")).grid(row=4, column=0, sticky="w", pady=(12, 4))
        self.schedule_text = ScrolledText(
            parent,
            height=10,
            wrap="word",
            font=("Segoe UI", 10),
            bg=COLORS["card"],
            fg=COLORS["ink"],
            relief="flat",
            borderwidth=1,
        )
        self.schedule_text.grid(row=5, column=0, sticky="nsew")
        self.schedule_text.configure(state="disabled")

    def _build_market_tab(self, parent: tk.Widget) -> None:
        parent.grid_columnconfigure(0, weight=1)
        parent.grid_rowconfigure(1, weight=0)
        parent.grid_rowconfigure(3, weight=1)
        parent.grid_rowconfigure(5, weight=1)

        tk.Label(
            parent,
            text="Market Readout",
            bg=COLORS["bg"],
            fg=COLORS["navy"],
            font=("Segoe UI", 10, "bold"),
        ).grid(row=0, column=0, sticky="w", pady=(6, 4))
        self.market_text = ScrolledText(
            parent,
            height=8,
            wrap="word",
            font=("Segoe UI", 10),
            bg=COLORS["card"],
            fg=COLORS["ink"],
            relief="flat",
            borderwidth=1,
        )
        self.market_text.grid(row=1, column=0, sticky="ew")
        self.market_text.configure(state="disabled")

        tk.Label(
            parent,
            text="Revenue Velocity",
            bg=COLORS["bg"],
            fg=COLORS["navy"],
            font=("Segoe UI", 10, "bold"),
        ).grid(row=2, column=0, sticky="w", pady=(12, 4))
        self.market_revenue_canvas = tk.Canvas(
            parent,
            bg=COLORS["card"],
            height=190,
            highlightthickness=1,
            highlightbackground=COLORS["line"],
        )
        self.market_revenue_canvas.grid(row=3, column=0, sticky="nsew")

        tk.Label(
            parent,
            text="Resale Price / Sqft",
            bg=COLORS["bg"],
            fg=COLORS["navy"],
            font=("Segoe UI", 10, "bold"),
        ).grid(row=4, column=0, sticky="w", pady=(12, 4))
        self.market_resale_canvas = tk.Canvas(
            parent,
            bg=COLORS["card"],
            height=210,
            highlightthickness=1,
            highlightbackground=COLORS["line"],
        )
        self.market_resale_canvas.grid(row=5, column=0, sticky="nsew")

    def _build_sensitivity_tab(self, parent: tk.Widget) -> None:
        parent.grid_columnconfigure(0, weight=1)
        parent.grid_rowconfigure(1, weight=1)
        parent.grid_rowconfigure(3, weight=0)

        tk.Label(
            parent,
            text="Price / Cost Sensitivity",
            bg=COLORS["bg"],
            fg=COLORS["navy"],
            font=("Segoe UI", 10, "bold"),
        ).grid(row=0, column=0, sticky="w", pady=(6, 4))
        self.sensitivity_canvas = tk.Canvas(
            parent,
            bg=COLORS["card"],
            height=260,
            highlightthickness=1,
            highlightbackground=COLORS["line"],
        )
        self.sensitivity_canvas.grid(row=1, column=0, sticky="nsew")
        tk.Label(
            parent,
            text="Each cell shows pre-G&A margin under a price / cost move. Green clears hurdles, amber is watch, red fails.",
            bg=COLORS["bg"],
            fg=COLORS["muted"],
            font=("Segoe UI", 9),
            wraplength=360,
            justify="left",
        ).grid(row=2, column=0, sticky="w", pady=(8, 0))
        self.sensitivity_summary_label = tk.Label(
            parent,
            text="",
            bg=COLORS["bg"],
            fg=COLORS["ink"],
            font=("Segoe UI", 9),
            justify="left",
            wraplength=360,
        )
        self.sensitivity_summary_label.grid(row=3, column=0, sticky="w", pady=(6, 0))

    def _build_memo_tab(self, parent: tk.Widget) -> None:
        parent.grid_columnconfigure(0, weight=1)
        parent.grid_rowconfigure(1, weight=1)

        toolbar = tk.Frame(parent, bg=COLORS["bg"])
        toolbar.grid(row=0, column=0, sticky="ew", pady=(6, 4))
        self._make_button(toolbar, "Copy Memo", self._copy_ic_memo, "primary").grid(row=0, column=0, sticky="w")

        self.memo_text = ScrolledText(
            parent,
            wrap="word",
            font=("Segoe UI", 10),
            bg=COLORS["card"],
            fg=COLORS["ink"],
            relief="flat",
            borderwidth=1,
        )
        self.memo_text.grid(row=1, column=0, sticky="nsew")
        self.memo_text.configure(state="disabled")

    def _build_raw_result_tab(self, parent: tk.Widget) -> None:
        parent.grid_columnconfigure(0, weight=1)
        parent.grid_rowconfigure(0, weight=1)
        self.raw_result_text = ScrolledText(
            parent,
            wrap="word",
            font=("Segoe UI", 10),
            bg=COLORS["card"],
            fg=COLORS["ink"],
            insertbackground=COLORS["ink"],
            relief="flat",
            borderwidth=1,
        )
        self.raw_result_text.grid(row=0, column=0, sticky="nsew")
        self.raw_result_text.configure(state="disabled")

    def _create_section(self, parent: tk.Widget, *, title: str, subtitle: str) -> tk.Frame:
        card = tk.Frame(parent, bg=COLORS["card"], padx=16, pady=14, highlightbackground=COLORS["line"], highlightthickness=1)
        card.pack(fill="x", pady=(0, 14))
        tk.Label(card, text=title, bg=COLORS["card"], fg=COLORS["navy"], font=("Aptos", 14, "bold")).pack(anchor="w")
        tk.Label(card, text=subtitle, bg=COLORS["card"], fg=COLORS["muted"], font=("Segoe UI", 9), justify="left", wraplength=980).pack(anchor="w", pady=(4, 10))
        body = tk.Frame(card, bg=COLORS["card"])
        body.pack(fill="x")
        return body

    def _make_button(self, parent: tk.Widget, text: str, command: Any, variant: str) -> tk.Button:
        if variant == "primary":
            bg = COLORS["accent"]
            fg = "white"
            active = "#B45D30"
        else:
            bg = COLORS["card"]
            fg = COLORS["navy"]
            active = COLORS["card_alt"]
        return tk.Button(
            parent,
            text=text,
            command=command,
            bg=bg,
            fg=fg,
            activebackground=active,
            activeforeground=fg,
            relief="flat",
            borderwidth=0,
            padx=14,
            pady=8,
            font=("Segoe UI", 10, "bold"),
            cursor="hand2",
        )

    def _make_info_chip(self, parent: tk.Widget, variable: tk.StringVar, accent: bool = False) -> tk.Frame:
        chip = tk.Frame(
            parent,
            bg=COLORS["accent_soft"] if accent else COLORS["card"],
            padx=10,
            pady=6,
            highlightbackground="#E5C9B6" if accent else COLORS["line"],
            highlightthickness=1,
        )
        tk.Label(
            chip,
            textvariable=variable,
            bg=chip["bg"],
            fg=COLORS["ink"],
            font=("Segoe UI", 9),
        ).pack()
        return chip

    def _labeled_entry(self, parent: tk.Widget, label: str, key: str, row: int, column: int, *, width: int) -> None:
        container = tk.Frame(parent, bg=COLORS["card"])
        container.grid(row=row, column=column, sticky="ew", padx=(0 if column == 0 else 10, 0), pady=(0, 10))
        tk.Label(container, text=label, bg=COLORS["card"], fg=COLORS["muted"], font=("Segoe UI", 9, "bold")).pack(anchor="w")
        var = self.form_vars.setdefault(key, tk.StringVar())
        entry = tk.Entry(
            container,
            textvariable=var,
            font=("Segoe UI", 10),
            bg="#FFFDFC",
            fg=COLORS["ink"],
            relief="flat",
            highlightthickness=1,
            highlightbackground=COLORS["line"],
            highlightcolor=COLORS["accent"],
            width=width,
        )
        entry.pack(fill="x", ipady=5, pady=(4, 0))

    def _labeled_combo(
        self,
        parent: tk.Widget,
        label: str,
        key: str,
        values: tuple[str, ...],
        row: int,
        column: int,
        *,
        width: int,
    ) -> None:
        container = tk.Frame(parent, bg=COLORS["card"])
        container.grid(row=row, column=column, sticky="ew", padx=(0 if column == 0 else 10, 0), pady=(0, 10))
        tk.Label(container, text=label, bg=COLORS["card"], fg=COLORS["muted"], font=("Segoe UI", 9, "bold")).pack(anchor="w")
        var = self.form_vars.setdefault(key, tk.StringVar())
        combo = ttk.Combobox(container, textvariable=var, values=values, width=width, state="readonly")
        combo.pack(fill="x", pady=(4, 0))

    def _labeled_checkbox(self, parent: tk.Widget, label: str, key: str, row: int, column: int) -> None:
        var = self.form_vars.setdefault(key, tk.BooleanVar(value=False))
        check = tk.Checkbutton(
            parent,
            text=label,
            variable=var,
            bg=COLORS["card"],
            activebackground=COLORS["card"],
            selectcolor=COLORS["card"],
            fg=COLORS["ink"],
            font=("Segoe UI", 10),
        )
        check.grid(row=row, column=column, sticky="w", pady=(8, 10))

    def _bind_shortcuts(self) -> None:
        self.root.bind("<Control-r>", lambda event: self._run_active_request())
        self.root.bind("<Control-s>", lambda event: self._save_request_file())
        self.root.bind("<Control-o>", lambda event: self._open_request_file())
        self.root.bind("<Control-l>", lambda event: self._load_sample_request())
        self.root.bind("<F5>", lambda event: self._run_active_request())

    def _attach_live_refresh_bindings(self) -> None:
        for variable in self.form_vars.values():
            variable.trace_add("write", lambda *_: self._schedule_refresh())

        for row in self.series_rows:
            for variable in row.values():
                variable.trace_add("write", lambda *_: self._schedule_refresh())

        for row_group in (self.phase_rows, self.competitor_rows, self.resale_rows):
            for row in row_group:
                for variable in row.values():
                    variable.trace_add("write", lambda *_: self._schedule_refresh())

        for widget in (self.notes_text, self.events_text):
            widget.bind("<KeyRelease>", lambda event: self._schedule_refresh())
            widget.bind("<FocusOut>", lambda event: self._schedule_refresh())
            widget.bind("<<Paste>>", lambda event: self.root.after(25, self._schedule_refresh))

        self._schedule_refresh()

    def _schedule_refresh(self) -> None:
        if self.refresh_job is not None:
            self.root.after_cancel(self.refresh_job)
        self.refresh_job = self.root.after(180, self._refresh_builder_overview)

    def _refresh_builder_overview(self) -> None:
        self.refresh_job = None
        payload = self._request_from_form(strict=False)
        series = payload.get("product_series", [])
        total_lots = sum(float(item.get("lots", 0) or 0) for item in series)
        gross_acres = float(payload.get("gross_acres", 0) or 0)

        rough_revenue = 0.0
        for item in series:
            base_price = float(item.get("base_house_price", 0) or 0)
            lot_premium = float(item.get("lot_premium", 0) or 0)
            options_pct = float(item.get("options_pct", 0) or 0)
            incentive_pct = float(item.get("price_incentives_pct", 0) or 0) + float(
                item.get("mortgage_incentives_pct", 0) or 0
            )
            net_sales_price = base_price + lot_premium + (base_price * options_pct) - (base_price * incentive_pct)
            rough_revenue += net_sales_price * float(item.get("lots", 0) or 0)

        land_basis = float(payload.get("land_brokerage_and_closing_costs_total", 0) or 0)
        events = payload.get("land_purchase_events", [])
        if events:
            land_basis += sum(
                float(item.get("lots", 0) or 0) * float(item.get("price_per_lot", 0) or 0)
                for item in events
            )
        else:
            land_basis += total_lots * float(payload.get("land_purchase_price_per_lot", 0) or 0)

        site_spend = (
            float(payload.get("land_development_cost_total", 0) or 0)
            + float(payload.get("project_management_cost_total", 0) or 0)
            + float(payload.get("other_land_costs_total", 0) or 0)
        )
        monthly_absorption = float(payload.get("monthly_absorption", 0) or 0)
        sellout_months = (total_lots / monthly_absorption) if monthly_absorption > 0 else None
        density = (total_lots / gross_acres) if gross_acres > 0 else None
        avg_net_price = (rough_revenue / total_lots) if total_lots > 0 else None
        land_per_lot = (land_basis / total_lots) if total_lots > 0 else None
        subject_sqft_total = sum(
            float(item.get("avg_sqft", 0) or 0) * float(item.get("lots", 0) or 0)
            for item in series
        )
        subject_avg_sqft = (subject_sqft_total / total_lots) if total_lots > 0 else None

        def set_card(key: str, value: str, note: str) -> None:
            value_label, note_label = self.overview_cards[key]
            value_label.configure(text=value)
            note_label.configure(text=note)

        active_series = sum(1 for item in series if float(item.get("lots", 0) or 0) > 0)
        set_card("lots", _format_number(total_lots, 0), f"{active_series} active series")
        set_card(
            "density",
            _format_number(density, 2),
            f"{_format_number(gross_acres, 1)} gross acres",
        )
        set_card(
            "revenue",
            _format_currency(rough_revenue),
            f"Avg net ASP {_format_currency(avg_net_price)}",
        )
        set_card(
            "land_basis",
            _format_currency(land_basis),
            f"{_format_currency(land_per_lot)} per lot",
        )
        set_card(
            "site_spend",
            _format_currency(site_spend),
            f"{_format_currency((site_spend / total_lots) if total_lots else None)} per lot",
        )
        set_card(
            "absorption",
            _format_number(monthly_absorption, 2),
            f"Approx. sellout {_format_number(sellout_months, 1)} months",
        )

        competitors = payload.get("competitor_projects", [])
        competitor_avg_price = (
            sum(float(item.get("avg_price", 0) or 0) for item in competitors) / len(competitors)
            if competitors
            else None
        )
        competitor_avg_pace = (
            sum(float(item.get("monthly_absorption", 0) or 0) for item in competitors) / len(competitors)
            if competitors
            else None
        )
        resales = payload.get("resale_comps", [])
        resale_avg_psf = None
        if resales:
            resale_psf_values = []
            for item in resales:
                close_price = float(item.get("close_price", 0) or 0)
                sqft = float(item.get("sqft", 0) or 0)
                if close_price > 0 and sqft > 0:
                    resale_psf_values.append(close_price / sqft)
            if resale_psf_values:
                resale_avg_psf = sum(resale_psf_values) / len(resale_psf_values)

        avg_net_psf = (avg_net_price / subject_avg_sqft) if avg_net_price and subject_avg_sqft else None

        if competitor_avg_price:
            price_note = f"Vs comps {_format_pct((avg_net_price - competitor_avg_price) / competitor_avg_price) if avg_net_price else '-'}"
        elif resale_avg_psf and avg_net_psf:
            price_note = f"Vs resale PPSF {_format_pct((avg_net_psf - resale_avg_psf) / resale_avg_psf)}"
        else:
            price_note = "Add competitor or resale data"
        set_card("market_price", _format_currency(competitor_avg_price or avg_net_price), price_note)

        if competitor_avg_pace:
            pace_note = f"Target delta {_format_pct((monthly_absorption - competitor_avg_pace) / competitor_avg_pace) if monthly_absorption else 0}"
            set_card("market_pace", _format_number(competitor_avg_pace, 2), pace_note)
        else:
            set_card("market_pace", _format_number(monthly_absorption, 2), "Add competitor pace to benchmark")

        self._draw_builder_schedule_preview(payload)
        diagnostics = self._builder_diagnostics(payload)
        band = diagnostics["band"]
        if band == "ready":
            bg = COLORS["green_soft"]
            fg = COLORS["green"]
            card_bg = COLORS["green"]
        elif band == "watch":
            bg = COLORS["amber_soft"]
            fg = COLORS["amber"]
            card_bg = COLORS["amber"]
        else:
            bg = COLORS["red_soft"]
            fg = COLORS["red"]
            card_bg = COLORS["red"]

        self.health_card.configure(bg=card_bg, highlightbackground=card_bg)
        self.health_value_label.configure(text=str(diagnostics["score"]), bg=card_bg)
        self.health_note_label.configure(text=diagnostics["summary"], bg=card_bg)
        for child in self.health_card.winfo_children():
            child.configure(bg=card_bg)
        self._set_scrolled_text(self.diagnostics_text, "\n".join(diagnostics["lines"]))

    def _set_scrolled_text(self, widget: ScrolledText, text: str) -> None:
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.insert("1.0", text)
        widget.configure(state="disabled")

    def _builder_diagnostics(self, payload: dict[str, Any]) -> dict[str, Any]:
        lines: list[str] = []
        score = 100
        series = payload.get("product_series", [])
        total_lots = sum(float(item.get("lots", 0) or 0) for item in series)
        phases = payload.get("schedule_phases") or payload.get("land_purchase_events") or []
        phase_lots = sum(float(item.get("lots", 0) or 0) for item in phases)
        competitors = payload.get("competitor_projects", [])
        resales = payload.get("resale_comps", [])
        market = str(payload.get("market") or "").strip()
        notes = str(payload.get("notes") or "").strip()
        monthly_absorption = float(payload.get("monthly_absorption", 0) or 0)

        if not market:
            score -= 8
            lines.append("Market is blank. Name the market so saved deals are easier to review.")
        if total_lots <= 0:
            score -= 25
            lines.append("No active product series. Add at least one series with positive lots.")
        if phases and total_lots and abs(phase_lots - total_lots) > 0.1:
            score -= 18
            lines.append(
                f"Phase lots ({_format_number(phase_lots, 0)}) do not match series lots ({_format_number(total_lots, 0)})."
            )
        elif not phases and (payload.get("land_purchase_price_per_lot") or 0) <= 0:
            score -= 20
            lines.append("No valid land basis. Enter Land Price / Lot or build a phase schedule.")
        elif not phases:
            score -= 6
            lines.append("Using a flat land price. Add phases if takedown timing matters to cash flow.")

        if len(competitors) == 0:
            score -= 8
            lines.append("No competitor communities loaded. Pace and pricing are not benchmarked.")
        if len(resales) == 0:
            score -= 6
            lines.append("No resale comps loaded. There is no backstop for price / sqft support.")
        if not notes:
            score -= 4
            lines.append("Notes are blank. Add diligence context so risk flags are more useful.")

        if competitors and monthly_absorption > 0:
            avg_comp_pace = sum(float(item.get("monthly_absorption", 0) or 0) for item in competitors) / len(competitors)
            if avg_comp_pace > 0:
                pace_delta = (monthly_absorption - avg_comp_pace) / avg_comp_pace
                if pace_delta > 0.2:
                    score -= 12
                    lines.append("Planned absorption is materially ahead of the competitor set.")
                elif pace_delta > 0.08:
                    score -= 5
                    lines.append("Planned absorption is modestly ahead of the competitor set.")

        if score >= 80:
            band = "ready"
            summary = "Deal packet is well-formed and benchmarked."
        elif score >= 60:
            band = "watch"
            summary = "Usable, but a few assumptions still need tightening."
        else:
            band = "risk"
            summary = "Incomplete or unsupported assumptions are weakening the screen."

        if not lines:
            lines.append("No major input issues detected. Run the underwrite and review the sensitivity tab.")

        return {
            "score": max(0, min(100, score)),
            "band": band,
            "summary": summary,
            "lines": lines,
        }

    def _auto_build_phases(self) -> None:
        payload = self._request_from_form(strict=False)
        total_lots = sum(float(item.get("lots", 0) or 0) for item in payload.get("product_series", []))
        if total_lots <= 0:
            messagebox.showerror("Missing Lots", "Add at least one product series before auto-building phases.", parent=self.root)
            return

        structure = str(payload.get("takedown_structure") or "bulk").lower()
        base_price = float(payload.get("land_purchase_price_per_lot", 0) or 0)
        if base_price <= 0:
            existing = payload.get("land_purchase_events") or []
            if existing:
                total_cost = sum(float(item.get("lots", 0) or 0) * float(item.get("price_per_lot", 0) or 0) for item in existing)
                base_price = total_cost / total_lots if total_lots else 0

        if structure == "bulk":
            phase_count = 1
            spacing = 0
        elif structure == "rolling":
            phase_count = 4 if total_lots >= 80 else 3
            spacing = 4
        else:
            phase_count = 3 if total_lots >= 50 else 2
            spacing = 6

        base_phase_size = int(total_lots // phase_count)
        remainder = int(round(total_lots - (base_phase_size * phase_count)))
        lots_by_phase = []
        for index in range(phase_count):
            lots = base_phase_size + (1 if index < remainder else 0)
            lots_by_phase.append(lots)

        for index, row in enumerate(self.phase_rows):
            default_name = f"Phase {index + 1}"
            if index < phase_count:
                price_multiplier = 1.0 + (0.02 * index if structure != "bulk" else 0.0)
                row["name"].set(default_name)
                row["month"].set(str(index * spacing))
                row["lots"].set(str(lots_by_phase[index]))
                row["price_per_lot"].set(_format_input_number(base_price * price_multiplier if base_price else 0))
            else:
                row["name"].set(default_name)
                row["month"].set("")
                row["lots"].set("")
                row["price_per_lot"].set("")

        self.events_text.delete("1.0", "end")
        self._schedule_refresh()
        self._set_status("Built a staged takedown plan from the current lot count and takedown structure.")

    def _balance_absorption_to_market(self) -> None:
        payload = self._request_from_form(strict=False)
        competitors = payload.get("competitor_projects", [])
        if not competitors:
            messagebox.showerror("No Competitors", "Add competitor communities before matching pace to market.", parent=self.root)
            return
        valid_paces = [float(item.get("monthly_absorption", 0) or 0) for item in competitors if float(item.get("monthly_absorption", 0) or 0) > 0]
        if not valid_paces:
            messagebox.showerror("No Pace Data", "Competitor rows need monthly absorption values.", parent=self.root)
            return
        avg_pace = sum(valid_paces) / len(valid_paces)
        self.form_vars["monthly_absorption"].set(_format_input_number(avg_pace, 2))
        self._schedule_refresh()
        self._set_status("Updated monthly absorption to the competitor average pace.")

    def _copy_ic_memo(self) -> None:
        result = self.current_result
        if isinstance(result, list):
            result = result[0] if result and isinstance(result[0], dict) else None
        if not isinstance(result, dict):
            self._set_status("Run an underwrite first to generate an IC memo.")
            return
        memo = result.get("investment_committee_memo")
        if not isinstance(memo, dict):
            self._set_status("No IC memo is available for the current result.")
            return
        lines = [
            memo.get("headline", ""),
            "",
            memo.get("summary", ""),
            "",
            "Strengths:",
        ]
        for item in memo.get("strengths", []):
            lines.append(f"- {item}")
        lines.extend(["", "Risks:"])
        for item in memo.get("risks", []):
            lines.append(f"- {item}")
        lines.extend(["", "Next Steps:"])
        for item in memo.get("next_steps", []):
            lines.append(f"- {item}")
        text = "\n".join(lines).strip()
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        self._set_status("Investment committee memo copied to clipboard.")

    def _request_from_form(self, strict: bool = True) -> dict[str, Any]:
        def text_value(key: str) -> str:
            variable = self.form_vars.get(key)
            if variable is None:
                return ""
            return str(variable.get()).strip()

        def float_value(key: str) -> float | None:
            raw = text_value(key)
            if not raw:
                return None
            try:
                return _parse_optional_float(raw)
            except ValueError as error:
                if strict:
                    raise ValueError(f"{key.replace('_', ' ').title()} is not a valid number.") from error
                return None

        def int_value(key: str) -> int | None:
            raw = text_value(key)
            if not raw:
                return None
            try:
                return _parse_optional_int(raw)
            except ValueError as error:
                if strict:
                    raise ValueError(f"{key.replace('_', ' ').title()} is not a valid whole number.") from error
                return None

        def ratio_value(key: str) -> float | None:
            raw = text_value(key)
            if not raw:
                return None
            try:
                return _parse_optional_ratio(raw)
            except ValueError as error:
                if strict:
                    raise ValueError(f"{key.replace('_', ' ').title()} is not a valid percentage.") from error
                return None

        def assign_if_present(target: dict[str, Any], key: str, value: Any) -> None:
            if value not in (None, ""):
                target[key] = value

        community_name = text_value("community_name") or "Unnamed Community"
        payload: dict[str, Any] = {
            "community_name": community_name,
            "division": text_value("division"),
            "market": text_value("market"),
            "gross_acres": float_value("gross_acres") or 0.0,
            "takedown_structure": text_value("takedown_structure") or "bulk",
            "deposit_credit_at_close": bool(self.form_vars["deposit_credit_at_close"].get()),
            "notes": self.notes_text.get("1.0", "end").strip(),
        }

        for key in (
            "land_purchase_price_per_lot",
            "land_brokerage_and_closing_costs_total",
            "earnest_money_deposit",
            "land_development_cost_total",
            "project_management_cost_total",
            "other_land_costs_total",
            "capitalized_marketing_total",
            "architecture_engineering_total",
            "indirect_field_overhead_per_month",
            "other_house_costs_per_unit",
            "monthly_absorption",
        ):
            assign_if_present(payload, key, float_value(key))

        for key in (
            "build_cycle_months",
            "months_to_first_home_start",
            "months_to_sales_open",
            "months_to_first_close",
            "site_improvement_spend_months",
        ):
            assign_if_present(payload, key, int_value(key))

        for key in (
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
        ):
            assign_if_present(payload, key, ratio_value(key))

        if text_value("land_close_date"):
            payload["land_close_date"] = text_value("land_close_date")

        global_options_pct = ratio_value("options_pct")
        global_price_incentives_pct = ratio_value("price_incentives_pct")
        global_mortgage_incentives_pct = ratio_value("mortgage_incentives_pct")
        global_direct_contingency_pct = ratio_value("direct_cost_contingency_pct")
        global_other_vertical = float_value("other_vertical_costs_per_unit")

        series_payload: list[dict[str, Any]] = []
        for index, row in enumerate(self.series_rows, start=1):
            row_text = {key: str(value.get()).strip() for key, value in row.items() if key != "move_up"}
            default_name = f"Series {chr(64 + index)}"

            def parse_row_number(field_name: str) -> float | None:
                raw_value = row_text.get(field_name, "")
                if not raw_value:
                    return None
                try:
                    return _parse_optional_float(raw_value)
                except ValueError as error:
                    if strict:
                        raise ValueError(
                            f"Series row {index} has an invalid value for {field_name.replace('_', ' ')}."
                        ) from error
                    return None

            lots_raw = row_text.get("lots", "")
            has_content = (
                any(value for key, value in row_text.items() if key != "name")
                or (row_text.get("name") not in ("", default_name))
                or bool(row["move_up"].get())
            )
            if not has_content:
                continue
            lots = parse_row_number("lots")
            if not lots or lots <= 0:
                if strict:
                    raise ValueError(f"Series row {index} needs positive Lots.")
                continue

            avg_sqft = parse_row_number("avg_sqft")
            base_house_price = parse_row_number("base_house_price")
            if strict and (avg_sqft is None or avg_sqft <= 0):
                raise ValueError(f"Series row {index} needs Avg Sqft.")
            if strict and (base_house_price is None or base_house_price <= 0):
                raise ValueError(f"Series row {index} needs Base Price.")

            item: dict[str, Any] = {
                "name": row_text.get("name") or default_name,
                "lots": lots,
                "avg_sqft": avg_sqft or 0.0,
                "base_house_price": base_house_price or 0.0,
                "move_up": bool(row["move_up"].get()),
            }
            assign_if_present(item, "lot_premium", parse_row_number("lot_premium"))
            assign_if_present(item, "direct_cost_psf", parse_row_number("direct_cost_psf"))
            assign_if_present(item, "permit_fees_per_unit", parse_row_number("permit_fees_per_unit"))
            assign_if_present(item, "tap_fees_per_unit", parse_row_number("tap_fees_per_unit"))
            assign_if_present(item, "options_pct", global_options_pct)
            assign_if_present(item, "price_incentives_pct", global_price_incentives_pct)
            assign_if_present(item, "mortgage_incentives_pct", global_mortgage_incentives_pct)
            assign_if_present(item, "direct_cost_contingency_pct", global_direct_contingency_pct)
            assign_if_present(item, "other_vertical_costs_per_unit", global_other_vertical)
            series_payload.append(item)

        if strict and not series_payload:
            raise ValueError("Enter at least one product series with positive lots.")
        payload["product_series"] = series_payload

        events_payload: list[dict[str, Any]] = []
        phase_payload: list[dict[str, Any]] = []
        for index, row in enumerate(self.phase_rows, start=1):
            row_text = {key: str(value.get()).strip() for key, value in row.items()}
            default_name = f"Phase {index}"
            has_content = any(value for key, value in row_text.items() if key != "name") or (
                row_text.get("name") not in ("", default_name)
            )
            if not has_content:
                continue

            try:
                month = _parse_optional_int(row_text.get("month", "")) if row_text.get("month") else None
                lots = _parse_optional_float(row_text.get("lots", "")) if row_text.get("lots") else None
                price_per_lot = (
                    _parse_optional_float(row_text.get("price_per_lot", ""))
                    if row_text.get("price_per_lot")
                    else None
                )
            except ValueError as error:
                if strict:
                    raise ValueError(f"Phase row {index} has an invalid number.") from error
                continue

            if strict and month is None:
                raise ValueError(f"Phase row {index} needs a Close Month.")
            if strict and (lots is None or lots <= 0):
                raise ValueError(f"Phase row {index} needs positive Lots.")
            if strict and (price_per_lot is None or price_per_lot <= 0):
                raise ValueError(f"Phase row {index} needs a positive Price / Lot.")
            if month is None or lots is None or lots <= 0 or price_per_lot is None or price_per_lot <= 0:
                continue

            phase_item = {
                "name": row_text.get("name") or default_name,
                "month": max(0, month),
                "lots": lots,
                "price_per_lot": price_per_lot,
            }
            phase_payload.append(phase_item)
            events_payload.append(
                {
                    "month": phase_item["month"],
                    "lots": phase_item["lots"],
                    "price_per_lot": phase_item["price_per_lot"],
                }
            )

        raw_events = self.events_text.get("1.0", "end").strip()
        if raw_events and not events_payload:
            for line_number, raw_line in enumerate(raw_events.splitlines(), start=1):
                line = raw_line.strip()
                if not line:
                    continue
                parts = [part.strip() for part in line.split(",")]
                if len(parts) != 3:
                    if strict:
                        raise ValueError(
                            f"Takedown event line {line_number} must be month,lots,price_per_lot."
                        )
                    continue
                try:
                    month = int(round(float(_clean_number_text(parts[0]))))
                    lots = float(_clean_number_text(parts[1]))
                    price_per_lot = float(_clean_number_text(parts[2]))
                except ValueError as error:
                    if strict:
                        raise ValueError(f"Takedown event line {line_number} has an invalid number.") from error
                    continue
                if lots <= 0 or price_per_lot <= 0:
                    if strict:
                        raise ValueError(
                            f"Takedown event line {line_number} needs positive lots and price."
                        )
                    continue
                events_payload.append(
                    {
                        "month": max(0, month),
                        "lots": lots,
                        "price_per_lot": price_per_lot,
                    }
                )

        if phase_payload:
            payload["schedule_phases"] = phase_payload
        if events_payload:
            payload["land_purchase_events"] = events_payload

        if strict and not events_payload and (payload.get("land_purchase_price_per_lot") or 0) <= 0:
            raise ValueError("Enter Land Price / Lot or at least one Takedown Event.")

        competitor_payload: list[dict[str, Any]] = []
        for row in self.competitor_rows:
            item = {key: str(value.get()).strip() for key, value in row.items()}
            if not any(item.values()):
                continue
            try:
                monthly_absorption = (
                    _parse_optional_float(item.get("monthly_absorption", ""))
                    if item.get("monthly_absorption")
                    else None
                )
                avg_price = _parse_optional_float(item.get("avg_price", "")) if item.get("avg_price") else None
                avg_sqft = _parse_optional_float(item.get("avg_sqft", "")) if item.get("avg_sqft") else None
            except ValueError as error:
                if strict:
                    raise ValueError("Competitor rows must contain valid numbers.") from error
                continue

            competitor_item: dict[str, Any] = {
                "name": item.get("name") or "Comparable Community",
                "status": item.get("status") or "",
            }
            assign_if_present(competitor_item, "monthly_absorption", monthly_absorption)
            assign_if_present(competitor_item, "avg_price", avg_price)
            assign_if_present(competitor_item, "avg_sqft", avg_sqft)
            if any(key in competitor_item for key in ("monthly_absorption", "avg_price", "avg_sqft")):
                competitor_payload.append(competitor_item)

        if competitor_payload:
            payload["competitor_projects"] = competitor_payload

        resale_payload: list[dict[str, Any]] = []
        for row in self.resale_rows:
            item = {key: str(value.get()).strip() for key, value in row.items()}
            if not any(item.values()):
                continue
            try:
                close_price = _parse_optional_float(item.get("close_price", "")) if item.get("close_price") else None
                sqft = _parse_optional_float(item.get("sqft", "")) if item.get("sqft") else None
                distance_miles = (
                    _parse_optional_float(item.get("distance_miles", ""))
                    if item.get("distance_miles")
                    else None
                )
            except ValueError as error:
                if strict:
                    raise ValueError("Resale rows must contain valid numbers.") from error
                continue

            resale_item: dict[str, Any] = {
                "name": item.get("name") or "Resale Comp",
                "close_date": item.get("close_date") or "",
            }
            assign_if_present(resale_item, "close_price", close_price)
            assign_if_present(resale_item, "sqft", sqft)
            assign_if_present(resale_item, "distance_miles", distance_miles)
            if "close_price" in resale_item or "sqft" in resale_item:
                resale_payload.append(resale_item)

        if resale_payload:
            payload["resale_comps"] = resale_payload

        return payload

    def _render_json_text(self, payload: Any) -> None:
        self.hidden_payload_cache = payload

    def _sync_builder_to_json(self) -> None:
        try:
            payload = self._request_from_form(strict=True)
        except ValueError as error:
            self._set_status(str(error))
            messagebox.showerror("Builder Error", str(error), parent=self.root)
            return
        self._render_json_text(payload)
        self._set_status("Deal assumptions refreshed in the background.")

    def _apply_request_to_builder(self, payload: dict[str, Any]) -> None:
        self.form_vars["community_name"].set(str(payload.get("community_name") or ""))
        self.form_vars["division"].set(str(payload.get("division") or ""))
        self.form_vars["market"].set(str(payload.get("market") or ""))
        self.form_vars["takedown_structure"].set(str(payload.get("takedown_structure") or "bulk"))
        self.form_vars["land_close_date"].set(str(payload.get("land_close_date") or ""))
        self.form_vars["deposit_credit_at_close"].set(bool(payload.get("deposit_credit_at_close", True)))

        for key in (
            "gross_acres",
            "land_purchase_price_per_lot",
            "land_brokerage_and_closing_costs_total",
            "earnest_money_deposit",
            "land_development_cost_total",
            "project_management_cost_total",
            "other_land_costs_total",
            "capitalized_marketing_total",
            "architecture_engineering_total",
            "indirect_field_overhead_per_month",
            "other_house_costs_per_unit",
            "monthly_absorption",
            "build_cycle_months",
            "months_to_first_home_start",
            "months_to_sales_open",
            "months_to_first_close",
            "site_improvement_spend_months",
        ):
            self.form_vars[key].set(_format_input_number(payload.get(key)))

        for key in (
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
        ):
            self.form_vars[key].set(_format_input_ratio(payload.get(key)))

        series = list(payload.get("product_series") or [])
        warnings: list[str] = []
        if len(series) > SERIES_ROW_COUNT:
            warnings.append(f"Builder shows the first {SERIES_ROW_COUNT} series only.")

        globals_source = series[0] if series else {}
        self.form_vars["options_pct"].set(_format_input_ratio(globals_source.get("options_pct")))
        self.form_vars["price_incentives_pct"].set(
            _format_input_ratio(globals_source.get("price_incentives_pct"))
        )
        self.form_vars["mortgage_incentives_pct"].set(
            _format_input_ratio(globals_source.get("mortgage_incentives_pct"))
        )
        self.form_vars["direct_cost_contingency_pct"].set(
            _format_input_ratio(globals_source.get("direct_cost_contingency_pct"))
        )
        self.form_vars["other_vertical_costs_per_unit"].set(
            _format_input_number(globals_source.get("other_vertical_costs_per_unit"))
        )

        for global_key in (
            "options_pct",
            "price_incentives_pct",
            "mortgage_incentives_pct",
            "direct_cost_contingency_pct",
            "other_vertical_costs_per_unit",
        ):
            first_value = globals_source.get(global_key)
            for item in series[1:]:
                if item.get(global_key) != first_value:
                    warnings.append("Some series-level overrides were simplified to fit the workspace view.")
                    break
            if len(warnings) > 1:
                break

        for index, row in enumerate(self.series_rows):
            default_name = f"Series {chr(65 + index)}"
            if index < len(series):
                item = series[index]
                row["name"].set(str(item.get("name") or default_name))
                row["lots"].set(_format_input_number(item.get("lots")))
                row["avg_sqft"].set(_format_input_number(item.get("avg_sqft")))
                row["base_house_price"].set(_format_input_number(item.get("base_house_price")))
                row["lot_premium"].set(_format_input_number(item.get("lot_premium")))
                row["direct_cost_psf"].set(_format_input_number(item.get("direct_cost_psf")))
                row["permit_fees_per_unit"].set(_format_input_number(item.get("permit_fees_per_unit")))
                row["tap_fees_per_unit"].set(_format_input_number(item.get("tap_fees_per_unit")))
                row["move_up"].set(bool(item.get("move_up", False)))
            else:
                row["name"].set(default_name)
                row["lots"].set("")
                row["avg_sqft"].set("")
                row["base_house_price"].set("")
                row["lot_premium"].set("")
                row["direct_cost_psf"].set("")
                row["permit_fees_per_unit"].set("")
                row["tap_fees_per_unit"].set("")
                row["move_up"].set(False)

        raw_events = payload.get("schedule_phases") or payload.get("land_purchase_events") or payload.get("takedown_schedule") or []
        for index, row in enumerate(self.phase_rows):
            default_name = f"Phase {index + 1}"
            if index < len(raw_events):
                item = raw_events[index]
                row["name"].set(str(item.get("name") or default_name))
                row["month"].set(_format_input_number(item.get("month"), 0))
                row["lots"].set(_format_input_number(item.get("lots")))
                row["price_per_lot"].set(_format_input_number(item.get("price_per_lot")))
            else:
                row["name"].set(default_name)
                row["month"].set("")
                row["lots"].set("")
                row["price_per_lot"].set("")

        event_lines = [
            f"{int(item.get('month', 0))},{_format_input_number(item.get('lots'))},{_format_input_number(item.get('price_per_lot'))}"
            for item in raw_events
        ]
        self.events_text.delete("1.0", "end")
        self.events_text.insert("1.0", "\n".join(event_lines))

        competitors = list(payload.get("competitor_projects") or [])
        for index, row in enumerate(self.competitor_rows):
            if index < len(competitors):
                item = competitors[index]
                row["name"].set(str(item.get("name") or ""))
                row["monthly_absorption"].set(_format_input_number(item.get("monthly_absorption")))
                row["avg_price"].set(_format_input_number(item.get("avg_price")))
                row["avg_sqft"].set(_format_input_number(item.get("avg_sqft")))
                row["status"].set(str(item.get("status") or ""))
            else:
                for variable in row.values():
                    variable.set("")

        resales = list(payload.get("resale_comps") or [])
        for index, row in enumerate(self.resale_rows):
            if index < len(resales):
                item = resales[index]
                row["name"].set(str(item.get("name") or ""))
                row["close_price"].set(_format_input_number(item.get("close_price")))
                row["sqft"].set(_format_input_number(item.get("sqft")))
                row["distance_miles"].set(_format_input_number(item.get("distance_miles")))
                row["close_date"].set(str(item.get("close_date") or ""))
            else:
                for variable in row.values():
                    variable.set("")

        self.notes_text.delete("1.0", "end")
        self.notes_text.insert("1.0", str(payload.get("notes") or ""))

        self._schedule_refresh()
        if self.refresh_job is not None:
            self.root.after_cancel(self.refresh_job)
            self.refresh_job = None
        self._refresh_builder_overview()
        if warnings:
            self._set_status(" ".join(dict.fromkeys(warnings)))

    def _apply_json_to_builder(self) -> None:
        payload = self.hidden_payload_cache
        if payload is None:
            self._set_status("No hidden deal payload is available.")
            return
        display_payload = payload[0] if isinstance(payload, list) and payload else payload
        if not isinstance(display_payload, dict):
            self._set_status("The hidden deal payload is not usable.")
            return
        self._apply_request_to_builder(display_payload)
        self.notebook.select(self.builder_tab)
        self._set_status("Background deal payload restored into the workspace.")

    def _load_request_payload(self, payload: Any, file_path: Path | None = None) -> None:
        display_payload = payload
        if isinstance(payload, list):
            if not payload or not isinstance(payload[0], dict):
                raise ValueError("Deal file must contain at least one valid deal.")
            display_payload = payload[0]
        elif not isinstance(payload, dict):
            raise ValueError("Deal file could not be read.")

        self.current_file = file_path.resolve() if file_path else None
        self.file_var.set(
            f"Deal: {_deal_display_name(self.current_file)}" if self.current_file else "Deal: Unsaved Deal"
        )

        generated_root = _repo_root() / "generated_agents"
        self.latest_agent_dir = _latest_land_underwriter_agent_dir(generated_root)
        if self.latest_agent_dir is not None:
            self.agent_var.set(f"Underwriter: {self.latest_agent_dir.name}")
        else:
            self.agent_var.set("Underwriter: rules engine only")

        self._apply_request_to_builder(display_payload)
        self._render_json_text(payload)
        self.notebook.select(self.builder_tab)

        if isinstance(payload, list):
            self._set_status(f"Loaded {len(payload)} deals; the workspace is showing the first one.")
        else:
            self._set_status("Deal loaded into the workspace.")

    def _load_sample_request(self) -> None:
        sample_path = _sample_request_path()
        try:
            payload = json.loads(sample_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            messagebox.showerror("Missing Starter Deal", f"Starter deal was not found:\n{sample_path}", parent=self.root)
            self._set_status("Starter deal is missing.")
            return
        except json.JSONDecodeError as error:
            messagebox.showerror("Invalid Starter Deal", error.msg, parent=self.root)
            self._set_status(f"Starter deal could not be read: {error.msg}")
            return

        self._load_request_payload(payload, sample_path)

    def _open_request_file(self) -> None:
        initial_dir = str(self.current_file.parent) if self.current_file else str(_sample_request_path().parent)
        selected = filedialog.askopenfilename(
            parent=self.root,
            title="Open Deal",
            initialdir=initial_dir,
            filetypes=[("Land Deal Files", "*.landdeal"), ("All Files", "*.*")],
        )
        if not selected:
            return

        path = Path(selected)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as error:
            messagebox.showerror("Invalid Deal File", error.msg, parent=self.root)
            self._set_status(f"Could not open deal: {error.msg}")
            return

        self._load_request_payload(payload, path)

    def _save_request_file(self) -> None:
        try:
            payload = self._request_from_form(strict=True)
            self._render_json_text(payload)
        except ValueError as error:
            messagebox.showerror("Builder Error", str(error), parent=self.root)
            self._set_status(str(error))
            return

        destination = self.current_file
        if destination is None or destination == _sample_request_path():
            selected = filedialog.asksaveasfilename(
                parent=self.root,
                title="Save Deal",
                defaultextension=".landdeal",
                initialfile="new_land_deal.landdeal",
                filetypes=[("Land Deal Files", "*.landdeal"), ("All Files", "*.*")],
            )
            if not selected:
                return
            destination = Path(selected)

        destination.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        self.current_file = destination.resolve()
        self.file_var.set(f"Deal: {_deal_display_name(self.current_file)}")
        self._set_status(f"Saved deal to {_deal_display_name(self.current_file)}.")

    def _run_active_request(self) -> None:
        if self.run_inflight:
            return
        self._run_builder_request()

    def _run_builder_request(self) -> None:
        try:
            payload = self._request_from_form(strict=True)
        except ValueError as error:
            messagebox.showerror("Builder Error", str(error), parent=self.root)
            self._set_status(str(error))
            return

        self._render_json_text(payload)
        self._enqueue_underwrite(payload)

    def _run_json_request(self) -> None:
        payload = self.hidden_payload_cache
        if not isinstance(payload, (dict, list)):
            self._set_status("No background deal payload is available to run.")
            return
        self._enqueue_underwrite(payload)

    def _enqueue_underwrite(self, payload: Any) -> None:
        generated_root = _repo_root() / "generated_agents"
        self.latest_agent_dir = _latest_land_underwriter_agent_dir(generated_root)
        if self.latest_agent_dir is not None:
            self.agent_var.set(f"Underwriter: {self.latest_agent_dir.name}")
        else:
            self.agent_var.set("Underwriter: rules engine only")

        self._set_busy(True)
        self._set_status("Running land deal underwrite...")
        self.notebook.select(self.results_tab)
        self.request_queue.put(
            {
                "payload": payload,
                "agent_dir": str(self.latest_agent_dir) if self.latest_agent_dir else None,
            }
        )

    def _set_status(self, message: str) -> None:
        self.status_var.set(message)

    def _set_busy(self, busy: bool) -> None:
        self.run_inflight = busy
        state = "disabled" if busy else "normal"
        for button in (self.load_button, self.open_button, self.save_button, self.memo_button, self.run_button):
            button.configure(state=state)
        self.root.configure(cursor="watch" if busy else "")
        if not busy:
            self.root.update_idletasks()

    def _start_worker(self) -> None:
        self.worker_thread = threading.Thread(target=self._worker_loop, daemon=True)
        self.worker_thread.start()

    def _worker_loop(self) -> None:
        while True:
            request = self.request_queue.get()
            if request is None:
                return

            try:
                payload = request["payload"]
                agent_dir = request.get("agent_dir")
                specialist = None
                if agent_dir:
                    resolved_agent_dir = Path(agent_dir)
                    if resolved_agent_dir.exists():
                        specialist = AgentFactory().load_specialist_agent(resolved_agent_dir)
                underwriter = LandDealUnderwriter(specialist)
                if isinstance(payload, list):
                    result = underwriter.underwrite_many(payload)
                else:
                    result = underwriter.underwrite(payload)
                self.response_queue.put(
                    (
                        "success",
                        {
                            "result": result,
                            "agent_dir": agent_dir,
                        },
                    )
                )
            except Exception as error:  # noqa: BLE001
                self.response_queue.put(("error", str(error)))

    def _poll_responses(self) -> None:
        try:
            while True:
                kind, payload = self.response_queue.get_nowait()
                if kind == "success":
                    self.current_result = payload["result"]
                    agent_dir = payload.get("agent_dir")
                    if agent_dir:
                        self.agent_var.set(f"Agent: {Path(agent_dir).name}")
                    self._render_result(payload["result"])
                    if isinstance(payload["result"], list):
                        self._set_status(f"Underwrite complete for {len(payload['result'])} deals.")
                    else:
                        self._set_status("Underwrite complete.")
                    self._set_busy(False)
                else:
                    self._set_busy(False)
                    self._set_status(f"Underwrite failed: {payload}")
                    messagebox.showerror("Underwrite Failed", str(payload), parent=self.root)
        except queue.Empty:
            pass

        if self.root.winfo_exists():
            self.root.after(150, self._poll_responses)

    def _render_result(self, result: Any) -> None:
        display_result = result
        if isinstance(result, list):
            display_result = result[0] if result and isinstance(result[0], dict) else None

        if not isinstance(display_result, dict):
            self._update_banner(None)
            self._render_raw_result(result)
            return

        self._update_banner(display_result)
        self._update_metric_cards(display_result)
        self._populate_scenario_tree(display_result)
        self._draw_chart(display_result)
        self._populate_decision_tab(display_result)
        self._populate_series_tab(display_result)
        self._populate_market_tab(display_result)
        self._populate_sensitivity_tab(display_result)
        self._populate_memo_tab(display_result)
        self._render_raw_result(result)

    def _update_banner(self, result: dict[str, Any] | None) -> None:
        if result is None:
            self.banner_frame.configure(bg=COLORS["card"])
            self.recommendation_label.configure(
                text="No single dashboard result to display.",
                bg=COLORS["card"],
                fg=COLORS["navy"],
            )
            self.recommendation_subtitle.configure(
                text="Open the Deep Dive tab for the full deal report.",
                bg=COLORS["card"],
                fg=COLORS["muted"],
            )
            return

        recommendation = str(result.get("recommendation") or "review").lower()
        if recommendation == "pursue":
            bg = COLORS["green_soft"]
            fg = COLORS["green"]
        elif recommendation == "negotiate":
            bg = COLORS["amber_soft"]
            fg = COLORS["amber"]
        else:
            bg = COLORS["red_soft"]
            fg = COLORS["red"]

        assumptions = result.get("assumptions", {})
        risk_flags = result.get("risk_flags", [])
        upside_flags = result.get("upside_flags", [])
        deal_score = result.get("deal_score", {})
        summary = (
            f"{result.get('community_name', 'Deal')} | "
            f"{_format_number(assumptions.get('total_lots'), 0)} lots | "
            f"{_format_number(assumptions.get('gross_acres'), 1)} acres | "
            f"Score {deal_score.get('score', '-')} | "
            f"{len(risk_flags)} risk flags | {len(upside_flags)} upside flags"
        )

        self.banner_frame.configure(bg=bg)
        self.recommendation_label.configure(
            text=f"Recommendation: {recommendation.upper()}",
            bg=bg,
            fg=fg,
        )
        self.recommendation_subtitle.configure(text=summary, bg=bg, fg=COLORS["ink"])

    def _update_metric_cards(self, result: dict[str, Any]) -> None:
        base_case = result["scenarios"]["base_case"]
        hurdles = result.get("hurdles", {}).get("base_case", {})
        assumptions = result.get("assumptions", {})
        investment = base_case["investment_summary"]
        income = base_case["income_statement"]
        cash = base_case["cash_flow_metrics"]

        gap = investment.get("land_value_gap_to_residual")
        peak_month = cash.get("peak_investment_month")
        peak_date = (base_case.get("schedule", {}).get("date_summary") or {}).get("peak_investment_date")

        cards = {
            "gross_margin": (
                _format_pct(income.get("gross_margin_pct")),
                f"Target {_format_pct(assumptions.get('target_gross_margin_pct'))}",
                bool(hurdles.get("gross_margin")),
            ),
            "pre_gna": (
                _format_pct(income.get("pre_gna_margin_pct")),
                f"Target {_format_pct(assumptions.get('target_pre_gna_margin_pct'))}",
                bool(hurdles.get("pre_gna_margin")),
            ),
            "irr": (
                _format_pct(cash.get("irr_pre_gna_pct")),
                f"Target {_format_pct(assumptions.get('target_irr_pct'))}",
                bool(hurdles.get("irr")),
            ),
            "residual": (
                _format_currency(investment.get("residual_max_land_cost_per_lot")),
                (
                    f"Above residual by {_format_currency(gap)}"
                    if isinstance(gap, (float, int)) and gap > 0
                    else f"Under residual by {_format_currency(abs(float(gap or 0)))}"
                ),
                bool(hurdles.get("residual_land_value")),
            ),
            "peak": (
                _format_currency(cash.get("peak_investment")),
                f"Month {peak_month}" + (f" | {peak_date}" if peak_date else ""),
                None,
            ),
        }

        for key, (value_text, note_text, passed) in cards.items():
            frame, value_label, note_label = self.metric_cards[key]
            if passed is True:
                bg = COLORS["green_soft"]
            elif passed is False:
                bg = COLORS["red_soft"]
            else:
                bg = COLORS["amber_soft"]

            frame.configure(bg=bg)
            for child in frame.winfo_children():
                child.configure(bg=bg)

            value_label.configure(text=value_text, fg=COLORS["ink"])
            note_label.configure(text=note_text, fg=COLORS["muted"])

    def _populate_scenario_tree(self, result: dict[str, Any]) -> None:
        for item in self.scenario_tree.get_children():
            self.scenario_tree.delete(item)

        for scenario_name in ("base_case", "downside_case", "severe_downside_case"):
            scenario = result.get("scenarios", {}).get(scenario_name)
            if not scenario:
                continue
            self.scenario_tree.insert(
                "",
                "end",
                values=(
                    _scenario_label(scenario_name),
                    _format_pct(scenario["income_statement"].get("gross_margin_pct")),
                    _format_pct(scenario["income_statement"].get("pre_gna_margin_pct")),
                    _format_pct(scenario["cash_flow_metrics"].get("irr_pre_gna_pct")),
                    _format_currency(scenario["investment_summary"].get("land_value_gap_to_residual")),
                    _format_currency(scenario["cash_flow_metrics"].get("peak_investment")),
                ),
            )

    def _draw_chart(self, result: dict[str, Any]) -> None:
        self.chart_canvas.delete("all")
        width = max(self.chart_canvas.winfo_width(), 640)
        height = max(self.chart_canvas.winfo_height(), 220)
        padding_x = 48
        padding_top = 20
        padding_bottom = 42

        values = []
        labels = []
        for name in ("base_case", "downside_case", "severe_downside_case"):
            scenario = result.get("scenarios", {}).get(name)
            if not scenario:
                continue
            values.append(float(scenario["income_statement"].get("pre_gna_margin_pct", 0) or 0))
            labels.append(_scenario_label(name))

        target = float(result.get("assumptions", {}).get("target_pre_gna_margin_pct", 0) or 0)
        if not values:
            return

        min_value = min(min(values), target, 0.0)
        max_value = max(max(values), target, 0.01)
        if max_value - min_value < 0.05:
            max_value += 0.03
            min_value -= 0.03

        def y_for(value: float) -> float:
            chart_height = height - padding_top - padding_bottom
            return padding_top + ((max_value - value) / (max_value - min_value)) * chart_height

        baseline_y = y_for(0.0)
        target_y = y_for(target)
        self.chart_canvas.create_line(padding_x, baseline_y, width - 20, baseline_y, fill=COLORS["line"], width=1)
        self.chart_canvas.create_line(
            padding_x,
            target_y,
            width - 20,
            target_y,
            fill=COLORS["accent"],
            width=2,
            dash=(6, 4),
        )
        self.chart_canvas.create_text(
            width - 24,
            target_y - 10,
            text=f"Target {_format_pct(target)}",
            fill=COLORS["accent"],
            font=("Segoe UI", 9, "bold"),
            anchor="e",
        )

        bar_width = 110
        gap = 42
        total_width = len(values) * bar_width + max(0, len(values) - 1) * gap
        start_x = padding_x + max(0, (width - padding_x - 20 - total_width) / 2)
        bar_colors = [COLORS["green"], COLORS["amber"], COLORS["red"]]

        for index, value in enumerate(values):
            x1 = start_x + index * (bar_width + gap)
            x2 = x1 + bar_width
            y = y_for(value)
            fill = bar_colors[min(index, len(bar_colors) - 1)]
            self.chart_canvas.create_rectangle(x1, min(y, baseline_y), x2, max(y, baseline_y), fill=fill, outline="")
            self.chart_canvas.create_text(
                (x1 + x2) / 2,
                y - 12 if value >= 0 else y + 12,
                text=_format_pct(value),
                fill=COLORS["ink"],
                font=("Segoe UI", 10, "bold"),
            )
            self.chart_canvas.create_text(
                (x1 + x2) / 2,
                height - 18,
                text=labels[index],
                fill=COLORS["navy"],
                font=("Segoe UI", 9, "bold"),
            )

    def _draw_schedule_canvas(
        self,
        canvas: tk.Canvas,
        *,
        phases: list[dict[str, Any]],
        milestones: list[tuple[str, int, str]],
        horizon: int,
    ) -> None:
        canvas.delete("all")
        width = max(canvas.winfo_width(), 560)
        height = max(canvas.winfo_height(), 170)
        left = 70
        right = width - 18
        top = 20
        axis_y = height - 34
        plot_width = max(120, right - left)
        horizon = max(1, horizon)

        def x_for(month: int) -> float:
            return left + (max(0, month) / horizon) * plot_width

        canvas.create_line(left, axis_y, right, axis_y, fill=COLORS["line"], width=2)
        tick_step = max(1, horizon // 6)
        for month in range(0, horizon + 1, tick_step):
            x = x_for(month)
            canvas.create_line(x, axis_y - 6, x, axis_y + 6, fill=COLORS["line"])
            canvas.create_text(x, axis_y + 18, text=str(month), fill=COLORS["muted"], font=("Segoe UI", 8))

        phase_y = top + 72
        canvas.create_text(left, top - 4, text="Milestones", anchor="w", fill=COLORS["navy"], font=("Segoe UI", 9, "bold"))
        for index, (label, month, detail) in enumerate(milestones):
            x = x_for(month)
            color = COLORS["accent"] if "Close" in label else COLORS["navy"]
            canvas.create_line(x, top + 12, x, axis_y - 10, fill=color, dash=(3, 4))
            canvas.create_oval(x - 5, top + 18, x + 5, top + 28, fill=color, outline="")
            canvas.create_text(
                x,
                top + 2 if index % 2 == 0 else top + 44,
                text=f"{label}\nM{month}",
                fill=COLORS["ink"],
                font=("Segoe UI", 8, "bold"),
                justify="center",
            )
            if detail:
                canvas.create_text(
                    x,
                    top + 56 if index % 2 == 0 else top + 30,
                    text=detail,
                    fill=COLORS["muted"],
                    font=("Segoe UI", 8),
                    justify="center",
                )

        for index, phase in enumerate(phases):
            month = int(float(phase.get("month", 0) or 0))
            x = x_for(month)
            y = phase_y + index * 18
            lots = _format_number(phase.get("lots"), 0)
            price = _format_currency(phase.get("price_per_lot"))
            fill = COLORS["green_soft"] if index % 2 == 0 else COLORS["accent_soft"]
            outline = COLORS["green"] if index % 2 == 0 else COLORS["accent"]
            canvas.create_rectangle(x - 10, y - 6, x + 10, y + 6, fill=fill, outline=outline)
            canvas.create_text(
                left - 8,
                y,
                text=str(phase.get("name") or f"Phase {index + 1}"),
                anchor="e",
                fill=COLORS["ink"],
                font=("Segoe UI", 8, "bold"),
            )
            canvas.create_text(
                x + 18,
                y,
                text=f"{lots} lots | {price}",
                anchor="w",
                fill=COLORS["muted"],
                font=("Segoe UI", 8),
            )

    def _draw_builder_schedule_preview(self, payload: dict[str, Any]) -> None:
        phases = list(payload.get("schedule_phases") or payload.get("land_purchase_events") or [])
        total_lots = sum(float(item.get("lots", 0) or 0) for item in payload.get("product_series", []))
        monthly_absorption = float(payload.get("monthly_absorption", 0) or 0)
        months_to_first_home_start = int(payload.get("months_to_first_home_start", 0) or 0)
        months_to_sales_open = int(payload.get("months_to_sales_open", 0) or 0)
        build_cycle_months = int(payload.get("build_cycle_months", 0) or 0)
        months_to_first_close = payload.get("months_to_first_close")
        first_close_month = (
            int(months_to_first_close)
            if months_to_first_close not in (None, "")
            else months_to_first_home_start + build_cycle_months
        )
        sellout_months = int(math.ceil(total_lots / monthly_absorption)) if total_lots and monthly_absorption else 0
        last_close_month = first_close_month + max(0, sellout_months - 1)
        milestones = [
            ("Land Close", 0, str(payload.get("land_close_date") or "")),
            ("First Start", months_to_first_home_start, ""),
            ("Sales Open", months_to_sales_open, ""),
            ("First Close", first_close_month, ""),
            ("Sellout", last_close_month, ""),
        ]
        horizon = max([item[1] for item in milestones] + [int(float(item.get("month", 0) or 0)) for item in phases] + [1]) + 2
        self._draw_schedule_canvas(
            self.builder_schedule_canvas,
            phases=phases,
            milestones=milestones,
            horizon=horizon,
        )

    def _draw_result_schedule(self, result: dict[str, Any]) -> None:
        assumptions = result.get("assumptions", {})
        base_case = result.get("scenarios", {}).get("base_case", {})
        schedule = base_case.get("schedule", {})
        dates = schedule.get("date_summary") or {}
        phases = list(assumptions.get("land_purchase_events") or [])
        milestones = [
            ("Land Close", 0, str(dates.get("land_close_date") or "")),
            ("First Start", int(schedule.get("months_to_first_home_start", 0) or 0), str(dates.get("first_home_start_date") or "")),
            ("Sales Open", int(schedule.get("months_to_sales_open", 0) or 0), str(dates.get("sales_open_date") or "")),
            ("First Close", int(schedule.get("months_to_first_close", 0) or 0), str(dates.get("first_close_date") or "")),
            ("Last Close", int(schedule.get("months_to_last_close", 0) or 0), str(dates.get("last_close_date") or "")),
        ]
        horizon = max([item[1] for item in milestones] + [int(float(item.get("month", 0) or 0)) for item in phases] + [1]) + 2
        self._draw_schedule_canvas(
            self.result_schedule_canvas,
            phases=phases,
            milestones=milestones,
            horizon=horizon,
        )

    def _populate_decision_tab(self, result: dict[str, Any]) -> None:
        score = result.get("deal_score") or {}
        lines = [
            f"Recommendation: {str(result.get('recommendation') or '').upper()}",
            f"Deal Score: {score.get('score', '-')}/100 ({str(score.get('band') or '').replace('_', ' ')})",
            "",
        ]

        reasons = result.get("recommendation_reasons") or []
        lines.append("Why:")
        for item in reasons:
            lines.append(f"- {item}")

        risk_flags = result.get("risk_flags") or []
        lines.append("")
        lines.append("Risk Flags:")
        if risk_flags:
            for item in risk_flags:
                lines.append(f"- {item}")
        else:
            lines.append("- None detected in notes.")

        upside_flags = result.get("upside_flags") or []
        lines.append("")
        lines.append("Upside Flags:")
        if upside_flags:
            for item in upside_flags:
                lines.append(f"- {item}")
        else:
            lines.append("- None detected in notes.")

        model_signal = result.get("model_signal")
        if model_signal:
            lines.append("")
            lines.append("Model Signal:")
            lines.append(f"- Predicted value: {_format_currency(model_signal.get('prediction'))}")
            lines.append(
                f"- Variance to actual land: {_format_currency(model_signal.get('variance_to_actual_land_cost'))}"
            )
            lines.append(
                f"- Variance to residual: {_format_currency(model_signal.get('variance_to_residual_land_value'))}"
            )

        self.decision_text.configure(state="normal")
        self.decision_text.delete("1.0", "end")
        self.decision_text.insert("1.0", "\n".join(lines))
        self.decision_text.configure(state="disabled")

        for item in self.hurdle_tree.get_children():
            self.hurdle_tree.delete(item)

        for scenario_name in ("base_case", "downside_case", "severe_downside_case"):
            scenario_hurdles = result.get("hurdles", {}).get(scenario_name)
            if not scenario_hurdles:
                continue
            self.hurdle_tree.insert(
                "",
                "end",
                values=(
                    _scenario_label(scenario_name),
                    "PASS" if scenario_hurdles.get("gross_margin") else "FAIL",
                    "PASS" if scenario_hurdles.get("pre_gna_margin") else "FAIL",
                    "PASS" if scenario_hurdles.get("irr") else "FAIL",
                    "PASS" if scenario_hurdles.get("residual_land_value") else "FAIL",
                ),
            )

    def _populate_series_tab(self, result: dict[str, Any]) -> None:
        for item in self.series_tree.get_children():
            self.series_tree.delete(item)

        base_case = result.get("scenarios", {}).get("base_case", {})
        for series in base_case.get("series_metrics", []):
            self.series_tree.insert(
                "",
                "end",
                values=(
                    series.get("name"),
                    _format_number(series.get("lots"), 0),
                    _format_pct(series.get("mix_pct")),
                    _format_currency(series.get("net_sales_price_per_unit")),
                    _format_currency(series.get("build_cost_per_unit")),
                    _format_currency(series.get("revenue_total")),
                ),
            )

        schedule = base_case.get("schedule", {})
        dates = schedule.get("date_summary") or {}
        cash = base_case.get("cash_flow_metrics", {})
        schedule_lines = [
            f"Monthly absorption: {_format_number(schedule.get('monthly_absorption'), 2)}",
            f"Months to first home start: {_format_number(schedule.get('months_to_first_home_start'), 0)}",
            f"Months to sales open: {_format_number(schedule.get('months_to_sales_open'), 0)}",
            f"Months to first close: {_format_number(schedule.get('months_to_first_close'), 0)}",
            f"Months to last close: {_format_number(schedule.get('months_to_last_close'), 0)}",
            f"Sellout months: {_format_number(schedule.get('sellout_months'), 0)}",
            f"Total project months: {_format_number(schedule.get('total_project_months'), 0)}",
            f"Peak investment month: {_format_number(cash.get('peak_investment_month'), 0)}",
            f"Months to positive net cash: {_format_number(cash.get('months_to_positive_net_cash'), 0)}",
        ]
        if dates:
            schedule_lines.extend(
                [
                    "",
                    f"Land close date: {dates.get('land_close_date')}",
                    f"First home start date: {dates.get('first_home_start_date')}",
                    f"Sales open date: {dates.get('sales_open_date')}",
                    f"First close date: {dates.get('first_close_date')}",
                    f"Last close date: {dates.get('last_close_date')}",
                    f"Peak investment date: {dates.get('peak_investment_date')}",
                ]
            )

        self.schedule_text.configure(state="normal")
        self.schedule_text.delete("1.0", "end")
        self.schedule_text.insert("1.0", "\n".join(schedule_lines))
        self.schedule_text.configure(state="disabled")
        self._draw_result_schedule(result)

    def _populate_market_tab(self, result: dict[str, Any]) -> None:
        market = result.get("market_intelligence")
        if not market:
            self.market_text.configure(state="normal")
            self.market_text.delete("1.0", "end")
            self.market_text.insert(
                "1.0",
                "No competitor or resale data was supplied. Add market rows in the builder to benchmark price and pace.",
            )
            self.market_text.configure(state="disabled")
            self.market_revenue_canvas.delete("all")
            self.market_resale_canvas.delete("all")
            return

        subject = market.get("subject", {})
        competitors = market.get("competitors", {})
        resales = market.get("resales", {})
        positioning = market.get("positioning", {})

        lines = [
            f"Subject net price: {_format_currency(subject.get('average_net_price'))}",
            f"Subject price / sqft: {_format_currency(subject.get('price_psf'))}",
            f"Subject monthly revenue velocity: {_format_currency(subject.get('revenue_per_month'))}",
            "",
            f"Competitor average price: {_format_currency(competitors.get('average_price'))}",
            f"Competitor average pace: {_format_number(competitors.get('average_absorption'), 2)} / month",
            f"Resale average price / sqft: {_format_currency(resales.get('average_price_psf'))}",
            "",
            f"Price vs competitors: {_format_pct(positioning.get('subject_vs_competitor_price_pct'))}",
            f"Pace vs competitors: {_format_pct(positioning.get('subject_vs_competitor_absorption_pct'))}",
            f"PPSF vs resale: {_format_pct(positioning.get('subject_vs_resale_psf_pct'))}",
        ]
        if market.get("risk_flags"):
            lines.extend(["", "Market Risks:"])
            for item in market["risk_flags"]:
                lines.append(f"- {item}")
        if market.get("upside_flags"):
            lines.extend(["", "Market Support:"])
            for item in market["upside_flags"]:
                lines.append(f"- {item}")

        self.market_text.configure(state="normal")
        self.market_text.delete("1.0", "end")
        self.market_text.insert("1.0", "\n".join(lines))
        self.market_text.configure(state="disabled")

        self._draw_market_revenue_chart(market)
        self._draw_market_resale_chart(market)

    def _draw_market_revenue_chart(self, market: dict[str, Any]) -> None:
        canvas = self.market_revenue_canvas
        canvas.delete("all")
        width = max(canvas.winfo_width(), 520)
        height = max(canvas.winfo_height(), 190)
        left = 44
        bottom = height - 26
        bar_width = 72
        gap = 24

        data = [("Subject", float(market["subject"].get("revenue_per_month", 0) or 0))]
        for item in list(market.get("competitors", {}).get("rows") or [])[:4]:
            data.append((str(item.get("name") or "Comp"), float(item.get("revenue_per_month", 0) or 0)))
        if not data:
            return

        max_value = max(value for _, value in data) or 1.0
        start_x = left + max(0, (width - left - 18 - (len(data) * bar_width + (len(data) - 1) * gap)) / 2)
        colors = [COLORS["accent"], COLORS["navy"], COLORS["navy_soft"], COLORS["green"], COLORS["amber"]]

        canvas.create_line(left, bottom, width - 18, bottom, fill=COLORS["line"], width=2)
        for index, (label, value) in enumerate(data):
            x1 = start_x + index * (bar_width + gap)
            x2 = x1 + bar_width
            bar_height = 0 if max_value <= 0 else (value / max_value) * (height - 60)
            y1 = bottom - bar_height
            canvas.create_rectangle(x1, y1, x2, bottom, fill=colors[index % len(colors)], outline="")
            canvas.create_text((x1 + x2) / 2, y1 - 12, text=_format_currency(value), fill=COLORS["ink"], font=("Segoe UI", 8, "bold"))
            canvas.create_text((x1 + x2) / 2, bottom + 14, text=label[:14], fill=COLORS["muted"], font=("Segoe UI", 8))

    def _draw_market_resale_chart(self, market: dict[str, Any]) -> None:
        canvas = self.market_resale_canvas
        canvas.delete("all")
        width = max(canvas.winfo_width(), 520)
        height = max(canvas.winfo_height(), 210)
        left = 54
        right = width - 20
        top = 16
        bottom = height - 34

        rows = list(market.get("resales", {}).get("rows") or [])
        if not rows:
            canvas.create_text(
                width / 2,
                height / 2,
                text="Add resale comps to plot price / sqft support.",
                fill=COLORS["muted"],
                font=("Segoe UI", 10),
            )
            return

        sqft_values = [float(item.get("sqft", 0) or 0) for item in rows if float(item.get("sqft", 0) or 0) > 0]
        ppsf_values = [float(item.get("price_psf", 0) or 0) for item in rows if float(item.get("price_psf", 0) or 0) > 0]
        if not sqft_values or not ppsf_values:
            return

        min_sqft = min(sqft_values)
        max_sqft = max(sqft_values)
        min_ppsf = min(ppsf_values)
        max_ppsf = max(ppsf_values)
        if max_sqft == min_sqft:
            max_sqft += 1
        if max_ppsf == min_ppsf:
            max_ppsf += 1

        canvas.create_line(left, bottom, right, bottom, fill=COLORS["line"], width=2)
        canvas.create_line(left, top, left, bottom, fill=COLORS["line"], width=2)

        def x_for(value: float) -> float:
            return left + ((value - min_sqft) / (max_sqft - min_sqft)) * (right - left)

        def y_for(value: float) -> float:
            return bottom - ((value - min_ppsf) / (max_ppsf - min_ppsf)) * (bottom - top)

        canvas.create_text(left, top - 4, text=f"${min_ppsf:,.0f}/sf", anchor="w", fill=COLORS["muted"], font=("Segoe UI", 8))
        canvas.create_text(left, bottom + 16, text=f"{min_sqft:,.0f} sf", anchor="w", fill=COLORS["muted"], font=("Segoe UI", 8))
        canvas.create_text(right, bottom + 16, text=f"{max_sqft:,.0f} sf", anchor="e", fill=COLORS["muted"], font=("Segoe UI", 8))

        subject_sqft = float(market["subject"].get("average_sqft", 0) or 0)
        subject_ppsf = float(market["subject"].get("price_psf", 0) or 0)

        for item in rows:
            sqft = float(item.get("sqft", 0) or 0)
            ppsf = float(item.get("price_psf", 0) or 0)
            if sqft <= 0 or ppsf <= 0:
                continue
            x = x_for(sqft)
            y = y_for(ppsf)
            canvas.create_oval(x - 4, y - 4, x + 4, y + 4, fill=COLORS["navy"], outline="")

        if subject_sqft > 0 and subject_ppsf > 0:
            x = x_for(subject_sqft)
            y = y_for(subject_ppsf)
            canvas.create_oval(x - 7, y - 7, x + 7, y + 7, fill=COLORS["accent"], outline="")
            canvas.create_text(x + 10, y - 10, text="Subject", anchor="w", fill=COLORS["accent"], font=("Segoe UI", 8, "bold"))

    def _populate_sensitivity_tab(self, result: dict[str, Any]) -> None:
        matrix = result.get("sensitivity_matrix")
        if not matrix:
            self.sensitivity_canvas.delete("all")
            self.sensitivity_summary_label.configure(text="Sensitivity data is unavailable.")
            return

        canvas = self.sensitivity_canvas
        canvas.delete("all")
        width = max(canvas.winfo_width(), 420)
        height = max(canvas.winfo_height(), 260)
        left = 92
        top = 42
        cell_w = 74
        cell_h = 42

        price_labels = list(matrix.get("price_deltas_pct") or [])
        rows = list(matrix.get("rows") or [])

        canvas.create_text(
            left + (len(price_labels) * cell_w) / 2,
            16,
            text="Sales Price Delta",
            fill=COLORS["navy"],
            font=("Segoe UI", 9, "bold"),
        )
        canvas.create_text(
            28,
            top + (len(rows) * cell_h) / 2,
            text="Cost\nDelta",
            fill=COLORS["navy"],
            font=("Segoe UI", 9, "bold"),
            justify="center",
        )

        for col, price_delta in enumerate(price_labels):
            canvas.create_text(
                left + col * cell_w + cell_w / 2,
                top - 16,
                text=_format_pct(price_delta),
                fill=COLORS["muted"],
                font=("Segoe UI", 8, "bold"),
            )

        clear_count = 0
        fail_count = 0
        for row_index, row in enumerate(rows):
            cost_delta = row.get("cost_delta_pct")
            canvas.create_text(
                left - 12,
                top + row_index * cell_h + cell_h / 2,
                text=_format_pct(cost_delta),
                anchor="e",
                fill=COLORS["muted"],
                font=("Segoe UI", 8, "bold"),
            )
            for col_index, cell in enumerate(row.get("cells", [])):
                x1 = left + col_index * cell_w
                y1 = top + row_index * cell_h
                x2 = x1 + cell_w - 4
                y2 = y1 + cell_h - 4
                status = cell.get("status")
                if status == "clear":
                    fill = COLORS["green_soft"]
                    clear_count += 1
                elif status == "watch":
                    fill = COLORS["amber_soft"]
                else:
                    fill = COLORS["red_soft"]
                    fail_count += 1
                canvas.create_rectangle(x1, y1, x2, y2, fill=fill, outline=COLORS["line"])
                canvas.create_text(
                    (x1 + x2) / 2,
                    y1 + 14,
                    text=_format_pct(cell.get("pre_gna_margin_pct")),
                    fill=COLORS["ink"],
                    font=("Segoe UI", 8, "bold"),
                )
                canvas.create_text(
                    (x1 + x2) / 2,
                    y1 + 30,
                    text=_format_pct(cell.get("irr_pre_gna_pct")),
                    fill=COLORS["muted"],
                    font=("Segoe UI", 7),
                )

        summary = (
            f"{clear_count} clear cells, {fail_count} fail cells. "
            "Top line in each cell is pre-G&A margin; second line is IRR."
        )
        self.sensitivity_summary_label.configure(text=summary)

    def _populate_memo_tab(self, result: dict[str, Any]) -> None:
        memo = result.get("investment_committee_memo") or {}
        score = result.get("deal_score") or {}
        lines = [
            str(memo.get("headline") or "Investment Committee Memo"),
            "",
            str(memo.get("summary") or ""),
            "",
            f"Deal score: {score.get('score', '-')}/100 ({str(score.get('band') or '').replace('_', ' ')})",
            "",
            "Strengths:",
        ]
        for item in memo.get("strengths", []):
            lines.append(f"- {item}")
        lines.extend(["", "Risks:"])
        for item in memo.get("risks", []):
            lines.append(f"- {item}")
        lines.extend(["", "Next Steps:"])
        for item in memo.get("next_steps", []):
            lines.append(f"- {item}")
        lines.extend(["", "Reason Snapshot:"])
        for item in memo.get("reason_snapshot", []):
            lines.append(f"- {item}")
        self._set_scrolled_text(self.memo_text, "\n".join(lines))

    def _render_raw_result(self, result: Any) -> None:
        display_result = result[0] if isinstance(result, list) and result and isinstance(result[0], dict) else result
        if not isinstance(display_result, dict):
            self._set_scrolled_text(self.raw_result_text, "No readable deal report is available.")
            return

        base_case = display_result.get("scenarios", {}).get("base_case", {})
        investment = base_case.get("investment_summary", {})
        income = base_case.get("income_statement", {})
        cash = base_case.get("cash_flow_metrics", {})
        market = display_result.get("market_intelligence") or {}
        memo = display_result.get("investment_committee_memo") or {}
        assumptions = display_result.get("assumptions") or {}

        lines = [
            str(memo.get("headline") or f"{display_result.get('community_name', 'Deal')} Deep Dive"),
            "",
            str(memo.get("summary") or ""),
            "",
            "Investment Summary",
            f"- Gross acres: {_format_number(investment.get('gross_acres'), 1)}",
            f"- Total lots: {_format_number(investment.get('total_lots'), 0)}",
            f"- Land cost / lot: {_format_currency(investment.get('land_cost_per_lot'))}",
            f"- Finished lot cost / lot: {_format_currency(investment.get('finished_lot_cost_per_lot'))}",
            f"- Residual support / lot: {_format_currency(investment.get('residual_max_land_cost_per_lot'))}",
            f"- Land gap to residual: {_format_currency(investment.get('land_value_gap_to_residual'))}",
            "",
            "Operating Results",
            f"- Revenue: {_format_currency(income.get('revenue_total'))}",
            f"- Gross margin: {_format_pct(income.get('gross_margin_pct'))}",
            f"- Pre-G&A margin: {_format_pct(income.get('pre_gna_margin_pct'))}",
            f"- Peak investment: {_format_currency(cash.get('peak_investment'))}",
            f"- IRR: {_format_pct(cash.get('irr_pre_gna_pct'))}",
            "",
            "Market Position",
            f"- Competitor communities: {_format_number((market.get('competitors') or {}).get('count'), 0)}",
            f"- Resale comps: {_format_number((market.get('resales') or {}).get('count'), 0)}",
            f"- Subject vs competitor price: {_format_pct((market.get('positioning') or {}).get('subject_vs_competitor_price_pct'))}",
            f"- Subject vs competitor pace: {_format_pct((market.get('positioning') or {}).get('subject_vs_competitor_absorption_pct'))}",
            f"- Subject vs resale PPSF: {_format_pct((market.get('positioning') or {}).get('subject_vs_resale_psf_pct'))}",
            "",
            "Assumptions Snapshot",
            f"- Monthly absorption: {_format_number(assumptions.get('monthly_absorption'), 2)}",
            f"- Build cycle: {_format_number(assumptions.get('build_cycle_months'), 0)} months",
            f"- First start: month {_format_number(assumptions.get('months_to_first_home_start'), 0)}",
            f"- Sales open: month {_format_number(assumptions.get('months_to_sales_open'), 0)}",
            f"- First close: month {_format_number(assumptions.get('months_to_first_close'), 0)}",
            "",
            "Recommendation Drivers",
        ]
        for item in display_result.get("recommendation_reasons", [])[:10]:
            lines.append(f"- {item}")

        self._set_scrolled_text(self.raw_result_text, "\n".join(lines))

    def _on_close(self) -> None:
        if self.refresh_job is not None:
            self.root.after_cancel(self.refresh_job)
            self.refresh_job = None
        self.request_queue.put(None)
        self.root.destroy()

    def run(self) -> None:
        self.root.mainloop()


def main() -> None:
    LandUnderwriterDesktopApp().run()


if __name__ == "__main__":
    main()
