"""Tests for selective PDF OCR fallback."""

from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from land_due_diligence_agent.parsing.pdf_parser import extract_pdf_text


class _FakePage:
    def __init__(self, text: str) -> None:
        self._text = text

    def extract_text(self) -> str:
        return self._text


class _FakeReader:
    def __init__(self, texts: list[str]) -> None:
        self.pages = [_FakePage(text) for text in texts]


class PDFParserTests(unittest.TestCase):
    @patch("land_due_diligence_agent.parsing.pdf_parser._extract_page_text_with_ocr")
    @patch("land_due_diligence_agent.parsing.pdf_parser.PdfReader")
    def test_uses_ocr_only_for_empty_or_low_text_pages(self, reader_mock, ocr_mock) -> None:
        reader_mock.return_value = _FakeReader(
            [
                "This page has enough machine-readable text to skip OCR.",
                "",
                "Short note",
            ]
        )
        ocr_mock.side_effect = [
            ("Recovered OCR text for page two.", None),
            ("Recovered OCR text for page three.", None),
        ]

        raw_text, metadata, warnings, chunk_records = extract_pdf_text(Path("demo.pdf"))

        self.assertIn("[Page 1]", raw_text)
        self.assertIn("[Page 2 | OCR]", raw_text)
        self.assertIn("[Page 3 | OCR]", raw_text)
        self.assertEqual(metadata["ocr_pages"], [2, 3])
        self.assertEqual(metadata["ocr_recovered_pages"], [2, 3])
        self.assertTrue(any("Page 2 required OCR fallback" in warning for warning in warnings))
        self.assertTrue(any(record["page_number"] == 2 and record["ocr_used"] for record in chunk_records))
        self.assertEqual(ocr_mock.call_count, 2)

    @patch("land_due_diligence_agent.parsing.pdf_parser._extract_page_text_with_ocr")
    @patch("land_due_diligence_agent.parsing.pdf_parser.PdfReader")
    def test_records_warning_when_ocr_does_not_recover_text(self, reader_mock, ocr_mock) -> None:
        reader_mock.return_value = _FakeReader([""])
        ocr_mock.return_value = ("", "pytesseract is not installed")

        raw_text, metadata, warnings, chunk_records = extract_pdf_text(Path("demo.pdf"))

        self.assertEqual(raw_text, "")
        self.assertEqual(metadata["ocr_pages"], [1])
        self.assertEqual(metadata["ocr_recovered_pages"], [])
        self.assertIn("pytesseract is not installed", warnings[0])
        self.assertEqual(chunk_records, [])


if __name__ == "__main__":
    unittest.main()
