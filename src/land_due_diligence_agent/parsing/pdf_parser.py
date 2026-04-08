"""PDF extraction helpers with selective OCR fallback."""

from __future__ import annotations

import os
import re
from functools import lru_cache
from pathlib import Path

from pypdf import PdfReader
from pypdf.errors import DependencyError

_LOW_TEXT_THRESHOLD = 50
_OCR_DPI = 200
_WHITESPACE_RE = re.compile(r"\s+")


def extract_pdf_text(path: Path) -> tuple[str, dict[str, int | list[int]], list[str], list[dict[str, str | int | bool | None]]]:
    """Extract page text from a PDF and apply OCR only to weak pages."""

    try:
        reader = PdfReader(str(path))
    except DependencyError as exc:  # pragma: no cover - dependency/environment issue
        raise RuntimeError(
            "PDF requires AES decryption support. Install cryptography>=3.1 to parse encrypted PDFs."
        ) from exc

    warnings: list[str] = []
    pages: list[str] = []
    chunk_records: list[dict[str, str | int | bool | None]] = []
    ocr_pages: list[int] = []
    ocr_recovered_pages: list[int] = []

    for index, page in enumerate(reader.pages, start=1):
        page_text = ""
        try:
            page_text = (page.extract_text() or "").strip()
        except Exception as exc:  # pragma: no cover - third-party parser behavior
            warnings.append(f"Page {index} text-layer extraction failed: {exc}")

        ocr_reason = _ocr_reason(page_text)
        ocr_used = False
        if ocr_reason is not None:
            ocr_pages.append(index)
            ocr_text, ocr_error = _extract_page_text_with_ocr(path, index)
            if ocr_text:
                page_text = _merge_page_text(page_text, ocr_text)
                ocr_recovered_pages.append(index)
                ocr_used = True
                warnings.append(f"Page {index} required OCR fallback ({ocr_reason}) and text was recovered.")
            elif ocr_error:
                warnings.append(f"Page {index} required OCR fallback ({ocr_reason}) but OCR did not recover text: {ocr_error}")
            else:
                warnings.append(f"Page {index} required OCR fallback ({ocr_reason}) but OCR did not recover text.")

        if not page_text:
            continue

        page_header = f"[Page {index}{' | OCR' if ocr_used else ''}]"
        pages.append(f"{page_header}\n{page_text}")
        chunk_records.append(
            {
                "chunk_id": f"page-{index:04d}",
                "page_number": index,
                "text": page_text,
                "ocr_used": ocr_used,
            }
        )

    if not pages:
        warnings.append("No PDF text extracted.")

    metadata: dict[str, int | list[int]] = {
        "page_count": len(reader.pages),
        "ocr_pages": ocr_pages,
        "ocr_recovered_pages": ocr_recovered_pages,
        "ocr_page_count": len(ocr_pages),
        "ocr_recovered_page_count": len(ocr_recovered_pages),
    }
    return "\n\n".join(pages), metadata, warnings, chunk_records


def _ocr_reason(page_text: str) -> str | None:
    condensed = _WHITESPACE_RE.sub(" ", page_text or "").strip()
    if not condensed:
        return "no text"
    if len(condensed) < _LOW_TEXT_THRESHOLD:
        return f"low text ({len(condensed)} chars)"
    return None


def _merge_page_text(text_layer_text: str, ocr_text: str) -> str:
    text_layer_text = (text_layer_text or "").strip()
    ocr_text = (ocr_text or "").strip()
    if not text_layer_text:
        return ocr_text
    if not ocr_text:
        return text_layer_text

    left = _normalize_compare_text(text_layer_text)
    right = _normalize_compare_text(ocr_text)
    if left == right:
        return ocr_text if len(ocr_text) >= len(text_layer_text) else text_layer_text
    if left and left in right:
        return ocr_text
    if right and right in left:
        return text_layer_text
    return f"{text_layer_text}\n[OCR Supplement]\n{ocr_text}"


def _normalize_compare_text(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", text.lower())


def _extract_page_text_with_ocr(path: Path, page_number: int) -> tuple[str, str | None]:
    runtime, runtime_error = _load_ocr_runtime()
    if runtime is None:
        return "", runtime_error

    pytesseract_module, convert_from_path, poppler_path = runtime
    images = []
    try:
        images = convert_from_path(
            str(path),
            dpi=_OCR_DPI,
            first_page=page_number,
            last_page=page_number,
            grayscale=True,
            fmt="png",
            thread_count=1,
            poppler_path=poppler_path,
        )
        if not images:
            return "", "pdf2image produced no page image"

        image = images[0]
        ocr_text = (pytesseract_module.image_to_string(image) or "").strip()
        if not ocr_text:
            return "", "tesseract returned no text"
        return ocr_text, None
    except Exception as exc:  # pragma: no cover - depends on local OCR toolchain
        return "", f"{type(exc).__name__}: {exc}"
    finally:
        for image in images:
            close = getattr(image, "close", None)
            if callable(close):
                close()


@lru_cache(maxsize=1)
def _load_ocr_runtime():
    try:
        import pytesseract
    except ImportError:
        return None, "pytesseract is not installed"

    try:
        from pdf2image import convert_from_path
    except ImportError:
        return None, "pdf2image is not installed"

    tesseract_cmd = os.getenv("TESSERACT_CMD", "").strip()
    if tesseract_cmd:
        pytesseract.pytesseract.tesseract_cmd = tesseract_cmd

    poppler_path = os.getenv("POPPLER_PATH", "").strip() or None
    return (pytesseract, convert_from_path, poppler_path), None
