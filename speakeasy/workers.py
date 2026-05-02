"""Worker helpers for background operations.

Includes a generic ``Worker`` QRunnable for Qt thread pools and a small
QThreadPool-like facade backed by Python threads for engine work that cannot
safely run on Qt-managed threads on Windows.
"""

from __future__ import annotations

import concurrent.futures
import logging
import threading
import time
import traceback
from typing import Any, Callable, Optional

from PySide6.QtCore import QObject, QRunnable, Signal, Slot

log = logging.getLogger(__name__)


class WorkerSignals(QObject):
    """Signals emitted by ``Worker`` instances."""

    finished = Signal()
    error = Signal(str)
    result = Signal(object)
    # Per-chunk partial transcription result: (running_text, chunk_index_1based, total_chunks).
    # Emitted from the worker thread; connect with Qt.QueuedConnection to marshal
    # into the UI thread.
    partial = Signal(str, int, int)


class Worker(QRunnable):
    """Generic runnable that executes *fn* on a ``QThreadPool``.

    Usage::

        worker = Worker(some_blocking_fn, arg1, arg2, kw=val)
        worker.signals.result.connect(handle_result)
        worker.signals.error.connect(handle_error)
        QThreadPool.globalInstance().start(worker)
    """

    def __init__(self, fn: Callable[..., Any], *args: Any, **kwargs: Any):
        super().__init__()
        self.fn = fn
        self.args = args
        self.kwargs = kwargs
        self.signals = WorkerSignals()
        self.setAutoDelete(True)

    @Slot()
    def run(self) -> None:
        try:
            result = self.fn(*self.args, **self.kwargs)
        except BaseException as exc:
            tb = traceback.format_exc()
            log.error("Worker error: %s\n%s", exc, tb)
            self.signals.error.emit(str(exc))
        else:
            self.signals.result.emit(result)
        finally:
            self.signals.finished.emit()


class DedicatedWorkerPool(QObject):
    """Minimal QThreadPool-like facade backed by Python threads.

    Speech/CUDA inference can hang when executed on Qt-managed worker threads on
    Windows. This class preserves the ``start()`` and ``waitForDone()`` API that
    the UI already uses, but runs QRunnables on a ``ThreadPoolExecutor``.
    """

    def __init__(self, parent: Optional[QObject] = None, thread_name_prefix: str = "speakeasy-engine"):
        super().__init__(parent)
        self._thread_name_prefix = thread_name_prefix
        self._max_workers = 1
        self._expiry_timeout_ms = -1
        self._lock = threading.Lock()
        self._futures: set[concurrent.futures.Future[Any]] = set()
        self._executor = self._create_executor()

    def _create_executor(self) -> concurrent.futures.ThreadPoolExecutor:
        return concurrent.futures.ThreadPoolExecutor(
            max_workers=self._max_workers,
            thread_name_prefix=self._thread_name_prefix,
        )

    def setMaxThreadCount(self, count: int) -> None:
        count = max(1, int(count))
        if count == self._max_workers:
            return

        old_executor = None
        with self._lock:
            self._max_workers = count
            if any(not future.done() for future in self._futures):
                return
            old_executor = self._executor
            self._executor = self._create_executor()

        if old_executor is not None:
            old_executor.shutdown(wait=False, cancel_futures=False)

    def setExpiryTimeout(self, timeout_ms: int) -> None:
        # Stored for API compatibility with QThreadPool.
        self._expiry_timeout_ms = int(timeout_ms)

    def start(self, worker: QRunnable) -> None:
        with self._lock:
            executor = self._executor

        future = executor.submit(worker.run)
        with self._lock:
            self._futures.add(future)
        future.add_done_callback(self._discard_future)

    def _discard_future(self, future: concurrent.futures.Future[Any]) -> None:
        with self._lock:
            self._futures.discard(future)

    def waitForDone(self, msecs: int = -1) -> bool:
        deadline = None if msecs < 0 else time.monotonic() + (msecs / 1000.0)

        while True:
            with self._lock:
                pending = [future for future in self._futures if not future.done()]

            if not pending:
                return True

            if deadline is not None:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
            else:
                remaining = None

            try:
                pending[0].result(timeout=remaining)
            except concurrent.futures.TimeoutError:
                return False
            except BaseException:
                continue

    def warmup(self) -> None:
        """Submit a no-op task and block until the worker thread has been created.

        Call this *before* loading CUDA DLLs (i.e. before importing torch) to
        ensure the engine thread already exists when those DLLs load.  On
        Windows, CUDA registers DllMain(DLL_THREAD_ATTACH) callbacks that fire
        for every thread created *after* the DLLs load; if the engine thread is
        new at that point the callback can corrupt its stack, causing access
        violations in otherwise-innocent code.
        """
        self._executor.submit(lambda: None).result()

    def shutdown(self, wait: bool = True, cancel_futures: bool = False) -> None:
        self._executor.shutdown(wait=wait, cancel_futures=cancel_futures)
