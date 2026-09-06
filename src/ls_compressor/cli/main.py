"""Headless command-line interface backed by the compression core."""

import argparse
import logging
import sys
import tempfile
import time
from collections.abc import Sequence
from pathlib import Path

from ls_compressor import __version__
from ls_compressor.core import (
    CompressionAlgorithm,
    CompressionRequest,
    DecompressionRequest,
    MediaOptimizationMode,
    MediaOptimizationRequest,
    MediaOptimizationResult,
    OperationProgress,
    OperationResult,
    compress,
    decompress,
    optimize_media,
    verify_archive,
)
from ls_compressor.core.encryption import (
    decrypt_archive,
    is_encrypted_file,
    is_self_extracting_archive,
)
from ls_compressor.core.exceptions import CompressionError, EncryptionError
from ls_compressor.core.watch import (
    WatchFolderConfig,
    WatchOperationType,
    process_watch_event,
)
from ls_compressor.infrastructure.logging import configure_logging
from ls_compressor.infrastructure.watch import WatchService

_LOGGER = logging.getLogger("ls_compressor.cli")


def build_parser() -> argparse.ArgumentParser:
    """Build and return the command-line argument parser."""
    parser = argparse.ArgumentParser(
        prog="ls-compressor",
        description="Compress and decompress files and folders losslessly.",
    )
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {__version__}"
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="count",
        default=0,
        help="enable verbose diagnostic logging",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    compress_parser = subparsers.add_parser("compress", help="create an archive")
    compress_parser.add_argument("source", type=Path)
    compress_parser.add_argument("destination", type=Path)
    compress_parser.add_argument(
        "--algorithm",
        "-a",
        choices=[algorithm.value for algorithm in CompressionAlgorithm],
        default=CompressionAlgorithm.ZIP.value,
    )
    compress_parser.add_argument("--level", "-l", type=int)
    compress_parser.add_argument("--password", "-p")
    compress_parser.add_argument(
        "--self-extracting",
        action="store_true",
        help="create a runnable self-extracting archive",
    )
    _add_operation_options(compress_parser)

    decompress_parser = subparsers.add_parser("decompress", help="extract an archive")
    decompress_parser.add_argument("source", type=Path)
    decompress_parser.add_argument("destination", type=Path)
    decompress_parser.add_argument("--password", "-p")
    _add_operation_options(decompress_parser)

    verify_parser = subparsers.add_parser("verify", help="verify archive integrity")
    verify_parser.add_argument("source", type=Path)
    verify_parser.add_argument("--password", "-p")

    media_parser = subparsers.add_parser(
        "media", help="optimize a media asset (image or video)"
    )
    media_parser.add_argument("source", type=Path)
    media_parser.add_argument("destination", type=Path)
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
        "--force", "-f", action="store_true", help="overwrite existing output"
    )
    media_parser.add_argument(
        "--quiet", "-q", action="store_true", help="suppress progress output"
    )

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
        choices=[algorithm.value for algorithm in CompressionAlgorithm],
        default=CompressionAlgorithm.ZIP.value,
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


def _run(args: argparse.Namespace) -> None:
    """Execute a parsed command or raise a user-safe core exception."""
    _LOGGER.info("Operation started command=%s", args.command)
    if args.command == "verify":
        if is_encrypted_file(args.source) or is_self_extracting_archive(args.source):
            if not args.password:
                raise EncryptionError(
                    "Encrypted archives require a password for verification"
                )
            with tempfile.TemporaryDirectory() as temp_dir:
                archive = Path(temp_dir) / "archive"
                if is_self_extracting_archive(args.source):
                    from ls_compressor.core.encryption import extract_payload

                    payload = extract_payload(args.source)
                    encrypted = Path(temp_dir) / "payload.lse"
                    encrypted.write_bytes(payload)
                    decrypt_archive(encrypted, archive, args.password)
                else:
                    decrypt_archive(args.source, archive, args.password)
                algorithm = verify_archive(archive)
        else:
            algorithm = verify_archive(args.source)
        _LOGGER.info(
            "Operation succeeded command=%s algorithm=%s", args.command, algorithm.value
        )
        print(f"Archive is valid ({algorithm.display_name}): {args.source}")
        return

    callback = None if getattr(args, "quiet", False) else _progress
    if args.command == "media":
        result = optimize_media(
            MediaOptimizationRequest(
                source=args.source,
                destination=args.destination,
                mode=MediaOptimizationMode(args.mode),
                quality=args.quality,
                overwrite=args.force,
                video_preset=args.video_preset,
                video_crf=args.video_crf,
            ),
            callback,
        )
        if callback is not None:
            print(file=sys.stderr)
        _LOGGER.info("Operation succeeded command=%s", args.command)
        _print_media_result(result)
        return

    if args.command == "watch":
        _run_watch(args)
        return

    if args.command == "compress":
        result = compress(
            CompressionRequest(
                source=args.source,
                destination=args.destination,
                algorithm=CompressionAlgorithm(args.algorithm),
                compression_level=args.level,
                overwrite=args.force,
                verify=not args.no_verify,
                password=args.password,
                self_extracting=args.self_extracting,
            ),
            callback,
        )
    else:
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
    _print_result(result)


def main(argv: Sequence[str] | None = None) -> int:
    """Run the CLI and return a process exit status."""
    parser = build_parser()
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
        print(f"Error: {error}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        _LOGGER.warning("Operation cancelled command=%s", args.command)
        print("Error: Operation cancelled", file=sys.stderr)
        return 130
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
