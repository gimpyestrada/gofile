"""Tests for folder structure cache persistence and validation."""

import json
import os
import shutil
import sys
import tempfile
import unittest
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import folder_cache  # noqa: E402


def _entry(root_id="root1", age_hours=0, folders=None):
    """Build a host cache entry with a timestamp offset into the past."""
    return {
        "timestamp": (datetime.now() - timedelta(hours=age_hours)).isoformat(),
        "root_folder_id": root_id,
        "folders": folders if folders is not None else {},
    }


class CacheFileTests(unittest.TestCase):
    """Reading and writing the cache file."""

    def setUp(self) -> None:
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        self.path = os.path.join(self.dir, "cache.json")

    def test_missing_file_reads_as_none(self) -> None:
        self.assertIsNone(folder_cache.read_cache(self.path))

    def test_round_trip(self) -> None:
        folder_cache.write_cache(self.path, {"gofile": _entry()})
        self.assertIn("gofile", folder_cache.read_cache(self.path))

    def test_corrupt_file_raises(self) -> None:
        with open(self.path, "w", encoding="utf-8") as handle:
            handle.write("{not json")
        with self.assertRaises(folder_cache.FolderCacheError):
            folder_cache.read_cache(self.path)

    def test_save_host_preserves_other_hosts(self) -> None:
        """Saving one host must not wipe another host's cached folders."""
        folder_cache.write_cache(self.path, {"gofile": _entry(root_id="g")})
        folder_cache.save_host_folders(self.path, "buzzheavier", "b", {"f1": {}})

        data = folder_cache.read_cache(self.path)
        self.assertEqual(set(data), {"gofile", "buzzheavier"})
        self.assertEqual(data["gofile"]["root_folder_id"], "g")
        self.assertEqual(data["buzzheavier"]["root_folder_id"], "b")

    def test_save_over_corrupt_file_starts_fresh(self) -> None:
        """A corrupt cache must not block an upload."""
        with open(self.path, "w", encoding="utf-8") as handle:
            handle.write("{not json")
        folder_cache.save_host_folders(self.path, "gofile", "g", {})
        self.assertIn("gofile", folder_cache.read_cache(self.path))


class MigrationTests(unittest.TestCase):
    """The original format stored one host's data at the root."""

    def test_old_format_is_detected(self) -> None:
        old = {"timestamp": datetime.now().isoformat(), "folders": {}}
        self.assertTrue(folder_cache.needs_migration(old))

    def test_new_format_is_not_migrated(self) -> None:
        self.assertFalse(folder_cache.needs_migration({"gofile": _entry()}))

    def test_migration_nests_under_gofile(self) -> None:
        old = {"timestamp": "t", "root_folder_id": "r", "folders": {"a": {}}}
        migrated = folder_cache.migrate(old)
        self.assertEqual(migrated["gofile"]["root_folder_id"], "r")


class ValidationTests(unittest.TestCase):
    """A cache entry is only usable if fresh and for the same account."""

    def test_fresh_matching_cache_is_valid(self) -> None:
        data = {"gofile": _entry(root_id="root1", age_hours=1)}
        entry, reason = folder_cache.get_valid_host_cache(data, "gofile", "root1", 24)
        self.assertIsNotNone(entry)
        self.assertEqual(reason, "ok")

    def test_expired_cache_is_rejected(self) -> None:
        data = {"gofile": _entry(root_id="root1", age_hours=48)}
        entry, reason = folder_cache.get_valid_host_cache(data, "gofile", "root1", 24)
        self.assertIsNone(entry)
        self.assertEqual(reason, "cache expired")

    def test_different_root_folder_is_rejected(self) -> None:
        """A different root means a different account; reusing it is wrong."""
        data = {"gofile": _entry(root_id="root1")}
        entry, reason = folder_cache.get_valid_host_cache(data, "gofile", "root2", 24)
        self.assertIsNone(entry)
        self.assertEqual(reason, "root folder changed")

    def test_missing_host_is_rejected(self) -> None:
        entry, reason = folder_cache.get_valid_host_cache({}, "gofile", "root1", 24)
        self.assertIsNone(entry)
        self.assertEqual(reason, "no cache")

    def test_bad_timestamp_is_rejected_not_raised(self) -> None:
        data = {"gofile": {"timestamp": "garbage", "root_folder_id": "root1"}}
        entry, reason = folder_cache.get_valid_host_cache(data, "gofile", "root1", 24)
        self.assertIsNone(entry)
        self.assertEqual(reason, "unreadable timestamp")


class ExtractParentFoldersTests(unittest.TestCase):
    """Only parent-type folders map a package to a folder id."""

    def test_only_parent_entries_are_returned(self) -> None:
        entry = _entry(folders={
            "id1": {"parsed": {"type": "parent", "package": "com.a"}},
            "id2": {"parsed": {"type": "version", "package": "com.a"}},
            "id3": {"parsed": {"type": "parent", "package": "com.b"}},
            "id4": {"parsed": {}},
        })
        self.assertEqual(
            folder_cache.extract_parent_folders(entry),
            {"com.a": "id1", "com.b": "id3"},
        )

    def test_parent_without_package_is_skipped(self) -> None:
        entry = _entry(folders={"id1": {"parsed": {"type": "parent"}}})
        self.assertEqual(folder_cache.extract_parent_folders(entry), {})


if __name__ == "__main__":
    unittest.main()
