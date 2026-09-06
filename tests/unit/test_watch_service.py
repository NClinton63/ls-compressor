"""Unit tests for the watchdog-backed hot-folder service."""

import time
from pathlib import Path

import pytest

try:
    from ls_compressor.core import CompressionAlgorithm
    from ls_compressor.core.watch import (
        WatchEvent,
        WatchFolderConfig,
        WatchOperationType,
    )
    from ls_compressor.infrastructure.watch import WatchService

    _WATCHDOG_AVAILABLE = True
except Exception:
    _WATCHDOG_AVAILABLE = False

pytestmark = pytest.mark.skipif(
    not _WATCHDOG_AVAILABLE, reason="watchdog is not installed"
)


def test_service_dispatches_created_file_event(tmp_path: Path) -> None:
    """A file created in a watched folder triggers the callback."""
    received: list[WatchEvent] = []
    service = WatchService(lambda event: received.append(event))
    config = WatchFolderConfig(
        path=tmp_path,
        output_folder=tmp_path / "out",
        operation=WatchOperationType.COMPRESS,
        algorithm=CompressionAlgorithm.ZIP,
    )
    service.add_folder(config)
    service.start()

    try:
        (tmp_path / "out").mkdir()
        test_file = tmp_path / "created.txt"
        test_file.write_text("hello", encoding="utf-8")

        for _ in range(50):
            if received:
                break
            time.sleep(0.05)

        assert len(received) >= 1
        assert received[0].source.resolve() == test_file.resolve()
        assert received[0].config == config
    finally:
        service.stop()


def test_service_ignores_hidden_and_temp_files(tmp_path: Path) -> None:
    """Hidden and temporary files are not dispatched to the callback."""
    received: list[WatchEvent] = []
    service = WatchService(lambda event: received.append(event))
    config = WatchFolderConfig(
        path=tmp_path,
        output_folder=tmp_path / "out",
        operation=WatchOperationType.COMPRESS,
        algorithm=CompressionAlgorithm.ZIP,
    )
    service.add_folder(config)
    service.start()

    try:
        (tmp_path / "out").mkdir()
        (tmp_path / ".hidden").write_text("x", encoding="utf-8")
        (tmp_path / "temp.tmp").write_text("x", encoding="utf-8")

        time.sleep(0.5)

        assert not received
    finally:
        service.stop()


def test_service_ignores_files_in_output_folder(tmp_path: Path) -> None:
    """Files written directly to the output folder do not re-trigger processing."""
    received: list[WatchEvent] = []
    service = WatchService(lambda event: received.append(event))
    output_folder = tmp_path / "out"
    output_folder.mkdir()
    config = WatchFolderConfig(
        path=tmp_path,
        output_folder=output_folder,
        operation=WatchOperationType.COMPRESS,
        algorithm=CompressionAlgorithm.ZIP,
    )
    service.add_folder(config)
    service.start()

    try:
        (output_folder / "result.txt").write_text("x", encoding="utf-8")

        time.sleep(0.5)

        assert not received
    finally:
        service.stop()


def test_update_folders_replaces_active_watches(tmp_path: Path) -> None:
    """Replacing folder configs removes stale watches and adds new ones."""
    received: list[WatchEvent] = []
    service = WatchService(lambda event: received.append(event))
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()

    service.update_folders(
        [
            WatchFolderConfig(
                path=tmp_path / "a",
                output_folder=tmp_path / "a" / "out",
                operation=WatchOperationType.COMPRESS,
                algorithm=CompressionAlgorithm.ZIP,
            ),
        ]
    )
    service.start()

    try:
        (tmp_path / "a" / "out").mkdir()
        (tmp_path / "a" / "file.txt").write_text("x", encoding="utf-8")

        for _ in range(50):
            if received:
                break
            time.sleep(0.05)

        assert len(received) == 1
        received.clear()

        service.update_folders(
            [
                WatchFolderConfig(
                    path=tmp_path / "b",
                    output_folder=tmp_path / "b" / "out",
                    operation=WatchOperationType.COMPRESS,
                    algorithm=CompressionAlgorithm.ZIP,
                ),
            ]
        )

        (tmp_path / "a" / "second.txt").write_text("x", encoding="utf-8")
        (tmp_path / "b" / "out").mkdir()
        (tmp_path / "b" / "file.txt").write_text("x", encoding="utf-8")

        for _ in range(50):
            if received:
                break
            time.sleep(0.05)

        assert len(received) == 1
        assert received[0].source.parent.name == "b"
    finally:
        service.stop()
