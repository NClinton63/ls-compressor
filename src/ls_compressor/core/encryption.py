"""AES-256-GCM archive encryption and self-extracting launcher generation."""

import base64
import json
import os
import plistlib
import shutil
import struct
import sys
import tempfile
import textwrap
from pathlib import Path

from argon2.low_level import Type as Argon2Type
from argon2.low_level import hash_secret_raw
from cryptography import exceptions as crypto_exceptions
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from ls_compressor.core.algorithms import CompressionAlgorithm
from ls_compressor.core.exceptions import EncryptionError

HEADER_MAGIC = b"LSE\x01"
SALT_LEN = 16
NONCE_LEN = 12
LEGACY_ITERATIONS = 100_000
ARGON2_TIME_COST = 3
ARGON2_MEMORY_COST_KIB = 65_536
ARGON2_PARALLELISM = 2
STUB_MAGIC = b"LSEX"
STUB_FOOTER_LEN = len(STUB_MAGIC) + 8


def derive_key(password: str, salt: bytes) -> bytes:
    """Derive a legacy 32-byte PBKDF2 key for archives predating v1.2."""
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=LEGACY_ITERATIONS,
    )
    return kdf.derive(password.encode("utf-8"))


def derive_key_argon2id(
    password: str,
    salt: bytes,
    *,
    time_cost: int = ARGON2_TIME_COST,
    memory_cost: int = ARGON2_MEMORY_COST_KIB,
    parallelism: int = ARGON2_PARALLELISM,
) -> bytes:
    """Derive a 32-byte AES-256 key with Argon2id and explicit parameters."""
    return hash_secret_raw(
        password.encode("utf-8"),
        salt,
        time_cost=time_cost,
        memory_cost=memory_cost,
        parallelism=parallelism,
        hash_len=32,
        type=Argon2Type.ID,
    )


def _kdf_metadata() -> dict[str, object]:
    """Return the Argon2id parameters recorded in new archive headers."""
    return {
        "algo": "argon2id",
        "time_cost": ARGON2_TIME_COST,
        "memory_cost": ARGON2_MEMORY_COST_KIB,
        "parallelism": ARGON2_PARALLELISM,
    }


def _derive_key_from_metadata(
    password: str, salt: bytes, metadata: dict[str, object]
) -> bytes:
    """Derive a key using the KDF parameters stored in archive metadata."""
    kdf = metadata.get("kdf")
    if kdf is None:
        return derive_key(password, salt)
    if not isinstance(kdf, dict):
        raise EncryptionError("Encrypted archive key metadata is corrupt")
    algo = kdf.get("algo")
    if algo == "pbkdf2-sha256":
        kdf_obj = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=int(kdf["iterations"]),
        )
        return kdf_obj.derive(password.encode("utf-8"))
    if algo == "argon2id":
        return derive_key_argon2id(
            password,
            salt,
            time_cost=int(kdf["time_cost"]),
            memory_cost=int(kdf["memory_cost"]),
            parallelism=int(kdf["parallelism"]),
        )
    raise EncryptionError(f"Unsupported key derivation: {algo}")


def is_encrypted_file(path: Path) -> bool:
    """Return True when a file starts with the LS Compressor encryption header."""
    try:
        with path.open("rb") as stream:
            return stream.read(len(HEADER_MAGIC)) == HEADER_MAGIC
    except OSError:
        return False


def _pack_header(metadata: dict[str, object], salt: bytes, nonce: bytes) -> bytes:
    """Serialize the magic, metadata, salt and nonce into a binary header."""
    metadata_bytes = json.dumps(metadata, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )
    if len(metadata_bytes) > 65535:
        raise EncryptionError("Archive metadata is too large")
    return (
        HEADER_MAGIC
        + struct.pack(">H", len(metadata_bytes))
        + metadata_bytes
        + salt
        + nonce
    )


