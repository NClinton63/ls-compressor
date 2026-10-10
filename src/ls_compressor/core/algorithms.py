"""Definitions for supported lossless compression algorithms."""

from enum import StrEnum


class CompressionAlgorithm(StrEnum):
    """Lossless archive and stream formats supported by LS Compressor."""

    ZSTD = "zstd"
    ZIP = "zip"
    XZ = "xz"
    GZIP = "gzip"
    BZ2 = "bz2"
    SEVENZ = "7z"
    RAR = "rar"

    @property
    def display_name(self) -> str:
        """Return the human-readable name for the algorithm."""
        names = {
            self.ZSTD: "Zstandard",
            self.ZIP: "ZIP (Deflate)",
            self.XZ: "LZMA (XZ)",
            self.GZIP: "GZIP",
            self.BZ2: "BZ2",
            self.SEVENZ: "7-Zip",
            self.RAR: "RAR",
        }
        return names[self]

    @property
    def can_compress(self) -> bool:
        """Return True when the algorithm supports creating archives."""
        return self not in {CompressionAlgorithm.SEVENZ, CompressionAlgorithm.RAR}

    def archive_suffix(self, *, is_directory: bool) -> str:
        """Return the conventional output suffix for a source type."""
        if is_directory:
            suffixes = {
                self.ZSTD: ".tar.zst",
                self.ZIP: ".zip",
                self.XZ: ".tar.xz",
                self.GZIP: ".tar.gz",
                self.BZ2: ".tar.bz2",
                self.SEVENZ: ".7z",
                self.RAR: ".rar",
            }
        else:
            suffixes = {
                self.ZSTD: ".zst",
                self.ZIP: ".zip",
                self.XZ: ".xz",
                self.GZIP: ".gz",
                self.BZ2: ".bz2",
                self.SEVENZ: ".7z",
                self.RAR: ".rar",
            }
        return suffixes[self]
