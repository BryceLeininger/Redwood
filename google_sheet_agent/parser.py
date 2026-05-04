"""Worksheet parsing and normalization helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import pandas as pd

from google_sheet_agent.utils import flatten_duplicate_names, snake_case


@dataclass(slots=True)
class WorksheetQuality:
    """Heuristic quality signal for whether a worksheet looks analysis-ready."""

    score: float
    looks_structured: bool
    reason: str


@dataclass(slots=True)
class ParsedWorksheet:
    """Normalized worksheet payload ready for export."""

    dataframe: pd.DataFrame
    header_row_index: int | None
    original_headers: list[str]
    normalized_headers: list[str]
    worksheet_quality: WorksheetQuality
    skipped_top_rows: int
    blank_row_count: int


def normalize_worksheet(
    values: Sequence[Sequence[str]],
    *,
    skip_top_rows: int = 0,
    header_scan_rows: int = 10,
) -> ParsedWorksheet:
    """Normalize raw sheet values into a dataframe without coercing types."""

    matrix = _normalize_matrix(values)
    if not matrix:
        empty_frame = pd.DataFrame()
        quality = WorksheetQuality(score=0.0, looks_structured=False, reason="worksheet is empty")
        return ParsedWorksheet(
            dataframe=empty_frame,
            header_row_index=None,
            original_headers=[],
            normalized_headers=[],
            worksheet_quality=quality,
            skipped_top_rows=skip_top_rows,
            blank_row_count=0,
        )

    header_index = detect_header_row(matrix, skip_top_rows=skip_top_rows, scan_rows=header_scan_rows)
    if header_index is None:
        header_index = min(skip_top_rows, len(matrix) - 1)

    header_cells = _build_headers(matrix, header_index)
    normalized_headers = flatten_duplicate_names([snake_case(cell) for cell in header_cells])
    data_rows = _trim_trailing_blank_rows(matrix[header_index + 1 :])
    blank_row_count = sum(1 for row in data_rows if _row_non_empty_count(row) == 0)

    trimmed_data_rows = [row for row in data_rows if _row_non_empty_count(row) > 0]
    width = max(len(normalized_headers), *(len(row) for row in trimmed_data_rows), default=len(normalized_headers))

    if width > len(normalized_headers):
        extension = [f"column_{index}" for index in range(len(normalized_headers) + 1, width + 1)]
        normalized_headers = flatten_duplicate_names(normalized_headers + extension)
        header_cells = header_cells + extension

    normalized_rows = [_pad_row(row, width) for row in trimmed_data_rows]
    dataframe = pd.DataFrame(normalized_rows, columns=normalized_headers, dtype=object)
    quality = score_worksheet(matrix, header_index)

    return ParsedWorksheet(
        dataframe=dataframe,
        header_row_index=header_index,
        original_headers=header_cells,
        normalized_headers=normalized_headers,
        worksheet_quality=quality,
        skipped_top_rows=skip_top_rows,
        blank_row_count=blank_row_count,
    )


def detect_header_row(
    values: Sequence[Sequence[str]],
    *,
    skip_top_rows: int = 0,
    scan_rows: int = 10,
) -> int | None:
    """Identify the most likely header row in the first section of a worksheet."""

    matrix = _normalize_matrix(values)
    if not matrix:
        return None

    start = max(skip_top_rows, 0)
    stop = min(len(matrix), start + max(scan_rows, 1))
    best_row: int | None = None
    best_score = float("-inf")

    for row_index in range(start, stop):
        row = matrix[row_index]
        non_empty = _row_non_empty_count(row)
        if non_empty == 0:
            continue

        score = float(non_empty * 3)
        unique_non_empty = len({cell for cell in row if cell})
        score += unique_non_empty
        if unique_non_empty == non_empty:
            score += 2

        long_cells = sum(1 for cell in row if len(cell) > 40)
        score -= long_cells * 2

        numeric_like = sum(1 for cell in row if _looks_numeric_like(cell))
        if numeric_like:
            score -= numeric_like * 1.5

        next_non_empty = _row_non_empty_count(matrix[row_index + 1]) if row_index + 1 < len(matrix) else 0
        if next_non_empty >= max(non_empty - 1, 1):
            score += 3
        if next_non_empty == 0:
            score -= 2

        if _looks_note_row(row):
            score -= 8

        if score > best_score:
            best_score = score
            best_row = row_index

    return best_row


def score_worksheet(values: Sequence[Sequence[str]], header_row_index: int | None) -> WorksheetQuality:
    """Score how likely a worksheet is to be a usable finance table versus notes/junk."""

    matrix = _normalize_matrix(values)
    if not matrix:
        return WorksheetQuality(score=0.0, looks_structured=False, reason="worksheet is empty")

    non_empty_rows = [row for row in matrix if _row_non_empty_count(row) > 0]
    if not non_empty_rows:
        return WorksheetQuality(score=0.0, looks_structured=False, reason="worksheet has no usable rows")

    row_density = sum(_row_non_empty_count(row) for row in non_empty_rows) / len(non_empty_rows)
    width = max(len(row) for row in non_empty_rows)
    normalized_density = min(row_density / max(width, 1), 1.0)
    score = normalized_density * 45

    if header_row_index is not None:
        score += 15
        score += min(_row_non_empty_count(matrix[header_row_index]) * 2, 20)

    data_row_count = max(len(non_empty_rows) - 1, 0)
    if data_row_count >= 3:
        score += 10
    if data_row_count >= 10:
        score += 10

    financial_token_hits = sum(
        1
        for row in non_empty_rows[:10]
        for cell in row
        if any(token in cell.lower() for token in ("revenue", "cost", "price", "budget", "%", "$", "noi", "lot"))
    )
    score += min(financial_token_hits * 2, 20)

    looks_structured = score >= 45
    reason = "worksheet looks structured" if looks_structured else "worksheet looks more like notes or sparse content"
    return WorksheetQuality(score=round(min(score, 100.0), 1), looks_structured=looks_structured, reason=reason)


def preview_dataframe(dataframe: pd.DataFrame, rows: int = 20) -> str:
    """Return a console friendly preview string for a dataframe."""

    if dataframe.empty:
        return "<empty worksheet>"
    return dataframe.head(rows).fillna("").to_string(index=False)


def _build_headers(matrix: list[list[str]], header_index: int) -> list[str]:
    header_row = matrix[header_index]
    if header_index > 0:
        previous_row = matrix[header_index - 1]
        if _should_merge_header_rows(previous_row, header_row):
            return _merge_header_rows(previous_row, header_row)
    return [cell or f"column_{position + 1}" for position, cell in enumerate(header_row)]


def _should_merge_header_rows(previous_row: list[str], header_row: list[str]) -> bool:
    previous_non_empty = _row_non_empty_count(previous_row)
    header_non_empty = _row_non_empty_count(header_row)
    if previous_non_empty < 2 or header_non_empty < 2:
        return False
    if previous_non_empty > header_non_empty:
        return False
    if _looks_note_row(previous_row):
        return False
    return any(not cell for cell in previous_row) and any(cell for cell in header_row)


def _merge_header_rows(previous_row: list[str], header_row: list[str]) -> list[str]:
    filled_previous: list[str] = []
    current_parent = ""
    width = max(len(previous_row), len(header_row))
    for index in range(width):
        current = previous_row[index] if index < len(previous_row) else ""
        if current:
            current_parent = current
        filled_previous.append(current_parent)

    merged: list[str] = []
    for index in range(width):
        top = filled_previous[index]
        bottom = header_row[index] if index < len(header_row) else ""
        if top and bottom:
            merged.append(f"{top} {bottom}".strip())
        else:
            merged.append(top or bottom or f"column_{index + 1}")
    return merged


def _normalize_matrix(values: Sequence[Sequence[str]]) -> list[list[str]]:
    matrix: list[list[str]] = []
    width = 0
    for raw_row in values:
        row = [str(cell).strip() if cell is not None else "" for cell in raw_row]
        width = max(width, len(row))
        matrix.append(row)

    if width == 0:
        return []

    return [_pad_row(row, width) for row in matrix]


def _trim_trailing_blank_rows(rows: Sequence[Sequence[str]]) -> list[list[str]]:
    trimmed = [list(row) for row in rows]
    while trimmed and _row_non_empty_count(trimmed[-1]) == 0:
        trimmed.pop()
    return trimmed


def _pad_row(row: Sequence[str], width: int) -> list[str]:
    padded = list(row)
    if len(padded) < width:
        padded.extend([""] * (width - len(padded)))
    return padded[:width]


def _row_non_empty_count(row: Sequence[str]) -> int:
    return sum(1 for cell in row if str(cell).strip())


def _looks_note_row(row: Sequence[str]) -> bool:
    non_empty_cells = [cell for cell in row if cell]
    if len(non_empty_cells) == 1 and len(non_empty_cells[0]) > 35:
        return True
    if len(non_empty_cells) <= 2 and any(len(cell) > 50 for cell in non_empty_cells):
        return True
    return False


def _looks_numeric_like(value: str) -> bool:
    stripped = value.strip().replace(",", "")
    if not stripped:
        return False
    if stripped.endswith("%"):
        stripped = stripped[:-1]
    if stripped.startswith("$"):
        stripped = stripped[1:]
    try:
        float(stripped)
    except ValueError:
        return False
    return True
