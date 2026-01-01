"""Command-line FRED agent for retrieving and storing economic time series data."""
from __future__ import annotations

import sys
from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional

import pandas as pd

from config import ConfigError, load_config
from tools.fred_tool import fetch_observations
from tools.logger import get_logger
from tools.series_resolver import SeriesCandidate, resolve
from tools.storage_tool import save_raw_csv, update_master_dataset

_DATE_FORMAT = "%Y-%m-%d"


@dataclass(frozen=True)
class UserRequest:
    series_id: str
    series_title: Optional[str]
    start_date: Optional[str]
    end_date: Optional[str]
    append_to_master: bool


def _prompt_date(prompt: str, default: Optional[str]) -> Optional[str]:
    if default:
        message = f"{prompt} [{default}]: "
    else:
        message = f"{prompt} (YYYY-MM-DD, optional): "
    value = input(message).strip()
    if not value:
        return default
    return _parse_date_or_none(value)


def _select_series_candidate(candidates: List[SeriesCandidate]) -> SeriesCandidate:
    if not candidates:
        raise ValueError("No series candidates were returned.")
    if len(candidates) == 1:
        return candidates[0]

    print("\nMultiple series found:")
    for idx, candidate in enumerate(candidates, start=1):
        frequency = f" [{candidate.frequency}]" if candidate.frequency else ""
        units = f" ({candidate.units})" if candidate.units else ""
        print(f"{idx}) {candidate.series_id} — {candidate.title}{frequency}{units}")

    selection_raw = input(f"Choose 1-{len(candidates)}: ").strip()
    if not selection_raw:
        raise ValueError("Selection is required.")
    try:
        selection = int(selection_raw)
    except ValueError as error:
        raise ValueError("Selection must be a number.") from error
    if not (1 <= selection <= len(candidates)):
        raise ValueError("Selection out of range.")

    return candidates[selection - 1]


def _gather_user_request(api_key: str, logger) -> UserRequest:
    query_text = input("What do you want from FRED? ").strip()
    if not query_text:
        raise ValueError("Query cannot be empty.")

    resolution = resolve(query_text, api_key)
    candidate = _select_series_candidate(resolution.candidates)

    print(f"\nSelected series: {candidate.series_id} — {candidate.title}")
    logger.info("Resolved query '%s' to '%s' (%s)", resolution.cleaned_query or query_text, candidate.series_id, candidate.title)

    start_date = resolution.start_date
    end_date = resolution.end_date

    if start_date:
        print(f"Detected start date: {start_date}")
        start_date = _prompt_date("Enter start date (press Enter to keep detected value)", start_date)
    else:
        start_date = _prompt_date("Enter the start date", None)

    if end_date:
        print(f"Detected end date: {end_date}")
        end_date = _prompt_date("Enter end date (press Enter to keep detected value)", end_date)
    else:
        end_date = _prompt_date("Enter the end date", None)

    if start_date and end_date and start_date > end_date:
        raise ValueError("Start date must be earlier than or equal to end date.")

    append_choice = input("Append to master dataset? [y/N]: ").strip().lower()
    append_to_master = append_choice == "y"

    return UserRequest(
        series_id=candidate.series_id,
        series_title=candidate.title or None,
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

    while True:
        try:
            request = _gather_user_request(config.api_key, logger)

            logger.info(
                "Fetching series '%s' (%s) with start=%s end=%s",
                request.series_id,
                request.series_title or "<no title>",
                request.start_date or "<not set>",
                request.end_date or "<not set>",
            )

            dataframe = fetch_observations(
                series_id=request.series_id,
                api_key=config.api_key,
                start_date=request.start_date,
                end_date=request.end_date,
            )
            logger.info("Fetched %d observations", len(dataframe))

            raw_path = save_raw_csv(dataframe, request.series_id, config.raw_output_dir)
            logger.info("Saved raw CSV to %s", raw_path)

            master_path: Optional[str] = None
            if request.append_to_master:
                master_file, total_rows = update_master_dataset(
                    dataframe,
                    config.master_output_path,
                )
                master_path = str(master_file)
                logger.info("Updated master dataset (%d total rows)", total_rows)
            else:
                logger.info("Master dataset update skipped by user")

            _summarize_results(dataframe, str(raw_path), master_path)
            logger.info("Run completed successfully.")
            break

        except ValueError as error:
            logger.error(f"Input validation failed: {error}")
            print("\n⚠️  Invalid input. Please try again.\n")

        except Exception:
            logger.exception("Unexpected error")
            print("\n❌ Unexpected error. Restarting agent.\n")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
