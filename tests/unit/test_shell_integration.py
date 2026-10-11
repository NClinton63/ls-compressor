"""Unit tests for per-user OS shell integration."""

import plistlib
import sys
from pathlib import Path

import pytest

from ls_compressor.core.exceptions import UnsupportedFormatError
from ls_compressor.infrastructure import shell_integration
from ls_compressor.infrastructure.shell_integration import (
    install,
    status,
    uninstall,
)

_EXE = "/opt/ls-compressor/bin/ls-compressor"


def test_darwin_install_creates_workflows(tmp_path: Path, monkeypatch) -> None:
    """macOS install writes two valid Quick Action workflow bundles."""
    monkeypatch.setattr(shell_integration, "_executable_command", lambda: _EXE)
    created = install(platform="darwin", home=tmp_path)
    services = tmp_path / "Library" / "Services"
    assert len(created) == 2
    compress = services / "Compress with LS Compressor.workflow"
    extract = services / "Extract with LS Compressor.workflow"
    assert str(compress) in created and str(extract) in created
    workflow = plistlib.loads((compress / "Contents" / "document.wflow").read_bytes())
    command = workflow["actions"][0]["action"]["ActionParameters"]["COMMAND_STRING"]
    assert _EXE in command
    assert "compress" in command
    meta = workflow["workflowMetaData"]
    assert meta["workflowTypeIdentifier"] == "com.apple.Automator.servicesMenu"
    entries = status(platform="darwin", home=tmp_path)
    assert all(entry.installed for entry in entries)


def test_darwin_uninstall_removes_workflows(tmp_path: Path, monkeypatch) -> None:
    """Uninstall deletes the workflow bundles and reports none installed."""
    monkeypatch.setattr(shell_integration, "_executable_command", lambda: _EXE)
    install(platform="darwin", home=tmp_path)
    removed = uninstall(platform="darwin", home=tmp_path)
    assert len(removed) == 2
    assert not (tmp_path / "Library" / "Services").exists() or not list(
        (tmp_path / "Library" / "Services").iterdir()
    )
    assert all(
        not entry.installed for entry in status(platform="darwin", home=tmp_path)
    )


def test_linux_install_creates_desktop_and_scripts(tmp_path: Path, monkeypatch) -> None:
    """Linux install writes the KDE service menu and Nautilus scripts."""
    monkeypatch.setattr(shell_integration, "_executable_command", lambda: _EXE)
    created = install(platform="linux", home=tmp_path)
    assert len(created) == 3
    desktop = tmp_path / ".local/share/kio/servicemenus/ls-compressor.desktop"
    assert desktop.exists()
    content = desktop.read_text("utf-8")
    assert _EXE in content and "compress" in content
    script = tmp_path / ".local/share/nautilus/scripts/Compress with LS Compressor"
    assert script.exists()
    assert script.stat().st_mode & 0o100  # user-executable
    removed = uninstall(platform="linux", home=tmp_path)
    assert len(removed) == 3
    assert all(not entry.installed for entry in status(platform="linux", home=tmp_path))


def test_windows_registry_spec_is_per_user() -> None:
    """The Windows registry spec stays inside HKCU context-menu paths."""
    keys = shell_integration._windows_registry_keys(_EXE)
    assert keys
    for key_path in keys:
        assert key_path.startswith("Software\\Classes\\")
        assert "\\shell\\" in key_path
    commands = [
        value
        for key_path, values in keys.items()
        for name, value in values.items()
        if key_path.endswith("command") and name == ""
    ]
    assert all(_EXE in command for command in commands)
    assert any("compress" in command for command in commands)
    assert any("decompress" in command for command in commands)


@pytest.mark.skipif(sys.platform != "win32", reason="winreg is Windows-only")
def test_windows_install_roundtrip() -> None:
    """Install writes then removes HKCU keys on Windows."""
    created = install(platform="win32")
    assert created
    entries = status(platform="win32")
    assert all(entry.installed for entry in entries)
    removed = uninstall(platform="win32")
    assert removed
    assert all(not entry.installed for entry in status(platform="win32"))


def test_unsupported_platform_raises(tmp_path: Path) -> None:
    """Unknown platforms raise instead of silently doing nothing."""
    with pytest.raises(UnsupportedFormatError):
        install(platform="amigaos", home=tmp_path)
    with pytest.raises(UnsupportedFormatError):
        status(platform="amigaos", home=tmp_path)
