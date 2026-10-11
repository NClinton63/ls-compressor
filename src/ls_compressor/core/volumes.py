"""Fixed-size multi-volume (split) archive helpers."""

import re
from pathlib import Path

from ls_compressor.core.exceptions import (
    CorruptedArchiveError,
    DestinationExistsError,
    InvalidRequestError,
)
from ls_compressor.core.filesystem import CHUNK_SIZE

_VOLUME_SUFFIX = re.compile(r"\.(\d{3,})$")
_SIZE_PATTERN = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*([kmgt]?i?b?)\s*$", re.IGNORECASE)
_SIZE_MULTIPLIERS = {
    "": 1,
    "b": 1,
    "k": 1024,
    "kb": 1024,
    "kib": 1024,
    "m": 1024**2,
    "mb": 1024**2,
    "mib": 1024**2,
    "g": 1024**3,
    "gb": 1024**3,
    "gib": 1024**3,
    "t": 1024**4,
    "tb": 1024**4,
    "tib": 1024**4,
}


def parse_size(text: str) -> int:
    """Parse a human size like ``100M`` or ``1.5GiB`` into bytes."""
    match = _SIZE_PATTERN.match(text)
    if match is None:
        raise InvalidRequestError(f"Invalid size: {text!r} (use e.g. 500K, 100M, 2G)")
    value = float(match.group(1))
    multiplier = _SIZE_MULTIPLIERS[match.group(2).lower()]
    size = int(value * multiplier)
    if size < 1:
        raise InvalidRequestError("Split size must be at least 1 byte")
    return size


def is_volume(path: Path) -> bool:
    """Return True when the path looks like a numbered archive volume."""
    return _VOLUME_SUFFIX.search(path.name) is not None


def volume_base(path: Path) -> Path:
    """Strip the numeric volume suffix, returning the archive base name."""
    match = _VOLUME_SUFFIX.search(path.name)
    if match is None:
        return path
    return path.with_name(path.name[: match.start()])


def _volume_name(base: Path, index: int) -> Path:
    """Return the sibling path for one numbered volume."""
    return base.with_name(f"{base.name}.{index:03d}")


def volume_parts(base: Path) -> list[Path]:
    """Return the ordered, contiguous volume paths starting at ``.001``.

    Raises when volumes are missing from the sequence.
    """
    indices = sorted(
        int(match.group(1))
        for sibling in base.parent.iterdir()
        if sibling.is_file()
        and (match := _VOLUME_SUFFIX.search(sibling.name))
        and sibling.name[: match.start()] == base.name
    )
    if not indices:
        raise CorruptedArchiveError(f"No volumes found for {base}")
    expected = list(range(1, len(indices) + 1))
    if indices != expected:
        raise CorruptedArchiveError(
            f"Missing volumes for {base}: expected .001-"
            f".{indices[-1]:03d}, found {len(indices)} parts"
        )
    return [_volume_name(base, index) for index in indices]


def split_archive(
    archive: Path,
    destination: Path,
    volume_size: int,
    *,
    overwrite: bool,
) -> list[Path]:
    """Split a finished archive into ``destination.NNN`` volumes.

    The source archive is removed after a successful split. Stale volumes
    left over from a previous split are cleaned up when overwriting.
    """
    if volume_size < 1:
        raise InvalidRequestError("Split size must be at least 1 byte")
    base = destination
    first = _volume_name(base, 1)
    existing = {
        sibling
        for sibling in base.parent.iterdir()
        if sibling.is_file()
        and (match := _VOLUME_SUFFIX.search(sibling.name))
        and sibling.name[: match.start()] == base.name
    }
    if existing and not overwrite:
        raise DestinationExistsError(f"Destination exists: {first}")
    parts: list[Path] = []
    try:
        with archive.open("rb") as source:
            index = 0
            while True:
                index += 1
                part = _volume_name(base, index)
                written = 0
                with part.open("wb") as output:
                    while written < volume_size:
                        chunk = source.read(min(CHUNK_SIZE, volume_size - written))
                        if not chunk:
                            break
                        output.write(chunk)
                        written += len(chunk)
                if written == 0:
                    part.unlink()
                    break
                parts.append(part)
                if written < volume_size:
                    break
    except BaseException:
        for part in parts:
            part.unlink(missing_ok=True)
        raise
    for stale in existing - set(parts):
        stale.unlink()
    archive.unlink()
    return parts


def join_volumes(source: Path, work_dir: Path) -> Path:
    """Concatenate the volume set containing ``source`` into ``work_dir``.

    Returns the path of the joined archive inside ``work_dir``; callers own
    the directory lifetime.
    """
    base = volume_base(source)
    parts = volume_parts(base)
    joined = work_dir / base.name
    with joined.open("wb") as output:
        for part in parts:
            with part.open("rb") as volume:
                while chunk := volume.read(CHUNK_SIZE):
                    output.write(chunk)
    return joined
