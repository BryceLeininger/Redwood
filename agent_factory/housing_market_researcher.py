"""Deterministic housing market research workflow layered on a specialist agent."""
from __future__ import annotations

from dataclasses import asdict, dataclass, fields
from typing import Any, Dict, List, Sequence

from .specialist_agent import SpecialistAgent

LABEL_TO_DIRECTION = {
    "cooling": -1,
    "balanced": 0,
    "hot": 1,
}


def _clean_text(value: str | None) -> str:
    return " ".join((value or "").split())


def _float_from_value(value: Any) -> float | None:
    if value in (None, ""):
        return None
    if isinstance(value, str):
        raw = value.strip().replace("%", "").replace(",", "").replace("$", "")
        if not raw:
            return None
        return float(raw)
    return float(value)


def _string_from_value(value: Any) -> str | None:
    if value in (None, ""):
        return None
    cleaned = _clean_text(str(value))
    return cleaned or None


def _clip_score(value: float, limit: float = 4.0) -> float:
    return max(-limit, min(limit, round(value, 2)))


def _pick_metric(payload: Dict[str, Any], metrics: Dict[str, Any], key: str) -> Any:
    if key in payload:
        return payload.get(key)
    return metrics.get(key)


def _append_signal(bucket: List[str], value: str) -> None:
    if value and value not in bucket:
        bucket.append(value)


def _top_class_confidence(prediction: str | None, top_classes: Sequence[Dict[str, Any]]) -> float | None:
    if not prediction:
        return None
    for item in top_classes:
        if str(item.get("label", "")).strip().lower() != prediction:
            continue
        try:
            return round(float(item.get("confidence")), 4)
        except (TypeError, ValueError):
            return None
    return None


