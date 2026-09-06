"""Unit tests for watch-folder core models and processing."""

from pathlib import Path

import pytest

from ls_compressor.core import CompressionAlgorithm, MediaOptimizationMode
from ls_compressor.core.watch import (
    WatchEvent,
    WatchFolderConfig,
    WatchOperationType,
    derive_watch_destination,
    process_watch_event,
)


def test_watch_folder_config_defaults() -> None:
    """Default watch folder config compresses with ZIP."""
    config = WatchFolderConfig(path=Path("/in"), output_folder=Path("/out"))

    assert config.operation is WatchOperationType.COMPRESS
    assert config.enabled is True
    assert config.algorithm is CompressionAlgorithm.ZIP
    assert config.media_mode is MediaOptimizationMode.LOSSLESS
    assert config.recursive is True


def test_watch_folder_config_rejects_invalid_operation() -> None:
    with pytest.raises(ValueError):
        WatchFolderConfig(
            path=Path("/in"),
            output_folder=Path("/out"),
            operation="compress",  # type: ignore[arg-type]
        )


def test_watch_folder_config_rejects_invalid_enabled() -> None:
    with pytest.raises(ValueError):
        WatchFolderConfig(
            path=Path("/in"),
            output_folder=Path("/out"),
            enabled="yes",  # type: ignore[arg-type]
        )


def test_watch_folder_config_roundtrips_through_dict() -> None:
    config = WatchFolderConfig(
        path=Path("/in"),
        output_folder=Path("/out"),
        operation=WatchOperationType.MEDIA_OPTIMIZE,
        enabled=False,
        algorithm=CompressionAlgorithm.XZ,
        compression_level=9,
        media_mode=MediaOptimizationMode.LOSSY,
        recursive=False,
    )

    restored = WatchFolderConfig.from_dict(config.to_dict())

    assert restored == config


def test_derive_watch_destination_for_compression(tmp_path: Path) -> None:
    config = WatchFolderConfig(
        path=tmp_path / "in",
        output_folder=tmp_path / "out",
        operation=WatchOperationType.COMPRESS,
        algorithm=CompressionAlgorithm.GZIP,
    )

    destination = derive_watch_destination(tmp_path / "in" / "file.txt", config)

    assert destination == tmp_path / "out" / "file.txt.gz"


def test_derive_watch_destination_for_media_optimization(tmp_path: Path) -> None:
    config = WatchFolderConfig(
        path=tmp_path / "in",
        output_folder=tmp_path / "out",
        operation=WatchOperationType.MEDIA_OPTIMIZE,
        media_mode=MediaOptimizationMode.LOSSY,
    )

    destination = derive_watch_destination(tmp_path / "in" / "image.png", config)

    assert destination == tmp_path / "out" / "image-optimized.webp"


def test_process_watch_event_compresses_file(tmp_path: Path) -> None:
    source = tmp_path / "in" / "data.txt"
    source.parent.mkdir()
    source.write_text("hello world", encoding="utf-8")
    output_folder = tmp_path / "out"
    output_folder.mkdir()
    config = WatchFolderConfig(
        path=tmp_path / "in",
        output_folder=output_folder,
        operation=WatchOperationType.COMPRESS,
        algorithm=CompressionAlgorithm.ZIP,
    )
    event = WatchEvent(source=source, config=config, event_type="created")

    result = process_watch_event(event)

    assert result.destination == output_folder / "data.txt.zip"
    assert result.destination.exists()
