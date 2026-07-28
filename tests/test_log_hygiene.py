"""Tests for log link allowlisting, email masking, and excerpt sanitizing."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from apkadmin_api import EXCERPT_MAX_CHARS, _sanitize_excerpt  # noqa: E402
from drag_drop_uploader import DragDropUploader  # noqa: E402


class LinkAllowlistTests(unittest.TestCase):
    """Only URLs belonging to the configured file hosts may be clickable."""

    def test_host_urls_are_allowed(self) -> None:
        for url in [
            "https://gofile.io/d/abc123",
            "https://upload-eu-par.gofile.io/uploadfile",
            "https://buzzheavier.com/xyz",
            "https://pixeldrain.com/u/xyz",
            "https://apkadmin.com/code/app.apk.html",
        ]:
            with self.subTest(url=url):
                self.assertTrue(DragDropUploader._is_allowed_link(url))

    def test_lookalike_domains_are_rejected(self) -> None:
        """A suffix match alone would accept an attacker-controlled domain."""
        for url in [
            "https://gofile.io.evil.com/pwn",
            "https://notgofile.io/pwn",
            "https://evil.com/?redirect=gofile.io",
        ]:
            with self.subTest(url=url):
                self.assertFalse(DragDropUploader._is_allowed_link(url))

    def test_non_http_schemes_are_rejected(self) -> None:
        for url in ["javascript:alert(1)", "file:///C:/Windows", "ftp://gofile.io/x"]:
            with self.subTest(url=url):
                self.assertFalse(DragDropUploader._is_allowed_link(url))

    def test_trailing_dot_host_is_normalized(self) -> None:
        self.assertTrue(DragDropUploader._is_allowed_link("https://gofile.io./d/a"))


class EmailMaskingTests(unittest.TestCase):
    """The account email must not appear in full in a shareable log."""

    def test_local_part_is_redacted(self) -> None:
        self.assertEqual(
            DragDropUploader._mask_email("someuser@example.com"),
            "so***@example.com",
        )

    def test_short_local_part_keeps_one_character(self) -> None:
        self.assertEqual(DragDropUploader._mask_email("ab@x.io"), "a***@x.io")

    def test_missing_or_malformed_email(self) -> None:
        self.assertEqual(DragDropUploader._mask_email(None), "(unknown)")
        self.assertEqual(DragDropUploader._mask_email("noatsign"), "(unknown)")


class ExcerptSanitizerTests(unittest.TestCase):
    """A scraped site's response is untrusted text."""

    def test_markup_and_urls_are_stripped(self) -> None:
        hostile = '<a href="http://evil.com">http://evil.com/steal</a> hello'
        result = _sanitize_excerpt(hostile)
        self.assertNotIn("<", result)
        self.assertNotIn("http", result)
        self.assertIn("hello", result)

    def test_long_response_is_truncated(self) -> None:
        result = _sanitize_excerpt("A" * 5000)
        self.assertLessEqual(len(result), EXCERPT_MAX_CHARS + 3)

    def test_empty_response_is_labeled(self) -> None:
        self.assertEqual(_sanitize_excerpt("   "), "(empty response)")


if __name__ == "__main__":
    unittest.main()
