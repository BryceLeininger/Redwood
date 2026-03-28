"""Workbook-aligned underwriting workflow for homebuilder land acquisition deals."""
from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import date, datetime
from statistics import median
from typing import Any, Dict, List, Sequence

from .specialist_agent import SpecialistAgent

DEFAULT_SALES_COMMISSION_PCT = 0.02373404255319149
DEFAULT_CORPORATE_CHARGE_PCT = 0.037650943812901905
DEFAULT_CAPITALIZED_MARKETING_PER_LOT = 5524.0
DEFAULT_OTHER_HOUSE_COSTS_PER_UNIT = 20826.88
DEFAULT_INDIRECT_FIELD_OVERHEAD_PER_MONTH = 73982.5
DEFAULT_TARGET_GROSS_MARGIN_PCT = 0.21
DEFAULT_TARGET_PRE_GNA_MARGIN_PCT = 0.15
DEFAULT_TARGET_IRR_PCT = 0.20

POSITIVE_SIGNAL_WEIGHTS: Dict[str, int] = {
    "tentative map": 5,
    "final map": 8,
    "approved": 6,
    "entitled": 8,
    "utilities at site": 5,
    "finished lots": 9,
    "existing subdivision": 4,
    "growth corridor": 4,
    "strong demand": 5,
    "infill": 4,
    "shovel ready": 10,
}

RISK_SIGNAL_WEIGHTS: Dict[str, int] = {
    "annexation": 9,
    "brownfield": 12,
    "easement": 5,
    "entitlement risk": 8,
    "environmental": 7,
    "floodplain": 10,
    "grading": 5,
    "mitigation": 6,
    "offsite": 5,
    "raw land": 4,
    "remediation": 10,
    "rezone": 8,
    "septic": 9,
    "steep": 6,
    "utility extension": 8,
    "variance": 7,
    "wetlands": 10,
}


def _clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def _safe_div(numerator: float, denominator: float) -> float:
    if abs(denominator) < 1e-9:
        return 0.0
    return numerator / denominator


def _round_money(value: float) -> float:
    return round(float(value), 2)


def _round_ratio(value: float | None) -> float | None:
    if value is None:
        return None
    return round(float(value), 4)


def _ratio_from_value(value: Any, *, default: float = 0.0) -> float:
    if value is None or value == "":
        return default
    if isinstance(value, str):
        raw = value.strip()
        if not raw:
            return default
        is_percent = "%" in raw
        raw = raw.replace("%", "").replace("$", "").replace(",", "")
        parsed = float(raw)
        if is_percent or abs(parsed) > 1.0:
            return parsed / 100.0
        return parsed
    parsed = float(value)
    if abs(parsed) > 1.0:
        return parsed / 100.0
    return parsed


def _float_from_value(value: Any, *, default: float = 0.0) -> float:
    if value is None or value == "":
        return default
    if isinstance(value, str):
        raw = value.strip().replace("$", "").replace(",", "")
        if not raw:
            return default
        return float(raw)
    return float(value)


def _int_from_value(value: Any, *, default: int = 0) -> int:
    if value is None or value == "":
        return default
    return int(round(_float_from_value(value, default=float(default))))


def _bool_from_value(value: Any, *, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "y"}:
        return True
    if text in {"0", "false", "no", "n"}:
        return False
    return default


def _date_from_value(value: Any) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, date):
        return value
    return datetime.fromisoformat(str(value).strip()).date()


def _add_months(value: date, months: int) -> date:
    year = value.year + (value.month - 1 + months) // 12
    month = (value.month - 1 + months) % 12 + 1
    day = min(
        value.day,
        (
            31
            if month in {1, 3, 5, 7, 8, 10, 12}
            else 30
            if month in {4, 6, 9, 11}
            else 29
            if year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)
            else 28
        ),
    )
    return date(year, month, day)


def _allocate_evenly(
    cash_flows: List[float],
    total_amount: float,
    start_month: int,
    number_of_months: int,
) -> None:
    if abs(total_amount) < 1e-9 or number_of_months <= 0:
        return
    start_month = max(0, start_month)
    per_month = total_amount / float(number_of_months)
    for offset in range(number_of_months):
        index = start_month + offset
        if index >= len(cash_flows):
            cash_flows.extend([0.0] * (index - len(cash_flows) + 1))
        cash_flows[index] += per_month


def _find_signal_hits(text: str, catalog: Dict[str, int]) -> List[str]:
    lowered = text.lower()
    hits = [phrase for phrase in catalog if phrase in lowered]
    hits.sort(key=lambda item: (-catalog[item], item))
    return hits


def _monthly_irr(cash_flows: Sequence[float]) -> float | None:
    negatives = any(value < 0 for value in cash_flows)
    positives = any(value > 0 for value in cash_flows)
    if not negatives or not positives:
        return None

    def npv(rate: float) -> float:
        total = 0.0
        base = 1.0 + rate
        for index, value in enumerate(cash_flows):
            if index == 0 or value == 0:
                total += value
                continue
            try:
                discount = base**index
            except OverflowError:
                # Extremely large candidate rates make distant cash flows converge to zero.
                continue
            total += value / discount
        return total

    low = -0.9999
    high = 1.0
    npv_low = npv(low)
    npv_high = npv(high)

    expansion_count = 0
    while npv_low * npv_high > 0 and expansion_count < 20:
        high *= 2.0
        npv_high = npv(high)
        expansion_count += 1

    if npv_low * npv_high > 0:
        return None

    for _ in range(120):
        midpoint = (low + high) / 2.0
        npv_mid = npv(midpoint)
        if abs(npv_mid) < 1e-8:
            return midpoint
        if npv_low * npv_mid <= 0:
            high = midpoint
            npv_high = npv_mid
        else:
            low = midpoint
            npv_low = npv_mid

    return (low + high) / 2.0


def _annualize_monthly_rate(monthly_rate: float | None) -> float | None:
    if monthly_rate is None:
        return None
    try:
        return (1.0 + monthly_rate) ** 12 - 1.0
    except OverflowError:
        return None


def _closing_schedule(total_lots: float, monthly_absorption: float, first_close_month: int) -> List[tuple[int, float]]:
    monthly_absorption = max(0.25, monthly_absorption)
    sold = 0.0
    month = first_close_month
    schedule: List[tuple[int, float]] = []
    period = 1

    while sold < total_lots - 1e-9:
        cumulative_target = min(total_lots, monthly_absorption * period)
        closings = cumulative_target - sold
        if closings <= 1e-9:
            break
        schedule.append((month, closings))
        sold = cumulative_target
        month += 1
        period += 1

    if not schedule:
        schedule.append((first_close_month, total_lots))
    return schedule


