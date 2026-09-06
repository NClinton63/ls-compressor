"""Unit tests for AES-256-GCM archive encryption and self-extracting launchers."""

import subprocess
import sys
from pathlib import Path

import pytest

from ls_compressor.core import (
    CompressionAlgorithm,
    EncryptionError,
    compress,
    create_self_extracting_archive,
    decrypt_archive,
    decompress,
    encrypt_archive,
    extract_payload,
    is_encrypted_file,
    is_self_extracting_archive,
)
from ls_compressor.core.algorithms import CompressionAlgorithm as Algorithm
from ls_compressor.core.encryption import derive_key
from ls_compressor.core.models import CompressionRequest, DecompressionRequest


PASSWORD = "correct horse battery staple"


def test_derive_key_is_256_bits() -> None:
    """PBKDF2 must produce a 32-byte AES-256 key."""
    salt = b"0123456789abcdef"
    key = derive_key(PASSWORD, salt)

    assert len(key) == 32
    assert key == derive_key(PASSWORD, salt)
    assert key != derive_key("different", salt)


def test_encrypt_archive_round_trips(tmp_path: Path) -> None:
    """An encrypted archive can be decrypted back to the exact plaintext."""
    archive = tmp_path / "sample.zip"
    archive.write_bytes(b"fake zip content that is at least a few bytes long")
    encrypted = tmp_path / "sample.zip.lsenc"

    encrypt_archive(
        archive,
        encrypted,
        PASSWORD,
        algorithm=Algorithm.ZIP,
        is_directory=False,
    )

    assert is_encrypted_file(encrypted)
    assert not is_encrypted_file(archive)
    restored = tmp_path / "restored.zip"
    decrypt_archive(encrypted, restored, PASSWORD)
    assert restored.read_bytes() == archive.read_bytes()


def test_decrypt_archive_rejects_wrong_password(tmp_path: Path) -> None:
    """A mismatched password fails authentication instead of producing garbage."""
    archive = tmp_path / "sample.zip"
    archive.write_bytes(b"sensitive contents")
    encrypted = tmp_path / "sample.zip.lsenc"
    encrypt_archive(
        archive, encrypted, PASSWORD, algorithm=Algorithm.ZIP, is_directory=False
    )

    with pytest.raises(EncryptionError):
        decrypt_archive(encrypted, tmp_path / "wrong.zip", "not the password")


def _make_zip(tmp_path: Path) -> Path:
    archive = tmp_path / "source.zip"
    import zipfile

    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("data.txt", "important data inside the archive")
    return archive


def test_create_self_extracting_py_launcher(tmp_path: Path) -> None:
    """A .py launcher embeds the encrypted payload and can extract itself."""
    archive = _make_zip(tmp_path)
    launcher = tmp_path / "source.py"

    create_self_extracting_archive(
        archive, launcher, PASSWORD, algorithm=Algorithm.ZIP, is_directory=False
    )

    assert launcher.is_file()
    assert is_self_extracting_archive(launcher)
    assert extract_payload(launcher).startswith(b"LSE\x01")

    extract_to = tmp_path / "extracted"
    result = subprocess.run(
        [sys.executable, str(launcher)],
        input=f"{PASSWORD}\n{extract_to}\n",
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "Extracted to" in result.stdout


@pytest.mark.skipif(sys.platform != "darwin", reason=".app bundles are macOS only")
def test_create_self_extracting_app_bundle(tmp_path: Path) -> None:
    """A .app bundle wraps the encrypted payload and is identified correctly."""
    archive = _make_zip(tmp_path)
    bundle = tmp_path / "Source.app"

    create_self_extracting_archive(
        archive, bundle, PASSWORD, algorithm=Algorithm.ZIP, is_directory=False
    )

    assert bundle.is_dir()
    assert is_self_extracting_archive(bundle)
    assert (bundle / "Contents" / "MacOS" / "self-extract").is_file()
    assert (bundle / "Contents" / "Info.plist").is_file()
    assert extract_payload(bundle).startswith(b"LSE\x01")


def test_compress_with_password_and_decompress(tmp_path: Path) -> None:
    """The compressor can create and restore an encrypted archive."""
    source = tmp_path / "data.txt"
    source.write_text("hello encrypted world", encoding="utf-8")
    encrypted = tmp_path / "data.txt.zip.lsenc"

    result = compress(
        CompressionRequest(
            source=source,
            destination=encrypted,
            password=PASSWORD,
        )
    )

    assert result.destination == encrypted
    assert is_encrypted_file(encrypted)
    assert encrypted.stat().st_size > 0

    out = tmp_path / "out"
    decomp = decompress(
        DecompressionRequest(source=encrypted, destination=out, password=PASSWORD)
    )
    assert decomp.files_processed == 1
    assert (out / "data.txt").read_text(encoding="utf-8") == "hello encrypted world"


def test_compress_self_extracting_py(tmp_path: Path) -> None:
    """The compressor can build a runnable .py self-extracting archive."""
    source = tmp_path / "data.txt"
    source.write_text("hello self-extracting", encoding="utf-8")
    launcher = tmp_path / "data.py"

    result = compress(
        CompressionRequest(
            source=source,
            destination=launcher,
            password=PASSWORD,
            self_extracting=True,
        )
    )

    assert result.destination == launcher
    assert is_self_extracting_archive(launcher)
