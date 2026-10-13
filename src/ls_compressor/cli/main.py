"""Headless command-line interface backed by the compression core."""

import argparse
import json
import logging
import sys
import tempfile
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from ls_compressor import __version__
from ls_compressor.cli.completions import available_shells, completion_script
from ls_compressor.core import (
    CompressionAlgorithm,
    CompressionPlan,
    CompressionPreset,
    CompressionRequest,
    DecompressionRequest,
    EncryptionFormat,
    MediaOptimizationMode,
    MediaOptimizationRequest,
    MediaOptimizationResult,
    OperationProgress,
    OperationResult,
    compress,
    decompress,
    extract_palette,
    format_listing,
    generate_icon_pack,
    list_archive,
    optimize_media,
    plan_compression,
    verify_archive,
)
from ls_compressor.core.encryption import (
    decrypt_archive,
    is_encrypted_file,
    is_self_extracting_archive,
)
from ls_compressor.core.exceptions import (
    CompressionError,
    EncryptionError,
    InvalidRequestError,
)
from ls_compressor.core.filesystem import source_size
from ls_compressor.core.volumes import is_volume, join_volumes, parse_size
from ls_compressor.core.watch import (
    WatchFolderConfig,
    WatchOperationType,
    process_watch_event,
)
from ls_compressor.infrastructure import shell_integration
from ls_compressor.infrastructure.cli_config import load_cli_config
from ls_compressor.infrastructure.logging import configure_logging
from ls_compressor.infrastructure.watch import WatchService

_LOGGER = logging.getLogger("ls_compressor.cli")