@dataclass(frozen=True)
class HousingMarketRequest:
    market: str
    period: str | None = None
    notes: str = ""
    active_listings_yoy_pct: float | None = None
    months_of_supply: float | None = None
    months_of_supply_yoy_pct: float | None = None
    median_sale_price_yoy_pct: float | None = None
    pending_sales_yoy_pct: float | None = None
    closed_sales_yoy_pct: float | None = None
    new_listings_yoy_pct: float | None = None
    days_on_market: float | None = None
    days_on_market_yoy_pct: float | None = None
    list_to_sale_ratio_pct: float | None = None
    price_reductions_share_pct: float | None = None
    seller_concessions_share_pct: float | None = None
    mortgage_rate_pct: float | None = None
    mortgage_rate_change_bps: float | None = None
    unemployment_rate_pct: float | None = None
    employment_growth_yoy_pct: float | None = None
    permits_yoy_pct: float | None = None
    starts_yoy_pct: float | None = None
    completions_yoy_pct: float | None = None
    rent_growth_yoy_pct: float | None = None
    rental_vacancy_rate_pct: float | None = None
    migration_trend: str | None = None
    builder_sentiment: str | None = None
    segment_notes: str | None = None

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "HousingMarketRequest":
        if not isinstance(payload, dict):
            raise ValueError("Housing market research input must be an object.")
        metrics = payload.get("metrics", {})
        if metrics is None:
            metrics = {}
        if not isinstance(metrics, dict):
            raise ValueError("The optional 'metrics' field must be an object.")

        market = _string_from_value(payload.get("market"))
        if not market:
            raise ValueError("Housing market research input requires a market name.")

        float_fields = {
            "active_listings_yoy_pct",
            "months_of_supply",
            "months_of_supply_yoy_pct",
            "median_sale_price_yoy_pct",
            "pending_sales_yoy_pct",
            "closed_sales_yoy_pct",
            "new_listings_yoy_pct",
            "days_on_market",
            "days_on_market_yoy_pct",
            "list_to_sale_ratio_pct",
            "price_reductions_share_pct",
            "seller_concessions_share_pct",
            "mortgage_rate_pct",
            "mortgage_rate_change_bps",
            "unemployment_rate_pct",
            "employment_growth_yoy_pct",
            "permits_yoy_pct",
            "starts_yoy_pct",
            "completions_yoy_pct",
            "rent_growth_yoy_pct",
            "rental_vacancy_rate_pct",
        }
        string_fields = {"migration_trend", "builder_sentiment", "segment_notes"}

        values: Dict[str, Any] = {
            "market": market,
            "period": _string_from_value(payload.get("period")),
            "notes": _clean_text(str(payload.get("notes") or "")),
        }

        for key in float_fields:
            values[key] = _float_from_value(_pick_metric(payload, metrics, key))
        for key in string_fields:
            values[key] = _string_from_value(_pick_metric(payload, metrics, key))

        return cls(**values)

    def available_metric_count(self) -> int:
        count = 0
        for field in fields(self):
            if field.name in {"market", "period", "notes"}:
                continue
            if getattr(self, field.name) not in (None, ""):
                count += 1
        return count

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class HousingMarketResearcher:
    """Analyze housing market packets and classify momentum."""

    def __init__(self, specialist: SpecialistAgent | None = None) -> None:
        self.specialist = specialist

    def research(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        request = HousingMarketRequest.from_dict(payload)
        heuristic = self._heuristic_report(request)
        summary_text = self._summary_text(request, heuristic)
        model_signal = self._model_signal(summary_text)
        final_label, final_confidence, basis = self._resolve_classification(heuristic, model_signal)
        actions = self._action_plan(final_label, heuristic)
        scenarios = self._scenario_outlook(request, heuristic, final_label)
        executive_summary = self._executive_summary(request, heuristic, final_label, basis)

        return {
            "agent": (
                self.specialist.metadata["blueprint"]["name"]
                if self.specialist is not None
                else "HousingMarketResearcher"
            ),
            "market": request.market,
            "period": request.period,
            "classification": final_label,
            "classification_confidence": final_confidence,
            "classification_basis": basis,
            "executive_summary": executive_summary,
            "data_coverage": {
                "available_metrics": request.available_metric_count(),
                "notes_provided": bool(request.notes),
            },
            "pillar_scores": heuristic["pillar_scores"],
            "signals": heuristic["signals"],
            "actions": actions,
            "scenario_outlook": scenarios,
            "analysis_text": summary_text,
            "heuristic_signal": heuristic["classification_signal"],
            "model_signal": model_signal,
            "request": request.to_dict(),
        }

    def research_many(self, payloads: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
        return [self.research(item) for item in payloads]

    def _model_signal(self, summary_text: str) -> Dict[str, Any] | None:
        if self.specialist is None:
            return None
        try:
            prediction = self.specialist.predict(summary_text)
        except Exception as error:  # pragma: no cover - defensive fallback for stale persisted models
            return {
                "prediction": None,
                "confidence": 0.0,
                "top_classes": [],
                "error": str(error),
            }
        label = str(prediction.get("prediction", "")).strip().lower()
        top_classes = prediction.get("top_classes", [])
        return {
            "prediction": label or None,
            "confidence": _top_class_confidence(label or None, top_classes) or 0.0,
            "top_classes": top_classes,
        }

    def _resolve_classification(
        self,
        heuristic: Dict[str, Any],
        model_signal: Dict[str, Any] | None,
    ) -> tuple[str, float, str]:
        heuristic_label = str(heuristic["classification_signal"]["prediction"])
        heuristic_confidence = float(heuristic["classification_signal"]["confidence"])

        if model_signal is None or not model_signal.get("prediction"):
            return heuristic_label, round(heuristic_confidence, 4), "heuristic"

        model_label = str(model_signal["prediction"])
        model_confidence = float(model_signal.get("confidence") or 0.0)
        if model_label == heuristic_label:
            confidence = min(0.98, (heuristic_confidence + model_confidence) / 2.0 + 0.08)
            return model_label, round(confidence, 4), "ensemble"

        heuristic_direction = LABEL_TO_DIRECTION.get(heuristic_label, 0)
        model_direction = LABEL_TO_DIRECTION.get(model_label, 0)
        combined_direction = heuristic_direction * heuristic_confidence + model_direction * model_confidence
        if abs(combined_direction) >= 0.55:
            label = "hot" if combined_direction > 0 else "cooling"
            confidence = max(heuristic_confidence, model_confidence)
            return label, round(confidence, 4), "ensemble"

        if model_confidence >= max(0.7, heuristic_confidence + 0.12):
            return model_label, round(model_confidence, 4), "specialist_model"
        return heuristic_label, round(heuristic_confidence, 4), "heuristic"

    def _executive_summary(
        self,
        request: HousingMarketRequest,
        heuristic: Dict[str, Any],
        classification: str,
        basis: str,
    ) -> str:
        positives = [item.rstrip(".") for item in heuristic["signals"]["positive"][:2]]
        risks = [item.rstrip(".") for item in heuristic["signals"]["risk"][:2]]
        summary = f"{request.market} reads as {classification} based on {basis.replace('_', ' ')} analysis."
        if positives:
            summary += " Supportive signals: " + "; ".join(positives) + "."
        if risks:
            summary += " Main risks: " + "; ".join(risks) + "."
        return summary

    def _summary_text(self, request: HousingMarketRequest, heuristic: Dict[str, Any]) -> str:
        parts: List[str] = []
        header = request.market
        if request.period:
            header += f" {request.period}"
        parts.append(header)

        metrics = [
            ("active listings yoy", request.active_listings_yoy_pct, "%"),
            ("months of supply", request.months_of_supply, ""),
            ("median sale price yoy", request.median_sale_price_yoy_pct, "%"),
            ("pending sales yoy", request.pending_sales_yoy_pct, "%"),
            ("days on market", request.days_on_market, ""),
            ("days on market yoy", request.days_on_market_yoy_pct, "%"),
            ("list to sale ratio", request.list_to_sale_ratio_pct, "%"),
            ("price reductions share", request.price_reductions_share_pct, "%"),
            ("seller concessions share", request.seller_concessions_share_pct, "%"),
            ("mortgage rate", request.mortgage_rate_pct, "%"),
            ("mortgage rate change", request.mortgage_rate_change_bps, " bps"),
            ("employment growth yoy", request.employment_growth_yoy_pct, "%"),
            ("permits yoy", request.permits_yoy_pct, "%"),
            ("completions yoy", request.completions_yoy_pct, "%"),
            ("rent growth yoy", request.rent_growth_yoy_pct, "%"),
            ("rental vacancy rate", request.rental_vacancy_rate_pct, "%"),
        ]
        for label, value, suffix in metrics:
            if value is None:
                continue
            parts.append(f"{label} {value}{suffix}")

        if request.migration_trend:
            parts.append(f"migration trend {request.migration_trend}")
        if request.builder_sentiment:
            parts.append(f"builder sentiment {request.builder_sentiment}")
        if request.segment_notes:
            parts.append(f"segment notes {request.segment_notes}")
        if request.notes:
            parts.append(f"notes {request.notes}")

        strongest = [item.rstrip(".") for item in heuristic["signals"]["positive"][:2] + heuristic["signals"]["risk"][:2]]
        if strongest:
            parts.append("key signals " + "; ".join(strongest))
        return ". ".join(part.strip().rstrip(".") for part in parts if part).strip() + "."

    def _heuristic_report(self, request: HousingMarketRequest) -> Dict[str, Any]:
        supply = self._score_supply(request)
        demand = self._score_demand(request)
        affordability = self._score_affordability(request)
        pricing = self._score_pricing(request)
        pipeline = self._score_pipeline(request)

        total_score = supply["score"] + demand["score"] + affordability["score"] + pricing["score"] + pipeline["score"]
        classification = self._label_from_score(total_score)
        coverage = max(1, request.available_metric_count())
        confidence = min(0.93, 0.38 + min(abs(total_score), 8.0) * 0.06 + min(coverage, 12) * 0.02)
        if classification == "balanced":
            confidence = max(0.42, confidence - 0.12)

        positive: List[str] = []
        risk: List[str] = []
        watch: List[str] = []
        for pillar in (supply, demand, affordability, pricing, pipeline):
            for item in pillar["positive"]:
                _append_signal(positive, item)
            for item in pillar["risk"]:
                _append_signal(risk, item)
            for item in pillar["watch"]:
                _append_signal(watch, item)

        return {
            "total_score": round(total_score, 2),
            "pillar_scores": {
                "supply": supply["payload"],
                "demand": demand["payload"],
                "affordability": affordability["payload"],
                "pricing": pricing["payload"],
                "pipeline": pipeline["payload"],
            },
            "signals": {
                "positive": positive,
                "risk": risk,
                "watch": watch,
            },
            "classification_signal": {
                "prediction": classification,
                "confidence": round(confidence, 4),
                "score": round(total_score, 2),
            },
        }

    def _label_from_score(self, score: float) -> str:
        if score >= 3.0:
            return "hot"
        if score <= -3.0:
            return "cooling"
        return "balanced"

    def _pillar_payload(
        self,
        name: str,
        score: float,
        positive: List[str],
        risk: List[str],
        watch: List[str],
    ) -> Dict[str, Any]:
        return {
            "pillar": name,
            "score": _clip_score(score),
            "positive": positive,
            "risk": risk,
            "watch": watch,
        }

    def _score_supply(self, request: HousingMarketRequest) -> Dict[str, Any]:
        score = 0.0
        positive: List[str] = []
        risk: List[str] = []
        watch: List[str] = []

        if request.active_listings_yoy_pct is not None:
            value = request.active_listings_yoy_pct
            if value <= -15:
                score += 2.0
                positive.append(f"Active listings are down {abs(value):.1f}% year over year.")
            elif value <= -5:
                score += 1.0
                positive.append(f"Inventory is tightening with listings down {abs(value):.1f}% year over year.")
            elif value >= 15:
                score -= 2.0
                risk.append(f"Active listings are up {value:.1f}% year over year.")
            elif value >= 5:
                score -= 1.0
                risk.append(f"Inventory is rebuilding with listings up {value:.1f}% year over year.")

        if request.months_of_supply is not None:
            value = request.months_of_supply
            if value < 2.5:
                score += 1.5
                positive.append(f"Months of supply is tight at {value:.1f}.")
            elif value < 4.0:
                score += 0.5
                watch.append(f"Supply remains healthy but not excessive at {value:.1f} months.")
            elif value > 6.0:
                score -= 1.5
                risk.append(f"Months of supply is elevated at {value:.1f}.")
            elif value > 5.0:
                score -= 0.75
                risk.append(f"Supply is drifting above balanced conditions at {value:.1f} months.")

        if request.days_on_market_yoy_pct is not None:
            value = request.days_on_market_yoy_pct
            if value <= -15:
                score += 1.0
                positive.append(f"Days on market improved {abs(value):.1f}% from last year.")
            elif value >= 25:
                score -= 1.5
                risk.append(f"Days on market worsened {value:.1f}% from last year.")

        payload = self._pillar_payload("supply", score, positive, risk, watch)
        return {
            "score": payload["score"],
            "positive": positive,
            "risk": risk,
            "watch": watch,
            "payload": payload,
        }

    def _score_demand(self, request: HousingMarketRequest) -> Dict[str, Any]:
        score = 0.0
        positive: List[str] = []
        risk: List[str] = []
        watch: List[str] = []

        if request.pending_sales_yoy_pct is not None:
            value = request.pending_sales_yoy_pct
            if value >= 10:
                score += 2.0
                positive.append(f"Pending sales are up {value:.1f}% year over year.")
            elif value >= 3:
                score += 1.0
                positive.append(f"Pending sales are improving by {value:.1f}% year over year.")
            elif value <= -10:
                score -= 2.0
                risk.append(f"Pending sales are down {abs(value):.1f}% year over year.")
            elif value <= -3:
                score -= 1.0
                risk.append(f"Pending sales are softening by {abs(value):.1f}% year over year.")

        if request.closed_sales_yoy_pct is not None:
            value = request.closed_sales_yoy_pct
            if value >= 5:
                score += 1.0
                positive.append(f"Closed sales are up {value:.1f}% year over year.")
            elif value <= -5:
                score -= 1.0
                risk.append(f"Closed sales are down {abs(value):.1f}% year over year.")

        migration = (request.migration_trend or "").strip().lower()
        if migration in {"inbound", "positive", "growing"}:
            score += 1.0
            positive.append("Migration trends are supportive.")
        elif migration in {"outbound", "negative", "shrinking"}:
            score -= 1.0
            risk.append("Migration trends are working against demand.")

        sentiment = (request.builder_sentiment or "").strip().lower()
        if sentiment in {"strong", "improving", "bullish"}:
            score += 0.75
            positive.append("Builder sentiment is positive.")
        elif sentiment in {"weak", "soft", "bearish"}:
            score -= 0.75
            risk.append("Builder sentiment is weak.")

        payload = self._pillar_payload("demand", score, positive, risk, watch)
        return {
            "score": payload["score"],
            "positive": positive,
            "risk": risk,
            "watch": watch,
            "payload": payload,
        }

    def _score_affordability(self, request: HousingMarketRequest) -> Dict[str, Any]:
        score = 0.0
        positive: List[str] = []
        risk: List[str] = []
        watch: List[str] = []

        if request.mortgage_rate_change_bps is not None:
            value = request.mortgage_rate_change_bps
            if value <= -50:
                score += 1.5
                positive.append(f"Mortgage rates improved by {abs(value):.0f} bps.")
            elif value >= 50:
                score -= 1.5
                risk.append(f"Mortgage rates worsened by {value:.0f} bps.")

        if request.mortgage_rate_pct is not None:
            value = request.mortgage_rate_pct
            if value <= 6.0:
                score += 0.5
                positive.append(f"Mortgage rates are supportive at {value:.2f}%.")
            elif value >= 7.0:
                score -= 1.0
                risk.append(f"Mortgage rates remain restrictive at {value:.2f}%.")

        if request.employment_growth_yoy_pct is not None:
            value = request.employment_growth_yoy_pct
            if value >= 2.0:
                score += 0.75
                positive.append(f"Employment growth is healthy at {value:.1f}% year over year.")
            elif value <= 0.0:
                score -= 1.0
                risk.append(f"Employment growth is weak at {value:.1f}% year over year.")

        if request.unemployment_rate_pct is not None:
            value = request.unemployment_rate_pct
            if value <= 4.5:
                score += 0.5
                positive.append(f"Unemployment is low at {value:.1f}%.")
            elif value >= 6.0:
                score -= 1.0
                risk.append(f"Unemployment is elevated at {value:.1f}%.")

        payload = self._pillar_payload("affordability", score, positive, risk, watch)
        return {
            "score": payload["score"],
            "positive": positive,
            "risk": risk,
            "watch": watch,
            "payload": payload,
        }

    def _score_pricing(self, request: HousingMarketRequest) -> Dict[str, Any]:
        score = 0.0
        positive: List[str] = []
        risk: List[str] = []
        watch: List[str] = []

        if request.median_sale_price_yoy_pct is not None:
            value = request.median_sale_price_yoy_pct
            if value >= 8.0:
                score += 2.0
                positive.append(f"Median sale prices are up {value:.1f}% year over year.")
            elif value >= 3.0:
                score += 1.0
                positive.append(f"Price growth remains constructive at {value:.1f}% year over year.")
            elif value <= -3.0:
                score -= 2.0
                risk.append(f"Median sale prices are down {abs(value):.1f}% year over year.")
            elif value <= 0.0:
                score -= 1.0
                risk.append("Price growth has stalled or turned negative.")

        if request.list_to_sale_ratio_pct is not None:
            value = request.list_to_sale_ratio_pct
            if value >= 99.0:
                score += 1.0
                positive.append(f"List to sale ratios remain strong at {value:.1f}%.")
            elif value < 97.0:
                score -= 1.0
                risk.append(f"List to sale ratios have weakened to {value:.1f}%.")

        if request.price_reductions_share_pct is not None:
            value = request.price_reductions_share_pct
            if value <= 10.0:
                score += 0.75
                positive.append(f"Price reductions are contained at {value:.1f}% of listings.")
            elif value >= 25.0:
                score -= 1.5
                risk.append(f"Price reductions are elevated at {value:.1f}% of listings.")

        if request.seller_concessions_share_pct is not None:
            value = request.seller_concessions_share_pct
            if value >= 20.0:
                score -= 1.0
                risk.append(f"Seller concessions are elevated at {value:.1f}% of deals.")
            elif value <= 8.0:
                score += 0.5
                positive.append(f"Seller concessions remain limited at {value:.1f}% of deals.")

        payload = self._pillar_payload("pricing", score, positive, risk, watch)
        return {
            "score": payload["score"],
            "positive": positive,
            "risk": risk,
            "watch": watch,
            "payload": payload,
        }

    def _score_pipeline(self, request: HousingMarketRequest) -> Dict[str, Any]:
        score = 0.0
        positive: List[str] = []
        risk: List[str] = []
        watch: List[str] = []

        if request.permits_yoy_pct is not None:
            value = request.permits_yoy_pct
            if value <= -10.0 and (request.active_listings_yoy_pct or 0.0) < 0:
                score += 0.75
                positive.append(f"Permits are down {abs(value):.1f}% which may keep future supply constrained.")
            elif value >= 15.0:
                watch.append(f"Permits are up {value:.1f}% and could rebuild supply later this year.")

        if request.completions_yoy_pct is not None and request.pending_sales_yoy_pct is not None:
            gap = request.completions_yoy_pct - request.pending_sales_yoy_pct
            if gap >= 10.0:
                score -= 1.25
                risk.append("Completions are outpacing pending demand growth.")
            elif gap <= -5.0:
                score += 0.5
                positive.append("Demand is absorbing deliveries faster than completions are growing.")

        if request.rent_growth_yoy_pct is not None:
            value = request.rent_growth_yoy_pct
            if value >= 4.0:
                score += 0.5
                positive.append(f"Rent growth remains supportive at {value:.1f}% year over year.")
            elif value <= 0.0:
                score -= 0.5
                risk.append("Rent growth has flattened, which can pressure investor demand.")

        if request.rental_vacancy_rate_pct is not None:
            value = request.rental_vacancy_rate_pct
            if value >= 8.0:
                score -= 0.75
                risk.append(f"Rental vacancy is elevated at {value:.1f}%.")
            elif value <= 5.0:
                score += 0.5
                positive.append(f"Rental vacancy is tight at {value:.1f}%.")

        payload = self._pillar_payload("pipeline", score, positive, risk, watch)
        return {
            "score": payload["score"],
            "positive": positive,
            "risk": risk,
            "watch": watch,
            "payload": payload,
        }

    def _action_plan(self, classification: str, heuristic: Dict[str, Any]) -> Dict[str, str]:
        risks = heuristic["signals"]["risk"]
        positives = heuristic["signals"]["positive"]
        if classification == "hot":
            return {
                "acquisition": "Stay active in constrained submarkets, but underwrite to slower absorption where new supply is ramping.",
                "pricing": "Push price cautiously before leaning on incentives; protect net pricing while list-to-sale ratios stay firm.",
                "product_mix": "Favor entry-level and move-up formats with proven turnover and keep quick-move-in inventory disciplined.",
                "risk_management": (
                    "Monitor " + risks[0].lower()
                    if risks
                    else "Monitor mortgage-rate volatility and signs of delivery volumes outrunning absorption."
                ),
            }
        if classification == "cooling":
            return {
                "acquisition": "Throttle discretionary land spend and prioritize deals with short entitlement duration and flexible takedowns.",
                "pricing": "Defend absorption first; use targeted incentives and price cuts surgically where aging inventory is building.",
                "product_mix": "Shift toward smaller, payment-sensitive products and delay speculative inventory where backlog is soft.",
                "risk_management": (
                    "Address " + risks[0].lower()
                    if risks
                    else "Watch concessions, cancellation risk, and any further drop in pending demand."
                ),
            }
        return {
            "acquisition": "Stay selective and favor submarkets where supply is controlled and demand has a clear local tailwind.",
            "pricing": "Hold pricing discipline, but keep tactical incentives ready if absorption slows by segment.",
            "product_mix": "Maintain a balanced mix and reallocate toward the segments showing the strongest local turnover.",
            "risk_management": (
                "Lean into " + positives[0].lower()
                if positives
                else "Keep watching both affordability and delivery pacing because either can move the market off balance quickly."
            ),
        }

    def _scenario_outlook(
        self,
        request: HousingMarketRequest,
        heuristic: Dict[str, Any],
        classification: str,
    ) -> Dict[str, str]:
        positives = heuristic["signals"]["positive"]
        risks = heuristic["signals"]["risk"]
        if classification == "hot":
            base_case = "Base case is continued seller leverage with selective inventory pressure concentrated in the most affordable segments."
        elif classification == "cooling":
            base_case = "Base case is slower absorption, heavier incentives, and more negotiation leverage shifting to buyers."
        else:
            base_case = "Base case is a range-bound market with localized pockets of strength and softness."

        upside = positives[0] if positives else "Mortgage costs ease further and demand stabilizes faster than supply can rebuild."
        downside = risks[0] if risks else "Affordability worsens or delivery volumes outrun demand."

        return {
            "base_case": base_case,
            "upside_trigger": upside,
            "downside_trigger": downside,
            "notes": request.segment_notes or request.notes,
        }
