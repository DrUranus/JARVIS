"""Central logging configuration."""
from __future__ import annotations

import logging
from pathlib import Path

_FORMAT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"


def setup_logging(level: str = "INFO", log_dir: str | Path | None = None, console: bool = False) -> logging.Logger:
    """Configure the 'jarvis' logger. Idempotent: replaces previous handlers.

    Console logging is off by default so the CLI dialog stays clean.
    """
    logger = logging.getLogger("jarvis")
    logger.setLevel(getattr(logging, str(level).upper(), logging.INFO))
    logger.propagate = False
    for h in list(logger.handlers):
        logger.removeHandler(h)
        h.close()
    fmt = logging.Formatter(_FORMAT)
    if console:
        h = logging.StreamHandler()
        h.setFormatter(fmt)
        logger.addHandler(h)
    if log_dir is not None:
        try:
            p = Path(log_dir)
            p.mkdir(parents=True, exist_ok=True)
            fh = logging.FileHandler(p / "jarvis.log", encoding="utf-8")
            fh.setFormatter(fmt)
            logger.addHandler(fh)
        except OSError:
            pass  # logging must never crash the assistant
    if not logger.handlers:
        logger.addHandler(logging.NullHandler())
    return logger
