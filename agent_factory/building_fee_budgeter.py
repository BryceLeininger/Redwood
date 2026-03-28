"""Deterministic workflow for building and impact fee budgeting."""
from __future__ import annotations

import ast
import math
import operator
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Sequence

from .specialist_agent import SpecialistAgent


class FormulaEvaluationError(ValueError):
    """Raised when a fee formula cannot be evaluated safely."""


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", value.strip().lower())
    return slug.strip("_") or "item"


def _float_from_value(value: Any, *, default: float = 0.0) -> float:
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace("$", "").replace(",", "")
    if not text:
        return default
    return float(text)


def _coerce_context_value(value: Any) -> Any:
    if isinstance(value, (bool, int, float)):
        return value
    if value is None:
        return value
    text = str(value).strip()
    if not text:
        return ""
    lowered = text.lower()
    if lowered in {"true", "yes", "y"}:
        return True
    if lowered in {"false", "no", "n"}:
        return False
    numeric_text = text.replace("$", "").replace(",", "")
    if re.fullmatch(r"-?\d+(\.\d+)?", numeric_text):
        return float(numeric_text)
    return text


def _round_money(value: float) -> float:
    return round(float(value), 2)


def _rounding_label(mode: str) -> str:
    return (mode or "nearest_cent").strip().lower()


def _apply_rounding(value: float, mode: str) -> float:
    normalized = _rounding_label(mode)
    if normalized in {"nearest_cent", "cent", "cents"}:
        return round(float(value), 2)
    if normalized in {"nearest_dollar", "dollar", "whole_dollar"}:
        return float(round(float(value)))
    if normalized in {"up_to_dollar", "ceil_dollar", "up"}:
        return float(math.ceil(float(value)))
    if normalized in {"down_to_dollar", "floor_dollar", "down"}:
        return float(math.floor(float(value)))
    raise ValueError(f"Unsupported rounding mode: {mode}")


@dataclass(frozen=True)
class FeeLineItem:
    code: str
    name: str
    category: str
    formula: str
    applies_when: str | None = None
    source_reference: str = ""
    basis_note: str = ""
    rounding: str = "nearest_cent"

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any], *, index: int) -> "FeeLineItem":
        name = str(payload.get("name") or "").strip()
        if not name:
            raise ValueError(f"Fee item #{index} is missing a name.")

        code = str(payload.get("code") or _slugify(name)).strip()
        formula = str(payload.get("formula") or "").strip()
        if not formula:
            raise ValueError(f"Fee item '{name}' is missing a formula.")

        category = str(payload.get("category") or "other").strip() or "other"
        applies_when = payload.get("applies_when")
        return cls(
            code=code,
            name=name,
            category=category,
            formula=formula,
            applies_when=str(applies_when).strip() if applies_when not in (None, "") else None,
            source_reference=str(payload.get("source_reference") or "").strip(),
            basis_note=str(payload.get("basis_note") or "").strip(),
            rounding=str(payload.get("rounding") or "nearest_cent").strip() or "nearest_cent",
        )


@dataclass(frozen=True)
class AgencyFeeSchedule:
    name: str
    jurisdiction: str
    fee_schedule_name: str
    effective_date: str
    source_url: str
    source_reference: str
    notes: str
    variables: Mapping[str, Any] = field(default_factory=dict)
    items: Sequence[FeeLineItem] = field(default_factory=list)

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any], *, index: int) -> "AgencyFeeSchedule":
        name = str(payload.get("name") or "").strip()
        if not name:
            raise ValueError(f"Agency #{index} is missing a name.")

        raw_items = payload.get("items") or []
        if not isinstance(raw_items, list) or not raw_items:
            raise ValueError(f"Agency '{name}' must contain at least one fee item.")

        items = [FeeLineItem.from_dict(item, index=item_index) for item_index, item in enumerate(raw_items, start=1)]
        return cls(
            name=name,
            jurisdiction=str(payload.get("jurisdiction") or "").strip(),
            fee_schedule_name=str(payload.get("fee_schedule_name") or "").strip(),
            effective_date=str(payload.get("effective_date") or "").strip(),
            source_url=str(payload.get("source_url") or "").strip(),
            source_reference=str(payload.get("source_reference") or "").strip(),
            notes=str(payload.get("notes") or "").strip(),
            variables=dict(payload.get("variables") or {}),
            items=items,
        )


