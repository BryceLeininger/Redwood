"""Logging configuration helpers."""

from __future__ import annotations

import logging
from pathlib import Path


def configure_logging(level: str, log_file: Path | None = None) -> logging.Logger:
    """Configure console and optional file logging for the CLI."""

    logger = logging.getLogger("land_due_diligence_agent")
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    logger.handlers.clear()
    logger.propagate = False

    formatter = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s")

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    if log_file is not None:
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    return logger
