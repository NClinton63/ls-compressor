# LS Compressor — Public API

`ls_compressor.core` is a GUI-independent Python API for compression,
extraction, encryption, verification, archive inspection, media optimization,
and volume splitting. Everything the CLI and GUI do is built on this layer, so
the same requests produce the same results everywhere.

```python
from pathlib import Path
from ls_compressor.core import (
    CompressionAlgorithm,
    CompressionRequest,
    DecompressionRequest,
    compress,
    decompress,
)
```

- All request/result models are immutable dataclasses in `core/models.py`.
- Paths are `pathlib.Path` objects (or `str` where annotated).
- Errors are raised as `CompressionError` subclasses (see
  [Error handling](#error-handling)) — no partial output is left behind;
  results are placed atomically via a temporary sibling path.

## Compressing

```python
request = CompressionRequest(
    source=Path("photos"),
    destination=Path("photos.tar.zst"),
    algorithm=CompressionAlgorithm.ZSTD,   # default
    compression_level=3,                   # None = per-algorithm default
)
result = compress(request)
print(result.compression_ratio, result.files_processed)
```

`CompressionRequest` fields:

| Field | Type | Default | Notes |
|-------|------|---------|-------|
| `source` | `Path` | — | File or directory |
| `destination` | `Path` | — | Output path |
| `algorithm` | `CompressionAlgorithm` | `ZSTD` | See table below |
| `compression_level` | `int \| None` | `None` | 0–9, per-algorithm default when omitted |
| `overwrite` | `bool` | `False` | Refuse to clobber existing output |
| `verify` | `bool` | `True` | Verify archive against sources |
| `password` | `str \| None` | `None` | Enables encryption (`encryption_format`) |
| `self_extracting` | `bool` | `False` | Standalone extractor output |
| `encryption_format` | `EncryptionFormat` | `LSE` | `LSE`, `ZIP` (AES-ZIP), `SEVENZ` (AES-7z) |
| `extra_sources` | `tuple[Path, ...]` | `()` | Additional files/folders in one archive |
| `exclude` | `tuple[str, ...]` | `()` | gitignore-lite patterns; `.lsignore` files apply automatically |
| `split_size` | `int \| None` | `None` | Max bytes per volume (`parse_size` helper) |

Algorithms (`CompressionAlgorithm`): `ZSTD` (default), `ZIP`, `GZIP`, `BZ2`,
`XZ` are write-capable; `SEVENZ` and `RAR` are extraction-only
(`algorithm.can_compress is False`). `CompressionPreset` maps Fast → Zstd 1,
Balanced → Zstd 3, Maximum → XZ 9.

Folders are tar-bundled automatically for stream algorithms; ZIP handles
directories natively. Multi-source input (`extra_sources`) requires uniquely
named sources and uses a container (ZIP, or tar for stream formats).

## Decompressing

```python
result = decompress(DecompressionRequest(
    source=Path("photos.tar.zst"),        # or .001 of a split set, .lsenc, .lsex
    destination=Path("out"),
    password=None,
))
```

`DecompressionRequest` fields: `source`, `destination`, `overwrite=False`,
`verify=True`, `password=None`. Split volumes are joined automatically from any
`.NNN` part; encrypted `.lsenc` and self-extracting inputs are decrypted when a
`password` is supplied. Extraction restores member permissions and
modification times where the format records them.

## Progress callbacks

Pass a `ProgressCallback` — `Callable[[OperationProgress], None]` — to
`compress`, `decompress`, or `optimize_media`. `OperationProgress` carries
`kind`, `completed_bytes`, `total_bytes`, and `current_file`. `ProgressReporter`
throttles and normalizes updates for you if you build your own pipeline.

```python
def on_progress(p: OperationProgress) -> None:
    print(f"{p.completed_bytes}/{p.total_bytes} {p.current_file or ''}")

compress(request, callback=on_progress)
```

## Verification and detection

```python
from ls_compressor.core import detect_algorithm, verify_archive, verify_against_source

algorithm = detect_algorithm(path)                 # signature sniffing
verify_archive(path, password=None)                # returns detected algorithm
verify_against_source(sources, archive, password=None, exclude=())
```

`verify_archive` validates the payload; `verify_against_source` compares
member names and bytes against original sources. Both understand encrypted,
self-extracting, and split-volume inputs.

## Listing archive contents

```python
from ls_compressor.core import list_archive

algorithm, entries = list_archive(Path("photos.tar.zst"))
for entry in entries:
    print(entry.name, entry.uncompressed_size, entry.is_dir)
```

`ArchiveEntry` reports `name`, `uncompressed_size`, `compressed_size` when the
format exposes them, and `is_dir`. `format_listing` renders the same table the
CLI prints.

## Encryption helpers

```python
from ls_compressor.core import (
    decrypt_archive, encrypt_archive, is_encrypted_file,
    is_self_extracting_archive, self_extracting_extension,
)

encrypt_archive(archive, output, password, algorithm=..., is_directory=...)
decrypt_archive(path, output, password)
```

The `LSE` container is `LSE\x01` magic + JSON metadata (Argon2id KDF
parameters; archives written before v1.2 used PBKDF2-HMAC-SHA256 and remain
readable) + AES-256-GCM ciphertext. `self_extracting_extension()` returns the
right suffix for the platform/stub availability (`.exe`, `.lsex`, `.app`, or
`.py` fallback).

## Split volumes

```python
from ls_compressor.core import (
    is_volume, join_volumes, parse_size, split_archive, volume_parts,
)

parse_size("100M")          # -> 104857600
parts = split_archive(archive, Path("backup.tar.zst"), parse_size("500M"))
joined = join_volumes(parts[0], work_dir)
```

Archives split as `DEST.001`, `DEST.002`, …; `is_volume`/`volume_base`/
`volume_parts` inspect a path's membership in a set. Decompress, verify, and
list accept any `.NNN` part directly.

## Media optimization

```python
from ls_compressor.core import (
    MediaOptimizationRequest, detect_media_format, optimize_media,
)

result = optimize_media(MediaOptimizationRequest(
    source=Path("photo.png"),
    destination=Path("photo.webp"),
))
```

PNG/JPEG/WebP images use Pillow; video uses the bundled FFmpeg. Request fields
cover quality, lossless/lossy mode, preset/CRF, and overwrite — see
`core/media.py` for the full `MediaOptimizationRequest`/`Result` fields.

## Password strength

```python
from ls_compressor.core import password_strength

strength = password_strength("hunter2")   # PasswordStrength.WEAK
print(strength.display_name)              # "Weak"
```

Local heuristic estimate (common-password list, character classes, entropy);
returns `PasswordStrength.WEAK | FAIR | GOOD | STRONG`.

## Error handling

All domain errors derive from `CompressionError` (`core/exceptions.py`):

| Exception | Raised when |
|-----------|-------------|
| `InvalidRequestError` | Bad input (missing source, unsupported link, name collision) |
| `DestinationExistsError` | Output exists and `overwrite=False` |
| `CorruptedArchiveError` | Archive fails integrity checks |
| `EncryptionError` | Missing/wrong password or KDF failure |
| `UnsupportedFormatError` | Format not supported for the operation |
| `InsufficientSpaceError` | Destination filesystem is full |
| `FileAccessError` | Permissions / generic filesystem failure |

## Guarantees

- **Atomic output** — results are written to a sibling temp path and moved
  into place only on success; failures clean up.
- **Bounded memory** — payloads stream in fixed-size chunks; archives are
  never fully loaded into memory (except the `LSE` container payload).
- **Safe extraction** — member paths are validated against traversal and link
  attacks before any byte is written.
- **One-way dependencies** — `core/` never imports `gui/` or `cli/`; embed it
  freely.
