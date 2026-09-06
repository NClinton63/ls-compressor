"""Unit tests for application file logging."""

import logging
from collections.abc import Iterator
from logging.handlers import RotatingFileHandler
from pathlib import Path

import pytest

from ls_compressor.infrastructure.logging import LOGGER_NAME, configure_logging


@pytest.fixture(autouse=True)
def reset_application_logger() -> Iterator[None]:
    """Close application handlers after each isolated logging test."""
    logger = logging.getLogger(LOGGER_NAME)
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()
    yield
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()


def test_configure_logging_creates_utf8_rotating_file(tmp_path: Path) -> None:
    """Configuration creates a bounded UTF-8 application log lazily."""
    path = tmp_path / "logs" / "application.log"

    logger = configure_logging(log_path=path, max_bytes=128, backup_count=2)
    logger.info("Opération réussie")
    handler = logger.handlers[0]
    handler.flush()

    assert isinstance(handler, RotatingFileHandler)
    assert handler.encoding.lower().replace("-", "") == "utf8"
    assert handler.maxBytes == 128
    assert handler.backupCount == 2
    assert "Opération réussie" in path.read_text(encoding="utf-8")


def test_reconfiguration_is_idempotent_and_adjusts_verbosity(tmp_path: Path) -> None:
    """Repeated setup reuses one handler while updating its level."""
    path = tmp_path / "application.log"

    first = configure_logging(log_path=path)
    second = configure_logging(verbosity=1, log_path=path)

    assert first is second
    assert len(second.handlers) == 1
    assert second.level == logging.DEBUG
    assert second.handlers[0].level == logging.DEBUG


def test_reconfiguration_replaces_an_old_destination(tmp_path: Path) -> None:
    """Changing destinations closes the managed handler without duplication."""
    first_path = tmp_path / "first.log"
    second_path = tmp_path / "second.log"
    logger = configure_logging(log_path=first_path)

    configure_logging(log_path=second_path)
    logger.info("new destination")
    logger.handlers[0].flush()

    assert len(logger.handlers) == 1
    assert "new destination" not in first_path.read_text(encoding="utf-8")
    assert "new destination" in second_path.read_text(encoding="utf-8")


def test_unwritable_log_location_falls_back_without_raising(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A log filesystem failure does not prevent application startup."""

    def fail_mkdir(*args: object, **kwargs: object) -> None:
        raise OSError("read only")

    monkeypatch.setattr(Path, "mkdir", fail_mkdir)

    logger = configure_logging(log_path=tmp_path / "logs" / "application.log")
    logger.info("safe")

    assert len(logger.handlers) == 1
    assert isinstance(logger.handlers[0], logging.NullHandler)


@pytest.mark.parametrize(
    ("arguments", "message"),
    [
        ({"verbosity": -1}, "verbosity"),
        ({"max_bytes": 0}, "max_bytes"),
        ({"backup_count": -1}, "backup_count"),
    ],
)
def test_invalid_logging_options_are_rejected(
    arguments: dict[str, int], message: str
) -> None:
    """Invalid rotation and verbosity values fail clearly."""
    with pytest.raises(ValueError, match=message):
        configure_logging(**arguments)
