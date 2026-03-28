import unittest

from agent_factory.housing_market_researcher import HousingMarketResearcher


class FakeSpecialist:
    def __init__(self, prediction: str, confidence: float = 0.86) -> None:
        self.prediction = prediction
        self.confidence = confidence
        self.metadata = {"blueprint": {"name": "HousingMarketResearcher"}}

    def predict(self, text: str) -> dict:
        alternate = "balanced" if self.prediction != "balanced" else "cooling"
        return {
            "prediction": self.prediction,
            "top_classes": [
                {"label": self.prediction, "confidence": self.confidence},
                {"label": alternate, "confidence": round(1.0 - self.confidence, 2)},
            ],
        }


class HousingMarketResearcherTests(unittest.TestCase):
    def test_hot_market_packet_scores_as_hot(self) -> None:
        researcher = HousingMarketResearcher()
        result = researcher.research(
            {
                "market": "Phoenix-Mesa-Scottsdale, AZ",
                "metrics": {
                    "active_listings_yoy_pct": -16,
                    "months_of_supply": 2.2,
                    "median_sale_price_yoy_pct": 7.1,
                    "pending_sales_yoy_pct": 10.4,
                    "days_on_market_yoy_pct": -19,
                    "list_to_sale_ratio_pct": 99.3,
                    "price_reductions_share_pct": 8.2,
                    "seller_concessions_share_pct": 6.5,
                    "employment_growth_yoy_pct": 2.5,
                    "unemployment_rate_pct": 4.0,
                    "rent_growth_yoy_pct": 4.1,
                    "migration_trend": "inbound",
                    "builder_sentiment": "strong",
                },
            }
        )

        self.assertEqual(result["classification"], "hot")
        self.assertGreater(result["pillar_scores"]["supply"]["score"], 0)
        self.assertIn("pricing", result["actions"])

    def test_cooling_market_packet_scores_as_cooling(self) -> None:
        researcher = HousingMarketResearcher()
        result = researcher.research(
            {
                "market": "Austin-Round Rock, TX",
                "metrics": {
                    "active_listings_yoy_pct": 24,
                    "months_of_supply": 6.4,
                    "median_sale_price_yoy_pct": -3.6,
                    "pending_sales_yoy_pct": -12.0,
                    "closed_sales_yoy_pct": -8.0,
                    "days_on_market_yoy_pct": 34.0,
                    "list_to_sale_ratio_pct": 96.6,
                    "price_reductions_share_pct": 31.0,
                    "seller_concessions_share_pct": 24.0,
                    "mortgage_rate_pct": 7.2,
                    "mortgage_rate_change_bps": 55.0,
                    "employment_growth_yoy_pct": -0.4,
                    "completions_yoy_pct": 15.0,
                    "rent_growth_yoy_pct": -0.5,
                    "migration_trend": "outbound",
                    "builder_sentiment": "weak",
                },
            }
        )

        self.assertEqual(result["classification"], "cooling")
        self.assertLess(result["pillar_scores"]["demand"]["score"], 0)
        self.assertTrue(result["signals"]["risk"])

    def test_specialist_and_heuristic_agreement_reports_ensemble_basis(self) -> None:
        researcher = HousingMarketResearcher(FakeSpecialist(prediction="hot", confidence=0.9))
        result = researcher.research(
            {
                "market": "Tampa-St. Petersburg-Clearwater, FL",
                "metrics": {
                    "active_listings_yoy_pct": -12,
                    "months_of_supply": 2.9,
                    "median_sale_price_yoy_pct": 5.0,
                    "pending_sales_yoy_pct": 6.0,
                    "list_to_sale_ratio_pct": 99.0,
                    "price_reductions_share_pct": 9.0,
                    "seller_concessions_share_pct": 7.5,
                    "employment_growth_yoy_pct": 2.1,
                    "migration_trend": "inbound",
                },
                "notes": "Buyer traffic has recovered after lower rates improved monthly payments.",
            }
        )

        self.assertEqual(result["classification"], "hot")
        self.assertEqual(result["classification_basis"], "ensemble")
        self.assertIsNotNone(result["model_signal"])


if __name__ == "__main__":
    unittest.main()
