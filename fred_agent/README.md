# FRED Agent

A deterministic command-line agent for collecting economic time-series observations from the [FRED API](https://fred.stlouisfed.org/).

## Prerequisites

- Python 3.10+
- A FRED API key stored in the `FRED_API_KEY` environment variable.

### Set the API key (one time)

On Windows PowerShell:

```powershell
setx FRED_API_KEY "<your-api-key>"
```

After setting the variable, restart your terminal before running the agent.

## Install dependencies

From the project root:

```bash
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
```

## Run the agent

```bash
python agent.py
```

The agent will prompt for:

1. FRED series ID (required)
2. Start date in `YYYY-MM-DD` format (optional)
3. End date in `YYYY-MM-DD` format (optional)
4. Whether to append the results to the master dataset (`outputs/master/fred_master.csv`).

## Example session

```
Enter the FRED series ID: GDP
Enter the start date (YYYY-MM-DD, optional): 2010-01-01
Enter the end date (YYYY-MM-DD, optional): 2023-12-31
Append to master dataset? [y/N]: y
```

Sample summary output:

```
FRED Agent Summary
-------------------
Rows fetched     : 57
Date range       : 2010-01-01 to 2023-10-01
Raw CSV path     : outputs/raw/GDP_20260101_101500.csv
Master CSV path  : outputs/master/fred_master.csv
```

## Outputs

- `outputs/raw/` – timestamped CSV extracts for each run.
- `outputs/master/fred_master.csv` – consolidated dataset (created or updated when you opt in).

## Adding future tools

1. Create a new module inside `tools/` that exposes pure functions (no user input or logging).
2. Import the new tool in `agent.py` and orchestrate it within the main flow.
3. Log the tool invocation and outcomes using `tools.logger.get_logger`.
4. Cover persistence needs in `tools/storage_tool.py` or a new dedicated tool with deterministic behavior.

## Notes

- All HTTP requests include retry handling with exponential delays.
- Missing values are converted to `NaN` for compatibility with downstream analytics.
