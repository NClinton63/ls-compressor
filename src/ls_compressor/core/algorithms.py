"""Definitions for supported lossless compression algorithms."""

from enum import StrEnum


class CompressionAlgorithm(StrEnum):
    """Lossless archive and stream formats supported by LS Compressor."""

    ZIP = "zip"
    XZ = "xz"
    GZIP = "gzip"
    BZ2 = "bz2"

    @property
    def display_name(self) -> str:
        """Return the human-readable name for the algorithm."""
        names = {
            self.ZIP: "ZIP (Deflate)",
            self.XZ: "LZMA (XZ)",
            self.GZIP: "GZIP",
            self.BZ2: "BZ2",
        }
        return names[self]

    def archive_suffix(self, *, is_directory: bool) -> str:
        """Return the conventional output suffix for a source type."""
        if is_directory:
            suffixes = {
                self.ZIP: ".zip",
                self.XZ: ".tar.xz",
                self.GZIP: ".tar.gz",
                self.BZ2: ".tar.bz2",
            }
        else:
            suffixes = {
                self.ZIP: ".zip",
                self.XZ: ".xz",
                self.GZIP: ".gz",
                self.BZ2: ".bz2",
            }
        return suffixes[self]
