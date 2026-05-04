from __future__ import annotations

import unittest

from google_sheet_agent.parser import detect_header_row, normalize_worksheet, score_worksheet
from google_sheet_agent.utils import extract_sheet_id, flatten_duplicate_names, snake_case


class GoogleSheetAgentParserTests(unittest.TestCase):
    def test_extract_sheet_id_from_url(self) -> None:
        sheet_id = extract_sheet_id(sheet_url="https://docs.google.com/spreadsheets/d/abc123DEF456/edit#gid=0")
        self.assertEqual(sheet_id, "abc123DEF456")

    def test_extract_sheet_id_rejects_invalid_url(self) -> None:
        with self.assertRaises(ValueError):
            extract_sheet_id(sheet_url="https://example.com/not-a-sheet")

    def test_snake_case_and_duplicate_flattening(self) -> None:
        self.assertEqual(snake_case("Gross Revenue %"), "gross_revenue_percent")
        self.assertEqual(
            flatten_duplicate_names(["lot", "lot", "lot"]),
            ["lot", "lot_2", "lot_3"],
        )

    def test_detect_header_row_skips_note_rows(self) -> None:
        values = [
            ["Internal planning draft only - numbers subject to change", "", ""],
            ["", "", ""],
            ["Lot", "Base Price", "Premium %"],
            ["101", "$425,000", "5%"],
        ]
        self.assertEqual(detect_header_row(values), 2)

    def test_normalize_worksheet_merges_parent_headers(self) -> None:
        values = [
            ["", "Sales", "Sales", "Costs", "Costs"],
            ["Lot", "Base", "Premium", "Hard", "Soft"],
            ["101", "$400,000", "$25,000", "$180,000", "$20,000"],
        ]
        parsed = normalize_worksheet(values)
        self.assertEqual(
            parsed.normalized_headers,
            ["sales_lot", "sales_base", "sales_premium", "costs_hard", "costs_soft"],
        )
        self.assertEqual(parsed.dataframe.iloc[0]["sales_base"], "$400,000")

    def test_score_worksheet_flags_notes_as_low_quality(self) -> None:
        values = [
            ["This tab contains meeting notes and comments about assumptions.", "", ""],
            ["Need to confirm impact fees with city.", "", ""],
        ]
        quality = score_worksheet(values, header_row_index=None)
        self.assertFalse(quality.looks_structured)


if __name__ == "__main__":
    unittest.main()