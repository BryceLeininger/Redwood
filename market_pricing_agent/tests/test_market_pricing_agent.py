from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from market_pricing_agent.agent import run_pricing_agent
from market_pricing_agent.config import load_sources_config
from market_pricing_agent.tools.extractors import extract_records
from market_pricing_agent.tools.fetcher import fetch_source


class MarketPricingAgentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.examples_dir = Path(__file__).resolve().parents[1] / "examples"
        self.project_config = self.examples_dir / "sample_project.json"
        self.sources_config = self.examples_dir / "sample_sources.json"

    def test_community_html_sources_extract_pricing(self) -> None:
        sources = load_sources_config(self.sources_config)
        community_sources = [source for source in sources if source.kind == "community"]

        extracted_count = 0
        for source in community_sources:
            records = extract_records(fetch_source(source))
            self.assertGreaterEqual(len(records), 1)
            self.assertIsNotNone(records[0].effective_price)
            self.assertIsNotNone(records[0].price_per_sqft)
            extracted_count += len(records)

        self.assertEqual(extracted_count, 6)

    def test_full_analysis_writes_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            result, artifacts = run_pricing_agent(
                self.project_config,
                self.sources_config,
                output_dir=temp_dir,
            )

            self.assertTrue(artifacts.report_path.exists())
            self.assertTrue(artifacts.analysis_path.exists())
            self.assertTrue(artifacts.comps_path.exists())
            self.assertGreaterEqual(result.extracted_comp_count, 5)
            self.assertEqual(result.recommendation.position_label, "market")
            self.assertGreater(result.recommendation.suggested_price_psf, 195.0)
            self.assertLess(result.recommendation.suggested_price_psf, 225.0)
            self.assertGreater(result.recommendation.confidence_score, 0.6)


if __name__ == "__main__":
    unittest.main()