"""Command-line FRED agent for retrieving and storing economic time series data."""
from __future__ import annotations

import sys
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

import pandas as pd

from config import ConfigError, load_config
from tools.fred_tool import FredAPIError, fetch_observations
from tools.logger import get_logger
from tools.storage_tool import save_raw_csv, update_master_dataset

_DATE_FORMAT = "%Y-%m-%d"


@dataclass(frozen=True)
class UserRequest:
    series_id: str
    start_date: Optional[str]
    end_date: Optional[str]
    append_to_master: bool


def _prompt_user_inputs() -> UserRequest:
    series_id = input("Enter the FRED series ID: ").strip()
    if not series_id:
        raise ValueError("Series ID cannot be empty.")

    start_date_raw = input("Enter the start date (YYYY-MM-DD, optional): ").strip()
    end_date_raw = input("Enter the end date (YYYY-MM-DD, optional): ").strip()

    start_date = _parse_date_or_none(start_date_raw)
    end_date = _parse_date_or_none(end_date_raw)

    if start_date and end_date and start_date > end_date:
        raise ValueError("Start date must be earlier than or equal to end date.")

    append_choice = input("Append to master dataset? [y/N]: ").strip().lower()
    append_to_master = append_choice == "y"

    return UserRequest(
        series_id=series_id,
        start_date=start_date,
        end_date=end_date,
        append_to_master=append_to_master,
    )


def _parse_date_or_none(value: str) -> Optional[str]:
    if not value:
        return None
    try:
        parsed = datetime.strptime(value, _DATE_FORMAT).date()
    except ValueError as error:
        raise ValueError(f"Invalid date '{value}'. Expected format YYYY-MM-DD.") from error
    return parsed.isoformat()


def _summarize_results(
    dataframe: pd.DataFrame,
    raw_path: str,
    master_path: Optional[str],
) -> None:
    row_count = len(dataframe)
    if row_count and dataframe["date"].notna().any():
        valid_dates = dataframe["date"].dropna()
        start = valid_dates.min()
        end = valid_dates.max()
        date_range = f"{start.date().isoformat()} to {end.date().isoformat()}"
    elif row_count:
        date_range = "Observations returned without valid dates"
    else:
        date_range = "No observations returned"

    print("\nFRED Agent Summary")
    print("-------------------")
    print(f"Rows fetched     : {row_count}")
    print(f"Date range       : {date_range}")
    print(f"Raw CSV path     : {raw_path}")
    if master_path:
        print(f"Master CSV path  : {master_path}")
    else:
        print("Master CSV path  : Skipped")


def main() -> None:
    logger = get_logger()

    try:
        config = load_config()
    except ConfigError as error:
        logger.error("Configuration error: %s", error)
        raise SystemExit(1) from error

    try:
        request = _prompt_user_inputs()
    except ValueError as error:
        logger.error("Input validation failed: %s", error)
        raise SystemExit(1) from error

    logger.info(
        "Fetching series '%s' with start=%s end=%s",
        request.series_id,
        request.start_date or "<not set>",
        request.end_date or "<not set>",
    )

    try:
        dataframe = fetch_observations(
            series_id=request.series_id,
            api_key=config.api_key,
            start_date=request.start_date,
            end_date=request.end_date,
        )
    except FredAPIError as error:
        logger.error("FRED API request failed: %s", error)
        raise SystemExit(1) from error

    logger.info("Fetched %d observations", len(dataframe))

    raw_path = save_raw_csv(dataframe, request.series_id, config.raw_output_dir)
    logger.info("Saved raw CSV to %s", raw_path)

    master_path: Optional[str] = None
    if request.append_to_master:
        master_file, total_rows = update_master_dataset(dataframe, config.master_output_path)
        master_path = str(master_file)
        logger.info("Updated master dataset (%d total rows)", total_rows)
    else:
        logger.info("Master dataset update skipped by user")

    _summarize_results(dataframe, str(raw_path), master_path)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
