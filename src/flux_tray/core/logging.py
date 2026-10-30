"""Small rotating application log."""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path


def configure_logging(directory: Path, level: int = logging.INFO) -> logging.Logger:
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("flux_tray")
    logger.setLevel(level)
    if not logger.handlers:
        handler = RotatingFileHandler(
            directory / "flux-tray.log", maxBytes=1_000_000, backupCount=3,
            encoding="utf-8",
        )
        handler.setFormatter(logging.Formatter(
            "%(asctime)s %(levelname)s %(name)s: %(message)s"
        ))
        logger.addHandler(handler)
    return logger
