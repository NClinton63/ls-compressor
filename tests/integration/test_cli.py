"""Subprocess integration tests for full CLI roundtrips."""

import os
import subprocess
import sys
import time
from pathlib import Path

import pytest
from PIL import Image

PROJECT_ROOT = Path(__file__).parents[2]


def run_cli(*arguments: str) -> subprocess.CompletedProcess[str]:
    """Run the package CLI in an isolated Python subprocess."""
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(PROJECT_ROOT / "src")
    return subprocess.run(
        [sys.executable, "-m", "ls_compressor", *arguments],
        cwd=PROJECT_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.mark.parametrize("algorithm", ["zip", "xz", "gzip", "bz2"])
def test_cli_file_roundtrip(tmp_path: Path, algorithm: str) -> None:
    """Every CLI algorithm roundtrips file bytes in separate processes."""
    source = tmp_path / "résumé.txt"
    source.write_bytes(b"lossless\x00content" * 100)
    archive = tmp_path / f"archive.{algorithm}"
    restored = tmp_path / "restored"

    compressed = run_cli(
        "compress", str(source), str(archive), "--algorithm", algorithm, "--quiet"
    )
    extracted = run_cli("decompress", str(archive), str(restored), "--quiet")

    assert compressed.returncode == 0, compressed.stderr
    assert extracted.returncode == 0, extracted.stderr
    output = restored / source.name if algorithm == "zip" else restored
    assert output.read_bytes() == source.read_bytes()
    assert "Verified: yes" in compressed.stdout


def test_cli_folder_roundtrip_and_progress(tmp_path: Path) -> None:
    """The CLI recursively restores folders and emits terminal progress."""
    source = tmp_path / "folder"
    (source / "nested").mkdir(parents=True)
    (source / "nested" / "文件.txt").write_text("content", encoding="utf-8")
    archive = tmp_path / "folder.tar.gz"
    restored = tmp_path / "restored"

    compressed = run_cli("compress", str(source), str(archive), "-a", "gzip")
    extracted = run_cli("decompress", str(archive), str(restored))

    assert compressed.returncode == extracted.returncode == 0
    assert (restored / "folder" / "nested" / "文件.txt").read_text(
        encoding="utf-8"
    ) == "content"
    assert "100.00%" in compressed.stderr
    assert "100.00%" in extracted.stderr


def test_cli_corrupted_archive_has_no_traceback(tmp_path: Path) -> None:
    """Corrupt input produces a concise nonzero CLI failure."""
    archive = tmp_path / "broken.zip"
    archive.write_bytes(b"PK\x03\x04broken")

    result = run_cli("verify", str(archive))

    assert result.returncode == 1
    assert "Error: Archive is corrupted" in result.stderr
    assert "Traceback" not in result.stderr


def test_cli_global_verbose_preserves_script_output(tmp_path: Path) -> None:
    """Verbose diagnostics go to the log without changing command output."""
    source = tmp_path / "source.txt"
    source.write_text("verbose", encoding="utf-8")
    archive = tmp_path / "archive.zip"

    result = run_cli("-v", "compress", str(source), str(archive), "--quiet")

    assert result.returncode == 0
    assert "Completed: compress" in result.stdout
    assert result.stderr == ""


def test_cli_media_image_optimization(tmp_path: Path) -> None:
    """The CLI optimizes an image and prints a media-specific summary."""
    source = tmp_path / "source.png"
    image = Image.new("RGBA", (64, 64), (255, 0, 0, 128))
    image.save(source, format="PNG")
    output = tmp_path / "output.png"

    result = run_cli("media", str(source), str(output), "--quiet")

    assert result.returncode == 0, result.stderr
    assert output.exists()
    assert "Completed: media_optimize" in result.stdout
    assert "Format: PNG Image" in result.stdout
    assert "Verified:" in result.stdout


def test_cli_media_unsupported_format(tmp_path: Path) -> None:
    """The CLI reports a user-safe error for unsupported media."""
    source = tmp_path / "plain.txt"
    source.write_text("not media", encoding="utf-8")
    output = tmp_path / "output.png"

    result = run_cli("media", str(source), str(output))

    assert result.returncode == 1
    assert "Error:" in result.stderr
    assert "Traceback" not in result.stderr


def test_cli_watch_processes_new_file(tmp_path: Path) -> None:
    """The watch command detects and compresses a newly created file."""
    watch_folder = tmp_path / "watch"
    watch_folder.mkdir()
    output_folder = tmp_path / "out"
    output_folder.mkdir()
    test_file = watch_folder / "hello.txt"

    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "ls_compressor",
            "watch",
            str(watch_folder),
            "--output",
            str(output_folder),
            "--algorithm",
            "zip",
        ],
        cwd=PROJECT_ROOT,
        env={**os.environ.copy(), "PYTHONPATH": str(PROJECT_ROOT / "src")},
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        time.sleep(1.0)
        test_file.write_text("hello world", encoding="utf-8")
        for _ in range(100):
            if (output_folder / "hello.txt.zip").exists():
                break
            time.sleep(0.05)
        assert (output_folder / "hello.txt.zip").exists()
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
