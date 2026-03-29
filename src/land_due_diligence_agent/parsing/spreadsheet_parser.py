"""Spreadsheet and CSV extraction helpers."""

from __future__ import annotations

import csv
from pathlib import Path

from openpyxl import load_workbook


def extract_xlsx_text(path: Path) -> tuple[str, dict[str, int], list[str], list[dict[str, str | int | None]]]:
    """Extract cell text from each worksheet in an XLSX workbook."""

    warnings: list[str] = []
    sections: list[str] = []
    chunk_records: list[dict[str, str | int | None]] = []
    workbook = load_workbook(filename=str(path), read_only=True, data_only=True)
    sheet_count = len(workbook.sheetnames)

    try:
        for sheet_index, worksheet in enumerate(workbook.worksheets, start=1):
            rows: list[str] = []
            for row_index, row in enumerate(worksheet.iter_rows(values_only=True), start=1):
                values = [str(value).strip() for value in row if value is not None and str(value).strip()]
                if values:
                    row_text = " | ".join(values)
                    rows.append(row_text)
                    chunk_records.append(
                        {
                            "chunk_id": f"sheet-{sheet_index:02d}-row-{row_index:04d}",
                            "page_number": None,
                            "text": f"Sheet: {worksheet.title}\n{row_text}",
                        }
                    )
            if rows:
                sections.append(f"Sheet: {worksheet.title}\n" + "\n".join(rows))
    finally:
        workbook.close()

    if not sections:
        warnings.append("No XLSX content extracted.")

    return "\n\n".join(sections), {"sheet_count": sheet_count}, warnings, chunk_records


def extract_csv_text(path: Path) -> tuple[str, dict[str, int], list[str], list[dict[str, str | int | None]]]:
    """Extract row text from a CSV file."""

    warnings: list[str] = []
    rows: list[str] = []
    chunk_records: list[dict[str, str | int | None]] = []

    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.reader(handle)
        for row_index, row in enumerate(reader, start=1):
            values = [value.strip() for value in row if value.strip()]
            if values:
                row_text = " | ".join(values)
                rows.append(row_text)
                chunk_records.append(
                    {
                        "chunk_id": f"row-{row_index:04d}",
                        "page_number": None,
                        "text": row_text,
                    }
                )

    if not rows:
        warnings.append("No CSV content extracted.")

    return "\n".join(rows), {"row_count": len(rows)}, warnings, chunk_records
