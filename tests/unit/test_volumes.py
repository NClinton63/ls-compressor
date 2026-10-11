"""Unit tests for multi-volume (split) archive helpers."""

import os
from pathlib import Path

import pytest

from ls_compressor.core import (
    CompressionRequest,
    DecompressionRequest,
    compress,
    decompress,
    list_archive,
)
from ls_compressor.core.exceptions import (
    CorruptedArchiveError,
    DestinationExistsError,
    InvalidRequestError,
)
from ls_compressor.core.volumes import (
    is_volume,
    join_volumes,
    parse_size,
    split_archive,
    volume_base,
    volume_parts,
)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("512", 512),
        ("512b", 512),
        ("10K", 10 * 1024),
        ("10kb", 10 * 1024),
        ("2MiB", 2 * 1024 * 1024),
        ("1.5M", int(1.5 * 1024 * 1024)),
        ("3g", 3 * 1024**3),
    ],
)
def test_parse_size_valid(text: str, expected: int) -> None:
    """Human-readable sizes parse into exact byte counts."""
    assert parse_size(text) == expected


@pytest.mark.parametrize("text", ["", "abc", "10MBs", "-5M", "0"])
def test_parse_size_invalid(text: str) -> None:
    """Malformed or non-positive sizes are rejected."""
    with pytest.raises(InvalidRequestError):
        parse_size(text)


def test_volume_name_helpers(tmp_path: Path) -> None:
    """Volume detection and base-name stripping follow the .NNN convention."""
    assert is_volume(tmp_path / "a.zip.001")
    assert is_volume(tmp_path / "a.zip.042")
    assert not is_volume(tmp_path / "a.zip")
    assert not is_volume(tmp_path / "a.01")
    assert volume_base(tmp_path / "dir" / "a.zst.007") == tmp_path / "dir" / "a.zst"


def test_split_and_join_roundtrip(tmp_path: Path) -> None:
    """Splitting then joining reproduces the original byte stream."""
    payload = bytes(range(256)) * 40
    archive = tmp_path / "src.bin"
    archive.write_bytes(payload)
    parts = split_archive(archive, tmp_path / "out.zst", 1024, overwrite=False)
    assert len(parts) == 10
    assert [p.name for p in parts] == [f"out.zst.{i:03d}" for i in range(1, 11)]
    assert not archive.exists()
    (tmp_path / "joined").mkdir()
    joined = join_volumes(parts[0], tmp_path / "joined")
    assert joined.read_bytes() == payload


def test_split_refuses_existing_volumes(tmp_path: Path) -> None:
    """Existing volumes are protected unless overwrite is requested."""
    archive = tmp_path / "src.bin"
    archive.write_bytes(b"data")
    (tmp_path / "out.zst.001").write_bytes(b"old")
    with pytest.raises(DestinationExistsError):
        split_archive(archive, tmp_path / "out.zst", 4, overwrite=False)
    parts = split_archive(archive, tmp_path / "out.zst", 4, overwrite=True)
    assert len(parts) == 1


def test_volume_parts_detects_gap(tmp_path: Path) -> None:
    """A missing middle volume is reported instead of silently truncating."""
    (tmp_path / "a.zip.001").write_bytes(b"x")
    (tmp_path / "a.zip.003").write_bytes(b"x")
    with pytest.raises(CorruptedArchiveError):
        volume_parts(tmp_path / "a.zip")


def test_split_compress_decompress_roundtrip(tmp_path: Path) -> None:
    """A split tar.zst extracts correctly from its first volume."""
    source = tmp_path / "docs"
    source.mkdir()
    payload_a = os.urandom(4096)
    payload_b = os.urandom(4096)
    (source / "a.bin").write_bytes(payload_a)
    (source / "b.bin").write_bytes(payload_b)
    destination = tmp_path / "docs.tar.zst"
    compress(
        CompressionRequest(
            source=source,
            destination=destination,
            split_size=512,
        )
    )
    assert not destination.exists()
    parts = volume_parts(destination)
    assert len(parts) > 1
    extracted = tmp_path / "out"
    decompress(DecompressionRequest(source=parts[0], destination=extracted))
    assert (extracted / "docs" / "a.bin").read_bytes() == payload_a
    assert (extracted / "docs" / "b.bin").read_bytes() == payload_b


def test_split_encrypted_roundtrip(tmp_path: Path) -> None:
    """Split volumes of an LS-encrypted archive decrypt and extract."""
    payload = os.urandom(4096)
    source = tmp_path / "secret.bin"
    source.write_bytes(payload)
    destination = tmp_path / "secret.lsenc"
    compress(
        CompressionRequest(
            source=source,
            destination=destination,
            password="pw",
            split_size=512,
        )
    )
    parts = volume_parts(destination)
    assert len(parts) > 1
    extracted = tmp_path / "out.bin"
    decompress(
        DecompressionRequest(source=parts[0], destination=extracted, password="pw")
    )
    assert extracted.read_bytes() == payload


def test_split_list_archive(tmp_path: Path) -> None:
    """Listing works against the first volume of a split archive."""
    source = tmp_path / "data.txt"
    source.write_text("payload " * 500, "utf-8")
    destination = tmp_path / "data.zip"
    from ls_compressor.core.algorithms import CompressionAlgorithm

    compress(
        CompressionRequest(
            source=source,
            destination=destination,
            algorithm=CompressionAlgorithm.ZIP,
            split_size=256,
        )
    )
    _, entries = list_archive(volume_parts(destination)[0])
    assert [entry.name for entry in entries] == ["data.txt"]


def test_split_rejects_self_extracting(tmp_path: Path) -> None:
    """Split volumes are rejected for self-extracting archives."""
    source = tmp_path / "f.txt"
    source.write_text("x", "utf-8")
    with pytest.raises(InvalidRequestError):
        compress(
            CompressionRequest(
                source=source,
                destination=tmp_path / "f.lsex",
                password="pw",
                self_extracting=True,
                split_size=100,
            )
        )