@dataclass(frozen=True)
class FeeBudgetRequest:
    project: Mapping[str, Any]
    variables: Mapping[str, Any]
    agencies: Sequence[AgencyFeeSchedule]
    assumptions: Sequence[str]
    notes: str

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "FeeBudgetRequest":
        project = dict(payload.get("project") or {})
        agencies = [
            AgencyFeeSchedule.from_dict(item, index=index)
            for index, item in enumerate(payload.get("agencies") or [], start=1)
        ]
        if not agencies:
            raise ValueError("At least one agency schedule is required.")

        assumptions = [str(item).strip() for item in payload.get("assumptions") or [] if str(item).strip()]
        notes = str(payload.get("notes") or project.get("notes") or "").strip()
        return cls(
            project=project,
            variables=dict(payload.get("variables") or {}),
            agencies=agencies,
            assumptions=assumptions,
            notes=notes,
        )

    @property
    def project_name(self) -> str:
        return str(
            self.project.get("project_name")
            or self.project.get("community_name")
            or self.project.get("name")
            or "Unnamed Project"
        ).strip() or "Unnamed Project"

    @property
    def jurisdiction(self) -> str:
        return str(self.project.get("jurisdiction") or self.project.get("market") or "").strip()

    def formula_context(self) -> Dict[str, Any]:
        context: Dict[str, Any] = {}
        for source in (self.project, self.variables):
            for key, value in source.items():
                cleaned_key = str(key).strip()
                if not cleaned_key:
                    continue
                context[cleaned_key] = _coerce_context_value(value)
        return context


_ALLOWED_BINARY_OPERATORS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}

_ALLOWED_UNARY_OPERATORS = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
    ast.Not: operator.not_,
}

_ALLOWED_COMPARE_OPERATORS = {
    ast.Eq: operator.eq,
    ast.NotEq: operator.ne,
    ast.Lt: operator.lt,
    ast.LtE: operator.le,
    ast.Gt: operator.gt,
    ast.GtE: operator.ge,
}

_ALLOWED_FUNCTIONS = {
    "abs": abs,
    "ceil": math.ceil,
    "floor": math.floor,
    "max": max,
    "min": min,
    "round": round,
}


