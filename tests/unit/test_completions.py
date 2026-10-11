"""Tests for shell completion script generation."""

import pytest

from ls_compressor.cli.completions import (
    available_shells,
    completion_script,
)
from ls_compressor.cli.main import build_parser, main


def test_available_shells() -> None:
    """All common interactive shells are supported."""
    assert set(available_shells()) == {"bash", "zsh", "fish"}


@pytest.mark.parametrize("shell", ["bash", "zsh", "fish"])
def test_script_mentions_every_subcommand(shell: str) -> None:
    """Generated scripts cover each registered subcommand."""
    script = completion_script(shell, build_parser())
    for command in ("compress", "decompress", "verify", "list", "media"):
        assert command in script


@pytest.mark.parametrize("shell", ["bash", "zsh", "fish"])
def test_script_includes_flags(shell: str) -> None:
    """Generated scripts surface real parser flags."""
    script = completion_script(shell, build_parser())
    flag = "algorithm" if shell == "fish" else "--algorithm"
    assert flag in script
    assert "password" in script


def test_script_reflects_parser_changes() -> None:
    """Scripts are generated from the parser, so new flags appear."""
    parser = build_parser()
    script = completion_script("bash", parser)
    assert "watch" in script and "--media-mode" in script


def test_rejects_unknown_shell() -> None:
    """Unknown shells raise a clear error."""
    with pytest.raises(ValueError, match="Unsupported shell"):
        completion_script("powershell", build_parser())


def test_completions_command_outputs_script(capsys) -> None:
    """The CLI subcommand prints a script for the requested shell."""
    assert main(["completions", "bash"]) == 0
    output = capsys.readouterr().out
    assert "complete" in output
    assert "compress" in output
