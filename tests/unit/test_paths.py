"""Unit tests for platform-specific infrastructure paths."""

from pathlib import Path
from types import SimpleNamespace

import pytest

from ls_compressor.infrastructure import paths


@pytest.fixture
def platform_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    """Provide deterministic platform directory values."""
    resolved = SimpleNamespace(
        user_config_dir=str(tmp_path / "config"),
        user_data_dir=str(tmp_path / "data"),
        user_log_dir=str(tmp_path / "logs"),
    )
    monkeypatch.setattr(paths, "_platform_dirs", lambda: resolved)
    return resolved


def test_application_constants_are_stable() -> None:
    """Platform directory identity uses public application constants."""
    assert paths.APP_NAME == "LS Compressor"
    assert paths.APP_AUTHOR == "LS Compressor"


def test_directories_are_not_created_by_lookup(
    platform_paths: SimpleNamespace,
) -> None:
    """Looking up platform paths has no filesystem side effects."""
    assert paths.app_config_dir() == Path(platform_paths.user_config_dir)
    assert paths.app_data_dir() == Path(platform_paths.user_data_dir)
    assert paths.app_log_dir() == Path(platform_paths.user_log_dir)
    assert not Path(platform_paths.user_config_dir).exists()
    assert not Path(platform_paths.user_data_dir).exists()
    assert not Path(platform_paths.user_log_dir).exists()


def test_directories_are_created_only_when_requested(
    platform_paths: SimpleNamespace,
) -> None:
    """Callers can lazily create each platform directory."""
    assert paths.app_config_dir(create=True).is_dir()
    assert paths.app_data_dir(create=True).is_dir()
    assert paths.app_log_dir(create=True).is_dir()


def test_file_paths_can_create_their_parent(platform_paths: SimpleNamespace) -> None:
    """File path helpers optionally prepare their parent directory."""
    config_path = paths.config_file_path(create_parent=True)
    log_path = paths.log_file_path(create_parent=True)

    assert config_path == Path(platform_paths.user_config_dir) / "settings.json"
    assert log_path == Path(platform_paths.user_log_dir) / "ls-compressor.log"
    assert config_path.parent.is_dir()
    assert log_path.parent.is_dir()
