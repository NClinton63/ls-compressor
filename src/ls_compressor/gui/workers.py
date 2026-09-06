"""QThreadPool/QRunnable workers that run compression core operations."""

import logging
from pathlib import Path
from uuid import UUID

from PySide6.QtCore import QObject, QRunnable, Signal

from ls_compressor.core import (
    CompressionAlgorithm,
    CompressionRequest,
    DecompressionRequest,
    MediaFormat,
    MediaOptimizationMode,
    MediaOptimizationRequest,
    OperationProgress,
    OperationResult,
    compress,
    decompress,
    detect_media_format,
    optimize_media,
)
from ls_compressor.core.exceptions import CompressionError
from ls_compressor.gui.models import GuiJobKind

LOGGER = logging.getLogger("ls_compressor.gui.workers")


class WorkerSignals(QObject):
    """Signals emitted by a background compression worker."""

    started = Signal(object)
    progress = Signal(object, float, object)
    current_file = Signal(object, object)
    result = Signal(object, object)
    error = Signal(object, str)


class CompressionWorker(QRunnable):
    """Run one compression, decompression, or media optimization operation."""

    def __init__(
        self,
        job_id: UUID,
        kind: GuiJobKind,
        source: Path,
        destination: Path,
        algorithm: CompressionAlgorithm | None = None,
        compression_level: int | None = None,
        media_format: MediaFormat | None = None,
        media_mode: MediaOptimizationMode = MediaOptimizationMode.LOSSLESS,
        media_quality: int | None = None,
        video_preset: str = "medium",
        video_crf: int | None = None,
        password: str | None = None,
        self_extracting: bool = False,
    ) -> None:
        """Initialize a worker for the supplied job description."""
        super().__init__()
        self.job_id = job_id
        self.kind = kind
        self.source = source
        self.destination = destination
        self.algorithm = algorithm
        self.compression_level = compression_level
        self.media_format = media_format
        self.media_mode = media_mode
        self.media_quality = media_quality
        self.video_preset = video_preset
        self.video_crf = video_crf
        self.password = password
        self.self_extracting = self_extracting
        self.signals = WorkerSignals()

    def run(self) -> None:
        """Execute the operation and emit progress, result, or error signals."""
        self.signals.started.emit(self.job_id)
        try:
            if self.kind == GuiJobKind.COMPRESS:
                result = self._compress()
            elif self.kind == GuiJobKind.MEDIA_OPTIMIZE:
                result = self._optimize_media()
            else:
                result = self._decompress()
            self.signals.result.emit(self.job_id, result)
        except CompressionError as error:
            LOGGER.warning("Job %s failed: %s", self.job_id, error)
            self.signals.error.emit(self.job_id, str(error))
        except Exception:
            LOGGER.exception("Unexpected worker failure for job %s", self.job_id)
            self.signals.error.emit(
                self.job_id, "The operation failed because of an unexpected error."
            )

    def _compress(self) -> OperationResult:
        """Run a compression request with progress reporting."""
        request = CompressionRequest(
            source=self.source,
            destination=self.destination,
            algorithm=self.algorithm or CompressionAlgorithm.ZIP,
            compression_level=self.compression_level,
            overwrite=False,
            verify=True,
            password=self.password,
            self_extracting=self.self_extracting,
        )
        return compress(request, self._on_progress)

    def _decompress(self) -> OperationResult:
        """Run a decompression request with progress reporting."""
        request = DecompressionRequest(
            source=self.source,
            destination=self.destination,
            overwrite=False,
            verify=True,
            password=self.password,
        )
        return decompress(request, self._on_progress)

    def _optimize_media(self) -> OperationResult:
        """Run a media optimization request with progress reporting."""
        detected_format = detect_media_format(self.source)
        request = MediaOptimizationRequest(
            source=self.source,
            destination=self.destination,
            mode=self.media_mode,
            quality=self.media_quality,
            overwrite=False,
            video_preset=self.video_preset,
            video_crf=self.video_crf,
        )
        if self.media_format is not None and detected_format != self.media_format:
            LOGGER.warning(
                "Requested format %s does not match detected format %s for %s",
                self.media_format,
                detected_format,
                self.source,
            )
        return optimize_media(request, self._on_progress)

    def _on_progress(self, update: OperationProgress) -> None:
        """Forward core progress updates as GUI worker signals."""
        self.signals.progress.emit(self.job_id, update.percentage, update.current_file)
        if update.current_file is not None:
            self.signals.current_file.emit(self.job_id, update.current_file)