def _evaluate_formula(expression: str, context: Mapping[str, Any], computed_items: Mapping[str, float]) -> Any:
    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError as error:
        raise FormulaEvaluationError(f"Invalid formula syntax '{expression}': {error.msg}") from error

    def lookup_item(code: str) -> float:
        cleaned_code = str(code).strip()
        if cleaned_code not in computed_items:
            raise FormulaEvaluationError(f"Formula '{expression}' references unknown prior line item '{cleaned_code}'.")
        return float(computed_items[cleaned_code])

    def evaluate(node: ast.AST) -> Any:
        if isinstance(node, ast.Expression):
            return evaluate(node.body)
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, ast.Name):
            if node.id not in context:
                raise FormulaEvaluationError(f"Formula '{expression}' references missing input '{node.id}'.")
            return context[node.id]
        if isinstance(node, ast.BinOp):
            operator_type = type(node.op)
            if operator_type not in _ALLOWED_BINARY_OPERATORS:
                raise FormulaEvaluationError(f"Unsupported operator in formula '{expression}'.")
            return _ALLOWED_BINARY_OPERATORS[operator_type](evaluate(node.left), evaluate(node.right))
        if isinstance(node, ast.UnaryOp):
            operator_type = type(node.op)
            if operator_type not in _ALLOWED_UNARY_OPERATORS:
                raise FormulaEvaluationError(f"Unsupported unary operator in formula '{expression}'.")
            return _ALLOWED_UNARY_OPERATORS[operator_type](evaluate(node.operand))
        if isinstance(node, ast.BoolOp):
            if isinstance(node.op, ast.And):
                result = True
                for value in node.values:
                    result = evaluate(value)
                    if not result:
                        return result
                return result
            if isinstance(node.op, ast.Or):
                result = False
                for value in node.values:
                    result = evaluate(value)
                    if result:
                        return result
                return result
            raise FormulaEvaluationError(f"Unsupported boolean operator in formula '{expression}'.")
        if isinstance(node, ast.Compare):
            left = evaluate(node.left)
            for operator_node, comparator in zip(node.ops, node.comparators):
                operator_type = type(operator_node)
                if operator_type not in _ALLOWED_COMPARE_OPERATORS:
                    raise FormulaEvaluationError(f"Unsupported comparison in formula '{expression}'.")
                right = evaluate(comparator)
                if not _ALLOWED_COMPARE_OPERATORS[operator_type](left, right):
                    return False
                left = right
            return True
        if isinstance(node, ast.IfExp):
            return evaluate(node.body) if evaluate(node.test) else evaluate(node.orelse)
        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name):
                raise FormulaEvaluationError(f"Unsupported function call in formula '{expression}'.")
            function_name = node.func.id
            args = [evaluate(argument) for argument in node.args]
            if node.keywords:
                raise FormulaEvaluationError(f"Keyword arguments are not supported in formula '{expression}'.")
            if function_name == "item":
                if len(args) != 1:
                    raise FormulaEvaluationError("item() expects exactly one line-item code argument.")
                return lookup_item(str(args[0]))
            if function_name not in _ALLOWED_FUNCTIONS:
                raise FormulaEvaluationError(f"Unsupported function '{function_name}' in formula '{expression}'.")
            return _ALLOWED_FUNCTIONS[function_name](*args)
        raise FormulaEvaluationError(f"Unsupported expression component in formula '{expression}'.")

    return evaluate(tree)


