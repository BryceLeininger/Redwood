# Market Pricing Agent

`market_pricing_agent` is a deterministic underwriting helper for new-home projects.

It does four things:

- fetches current new-home community pricing from public HTML pages or local HTML snapshots
- ingests recent resale comps from CSV, JSON, or HTML/table sources
- normalizes the data into a common comp model
- recommends a pricing position and price range for a potential new project

## Why it is separate from `agent_factory`

The existing `agent_factory` package is optimized for text classification/regression over static CSV training data. Pricing strategy is a live data collection and rules-based analysis problem, so this package follows the deterministic tool-driven pattern used by `fred_agent`.

## Install

From the repository root:

```bash
python -m pip install -r market_pricing_agent/requirements.txt
```

## Run the sample analysis

From the repository root:

```bash
python -m market_pricing_agent analyze \
  --project-config market_pricing_agent/examples/sample_project.json \
  --sources-config market_pricing_agent/examples/sample_sources.json \
  --print-report
```

Or use the batch launcher:

```bash
run_market_pricing_agent.bat analyze --project-config market_pricing_agent/examples/sample_project.json --sources-config market_pricing_agent/examples/sample_sources.json --print-report
```

Outputs are written under:

- `market_pricing_agent/outputs/<project>_<timestamp>/pricing_report.md`
- `market_pricing_agent/outputs/<project>_<timestamp>/analysis.json`
- `market_pricing_agent/outputs/<project>_<timestamp>/normalized_comps.csv`

## Config files

### Project config

Example `sample_project.json`:

```json
{
  "name": "Willow Bend",
  "submarket": "Northlake",
  "product_type": "single_family_detached",
  "avg_living_area_sqft": 2400,
  "quality_tier": "market",
  "target_position": "market",
  "bedrooms": 4,
  "bathrooms": 3,
  "garage_spaces": 2,
  "lot_width_ft": 50,
  "notes": "Entry move-up program close to major job centers."
}
```

### Sources config

Example `sample_sources.json`:

```json
{
  "submarket": "Northlake",
  "sources": [
    {
      "name": "Builder Alpha",
      "kind": "community",
      "source_type": "html",
      "location": "sample_builder_community_alpha.html"
    },
    {
      "name": "Recent Resales",
      "kind": "resale",
      "source_type": "csv",
      "location": "sample_resales.csv"
    }
  ]
}
```

Each source supports:

- `kind`: `community` or `resale`
- `source_type`: `html`, `csv`, or `json`
- `location`: URL or local file path
- `field_map`: optional column mapping override when your CSV/JSON column names are non-standard
- `headers`: optional HTTP headers for remote requests

## Source guidance

- New-home community pricing works best with public builder pages that expose prices or price bands in visible text or JSON-LD.
- Recent resale data is usually strongest from MLS or brokerage CSV exports because those files contain closed price, close date, and living area.
- The agent does not depend on a single data vendor. It uses generic parsers so you can plug in the sources your team already has access to.

## Tests

Run the offline unit tests from the repository root:

```bash
python -m unittest discover -s market_pricing_agent/tests
```

The sample fixtures are designed to run entirely offline.