def build_parser(
    config: dict[str, dict[str, Any]] | None = None,
) -> argparse.ArgumentParser:
    """Build and return the command-line argument parser.

    ``config`` maps subcommand names to option default overrides loaded
    from ``ls-compressor.toml``; explicit flags always win.
    """
    config = config or {}
    parser = argparse.ArgumentParser(
        prog="ls-compressor",
        description="Compress and decompress files and folders losslessly.",
    )
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {__version__}"
    )
    parser.add_argument(
        "--config",
        type=Path,
        help="load option defaults from this TOML file instead of the "
        "default search paths",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="count",
        default=0,
        help="enable verbose diagnostic logging",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    compress_parser = subparsers.add_parser(
        "compress",
        help="create an archive from one or more sources "
        "(last argument is the destination)",
    )
    compress_parser.add_argument(
        "paths",
        type=Path,
        nargs="+",
        metavar="PATH",
        help="one or more sources followed by the destination",
    )
    compress_parser.add_argument(
        "--algorithm",
        "-a",
        choices=[
            algorithm.value
            for algorithm in CompressionAlgorithm
            if algorithm.can_compress
        ],
        default=CompressionAlgorithm.ZSTD.value,
    )
    compress_parser.add_argument("--level", "-l", type=int)
    compress_parser.add_argument(
        "--preset",
        choices=[preset.value for preset in CompressionPreset],
        help="named speed/ratio bundle; overrides --algorithm and --level",
    )
    compress_parser.add_argument("--password", "-p")
    compress_parser.add_argument(
        "--encryption",
        choices=[fmt.value for fmt in EncryptionFormat],
        default=EncryptionFormat.LSE.value,
        help="encryption container for --password archives",
    )
    compress_parser.add_argument(
        "--self-extracting",
        action="store_true",
        help="create a runnable self-extracting archive",
    )
    compress_parser.add_argument(
        "--exclude",
        action="append",
        metavar="PATTERN",
        help="exclude sources matching a glob pattern (repeatable); "
        ".lsignore files in source folders are also honored",
    )
    compress_parser.add_argument(
        "--split",
        metavar="SIZE",
        help="split the output into fixed-size volumes named DEST.001, "
        "DEST.002, ... (e.g. --split 100M)",
    )
    compress_parser.add_argument(
        "--jobs",
        "-j",
        type=int,
        metavar="N",
        help="Zstandard compression worker threads; 0 uses all cores "
        "(default: single-threaded)",
    )
    _add_operation_options(compress_parser)
    _add_json_option(compress_parser)

    decompress_parser = subparsers.add_parser("decompress", help="extract an archive")
    decompress_parser.add_argument("source", type=Path)
    decompress_parser.add_argument("destination", type=Path)
    decompress_parser.add_argument("--password", "-p")
    _add_operation_options(decompress_parser)
    _add_json_option(decompress_parser)

    verify_parser = subparsers.add_parser("verify", help="verify archive integrity")
    verify_parser.add_argument("source", type=Path)
    verify_parser.add_argument("--password", "-p")
    _add_json_option(verify_parser)

    list_parser = subparsers.add_parser(
        "list",
        aliases=["ls"],
        help="list archive contents without extracting",
    )
    list_parser.add_argument("source", type=Path)
    list_parser.add_argument("--password", "-p")
    _add_json_option(list_parser)

    media_parser = subparsers.add_parser(
        "media", help="optimize media assets (images, SVG, or video)"
    )
    media_parser.add_argument(
        "paths",
        type=Path,
        nargs="+",
        metavar="PATH",
        help="one or more sources followed by the destination; a directory "
        "source or multiple sources means DEST is an output folder",
    )
    media_parser.add_argument(
        "--mode",
        choices=[mode.value for mode in MediaOptimizationMode],
        default=MediaOptimizationMode.LOSSLESS.value,
    )
    media_parser.add_argument(
        "--quality",
        type=int,
        help="JPEG/WebP quality (1-100) or video CRF override",
    )
    media_parser.add_argument(
        "--video-preset",
        default="medium",
        help="FFmpeg x264 preset (ultrafast to veryslow)",
    )
    media_parser.add_argument(
        "--video-crf",
        type=int,
        help="FFmpeg x264 CRF (0-51, lower is higher quality)",
    )
    media_parser.add_argument(
        "--max-size",
        type=int,
        metavar="PX",
        help="downscale images so the longest edge fits PX pixels",
    )
    media_parser.add_argument(
        "--format",
        choices=["png", "jpg", "webp", "avif"],
        help="convert batch output to this format (keeps source format when "
        "omitted)",
    )
    media_parser.add_argument(
        "--force", "-f", action="store_true", help="overwrite existing output"
    )
    media_parser.add_argument(
        "--quiet", "-q", action="store_true", help="suppress progress output"
    )
    _add_json_option(media_parser)

    palette_parser = subparsers.add_parser(
        "palette", help="extract dominant colors from an image"
    )
    palette_parser.add_argument("source", type=Path)
    palette_parser.add_argument(
        "--count", "-n", type=int, default=8, help="number of colors (default 8)"
    )
    _add_json_option(palette_parser)
    icons_parser = subparsers.add_parser(
        "icons", help="generate a favicon/app-icon pack from an image"
    )
    icons_parser.add_argument("source", type=Path)
    icons_parser.add_argument("destination", type=Path, help="output .zip path")
    icons_parser.add_argument(
        "--force", "-f", action="store_true", help="overwrite existing output"
    )
    _add_json_option(icons_parser)

    watch_parser = subparsers.add_parser(
        "watch", help="monitor a folder and process new files automatically"
    )
    watch_parser.add_argument("folder", type=Path)
    watch_parser.add_argument(
        "--output",
        "-o",
        type=Path,
        required=True,
        help="output folder for processed files",
    )
    watch_parser.add_argument(
        "--operation",
        choices=[op.value for op in WatchOperationType],
        default=WatchOperationType.COMPRESS.value,
        help="processing operation for new files",
    )
    watch_parser.add_argument(
        "--algorithm",
        "-a",
        choices=[
            algorithm.value
            for algorithm in CompressionAlgorithm
            if algorithm.can_compress
        ],
        default=CompressionAlgorithm.ZSTD.value,
    )
    watch_parser.add_argument(
        "--level",
        "-l",
        type=int,
        help="compression level for watched files",
    )
    watch_parser.add_argument(
        "--media-mode",
        choices=[mode.value for mode in MediaOptimizationMode],
        default=MediaOptimizationMode.LOSSLESS.value,
        help="media optimization mode",
    )
    watch_parser.add_argument("--password", "-p")
    watch_parser.add_argument(
        "--self-extracting",
        action="store_true",
        help="create runnable self-extracting archives",
    )
    watch_parser.add_argument(
        "--recursive",
        action="store_true",
        default=True,
        help="watch subdirectories recursively",
    )
    watch_parser.add_argument(
        "--no-recursive",
        action="store_false",
        dest="recursive",
        help="watch only the top-level folder",
    )
    watch_parser.add_argument(
        "--quiet", "-q", action="store_true", help="suppress per-file output"
    )

    bench_parser = subparsers.add_parser(
        "bench", help="benchmark every algorithm against one source"
    )
    bench_parser.add_argument("source", type=Path)
    bench_parser.add_argument(
        "--level",
        "-l",
        type=int,
        help="compression level applied to every algorithm (default: per-algorithm)",
    )

    shell_parser = subparsers.add_parser(
        "shell", help="manage OS shell integration (context menus)"
    )
    shell_parser.add_argument(
        "action",
        choices=["install", "uninstall", "status"],
        help="install, remove, or report shell integration entries",
    )
    completions_parser = subparsers.add_parser(
        "completions", help="print a shell completion script"
    )
    completions_parser.add_argument(
        "shell",
        choices=available_shells(),
        help="shell to generate completions for",
    )

    for name, subparser in {
        "compress": compress_parser,
        "decompress": decompress_parser,
        "verify": verify_parser,
        "list": list_parser,
        "media": media_parser,
        "watch": watch_parser,
        "shell": shell_parser,
    }.items():
        subparser.add_argument("--config", type=Path, help=argparse.SUPPRESS)
        section = config.get(name)
        if section:
            subparser.set_defaults(**section)
    return parser


def _add_operation_options(parser: argparse.ArgumentParser) -> None:
    """Add options shared by compression and decompression commands."""
    parser.add_argument(
        "--force", "-f", action="store_true", help="overwrite existing output"
    )
    parser.add_argument(
        "--no-verify", action="store_true", help="skip archive integrity verification"
    )
    parser.add_argument(
        "--quiet", "-q", action="store_true", help="suppress progress output"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="report what the operation would do without writing output",
    )


def _add_json_option(parser: argparse.ArgumentParser) -> None:
    """Add the machine-readable output flag to a subcommand."""
    parser.add_argument(
        "--json",
        action="store_true",
        help="emit the result as JSON on stdout and suppress progress",
    )


def _emit_json(payload: dict) -> None:
    """Print a JSON document to standard output."""
    print(json.dumps(payload, indent=2))


def _operation_result_dict(result: OperationResult) -> dict:
    """Serialize a compression/decompression result for JSON output."""
    return {
        "operation": result.kind.value,
        "source": str(result.source),
        "destination": str(result.destination),
        "algorithm": result.algorithm.value,
        "source_size": result.source_size,
        "output_size": result.output_size,
        "elapsed_seconds": result.elapsed_seconds,
        "files_processed": result.files_processed,
        "compression_ratio": result.compression_ratio,
        "integrity_verified": result.integrity_verified,
    }


def _print_compress_plan(plan: CompressionPlan, *, json_mode: bool) -> None:
    """Render a compression dry-run plan in human or JSON form."""
    files = [member for member in plan.members if not member.is_dir]
    if json_mode:
        _emit_json(
            {
                "operation": "compress",
                "dry_run": True,
                "destination": str(plan.destination),
                "algorithm": plan.algorithm.value,
                "file_count": len(files),
                "total_bytes": plan.total_bytes,
                "destination_exists": plan.destination_exists,
                "split_volumes": plan.split_volumes,
                "members": [
                    {
                        "name": member.name,
                        "size": member.size,
                        "is_dir": member.is_dir,
                    }
                    for member in plan.members
                ],
            }
        )
        return
    print(f"Dry run: compress → {plan.destination}")
    print(f"Algorithm: {plan.algorithm.display_name}")
    print(f"Files: {len(files)} ({_human_size(plan.total_bytes)})")
    if plan.split_volumes:
        print(f"Volumes: {plan.split_volumes} (estimated)")
    if plan.destination_exists:
        print("Warning: destination already exists (use --force to overwrite)")
    for member in plan.members:
        kind = "dir " if member.is_dir else "file"
        print(f"  {kind} {_human_size(member.size):>12}  {member.name}")


def _print_decompress_plan(args: argparse.Namespace, *, json_mode: bool) -> None:
    """Render a decompression dry-run plan in human or JSON form."""
    algorithm, entries = list_archive(args.source, password=args.password)
    files = [entry for entry in entries if not entry.is_dir]
    destination_exists = args.destination.exists()
    if json_mode:
        _emit_json(
            {
                "operation": "decompress",
                "dry_run": True,
                "source": str(args.source),
                "destination": str(args.destination),
                "algorithm": algorithm.value,
                "file_count": len(files),
                "destination_exists": destination_exists,
                "entries": [
                    {
                        "name": entry.name,
                        "uncompressed_size": entry.uncompressed_size,
                        "is_dir": entry.is_dir,
                    }
                    for entry in entries
                ],
            }
        )
        return
    print(f"Dry run: extract {args.source} → {args.destination}")
    print(f"Algorithm: {algorithm.display_name}")
    print(f"Files: {len(files)}")
    if destination_exists:
        print("Warning: destination already exists (use --force to overwrite)")
    print(format_listing(entries, human_size=_human_size))


def _media_result_dict(result: MediaOptimizationResult) -> dict:
    """Serialize a media optimization result for JSON output."""
    return {
        "operation": result.kind.value,
        "source": str(result.source),
        "destination": str(result.destination),
        "media_format": result.media_format.value,
        "source_size": result.source_size,
        "output_size": result.output_size,
        "elapsed_seconds": result.elapsed_seconds,
        "compression_ratio": result.compression_ratio,
        "integrity_verified": result.integrity_verified,
    }


def _progress(update: OperationProgress) -> None:
    """Render one compact progress update to standard error."""
    current = f"  {update.current_file}" if update.current_file is not None else ""
    print(f"\r{update.percentage:6.2f}%{current}", end="", file=sys.stderr, flush=True)


def _print_result(result: OperationResult) -> None:
    """Print a stable summary of a completed operation."""
    print(f"Completed: {result.kind.value}")
    print(f"Output: {result.destination}")
    print(f"Files: {result.files_processed}")
    print(f"Ratio: {result.compression_ratio:.3f}")
    print(f"Time: {result.elapsed_seconds:.3f}s")
    print(f"Verified: {'yes' if result.integrity_verified else 'no'}")


def _print_media_result(result: MediaOptimizationResult) -> None:
    """Print a stable summary of a completed media optimization."""
    print(f"Completed: {result.kind.value}")
    print(f"Format: {result.media_format.display_name}")
    print(f"Output: {result.destination}")
    print(f"Ratio: {result.compression_ratio:.3f}")
    print(f"Savings: {result.space_savings_percentage:.1f}%")
    print(f"Time: {result.elapsed_seconds:.3f}s")
    print(f"Verified: {'yes' if result.integrity_verified else 'no'}")


def _media_sources(args: argparse.Namespace) -> list[Path]:
    """Expand media command paths into the concrete files to process."""
    sources = args.paths[:-1]
    if not sources:
        raise InvalidRequestError(
            "media requires at least one source and a destination"
        )
    files: list[Path] = []
    for source in sources:
        if source.is_dir():
            files.extend(sorted(path for path in source.iterdir() if path.is_file()))
        else:
            files.append(source)
    return files


def _run_media(args: argparse.Namespace, callback: object) -> None:
    """Run single-file or batch media optimization."""
    files = _media_sources(args)
    destination = args.paths[-1]
    batch = len(args.paths) > 2 or any(source.is_dir() for source in args.paths[:-1])
    if batch:
        destination.mkdir(parents=True, exist_ok=True)
        if not destination.is_dir():
            raise InvalidRequestError(
                "Batch media optimization requires a destination directory"
            )
    results = []
    skipped = 0
    for source in files:
        if batch:
            suffix = f".{args.format}" if args.format else source.suffix
            target = destination / f"{source.stem}{suffix}"
        else:
            target = destination
        try:
            results.append(
                optimize_media(
                    MediaOptimizationRequest(
                        source=source,
                        destination=target,
                        mode=MediaOptimizationMode(args.mode),
                        quality=args.quality,
                        overwrite=True if batch else args.force,
                        video_preset=args.video_preset,
                        video_crf=args.video_crf,
                        max_dimension=args.max_size,
                    ),
                    callback,
                )
            )
        except CompressionError as error:
            _LOGGER.warning("Skipping unsupported media source=%s", source)
            print(f"Skipped {source}: {error}", file=sys.stderr)
            skipped += 1
    if not results:
        raise InvalidRequestError("No supported media files to process")
    if callback is not None:
        print(file=sys.stderr)
    _LOGGER.info(
        "Operation succeeded command=%s files=%d skipped=%d",
        args.command,
        len(results),
        skipped,
    )
    if args.json:
        if batch or len(results) > 1:
            _emit_json(
                {
                    "operation": "media",
                    "files": [_media_result_dict(r) for r in results],
                    "skipped": skipped,
                }
            )
        else:
            _emit_json(_media_result_dict(results[0]))
        return
    for result in results:
        _print_media_result(result)
    if skipped:
        print(f"Skipped: {skipped} file(s)")


def _run_watch(args: argparse.Namespace) -> None:
    """Run a foreground watch service until interrupted."""
    config = WatchFolderConfig(
        path=args.folder,
        output_folder=args.output,
        operation=WatchOperationType(args.operation),
        algorithm=CompressionAlgorithm(args.algorithm),
        compression_level=args.level,
        media_mode=MediaOptimizationMode(args.media_mode),
        recursive=args.recursive,
        password=args.password,
        self_extracting=args.self_extracting,
    )
    service = WatchService(lambda event: _handle_watch_event(event, args.quiet))
    service.add_folder(config)
    service.start()
    print(
        f"Watching {args.folder} for new files. Press Ctrl-C to stop.",
        file=sys.stderr,
    )
    try:
        while True:
            time.sleep(0.5)
    except KeyboardInterrupt:
        service.stop()
        print("\nWatch service stopped.", file=sys.stderr)


def _handle_watch_event(event: object, quiet: bool) -> None:
    """Process one watched file event and print a summary."""
    from ls_compressor.core.watch import WatchEvent

    assert isinstance(event, WatchEvent)
    try:
        result = process_watch_event(event)
    except CompressionError as error:
        _LOGGER.warning("Watch processing failed: %s", error)
        print(f"Error: {error}", file=sys.stderr)
        return
    if not quiet:
        print(
            f"Processed: {event.source.name} -> {result.destination} "
            f"({result.compression_ratio:.1%})",
            file=sys.stderr,
        )


def _run_bench(args: argparse.Namespace) -> None:
    """Time every write-capable algorithm on one source and print a table."""
    source_bytes = source_size(args.source)
    results: list[tuple[CompressionAlgorithm, float, int]] = []
    with tempfile.TemporaryDirectory() as temp_dir:
        for algorithm in CompressionAlgorithm:
            if not algorithm.can_compress:
                continue
            destination = Path(temp_dir) / f"bench.{algorithm.value}"
            try:
                result = compress(
                    CompressionRequest(
                        source=args.source,
                        destination=destination,
                        algorithm=algorithm,
                        compression_level=args.level,
                        verify=False,
                    )
                )
            except CompressionError as error:
                _LOGGER.warning(
                    "Benchmark skipped algorithm=%s error=%s",
                    algorithm.value,
                    error,
                )
                continue
            results.append((algorithm, result.elapsed_seconds, result.output_size))
    if not results:
        raise CompressionError("No algorithm completed the benchmark")
    print(f"Benchmark: {args.source} ({_human_size(source_bytes)} source)")
    print(f"{'Algorithm':<12} {'Time':>10} {'Output':>12} {'Ratio':>8}")
    for algorithm, elapsed, output_size in sorted(results, key=lambda r: r[2]):
        ratio = output_size / source_bytes if source_bytes else 0.0
        print(
            f"{algorithm.display_name:<12} {elapsed:>9.3f}s "
            f"{_human_size(output_size):>12} {ratio:>7.2f}x"
        )


def _run_shell(args: argparse.Namespace) -> None:
    """Install, remove, or report OS shell integration entries."""
    if args.action == "status":
        entries = shell_integration.status()
        for entry in entries:
            marker = "installed" if entry.installed else "missing "
            print(f"[{marker}] {entry.name}: {entry.location}")
        return
    items = (
        shell_integration.install()
        if args.action == "install"
        else shell_integration.uninstall()
    )
    verb = "Installed" if args.action == "install" else "Removed"
    for item in items:
        print(f"{verb}: {item}")
    if not items:
        print("No shell integration entries found.")


def _human_size(size: int | None) -> str:
    """Format a byte count as a compact human-readable string."""
    if size is None:
        return "-"
    value = float(size)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if value < 1024 or unit == "TiB":
            return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} B"
        value /= 1024
    return f"{value:.1f} TiB"


