"""Tests that awkward filenames survive upload URL construction."""

import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from buzzheavier_api import BuzzheavierAPI  # noqa: E402
from pixeldrain_api import PixeldrainAPI  # noqa: E402

# '#' truncates a URL, '%' begins an escape sequence, and a space is illegal
# in a URL path. '?' is excluded: Windows rejects it in a filename.
AWKWARD_NAMES = [
    "app#1-1.0-release.apk",
    "100%-complete-1.0.apk",
    "my app-1.0-release.apk",
    "app&co-1.0.apk",
    "app+plus-1.0.apk",
]


class UploadURLQuotingTests(unittest.TestCase):
    """The filename must be percent-encoded into the URL path, not inlined."""

    def _capture_url(self, api, method_name, tmp_path):
        """Run upload_file against a stubbed transport and return the URL."""
        captured = {}

        def fake_request(url, **kwargs):
            captured["url"] = url
            response = mock.Mock()
            response.status_code = 200
            response.headers = {"content-type": "application/json"}
            response.json.return_value = {"id": "abc", "data": {"id": "abc"}}
            response.raise_for_status.return_value = None
            return response

        with mock.patch.object(api.session, method_name, fake_request):
            api.upload_file(str(tmp_path))
        return captured["url"]

    def _write_file(self, name):
        """Create a small temp file with the given name; returns its path."""
        directory = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, directory, ignore_errors=True)
        path = os.path.join(directory, name)
        with open(path, "wb") as handle:
            handle.write(b"test")
        return path

    def test_buzzheavier_encodes_filename(self) -> None:
        api = BuzzheavierAPI(account_id="token")
        for name in AWKWARD_NAMES:
            with self.subTest(name=name):
                path = self._write_file(name)
                url = self._capture_url(api, "put", path)
                self.assertNotIn(" ", url)
                self.assertNotIn("#", url)
                # The location query must survive: exactly one '?' in the URL.
                self.assertEqual(url.count("?"), 1)
                self.assertIn("locationId=", url)

    def test_pixeldrain_encodes_filename(self) -> None:
        api = PixeldrainAPI(api_key="key")
        for name in AWKWARD_NAMES:
            with self.subTest(name=name):
                path = self._write_file(name)
                url = self._capture_url(api, "put", path)
                self.assertNotIn(" ", url)
                self.assertNotIn("#", url)
                self.assertNotIn("?", url)
                self.assertTrue(url.startswith(f"{api.BASE_API_URL}/file/"))

    def test_plain_filename_is_unchanged(self) -> None:
        """Ordinary APK names must not gain escapes."""
        api = PixeldrainAPI(api_key="key")
        path = self._write_file("com.example.app-1.2.3-release.apk")
        url = self._capture_url(api, "put", path)
        self.assertTrue(url.endswith("/com.example.app-1.2.3-release.apk"))


if __name__ == "__main__":
    unittest.main()
