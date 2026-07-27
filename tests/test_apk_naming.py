"""Tests for APK filename parsing rules."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from apk_naming import (  # noqa: E402
    normalize_version_folder_name,
    parse_apk_filename,
)


class ParseApkFilenameTests(unittest.TestCase):
    """Package/version splitting across the naming shapes actually used."""

    def test_simple_name(self) -> None:
        result = parse_apk_filename("com.app.name-1.0-release.apk")
        self.assertEqual(result["package"], "com.app.name")
        self.assertEqual(result["version"], "1.0")
        self.assertEqual(result["full_name"], "com.app.name-1.0-release")
        self.assertEqual(result["filename"], "com.app.name-1.0-release.apk")

    def test_version_containing_hyphens_is_preserved(self) -> None:
        """Only trailing build-type words are stripped, not inner hyphens."""
        result = parse_apk_filename(
            "com.estrada777.projectmyriam-ch.end.03+p-release.apk"
        )
        self.assertEqual(result["package"], "com.estrada777.projectmyriam")
        self.assertEqual(result["version"], "ch.end.03+p")

    def test_each_suffix_token_is_stripped(self) -> None:
        for suffix in ["release", "fix", "hotfix", "bugfix", "patch", "patched"]:
            with self.subTest(suffix=suffix):
                result = parse_apk_filename(f"com.app-2.5-{suffix}.apk")
                self.assertEqual(result["version"], "2.5")

    def test_stacked_suffixes_are_stripped(self) -> None:
        result = parse_apk_filename("com.app-2.5-fix-release.apk")
        self.assertEqual(result["version"], "2.5")

    def test_suffix_matching_is_case_insensitive(self) -> None:
        result = parse_apk_filename("com.app-2.5-RELEASE.apk")
        self.assertEqual(result["version"], "2.5")

    def test_no_suffix_still_parses(self) -> None:
        result = parse_apk_filename("com.app-3.1.apk")
        self.assertEqual(result["version"], "3.1")

    def test_uppercase_extension_is_accepted(self) -> None:
        self.assertIsNotNone(parse_apk_filename("com.app-1.0.APK"))

    def test_rejects_non_apk(self) -> None:
        self.assertIsNone(parse_apk_filename("com.app-1.0.zip"))

    def test_rejects_name_without_version(self) -> None:
        self.assertIsNone(parse_apk_filename("noversion.apk"))

    def test_rejects_name_that_is_only_suffixes(self) -> None:
        """'app-release.apk' has no version left after stripping."""
        self.assertIsNone(parse_apk_filename("app-release.apk"))

    def test_rejects_empty_package(self) -> None:
        self.assertIsNone(parse_apk_filename("-1.0-release.apk"))


class NormalizeVersionFolderNameTests(unittest.TestCase):
    """Folder names drop a trailing '-release' so variants share a folder."""

    def test_trailing_release_is_removed(self) -> None:
        self.assertEqual(
            normalize_version_folder_name("com.app-1.0-release"), "com.app-1.0"
        )

    def test_case_insensitive(self) -> None:
        self.assertEqual(
            normalize_version_folder_name("com.app-1.0-RELEASE"), "com.app-1.0"
        )

    def test_release_not_at_end_is_kept(self) -> None:
        self.assertEqual(
            normalize_version_folder_name("com.app-release-1.0"),
            "com.app-release-1.0",
        )

    def test_name_without_release_is_unchanged(self) -> None:
        self.assertEqual(
            normalize_version_folder_name("com.app-1.0"), "com.app-1.0"
        )


if __name__ == "__main__":
    unittest.main()
