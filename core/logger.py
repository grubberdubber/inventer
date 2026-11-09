"""System event logging and telemetry handlers.

All operational anomalies are persisted to the rotating log configured in the
system configuration file (``var/log/inventer.log`` by default).
"""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

_LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)-22s | %(message)s"
_LOGGER_NAME = "inventer"


def configure_logging(log_path: Path, level: int = logging.INFO) -> logging.Logger:
    """Configure the shared ``inventer`` logger.

    Args:
        log_path: Destination path for the rotating log file.
        level: Root logging level for the application namespace.

    Returns:
        The configured ``inventer`` logger instance.
    """
    log_path.parent.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger(_LOGGER_NAME)
    logger.setLevel(level)
    logger.propagate = False

    has_file_handler = any(
        isinstance(handler, RotatingFileHandler) for handler in logger.handlers
    )
    if not has_file_handler:
        handler = RotatingFileHandler(
            log_path,
            maxBytes=1_000_000,
            backupCount=3,
            encoding="utf-8",
        )
        handler.setFormatter(logging.Formatter(_LOG_FORMAT))
        logger.addHandler(handler)

    return logger