@dataclass(frozen=True)
class ProductSeriesInput:
    name: str
    lots: float
    avg_sqft: float
    base_house_price: float
    lot_premium: float = 0.0
    options_pct: float = 0.0
    price_incentives_pct: float = 0.03
    mortgage_incentives_pct: float = 0.03
    direct_cost_psf: float = 90.0
    direct_cost_contingency_pct: float = 0.02
    permit_fees_per_unit: float = 75000.0
    tap_fees_per_unit: float = 20000.0
    other_vertical_costs_per_unit: float = 0.0
    move_up: bool = False

    @classmethod
    def from_dict(cls, payload: Dict[str, Any], *, default_name: str) -> "ProductSeriesInput":
        return cls(
            name=str(payload.get("name") or default_name).strip() or default_name,
            lots=_float_from_value(payload.get("lots"), default=0.0),
            avg_sqft=_float_from_value(payload.get("avg_sqft"), default=0.0),
            base_house_price=_float_from_value(payload.get("base_house_price"), default=0.0),
            lot_premium=_float_from_value(payload.get("lot_premium"), default=0.0),
            options_pct=_ratio_from_value(payload.get("options_pct"), default=0.0),
            price_incentives_pct=_ratio_from_value(payload.get("price_incentives_pct"), default=0.03),
            mortgage_incentives_pct=_ratio_from_value(payload.get("mortgage_incentives_pct"), default=0.03),
            direct_cost_psf=_float_from_value(payload.get("direct_cost_psf"), default=90.0),
            direct_cost_contingency_pct=_ratio_from_value(
                payload.get("direct_cost_contingency_pct"),
                default=0.02,
            ),
            permit_fees_per_unit=_float_from_value(payload.get("permit_fees_per_unit"), default=75000.0),
            tap_fees_per_unit=_float_from_value(payload.get("tap_fees_per_unit"), default=20000.0),
            other_vertical_costs_per_unit=_float_from_value(
                payload.get("other_vertical_costs_per_unit"),
                default=0.0,
            ),
            move_up=_bool_from_value(payload.get("move_up"), default=False),
        )

    def net_sales_price_per_unit(self, *, price_multiplier: float = 1.0) -> float:
        base_price = self.base_house_price * price_multiplier
        options_value = base_price * self.options_pct
        incentive_value = base_price * (self.price_incentives_pct + self.mortgage_incentives_pct)
        premium_value = self.lot_premium * price_multiplier
        return base_price + premium_value + options_value - incentive_value

    def build_cost_per_unit(self, *, cost_multiplier: float = 1.0) -> float:
        direct_cost = self.direct_cost_psf * self.avg_sqft * cost_multiplier
        contingency = direct_cost * self.direct_cost_contingency_pct
        permit_fees = self.permit_fees_per_unit * cost_multiplier
        tap_fees = self.tap_fees_per_unit * cost_multiplier
        other_vertical = self.other_vertical_costs_per_unit * cost_multiplier
        return direct_cost + contingency + permit_fees + tap_fees + other_vertical


@dataclass(frozen=True)
class LandPurchaseEvent:
    month: int
    lots: float
    price_per_lot: float

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "LandPurchaseEvent":
        return cls(
            month=max(0, _int_from_value(payload.get("month"), default=0)),
            lots=max(0.0, _float_from_value(payload.get("lots"), default=0.0)),
            price_per_lot=max(0.0, _float_from_value(payload.get("price_per_lot"), default=0.0)),
        )

    def total_cost(self) -> float:
        return self.lots * self.price_per_lot


@dataclass(frozen=True)
class DealScenario:
    name: str
    sales_price_delta_pct: float
    cost_delta_pct: float
    absorption_delta_pct: float


