"""Tests for duplicate detection across hosts."""

import os
import sys
import threading
import unittest
from collections import deque

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from drag_drop_uploader import DragDropUploader  # noqa: E402


class _Flag:
    """Stand-in for a tkinter BooleanVar."""

    def __init__(self, value):
        self._value = value

    def get(self):
        return self._value


class _GofileAPI:
    """Returns one file inside the version folder."""

    def __init__(self, children):
        self.children = children

    def get_content(self, _content_id):
        return {"children": self.children}


class _PixeldrainAPI:
    def __init__(self, files):
        self.files = files

    def get_user_files(self):
        return {"files": self.files}


FILENAME = "com.a-1.0-release.apk"
FULL_NAME = "com.a-1.0-release"


class DetectDuplicatesTests(unittest.TestCase):
    """Only enabled, connected hosts are consulted."""

    def setUp(self) -> None:
        self.app = DragDropUploader()
        self.app.log = lambda *a, **k: None
        self.app.root = None
        self.app._find_existing_version_folder = lambda *a: "ver1"

        self.app.gofile_enabled = _Flag(False)
        self.app.buzzheavier_enabled = _Flag(False)
        self.app.pixeldrain_enabled = _Flag(False)
        self.app.api = None
        self.app.buzzheavier_api = None
        self.app.pixeldrain_api = None
        self.app.root_folder_id = "root"
        self.app.buzzheavier_root_folder_id = "root"
        self.app.folder_structure = {"com.a": "parent1"}
        self.app.buzzheavier_folder_structure = {}

    def _enable_gofile(self, children):
        self.app.gofile_enabled = _Flag(True)
        self.app.api = _GofileAPI(children)

    def _detect(self):
        return self.app._detect_duplicates(FILENAME, "com.a", FULL_NAME)

    def test_gofile_file_match(self) -> None:
        self._enable_gofile({"f1": {"type": "file", "name": FILENAME}})
        result = self._detect()
        self.assertEqual(result["gofile"], {"folder_id": "ver1", "file_id": "f1"})

    def test_gofile_folder_without_file(self) -> None:
        """An existing version folder alone still counts as a duplicate."""
        self._enable_gofile({"f1": {"type": "file", "name": "other.apk"}})
        result = self._detect()
        self.assertEqual(result["gofile"], {"folder_id": "ver1", "file_id": None})

    def test_gofile_no_version_folder_means_no_duplicate(self) -> None:
        self._enable_gofile({})
        self.app._find_existing_version_folder = lambda *a: None
        self.assertEqual(self._detect(), {})

    def test_disabled_host_is_skipped(self) -> None:
        """A connected but disabled host must not be reported."""
        self.app.gofile_enabled = _Flag(False)
        self.app.api = _GofileAPI({"f1": {"type": "file", "name": FILENAME}})
        self.assertEqual(self._detect(), {})

    def test_enabled_but_unconnected_host_is_skipped(self) -> None:
        self.app.gofile_enabled = _Flag(True)
        self.app.api = None
        self.assertEqual(self._detect(), {})

    def test_pixeldrain_matches_by_filename(self) -> None:
        self.app.pixeldrain_enabled = _Flag(True)
        self.app.pixeldrain_api = _PixeldrainAPI([{"name": FILENAME, "id": "px1"}])
        result = self._detect()
        self.assertEqual(result["pixeldrain"], {"folder_id": None, "file_id": "px1"})

    def test_pixeldrain_no_match(self) -> None:
        self.app.pixeldrain_enabled = _Flag(True)
        self.app.pixeldrain_api = _PixeldrainAPI([{"name": "other.apk", "id": "x"}])
        self.assertEqual(self._detect(), {})

    def test_api_error_does_not_propagate(self) -> None:
        """A host failing its lookup must not abort the whole scan."""
        class Exploding:
            def get_user_files(self):
                raise RuntimeError("api down")

        self.app.pixeldrain_enabled = _Flag(True)
        self.app.pixeldrain_api = Exploding()
        self.assertEqual(self._detect(), {})

    def test_multiple_hosts_reported_together(self) -> None:
        self._enable_gofile({"f1": {"type": "file", "name": FILENAME}})
        self.app.pixeldrain_enabled = _Flag(True)
        self.app.pixeldrain_api = _PixeldrainAPI([{"name": FILENAME, "id": "px1"}])
        self.assertEqual(set(self._detect()), {"gofile", "pixeldrain"})


class BatchScanTests(unittest.TestCase):
    """Batch scanning skips unparseable names and releases the queue."""

    def setUp(self) -> None:
        self.app = DragDropUploader()
        self.app.log = lambda *a, **k: None
        self.app.root = None
        self.app.queue_lock = threading.Lock()
        self.app.scan_complete_event = threading.Event()
        self.app.scan_complete_event.clear()
        self.app.scanning_in_progress = True
        self.app.scanned_files = set()
        self.app.duplicate_decisions = {}
        self.app.upload_queue = deque()

    def test_unparseable_filenames_are_skipped(self) -> None:
        self.app._detect_duplicates = lambda *a: {"gofile": {}}
        found = self.app._batch_scan_duplicates([FILENAME, "not-an-apk.txt"])
        self.assertEqual(list(found), [FILENAME])

    def test_detection_error_does_not_stop_the_batch(self) -> None:
        seen = []

        def flaky(file_path, *_a):
            seen.append(file_path)
            if len(seen) == 1:
                raise RuntimeError("boom")
            return {"gofile": {}}

        self.app._detect_duplicates = flaky
        found = self.app._batch_scan_duplicates([FILENAME, "com.b-2.0-release.apk"])
        self.assertEqual(list(found), ["com.b-2.0-release.apk"])

    def test_no_duplicates_releases_queue_worker(self) -> None:
        """The queue blocks on this event; every path must set it."""
        self.app._detect_duplicates = lambda *a: {}
        self.app._batch_scan_and_prompt([FILENAME])
        self.assertFalse(self.app.scanning_in_progress)
        self.assertTrue(self.app.scan_complete_event.is_set())

    def test_scanned_files_are_recorded(self) -> None:
        self.app._detect_duplicates = lambda *a: {}
        self.app._batch_scan_and_prompt([FILENAME])
        self.assertIn(FILENAME, self.app.scanned_files)

    def test_finish_scanning_is_idempotent(self) -> None:
        self.app._finish_scanning()
        self.app._finish_scanning()
        self.assertTrue(self.app.scan_complete_event.is_set())


if __name__ == "__main__":
    unittest.main()
