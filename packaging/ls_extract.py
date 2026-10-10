"""Standalone self-extracting stub binary entry point.

The stub reads an encrypted payload appended to its own executable and
extracts it without requiring a Python installation on the target machine.
Layout of a self-extracting file:

    [stub binary bytes][LSE-encrypted payload][b"LSEX"][8-byte LE payload len]
"""

import getpass
import struct
import sys
import tempfile
from pathlib import Path

FOOTER_MAGIC = b"LSEX"
FOOTER_LEN = len(FOOTER_MAGIC) + 8


def _own_file() -> Path:
    """Return the file that contains the appended payload."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable)
    return Path(__file__)


def read_appended_payload(path: Path) -> bytes:
    """Return the payload appended to a self-extracting stub file."""
    data = path.read_bytes()
    if len(data) < FOOTER_LEN or data[-FOOTER_LEN:-8] != FOOTER_MAGIC:
        sys.exit("This executable does not contain an embedded archive")
    payload_len = struct.unpack("<Q", data[-8:])[0]
    if payload_len <= 0 or payload_len > len(data) - FOOTER_LEN:
        sys.exit("Embedded archive metadata is corrupt")
    return data[-FOOTER_LEN - payload_len : -FOOTER_LEN]


def main() -> int:
    """Decrypt and extract the embedded payload to a destination folder."""
    from ls_compressor.core.compressor import decompress
    from ls_compressor.core.encryption import decrypt_archive
    from ls_compressor.core.models import DecompressionRequest

    payload = read_appended_payload(_own_file())
    if sys.stdin.isatty():
        password = getpass.getpass("Archive password: ")
    else:
        password = input("Archive password: ").strip()
    with tempfile.TemporaryDirectory() as temp_dir:
        encrypted = Path(temp_dir) / "payload.lse"
        encrypted.write_bytes(payload)
        archive = Path(temp_dir) / "archive"
        try:
            decrypt_archive(encrypted, archive, password)
        except Exception as error:
            sys.exit(f"Could not decrypt archive: {error}")
        if len(sys.argv) > 1:
            destination = Path(sys.argv[1])
        else:
            destination = Path.cwd() / "extracted"
        try:
            decompress(DecompressionRequest(archive, destination))
        except Exception as error:
            sys.exit(f"Extraction failed: {error}")
    print(f"Extracted to {destination}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