def _run(args: argparse.Namespace) -> None:
    """Execute a parsed command or raise a user-safe core exception."""
    _LOGGER.info("Operation started command=%s", args.command)
    if args.command in {"list", "ls"}:
        algorithm, entries = list_archive(args.source, password=args.password)
        files = [entry for entry in entries if not entry.is_dir]
        total = sum(entry.uncompressed_size or 0 for entry in files)
        if args.json:
            _emit_json(
                {
                    "operation": "list",
                    "source": str(args.source),
                    "algorithm": algorithm.value,
                    "file_count": len(files),
                    "total_uncompressed": total,
                    "entries": [
                        {
                            "name": entry.name,
                            "uncompressed_size": entry.uncompressed_size,
                            "compressed_size": entry.compressed_size,
                            "is_dir": entry.is_dir,
                        }
                        for entry in entries
                    ],
                }
            )
            return
        print(f"{algorithm.display_name} archive: {args.source}")
        print(format_listing(entries, human_size=_human_size))
        print(f"{len(files)} files, {_human_size(total)} uncompressed")
        return
    if args.command == "palette":
        colors = extract_palette(args.source, count=args.count)
        if args.json:
            _emit_json(
                {
                    "operation": "palette",
                    "source": str(args.source),
                    "colors": colors,
                }
            )
        else:
            print(f"Palette ({len(colors)} colors): {args.source}")
            for color in colors:
                print(f"  {color}")
        return

    if args.command == "icons":
        members = generate_icon_pack(
            args.source, args.destination, overwrite=args.force
        )
        if args.json:
            _emit_json(
                {
                    "operation": "icons",
                    "source": str(args.source),
                    "destination": str(args.destination),
                    "files": members,
                }
            )
        else:
            print(f"Icon pack written: {args.destination}")
            for member in members:
                print(f"  {member}")
        return
    if args.command == "verify":
        with tempfile.TemporaryDirectory() as temp_dir:
            source = args.source
            if is_volume(source):
                source = join_volumes(source, Path(temp_dir))
            if is_encrypted_file(source) or is_self_extracting_archive(source):
                if not args.password:
                    raise EncryptionError(
                        "Encrypted archives require a password for verification"
                    )
                archive = Path(temp_dir) / "archive"
                if is_self_extracting_archive(source):
                    from ls_compressor.core.encryption import extract_payload

                    payload = extract_payload(source)
                    encrypted = Path(temp_dir) / "payload.lse"
                    encrypted.write_bytes(payload)
                    decrypt_archive(encrypted, archive, args.password)
                else:
                    decrypt_archive(source, archive, args.password)
                algorithm = verify_archive(archive)
            else:
                algorithm = verify_archive(source, password=args.password)
        _LOGGER.info(
            "Operation succeeded command=%s algorithm=%s", args.command, algorithm.value
        )
        if args.json:
            _emit_json(
                {
                    "operation": "verify",
                    "source": str(args.source),
                    "algorithm": algorithm.value,
                    "valid": True,
                }
            )
        else:
            print(f"Archive is valid ({algorithm.display_name}): {args.source}")
        return

    callback = (
        None
        if getattr(args, "quiet", False) or getattr(args, "json", False)
        else _progress
    )
    if args.command == "media":
        _run_media(args, callback)
        return

    if args.command == "watch":
        _run_watch(args)
        return

    if args.command == "bench":
        _run_bench(args)
        return

    if args.command == "shell":
        _run_shell(args)
        return

    if args.command == "completions":
        print(
            completion_script(args.shell, build_parser()),
            end="",
        )
        return

    if args.command == "compress":
        if len(args.paths) < 2:
            raise InvalidRequestError(
                "compress requires at least one source and a destination"
            )
        sources = args.paths[:-1]
        preset = CompressionPreset(args.preset) if args.preset else None
        if args.dry_run:
            plan = plan_compression(
                CompressionRequest(
                    source=sources[0],
                    destination=args.paths[-1],
                    algorithm=(
                        preset.algorithm
                        if preset
                        else CompressionAlgorithm(args.algorithm)
                    ),
                    compression_level=preset.level if preset else args.level,
                    password=args.password,
                    self_extracting=args.self_extracting,
                    encryption_format=EncryptionFormat(args.encryption),
                    extra_sources=tuple(sources[1:]),
                    exclude=tuple(args.exclude or ()),
                    split_size=parse_size(args.split) if args.split else None,
                )
            )
            _print_compress_plan(plan, json_mode=args.json)
            return
        result = compress(
            CompressionRequest(
                source=sources[0],
                destination=args.paths[-1],
                algorithm=(
                    preset.algorithm if preset else CompressionAlgorithm(args.algorithm)
                ),
                compression_level=preset.level if preset else args.level,
                overwrite=args.force,
                verify=not args.no_verify,
                password=args.password,
                self_extracting=args.self_extracting,
                encryption_format=EncryptionFormat(args.encryption),
                extra_sources=tuple(sources[1:]),
                exclude=tuple(args.exclude or ()),
                split_size=parse_size(args.split) if args.split else None,
                threads=args.jobs,
            ),
            callback,
        )
    else:
        if args.dry_run:
            _print_decompress_plan(args, json_mode=args.json)
            return
        result = decompress(
            DecompressionRequest(
                source=args.source,
                destination=args.destination,
                overwrite=args.force,
                verify=not args.no_verify,
                password=args.password,
            ),
            callback,
        )
    if callback is not None:
        print(file=sys.stderr)
    _LOGGER.info("Operation succeeded command=%s", args.command)
    if getattr(args, "json", False):
        _emit_json(_operation_result_dict(result))
    else:
        _print_result(result)


def main(argv: Sequence[str] | None = None) -> int:
    """Run the CLI and return a process exit status."""
    pre_parser = argparse.ArgumentParser(prog="ls-compressor", add_help=False)
    pre_parser.add_argument("--config", type=Path)
    known, _ = pre_parser.parse_known_args(argv)
    try:
        config = load_cli_config(known.config)
    except InvalidRequestError as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    parser = build_parser(config)
    args = parser.parse_args(argv)
    configure_logging(args.verbose)
    try:
        _run(args)
    except CompressionError as error:
        _LOGGER.error(
            "Operation failed command=%s error_type=%s",
            args.command,
            type(error).__name__,
        )
        if getattr(args, "json", False):
            print(
                json.dumps(
                    {
                        "operation": args.command,
                        "error": str(error),
                        "error_type": type(error).__name__,
                    }
                ),
                file=sys.stderr,
            )
        else:
            print(f"Error: {error}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        _LOGGER.warning("Operation cancelled command=%s", args.command)
        print("Error: Operation cancelled", file=sys.stderr)
        return 130
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
