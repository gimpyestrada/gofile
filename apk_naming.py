"""
APK filename parsing.

Uploaded files are named ``<package>-<version>[-<suffix>].apk`` and the folder
structure on each host is derived from that name. Kept free of GUI and network
dependencies so the rules stay testable in isolation.
"""

import re
from typing import Dict, Optional


# Build-type words that trail the version and are not part of it.
VERSION_SUFFIX_TOKENS = frozenset({
    'release', 'fix', 'hotfix', 'bugfix', 'patch', 'patched',
})


def parse_apk_filename(filename: str) -> Optional[Dict[str, str]]:
    """
    Parse an APK filename into its package and version parts.

    Parameters
    ----------
    filename : str
        The APK filename to parse (e.g. 'com.app.name-1.0-release.apk' or
        'com.estrada777.projectmyriam-ch.end.03+p-release.apk').

    Returns
    -------
    Optional[Dict[str, str]]
        Dictionary with 'package', 'version', 'full_name', and 'filename'
        keys if parsing succeeds, None otherwise.
    """
    if not filename.lower().endswith('.apk'):
        return None

    name_without_ext = filename[:-4]

    if '-' not in name_without_ext:
        return None

    package, remainder = name_without_ext.split('-', 1)

    if not remainder:
        return None

    # The version may itself contain hyphens, so strip build-type words from
    # the end rather than assuming a fixed number of parts.
    version_tokens = remainder.split('-')
    while version_tokens and version_tokens[-1].lower() in VERSION_SUFFIX_TOKENS:
        version_tokens.pop()

    if not version_tokens:
        return None

    version = '-'.join(version_tokens).strip()
    package = package.strip()

    if not package or not version:
        return None

    return {
        'package': package,
        'version': version,
        'full_name': name_without_ext,
        'filename': filename,
    }


def normalize_version_folder_name(folder_name: str) -> str:
    """
    Normalize a version folder name by removing a trailing '-release'.

    The uploaded file keeps its original name; only the folder is normalized,
    so 'app-1.0-release' and 'app-1.0' resolve to the same folder.

    Parameters
    ----------
    folder_name : str
        Proposed folder name.

    Returns
    -------
    str
        Folder name without a trailing '-release' token.
    """
    return re.sub(r'(?i)-release$', '', folder_name)
