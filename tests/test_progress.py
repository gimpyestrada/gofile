"""Tests for upload progress reporting and throttling."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from drag_drop_uploader import DragDropUploader  # noqa: E402


class ProgressCallbackTests(unittest.TestCase):
    """The per-chunk callback must not drive a GUI update per chunk."""

    def setUp(self) -> None:
        self.app = DragDropUploader()
        self.updates = []
        self.app._set_host_progress = (
            lambda host, percent: self.updates.append((host, percent))
        )

    def test_reports_whole_percent_steps_only(self) -> None:
        callback = self.app._make_progress_callback("gofile")
        total = 100_000
        for sent in range(1, total + 1, 13):
            callback(sent, total)
        callback(total, total)

        percents = [p for _host, p in self.updates]
        self.assertLessEqual(len(percents), 101)
        self.assertEqual(len(percents), len(set(percents)))
        self.assertEqual(percents[-1], 100)

    def test_percents_are_monotonic(self) -> None:
        callback = self.app._make_progress_callback("gofile")
        for sent in range(1, 10_001):
            callback(sent, 10_000)
        percents = [p for _host, p in self.updates]
        self.assertEqual(percents, sorted(percents))

    def test_host_is_tagged_on_each_update(self) -> None:
        self.app._make_progress_callback("pixeldrain")(50, 100)
        self.assertEqual(self.updates, [("pixeldrain", 50)])

    def test_unknown_total_size_is_ignored(self) -> None:
        """Some responses stream without a known length; that is not an error."""
        callback = self.app._make_progress_callback("gofile")
        callback(500, None)
        callback(500, 0)
        self.assertEqual(self.updates, [])

    def test_callbacks_for_different_hosts_are_independent(self) -> None:
        gofile = self.app._make_progress_callback("gofile")
        pixeldrain = self.app._make_progress_callback("pixeldrain")
        gofile(50, 100)
        pixeldrain(50, 100)
        self.assertEqual(self.updates, [("gofile", 50), ("pixeldrain", 50)])


class ProgressWidgetGuardTests(unittest.TestCase):
    """Progress helpers must be safe before any widgets exist."""

    def test_set_and_reset_without_widgets(self) -> None:
        app = DragDropUploader()
        app._set_host_progress("gofile", 50)
        app._reset_host_progress("gofile")
        app._reset_all_progress()


if __name__ == "__main__":
    unittest.main()
