import unittest

from agent_factory.building_fee_budgeter import BuildingFeeBudgeter, FormulaEvaluationError


class FakeSpecialist:
    def __init__(self) -> None:
        self.metadata = {"blueprint": {"name": "BuildingImpactFeeBudgetAdvisor"}}

    def predict(self, text: str) -> dict:
        label = "ready_to_budget"
        if "Warnings: 0" not in text:
            label = "needs_source_confirmation"
        return {
            "prediction": label,
            "top_classes": [
                {"label": label, "confidence": 0.91},
                {"label": "missing_critical_inputs", "confidence": 0.09},
            ],
        }


class BuildingFeeBudgeterTests(unittest.TestCase):
    def test_budget_rolls_up_multiple_agencies_and_categories(self) -> None:
        budgeter = BuildingFeeBudgeter()
        result = budgeter.budget(
            {
                "project": {
                    "project_name": "Maple Grove",
                    "jurisdiction": "Folsom, CA",
                    "total_units": 10,
                    "residential_sqft": 20000,
                    "building_valuation": 3500000,
                    "service_connections": 10,
                },
                "agencies": [
                    {
                        "name": "City Building",
                        "fee_schedule_name": "Building Fees",
                        "effective_date": "2026-01-01",
                        "source_reference": "Schedule A",
                        "items": [
                            {
                                "code": "PERMIT",
                                "name": "Building permit",
                                "category": "building_permit",
                                "formula": "building_valuation * 0.01",
                            },
                            {
                                "code": "PLAN",
                                "name": "Plan check",
                                "category": "plan_check",
                                "formula": "item(\"PERMIT\") * 0.5",
                            },
                        ],
                    },
                    {
                        "name": "City Impact Fees",
                        "fee_schedule_name": "Impact Fees",
                        "effective_date": "2026-01-01",
                        "source_reference": "Resolution 22",
                        "items": [
                            {
                                "code": "TRAFFIC",
                                "name": "Traffic impact",
                                "category": "impact_fee",
                                "formula": "total_units * 3000",
                            },
                            {
                                "code": "SCHOOL",
                                "name": "School fee",
                                "category": "school_fee",
                                "formula": "residential_sqft * 4",
                            },
                        ],
                    },
                ],
            }
        )

        self.assertEqual(result["totals"]["grand_total"], 162500.0)
        self.assertEqual(result["totals"]["per_unit"], 16250.0)
        self.assertEqual(result["totals"]["per_sqft"], 8.12)
        self.assertEqual(result["totals"]["pct_of_valuation"], 0.0464)
        self.assertEqual(result["category_totals"]["building_permit"], 35000.0)
        self.assertEqual(result["category_totals"]["plan_check"], 17500.0)
        self.assertEqual(result["category_totals"]["impact_fee"], 30000.0)
        self.assertEqual(result["category_totals"]["school_fee"], 80000.0)
        self.assertEqual(result["agency_totals"][0]["items"][1]["amount"], 17500.0)

    def test_budget_honors_rounding_and_applies_when(self) -> None:
        budgeter = BuildingFeeBudgeter()
        result = budgeter.budget(
            {
                "project": {
                    "project_name": "Cornerstone",
                    "jurisdiction": "Roseville, CA",
                    "total_units": 3,
                },
                "variables": {
                    "include_option": False,
                },
                "agencies": [
                    {
                        "name": "City Admin",
                        "fee_schedule_name": "Admin Fees",
                        "effective_date": "2026-01-01",
                        "source_reference": "Table 1",
                        "items": [
                            {
                                "code": "ADMIN",
                                "name": "Admin fee",
                                "category": "admin",
                                "formula": "99.2",
                                "rounding": "up_to_dollar",
                            },
                            {
                                "code": "OPTIONAL",
                                "name": "Optional surcharge",
                                "category": "admin",
                                "formula": "250",
                                "applies_when": "include_option",
                            },
                        ],
                    }
                ],
            }
        )

        self.assertEqual(result["totals"]["grand_total"], 100.0)
        self.assertEqual(result["agency_totals"][0]["items"][0]["amount"], 100.0)
        self.assertFalse(result["agency_totals"][0]["items"][1]["applied"])
        self.assertEqual(result["agency_totals"][0]["items"][1]["amount"], 0.0)

    def test_budget_raises_when_formula_input_is_missing(self) -> None:
        budgeter = BuildingFeeBudgeter()
        with self.assertRaises(FormulaEvaluationError):
            budgeter.budget(
                {
                    "project": {
                        "project_name": "Broken Packet",
                    },
                    "agencies": [
                        {
                            "name": "School District",
                            "fee_schedule_name": "School Fee",
                            "effective_date": "2026-01-01",
                            "source_reference": "Resolution A",
                            "items": [
                                {
                                    "name": "School fee",
                                    "category": "school_fee",
                                    "formula": "residential_sqft * 4.79",
                                }
                            ],
                        }
                    ],
                }
            )

    def test_budget_can_include_specialist_signal(self) -> None:
        budgeter = BuildingFeeBudgeter(FakeSpecialist())
        result = budgeter.budget(
            {
                "project": {
                    "project_name": "Signal Test",
                    "jurisdiction": "Rocklin, CA",
                    "total_units": 2,
                },
                "agencies": [
                    {
                        "name": "City Building",
                        "fee_schedule_name": "Building Fees",
                        "effective_date": "2026-01-01",
                        "source_reference": "Schedule A",
                        "items": [
                            {
                                "name": "Admin fee",
                                "category": "admin",
                                "formula": "50",
                            }
                        ],
                    }
                ],
            }
        )

        self.assertIn("specialist_signal", result)
        self.assertEqual(result["specialist_signal"]["prediction"], "ready_to_budget")


if __name__ == "__main__":
    unittest.main()
