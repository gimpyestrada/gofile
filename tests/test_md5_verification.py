"""Tests for post-upload MD5 verification."""

import hashlib
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from drag_drop_uploader import DragDropUploader  # noqa: E402


class ComputeMd5Tests(unittest.TestCase):
    """Chunked hashing must agree with a one-shot hash."""

    def setUp(self) -> None:
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)

    def _write(self, data: bytes) -> str:
        path = os.path.join(self.dir, "f.bin")
        with open(path, "wb") as handle:
            handle.write(data)
        return path

    def test_matches_one_shot_hash(self) -> None:
        data = os.urandom(3 * 1024 * 1024 + 517)
        path = self._write(data)
        self.assertEqual(
            DragDropUploader._compute_md5(path), hashlib.md5(data).hexdigest()
        )

    def test_empty_file(self) -> None:
        path = self._write(b"")
        self.assertEqual(
            DragDropUploader._compute_md5(path), hashlib.md5(b"").hexdigest()
        )

    def test_missing_file_returns_none(self) -> None:
        missing = os.path.join(self.dir, "nope.bin")
        self.assertIsNone(DragDropUploader._compute_md5(missing))


class VerifyUploadMd5Tests(unittest.TestCase):
    """Verification reports mismatches but never blocks the upload."""

    def setUp(self) -> None:
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        self.data = b"apk contents" * 100
        self.path = os.path.join(self.dir, "app.apk")
        with open(self.path, "wb") as handle:
            handle.write(self.data)
        self.md5 = hashlib.md5(self.data).hexdigest()

        self.app = DragDropUploader()
        self.messages = []
        self.app.log = lambda m, level="INFO", host="both": (
            self.messages.append((level, m))
        )

    def test_match_logs_success(self) -> None:
        self.app._verify_upload_md5(self.path, {"md5": self.md5})
        self.assertEqual(self.messages[0][0], "SUCCESS")

    def test_comparison_is_case_insensitive(self) -> None:
        """Casing of the server's hex digest must not fail verification."""
        self.app._verify_upload_md5(self.path, {"md5": self.md5.upper()})
        self.assertEqual(self.messages[0][0], "SUCCESS")

    def test_mismatch_logs_error(self) -> None:
        self.app._verify_upload_md5(self.path, {"md5": "0" * 32})
        self.assertEqual(self.messages[0][0], "ERROR")
        self.assertIn("MISMATCH", self.messages[0][1])

    def test_absent_md5_is_silent(self) -> None:
        """Not every response carries an md5; that is not an error."""
        self.app._verify_upload_md5(self.path, {"id": "abc"})
        self.assertEqual(self.messages, [])

    def test_non_dict_result_is_silent(self) -> None:
        for result in (None, "string", 42, []):
            with self.subTest(result=result):
                self.messages.clear()
                self.app._verify_upload_md5(self.path, result)
                self.assertEqual(self.messages, [])

    def test_unreadable_file_warns(self) -> None:
        missing = os.path.join(self.dir, "gone.apk")
        self.app._verify_upload_md5(missing, {"md5": self.md5})
        self.assertEqual(self.messages[0][0], "WARNING")


if __name__ == "__main__":
    unittest.main()
