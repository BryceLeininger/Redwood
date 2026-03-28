"""Spreadsheet and CSV extraction helpers."""

from __future__ import annotations

import csv
from pathlib import Path

from openpyxl import load_workbook


def extract_xlsx_text(path: Path) -> tuple[str, dict[str, int], list[str]]:
    """Extract cell text from each worksheet in an XLSX workbook."""

    warnings: list[str] = []
    sections: list[str] = []
    workbook = load_workbook(filename=str(path), read_only=True, data_only=True)
    sheet_count = len(workbook.sheetnames)

    try:
        for worksheet in workbook.worksheets:
            rows: list[str] = []
            for row in worksheet.iter_rows(values_only=True):
                values = [str(value).strip() for value in row if value is not None and str(value).strip()]
                if values:
                    rows.append(" | ".join(values))
            if rows:
                sections.append(f"Sheet: {worksheet.title}\n" + "\n".join(rows))
    finally:
        workbook.close()

    if not sections:
        warnings.append("No XLSX content extracted.")

    return "\n\n".join(sections), {"sheet_count": sheet_count}, warnings


def extract_csv_text(path: Path) -> tuple[str, dict[str, int], list[str]]:
    """Extract row text from a CSV file."""

    warnings: list[str] = []
    rows: list[str] = []

    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.reader(handle)
        for row in reader:
            values = [value.strip() for value in row if value.strip()]
            if values:
                rows.append(" | ".join(values))

    if not rows:
        warnings.append("No CSV content extracted.")

    return "\n".join(rows), {"row_count": len(rows)}, warnings