@dataclass(frozen=True)
class LandDealInput:
    community_name: str
    division: str
    market: str
    notes: str
    gross_acres: float
    takedown_structure: str
    product_series: Sequence[ProductSeriesInput]
    land_purchase_price_per_lot: float
    land_purchase_events: Sequence[LandPurchaseEvent]
    land_brokerage_and_closing_costs_total: float
    earnest_money_deposit: float
    deposit_credit_at_close: bool
    land_development_cost_total: float
    project_management_cost_total: float
    other_land_costs_total: float
    capitalized_marketing_total: float | None
    capitalized_marketing_per_lot: float | None
    architecture_engineering_total: float
    indirect_field_overhead_total: float | None
    indirect_field_overhead_per_month: float | None
    indirect_field_overhead_per_lot: float | None
    sales_commission_pct: float
    home_sale_excise_tax_pct: float
    corporate_charge_pct: float
    other_house_costs_per_unit: float
    monthly_absorption: float
    build_cycle_months: int
    months_to_first_home_start: int
    months_to_sales_open: int
    months_to_first_close: int | None
    site_improvement_spend_months: int | None
    land_close_date: date | None
    target_gross_margin_pct: float
    target_pre_gna_margin_pct: float
    target_irr_pct: float
    downside_sales_price_delta_pct: float
    downside_cost_delta_pct: float
    downside_absorption_delta_pct: float
    severe_downside_sales_price_delta_pct: float
    severe_downside_cost_delta_pct: float
    severe_downside_absorption_delta_pct: float

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "LandDealInput":
        raw_series = payload.get("product_series")
        if raw_series is None:
            raw_series = [
                {
                    "name": payload.get("product_type") or "Product Series A",
                    "lots": payload.get("lots") or payload.get("lot_count"),
                    "avg_sqft": payload.get("avg_sqft"),
                    "base_house_price": payload.get("base_house_price"),
                    "lot_premium": payload.get("lot_premium"),
                    "options_pct": payload.get("options_pct"),
                    "price_incentives_pct": payload.get("price_incentives_pct"),
                    "mortgage_incentives_pct": payload.get("mortgage_incentives_pct"),
                    "direct_cost_psf": payload.get("direct_cost_psf"),
                    "direct_cost_contingency_pct": payload.get("direct_cost_contingency_pct"),
                    "permit_fees_per_unit": payload.get("permit_fees_per_unit"),
                    "tap_fees_per_unit": payload.get("tap_fees_per_unit"),
                    "other_vertical_costs_per_unit": payload.get("other_vertical_costs_per_unit"),
                    "move_up": payload.get("move_up"),
                }
            ]

        product_series = [
            ProductSeriesInput.from_dict(item, default_name=f"Product Series {index}")
            for index, item in enumerate(raw_series, start=1)
        ]
        valid_series = [item for item in product_series if item.lots > 0]
        if not valid_series:
            raise ValueError("At least one product series with a positive lot count is required.")

        total_lots = sum(item.lots for item in valid_series)
        raw_events = (
            payload.get("land_purchase_events")
            or payload.get("schedule_phases")
            or payload.get("takedown_schedule")
            or []
        )
        purchase_events = [LandPurchaseEvent.from_dict(item) for item in raw_events]
        purchase_events = [item for item in purchase_events if item.lots > 0 and item.price_per_lot > 0]

        land_purchase_price_per_lot = _float_from_value(payload.get("land_purchase_price_per_lot"), default=0.0)
        if not purchase_events:
            if land_purchase_price_per_lot <= 0:
                raise ValueError("Provide land_purchase_price_per_lot or land_purchase_events.")
            purchase_events = [
                LandPurchaseEvent(
                    month=0,
                    lots=total_lots,
                    price_per_lot=land_purchase_price_per_lot,
                )
            ]

        purchase_event_lots = sum(item.lots for item in purchase_events)
        if abs(purchase_event_lots - total_lots) > 1e-6:
            raise ValueError("Land purchase events must cover the same total lots as the product series mix.")

        if land_purchase_price_per_lot <= 0:
            weighted_land_cost = sum(item.total_cost() for item in purchase_events)
            land_purchase_price_per_lot = _safe_div(weighted_land_cost, total_lots)

        return cls(
            community_name=str(payload.get("community_name") or "Unnamed Community").strip() or "Unnamed Community",
            division=str(payload.get("division") or payload.get("market") or "").strip(),
            market=str(payload.get("market") or payload.get("division") or "").strip(),
            notes=_clean_text(str(payload.get("notes") or "")),
            gross_acres=max(0.0, _float_from_value(payload.get("gross_acres"), default=0.0)),
            takedown_structure=str(payload.get("takedown_structure") or "bulk").strip() or "bulk",
            product_series=valid_series,
            land_purchase_price_per_lot=land_purchase_price_per_lot,
            land_purchase_events=purchase_events,
            land_brokerage_and_closing_costs_total=_float_from_value(
                payload.get("land_brokerage_and_closing_costs_total"),
                default=0.0,
            ),
            earnest_money_deposit=_float_from_value(payload.get("earnest_money_deposit"), default=0.0),
            deposit_credit_at_close=_bool_from_value(payload.get("deposit_credit_at_close"), default=True),
            land_development_cost_total=_float_from_value(payload.get("land_development_cost_total"), default=0.0),
            project_management_cost_total=_float_from_value(
                payload.get("project_management_cost_total"),
                default=0.0,
            ),
            other_land_costs_total=_float_from_value(payload.get("other_land_costs_total"), default=0.0),
            capitalized_marketing_total=(
                None
                if payload.get("capitalized_marketing_total") in (None, "")
                else _float_from_value(payload.get("capitalized_marketing_total"), default=0.0)
            ),
            capitalized_marketing_per_lot=(
                None
                if payload.get("capitalized_marketing_per_lot") in (None, "")
                else _float_from_value(payload.get("capitalized_marketing_per_lot"), default=0.0)
            ),
            architecture_engineering_total=_float_from_value(
                payload.get("architecture_engineering_total"),
                default=0.0,
            ),
            indirect_field_overhead_total=(
                None
                if payload.get("indirect_field_overhead_total") in (None, "")
                else _float_from_value(payload.get("indirect_field_overhead_total"), default=0.0)
            ),
            indirect_field_overhead_per_month=(
                None
                if payload.get("indirect_field_overhead_per_month") in (None, "")
                else _float_from_value(payload.get("indirect_field_overhead_per_month"), default=0.0)
            ),
            indirect_field_overhead_per_lot=(
                None
                if payload.get("indirect_field_overhead_per_lot") in (None, "")
                else _float_from_value(payload.get("indirect_field_overhead_per_lot"), default=0.0)
            ),
            sales_commission_pct=_ratio_from_value(
                payload.get("sales_commission_pct"),
                default=DEFAULT_SALES_COMMISSION_PCT,
            ),
            home_sale_excise_tax_pct=_ratio_from_value(payload.get("home_sale_excise_tax_pct"), default=0.0),
            corporate_charge_pct=_ratio_from_value(
                payload.get("corporate_charge_pct"),
                default=DEFAULT_CORPORATE_CHARGE_PCT,
            ),
            other_house_costs_per_unit=_float_from_value(
                payload.get("other_house_costs_per_unit"),
                default=DEFAULT_OTHER_HOUSE_COSTS_PER_UNIT,
            ),
            monthly_absorption=max(0.25, _float_from_value(payload.get("monthly_absorption"), default=3.0)),
            build_cycle_months=max(1, _int_from_value(payload.get("build_cycle_months"), default=5)),
            months_to_first_home_start=max(
                0,
                _int_from_value(payload.get("months_to_first_home_start"), default=6),
            ),
            months_to_sales_open=max(
                0,
                _int_from_value(payload.get("months_to_sales_open"), default=9),
            ),
            months_to_first_close=(
                None
                if payload.get("months_to_first_close") in (None, "")
                else max(0, _int_from_value(payload.get("months_to_first_close"), default=0))
            ),
            site_improvement_spend_months=(
                None
                if payload.get("site_improvement_spend_months") in (None, "")
                else max(1, _int_from_value(payload.get("site_improvement_spend_months"), default=1))
            ),
            land_close_date=_date_from_value(payload.get("land_close_date")),
            target_gross_margin_pct=_ratio_from_value(
                payload.get("target_gross_margin_pct"),
                default=DEFAULT_TARGET_GROSS_MARGIN_PCT,
            ),
            target_pre_gna_margin_pct=_ratio_from_value(
                payload.get("target_pre_gna_margin_pct"),
                default=DEFAULT_TARGET_PRE_GNA_MARGIN_PCT,
            ),
            target_irr_pct=_ratio_from_value(payload.get("target_irr_pct"), default=DEFAULT_TARGET_IRR_PCT),
            downside_sales_price_delta_pct=_ratio_from_value(
                payload.get("downside_sales_price_delta_pct"),
                default=-0.05,
            ),
            downside_cost_delta_pct=_ratio_from_value(payload.get("downside_cost_delta_pct"), default=0.05),
            downside_absorption_delta_pct=_ratio_from_value(
                payload.get("downside_absorption_delta_pct"),
                default=-0.15,
            ),
            severe_downside_sales_price_delta_pct=_ratio_from_value(
                payload.get("severe_downside_sales_price_delta_pct"),
                default=-0.10,
            ),
            severe_downside_cost_delta_pct=_ratio_from_value(
                payload.get("severe_downside_cost_delta_pct"),
                default=0.10,
            ),
            severe_downside_absorption_delta_pct=_ratio_from_value(
                payload.get("severe_downside_absorption_delta_pct"),
                default=-0.25,
            ),
        )

    @property
    def total_lots(self) -> float:
        return sum(item.lots for item in self.product_series)

    @property
    def first_close_month(self) -> int:
        if self.months_to_first_close is not None:
            return self.months_to_first_close
        return self.months_to_first_home_start + self.build_cycle_months

    def capitalized_marketing_total_value(self) -> float:
        if self.capitalized_marketing_total is not None:
            return self.capitalized_marketing_total
        if self.capitalized_marketing_per_lot is not None:
            return self.capitalized_marketing_per_lot * self.total_lots
        return DEFAULT_CAPITALIZED_MARKETING_PER_LOT * self.total_lots


