"""Logging to console (rich) and a rotating file."""

from __future__ import annotations

import logging
from pathlib import Path

from rich.logging import RichHandler

_CONFIGURED = False


def setup_logging(log_dir: str | Path = "output", level: int = logging.INFO) -> logging.Logger:
    """Configure root logging once: pretty console + plain file."""
    global _CONFIGURED
    logger = logging.getLogger("lead_qualifier")
    if _CONFIGURED:
        return logger

    logger.setLevel(logging.DEBUG)
    logger.propagate = False

    # Console — rich, human-friendly.
    console = RichHandler(rich_tracebacks=True, show_path=False, markup=True)
    console.setLevel(level)
    console.setFormatter(logging.Formatter("%(message)s", datefmt="[%X]"))
    logger.addHandler(console)

    # File — full detail.
    Path(log_dir).mkdir(parents=True, exist_ok=True)
    fh = logging.FileHandler(Path(log_dir) / "run.log", encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s")
    )
    logger.addHandler(fh)

    _CONFIGURED = True
    return logger


def get_logger(name: str = "lead_qualifier") -> logging.Logger:
    return logging.getLogger(name if name.startswith("lead_qualifier") else f"lead_qualifier.{name}")