class BuildingFeeBudgeter:
    """Prices fee schedules from structured official inputs instead of guessing."""

    def __init__(self, specialist: SpecialistAgent | None = None) -> None:
        self.specialist = specialist

    def budget(self, payload: Mapping[str, Any]) -> Dict[str, Any]:
        request = FeeBudgetRequest.from_dict(payload)
        formula_context = request.formula_context()

        agency_results: List[Dict[str, Any]] = []
        category_totals: Dict[str, float] = {}
        warnings: List[str] = []
        line_item_count = 0

        for agency in request.agencies:
            agency_result = self._price_agency(agency, formula_context)
            line_item_count += len(agency_result["items"])
            agency_results.append(agency_result)
            warnings.extend(agency_result.pop("_warnings"))
            for category, amount in agency_result["category_totals"].items():
                category_totals[category] = category_totals.get(category, 0.0) + float(amount)

        grand_total = _round_money(sum(float(item["total"]) for item in agency_results))
        totals = {
            "grand_total": grand_total,
            "agency_count": len(agency_results),
            "line_item_count": line_item_count,
        }

        for field_name, label in (
            ("total_units", "per_unit"),
            ("dwelling_units", "per_unit"),
            ("lots", "per_unit"),
        ):
            denominator = formula_context.get(field_name)
            if isinstance(denominator, (int, float)) and float(denominator) > 0:
                totals[label] = _round_money(grand_total / float(denominator))
                break

        for field_name, label in (
            ("residential_sqft", "per_sqft"),
            ("total_sqft", "per_sqft"),
            ("building_sqft", "per_sqft"),
        ):
            denominator = formula_context.get(field_name)
            if isinstance(denominator, (int, float)) and float(denominator) > 0:
                totals[label] = _round_money(grand_total / float(denominator))
                break

        valuation = formula_context.get("building_valuation")
        if isinstance(valuation, (int, float)) and float(valuation) > 0:
            totals["pct_of_valuation"] = round(grand_total / float(valuation), 4)

        result: Dict[str, Any] = {
            "project": {
                "project_name": request.project_name,
                "jurisdiction": request.jurisdiction,
                "notes": request.notes,
                "inputs": request.project,
                "variables": request.variables,
            },
            "status": "complete",
            "totals": totals,
            "agency_totals": agency_results,
            "category_totals": {key: _round_money(value) for key, value in sorted(category_totals.items())},
            "citations": [
                {
                    "agency": agency.name,
                    "jurisdiction": agency.jurisdiction,
                    "fee_schedule_name": agency.fee_schedule_name,
                    "effective_date": agency.effective_date,
                    "source_url": agency.source_url,
                    "source_reference": agency.source_reference,
                }
                for agency in request.agencies
            ],
            "validation": {
                "warnings": warnings,
                "assumptions": list(request.assumptions),
            },
        }

        if self.specialist is not None:
            result["specialist_signal"] = self.specialist.predict(self._specialist_summary(request, warnings))

        return result

    def budget_many(self, payloads: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
        return [self.budget(payload) for payload in payloads]

    def _price_agency(self, agency: AgencyFeeSchedule, base_context: Mapping[str, Any]) -> Dict[str, Any]:
        agency_context = dict(base_context)
        agency_context.update({key: _coerce_context_value(value) for key, value in agency.variables.items()})

        category_totals: Dict[str, float] = {}
        computed_items: Dict[str, float] = {}
        warnings: List[str] = []
        results: List[Dict[str, Any]] = []
        seen_codes: set[str] = set()

        if not agency.effective_date:
            warnings.append(f"{agency.name}: missing effective_date.")
        if not agency.source_url and not agency.source_reference:
            warnings.append(f"{agency.name}: missing source_url or source_reference.")

        for item in agency.items:
            if item.code in seen_codes:
                raise ValueError(f"Agency '{agency.name}' contains duplicate fee item code '{item.code}'.")
            seen_codes.add(item.code)

            applies = True
            if item.applies_when:
                applies = bool(_evaluate_formula(item.applies_when, agency_context, computed_items))

            raw_amount = 0.0
            if applies:
                evaluated = _evaluate_formula(item.formula, agency_context, computed_items)
                if isinstance(evaluated, bool) or not isinstance(evaluated, (int, float)):
                    raise FormulaEvaluationError(
                        f"Formula '{item.formula}' for line item '{item.name}' must resolve to a number."
                    )
                raw_amount = float(evaluated)

            amount = _apply_rounding(raw_amount, item.rounding)
            computed_items[item.code] = amount
            category_totals[item.category] = category_totals.get(item.category, 0.0) + amount
            results.append(
                {
                    "code": item.code,
                    "name": item.name,
                    "category": item.category,
                    "formula": item.formula,
                    "applies_when": item.applies_when,
                    "applied": applies,
                    "amount": _round_money(amount),
                    "rounding": _rounding_label(item.rounding),
                    "source_reference": item.source_reference,
                    "basis_note": item.basis_note,
                }
            )

        return {
            "agency": agency.name,
            "jurisdiction": agency.jurisdiction,
            "fee_schedule_name": agency.fee_schedule_name,
            "effective_date": agency.effective_date,
            "source_url": agency.source_url,
            "source_reference": agency.source_reference,
            "notes": agency.notes,
            "category_totals": {key: _round_money(value) for key, value in sorted(category_totals.items())},
            "items": results,
            "total": _round_money(sum(computed_items.values())),
            "_warnings": warnings,
        }

    def _specialist_summary(self, request: FeeBudgetRequest, warnings: Sequence[str]) -> str:
        source_count = sum(
            1 for agency in request.agencies if agency.source_url or agency.source_reference or agency.fee_schedule_name
        )
        effective_date_count = sum(1 for agency in request.agencies if agency.effective_date)
        item_count = sum(len(agency.items) for agency in request.agencies)

        parts = [
            f"Project: {request.project_name}",
            f"Jurisdiction: {request.jurisdiction or 'unknown'}",
            f"Agencies: {len(request.agencies)}",
            f"Fee items: {item_count}",
            f"Source records: {source_count}",
            f"Effective dates captured: {effective_date_count}",
            f"Warnings: {len(warnings)}",
        ]
        if request.notes:
            parts.append(f"Notes: {request.notes}")
        if warnings:
            parts.append("Warning detail: " + " | ".join(warnings[:5]))
        return ". ".join(parts)
