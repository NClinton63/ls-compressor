"""Unit tests for command-line argument handling and output."""

import importlib
import json
from pathlib import Path
from unittest.mock import Mock

import pytest
from PIL import Image

from ls_compressor.cli.main import main

cli_main = importlib.import_module("ls_compressor.cli.main")


def test_missing_source_returns_user_safe_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Expected domain failures return status one without a traceback."""
    status = main(
        ["compress", str(tmp_path / "missing"), str(tmp_path / "archive.zip")]
    )
    captured = capsys.readouterr()

    assert status == 1
    assert "Error: Source does not exist" in captured.err
    assert "Traceback" not in captured.err


def test_quiet_compression_prints_summary_without_progress(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Quiet mode remains useful for scripts while retaining final metrics."""
    source = tmp_path / "source.txt"
    source.write_text("compress me", encoding="utf-8")
    archive = tmp_path / "archive.zip"

    status = main(["compress", str(source), str(archive), "--quiet"])
    captured = capsys.readouterr()

    assert status == 0
    assert "Completed: compress" in captured.out
    assert "Ratio:" in captured.out
    assert captured.err == ""


def test_verify_command_reports_detected_algorithm(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Verify reports a readable format name for valid archives."""
    source = tmp_path / "source"
    source.write_bytes(b"verified")
    archive = tmp_path / "archive.xz"
    assert main(["compress", str(source), str(archive), "-a", "xz", "-q"]) == 0
    capsys.readouterr()

    status = main(["verify", str(archive)])
    captured = capsys.readouterr()

    assert status == 0
    assert "Archive is valid (LZMA (XZ))" in captured.out


def test_global_verbose_configures_logging_without_changing_output(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Global verbosity adjusts diagnostics while preserving direct output."""
    source = tmp_path / "source.txt"
    source.write_text("content", encoding="utf-8")
    archive = tmp_path / "archive.zip"
    configure = Mock()
    monkeypatch.setattr(cli_main, "configure_logging", configure)

    status = main(["-vv", "compress", str(source), str(archive), "--quiet"])
    captured = capsys.readouterr()

    assert status == 0
    configure.assert_called_once_with(2)
    assert "Completed: compress" in captured.out
    assert captured.err == ""


def test_cli_logs_failure_without_sensitive_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Failed operations record lifecycle metadata but omit user paths."""
    logger = Mock()
    monkeypatch.setattr(cli_main, "_LOGGER", logger)
    monkeypatch.setattr(cli_main, "configure_logging", Mock())
    missing = tmp_path / "private-name.txt"

    assert main(["verify", str(missing)]) == 1

    failure_call = logger.error.call_args
    assert failure_call.args[0] == "Operation failed command=%s error_type=%s"
    assert str(missing) not in " ".join(str(value) for value in failure_call.args)
    logger.info.assert_called_with("Operation started command=%s", "verify")


def test_media_command_optimizes_image_and_prints_summary(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The media subcommand produces a dedicated result summary."""
    source = tmp_path / "source.png"
    image = Image.new("RGBA", (64, 64), (255, 0, 0, 128))
    image.save(source, format="PNG")
    output = tmp_path / "output.png"

    status = main(["media", str(source), str(output), "--quiet"])
    captured = capsys.readouterr()

    assert status == 0
    assert output.exists()
    assert "Completed: media_optimize" in captured.out
    assert "Format: PNG Image" in captured.out
    assert "Savings:" in captured.out
    assert captured.err == ""


def test_json_compress_emits_parseable_result(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """--json prints the operation result as a JSON document on stdout."""
    source = tmp_path / "source.txt"
    source.write_text("compress me", encoding="utf-8")
    archive = tmp_path / "archive.zip"

    status = main(["compress", str(source), str(archive), "-a", "zip", "--json"])
    captured = capsys.readouterr()

    assert status == 0
    payload = json.loads(captured.out)
    assert payload["operation"] == "compress"
    assert payload["algorithm"] == "zip"
    assert payload["source"] == str(source)
    assert payload["destination"] == str(archive)
    assert payload["files_processed"] == 1
    assert payload["integrity_verified"] is True
    assert payload["source_size"] > 0


def test_json_verify_and_list_emit_structured_output(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """--json verify and list report algorithm and entries as JSON."""
    source = tmp_path / "source.txt"
    source.write_text("content", encoding="utf-8")
    archive = tmp_path / "archive.zip"
    assert main(["compress", str(source), str(archive), "-a", "zip", "-q"]) == 0
    capsys.readouterr()

    assert main(["verify", str(archive), "--json"]) == 0
    verify = json.loads(capsys.readouterr().out)
    assert verify == {
        "operation": "verify",
        "source": str(archive),
        "algorithm": "zip",
        "valid": True,
    }

    assert main(["list", str(archive), "--json"]) == 0
    listing = json.loads(capsys.readouterr().out)
    assert listing["algorithm"] == "zip"
    assert listing["file_count"] == 1
    assert listing["entries"][0]["name"] == "source.txt"
    assert listing["entries"][0]["is_dir"] is False


def test_json_error_emits_json_on_stderr(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Failures in --json mode produce a JSON error object and exit one."""
    status = main(
        [
            "compress",
            str(tmp_path / "missing"),
            str(tmp_path / "out.zip"),
            "--json",
        ]
    )
    captured = capsys.readouterr()

    assert status == 1
    payload = json.loads(captured.err)
    assert payload["operation"] == "compress"
    assert payload["error_type"]
    assert "Source does not exist" in payload["error"]
    assert captured.out == ""


def test_media_command_reports_unsupported_format(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Unsupported media formats surface a user-safe error."""
    source = tmp_path / "plain.txt"
    source.write_text("not media", encoding="utf-8")
    output = tmp_path / "output.png"

    status = main(["media", str(source), str(output)])
    captured = capsys.readouterr()

    assert status == 1
    assert "Error:" in captured.err
    assert "Traceback" not in captured.err
