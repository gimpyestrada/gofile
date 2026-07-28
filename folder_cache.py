"""
Persistence for the per-host folder structure cache.

Scanning every folder on a host is slow, so the layout is cached on disk and
reused until it expires. Pure file I/O: callers supply the path and handle any
reporting, keeping this independent of the GUI.
"""

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Optional, Tuple


class FolderCacheError(Exception):
    """Raised when the cache file cannot be read or written."""


def read_cache(cache_file: str) -> Optional[Dict]:
    """
    Read the raw cache file.

    Parameters
    ----------
    cache_file : str
        Path to the cache JSON file.

    Returns
    -------
    Optional[Dict]
        Parsed cache contents, or None if the file does not exist.

    Raises
    ------
    FolderCacheError
        If the file exists but cannot be read or parsed.
    """
    path = Path(cache_file)
    if not path.exists():
        return None

    try:
        with open(path, 'r', encoding='utf-8') as handle:
            return json.load(handle)
    except (json.JSONDecodeError, OSError) as e:
        raise FolderCacheError(f"Error loading cache: {e}") from e


def write_cache(cache_file: str, cache_data: Dict) -> None:
    """
    Write the full cache structure to disk.

    Raises
    ------
    FolderCacheError
        If the file cannot be written.
    """
    try:
        with open(cache_file, 'w', encoding='utf-8') as handle:
            json.dump(cache_data, handle, indent=2, ensure_ascii=False)
    except OSError as e:
        raise FolderCacheError(f"Error saving cache: {e}") from e


def needs_migration(cache_data: Dict) -> bool:
    """
    Check whether the cache predates the multi-host layout.

    The original format stored one host's data at the root, identified by a
    top-level 'timestamp' with no host keys beside it.
    """
    return 'timestamp' in cache_data and 'gofile' not in cache_data


def migrate(cache_data: Dict) -> Dict:
    """Wrap a single-host cache under the 'gofile' key."""
    return {'gofile': dict(cache_data)}


def save_host_folders(cache_file: str, host: str, root_folder_id: str,
                      folders: Dict) -> None:
    """
    Update one host's entry, preserving the other hosts' cached data.

    Raises
    ------
    FolderCacheError
        If the cache cannot be written.
    """
    try:
        cache_data = read_cache(cache_file) or {}
    except FolderCacheError:
        # A corrupt cache is not worth failing an upload over; start fresh.
        cache_data = {}

    cache_data[host] = {
        'timestamp': datetime.now().isoformat(),
        'root_folder_id': root_folder_id,
        'folders': folders,
    }

    write_cache(cache_file, cache_data)


def get_valid_host_cache(cache_data: Optional[Dict], host: str,
                         root_folder_id: str,
                         expiry_hours: int) -> Tuple[Optional[Dict], str]:
    """
    Return a host's cache entry if it is still usable.

    Parameters
    ----------
    cache_data : Optional[Dict]
        Previously loaded cache contents.
    host : str
        Host name to look up.
    root_folder_id : str
        Root folder currently in use. A cache built against a different root
        describes a different account and must not be reused.
    expiry_hours : int
        Maximum age of a usable cache.

    Returns
    -------
    Tuple[Optional[Dict], str]
        The usable cache entry (or None) and a short reason describing why it
        was rejected, for logging.
    """
    if not cache_data or host not in cache_data:
        return None, "no cache"

    host_cache = cache_data[host]

    try:
        cache_time = datetime.fromisoformat(host_cache.get('timestamp', ''))
    except (TypeError, ValueError):
        return None, "unreadable timestamp"

    if datetime.now() - cache_time > timedelta(hours=expiry_hours):
        return None, "cache expired"

    if host_cache.get('root_folder_id') != root_folder_id:
        return None, "root folder changed"

    return host_cache, "ok"


def extract_parent_folders(host_cache: Dict) -> Dict[str, str]:
    """
    Build the package -> folder id mapping from a cache entry.

    Returns
    -------
    Dict[str, str]
        Mapping of package name to its parent folder id.
    """
    mapping = {}
    for folder_id, folder_info in host_cache.get('folders', {}).items():
        parsed = folder_info.get('parsed', {})
        if parsed.get('type') == 'parent':
            package = parsed.get('package')
            if package:
                mapping[package] = folder_id
    return mapping
