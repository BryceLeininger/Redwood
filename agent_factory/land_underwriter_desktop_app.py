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
        self._build_series_section(body)
        self._build_operations_section(body)
        self._build_targets_section(body)
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
            subtitle="Use the simple fields for most deals. If you have a staged takedown, enter one line per event.",
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

        events_frame = tk.Frame(body, bg=COLORS["card"])
        events_frame.grid(row=3, column=0, columnspan=3, sticky="ew", pady=(12, 0))
        events_frame.grid_columnconfigure(0, weight=1)
        tk.Label(
            events_frame,
            text="Takedown Events",
            bg=COLORS["card"],
            fg=COLORS["ink"],
            font=("Segoe UI", 10, "bold"),
        ).grid(row=0, column=0, sticky="w")
        tk.Label(
            events_frame,
            text="One event per line: month,lots,price_per_lot  Example: 0,25,67500",
            bg=COLORS["card"],
            fg=COLORS["muted"],
            font=("Segoe UI", 9),
        ).grid(row=1, column=0, sticky="w", pady=(2, 6))
        self.events_text = ScrolledText(
            events_frame,
            height=4,
            wrap="none",
            font=("Consolas", 10),
            bg="#FFFDFC",
            fg=COLORS["ink"],
            insertbackground=COLORS["ink"],
            relief="flat",
            borderwidth=1,
        )
        self.events_text.grid(row=2, column=0, sticky="ew")

    def _build_series_section(self, parent: tk.Widget) -> None:
        body = self._create_section(
            parent,
            title="3. Product Mix Builder",
            subtitle="Rows with zero lots are ignored. This stays fast for common underwriting, while Advanced JSON handles edge-case overrides.",
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
            title="4. Operating Plan",
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
            title="5. Returns And Stress Cases",
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
            title="6. Notes And Diligence Signals",
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
        ):
            card = tk.Frame(panel, bg=COLORS["card_alt"], padx=12, pady=10, highlightbackground=COLORS["line"], highlightthickness=1)
            card.pack(fill="x", pady=(0, 10))
            tk.Label(card, text=title, bg=COLORS["card_alt"], fg=COLORS["muted"], font=("Segoe UI", 9, "bold")).pack(anchor="w")
            value = tk.Label(card, text="-", bg=COLORS["card_alt"], fg=COLORS["ink"], font=("Aptos", 16, "bold"))
            value.pack(anchor="w", pady=(4, 0))
            note = tk.Label(card, text="", bg=COLORS["card_alt"], fg=COLORS["muted"], font=("Segoe UI", 9))
            note.pack(anchor="w")
            self.overview_cards[key] = (value, note)

        tips = tk.Frame(panel, bg=COLORS["accent_soft"], padx=12, pady=12, highlightbackground="#E5C9B6", highlightthickness=1)
        tips.pack(fill="both", expand=True)
        tk.Label(tips, text="Workflow", bg=COLORS["accent_soft"], fg=COLORS["navy"], font=("Segoe UI", 10, "bold")).pack(anchor="w")
        guidance = (
            "1. Use the builder for fast screening.\n"
            "2. Open Advanced JSON only when you need staged takedowns or custom per-series overrides.\n"
            "3. Press Ctrl+R to run, Ctrl+S to save, Ctrl+O to open.\n"
            "4. Review Results Dashboard before deciding whether to pursue, negotiate, or pass."
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
        raw_tab = tk.Frame(right_tabs, bg=COLORS["bg"])
        right_tabs.add(decision_tab, text="Decision")
        right_tabs.add(series_tab, text="Series + Schedule")
        right_tabs.add(raw_tab, text="Raw JSON")

        self._build_decision_tab(decision_tab)
        self._build_series_tab(series_tab)
        self._build_raw_result_tab(raw_tab)

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
        parent.grid_rowconfigure(3, weight=1)

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

        tk.Label(parent, text="Base-Case Schedule", bg=COLORS["bg"], fg=COLORS["navy"], font=("Segoe UI", 10, "bold")).grid(row=2, column=0, sticky="w", pady=(12, 4))
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
        self.schedule_text.grid(row=3, column=0, sticky="nsew")
        self.schedule_text.configure(state="disabled")

    def _build_raw_result_tab(self, parent: tk.Widget) -> None:
        parent.grid_columnconfigure(0, weight=1)
        parent.grid_rowconfigure(0, weight=1)
        self.raw_result_text = ScrolledText(
            parent,
            wrap="none",
            font=("Consolas", 10),
            bg=COLORS["card"],
            fg=COLORS["ink"],
            insertbackground=COLORS["ink"],
            relief="flat",
            borderwidth=1,
        )
        self.raw_result_text.grid(row=0, column=0, sticky="nsew")
        self.raw_result_text.configure(state="disabled")

    def _build_json_tab(self) -> None:
        self.json_tab.grid_columnconfigure(0, weight=1)
        self.json_tab.grid_rowconfigure(1, weight=1)

        toolbar = tk.Frame(self.json_tab, bg=COLORS["bg"])
        toolbar.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        self._make_button(toolbar, "Builder -> JSON", self._sync_builder_to_json, "secondary").grid(row=0, column=0, padx=(0, 8))
        self._make_button(toolbar, "JSON -> Builder", self._apply_json_to_builder, "secondary").grid(row=0, column=1, padx=(0, 8))
        self._make_button(toolbar, "Run JSON", self._run_json_request, "primary").grid(row=0, column=2)

        self.json_text = ScrolledText(
            self.json_tab,
            wrap="none",
            font=("Consolas", 10),
            bg="#FFFDFC",
            fg=COLORS["ink"],
            insertbackground=COLORS["ink"],
            relief="flat",
            borderwidth=1,
        )
        self.json_text.grid(row=1, column=0, sticky="nsew")

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
