"""Pattern-based bulk rename for exported assets.

Mirrors the web edition's bulk-rename handoff tool: renames a batch of
files in place using a ``{stem}``/``{ext}``/``{index}``/``{parent}``
pattern so exported sets can be named like ``hero-2x.webp``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from ls_compressor.core.exceptions import (
    DestinationExistsError,
    InvalidRequestError,
)

_TOKENS = ("stem", "ext", "index", "parent")


@dataclass(frozen=True)
class RenameItem:
    """A single planned rename."""

    source: Path
    destination: Path


def _validate_pattern(pattern: str) -> None:
    """Reject patterns containing unknown tokens or path separators."""
    if "/" in pattern or "\\" in pattern:
        raise InvalidRequestError("Rename pattern must be a filename, not a path")
    for match in re.finditer(r"\{([^{}]*)\}", pattern):
        token = match.group(1)
        if token not in _TOKENS:
            raise InvalidRequestError(
                f"Unknown rename token {{{token}}}; "
                f"available: {', '.join('{' + t + '}' for t in _TOKENS)}"
            )


def plan_renames(
    sources: list[Path],
    pattern: str,
    start_index: int = 1,
) -> list[RenameItem]:
    """Compute the rename plan without touching the filesystem.

    Args:
        sources: Files to rename, processed in the given order.
        pattern: Filename template. Tokens: ``{stem}`` (name without
            extension), ``{ext}`` (extension including the dot), ``{index}``
            (sequence number), ``{parent}`` (parent directory name).
        start_index: First sequence number for ``{index}``.

    Returns:
        Ordered rename items.

    Raises:
        InvalidRequestError: Unknown token, path separators, duplicate
            sources, or a pattern producing identical/duplicated names.
    """
    _validate_pattern(pattern)
    seen_sources: set[Path] = set()
    items: list[RenameItem] = []
    for offset, source in enumerate(sources):
        if source in seen_sources:
            raise InvalidRequestError(f"Duplicate source: {source}")
        seen_sources.add(source)
        if not source.is_file():
            raise InvalidRequestError(f"Not a file: {source}")
        rendered = (
            pattern.replace("{stem}", source.stem)
            .replace("{ext}", source.suffix)
            .replace("{index}", str(start_index + offset))
            .replace("{parent}", source.parent.name)
        )
        if not rendered or rendered in {".", ".."}:
            raise InvalidRequestError(
                f"Pattern produced an invalid filename for {source}"
            )
        items.append(RenameItem(source, source.with_name(rendered)))
    destinations = [item.destination for item in items]
    if len(set(destinations)) != len(destinations):
        raise InvalidRequestError(
            "Rename pattern produces duplicate destinations; "
            "add {index} to make names unique"
        )
    return items


def apply_renames(
    items: list[RenameItem],
    overwrite: bool = False,
) -> list[RenameItem]:
    """Execute a rename plan.

    Two-phase so a source that is another item's destination is handled
    safely; refuses to clobber existing files unless ``overwrite`` is set.
    """
    pending = {item.source for item in items}
    for item in items:
        if (
            item.destination.exists()
            and item.destination not in pending
            and not overwrite
            and item.destination != item.source
        ):
            raise DestinationExistsError(item.destination)
    staged: list[tuple[Path, Path, Path]] = []
    try:
        for index, item in enumerate(items):
            if item.destination == item.source:
                continue
            temp = item.source.with_name(f".lsc-rename-{index}-{item.source.name}")
            item.source.rename(temp)
            staged.append((temp, item.source, item.destination))
        for temp, _source, destination in staged:
            if destination.exists():
                if not overwrite:
                    raise DestinationExistsError(destination)
                destination.unlink()
            temp.rename(destination)
    except OSError:
        for temp, source, _destination in staged:
            if temp.exists() and not source.exists():
                temp.rename(source)
        raise
    return items