def _unpack_header(
    data: bytes,
) -> tuple[dict[str, object], bytes, bytes, bytes]:
    """Read metadata, salt, nonce and ciphertext from an encrypted payload."""
    if not data.startswith(HEADER_MAGIC):
        raise EncryptionError("Not a valid LS Compressor encrypted archive")
    offset = len(HEADER_MAGIC)
    if len(data) < offset + 2:
        raise EncryptionError("Encrypted archive is too short")
    metadata_len = struct.unpack_from(">H", data, offset)[0]
    offset += 2
    if len(data) < offset + metadata_len + SALT_LEN + NONCE_LEN:
        raise EncryptionError("Encrypted archive is too short")
    try:
        metadata = json.loads(data[offset : offset + metadata_len].decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise EncryptionError("Encrypted archive metadata is corrupt") from error
    offset += metadata_len
    salt = data[offset : offset + SALT_LEN]
    offset += SALT_LEN
    nonce = data[offset : offset + NONCE_LEN]
    offset += NONCE_LEN
    ciphertext = data[offset:]
    return metadata, salt, nonce, ciphertext


def _archive_extension(algorithm: CompressionAlgorithm, *, is_directory: bool) -> str:
    """Return the canonical extension for an archive so the launcher can extract it."""
    return algorithm.archive_suffix(is_directory=is_directory)


def encrypt_archive(
    archive_path: Path,
    output_path: Path,
    password: str,
    *,
    algorithm: CompressionAlgorithm | None = None,
    is_directory: bool = False,
) -> None:
    """Encrypt an existing archive file with AES-256-GCM."""
    if not password:
        raise EncryptionError("A password is required to encrypt an archive")
    plaintext = archive_path.read_bytes()
    salt = os.urandom(SALT_LEN)
    nonce = os.urandom(NONCE_LEN)
    metadata: dict[str, object] = {"kdf": _kdf_metadata()}
    key = _derive_key_from_metadata(password, salt, metadata)
    ciphertext = AESGCM(key).encrypt(nonce, plaintext, None)
    if algorithm is not None:
        metadata["ext"] = _archive_extension(algorithm, is_directory=is_directory)
    output_path.write_bytes(_pack_header(metadata, salt, nonce) + ciphertext)


def decrypt_archive(
    encrypted_path: Path,
    output_path: Path,
    password: str,
) -> None:
    """Decrypt an archive file and write the raw archive bytes to output_path."""
    if not password:
        raise EncryptionError("A password is required to decrypt an archive")
    data = encrypted_path.read_bytes()
    metadata, salt, nonce, ciphertext = _unpack_header(data)
    key = _derive_key_from_metadata(password, salt, metadata)
    try:
        plaintext = AESGCM(key).decrypt(nonce, ciphertext, None)
    except crypto_exceptions.InvalidTag as error:
        raise EncryptionError("Invalid password or corrupted archive") from error
    output_path.write_bytes(plaintext)


def read_encrypted_extension(encrypted_path: Path) -> str:
    """Return the original archive extension stored in an encrypted file's header."""
    data = encrypted_path.read_bytes()
    metadata, _, _, _ = _unpack_header(data)
    return str(metadata.get("ext", ""))


def _launcher_script() -> str:
    """Return a self-contained Python launcher template for the encrypted payload."""
    return textwrap.dedent(
        r'''
        #!/usr/bin/env python3
        """Self-extracting LS Compressor archive."""
        import base64
        import bz2
        import getpass
        import gzip
        import io
        import json
        import lzma
        import os
        import struct
        import sys
        import tarfile
        import zipfile
        from pathlib import Path

        try:
            from cryptography.hazmat.primitives import hashes
            from cryptography.hazmat.primitives.ciphers.aead import AESGCM
            from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
        except ImportError as _exc:
            sys.exit(
                "This archive requires the 'cryptography' package: "
                "pip install cryptography"
            )

        _HEADER = b"LSE\x01"
        _SALT_LEN = 16
        _NONCE_LEN = 12
        _LEGACY_ITERATIONS = 100000

        def _derive_key(password, salt, metadata):
            kdf = metadata.get("kdf")
            if kdf is None or kdf.get("algo") == "pbkdf2-sha256":
                iterations = (
                    _LEGACY_ITERATIONS if kdf is None else int(kdf["iterations"])
                )
                pbkdf = PBKDF2HMAC(
                    algorithm=hashes.SHA256(),
                    length=32,
                    salt=salt,
                    iterations=iterations,
                )
                return pbkdf.derive(password.encode("utf-8"))
            if kdf.get("algo") == "argon2id":
                try:
                    from argon2.low_level import Type, hash_secret_raw
                except ImportError:
                    sys.exit(
                        "This archive requires the 'argon2-cffi' package: "
                        "pip install argon2-cffi"
                    )
                return hash_secret_raw(
                    password.encode("utf-8"),
                    salt,
                    time_cost=int(kdf["time_cost"]),
                    memory_cost=int(kdf["memory_cost"]),
                    parallelism=int(kdf["parallelism"]),
                    hash_len=32,
                    type=Type.ID,
                )
            raise ValueError("Unsupported key derivation: " + str(kdf.get("algo")))

        def _decrypt(payload, password):
            if not payload.startswith(_HEADER):
                raise ValueError("Archive payload is missing the LS Compressor header")
            offset = len(_HEADER)
            metadata_len = struct.unpack_from(">H", payload, offset)[0]
            offset += 2
            metadata = json.loads(payload[offset:offset + metadata_len].decode("utf-8"))
            offset += metadata_len
            salt = payload[offset:offset + _SALT_LEN]
            offset += _SALT_LEN
            nonce = payload[offset:offset + _NONCE_LEN]
            offset += _NONCE_LEN
            ciphertext = payload[offset:]
            aesgcm = AESGCM(_derive_key(password, salt, metadata))
            return aesgcm.decrypt(nonce, ciphertext, None), metadata

        def _extract(plaintext, ext, dest):
            dest = Path(dest)
            dest.mkdir(parents=True, exist_ok=True)
            if ext == ".zip":
                with zipfile.ZipFile(io.BytesIO(plaintext)) as archive:
                    archive.extractall(dest)
            elif ext in (".tar.gz", ".tar.bz2", ".tar.xz"):
                mode_map = {".gz": "r:gz", ".bz2": "r:bz2", ".xz": "r:xz"}
                mode = mode_map[ext.rsplit(".")[-1]]
                with tarfile.open(fileobj=io.BytesIO(plaintext), mode=mode) as archive:
                    archive.extractall(dest)
            elif ext in (".zst", ".tar.zst"):
                try:
                    import zstandard
                except ImportError:
                    sys.exit(
                        "This archive requires the 'zstandard' package: "
                        "pip install zstandard"
                    )
                dctx = zstandard.ZstdDecompressor()
                if ext == ".tar.zst":
                    with dctx.stream_reader(io.BytesIO(plaintext)) as reader:
                        with tarfile.open(fileobj=reader, mode="r|") as archive:
                            archive.extractall(dest)
                else:
                    with dctx.stream_reader(io.BytesIO(plaintext)) as reader:
                        (dest / "output").write_bytes(reader.read())
            elif ext == ".gz":
                (dest / "output").write_bytes(gzip.decompress(plaintext))
            elif ext == ".xz":
                (dest / "output").write_bytes(lzma.decompress(plaintext))
            elif ext == ".bz2":
                (dest / "output").write_bytes(bz2.decompress(plaintext))
            else:
                (dest / ("output" + ext)).write_bytes(plaintext)

        __PAYLOAD_DATA__ = "__PAYLOAD_PLACEHOLDER__"

        def main():
            payload = base64.b64decode(__PAYLOAD_DATA__)
            if sys.stdin.isatty():
                password = getpass.getpass("Archive password: ")
            else:
                password = input("Archive password: ").strip()
            try:
                plaintext, metadata = _decrypt(payload, password)
            except Exception as exc:
                sys.exit(f"Could not decrypt archive: {exc}")
            ext = metadata.get("ext", "")
            default = os.getcwd()
            prompt = f"Extract to [{default}]: "
            try:
                dest = input(prompt).strip() or default
            except EOFError:
                dest = default
            try:
                _extract(plaintext, ext, dest)
            except Exception as exc:
                sys.exit(f"Extraction failed: {exc}")
            print(f"Extracted to {dest}")

        if __name__ == "__main__":
            main()
        '''
    ).lstrip("\n")


def _create_py_launcher(payload: bytes, output_path: Path) -> None:
    """Create a .py self-extracting launcher embedding the encrypted payload."""
    encoded = base64.b64encode(payload).decode("ascii")
    script = _launcher_script().replace("__PAYLOAD_PLACEHOLDER__", encoded, 1)
    output_path.write_text(script, encoding="utf-8")
    output_path.chmod(0o755)


def _create_app_bundle(payload: bytes, output_path: Path) -> None:
    """Create a macOS .app bundle that runs the self-extracting Python launcher."""
    if not output_path.name.endswith(".app"):
        output_path = output_path.with_name(output_path.name + ".app")
    contents = output_path / "Contents"
    macos = contents / "MacOS"
    macos.mkdir(parents=True, exist_ok=True)
    encoded = base64.b64encode(payload).decode("ascii")
    script = _launcher_script().replace("__PAYLOAD_PLACEHOLDER__", encoded, 1)
    executable = macos / "self-extract"
    executable.write_text(script, encoding="utf-8")
    executable.chmod(0o755)
    info_plist: dict[str, object] = {
        "CFBundleDisplayName": output_path.name,
        "CFBundleExecutable": "self-extract",
        "CFBundleIdentifier": "com.lscompressor.self-extract",
        "CFBundleInfoDictionaryVersion": "6.0",
        "CFBundleName": output_path.name,
        "CFBundlePackageType": "APPL",
        "CFBundleShortVersionString": "1.0.0",
        "CFBundleVersion": "1.0.0",
        "LSMinimumSystemVersion": "10.14",
    }
    (contents / "Info.plist").write_bytes(plistlib.dumps(info_plist))


def _stub_name() -> str:
    """Return the platform-specific stub binary filename."""
    return "ls-extract.exe" if sys.platform == "win32" else "ls-extract"


def _find_extract_stub() -> Path | None:
    """Locate a prebuilt standalone ``ls-extract`` stub binary, if present."""
    candidates: list[Path] = []
    env_stub = os.environ.get("LS_EXTRACT_STUB")
    if env_stub:
        candidates.append(Path(env_stub))
    bundle_dir = getattr(sys, "_MEIPASS", None)
    if bundle_dir:
        candidates.append(Path(bundle_dir) / _stub_name())
    candidates.append(Path(sys.executable).resolve().parent / _stub_name())
    repo_stub = (
        Path(__file__).resolve().parents[3] / "packaging" / "stub" / _stub_name()
    )
    candidates.append(repo_stub)
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def _create_stub_launcher(payload: bytes, output_path: Path, stub: Path) -> None:
    """Append the encrypted payload and footer to a copy of the stub binary."""
    with stub.open("rb") as src, output_path.open("wb") as dst:
        shutil.copyfileobj(src, dst, length=1024 * 1024)
        dst.write(payload)
        dst.write(STUB_MAGIC + struct.pack("<Q", len(payload)))
    if sys.platform != "win32":
        output_path.chmod(0o755)


def self_extracting_extension(*, stub_path: Path | None = None) -> str:
    """Return the output filename extension for a self-extracting archive."""
    if sys.platform == "darwin":
        return ".app"
    stub = Path(stub_path) if stub_path is not None else _find_extract_stub()
    if stub is not None and stub.is_file():
        return ".exe" if sys.platform == "win32" else ".lsex"
    return ".py"


def create_self_extracting_archive(
    archive_path: Path,
    output_path: Path,
    password: str,
    *,
    algorithm: CompressionAlgorithm | None = None,
    is_directory: bool = False,
    stub_path: Path | None = None,
) -> None:
    """Encrypt an archive and wrap it in a runnable self-extracting launcher."""
    output_path = Path(output_path)
    with tempfile.TemporaryDirectory() as temp_dir:
        encrypted = Path(temp_dir) / "payload.lse"
        encrypt_archive(
            archive_path,
            encrypted,
            password,
            algorithm=algorithm,
            is_directory=is_directory,
        )
        payload = encrypted.read_bytes()
    if sys.platform == "darwin" and output_path.suffix.lower() == ".app":
        _create_app_bundle(payload, output_path)
        return
    stub = Path(stub_path) if stub_path is not None else _find_extract_stub()
    if stub is not None and stub.is_file():
        _create_stub_launcher(payload, output_path, stub)
    else:
        _create_py_launcher(payload, output_path)


def _read_payload_from_script(script_path: Path) -> bytes:
    """Extract the base64 payload from a generated .py launcher or .app executable."""
    text = script_path.read_text(encoding="utf-8")
    marker = '__PAYLOAD_DATA__ = "'
    start = text.find(marker)
    if start == -1:
        raise EncryptionError("Cannot locate the embedded payload")
    start += len(marker)
    end = text.find('"', start)
    if end == -1:
        raise EncryptionError("Cannot locate the embedded payload")
    return base64.b64decode(text[start:end])


def _stub_payload_range(path: Path) -> tuple[int, int] | None:
    """Return (offset, length) of the stub-appended payload, or None."""
    try:
        size = path.stat().st_size
    except OSError:
        return None
    if size <= STUB_FOOTER_LEN:
        return None
    try:
        with path.open("rb") as stream:
            stream.seek(size - STUB_FOOTER_LEN)
            footer = stream.read(STUB_FOOTER_LEN)
    except OSError:
        return None
    if footer[: len(STUB_MAGIC)] != STUB_MAGIC:
        return None
    payload_len = struct.unpack("<Q", footer[len(STUB_MAGIC) :])[0]
    offset = size - STUB_FOOTER_LEN - payload_len
    if payload_len <= 0 or offset < 0:
        return None
    return offset, payload_len


def is_self_extracting_archive(path: Path) -> bool:
    """Return True if path is a .py, .app, or binary self-extracting archive."""
    if path.is_file():
        if _stub_payload_range(path) is not None:
            return True
        if path.suffix.lower() in {".py", ".lsex"}:
            try:
                head = path.read_text(encoding="utf-8")[:4096]
            except (OSError, UnicodeDecodeError):
                return False
            return _launcher_marker() in head
    if path.is_dir() and path.suffix.lower() == ".app":
        executable = path / "Contents" / "MacOS" / "self-extract"
        if executable.is_file():
            return _launcher_marker() in executable.read_text(encoding="utf-8")[:4096]
    return False


def _launcher_marker() -> str:
    """Return a stable string that identifies generated self-extracting launchers."""
    return "Self-extracting LS Compressor archive"


def extract_payload(path: Path) -> bytes:
    """Return the raw encrypted payload from a self-extracting archive."""
    if path.is_file():
        stub_range = _stub_payload_range(path)
        if stub_range is not None:
            offset, payload_len = stub_range
            with path.open("rb") as stream:
                stream.seek(offset)
                return stream.read(payload_len)
        if path.suffix.lower() in {".py", ".lsex"}:
            return _read_payload_from_script(path)
    if path.is_dir() and path.suffix.lower() == ".app":
        return _read_payload_from_script(path / "Contents" / "MacOS" / "self-extract")
    raise EncryptionError(f"Unsupported self-extracting archive: {path}")
