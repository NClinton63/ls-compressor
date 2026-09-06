"""Shared fixtures for Qt GUI tests."""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest

try:
    from PySide6.QtWidgets import QApplication

    _PYSIDE6_AVAILABLE = True
except Exception:
    _PYSIDE6_AVAILABLE = False


@pytest.fixture(scope="session")
def qapp() -> Iterator[QApplication]:
    """Provide a singleton headless QApplication for the GUI test session."""
    if not _PYSIDE6_AVAILABLE:
        pytest.skip("PySide6 is not installed")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    application = QApplication.instance()
    if application is None:
        application = QApplication([])
    yield application
