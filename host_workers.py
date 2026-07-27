"""
Per-host connection, upload, and retry logic.

Mixed into DragDropUploader rather than standing alone: these methods drive
the GUI through self.log, self._update_status_emoji, and the host state set up
in the uploader's __init__.
"""

import hashlib
import os
import threading
import time
import tkinter as tk
from tkinter import messagebox
from typing import Dict, List, Optional

import requests

from gofile_api import GofileAPI, GofileAPIError
from buzzheavier_api import (
    BuzzheavierAPI,
    BuzzheavierAPIError,
    BuzzheavierHTTPError,
    NetworkException,
)
from pixeldrain_api import (
    PixeldrainAPI,
    PixeldrainAPIError,
    NetworkException as PixeldrainNetworkException,
)
from apkadmin_api import (
    ApkadminAPI,
    ApkadminAPIError,
    ApkadminAuthError,
    NetworkException as ApkadminNetworkException,
)
from config_loader import get_app_dir


# Read size for hashing large APKs without loading them into memory.
MD5_CHUNK_SIZE = 1024 * 1024


class HostWorkersMixin:
    """Connect to, upload to, and retry each configured file host."""

    # ===== CONNECTION =====

    def _initialize_gofile(self) -> bool:
        """
        Initialize Gofile API connection.

        Returns
        -------
        bool
            True if initialization successful, False otherwise
        """
        try:
            self.log("Connecting to Gofile...", host="gofile")
            self.api = GofileAPI(api_token=self.config.api_token)

            account_details = self.api.get_account_details(self.config.account_id)
            self.root_folder_id = account_details.get('rootFolder')

            tier = account_details.get('tier')

            self.log("Connected to Gofile account", "SUCCESS", host="gofile")
            self.log(f"Account: {self._mask_email(account_details.get('email'))}",
                     host="gofile")
            self.log(f"Tier: {tier}", host="gofile")

            return True

        except GofileAPIError as e:
            self.log(f"Failed to connect to Gofile: {e}", "ERROR", host="gofile")
            return False
        except requests.exceptions.RequestException as e:
            self.log(f"Network error connecting to Gofile: {e}", "ERROR", host="gofile")
            return False
        except (RuntimeError, KeyError, ValueError) as e:
            self.log(f"Failed to connect to Gofile: {e}", "ERROR", host="gofile")
            return False
        except Exception as e:  # pylint: disable=broad-except
            self.log(f"Unexpected error connecting to Gofile: {e}", "ERROR", host="gofile")
            return False

    def _initialize_buzzheavier(self) -> bool:
        """
        Initialize Buzzheavier API connection.

        Returns
        -------
        bool
            True if initialization successful, False otherwise
        """
        try:
            self.log("Connecting to Buzzheavier...", host="buzzheavier")
            self.buzzheavier_api = BuzzheavierAPI(
                account_id=self.config.buzzheavier_account_id,
                preferred_location=BuzzheavierAPI.LOCATION_EASTERN_US
            )

            account_details = self.buzzheavier_api.get_account_details()

            # Get root directory
            root_content = self.buzzheavier_api.get_content()
            self.buzzheavier_root_folder_id = root_content.get('id')

            created_at = account_details.get('createdAt', 'Unknown')
            locations = account_details.get('locations', [])
            location_names = ', '.join([loc.get('name', '') for loc in locations])

            self.log("Connected to Buzzheavier account", "SUCCESS", host="buzzheavier")
            self.log(f"Account created: {created_at}", host="buzzheavier")
            self.log(f"Available locations: {location_names}", host="buzzheavier")

            return True

        except NetworkException as e:
            self.log(f"Network error connecting to Buzzheavier: {e}", "ERROR", host="buzzheavier")
            return False
        except BuzzheavierAPIError as e:
            self.log(f"Failed to connect to Buzzheavier: {e}", "ERROR", host="buzzheavier")
            return False
        except requests.exceptions.RequestException as e:
            self.log(f"Network error connecting to Buzzheavier: {e}", "ERROR", host="buzzheavier")
            return False
        except (RuntimeError, KeyError, ValueError) as e:
            self.log(f"Failed to connect to Buzzheavier: {e}", "ERROR", host="buzzheavier")
            return False
        except Exception as e:  # pylint: disable=broad-except
            self.log(f"Unexpected error connecting to Buzzheavier: {e}", "ERROR", host="buzzheavier")
            return False

    def _initialize_pixeldrain(self) -> bool:
        """
        Initialize Pixeldrain API connection.

        Returns
        -------
        bool
            True if initialization successful, False otherwise
        """
        try:
            self.log("Connecting to Pixeldrain...", host="pixeldrain")

            self.pixeldrain_api = PixeldrainAPI(api_key=self.config.pixeldrain_api_key)

            # Get user files to verify connection
            user_data = self.pixeldrain_api.get_user_files()

            file_count = len(user_data.get('files', []))
            self.log("Connected to Pixeldrain account", "SUCCESS", host="pixeldrain")
            self.log(f"Files in account: {file_count}", host="pixeldrain")

            return True

        except PixeldrainNetworkException as e:
            self.log(f"Network error connecting to Pixeldrain: {e}", "ERROR", host="pixeldrain")
            return False
        except PixeldrainAPIError as e:
            self.log(f"Failed to connect to Pixeldrain: {e}", "ERROR", host="pixeldrain")
            return False
        except (RuntimeError, KeyError, ValueError) as e:
            self.log(f"Failed to connect to Pixeldrain: {e}", "ERROR", host="pixeldrain")
            return False
        except Exception as e:  # pylint: disable=broad-except
            self.log(f"Unexpected error connecting to Pixeldrain: {e}", "ERROR", host="pixeldrain")
            return False

    def _initialize_apkadmin(self) -> bool:
        """
        Initialize Apkadmin session using browser cookies.

        Returns
        -------
        bool
            True if initialization successful, False otherwise
        """
        try:
            self.log("Connecting to Apkadmin...", host="apkadmin")

            self.apkadmin_api = ApkadminAPI(
                cf_clearance=self.config.apkadmin_cf_clearance,
                xfss=self.config.apkadmin_xfss,
                user_agent=self.config.apkadmin_user_agent,
            )
            self.apkadmin_api.verify_connection()
            self.log("Connected to Apkadmin", "SUCCESS", host="apkadmin")
            return True

        except ApkadminAuthError as e:
            self.log(f"Auth error: {e}", "ERROR", host="apkadmin")
            self._warn_apkadmin_cookies_expired()
            return False
        except ApkadminNetworkException as e:
            self.log(f"Network error connecting to Apkadmin: {e}", "ERROR", host="apkadmin")
            return False
        except ApkadminAPIError as e:
            self.log(f"Failed to connect to Apkadmin: {e}", "ERROR", host="apkadmin")
            return False
        except (ValueError, KeyError) as e:
            self.log(f"Config error for Apkadmin: {e}", "ERROR", host="apkadmin")
            return False
        except Exception as e:  # pylint: disable=broad-except
            self.log(f"Unexpected error connecting to Apkadmin: {e}", "ERROR", host="apkadmin")
            return False

    def _warn_apkadmin_cookies_expired(self) -> None:
        """
        Offer to open the setup guide when Apkadmin cookies have expired.

        Cloudflare's cf_clearance cookie expires often, so this is the routine
        failure for this host rather than an exceptional one. Without a prompt
        the only clue is a line in a log column the user may not be watching.
        """
        def prompt():
            open_guide = messagebox.askyesno(
                "Apkadmin Cookies Expired",
                "Apkadmin rejected the saved session.\n\n"
                "The cf_clearance cookie expires regularly and has to be "
                "copied from your browser again.\n\n"
                "Open the setup guide now?",
            )
            if open_guide:
                self._open_setup_guide()

        self._run_on_gui_thread(prompt)

    def _open_setup_guide(self) -> None:
        """Open the Apkadmin setup guide in the default application."""
        guide_path = os.path.join(get_app_dir(), "docs", "APKADMIN_SETUP.md")
        if not os.path.exists(guide_path):
            messagebox.showerror(
                "Not Found",
                f"Setup guide not found at:\n{guide_path}"
            )
            return
        os.startfile(guide_path)

    # ===== UPLOAD =====

    def _upload_to_gofile(self, file_path: str, package: str, _version: str, full_name: str) -> Optional[str]:
        """
        Upload file to Gofile.

        Parameters
        ----------
        file_path : str
            Path to the file
        package : str
            Package name
        _version : str
            Version string
        full_name : str
            Full folder name (package-version-suffix)

        Returns
        -------
        Optional[str]
            Public link if successful, None otherwise
        """
        try:
            # Get or create parent folder
            parent_id = self.folder_structure.get(package)

            if not parent_id:
                self.log(f"No parent folder found for {package}", "WARNING", host="gofile")
                parent_id = self.create_parent_folder(package)
                if not parent_id:
                    self.log("Failed to create parent folder", "ERROR", host="gofile")
                    return None
            else:
                self.log(f"Found parent folder: {package}", host="gofile")

            version_folder_name = self._normalize_version_folder_name(full_name)

            # Create or get version folder, honoring legacy names
            version_id = self.create_version_folder(
                parent_id,
                version_folder_name,
                alt_version_names=[full_name] if full_name != version_folder_name else None
            )
            if not version_id:
                self.log("Failed to create/get version folder", "ERROR", host="gofile")
                return None

            # Upload file
            file_size_bytes = os.path.getsize(file_path)
            file_size_mb = file_size_bytes / (1024 * 1024)
            self.log(f"Uploading - {round(file_size_mb)} MB...", host="gofile")

            start_time = time.time()
            upload_result = self.api.upload_file(
                file_path, folder_id=version_id,
                progress_callback=self._make_progress_callback('gofile')
            )
            upload_time = time.time() - start_time

            upload_speed_mbps = (file_size_bytes * 8) / (upload_time * 1_000_000)
            self.log(f"Upload complete! - {upload_time:.1f}s, {upload_speed_mbps:.2f} Mbps", "SUCCESS", host="gofile")

            self._verify_upload_md5(file_path, upload_result)

            # Make folder public and get link
            self.log("Making folder public...", host="gofile")
            if self.make_folder_public(version_id):
                self.log("Folder is now public", "SUCCESS", host="gofile")

            self.log("Getting public link...", host="gofile")
            link = self.get_folder_link(version_id)

            if link:
                self.log("Public link ready", "SUCCESS", host="gofile")
                self.log(f"Link: {link}", "SUCCESS", host="gofile")
                # Update link entry immediately (thread-safe GUI update)
                if self.gofile_link_entry:
                    self.root.after(0, lambda: self._update_link_entry(self.gofile_link_entry, link))
                # Update status to success
                self._update_status_emoji("gofile", "🟢")
                self.log("-" * 25, host="gofile")
                return link
            else:
                self.log("Could not retrieve public link", "ERROR", host="gofile")
                self._update_status_emoji("gofile", "🔴")
                self.log("-" * 25, host="gofile")
                return None

        except (RuntimeError, KeyError) as e:
            self.log(f"Upload failed: {e}", "ERROR", host="gofile")
            self._update_status_emoji("gofile", "🔴")
            self.log("-" * 25, host="gofile")
            return None
        except (OSError, IOError) as e:
            # File/permission errors that aren't network-related
            self.log(f"Upload failed: {e}", "ERROR", host="gofile")
            self._update_status_emoji("gofile", "🔴")
            self.log("-" * 25, host="gofile")
            return None

    @staticmethod
    def _compute_md5(file_path: str) -> Optional[str]:
        """
        Compute a file's MD5 digest.

        Reads in chunks so a multi-gigabyte APK is not loaded into memory.

        Returns
        -------
        Optional[str]
            Lowercase hex digest, or None if the file could not be read.
        """
        digest = hashlib.md5()
        try:
            with open(file_path, 'rb') as handle:
                for chunk in iter(lambda: handle.read(MD5_CHUNK_SIZE), b''):
                    digest.update(chunk)
        except OSError:
            return None
        return digest.hexdigest()

    def _verify_upload_md5(self, file_path: str, upload_result: Optional[Dict]) -> None:
        """
        Compare Gofile's reported MD5 against the local file.

        Catches corruption in transit that a successful HTTP status would not.
        A mismatch is reported but the link is still published: the user
        decides whether to re-upload.
        """
        if not isinstance(upload_result, dict):
            return

        remote_md5 = upload_result.get('md5')
        if not remote_md5:
            return

        local_md5 = self._compute_md5(file_path)
        if not local_md5:
            self.log("Could not read file to verify MD5", "WARNING", host="gofile")
            return

        if local_md5.lower() == remote_md5.lower():
            self.log("MD5 verified", "SUCCESS", host="gofile")
        else:
            self.log(
                f"MD5 MISMATCH - file may be corrupted "
                f"(local {local_md5[:12]}..., remote {remote_md5[:12]}...)",
                "ERROR", host="gofile"
            )

    def _upload_to_buzzheavier(self, file_path: str, package: str, _version: str, full_name: str) -> Optional[str]:
        """
        Upload file to Buzzheavier.

        Parameters
        ----------
        file_path : str
            Path to the file
        package : str
            Package name
        _version : str
            Version string
        full_name : str
            Full folder name (package-version-suffix)

        Returns
        -------
        Optional[str]
            Public link if successful, None otherwise
        """
        try:
            # Get or create parent folder
            parent_id = self.buzzheavier_folder_structure.get(package)

            if not parent_id:
                reused_existing = False
                self.log(f"Creating parent folder: {package}", host="buzzheavier")
                try:
                    result = self.buzzheavier_api.create_folder(self.buzzheavier_root_folder_id, package)
                    parent_id = result.get('id')
                except BuzzheavierHTTPError as e:
                    if "409" in str(e) or "Conflict" in str(e):
                        self.log("Parent folder already exists; reusing it", "WARNING", host="buzzheavier")
                        root_content = self.buzzheavier_api.get_content(self.buzzheavier_root_folder_id)
                        children = root_content.get('children', [])
                        existing = next((c for c in children if c.get('isDirectory') and c.get('name') == package), None)
                        parent_id = existing.get('id') if existing else None
                        reused_existing = parent_id is not None
                    else:
                        raise

                if parent_id:
                    self.buzzheavier_folder_structure[package] = parent_id
                    if reused_existing:
                        self.log("Using existing parent folder", "SUCCESS", host="buzzheavier")
                    else:
                        self.log("Created parent folder", "SUCCESS", host="buzzheavier")
                else:
                    self.log("Failed to create parent folder", "ERROR", host="buzzheavier")
                    return None
            else:
                self.log(f"Found parent folder: {package}", host="buzzheavier")

            version_folder_name = self._normalize_version_folder_name(full_name)
            candidate_names = [version_folder_name]
            if full_name != version_folder_name:
                candidate_names.append(full_name)

            # Check if version folder exists (prefer normalized, but allow legacy)
            parent_contents = self.buzzheavier_api.get_content(parent_id)
            children = parent_contents.get('children', [])
            version_folder = next(
                (
                    c for c in children
                    if c.get('isDirectory') and c.get('name') in candidate_names
                ),
                None
            )

            if version_folder:
                version_id = version_folder.get('id')
                self.log(f"Version folder already exists: {version_folder_name}", host="buzzheavier")
            else:
                self.log(f"Creating version folder: {version_folder_name}", host="buzzheavier")
                result = self.buzzheavier_api.create_folder(parent_id, version_folder_name)
                version_id = result.get('id')
                if not version_id:
                    self.log("Failed to create version folder", "ERROR", host="buzzheavier")
                    return None

            # Upload file
            file_size_bytes = os.path.getsize(file_path)
            file_size_mb = file_size_bytes / (1024 * 1024)
            self.log(f"Uploading - {round(file_size_mb)} MB...", host="buzzheavier")

            start_time = time.time()
            result = self.buzzheavier_api.upload_file(
                file_path, parent_id=version_id,
                progress_callback=self._make_progress_callback('buzzheavier')
            )
            upload_time = time.time() - start_time

            upload_speed_mbps = (file_size_bytes * 8) / (upload_time * 1_000_000)
            self.log(f"Upload complete! - {upload_time:.1f}s, {upload_speed_mbps:.2f} Mbps", "SUCCESS", host="buzzheavier")

            # Get file ID and generate public link
            file_id = result.get('id')
            if file_id:
                link = f"https://buzzheavier.com/{file_id}"
                self.log("Public link ready", "SUCCESS", host="buzzheavier")
                self.log(f"Link: {link}", "SUCCESS", host="buzzheavier")
                # Update link entry immediately (thread-safe GUI update)
                if self.buzzheavier_link_entry:
                    self.root.after(0, lambda: self._update_link_entry(self.buzzheavier_link_entry, link))
                # Update status to success
                self._update_status_emoji("buzzheavier", "🟢")
                self.log("-" * 25, host="buzzheavier")
                return link
            else:
                self.log("Could not get file ID", "ERROR", host="buzzheavier")
                self._update_status_emoji("buzzheavier", "🔴")
                self.log("-" * 25, host="buzzheavier")
                return None

        except NetworkException as e:
            # Network errors after all retries exhausted
            self.log(f"Upload failed after retries: {e}", "ERROR", host="buzzheavier")
            self._update_status_emoji("buzzheavier", "🔴")
            self.log("-" * 25, host="buzzheavier")
            return None
        except (RuntimeError, KeyError) as e:
            self.log(f"Upload failed: {e}", "ERROR", host="buzzheavier")
            self._update_status_emoji("buzzheavier", "🔴")
            self.log("-" * 25, host="buzzheavier")
            return None
        except (OSError, IOError) as e:
            # File/permission errors that aren't network-related
            self.log(f"Upload failed: {e}", "ERROR", host="buzzheavier")
            self._update_status_emoji("buzzheavier", "🔴")
            self.log("-" * 25, host="buzzheavier")
            return None

    def _upload_to_pixeldrain(self, file_path: str, _package: str, _version: str, _full_name: str) -> Optional[str]:
        """
        Upload file to Pixeldrain (flat structure).

        Parameters
        ----------
        file_path : str
            Path to the file
        _package : str
            Package name (unused - for future list organization)
        _version : str
            Version string (unused - for future list organization)
        _full_name : str
            Full folder name (unused - for future list organization)

        Returns
        -------
        Optional[str]
            Public link if successful, None otherwise
        """
        try:
            file_size_bytes = os.path.getsize(file_path)
            file_size_mb = file_size_bytes / (1024 * 1024)
            self.log(f"Uploading - {round(file_size_mb)} MB...", host="pixeldrain")

            start_time = time.time()
            result = self.pixeldrain_api.upload_file(
                file_path,
                progress_callback=self._make_progress_callback('pixeldrain')
            )
            upload_time = time.time() - start_time

            upload_speed_mbps = (file_size_bytes * 8) / (upload_time * 1_000_000)
            self.log(f"Upload complete! - {upload_time:.1f}s, {upload_speed_mbps:.2f} Mbps", "SUCCESS", host="pixeldrain")

            # Get file ID and generate public link
            file_id = result.get('id')
            if file_id:
                link = f"https://pixeldrain.com/u/{file_id}"
                self.log("Public link ready", "SUCCESS", host="pixeldrain")
                self.log(f"Link: {link}", "SUCCESS", host="pixeldrain")
                # Update link entry immediately (thread-safe GUI update)
                if self.pixeldrain_link_entry:
                    self.root.after(0, lambda: self._update_link_entry(self.pixeldrain_link_entry, link))
                # Update status to success
                self._update_status_emoji("pixeldrain", "🟢")
                self.log("-" * 25, host="pixeldrain")
                return link
            else:
                self.log("Could not get file ID", "ERROR", host="pixeldrain")
                self._update_status_emoji("pixeldrain", "🔴")
                self.log("-" * 25, host="pixeldrain")
                return None

        except PixeldrainNetworkException as e:
            self.log(f"Network error: {e}", "ERROR", host="pixeldrain")
            self._update_status_emoji("pixeldrain", "🔴")
            self.log("-" * 25, host="pixeldrain")
            return None
        except (OSError, IOError) as e:
            self.log(f"File error: {e}", "ERROR", host="pixeldrain")
            self._update_status_emoji("pixeldrain", "🔴")
            self.log("-" * 25, host="pixeldrain")
            return None
        except Exception as e:  # pylint: disable=broad-except
            self.log(f"Unexpected error: {e}", "ERROR", host="pixeldrain")
            self._update_status_emoji("pixeldrain", "🔴")
            return None

    def _upload_to_apkadmin(self, file_path: str, _package: str, _version: str, _full_name: str) -> Optional[str]:
        """
        Upload file to Apkadmin (flat structure, no folder organization).

        Parameters
        ----------
        file_path : str
            Path to the file
        _package : str
            Unused — Apkadmin has no folder API
        _version : str
            Unused — Apkadmin has no folder API
        _full_name : str
            Unused — Apkadmin has no folder API

        Returns
        -------
        Optional[str]
            Public link if successful, None otherwise
        """
        try:
            file_size_bytes = os.path.getsize(file_path)
            file_size_mb = file_size_bytes / (1024 * 1024)
            self.log(f"Uploading - {round(file_size_mb)} MB...", host="apkadmin")

            start_time = time.time()
            result = self.apkadmin_api.upload_file(
                file_path,
                progress_callback=self._make_progress_callback('apkadmin')
            )
            upload_time = time.time() - start_time

            upload_speed_mbps = (file_size_bytes * 8) / (upload_time * 1_000_000)
            self.log(f"Upload complete! - {upload_time:.1f}s, {upload_speed_mbps:.2f} Mbps", "SUCCESS", host="apkadmin")

            link = result.get("url")
            if link:
                self.log("Public link ready", "SUCCESS", host="apkadmin")
                self.log(f"Link: {link}", "SUCCESS", host="apkadmin")
                if self.apkadmin_link_entry:
                    self.root.after(0, lambda: self._update_link_entry(self.apkadmin_link_entry, link))
                self._update_status_emoji("apkadmin", "🟢")
                self.log("-" * 25, host="apkadmin")
                return link
            else:
                self.log("Could not get file URL from response", "ERROR", host="apkadmin")
                self._update_status_emoji("apkadmin", "🔴")
                self.log("-" * 25, host="apkadmin")
                return None

        except ApkadminAuthError as e:
            self.log(f"Auth error: {e}", "ERROR", host="apkadmin")
            self._update_status_emoji("apkadmin", "🔴")
            self.log("-" * 25, host="apkadmin")
            return None
        except ApkadminNetworkException as e:
            self.log(f"Network error: {e}", "ERROR", host="apkadmin")
            self._update_status_emoji("apkadmin", "🔴")
            self.log("-" * 25, host="apkadmin")
            return None
        except ApkadminAPIError as e:
            self.log(f"Upload failed: {e}", "ERROR", host="apkadmin")
            self._update_status_emoji("apkadmin", "🔴")
            self.log("-" * 25, host="apkadmin")
            return None
        except (OSError, IOError) as e:
            self.log(f"File error: {e}", "ERROR", host="apkadmin")
            self._update_status_emoji("apkadmin", "🔴")
            self.log("-" * 25, host="apkadmin")
            return None
        except Exception as e:  # pylint: disable=broad-except
            self.log(f"Unexpected error: {e}", "ERROR", host="apkadmin")
            self._update_status_emoji("apkadmin", "🔴")
            return None

    # ===== RETRY =====

    def retry_gofile(self) -> None:
        """Retry upload to Gofile for the last uploaded file."""
        if not self.api or not self.root_folder_id:
            ready_error = "Gofile not initialized"
        else:
            ready_error = None
        self._retry_host("gofile", "Gofile", ready_error,
                         self.gofile_link_entry, self._upload_to_gofile)

    def retry_buzzheavier(self) -> None:
        """Retry upload to Buzzheavier for the last uploaded file."""
        if not self.buzzheavier_api or not self.buzzheavier_root_folder_id:
            ready_error = "Buzzheavier not initialized"
        else:
            ready_error = None
        self._retry_host("buzzheavier", "Buzzheavier", ready_error,
                         self.buzzheavier_link_entry, self._upload_to_buzzheavier)

    def retry_pixeldrain(self) -> None:
        """Retry upload to Pixeldrain for the last uploaded file."""
        ready_error = None if self.pixeldrain_api else "Pixeldrain not initialized"
        self._retry_host("pixeldrain", "Pixeldrain", ready_error,
                         self.pixeldrain_link_entry, self._upload_to_pixeldrain)

    def retry_apkadmin(self) -> None:
        """Retry upload to Apkadmin for the last uploaded file."""
        ready_error = None if self.apkadmin_api else "Apkadmin not initialized"
        self._retry_host("apkadmin", "Apkadmin", ready_error,
                         self.apkadmin_link_entry, self._upload_to_apkadmin)

    def _retry_host(self, host: str, label: str, ready_error: Optional[str],
                    link_entry, upload_method) -> None:
        """
        Re-run the last upload for one host on a background thread.

        Parameters
        ----------
        host : str
            Log column key for this host.
        label : str
            Display name used in messages.
        ready_error : Optional[str]
            Message to log if the host is not connected; None when it is.
        link_entry : tkinter.Entry
            Entry to blank before retrying.
        upload_method : Callable
            The host's _upload_to_* method.
        """
        if not self.last_upload_file_path or not self.last_upload_parsed_info:
            self.log("No previous upload to retry", "WARNING", host=host)
            return

        status = self.last_upload_status.get(host)
        if status is True:
            self.log(f"Last {label} upload succeeded; nothing to retry", "INFO", host=host)
            return
        if status is None:
            self.log(f"{label} upload was skipped; nothing to retry", "INFO", host=host)
            return

        if ready_error:
            self.log(ready_error, "ERROR", host=host)
            return

        self.log(f"Retrying {label} upload...", "INFO", host=host)

        if link_entry:
            link_entry.delete(0, tk.END)
        self._update_status_emoji(host, "⏳")

        parsed = self.last_upload_parsed_info
        file_path = self.last_upload_file_path

        def retry_thread():
            link = upload_method(
                file_path,
                parsed['package'],
                parsed['version'],
                parsed['full_name']
            )
            if not link:
                self.log("Retry failed", "ERROR", host=host)

        threading.Thread(target=retry_thread, daemon=True).start()
