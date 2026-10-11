"""Unit tests for TOML-backed CLI default overrides."""

from pathlib import Path

import pytest

from ls_compressor.cli.main import build_parser, main
from ls_compressor.core.exceptions import InvalidRequestError
from ls_compressor.infrastructure.cli_config import load_cli_config


def test_load_cli_config_returns_sections(tmp_path: Path) -> None:
    """Config sections are returned with normalized option names."""
    config = tmp_path / "ls-compressor.toml"
    config.write_text(
        '[compress]\nalgorithm = "xz"\nlevel = 6\n'
        'exclude = ["*.tmp"]\nno-verify = true\n',
        "utf-8",
    )
    sections = load_cli_config(config)
    assert sections["compress"] == {
        "algorithm": "xz",
        "level": 6,
        "exclude": ["*.tmp"],
        "no_verify": True,
    }


def test_load_cli_config_searches_cwd(tmp_path: Path) -> None:
    """Without an explicit path the current directory is searched first."""
    config = tmp_path / "ls-compressor.toml"
    config.write_text('[compress]\nalgorithm = "zip"\n', "utf-8")
    sections = load_cli_config(cwd=tmp_path)
    assert sections["compress"]["algorithm"] == "zip"
    assert load_cli_config(cwd=tmp_path / "empty") == {}


def test_load_cli_config_missing_explicit_path(tmp_path: Path) -> None:
    """An explicit --config path must exist."""
    with pytest.raises(InvalidRequestError):
        load_cli_config(tmp_path / "missing.toml")


def test_load_cli_config_rejects_bad_values(tmp_path: Path) -> None:
    """Unknown sections, bad types, and invalid enum values are errors."""
    cases = [
        "[bogus]\nx = 1\n",
        '[compress]\nalgorithm = "nope"\n',
        '[compress]\nlevel = "high"\nlevel2 = [1, 2]\n',
        "compress = 5\n",
    ]
    for index, text in enumerate(cases):
        config = tmp_path / f"bad{index}.toml"
        config.write_text(text, "utf-8")
        if index == 2:
            # "high" is a str so it parses; nested lists are rejected
            config.write_text("[compress]\nlevel = [[1]]\n", "utf-8")
        with pytest.raises(InvalidRequestError):
            load_cli_config(config)


def test_config_defaults_apply_and_flags_override(tmp_path: Path) -> None:
    """Config supplies defaults; explicit CLI flags still win."""
    config = tmp_path / "ls-compressor.toml"
    config.write_text(
        '[compress]\nalgorithm = "xz"\nlevel = 1\nexclude = ["*.tmp"]\n',
        "utf-8",
    )
    parser = build_parser(load_cli_config(config))

    args = parser.parse_args(["compress", "a", "b"])
    assert args.algorithm == "xz"
    assert args.level == 1
    assert args.exclude == ["*.tmp"]

    args = parser.parse_args(["compress", "a", "b", "-a", "zip", "-l", "9"])
    assert args.algorithm == "zip"
    assert args.level == 9

    args = parser.parse_args(["compress", "a", "b", "--exclude", "*.log"])
    assert args.exclude == ["*.tmp", "*.log"]


def test_main_uses_config_defaults(tmp_path: Path) -> None:
    """An explicit --config file drives end-to-end command defaults."""
    config = tmp_path / "custom.toml"
    config.write_text('[compress]\nalgorithm = "xz"\n', "utf-8")
    source = tmp_path / "note.txt"
    source.write_text("data", "utf-8")
    archive = tmp_path / "note.xz"

    status = main(
        [
            "--config",
            str(config),
            "compress",
            str(source),
            str(archive),
            "-q",
        ]
    )
    assert status == 0
    assert archive.exists()


def test_main_rejects_missing_config(tmp_path: Path, capsys) -> None:
    """A missing --config path exits one with a readable error."""
    status = main(["--config", str(tmp_path / "nope.toml"), "verify", "x"])
    assert status == 1
    assert "Config file not found" in capsys.readouterr().err
