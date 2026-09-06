"""Application logging configuration using the Python standard library."""

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from ls_compressor.infrastructure.paths import log_file_path

LOGGER_NAME = "ls_compressor"
_HANDLER_MARKER = "ls_compressor_file_handler"


def configure_logging(
    verbosity: int = 0,
    log_path: Path | None = None,
    *,
    max_bytes: int = 1_048_576,
    backup_count: int = 3,
) -> logging.Logger:
    """Configure and return the application logger without duplicate handlers."""
    if verbosity < 0:
        raise ValueError("verbosity cannot be negative")
    if max_bytes <= 0:
        raise ValueError("max_bytes must be positive")
    if backup_count < 0:
        raise ValueError("backup_count cannot be negative")

    logger = logging.getLogger(LOGGER_NAME)
    level = logging.DEBUG if verbosity else logging.INFO
    logger.setLevel(level)
    logger.propagate = False
    destination = log_path if log_path is not None else log_file_path()

    matching_handler: logging.Handler | None = None
    for handler in list(logger.handlers):
        if getattr(handler, "name", None) != _HANDLER_MARKER:
            continue
        if (
            isinstance(handler, RotatingFileHandler)
            and Path(handler.baseFilename) == destination.absolute()
        ):
            matching_handler = handler
        else:
            logger.removeHandler(handler)
            handler.close()

    if matching_handler is None:
        try:
            destination.parent.mkdir(parents=True, exist_ok=True)
            matching_handler = RotatingFileHandler(
                destination,
                maxBytes=max_bytes,
                backupCount=backup_count,
                encoding="utf-8",
            )
            matching_handler.name = _HANDLER_MARKER
            matching_handler.setFormatter(
                logging.Formatter(
                    "%(asctime)s %(levelname)s %(name)s %(message)s",
                    datefmt="%Y-%m-%dT%H:%M:%S",
                )
            )
            logger.addHandler(matching_handler)
        except OSError:
            matching_handler = logging.NullHandler()
            matching_handler.name = _HANDLER_MARKER
            logger.addHandler(matching_handler)

    matching_handler.setLevel(level)
    return logger
