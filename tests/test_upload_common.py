"""Tests for the shared upload helpers in upload_common."""

import io
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from upload_common import ProgressTrackingFile  # noqa: E402


class ProgressTrackingFileTests(unittest.TestCase):
    """Cover reads, stall detection, progress reporting, and delegation."""

    def test_read_returns_underlying_data(self) -> None:
        tracked = ProgressTrackingFile(io.BytesIO(b"abcdef"))
        self.assertEqual(tracked.read(3), b"abc")
        self.assertEqual(tracked.read(), b"def")
        self.assertEqual(tracked.read(), b"")

    def test_bytes_read_accumulates(self) -> None:
        tracked = ProgressTrackingFile(io.BytesIO(b"abcdef"))
        tracked.read(2)
        tracked.read(2)
        self.assertEqual(tracked.bytes_read, 4)

    def test_stall_raises_timeout_error(self) -> None:
        tracked = ProgressTrackingFile(io.BytesIO(b"abcdef"), timeout_seconds=0)
        tracked.last_read_time -= 1
        with self.assertRaises(TimeoutError):
            tracked.read(1)

    def test_progress_callback_receives_running_total(self) -> None:
        seen = []
        tracked = ProgressTrackingFile(
            io.BytesIO(b"abcdef"),
            progress_callback=lambda read, total: seen.append((read, total)),
            total_size=6,
        )
        tracked.read(4)
        tracked.read(2)
        self.assertEqual(seen, [(4, 6), (6, 6)])

    def test_empty_read_does_not_report_progress(self) -> None:
        seen = []
        tracked = ProgressTrackingFile(
            io.BytesIO(b""),
            progress_callback=lambda read, total: seen.append(read),
        )
        tracked.read()
        self.assertEqual(seen, [])

    def test_failing_callback_is_dropped_not_raised(self) -> None:
        """A broken progress display must never abort an upload."""
        def boom(_read, _total):
            raise RuntimeError("progress bar exploded")

        tracked = ProgressTrackingFile(
            io.BytesIO(b"abcdef"), progress_callback=boom
        )
        tracked.read(3)
        self.assertIsNone(tracked.progress_callback)
        self.assertEqual(tracked.read(3), b"def")

    def test_unknown_attributes_delegate_to_file(self) -> None:
        tracked = ProgressTrackingFile(io.BytesIO(b"abcdef"))
        self.assertEqual(tracked.tell(), 0)
        tracked.read(2)
        self.assertEqual(tracked.tell(), 2)


if __name__ == "__main__":
    unittest.main()
