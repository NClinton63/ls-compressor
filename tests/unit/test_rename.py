"""Tests for pattern-based bulk rename."""

from __future__ import annotations

from pathlib import Path

import pytest

from ls_compressor.core.exceptions import (
    DestinationExistsError,
    InvalidRequestError,
)
from ls_compressor.core.rename import apply_renames, plan_renames


@pytest.fixture()
def files(tmp_path: Path) -> list[Path]:
    """Create three files in a folder named ``batch``."""
    folder = tmp_path / "batch"
    folder.mkdir()
    paths = []
    for name in ("a.png", "b.png", "c.png"):
        path = folder / name
        path.write_text(name)
        paths.append(path)
    return paths


class TestPlan:
    def test_token_expansion(self, files: list[Path]) -> None:
        items = plan_renames(files, "{parent}-{index}{ext}")
        assert [item.destination.name for item in items] == [
            "batch-1.png",
            "batch-2.png",
            "batch-3.png",
        ]

    def test_stem_and_start_index(self, files: list[Path]) -> None:
        items = plan_renames(files, "{stem}-2x{ext}", start_index=5)
        assert [item.destination.name for item in items] == [
            "a-2x.png",
            "b-2x.png",
            "c-2x.png",
        ]

    def test_unknown_token_rejected(self, files: list[Path]) -> None:
        with pytest.raises(InvalidRequestError, match="Unknown rename token"):
            plan_renames(files, "{bogus}{ext}")

    def test_path_separator_rejected(self, files: list[Path]) -> None:
        with pytest.raises(InvalidRequestError):
            plan_renames(files, "sub/{stem}{ext}")

    def test_duplicate_destinations_rejected(self, files: list[Path]) -> None:
        with pytest.raises(InvalidRequestError, match="duplicate"):
            plan_renames(files, "same{ext}")

    def test_missing_file_rejected(self, tmp_path: Path) -> None:
        with pytest.raises(InvalidRequestError, match="Not a file"):
            plan_renames([tmp_path / "nope.png"], "{stem}{ext}")


class TestApply:
    def test_renames_in_place(self, files: list[Path]) -> None:
        items = plan_renames(files, "renamed-{index}{ext}")
        apply_renames(items)
        for item, original in zip(items, ("a.png", "b.png", "c.png"), strict=True):
            assert item.destination.read_text() == original
            assert not item.source.exists()

    def test_swap_chain(self, tmp_path: Path) -> None:
        a = tmp_path / "a.txt"
        b = tmp_path / "b.txt"
        a.write_text("AAA")
        b.write_text("BBB")
        items = plan_renames([a, b], "{stem}-x{ext}")
        apply_renames(items)
        assert (tmp_path / "a-x.txt").read_text() == "AAA"
        assert (tmp_path / "b-x.txt").read_text() == "BBB"

    def test_existing_destination_rejected(self, files: list[Path]) -> None:
        blocker = files[0].parent / "renamed-1.png"
        blocker.write_text("occupied")
        items = plan_renames(files, "renamed-{index}{ext}")
        with pytest.raises(DestinationExistsError):
            apply_renames(items)
        # Original files untouched on failure before phase 1.
        assert all(path.exists() for path in files)
        assert blocker.read_text() == "occupied"

    def test_overwrite(self, files: list[Path]) -> None:
        blocker = files[0].parent / "renamed-1.png"
        blocker.write_text("occupied")
        items = plan_renames(files, "renamed-{index}{ext}")
        apply_renames(items, overwrite=True)
        assert blocker.read_text() == "a.png"

    def test_identity_rename_is_noop(self, files: list[Path]) -> None:
        items = plan_renames([files[0]], "{stem}{ext}")
        apply_renames(items)
        assert files[0].exists()
