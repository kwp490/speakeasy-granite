"""Qt dialog for downloading the Granite model with progress feedback."""

from __future__ import annotations

from PySide6.QtCore import QObject, QThreadPool, QTimer, Signal
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QProgressBar,
    QVBoxLayout,
    QWidget,
)

from .model_downloader import DownloadProgress, EXIT_SUCCESS, download_model
from .workers import Worker


def _format_bytes(num_bytes: int) -> str:
    value = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            if unit == "B":
                return f"{int(value)} {unit}"
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} TB"


class _DownloadSignals(QObject):
    progress = Signal(object)


class ModelDownloadDialog(QDialog):
    """Modal dialog that runs Granite model download on a worker thread."""

    def __init__(self, model_path: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._model_path = model_path
        self._signals = _DownloadSignals(self)
        self._worker: Worker | None = None
        self._success = False

        self.setWindowTitle("Downloading Granite Model")
        self.setModal(True)
        self.setMinimumWidth(460)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 14)
        layout.setSpacing(10)

        title = QLabel("Downloading IBM Granite Speech")
        title.setObjectName("downloadTitle")
        layout.addWidget(title)

        self._status_label = QLabel("Preparing download...")
        self._status_label.setWordWrap(True)
        layout.addWidget(self._status_label)

        self._progress = QProgressBar()
        self._progress.setRange(0, 0)
        self._progress.setTextVisible(True)
        layout.addWidget(self._progress)

        self._detail_label = QLabel("")
        self._detail_label.setWordWrap(True)
        layout.addWidget(self._detail_label)

        button_row = QHBoxLayout()
        button_row.addStretch(1)
        self._close_button = QPushButton("Close")
        self._close_button.setEnabled(False)
        self._close_button.clicked.connect(self.reject)
        button_row.addWidget(self._close_button)
        layout.addLayout(button_row)

        self._signals.progress.connect(self._on_progress)
        QTimer.singleShot(0, self._start_download)

    @property
    def success(self) -> bool:
        return self._success

    def reject(self) -> None:
        if self._close_button.isEnabled():
            super().reject()

    def _start_download(self) -> None:
        def run_download() -> bool:
            rc = download_model(
                "granite",
                self._model_path,
                progress_callback=self._signals.progress.emit,
                progress_format="none",
            )
            return rc == EXIT_SUCCESS

        self._worker = Worker(run_download)
        self._worker.signals.result.connect(self._on_result)
        self._worker.signals.error.connect(self._on_error)
        QThreadPool.globalInstance().start(self._worker)

    def _on_progress(self, progress: DownloadProgress) -> None:
        self._status_label.setText(progress.message)
        if progress.percent is None:
            self._progress.setRange(0, 0)
        else:
            self._progress.setRange(0, 100)
            self._progress.setValue(progress.percent)

        details: list[str] = []
        if progress.downloaded_bytes is not None and progress.total_bytes:
            details.append(
                f"{_format_bytes(progress.downloaded_bytes)} / "
                f"{_format_bytes(progress.total_bytes)}"
            )
        if progress.label:
            details.append(progress.label)
        self._detail_label.setText(" - ".join(details))

    def _on_result(self, success: object) -> None:
        self._success = bool(success)
        self._progress.setRange(0, 100)
        if self._success:
            self._progress.setValue(100)
            self._status_label.setText("Granite model is ready.")
            self._detail_label.setText("")
            QTimer.singleShot(700, self.accept)
        else:
            self._status_label.setText("The Granite model download failed.")
            self._detail_label.setText("Check the application log, then try again from Settings.")
            self._close_button.setEnabled(True)

    def _on_error(self, message: str) -> None:
        self._success = False
        self._progress.setRange(0, 100)
        self._status_label.setText("The Granite model download failed.")
        self._detail_label.setText(message)
        self._close_button.setEnabled(True)


def run_model_download_dialog(model_path: str, parent: QWidget | None = None) -> bool:
    dialog = ModelDownloadDialog(model_path, parent)
    dialog.exec()
    return dialog.success
