import unittest

from agent_factory.subdivision_scout import SubdivisionScout, _assess_homebuilder_opportunity, _compose_parcel_text


class FakeSpecialist:
    def __init__(self, default_prediction: str = "not_ready", default_confidence: float = 0.88) -> None:
        self.metadata = {"blueprint": {"name": "ResidentialSubdivisionScout"}}
        self.default_prediction = default_prediction
        self.default_confidence = default_confidence

    def predict(self, text: str) -> dict:
        prediction = self.default_prediction
        confidence = self.default_confidence
        lowered = text.lower()
        if "finished lots" in lowered or "tentative subdivision map approved" in lowered:
            prediction = "high_probability"
            confidence = 0.91

        alternate = "high_probability" if prediction == "not_ready" else "not_ready"
        return {
            "prediction": prediction,
            "top_classes": [
                {"label": prediction, "confidence": confidence},
                {"label": alternate, "confidence": round(1.0 - confidence, 2)},
            ],
        }


class SubdivisionScoutTests(unittest.TestCase):
    def test_compose_parcel_text_labels_structured_fields(self) -> None:
        text = _compose_parcel_text(
            {
                "parcel_id": "roseville-1",
                "market": "Roseville, CA",
                "acres": "13.4",
                "planned_lots": "82",
                "description": "Adjacent to existing rooftops.",
            }
        )

        self.assertIn("Acres: 13.4", text)
        self.assertIn("Planned lots: 82", text)
        self.assertIn("Market: Roseville, CA", text)

    def test_homebuilder_assessment_rewards_ready_lot_delivery(self) -> None:
        ready = _assess_homebuilder_opportunity(
            "32 finished lots with final map recorded, utilities at site, existing rooftops, and minimal grading."
        )
        risky = _assess_homebuilder_opportunity(
            "18 acres outside city limits with septic, annexation, wetlands, and utility extension before any map can move forward."
        )

        self.assertEqual(ready.opportunity_profile, "finished_lot_delivery")
        self.assertGreater(ready.priority_score, risky.priority_score)
        self.assertGreater(ready.execution_readiness_score, risky.execution_readiness_score)

    def test_scout_prioritizes_builder_ready_site_over_raw_land(self) -> None:
        scout = SubdivisionScout(FakeSpecialist(default_prediction="not_ready", default_confidence=0.9))
        results = scout.screen_parcel_rows(
            [
                {
                    "parcel_id": "ready-1",
                    "market": "Roseville, CA",
                    "acres": "14",
                    "planned_lots": "84",
                    "description": "Tentative subdivision map approved with utilities at site and adjacent existing subdivision.",
                    "notes": "Strong school demand, clean title, minimal grading.",
                },
                {
                    "parcel_id": "risky-1",
                    "market": "Placer County, CA",
                    "acres": "18",
                    "description": "Raw land outside city limits with wetlands, septic, and utility extension exposure.",
                    "notes": "Annexation and title issue risk remain open.",
                },
            ]
        )

        self.assertEqual(results[0]["parcel_id"], "ready-1")
        self.assertGreater(results[0]["priority_score"], results[1]["priority_score"])
        self.assertIn(results[0]["recommendation"], {"watch", "prioritize"})
        self.assertEqual(results[1]["recommendation"], "pass")


if __name__ == "__main__":
    unittest.main()