class LandDealUnderwriter:
    """Applies workbook-style underwriting logic plus optional ML deal context."""

    def __init__(self, specialist: SpecialistAgent | None = None) -> None:
        self.specialist = specialist

    def underwrite(self, payload: Dict[str, Any] | LandDealInput) -> Dict[str, Any]:
        request = payload if isinstance(payload, LandDealInput) else LandDealInput.from_dict(payload)
        note_hits = self._note_signals(request.notes)

        scenarios = [
            DealScenario("base_case", 0.0, 0.0, 0.0),
            DealScenario(
                "downside_case",
                request.downside_sales_price_delta_pct,
                request.downside_cost_delta_pct,
                request.downside_absorption_delta_pct,
            ),
            DealScenario(
                "severe_downside_case",
                request.severe_downside_sales_price_delta_pct,
                request.severe_downside_cost_delta_pct,
                request.severe_downside_absorption_delta_pct,
            ),
        ]

        scenario_results = {scenario.name: self._compute_scenario(request, scenario) for scenario in scenarios}
        base_case = scenario_results["base_case"]
        downside_case = scenario_results["downside_case"]
        severe_case = scenario_results["severe_downside_case"]
        market_intelligence = (
            self._market_intelligence_summary(payload, request, base_case)
            if isinstance(payload, dict)
            else None
        )

        hurdle_results = {
            name: self._scenario_hurdles(request, result)
            for name, result in scenario_results.items()
        }
        sensitivity_matrix = self._sensitivity_matrix(request)

        model_signal = self._model_signal(request, base_case)
        recommendation, reasons = self._recommendation(
            request=request,
            base_case=base_case,
            downside_case=downside_case,
            severe_case=severe_case,
            hurdle_results=hurdle_results,
            note_hits=note_hits,
            model_signal=model_signal,
            market_intelligence=market_intelligence,
        )
        deal_score = self._deal_score(
            hurdle_results=hurdle_results,
            note_hits=note_hits,
            market_intelligence=market_intelligence,
            base_case=base_case,
        )
        investment_committee_memo = self._investment_committee_memo(
            request=request,
            base_case=base_case,
            hurdle_results=hurdle_results,
            recommendation=recommendation,
            reasons=reasons,
            note_hits=note_hits,
            market_intelligence=market_intelligence,
        )

        return {
            "agent": self.specialist.metadata["blueprint"]["name"] if self.specialist else "LandDealUnderwriter",
            "community_name": request.community_name,
            "division": request.division,
            "market": request.market,
            "takedown_structure": request.takedown_structure,
            "recommendation": recommendation,
            "recommendation_reasons": reasons,
            "risk_flags": note_hits["risk_signals"],
            "upside_flags": note_hits["positive_signals"],
            "hurdles": hurdle_results,
            "scenarios": scenario_results,
            "model_signal": model_signal,
            "market_intelligence": market_intelligence,
            "sensitivity_matrix": sensitivity_matrix,
            "deal_score": deal_score,
            "investment_committee_memo": investment_committee_memo,
            "assumptions": self._assumption_summary(request),
        }

    def underwrite_many(self, payloads: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
        return [self.underwrite(item) for item in payloads]

    def _assumption_summary(self, request: LandDealInput) -> Dict[str, Any]:
        land_close_date = request.land_close_date.isoformat() if request.land_close_date else None
        return {
            "community_name": request.community_name,
            "division": request.division,
            "market": request.market,
            "gross_acres": _round_money(request.gross_acres),
            "total_lots": _round_money(request.total_lots),
            "density_du_per_acre": _round_money(_safe_div(request.total_lots, request.gross_acres)),
            "monthly_absorption": _round_money(request.monthly_absorption),
            "build_cycle_months": request.build_cycle_months,
            "months_to_first_home_start": request.months_to_first_home_start,
            "months_to_sales_open": request.months_to_sales_open,
            "months_to_first_close": request.first_close_month,
            "land_close_date": land_close_date,
            "target_gross_margin_pct": _round_ratio(request.target_gross_margin_pct),
            "target_pre_gna_margin_pct": _round_ratio(request.target_pre_gna_margin_pct),
            "target_irr_pct": _round_ratio(request.target_irr_pct),
            "product_series": [
                {
                    "name": item.name,
                    "lots": _round_money(item.lots),
                    "avg_sqft": _round_money(item.avg_sqft),
                    "base_house_price": _round_money(item.base_house_price),
                    "net_sales_price_per_unit": _round_money(item.net_sales_price_per_unit()),
                    "build_cost_per_unit": _round_money(item.build_cost_per_unit()),
                    "move_up": item.move_up,
                }
                for item in request.product_series
            ],
            "land_purchase_events": [
                {
                    "month": item.month,
                    "lots": _round_money(item.lots),
                    "price_per_lot": _round_money(item.price_per_lot),
                    "total_cost": _round_money(item.total_cost()),
                }
                for item in request.land_purchase_events
            ],
        }

    def _market_intelligence_summary(
        self,
        payload: Dict[str, Any],
        request: LandDealInput,
        base_case: Dict[str, Any],
    ) -> Dict[str, Any] | None:
        raw_competitors = payload.get("competitor_projects") or []
        raw_resales = payload.get("resale_comps") or []

        competitors: List[Dict[str, Any]] = []
        for item in raw_competitors:
            if not isinstance(item, dict):
                continue
            price = _float_from_value(item.get("avg_price"), default=0.0)
            pace = _float_from_value(item.get("monthly_absorption"), default=0.0)
            sqft = _float_from_value(item.get("avg_sqft"), default=0.0)
            if price <= 0 and pace <= 0 and sqft <= 0:
                continue
            competitors.append(
                {
                    "name": str(item.get("name") or "Comparable Community").strip() or "Comparable Community",
                    "monthly_absorption": _round_money(pace),
                    "avg_price": _round_money(price),
                    "avg_sqft": _round_money(sqft),
                    "avg_price_psf": _round_money(_safe_div(price, sqft)),
                    "revenue_per_month": _round_money(price * pace),
                    "active_listings": _round_money(
                        _float_from_value(item.get("active_listings"), default=0.0)
                    ),
                    "status": str(item.get("status") or "").strip(),
                }
            )

        resales: List[Dict[str, Any]] = []
        for item in raw_resales:
            if not isinstance(item, dict):
                continue
            close_price = _float_from_value(item.get("close_price"), default=0.0)
            sqft = _float_from_value(item.get("sqft"), default=0.0)
            if close_price <= 0 and sqft <= 0:
                continue
            resales.append(
                {
                    "name": str(item.get("name") or "Resale Comp").strip() or "Resale Comp",
                    "close_price": _round_money(close_price),
                    "sqft": _round_money(sqft),
                    "price_psf": _round_money(_safe_div(close_price, sqft)),
                    "distance_miles": _round_money(
                        _float_from_value(item.get("distance_miles"), default=0.0)
                    ),
                    "close_date": str(item.get("close_date") or "").strip(),
                }
            )

        if not competitors and not resales:
            return None

        subject_avg_sqft = _safe_div(
            sum(item.avg_sqft * item.lots for item in request.product_series),
            request.total_lots,
        )
        subject_avg_net_price = _float_from_value(
            base_case["investment_summary"]["average_net_sales_price"],
            default=0.0,
        )
        subject_price_psf = _safe_div(subject_avg_net_price, subject_avg_sqft)
        subject_revenue_per_month = subject_avg_net_price * request.monthly_absorption

        competitor_avg_price = _safe_div(
            sum(item["avg_price"] for item in competitors),
            len(competitors),
        )
        competitor_avg_sqft = _safe_div(
            sum(item["avg_sqft"] for item in competitors),
            len(competitors),
        )
        competitor_avg_price_psf = _safe_div(
            sum(item["avg_price_psf"] for item in competitors),
            len(competitors),
        )
        competitor_avg_absorption = _safe_div(
            sum(item["monthly_absorption"] for item in competitors),
            len(competitors),
        )
        competitor_avg_revenue_per_month = _safe_div(
            sum(item["revenue_per_month"] for item in competitors),
            len(competitors),
        )

        resale_prices = [item["close_price"] for item in resales if item["close_price"] > 0]
        resale_price_psf = [item["price_psf"] for item in resales if item["price_psf"] > 0]
        resale_avg_price = _safe_div(sum(resale_prices), len(resale_prices))
        resale_avg_price_psf = _safe_div(sum(resale_price_psf), len(resale_price_psf))
        resale_median_price = median(resale_prices) if resale_prices else 0.0

        positioning = {
            "subject_vs_competitor_price_pct": _round_ratio(
                _safe_div(subject_avg_net_price - competitor_avg_price, competitor_avg_price)
            ),
            "subject_vs_competitor_psf_pct": _round_ratio(
                _safe_div(subject_price_psf - competitor_avg_price_psf, competitor_avg_price_psf)
            ),
            "subject_vs_competitor_absorption_pct": _round_ratio(
                _safe_div(request.monthly_absorption - competitor_avg_absorption, competitor_avg_absorption)
            ),
            "subject_vs_competitor_revenue_velocity_pct": _round_ratio(
                _safe_div(
                    subject_revenue_per_month - competitor_avg_revenue_per_month,
                    competitor_avg_revenue_per_month,
                )
            ),
            "subject_vs_resale_price_pct": _round_ratio(
                _safe_div(subject_avg_net_price - resale_avg_price, resale_avg_price)
            ),
            "subject_vs_resale_psf_pct": _round_ratio(
                _safe_div(subject_price_psf - resale_avg_price_psf, resale_avg_price_psf)
            ),
        }

        risk_flags: List[str] = []
        upside_flags: List[str] = []
        risk_score = 0

        if competitor_avg_price > 0 and subject_avg_net_price > competitor_avg_price * 1.1:
            risk_flags.append("Subject net price is more than 10% above competitor average.")
            risk_score += 4
        elif competitor_avg_price > 0 and subject_avg_net_price < competitor_avg_price * 0.94:
            upside_flags.append("Subject net price is at least 6% below competitor average.")

        if resale_avg_price_psf > 0 and subject_price_psf > resale_avg_price_psf * 1.12:
            risk_flags.append("Subject price per foot is more than 12% above resale comps.")
            risk_score += 3
        elif resale_avg_price_psf > 0 and subject_price_psf < resale_avg_price_psf * 0.97:
            upside_flags.append("Subject price per foot is below the resale comp set.")

        if competitor_avg_absorption > 0 and request.monthly_absorption > competitor_avg_absorption * 1.2:
            risk_flags.append("Planned absorption is more than 20% ahead of competitor pace.")
            risk_score += 3
        elif competitor_avg_absorption > 0 and request.monthly_absorption <= competitor_avg_absorption * 0.95:
            upside_flags.append("Planned absorption is at or below current competitor pace.")

        return {
            "subject": {
                "average_net_price": _round_money(subject_avg_net_price),
                "average_sqft": _round_money(subject_avg_sqft),
                "price_psf": _round_money(subject_price_psf),
                "monthly_absorption": _round_money(request.monthly_absorption),
                "revenue_per_month": _round_money(subject_revenue_per_month),
            },
            "competitors": {
                "count": len(competitors),
                "average_price": _round_money(competitor_avg_price),
                "average_sqft": _round_money(competitor_avg_sqft),
                "average_price_psf": _round_money(competitor_avg_price_psf),
                "average_absorption": _round_money(competitor_avg_absorption),
                "average_revenue_per_month": _round_money(competitor_avg_revenue_per_month),
                "rows": competitors,
            },
            "resales": {
                "count": len(resales),
                "average_price": _round_money(resale_avg_price),
                "median_price": _round_money(resale_median_price),
                "average_price_psf": _round_money(resale_avg_price_psf),
                "rows": resales,
            },
            "positioning": positioning,
            "risk_flags": risk_flags,
            "upside_flags": upside_flags,
            "risk_score": risk_score,
        }

    def _sensitivity_matrix(self, request: LandDealInput) -> Dict[str, Any]:
        price_deltas = [-0.10, -0.05, 0.0, 0.05]
        cost_deltas = [0.10, 0.05, 0.0, -0.05]
        rows: List[Dict[str, Any]] = []

        for cost_delta in cost_deltas:
            row_cells: List[Dict[str, Any]] = []
            for price_delta in price_deltas:
                scenario = DealScenario(
                    name=f"sensitivity_{price_delta}_{cost_delta}",
                    sales_price_delta_pct=price_delta,
                    cost_delta_pct=cost_delta,
                    absorption_delta_pct=0.0,
                )
                result = self._compute_scenario(request, scenario)
                hurdles = self._scenario_hurdles(request, result)
                pass_count = sum(1 for value in hurdles.values() if value)
                status = "clear" if pass_count == 4 else "watch" if pass_count >= 2 else "fail"
                row_cells.append(
                    {
                        "sales_price_delta_pct": _round_ratio(price_delta),
                        "cost_delta_pct": _round_ratio(cost_delta),
                        "pre_gna_margin_pct": result["income_statement"]["pre_gna_margin_pct"],
                        "irr_pre_gna_pct": result["cash_flow_metrics"]["irr_pre_gna_pct"],
                        "land_value_gap_to_residual": result["investment_summary"]["land_value_gap_to_residual"],
                        "status": status,
                    }
                )
            rows.append(
                {
                    "cost_delta_pct": _round_ratio(cost_delta),
                    "cells": row_cells,
                }
            )

        return {
            "price_deltas_pct": [_round_ratio(item) for item in price_deltas],
            "cost_deltas_pct": [_round_ratio(item) for item in cost_deltas],
            "rows": rows,
        }

    def _deal_score(
        self,
        *,
        hurdle_results: Dict[str, Dict[str, bool]],
        note_hits: Dict[str, Any],
        market_intelligence: Dict[str, Any] | None,
        base_case: Dict[str, Any],
    ) -> Dict[str, Any]:
        score = 50
        base_passes = sum(1 for value in hurdle_results["base_case"].values() if value)
        downside_passes = sum(1 for value in hurdle_results["downside_case"].values() if value)
        severe_passes = sum(1 for value in hurdle_results["severe_downside_case"].values() if value)
        score += base_passes * 8
        score += downside_passes * 4
        score += severe_passes * 2
        score -= min(20, int(note_hits.get("risk_score", 0) or 0))
        score += min(10, int(note_hits.get("positive_score", 0) or 0) // 2)

        if market_intelligence is not None:
            score -= min(16, int(market_intelligence.get("risk_score", 0) or 0) * 2)
            score += min(8, len(market_intelligence.get("upside_flags", [])) * 2)

        residual_gap = _float_from_value(
            base_case["investment_summary"]["land_value_gap_to_residual"],
            default=0.0,
        )
        if residual_gap <= 0:
            score += 8
        else:
            score -= min(14, int(abs(residual_gap) / 250000))

        score = max(0, min(100, score))
        if score >= 80:
            band = "strong"
        elif score >= 65:
            band = "workable"
        elif score >= 50:
            band = "fragile"
        else:
            band = "high_risk"

        return {
            "score": score,
            "band": band,
            "base_hurdles_passed": base_passes,
            "downside_hurdles_passed": downside_passes,
            "severe_hurdles_passed": severe_passes,
        }

    def _investment_committee_memo(
        self,
        *,
        request: LandDealInput,
        base_case: Dict[str, Any],
        hurdle_results: Dict[str, Dict[str, bool]],
        recommendation: str,
        reasons: Sequence[str],
        note_hits: Dict[str, Any],
        market_intelligence: Dict[str, Any] | None,
    ) -> Dict[str, Any]:
        revenue = _float_from_value(base_case["income_statement"]["revenue_total"], default=0.0)
        gross_margin_pct = _ratio_from_value(base_case["income_statement"]["gross_margin_pct"], default=0.0)
        pre_gna_margin_pct = _ratio_from_value(base_case["income_statement"]["pre_gna_margin_pct"], default=0.0)
        irr_pct = _ratio_from_value(base_case["cash_flow_metrics"]["irr_pre_gna_pct"], default=0.0)
        residual_gap = _float_from_value(
            base_case["investment_summary"]["land_value_gap_to_residual"],
            default=0.0,
        )

        strengths: List[str] = []
        risks: List[str] = []

        if hurdle_results["base_case"]["gross_margin"]:
            strengths.append("Base gross margin clears the underwriting hurdle.")
        else:
            risks.append("Base gross margin is below the underwriting hurdle.")
        if hurdle_results["base_case"]["pre_gna_margin"]:
            strengths.append("Base pre-G&A contribution clears the target.")
        else:
            risks.append("Base pre-G&A contribution misses the target.")
        if hurdle_results["base_case"]["irr"]:
            strengths.append("Base IRR clears the required return.")
        else:
            risks.append("Base IRR does not clear the required return.")
        if residual_gap <= 0:
            strengths.append("Residual land value supports the current land basis.")
        else:
            risks.append("Current land basis is above residual value support.")

        for item in note_hits.get("positive_signals", [])[:3]:
            strengths.append(f"Deal notes indicate {item}.")
        for item in note_hits.get("risk_signals", [])[:3]:
            risks.append(f"Deal notes flag {item}.")

        if market_intelligence is not None:
            for item in market_intelligence.get("upside_flags", [])[:2]:
                strengths.append(item)
            for item in market_intelligence.get("risk_flags", [])[:2]:
                risks.append(item)

        if recommendation == "pursue":
            next_steps = [
                "Advance LOI and lock down diligence scope.",
                "Confirm takedown timing and entitlement milestones.",
                "Protect current pricing assumptions with fresh market checks before committee approval.",
            ]
        elif recommendation == "negotiate":
            next_steps = [
                "Re-cut the land basis to create more residual support.",
                "Validate pace and pricing with an updated comp shop before final bid.",
                "Stress-test offsite, grading, and utility exposure in diligence.",
            ]
        else:
            next_steps = [
                "Do not advance at the current basis.",
                "Revisit only if price, phasing, or product mix materially improve returns.",
                "Use the sensitivity matrix to identify what would be required to re-open the deal.",
            ]

        summary = (
            f"{request.community_name} underwrites to {recommendation.upper()} on "
            f"{request.total_lots:.0f} lots / {request.gross_acres:.1f} acres. "
            f"Base revenue is {revenue:,.0f}, gross margin is {gross_margin_pct:.1%}, "
            f"pre-G&A margin is {pre_gna_margin_pct:.1%}, and IRR is {irr_pct:.1%}."
        )

        return {
            "headline": f"{recommendation.upper()} | {request.community_name}",
            "summary": summary,
            "strengths": strengths[:6],
            "risks": risks[:6],
            "next_steps": next_steps,
            "reason_snapshot": list(reasons[:6]),
        }

    def _note_signals(self, notes: str) -> Dict[str, Any]:
        positive_hits = _find_signal_hits(notes, POSITIVE_SIGNAL_WEIGHTS)
        risk_hits = _find_signal_hits(notes, RISK_SIGNAL_WEIGHTS)
        positive_score = sum(POSITIVE_SIGNAL_WEIGHTS[item] for item in positive_hits[:4])
        risk_score = sum(RISK_SIGNAL_WEIGHTS[item] for item in risk_hits[:4])
        return {
            "positive_signals": positive_hits,
            "risk_signals": risk_hits,
            "positive_score": positive_score,
            "risk_score": risk_score,
        }

    def _model_signal(self, request: LandDealInput, base_case: Dict[str, Any]) -> Dict[str, Any] | None:
        if self.specialist is None:
            return None

        context = request.notes or self._deal_narrative(request, base_case)
        prediction = self.specialist.predict(context)
        model_value = _float_from_value(prediction.get("prediction"), default=0.0)
        actual_land = _float_from_value(
            base_case["investment_summary"]["actual_land_cost_total"],
            default=0.0,
        )
        residual_land = _float_from_value(
            base_case["investment_summary"]["residual_max_land_cost_total"],
            default=0.0,
        )
        return {
            "input_text": context,
            "prediction": _round_money(model_value),
            "variance_to_actual_land_cost": _round_money(model_value - actual_land),
            "variance_to_residual_land_value": _round_money(model_value - residual_land),
        }

    def _deal_narrative(self, request: LandDealInput, base_case: Dict[str, Any]) -> str:
        revenue = base_case["income_statement"]["revenue_total"]
        land_cost = base_case["investment_summary"]["actual_land_cost_total"]
        gross_margin_pct = base_case["income_statement"]["gross_margin_pct"]
        irr_pct = base_case["cash_flow_metrics"]["irr_pre_gna_pct"] or 0.0
        notes = request.notes or "No supplemental notes provided."
        return (
            f"{request.community_name} in {request.market or request.division}. "
            f"{request.total_lots:.0f} lots on {request.gross_acres:.1f} acres. "
            f"Average absorption {request.monthly_absorption:.2f} homes per month. "
            f"Revenue {revenue}, land basis {land_cost}, gross margin {gross_margin_pct}, irr {irr_pct}. "
            f"Notes: {notes}"
        )

    def _scenario_hurdles(self, request: LandDealInput, result: Dict[str, Any]) -> Dict[str, bool]:
        gross_margin_pct = _ratio_from_value(result["income_statement"]["gross_margin_pct"], default=0.0)
        pre_gna_margin_pct = _ratio_from_value(result["income_statement"]["pre_gna_margin_pct"], default=0.0)
        irr_pct = _ratio_from_value(result["cash_flow_metrics"]["irr_pre_gna_pct"], default=0.0)
        actual_land_cost = _float_from_value(result["investment_summary"]["actual_land_cost_total"], default=0.0)
        residual_land_value = _float_from_value(
            result["investment_summary"]["residual_max_land_cost_total"],
            default=0.0,
        )
        return {
            "gross_margin": gross_margin_pct >= request.target_gross_margin_pct,
            "pre_gna_margin": pre_gna_margin_pct >= request.target_pre_gna_margin_pct,
            "irr": irr_pct >= request.target_irr_pct,
            "residual_land_value": actual_land_cost <= residual_land_value,
        }

    def _recommendation(
        self,
        *,
        request: LandDealInput,
        base_case: Dict[str, Any],
        downside_case: Dict[str, Any],
        severe_case: Dict[str, Any],
        hurdle_results: Dict[str, Dict[str, bool]],
        note_hits: Dict[str, Any],
        model_signal: Dict[str, Any] | None,
        market_intelligence: Dict[str, Any] | None,
    ) -> tuple[str, List[str]]:
        reasons: List[str] = []
        base_hurdles = hurdle_results["base_case"]
        downside_hurdles = hurdle_results["downside_case"]
        severe_pre_gna = _ratio_from_value(severe_case["income_statement"]["pre_gna_margin_pct"], default=0.0)
        actual_land_cost = _float_from_value(base_case["investment_summary"]["actual_land_cost_total"], default=0.0)
        residual_land_value = _float_from_value(
            base_case["investment_summary"]["residual_max_land_cost_total"],
            default=0.0,
        )

        reasons.append(
            "Base case clears the target gross margin."
            if base_hurdles["gross_margin"]
            else "Base case misses the target gross margin."
        )
        reasons.append(
            "Base case clears the target pre-G&A contribution margin."
            if base_hurdles["pre_gna_margin"]
            else "Base case misses the target pre-G&A contribution margin."
        )
        reasons.append(
            "Base case clears the target IRR."
            if base_hurdles["irr"]
            else "Base case misses the target IRR."
        )
        if actual_land_cost > residual_land_value:
            reasons.append("Actual land basis is above the residual land value.")
        if note_hits["risk_signals"]:
            reasons.append("Key diligence risks were detected in the notes.")
        if model_signal is not None:
            variance_to_residual = _float_from_value(model_signal["variance_to_residual_land_value"], default=0.0)
            if variance_to_residual > 0:
                reasons.append("The text-based pricing model is above the residual land value.")
            else:
                reasons.append("The text-based pricing model is at or below the residual land value.")

        market_risk_score = 0
        if market_intelligence is not None:
            market_risk_score = int(market_intelligence.get("risk_score", 0) or 0)
            competitor_count = int(market_intelligence["competitors"].get("count", 0) or 0)
            resale_count = int(market_intelligence["resales"].get("count", 0) or 0)
            if competitor_count or resale_count:
                reasons.append(
                    f"Market check includes {competitor_count} competitor communities and {resale_count} resale comps."
                )
            for item in market_intelligence.get("risk_flags", []):
                reasons.append(item)
            for item in market_intelligence.get("upside_flags", []):
                reasons.append(item)

        if (
            all(base_hurdles.values())
            and all(downside_hurdles.values())
            and note_hits["risk_score"] <= 12
            and market_risk_score <= 4
        ):
            return "pursue", reasons

        if (
            base_hurdles["gross_margin"]
            and base_hurdles["pre_gna_margin"]
            and base_hurdles["residual_land_value"]
            and base_hurdles["irr"]
            and actual_land_cost <= residual_land_value * 1.1
            and severe_pre_gna > -0.03
            and market_risk_score <= 8
        ):
            return "negotiate", reasons

        return "pass", reasons

    def _compute_scenario(self, request: LandDealInput, scenario: DealScenario) -> Dict[str, Any]:
        price_multiplier = 1.0 + scenario.sales_price_delta_pct
        cost_multiplier = 1.0 + scenario.cost_delta_pct
        absorption = max(0.25, request.monthly_absorption * (1.0 + scenario.absorption_delta_pct))
        first_close_month = request.first_close_month
        first_home_start_month = request.months_to_first_home_start
        sales_open_month = min(request.months_to_sales_open, first_close_month)

        series_metrics: List[Dict[str, Any]] = []
        revenue_total = 0.0
        build_cost_total = 0.0
        for series in request.product_series:
            net_sales_price = series.net_sales_price_per_unit(price_multiplier=price_multiplier)
            build_cost = series.build_cost_per_unit(cost_multiplier=cost_multiplier)
            series_revenue = net_sales_price * series.lots
            series_build_cost = build_cost * series.lots
            revenue_total += series_revenue
            build_cost_total += series_build_cost
            series_metrics.append(
                {
                    "name": series.name,
                    "lots": _round_money(series.lots),
                    "mix_pct": _round_ratio(_safe_div(series.lots, request.total_lots)),
                    "avg_sqft": _round_money(series.avg_sqft),
                    "net_sales_price_per_unit": _round_money(net_sales_price),
                    "build_cost_per_unit": _round_money(build_cost),
                    "revenue_total": _round_money(series_revenue),
                    "build_cost_total": _round_money(series_build_cost),
                    "move_up": series.move_up,
                }
            )

        total_lots = request.total_lots
        avg_net_sales_price = _safe_div(revenue_total, total_lots)
        avg_build_cost_per_unit = _safe_div(build_cost_total, total_lots)

        land_purchase_cost_total = sum(item.total_cost() for item in request.land_purchase_events)
        actual_land_cost_total = land_purchase_cost_total + request.land_brokerage_and_closing_costs_total
        land_cost_per_lot = _safe_div(actual_land_cost_total, total_lots)

        land_development_cost_total = request.land_development_cost_total * cost_multiplier
        project_management_cost_total = request.project_management_cost_total * cost_multiplier
        site_improvements_total = land_development_cost_total + project_management_cost_total
        other_land_costs_total = request.other_land_costs_total * cost_multiplier
        finished_lot_cost_total = actual_land_cost_total + site_improvements_total + other_land_costs_total
        finished_lot_cost_per_lot = _safe_div(finished_lot_cost_total, total_lots)

        closing_schedule = _closing_schedule(total_lots, absorption, first_close_month)
        last_close_month = closing_schedule[-1][0]
        construction_months = max(1, last_close_month - first_home_start_month + 1)

        if request.indirect_field_overhead_total is not None:
            indirect_field_overhead_total = request.indirect_field_overhead_total * cost_multiplier
        elif request.indirect_field_overhead_per_month is not None:
            indirect_field_overhead_total = request.indirect_field_overhead_per_month * cost_multiplier * construction_months
        elif request.indirect_field_overhead_per_lot is not None:
            indirect_field_overhead_total = request.indirect_field_overhead_per_lot * cost_multiplier * total_lots
        else:
            indirect_field_overhead_total = (
                DEFAULT_INDIRECT_FIELD_OVERHEAD_PER_MONTH * cost_multiplier * construction_months
            )

        architecture_engineering_total = request.architecture_engineering_total * cost_multiplier
        capitalized_marketing_total = request.capitalized_marketing_total_value() * cost_multiplier
        other_house_costs_total = request.other_house_costs_per_unit * cost_multiplier * total_lots

        house_costs_total = (
            build_cost_total
            + indirect_field_overhead_total
            + architecture_engineering_total
            + other_house_costs_total
        )
        house_costs_per_unit = _safe_div(house_costs_total, total_lots)

        total_cost_of_sales = finished_lot_cost_total + house_costs_total
        gross_margin = revenue_total - total_cost_of_sales
        sales_commission_total = revenue_total * request.sales_commission_pct
        contribution_margin = gross_margin - sales_commission_total
        home_sale_excise_tax_total = revenue_total * request.home_sale_excise_tax_pct
        corporate_charge_total = revenue_total * request.corporate_charge_pct
        pre_gna_contribution = (
            contribution_margin
            - capitalized_marketing_total
            - home_sale_excise_tax_total
            - corporate_charge_total
        )

        target_pre_gna_dollars = revenue_total * request.target_pre_gna_margin_pct
        residual_max_land_cost_total = (
            revenue_total
            - site_improvements_total
            - other_land_costs_total
            - house_costs_total
            - sales_commission_total
            - capitalized_marketing_total
            - home_sale_excise_tax_total
            - corporate_charge_total
            - target_pre_gna_dollars
        )
        residual_max_land_cost_per_lot = _safe_div(residual_max_land_cost_total, total_lots)
        residual_max_land_cost_per_acre = _safe_div(residual_max_land_cost_total, request.gross_acres)

        timeline_length = last_close_month + request.build_cycle_months + 6
        cash_flows = [0.0] * max(12, timeline_length)

        if request.earnest_money_deposit > 0:
            cash_flows[0] -= request.earnest_money_deposit

        total_event_lots = sum(item.lots for item in request.land_purchase_events)
        first_land_close_month = min(item.month for item in request.land_purchase_events)
        for event in request.land_purchase_events:
            event_cost = event.total_cost()
            if request.deposit_credit_at_close and total_event_lots > 0:
                event_cost -= request.earnest_money_deposit * _safe_div(event.lots, total_event_lots)
            if event.month >= len(cash_flows):
                cash_flows.extend([0.0] * (event.month - len(cash_flows) + 1))
            cash_flows[event.month] -= event_cost

        if request.land_brokerage_and_closing_costs_total:
            cash_flows[first_land_close_month] -= request.land_brokerage_and_closing_costs_total

        site_spend_months = request.site_improvement_spend_months or max(
            first_close_month,
            math.ceil(construction_months * 0.75),
        )
        _allocate_evenly(
            cash_flows,
            -(site_improvements_total + other_land_costs_total),
            first_land_close_month,
            site_spend_months,
        )
        _allocate_evenly(
            cash_flows,
            -architecture_engineering_total,
            first_land_close_month,
            max(1, first_home_start_month),
        )
        _allocate_evenly(
            cash_flows,
            -indirect_field_overhead_total,
            first_home_start_month,
            construction_months,
        )
        _allocate_evenly(
            cash_flows,
            -capitalized_marketing_total,
            sales_open_month,
            max(1, last_close_month - sales_open_month + 1),
        )

        build_window = max(1, request.build_cycle_months)
        sales_commission_per_unit = avg_net_sales_price * request.sales_commission_pct
        excise_per_unit = avg_net_sales_price * request.home_sale_excise_tax_pct
        corporate_charge_per_unit = avg_net_sales_price * request.corporate_charge_pct
        close_cost_per_unit = request.other_house_costs_per_unit * cost_multiplier

        for month, closings in closing_schedule:
            if month >= len(cash_flows):
                cash_flows.extend([0.0] * (month - len(cash_flows) + 1))
            cash_flows[month] += closings * avg_net_sales_price
            cash_flows[month] -= closings * (sales_commission_per_unit + excise_per_unit + corporate_charge_per_unit)
            cash_flows[month] -= closings * close_cost_per_unit
            build_cost_amount = closings * avg_build_cost_per_unit
            _allocate_evenly(
                cash_flows,
                -build_cost_amount,
                max(first_home_start_month, month - build_window + 1),
                build_window,
            )

        cumulative_cash: List[float] = []
        running_balance = 0.0
        for value in cash_flows:
            running_balance += value
            cumulative_cash.append(running_balance)

        peak_investment_balance = min(cumulative_cash)
        peak_investment_month = cumulative_cash.index(peak_investment_balance)
        months_to_positive_net_cash = next((index for index, value in enumerate(cumulative_cash) if value >= 0), None)
        monthly_irr = _monthly_irr(cash_flows)
        irr_pre_gna_pct = _annualize_monthly_rate(monthly_irr)
        avg_total_assets = _safe_div(sum(max(-value, 0.0) for value in cumulative_cash), len(cumulative_cash))
        return_on_average_assets = _safe_div(pre_gna_contribution, avg_total_assets)

        date_summary = None
        if request.land_close_date is not None:
            date_summary = {
                "land_close_date": request.land_close_date.isoformat(),
                "first_home_start_date": _add_months(request.land_close_date, first_home_start_month).isoformat(),
                "sales_open_date": _add_months(request.land_close_date, sales_open_month).isoformat(),
                "first_close_date": _add_months(request.land_close_date, first_close_month).isoformat(),
                "last_close_date": _add_months(request.land_close_date, last_close_month).isoformat(),
                "peak_investment_date": _add_months(request.land_close_date, peak_investment_month).isoformat(),
            }

        return {
            "scenario": scenario.name,
            "scenario_adjustments": {
                "sales_price_delta_pct": _round_ratio(scenario.sales_price_delta_pct),
                "cost_delta_pct": _round_ratio(scenario.cost_delta_pct),
                "absorption_delta_pct": _round_ratio(scenario.absorption_delta_pct),
            },
            "investment_summary": {
                "gross_acres": _round_money(request.gross_acres),
                "total_lots": _round_money(total_lots),
                "density_du_per_acre": _round_money(_safe_div(total_lots, request.gross_acres)),
                "actual_land_cost_total": _round_money(actual_land_cost_total),
                "land_cost_per_lot": _round_money(land_cost_per_lot),
                "site_improvements_total": _round_money(site_improvements_total),
                "site_improvements_per_lot": _round_money(_safe_div(site_improvements_total, total_lots)),
                "other_land_costs_total": _round_money(other_land_costs_total),
                "finished_lot_cost_total": _round_money(finished_lot_cost_total),
                "finished_lot_cost_per_lot": _round_money(finished_lot_cost_per_lot),
                "average_net_sales_price": _round_money(avg_net_sales_price),
                "finished_lot_cost_pct_of_asp": _round_ratio(_safe_div(finished_lot_cost_per_lot, avg_net_sales_price)),
                "residual_max_land_cost_total": _round_money(residual_max_land_cost_total),
                "residual_max_land_cost_per_lot": _round_money(residual_max_land_cost_per_lot),
                "residual_max_land_cost_per_acre": _round_money(residual_max_land_cost_per_acre),
                "land_value_gap_to_residual": _round_money(actual_land_cost_total - residual_max_land_cost_total),
            },
            "schedule": {
                "monthly_absorption": _round_money(absorption),
                "sellout_months": len(closing_schedule),
                "months_to_first_home_start": first_home_start_month,
                "months_to_sales_open": sales_open_month,
                "months_to_first_close": first_close_month,
                "months_to_last_close": last_close_month,
                "total_project_months": last_close_month - first_land_close_month + 1,
                "date_summary": date_summary,
            },
            "income_statement": {
                "revenue_total": _round_money(revenue_total),
                "house_costs_total": _round_money(house_costs_total),
                "house_costs_per_unit": _round_money(house_costs_per_unit),
                "total_cost_of_sales": _round_money(total_cost_of_sales),
                "gross_margin": _round_money(gross_margin),
                "gross_margin_pct": _round_ratio(_safe_div(gross_margin, revenue_total)),
                "sales_commission_total": _round_money(sales_commission_total),
                "contribution_margin": _round_money(contribution_margin),
                "contribution_margin_pct": _round_ratio(_safe_div(contribution_margin, revenue_total)),
                "capitalized_marketing_total": _round_money(capitalized_marketing_total),
                "home_sale_excise_tax_total": _round_money(home_sale_excise_tax_total),
                "corporate_charge_total": _round_money(corporate_charge_total),
                "pre_gna_contribution": _round_money(pre_gna_contribution),
                "pre_gna_margin_pct": _round_ratio(_safe_div(pre_gna_contribution, revenue_total)),
            },
            "cash_flow_metrics": {
                "irr_pre_gna_pct": _round_ratio(irr_pre_gna_pct),
                "peak_investment": _round_money(abs(peak_investment_balance)),
                "peak_investment_month": peak_investment_month,
                "months_to_positive_net_cash": months_to_positive_net_cash,
                "average_total_assets": _round_money(avg_total_assets),
                "return_on_average_total_assets": _round_ratio(return_on_average_assets),
            },
            "series_metrics": series_metrics,
        }
