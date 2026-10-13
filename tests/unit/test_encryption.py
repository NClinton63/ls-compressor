"""Unit tests for AES-256-GCM archive encryption and self-extracting launchers."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from ls_compressor.core import (
    EncryptionError,
    compress,
    create_self_extracting_archive,
    decompress,
    decrypt_archive,
    encrypt_archive,
    extract_payload,
    is_encrypted_file,
    is_self_extracting_archive,
)
from ls_compressor.core.algorithms import CompressionAlgorithm as Algorithm
from ls_compressor.core.encryption import (
    NONCE_LEN,
    SALT_LEN,
    derive_key,
    derive_key_argon2id,
)
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


def test_create_self_extracting_py_launcher(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A .py launcher embeds the encrypted payload and can extract itself."""
    from ls_compressor.core import encryption

    monkeypatch.setattr(encryption, "_find_extract_stub", lambda: None)
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
            algorithm=Algorithm.ZIP,
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


def test_compress_self_extracting_py(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The compressor can build a runnable .py self-extracting archive."""
    from ls_compressor.core import encryption

    monkeypatch.setattr(encryption, "_find_extract_stub", lambda: None)
    source = tmp_path / "data.txt"
    source.write_text("hello self-extracting", encoding="utf-8")
    launcher = tmp_path / "data.py"

    result = compress(
        CompressionRequest(
            source=source,
            destination=launcher,
            algorithm=Algorithm.ZIP,
            password=PASSWORD,
            self_extracting=True,
        )
    )

    assert result.destination == launcher
    assert is_self_extracting_archive(launcher)


def test_create_self_extracting_stub_binary(tmp_path: Path) -> None:
    """A stub-based archive appends the payload and footer to the binary."""
    from ls_compressor.core import encryption

    stub = tmp_path / "ls-extract"
    stub.write_bytes(b"\x7fELF fake stub binary")
    archive = _make_zip(tmp_path)
    launcher = tmp_path / "source.lsex"

    create_self_extracting_archive(
        archive,
        launcher,
        PASSWORD,
        algorithm=Algorithm.ZIP,
        is_directory=False,
        stub_path=stub,
    )

    data = launcher.read_bytes()
    assert data.startswith(b"\x7fELF fake stub binary")
    footer = data[-encryption.STUB_FOOTER_LEN :]
    assert footer[:4] == encryption.STUB_MAGIC
    assert is_self_extracting_archive(launcher)
    payload = extract_payload(launcher)
    assert payload.startswith(b"LSE\x01")

    encrypted = tmp_path / "payload.lse"
    encrypted.write_bytes(payload)
    restored = tmp_path / "restored.zip"
    decrypt_archive(encrypted, restored, PASSWORD)
    assert restored.read_bytes() == archive.read_bytes()


def test_self_extracting_extension_prefers_stub(tmp_path: Path) -> None:
    """The output extension switches to a binary suffix when a stub exists."""
    from ls_compressor.core.encryption import self_extracting_extension

    stub = tmp_path / "ls-extract"
    stub.write_bytes(b"stub")
    if sys.platform == "darwin":
        assert self_extracting_extension(stub_path=stub) == ".app"
    elif sys.platform == "win32":
        assert self_extracting_extension(stub_path=stub) == ".exe"
    else:
        assert self_extracting_extension(stub_path=stub) == ".lsex"

    missing = tmp_path / "missing-stub"
    if sys.platform == "darwin":
        assert self_extracting_extension(stub_path=missing) == ".app"
    else:
        assert self_extracting_extension(stub_path=missing) == ".py"


def test_is_self_extracting_archive_rejects_plain_binary(tmp_path: Path) -> None:
    """A binary without the LSEX footer is not treated as self-extracting."""
    blob = tmp_path / "program"
    blob.write_bytes(b"\x7fELF" + b"\x00" * 64)
    assert not is_self_extracting_archive(blob)


def test_new_archives_record_argon2id_kdf_metadata(tmp_path: Path) -> None:
    """New encrypted archives store Argon2id parameters in the header."""
    from ls_compressor.core.encryption import _unpack_header

    archive = tmp_path / "sample.zip"
    archive.write_bytes(b"payload")
    encrypted = tmp_path / "sample.lsenc"
    encrypt_archive(
        archive, encrypted, PASSWORD, algorithm=Algorithm.ZIP, is_directory=False
    )

    metadata, _, _, _ = _unpack_header(encrypted.read_bytes())

    assert metadata["kdf"]["algo"] == "argon2id"
    assert metadata["kdf"]["time_cost"] >= 1
    assert metadata["kdf"]["memory_cost"] >= 19_456


def test_legacy_pbkdf2_archive_still_decrypts(tmp_path: Path) -> None:
    """Archives written before Argon2id (no kdf metadata) remain readable."""
    import os

    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    from ls_compressor.core.encryption import (
        NONCE_LEN,
        SALT_LEN,
        _pack_header,
    )

    payload = b"legacy payload bytes"
    salt = os.urandom(SALT_LEN)
    nonce = os.urandom(NONCE_LEN)
    ciphertext = AESGCM(derive_key(PASSWORD, salt)).encrypt(nonce, payload, None)
    legacy = tmp_path / "legacy.lsenc"
    legacy.write_bytes(_pack_header({"ext": ".zip"}, salt, nonce) + ciphertext)

    restored = tmp_path / "restored.zip"
    decrypt_archive(legacy, restored, PASSWORD)

    assert restored.read_bytes() == payload


def test_pbkdf2_metadata_iterations_are_honored(tmp_path: Path) -> None:
    """Stored PBKDF2 iteration counts are used for decryption."""
    import os

    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

    from ls_compressor.core.encryption import (
        NONCE_LEN,
        SALT_LEN,
        _pack_header,
    )

    payload = b"pbkdf2 payload"
    salt = os.urandom(SALT_LEN)
    nonce = os.urandom(NONCE_LEN)
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(), length=32, salt=salt, iterations=250_000
    )
    ciphertext = AESGCM(kdf.derive(PASSWORD.encode())).encrypt(nonce, payload, None)
    archive = tmp_path / "pbkdf2.lsenc"
    archive.write_bytes(
        _pack_header(
            {"ext": ".zip", "kdf": {"algo": "pbkdf2-sha256", "iterations": 250_000}},
            salt,
            nonce,
        )
        + ciphertext
    )

    restored = tmp_path / "restored.zip"
    decrypt_archive(archive, restored, PASSWORD)

    assert restored.read_bytes() == payload


def test_aes_zip_roundtrip_requires_password(tmp_path: Path) -> None:
    """WinZip-compatible AES archives extract only with the password."""
    source = tmp_path / "report.txt"
    source.write_text("confidential", encoding="utf-8")
    archive = tmp_path / "report.zip"
    restored = tmp_path / "restored"

    from ls_compressor.core import EncryptionFormat

    compress(
        CompressionRequest(
            source=source,
            destination=archive,
            algorithm=Algorithm.ZIP,
            password=PASSWORD,
            encryption_format=EncryptionFormat.ZIP_AES,
        )
    )

    assert archive.exists()
    assert not is_encrypted_file(archive)
    with pytest.raises(EncryptionError):
        decompress(DecompressionRequest(archive, restored))
    decompress(DecompressionRequest(archive, restored, password=PASSWORD))
    assert (restored / "report.txt").read_text(encoding="utf-8") == "confidential"


def test_aes_7z_roundtrip_preserves_tree(tmp_path: Path) -> None:
    """7z AES archives roundtrip a directory tree with the password."""
    source = tmp_path / "folder"
    (source / "nested").mkdir(parents=True)
    (source / "a.txt").write_text("one", encoding="utf-8")
    (source / "nested" / "b.txt").write_text("two", encoding="utf-8")
    archive = tmp_path / "folder.7z"
    restored = tmp_path / "restored"

    from ls_compressor.core import EncryptionFormat

    compress(
        CompressionRequest(
            source=source,
            destination=archive,
            algorithm=Algorithm.SEVENZ,
            password=PASSWORD,
            encryption_format=EncryptionFormat.SEVENZ,
        )
    )

    decompress(DecompressionRequest(archive, restored, password=PASSWORD))
    assert (restored / "folder" / "a.txt").read_text() == "one"
    assert (restored / "folder" / "nested" / "b.txt").read_text() == "two"


def test_self_extracting_requires_lse_container(tmp_path: Path) -> None:
    """Self-extracting launchers are rejected for standard containers."""
    source = tmp_path / "data.txt"
    source.write_text("data", encoding="utf-8")

    from ls_compressor.core import EncryptionFormat
    from ls_compressor.core.exceptions import InvalidRequestError

    with pytest.raises(InvalidRequestError, match="LS container"):
        compress(
            CompressionRequest(
                source=source,
                destination=tmp_path / "out.py",
                algorithm=Algorithm.ZIP,
                password=PASSWORD,
                self_extracting=True,
                encryption_format=EncryptionFormat.ZIP_AES,
            )
        )


class TestWebInterop:
    """LSE containers produced by the web platform's lib/lse.ts."""

    @staticmethod
    def _web_pack(metadata: dict, salt: bytes, nonce: bytes) -> bytes:
        """Pack a header exactly as lse.ts packHeader() does."""
        meta = json.dumps(metadata, sort_keys=True, separators=(",", ":")).encode()
        return b"LSE\x01" + len(meta).to_bytes(2, "big") + meta + salt + nonce

    def test_web_argon2id_archive_decrypts(self, tmp_path: Path) -> None:
        """A web-produced argon2id LSE file decrypts on the desktop."""
        import os

        from cryptography.hazmat.primitives.ciphers.aead import AESGCM

        payload = b"web-encrypted archive bytes"
        salt = os.urandom(SALT_LEN)
        nonce = os.urandom(NONCE_LEN)
        metadata = {
            "ext": ".zip",
            "kdf": {
                "algo": "argon2id",
                "memory_cost": 65_536,
                "parallelism": 2,
                "time_cost": 3,
            },
        }
        key = derive_key_argon2id(
            PASSWORD, salt, time_cost=3, memory_cost=65_536, parallelism=2
        )
        ciphertext = AESGCM(key).encrypt(nonce, payload, None)
        archive = tmp_path / "web.lsenc"
        archive.write_bytes(self._web_pack(metadata, salt, nonce) + ciphertext)

        restored = tmp_path / "out.zip"
        decrypt_archive(archive, restored, PASSWORD)

        assert restored.read_bytes() == payload

    def test_web_pbkdf2_archive_without_iterations_decrypts(
        self, tmp_path: Path
    ) -> None:
        """Web PBKDF2 archives may omit iterations; fall back to the default."""
        import os

        from cryptography.hazmat.primitives.ciphers.aead import AESGCM

        payload = b"web pbkdf2 payload"
        salt = os.urandom(SALT_LEN)
        nonce = os.urandom(NONCE_LEN)
        metadata = {"kdf": {"algo": "pbkdf2-sha256"}}
        ciphertext = AESGCM(derive_key(PASSWORD, salt)).encrypt(nonce, payload, None)
        archive = tmp_path / "web-legacy.lsenc"
        archive.write_bytes(self._web_pack(metadata, salt, nonce) + ciphertext)

        restored = tmp_path / "out.bin"
        decrypt_archive(archive, restored, PASSWORD)

        assert restored.read_bytes() == payload

    def test_desktop_archive_matches_web_layout(self, tmp_path: Path) -> None:
        """A desktop-produced LSE header parses per the web spec."""
        plain = tmp_path / "a.zip"
        plain.write_bytes(b"PK fake archive")
        encrypted = tmp_path / "a.lsenc"
        encrypt_archive(plain, encrypted, PASSWORD)

        data = encrypted.read_bytes()
        assert data[:4] == b"LSE\x01"
        meta_len = int.from_bytes(data[4:6], "big")
        metadata = json.loads(data[6 : 6 + meta_len])
        assert metadata["kdf"]["algo"] == "argon2id"
        salt = data[6 + meta_len : 6 + meta_len + SALT_LEN]
        nonce = data[6 + meta_len + SALT_LEN : 6 + meta_len + SALT_LEN + NONCE_LEN]
        assert len(salt) == SALT_LEN and len(nonce) == NONCE_LEN
        ciphertext = data[6 + meta_len + SALT_LEN + NONCE_LEN :]
        key = derive_key_argon2id(PASSWORD, salt)
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM

        assert AESGCM(key).decrypt(nonce, ciphertext, None) == b"PK fake archive"
