"""
Shared upload helpers used by every host API client.

Keeps stall detection, retry pacing, and progress reporting in one place so a
fix applies to all hosts at once.
"""

import time
from typing import Callable, Optional


# Retry pacing shared by all host clients.
BACKOFF_BASE_SECONDS = 5
UPLOAD_MAX_RETRIES = 3
UPLOAD_RETRY_DELAY = 3

# Seconds to wait for the TCP connection on an upload. Separate from the read
# timeout, which must stay generous enough for a large file to finish.
UPLOAD_CONNECT_TIMEOUT = 30

ProgressCallback = Callable[[int, Optional[int]], None]


class ProgressTrackingFile:
    """
    File wrapper that detects stalled uploads and reports transfer progress.

    A plain read timeout cannot distinguish a slow upload from a dead one, so
    this tracks the time between reads instead: the upload only fails if no
    data moves for ``timeout_seconds``.
    """

    def __init__(
        self,
        file_obj,
        timeout_seconds: int = 60,
        progress_callback: Optional[ProgressCallback] = None,
        total_size: Optional[int] = None,
    ):
        """
        Wrap a binary file object.

        Parameters
        ----------
        file_obj : BinaryIO
            The open file to read from.
        timeout_seconds : int, optional
            Seconds without any data transferred before the upload is
            considered stalled. Default is 60.
        progress_callback : Callable[[int, Optional[int]], None], optional
            Called after each read with (bytes_read_so_far, total_size).
            Exceptions raised by the callback are suppressed so a failing
            progress display can never abort an upload.
        total_size : int, optional
            Total size in bytes, passed through to the callback.
        """
        self.file_obj = file_obj
        self.timeout_seconds = timeout_seconds
        self.progress_callback = progress_callback
        self.total_size = total_size
        self.bytes_read = 0
        self.last_read_time = time.time()

    def read(self, size: int = -1) -> bytes:
        """Read a chunk, refreshing the stall timer and reporting progress."""
        elapsed = time.time() - self.last_read_time
        if elapsed > self.timeout_seconds:
            raise TimeoutError(
                f"Upload stalled - no data transferred for "
                f"{self.timeout_seconds}s"
            )

        data = self.file_obj.read(size)
        if data:
            self.last_read_time = time.time()
            self.bytes_read += len(data)
            self._report_progress()
        return data

    def _report_progress(self) -> None:
        """
        Notify the progress callback.

        A broken progress display must never abort an upload, so the callback
        is dropped after its first failure rather than raising once per chunk.
        """
        if not self.progress_callback:
            return
        try:
            self.progress_callback(self.bytes_read, self.total_size)
        except Exception:  # pylint: disable=broad-except
            self.progress_callback = None

    def __getattr__(self, name):
        """Delegate everything else to the wrapped file object."""
        return getattr(self.file_obj, name)
