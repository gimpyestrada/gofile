"""
Gofile Drag & Drop Uploader
A GUI application that accepts drag-and-drop APK files and uploads them to the appropriate
Gofile folder structure, then returns a public link.
"""

import os
import re
import sys
import json
import time
import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, Optional
import threading
from gofile_api import GofileAPI
from buzzheavier_api import BuzzheavierAPI, NetworkException
from config_loader import load_config


class DragDropUploader:
    """Drag and drop uploader with GUI."""

    # Cache file path - use user's local appdata for persistence
    @staticmethod
    def _get_cache_dir():
        """Get the cache directory path that works for both script and executable."""
        # Try to get executable directory first (for PyInstaller)
        if getattr(sys, 'frozen', False):
            # Running as compiled executable
            app_dir = os.path.dirname(sys.executable)
        else:
            # Running as script
            app_dir = os.path.dirname(os.path.abspath(__file__))
        return app_dir
    
    CACHE_EXPIRY_HOURS = 24

    # Window dimensions
    NORMAL_MODE_WIDTH = 900
    NORMAL_MODE_HEIGHT = 650
    MINI_MODE_WIDTH = 200
    MINI_MODE_HEIGHT = 320

    # API delays (seconds)
    API_FOLDER_CREATE_DELAY = 2
    API_FOLDER_UPDATE_DELAY = 1

    def __init__(self):
        """Initialize the uploader."""
        # Set cache file path
        self.FOLDER_CACHE_FILE = os.path.join(self._get_cache_dir(), "folder_structure_cache.json")
        # Gofile API
        self.api = None
        self.root_folder_id = None
        self.folder_structure = {}  # package -> parent_folder_id
        
        # Buzzheavier API
        self.buzzheavier_api = None
        self.buzzheavier_root_folder_id = None
        self.buzzheavier_folder_structure = {}  # package -> parent_folder_id
        
        # Pixeldrain API
        self.pixeldrain_api = None
        self.pixeldrain_folder_structure = {}  # package -> list_id
        
        # Cache and config
        self.cache_data = None
        self.config = None

        # Thread safety
        self._ready_lock = threading.Lock()
        self._is_ready = False
        self._gofile_ready = False
        self._buzzheavier_ready = False
        self._pixeldrain_ready = False

        # Upload tracking for retry functionality
        self.last_upload_file_path = None
        self.last_upload_parsed_info = None
        
        # Host toggle settings
        self.gofile_enabled = None
        self.buzzheavier_enabled = None
        self.pixeldrain_enabled = None
        
        # Pixeldrain-specific state
        self.pixeldrain_api = None
        self.pixeldrain_folder_structure = {}
        self.pixeldrain_ready = False

        # GUI components
        self.root = None
        self.log_text = None  # Keep for backward compatibility (maps to gofile_log_text)
        self.gofile_log_text = None
        self.buzzheavier_log_text = None
        self.pixeldrain_log_text = None
        self.status_label = None
        self.gofile_status_label = None
        self.buzzheavier_status_label = None
        self.pixeldrain_status_label = None
        self.link_entry = None  # Keep for backward compatibility (maps to gofile_link_entry)
        self.gofile_link_entry = None
        self.buzzheavier_link_entry = None
        self.pixeldrain_link_entry = None
        self.is_ready = False
        self.mini_mode = None  # Will be set after root window created

        # Store frames for show/hide
        self.main_frame = None
        self.drop_frame = None
        self.link_frame = None
        self.log_frame = None
        self.mini_frame = None
        self.mini_status_label = None
        
        # Store log column widgets for dynamic visibility
        self.gofile_log_label = None
        self.buzzheavier_log_label = None
        self.pixeldrain_log_label = None
        
        # Store button frames for dynamic visibility
        self.gofile_buttons_frame = None
        self.buzzheavier_buttons_frame = None
        self.pixeldrain_buttons_frame = None
        
        # Store status indicator labels (separate from name labels)
        self.gofile_status_indicator = None
        self.buzzheavier_status_indicator = None
        self.pixeldrain_status_indicator = None
        
        # Store status frames (contain indicator + name)
        self.gofile_status_frame = None
        self.buzzheavier_status_frame = None
        self.pixeldrain_status_frame = None
        
        # Mini mode indicators (initialized in run())
        self.mini_gofile_indicator = None
        self.mini_buzzheavier_indicator = None
        self.mini_pixeldrain_indicator = None
        self.buzzheavier_status_frame = None
        self.pixeldrain_status_frame = None

    def log(self, message: str, level: str = "INFO", host: str = "both") -> None:
        """
        Log a message to both the GUI and console.

        Parameters
        ----------
        message : str
            The message to log.
        level : str, optional
            The log level for color coding. Valid values are 'INFO',
            'SUCCESS', 'ERROR', 'WARNING'. Default is 'INFO'.
        host : str, optional
            Which host log to write to: 'gofile', 'buzzheavier', 'pixeldrain', or 'both'.
            Default is 'both'.
        """
        timestamp = datetime.now().strftime("%H:%M:%S")
        formatted_msg = f"[{timestamp}] {message}\n"

        print(message)

        # Helper function to add message to a log widget
        def add_to_log(log_widget):
            if log_widget:
                log_widget.insert(tk.END, formatted_msg)
                log_widget.see(tk.END)

                # Color coding
                if level == "SUCCESS":
                    line_start = log_widget.index("end-2c linestart")
                    line_end = log_widget.index("end-1c lineend")
                    log_widget.tag_add("success", line_start, line_end)
                elif level == "ERROR":
                    line_start = log_widget.index("end-2c linestart")
                    line_end = log_widget.index("end-1c lineend")
                    log_widget.tag_add("error", line_start, line_end)

        # Route to appropriate log(s)
        if host == "gofile" or host == "both":
            add_to_log(self.gofile_log_text)
        if host == "buzzheavier" or host == "both":
            add_to_log(self.buzzheavier_log_text)
        if host == "pixeldrain":
            add_to_log(self.pixeldrain_log_text)
        
        # Backward compatibility: if old log_text exists and is different from gofile_log_text
        if self.log_text and self.log_text != self.gofile_log_text:
            add_to_log(self.log_text)

    @property
    def is_ready(self) -> bool:
        """Thread-safe getter for ready state."""
        with self._ready_lock:
            return self._is_ready

    @is_ready.setter
    def is_ready(self, value: bool) -> None:
        """Thread-safe setter for ready state."""
        with self._ready_lock:
            self._is_ready = value

    def update_status(self, message: str) -> None:
        """Update status label in both normal and mini mode."""
        if self.status_label:
            self.status_label.config(text=message)
        if hasattr(self, 'mini_status_label') and self.mini_status_label:
            core_status = message.split(' - ')[-1] if ' - ' in message else message
            self.mini_status_label.config(text=core_status)

    def save_host_settings(self) -> None:
        """Save enabled host settings to config.json."""
        if self.config and self.gofile_enabled and self.buzzheavier_enabled and self.pixeldrain_enabled:
            try:
                self.config.update('gofile_enabled', self.gofile_enabled.get())
                self.config.update('buzzheavier_enabled', self.buzzheavier_enabled.get())
                self.config.update('pixeldrain_enabled', self.pixeldrain_enabled.get())
                
                self.update_visibility()
            except (IOError, OSError) as e:
                print(f"Error saving host settings to file: {e}")
            except (AttributeError, KeyError, ValueError) as e:
                print(f"Error with config data: {e}")
            except Exception as e:  # pylint: disable=broad-except
                print(f"Unexpected error saving host settings: {e}")
    
    def load_host_settings(self) -> None:
        """Load enabled host settings from config.json."""
        if self.config:
            # Default: gofile only if no settings exist
            gofile_enabled = self.config.get('gofile_enabled')
            if gofile_enabled is None:
                gofile_enabled = True
            
            buzzheavier_enabled = self.config.get('buzzheavier_enabled', False)
            pixeldrain_enabled = self.config.get('pixeldrain_enabled', False)
            
            if self.gofile_enabled:
                self.gofile_enabled.set(gofile_enabled)
            if self.buzzheavier_enabled:
                self.buzzheavier_enabled.set(buzzheavier_enabled)
            if self.pixeldrain_enabled:
                self.pixeldrain_enabled.set(pixeldrain_enabled)
    
    def show_settings_menu(self) -> None:
        """Show settings menu with host enable/disable checkboxes."""
        menu = tk.Menu(self.root, tearoff=0)
        
        menu.add_checkbutton(
            label="Gofile",
            variable=self.gofile_enabled,
            command=self._validate_and_save_host_settings
        )
        menu.add_checkbutton(
            label="Buzzheavier",
            variable=self.buzzheavier_enabled,
            command=self._validate_and_save_host_settings
        )
        menu.add_checkbutton(
            label="Pixeldrain",
            variable=self.pixeldrain_enabled,
            command=self._validate_and_save_host_settings
        )
        
        # Display menu at mouse position
        try:
            menu.tk_popup(self.root.winfo_pointerx(), self.root.winfo_pointery())
        finally:
            menu.grab_release()
    
    def _validate_and_save_host_settings(self) -> None:
        """Validate at least one host is enabled before saving."""
        if not (self.gofile_enabled.get() or self.buzzheavier_enabled.get() or self.pixeldrain_enabled.get()):
            messagebox.showwarning(
                "Invalid Settings",
                "At least one file host must be enabled."
            )
            self.gofile_enabled.set(True)
        
        self.save_host_settings()
    
    def update_visibility(self) -> None:
        """Update visibility of log columns and link rows based on enabled hosts."""
        if not self.log_frame or not self.link_frame:
            return
        
        # Get enabled hosts in order
        enabled_hosts = []
        if self.gofile_enabled.get():
            enabled_hosts.append(('gofile', self.gofile_log_label, self.gofile_log_text, 
                                 self.gofile_status_frame, self.gofile_link_entry))
        if self.buzzheavier_enabled.get():
            enabled_hosts.append(('buzzheavier', self.buzzheavier_log_label, self.buzzheavier_log_text,
                                 self.buzzheavier_status_frame, self.buzzheavier_link_entry))
        if self.pixeldrain_enabled.get():
            enabled_hosts.append(('pixeldrain', self.pixeldrain_log_label, self.pixeldrain_log_text,
                                 self.pixeldrain_status_frame, self.pixeldrain_link_entry))
        
        # Hide all log widgets
        if self.gofile_log_label:
            self.gofile_log_label.grid_remove()
        if self.gofile_log_text:
            self.gofile_log_text.grid_remove()
        if self.buzzheavier_log_label:
            self.buzzheavier_log_label.grid_remove()
        if self.buzzheavier_log_text:
            self.buzzheavier_log_text.grid_remove()
        if self.pixeldrain_log_label:
            self.pixeldrain_log_label.grid_remove()
        if self.pixeldrain_log_text:
            self.pixeldrain_log_text.grid_remove()
        
        # Hide all link rows
        if self.gofile_status_frame:
            self.gofile_status_frame.grid_remove()
        if self.gofile_link_entry:
            self.gofile_link_entry.grid_remove()
        if self.gofile_buttons_frame:
            self.gofile_buttons_frame.grid_remove()
            
        if self.buzzheavier_status_frame:
            self.buzzheavier_status_frame.grid_remove()
        if self.buzzheavier_link_entry:
            self.buzzheavier_link_entry.grid_remove()
        if self.buzzheavier_buttons_frame:
            self.buzzheavier_buttons_frame.grid_remove()
            
        if self.pixeldrain_status_frame:
            self.pixeldrain_status_frame.grid_remove()
        if self.pixeldrain_link_entry:
            self.pixeldrain_link_entry.grid_remove()
        if self.pixeldrain_buttons_frame:
            self.pixeldrain_buttons_frame.grid_remove()
        
        # Reset column weights
        for i in range(3):
            self.log_frame.columnconfigure(i, weight=0)
        
        # Show enabled logs and links with new positions
        for row, (name, label_widget, log_widget, status_frame, link_entry) in enumerate(enabled_hosts):
            # Show link row
            if status_frame:
                status_frame.grid(row=row, column=0, sticky=tk.W, padx=(0, 5), pady=(5, 0) if row > 0 else (0, 0))
            if link_entry:
                link_entry.grid(row=row, column=1, sticky=(tk.W, tk.E), padx=(0, 5), pady=(5, 0) if row > 0 else (0, 0))
            
            # Show button frame
            if name == 'gofile' and self.gofile_buttons_frame:
                self.gofile_buttons_frame.grid(row=row, column=2, pady=(5, 0) if row > 0 else (0, 0))
            elif name == 'buzzheavier' and self.buzzheavier_buttons_frame:
                self.buzzheavier_buttons_frame.grid(row=row, column=2, pady=(5, 0) if row > 0 else (0, 0))
            elif name == 'pixeldrain' and self.pixeldrain_buttons_frame:
                self.pixeldrain_buttons_frame.grid(row=row, column=2, pady=(5, 0) if row > 0 else (0, 0))
        
        # Show enabled logs with new column positions
        for col, (name, label_widget, log_widget, _status_label, link_entry) in enumerate(enabled_hosts):
            if label_widget:
                label_widget.grid(row=0, column=col, sticky=tk.W, pady=(0, 5), padx=(0, 5) if col < len(enabled_hosts)-1 else (0, 0))
            if log_widget:
                log_widget.grid(row=1, column=col, sticky=(tk.W, tk.E, tk.N, tk.S), 
                              padx=(0, 5) if col < len(enabled_hosts)-1 else (0, 0))
            self.log_frame.columnconfigure(col, weight=1)
    
    def parse_apk_filename(self, filename: str) -> Optional[Dict[str, str]]:
        """
        Parse APK filename to extract package name and version.

        Parameters
        ----------
        filename : str
            The APK filename to parse (e.g., 'com.app.name-1.0-release.apk').

        Returns
        -------
        Optional[Dict[str, str]]
            Dictionary containing 'package', 'version', 'full_name', and
            'filename' keys if parsing succeeds, None otherwise.
        """
        if not filename.lower().endswith('.apk'):
            return None

        name_without_ext = filename[:-4]

        # Pattern: com.company.app-version-suffix
        match = re.match(r'^(.+?)-([0-9]+(?:\.[0-9]+)*(?:[a-zA-Z0-9\+\.]*))(?:-.*)?$', name_without_ext)

        if match:
            package = match.group(1)
            version = match.group(2)
            return {
                'package': package,
                'version': version,
                'full_name': name_without_ext,
                'filename': filename
            }

        return None

    def save_folder_cache(self, host: str, root_folder_id: str, folders: Dict) -> None:
        """
        Save folder structure to cache for a specific host.
        
        Parameters
        ----------
        host : str
            The host name ('gofile' or 'buzzheavier').
        root_folder_id : str
            The root folder ID for this host.
        folders : Dict
            The folder structure data to cache.
        """
        cache_path = Path(self.FOLDER_CACHE_FILE)
        
        # Load existing cache or create new structure
        if cache_path.exists():
            try:
                with open(cache_path, 'r', encoding='utf-8') as f:
                    cache_data = json.load(f)
            except (json.JSONDecodeError, OSError, IOError):
                cache_data = {}
        else:
            cache_data = {}
        
        # Update host-specific data
        cache_data[host] = {
            'timestamp': datetime.now().isoformat(),
            'root_folder_id': root_folder_id,
            'folders': folders
        }
        
        # Save to file
        try:
            with open(cache_path, 'w', encoding='utf-8') as f:
                json.dump(cache_data, f, indent=2, ensure_ascii=False)
            self.log(f"Saved {host} cache with {len(folders)} folders", "SUCCESS", host=host)
        except (OSError, IOError) as e:
            self.log(f"Error saving {host} cache: {e}", "ERROR", host=host)

    def load_folder_cache(self) -> Optional[Dict]:
        """
        Load cached folder structure.
        Supports both old single-host and new dual-host formats.
        Migrates old format to new format automatically.
        """
        cache_path = Path(self.FOLDER_CACHE_FILE)

        if not cache_path.exists():
            return None

        try:
            with open(cache_path, 'r', encoding='utf-8') as f:
                cache_data = json.load(f)

            # Check if this is old format (has 'timestamp' at root level)
            if 'timestamp' in cache_data and 'gofile' not in cache_data:
                self.log("Migrating old cache format to dual-host structure...")
                # Migrate: wrap old data under 'gofile' key
                old_data = cache_data.copy()
                cache_data = {
                    'gofile': old_data
                }
                # Save migrated format
                try:
                    with open(cache_path, 'w', encoding='utf-8') as f:
                        json.dump(cache_data, f, indent=2, ensure_ascii=False)
                    self.log("Cache migration complete", "SUCCESS")
                except (OSError, IOError) as e:
                    self.log(f"Warning: Could not save migrated cache: {e}", "WARNING")

            return cache_data

        except (json.JSONDecodeError, OSError, IOError) as e:
            self.log(f"Error loading cache: {e}", "ERROR")
            return None

    def build_folder_structure_for_host(self, host: str, api, root_folder_id: str, folder_structure_dict: Dict) -> None:
        """
        Build folder structure for a specific host.
        
        Parameters
        ----------
        host : str
            The host name ('gofile' or 'buzzheavier').
        api : object
            The API instance (GofileAPI or BuzzheavierAPI).
        root_folder_id : str
            The root folder ID for this host.
        folder_structure_dict : Dict
            The dictionary to populate with package -> folder_id mappings.
        """
        # Check if we have valid cached data for this host
        if self.cache_data and host in self.cache_data:
            host_cache = self.cache_data[host]
            cache_time = datetime.fromisoformat(host_cache.get('timestamp', ''))
            cache_age = datetime.now() - cache_time
            
            # Validate cache
            if (cache_age <= timedelta(hours=self.CACHE_EXPIRY_HOURS) and
                host_cache.get('root_folder_id') == root_folder_id):
                
                self.log(f"Using cached {host} folder structure", host=host)
                folders = host_cache.get('folders', {})
                
                for folder_id, folder_info in folders.items():
                    parsed = folder_info.get('parsed', {})
                    folder_type = parsed.get('type')
                    
                    if folder_type == 'parent':
                        package = parsed.get('package')
                        if package:
                            folder_structure_dict[package] = folder_id
                
                parent_count = len(folder_structure_dict)
                self.log(f"Loaded {parent_count} {host} parent folders from cache", "SUCCESS", host=host)
                return
        
        # No valid cache - scan the host
        self.log(f"No valid {host} cache - scanning folders...", host=host)
        
        try:
            root_contents = api.get_content(root_folder_id)
            children = root_contents.get('children', {})
            
            # Handle both dict format (Gofile) and list format (Buzzheavier)
            if isinstance(children, dict):
                # Gofile format: {id: {data}}
                folders = [
                    (cid, cdata) for cid, cdata in children.items()
                    if cdata.get('type') == 'folder' or cdata.get('isDirectory')
                ]
            else:
                # Buzzheavier format: [{id, name, isDirectory, ...}, ...]
                folders = [
                    (item.get('id'), item) for item in children
                    if item.get('isDirectory', False)
                ]
            
            # Build cache data structure
            cache_folders = {}
            
            for folder_id, folder_data in folders:
                folder_name = folder_data.get('name')
                
                # Check if it's a parent folder (package name without version)
                is_parent = (folder_name.count('.') >= 2 and '-' not in folder_name)
                if is_parent:
                    folder_structure_dict[folder_name] = folder_id
                    # Store in cache format
                    cache_folders[folder_id] = {
                        'name': folder_name,
                        'parsed': {
                            'type': 'parent',
                            'package': folder_name
                        }
                    }
            
            self.log(f"Found {len(folder_structure_dict)} {host} parent folders", "SUCCESS", host=host)
            
            # Save to cache
            self.save_folder_cache(host, root_folder_id, cache_folders)
            
        except (KeyError, ValueError, TypeError) as e:
            self.log(f"Error scanning {host} folders: {e}", "ERROR", host=host)

    def build_folder_structure(self) -> None:
        """Build mapping of package names to parent folder IDs for all hosts."""
        self.log("Building folder structure...")

        # Load cache (handles migration from old format)
        self.cache_data = self.load_folder_cache()

        # Build Gofile structure
        if self.api and self.root_folder_id:
            self.build_folder_structure_for_host(
                'gofile', 
                self.api, 
                self.root_folder_id, 
                self.folder_structure
            )
        
        # Build Buzzheavier structure (when Phase 4 is implemented)
        if self.buzzheavier_api and self.buzzheavier_root_folder_id:
            self.build_folder_structure_for_host(
                'buzzheavier',
                self.buzzheavier_api,
                self.buzzheavier_root_folder_id,
                self.buzzheavier_folder_structure
            )

    def create_parent_folder(self, package: str) -> Optional[str]:
        """
        Create a new parent folder for a package.

        Parameters
        ----------
        package : str
            The package name (e.g., 'com.example.app').

        Returns
        -------
        Optional[str]
            The parent folder ID if successful, None otherwise.
        """
        try:
            self.log(f"Creating parent folder: {package}")
            result = self.api.create_folder(self.root_folder_id, package)
            parent_id = result.get('id')
            self.log(f"Created parent folder with ID: {parent_id}", "SUCCESS")

            # Add to structure
            self.folder_structure[package] = parent_id

            time.sleep(self.API_FOLDER_CREATE_DELAY)
            return parent_id

        except (KeyError, ValueError, RuntimeError) as e:
            self.log(f"Error creating parent folder: {e}", "ERROR")
            return None

    def create_version_folder(self, parent_id: str, version_folder_name: str) -> Optional[str]:
        """
        Create or get version folder within a parent folder.

        Parameters
        ----------
        parent_id : str
            The parent folder ID where the version folder will be created.
        version_folder_name : str
            The name for the version folder (e.g., 'com.app.name-1.0-release').

        Returns
        -------
        Optional[str]
            The version folder ID if successful, None otherwise.
        """
        try:
            # Verify parent folder exists first
            self.log(f"Verifying parent folder ID: {parent_id}")
            parent_contents = self.api.get_content(parent_id)

            if not parent_contents or 'children' not in parent_contents:
                self.log(f"Parent folder not found or invalid: {parent_id}", "ERROR")
                return None

            children = parent_contents.get('children', {})

            # Check if version folder already exists
            for child_id, child_data in children.items():
                if child_data.get('type') == 'folder' and child_data.get('name') == version_folder_name:
                    self.log(f"Version folder already exists: {version_folder_name}")
                    return child_id

            # Create new version folder
            self.log(f"Creating version folder: {version_folder_name}")
            result = self.api.create_folder(parent_id, version_folder_name)
            version_id = result.get('id')

            if not version_id:
                self.log("Failed to get version folder ID from API response", "ERROR")
                return None

            self.log(f"Created version folder with ID: {version_id}", "SUCCESS")

            time.sleep(self.API_FOLDER_CREATE_DELAY)
            return version_id

        except (KeyError, ValueError, RuntimeError) as e:
            self.log(f"Error with version folder: {e}", "ERROR")
            warning_msg = ("This may indicate the parent folder no longer "
                          "exists or the cache is stale")
            self.log(warning_msg, "WARNING")
            return None

    def make_folder_public(self, folder_id: str) -> bool:
        """
        Make a folder publicly accessible.

        Parameters
        ----------
        folder_id : str
            The ID of the folder to make public.

        Returns
        -------
        bool
            True if the operation succeeded, False otherwise.
        """
        try:
            self.log("Setting folder to public...")
            self.api.update_content(folder_id, 'public', 'true')
            time.sleep(self.API_FOLDER_UPDATE_DELAY)
            return True
        except (KeyError, ValueError, RuntimeError) as e:
            self.log(f"Error making folder public: {e}", "ERROR")
            return False

    def get_folder_link(self, folder_id: str) -> Optional[str]:
        """
        Get the public download link for a folder.

        Parameters
        ----------
        folder_id : str
            The ID of the folder to get the link for.

        Returns
        -------
        Optional[str]
            The public link URL if available, None otherwise.
        """
        try:
            contents = self.api.get_content(folder_id)
            link = contents.get('link', '')
            code = contents.get('code', '')

            if link:
                return link
            elif code:
                return f"https://gofile.io/d/{code}"
            else:
                return None

        except (KeyError, ValueError, RuntimeError) as e:
            self.log(f"Error getting folder link: {e}", "ERROR")
            return None

    def _update_link_entry(self, entry_widget, link: str) -> None:
        """Thread-safe helper to update a link entry widget."""
        entry_widget.delete(0, tk.END)
        entry_widget.insert(0, link)

    def _update_status_emoji(self, host: str, emoji: str) -> None:
        """Thread-safe helper to update status indicator with color."""
        # Map emoji to colored text
        if emoji == "🟢":
            indicator = "✓"
            color = "green"
        elif emoji == "🔴":
            indicator = "✗"
            color = "red"
        else:  # "⏳"
            indicator = "⟳"
            color = "orange"
        
        if host == "gofile" and self.gofile_status_indicator:
            self.root.after(0, lambda: self.gofile_status_indicator.config(
                text=indicator, foreground=color))
            if hasattr(self, 'mini_gofile_indicator'):
                self.root.after(0, lambda: self.mini_gofile_indicator.config(
                    text=indicator, foreground=color))
        elif host == "buzzheavier" and self.buzzheavier_status_indicator:
            self.root.after(0, lambda: self.buzzheavier_status_indicator.config(
                text=indicator, foreground=color))
            if hasattr(self, 'mini_buzzheavier_indicator'):
                self.root.after(0, lambda: self.mini_buzzheavier_indicator.config(
                    text=indicator, foreground=color))
        elif host == "pixeldrain" and self.pixeldrain_status_indicator:
            self.root.after(0, lambda: self.pixeldrain_status_indicator.config(
                text=indicator, foreground=color))
            if hasattr(self, 'mini_pixeldrain_indicator'):
                self.root.after(0, lambda: self.mini_pixeldrain_indicator.config(
                    text=indicator, foreground=color))

    def _upload_to_gofile(self, file_path: str, package: str, _version: str, full_name: str) -> Optional[str]:
        """
        Upload file to Gofile.
        
        Parameters
        ----------
        file_path : str
            Path to the file
        package : str
            Package name
        version : str
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

            # Create or get version folder
            version_id = self.create_version_folder(parent_id, full_name)
            if not version_id:
                self.log("Failed to create/get version folder", "ERROR", host="gofile")
                return None

            # Upload file
            file_size_bytes = os.path.getsize(file_path)
            file_size_mb = file_size_bytes / (1024 * 1024)
            self.log(f"Uploading - {round(file_size_mb)} MB...", host="gofile")

            start_time = time.time()
            self.api.upload_file(file_path, folder_id=version_id)
            upload_time = time.time() - start_time

            upload_speed_mbps = (file_size_bytes * 8) / (upload_time * 1_000_000)
            self.log(f"Upload complete! - {upload_time:.1f}s, {upload_speed_mbps:.2f} Mbps", "SUCCESS", host="gofile")

            # Make folder public and get link
            self.log("Making folder public...", host="gofile")
            if self.make_folder_public(version_id):
                self.log("Folder is now public", "SUCCESS", host="gofile")

            self.log("Getting public link...", host="gofile")
            link = self.get_folder_link(version_id)

            if link:
                self.log("Public link ready", "SUCCESS", host="gofile")
                # Update link entry immediately (thread-safe GUI update)
                if self.gofile_link_entry:
                    self.root.after(0, lambda: self._update_link_entry(self.gofile_link_entry, link))
                # Update status to success
                self._update_status_emoji("gofile", "🟢")
                return link
            else:
                self.log("Could not retrieve public link", "ERROR", host="gofile")
                self._update_status_emoji("gofile", "🔴")
                return None

        except (RuntimeError, KeyError) as e:
            self.log(f"Upload failed: {e}", "ERROR", host="gofile")
            self._update_status_emoji("gofile", "🔴")
            return None
        except (OSError, IOError) as e:
            # File/permission errors that aren't network-related
            self.log(f"Upload failed: {e}", "ERROR", host="gofile")
            self._update_status_emoji("gofile", "🔴")
            return None

    def _upload_to_buzzheavier(self, file_path: str, package: str, _version: str, full_name: str) -> Optional[str]:
        """
        Upload file to Buzzheavier.
        
        Parameters
        ----------
        file_path : str
            Path to the file
        package : str
            Package name
        version : str
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
                self.log(f"Creating parent folder: {package}", host="buzzheavier")
                result = self.buzzheavier_api.create_folder(self.buzzheavier_root_folder_id, package)
                parent_id = result.get('id')
                if parent_id:
                    self.buzzheavier_folder_structure[package] = parent_id
                    self.log("Created parent folder", "SUCCESS", host="buzzheavier")
                else:
                    self.log("Failed to create parent folder", "ERROR", host="buzzheavier")
                    return None
            else:
                self.log(f"Found parent folder: {package}", host="buzzheavier")

            # Check if version folder exists
            parent_contents = self.buzzheavier_api.get_content(parent_id)
            children = parent_contents.get('children', [])
            version_folder = next((c for c in children if c.get('name') == full_name and c.get('isDirectory')), None)

            if version_folder:
                version_id = version_folder.get('id')
                self.log(f"Version folder already exists: {full_name}", host="buzzheavier")
            else:
                self.log(f"Creating version folder: {full_name}", host="buzzheavier")
                result = self.buzzheavier_api.create_folder(parent_id, full_name)
                version_id = result.get('id')
                if not version_id:
                    self.log("Failed to create version folder", "ERROR", host="buzzheavier")
                    return None

            # Upload file
            file_size_bytes = os.path.getsize(file_path)
            file_size_mb = file_size_bytes / (1024 * 1024)
            self.log(f"Uploading - {round(file_size_mb)} MB...", host="buzzheavier")

            start_time = time.time()
            result = self.buzzheavier_api.upload_file(file_path, parent_id=version_id)
            upload_time = time.time() - start_time

            upload_speed_mbps = (file_size_bytes * 8) / (upload_time * 1_000_000)
            self.log(f"Upload complete! - {upload_time:.1f}s, {upload_speed_mbps:.2f} Mbps", "SUCCESS", host="buzzheavier")

            # Get file ID and generate public link
            file_id = result.get('id')
            if file_id:
                link = f"https://buzzheavier.com/{file_id}"
                self.log("Public link ready", "SUCCESS", host="buzzheavier")
                # Update link entry immediately (thread-safe GUI update)
                if self.buzzheavier_link_entry:
                    self.root.after(0, lambda: self._update_link_entry(self.buzzheavier_link_entry, link))
                # Update status to success
                self._update_status_emoji("buzzheavier", "🟢")
                return link
            else:
                self.log("Could not get file ID", "ERROR", host="buzzheavier")
                self._update_status_emoji("buzzheavier", "🔴")
                return None

        except NetworkException as e:
            # Network errors after all retries exhausted
            self.log(f"Upload failed after retries: {e}", "ERROR", host="buzzheavier")
            self._update_status_emoji("buzzheavier", "🔴")
            return None
        except (RuntimeError, KeyError) as e:
            self.log(f"Upload failed: {e}", "ERROR", host="buzzheavier")
            self._update_status_emoji("buzzheavier", "🔴")
            return None
        except (OSError, IOError) as e:
            # File/permission errors that aren't network-related
            self.log(f"Upload failed: {e}", "ERROR", host="buzzheavier")
            self._update_status_emoji("buzzheavier", "🔴")
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
            result = self.pixeldrain_api.upload_file(file_path)
            upload_time = time.time() - start_time

            upload_speed_mbps = (file_size_bytes * 8) / (upload_time * 1_000_000)
            self.log(f"Upload complete! - {upload_time:.1f}s, {upload_speed_mbps:.2f} Mbps", "SUCCESS", host="pixeldrain")
            
            # Get file ID and generate public link
            file_id = result.get('id')
            if file_id:
                link = f"https://pixeldrain.com/u/{file_id}"
                self.log("Public link ready", "SUCCESS", host="pixeldrain")
                # Update link entry immediately (thread-safe GUI update)
                if self.pixeldrain_link_entry:
                    self.root.after(0, lambda: self._update_link_entry(self.pixeldrain_link_entry, link))
                # Update status to success
                self._update_status_emoji("pixeldrain", "🟢")
                return link
            else:
                self.log("Could not get file ID", "ERROR", host="pixeldrain")
                self._update_status_emoji("pixeldrain", "🔴")
                return None

        except NetworkException as e:
            self.log(f"Network error: {e}", "ERROR", host="pixeldrain")
            self._update_status_emoji("pixeldrain", "🔴")
            return None
        except (OSError, IOError) as e:
            self.log(f"File error: {e}", "ERROR", host="pixeldrain")
            self._update_status_emoji("pixeldrain", "🔴")
            return None
        except Exception as e:  # pylint: disable=broad-except
            self.log(f"Unexpected error: {e}", "ERROR", host="pixeldrain")
            self._update_status_emoji("pixeldrain", "🔴")
            return None

    def upload_file(self, file_path: str) -> None:
        """
        Upload an APK file to all enabled hosts in parallel.

        This method handles the entire upload workflow including parsing
        the filename, finding/creating folders, uploading the file, and
        generating public links for all hosts.

        Parameters
        ----------
        file_path : str
            The full path to the APK file to upload.
        """
        self.update_status("Processing...")
        
        # Clear all link entries
        if self.gofile_link_entry:
            self.gofile_link_entry.delete(0, tk.END)
        if self.buzzheavier_link_entry:
            self.buzzheavier_link_entry.delete(0, tk.END)
        if self.pixeldrain_link_entry:
            self.pixeldrain_link_entry.delete(0, tk.END)

        try:
            file_path = file_path.strip()

            # Validate file existence
            if not os.path.exists(file_path):
                self.log(f"File not found: {file_path}", "ERROR")
                self.update_status("Ready - Drop APK file here")
                return

            if not os.path.isfile(file_path):
                self.log(f"Not a file: {file_path}", "ERROR")
                self.update_status("Ready - Drop APK file here")
                return

            filename = os.path.basename(file_path)

            self.log("=" * 50)
            self.log(f"Processing: {filename}", "INFO")

            # Parse filename
            parsed = self.parse_apk_filename(filename)

            if not parsed:
                self.log("Could not parse APK filename", "ERROR")
                self.log("Expected format: package-version-suffix.apk", "ERROR")
                self.update_status("Ready - Drop APK file here")
                return

            package = parsed['package']
            version = parsed['version']
            full_name = parsed['full_name']

            self.log(f"Package: {package}")
            self.log(f"Version: {version}")

            # Store for retry functionality
            self.last_upload_file_path = file_path
            self.last_upload_parsed_info = parsed

            # Reset status emojis to uploading
            self._update_status_emoji("gofile", "⏳")
            self._update_status_emoji("buzzheavier", "⏳")
            self._update_status_emoji("pixeldrain", "⏳")

            # Upload to all hosts in parallel
            self.update_status("Uploading to enabled hosts...")

            gofile_link = None
            buzzheavier_link = None
            pixeldrain_link = None

            def upload_gofile():
                nonlocal gofile_link
                if self.gofile_enabled and not self.gofile_enabled.get():
                    self.log("Gofile upload skipped (disabled)", "WARNING", host="gofile")
                elif self.api and self.root_folder_id:
                    gofile_link = self._upload_to_gofile(file_path, package, version, full_name)

            def upload_buzzheavier():
                nonlocal buzzheavier_link
                if self.buzzheavier_enabled and not self.buzzheavier_enabled.get():
                    self.log("Buzzheavier upload skipped (disabled)", "WARNING", host="buzzheavier")
                elif self.buzzheavier_api and self.buzzheavier_root_folder_id:
                    buzzheavier_link = self._upload_to_buzzheavier(file_path, package, version, full_name)
            
            def upload_pixeldrain():
                nonlocal pixeldrain_link
                if self.pixeldrain_enabled and not self.pixeldrain_enabled.get():
                    self.log("Pixeldrain upload skipped (disabled)", "WARNING", host="pixeldrain")
                elif self.pixeldrain_api:
                    pixeldrain_link = self._upload_to_pixeldrain(file_path, package, version, full_name)

            # Start parallel uploads
            gofile_thread = threading.Thread(target=upload_gofile)
            buzzheavier_thread = threading.Thread(target=upload_buzzheavier)
            pixeldrain_thread = threading.Thread(target=upload_pixeldrain)

            gofile_thread.start()
            buzzheavier_thread.start()
            pixeldrain_thread.start()

            # Wait for all to complete
            gofile_thread.join()
            buzzheavier_thread.join()
            pixeldrain_thread.join()

            # Log completion summary with emoji status
            self.log("=" * 50)
            gofile_emoji = "🟢" if gofile_link else "🔴"
            buzzheavier_emoji = "🟢" if buzzheavier_link else "🔴"
            pixeldrain_emoji = "🟢" if pixeldrain_link else "🔴"
            
            success_count = sum([bool(gofile_link), bool(buzzheavier_link), bool(pixeldrain_link)])
            self.log(f"Gofile: {gofile_emoji} | Buzzheavier: {buzzheavier_emoji} | Pixeldrain: {pixeldrain_emoji}")
            
            if success_count >= 2:
                self.log(f"Upload complete to {success_count} hosts!", "SUCCESS")
            elif success_count == 1:
                self.log("Upload complete to one host (check logs)", "WARNING")
            else:
                self.log("Upload failed on both hosts", "ERROR")
            self.log("=" * 50)
            self.update_status("Ready - Drop APK file here")

        except (OSError, IOError, RuntimeError) as e:
            self.log(f"Upload failed: {e}", "ERROR")
            self.update_status("Ready - Drop APK file here")

    def on_drop(self, event) -> None:
        """Handle file drop event."""
        files = self.root.tk.splitlist(event.data)

        if files:
            file_path = files[0]

            # Remove curly braces if present (Windows)
            if file_path.startswith('{') and file_path.endswith('}'):
                file_path = file_path[1:-1]

            # Check if it's an APK file
            if not file_path.lower().endswith('.apk'):
                self.log("Only APK files are supported", "ERROR")
                return

            # Upload in separate thread to avoid blocking GUI
            upload_thread = threading.Thread(target=self.upload_file, args=(file_path,))
            upload_thread.daemon = True
            upload_thread.start()

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

            email = account_details.get('email')
            tier = account_details.get('tier')

            self.log("Connected to Gofile account", "SUCCESS", host="gofile")
            self.log(f"Email: {email}", host="gofile")
            self.log(f"Tier: {tier}", host="gofile")

            return True

        except (RuntimeError, KeyError, ValueError) as e:
            self.log(f"Failed to connect to Gofile: {e}", "ERROR", host="gofile")
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

        except (RuntimeError, KeyError, ValueError) as e:
            self.log(f"Failed to connect to Buzzheavier: {e}", "ERROR", host="buzzheavier")
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
            from pixeldrain_api import PixeldrainAPI
            
            self.pixeldrain_api = PixeldrainAPI(api_key=self.config.pixeldrain_api_key)

            # Get user files to verify connection
            user_data = self.pixeldrain_api.get_user_files()
            
            file_count = len(user_data.get('files', []))
            self.log("Connected to Pixeldrain account", "SUCCESS", host="pixeldrain")
            self.log(f"Files in account: {file_count}", host="pixeldrain")

            return True

        except NetworkException as e:
            self.log(f"Network error connecting to Pixeldrain: {e}", "ERROR", host="pixeldrain")
            return False
        except Exception as e:  # pylint: disable=broad-except
            self.log(f"Unexpected error connecting to Pixeldrain: {e}", "ERROR", host="pixeldrain")
            return False

    def initialize_api(self) -> None:
        """Initialize API connections for all hosts in parallel."""
        try:
            self.config = load_config()

            # Initialize all APIs in parallel
            gofile_thread = threading.Thread(target=lambda: setattr(self, '_gofile_ready', self._initialize_gofile()))
            buzzheavier_thread = threading.Thread(target=lambda: setattr(self, '_buzzheavier_ready', self._initialize_buzzheavier()))
            pixeldrain_thread = threading.Thread(target=lambda: setattr(self, '_pixeldrain_ready', self._initialize_pixeldrain()))

            self._gofile_ready = False
            self._buzzheavier_ready = False
            self._pixeldrain_ready = False

            gofile_thread.start()
            buzzheavier_thread.start()
            pixeldrain_thread.start()

            # Wait for all to complete
            gofile_thread.join()
            buzzheavier_thread.join()
            pixeldrain_thread.join()

            # Build folder structures for successful connections
            self.build_folder_structure()
            
            # Load host settings from config after GUI is ready
            if self.root:
                self.root.after(100, self.load_host_settings)
                # Update visibility after loading settings
                self.root.after(200, self.update_visibility)

            # Set ready if at least one host connected
            if self._gofile_ready or self._buzzheavier_ready or self._pixeldrain_ready:
                self.is_ready = True
                self.update_status("Ready - Drop APK file here")
                self.log("=" * 50)
                self.log("Ready! Drag and drop APK files here", "SUCCESS")
                self.log("=" * 50)
            else:
                self.update_status("Error - Check credentials")
                messagebox.showerror("Connection Error", 
                                   "Failed to connect to all file hosts.\n\n"
                                   "Check your config.json file.")

        except (RuntimeError, KeyError, ValueError, OSError, IOError) as e:
            self.log(f"Initialization error: {e}", "ERROR")
            self.update_status("Error - Check credentials")
            messagebox.showerror("Connection Error", f"Failed to initialize:\n{e}")

    def copy_link(self, host: str = "gofile") -> None:
        """
        Copy link to clipboard.
        
        Parameters
        ----------
        host : str
            Which host link to copy: 'gofile', 'buzzheavier', or 'pixeldrain'
        """
        if host == "gofile":
            link_entry = self.gofile_link_entry
        elif host == "buzzheavier":
            link_entry = self.buzzheavier_link_entry
        elif host == "pixeldrain":
            link_entry = self.pixeldrain_link_entry
        else:
            link_entry = None
            
        link = link_entry.get() if link_entry else ""
        if link:
            self.root.clipboard_clear()
            self.root.clipboard_append(link)
            self.log(f"{host.capitalize()} link copied to clipboard!", "SUCCESS", host=host)

    def copy_all_links(self) -> None:
        """
        Copy all enabled host links to clipboard, one per line.
        Uses base URL if no link is generated yet.
        """
        links = []
        
        if self.gofile_enabled and self.gofile_enabled.get():
            link = self.gofile_link_entry.get()
            links.append(link if link else "https://gofile.io")
        
        if self.buzzheavier_enabled and self.buzzheavier_enabled.get():
            link = self.buzzheavier_link_entry.get()
            links.append(link if link else "https://buzzheavier.com")
        
        if self.pixeldrain_enabled and self.pixeldrain_enabled.get():
            link = self.pixeldrain_link_entry.get()
            links.append(link if link else "https://pixeldrain.com")
        
        if links:
            all_links = "\n".join(links)
            self.root.clipboard_clear()
            self.root.clipboard_append(all_links)
            if self.gofile_enabled and self.gofile_enabled.get():
                self.log(f"Copied {len(links)} link(s) to clipboard!", "SUCCESS", host="gofile")
            elif self.buzzheavier_enabled and self.buzzheavier_enabled.get():
                self.log(f"Copied {len(links)} link(s) to clipboard!", "SUCCESS", host="buzzheavier")
            elif self.pixeldrain_enabled and self.pixeldrain_enabled.get():
                self.log(f"Copied {len(links)} link(s) to clipboard!", "SUCCESS", host="pixeldrain")

    def clear_all(self) -> None:
        """Clear all public links and reset logs."""
        if self.gofile_link_entry:
            self.gofile_link_entry.delete(0, tk.END)
        if self.buzzheavier_link_entry:
            self.buzzheavier_link_entry.delete(0, tk.END)
        if self.pixeldrain_link_entry:
            self.pixeldrain_link_entry.delete(0, tk.END)
        
        if self.gofile_log_text:
            self.gofile_log_text.delete(1.0, tk.END)
        if self.buzzheavier_log_text:
            self.buzzheavier_log_text.delete(1.0, tk.END)
        if self.pixeldrain_log_text:
            self.pixeldrain_log_text.delete(1.0, tk.END)
        
        if self.log_text and self.log_text != self.gofile_log_text:
            self.log_text.delete(1.0, tk.END)

    def open_link(self, host: str = "gofile") -> None:
        """
        Open link in browser.
        
        Parameters
        ----------
        host : str
            Which host link to open: 'gofile', 'buzzheavier', or 'pixeldrain'
        """
        if host == "gofile":
            link_entry = self.gofile_link_entry
        elif host == "buzzheavier":
            link_entry = self.buzzheavier_link_entry
        elif host == "pixeldrain":
            link_entry = self.pixeldrain_link_entry
        else:
            link_entry = None
            
        link = link_entry.get() if link_entry else ""
        if link:
            import webbrowser
            webbrowser.open(link)
            self.log(f"Opened {host.capitalize()} link in browser", host=host)

    def retry_gofile(self) -> None:
        """Retry upload to Gofile for the last uploaded file."""
        if not self.last_upload_file_path or not self.last_upload_parsed_info:
            self.log("No previous upload to retry", "WARNING", host="gofile")
            return

        if not self.api or not self.root_folder_id:
            self.log("Gofile not initialized", "ERROR", host="gofile")
            return

        self.log("Retrying Gofile upload...", "INFO", host="gofile")
        
        # Clear entry and reset status
        if self.gofile_link_entry:
            self.gofile_link_entry.delete(0, tk.END)
        self._update_status_emoji("gofile", "⏳")

        parsed = self.last_upload_parsed_info
        
        def retry_thread():
            link = self._upload_to_gofile(
                self.last_upload_file_path,
                parsed['package'],
                parsed['version'],
                parsed['full_name']
            )
            if not link:
                self.log("Retry failed", "ERROR", host="gofile")

        thread = threading.Thread(target=retry_thread, daemon=True)
        thread.start()

    def retry_buzzheavier(self) -> None:
        """Retry upload to Buzzheavier for the last uploaded file."""
        if not self.last_upload_file_path or not self.last_upload_parsed_info:
            self.log("No previous upload to retry", "WARNING", host="buzzheavier")
            return

        if not self.buzzheavier_api or not self.buzzheavier_root_folder_id:
            self.log("Buzzheavier not initialized", "ERROR", host="buzzheavier")
            return

        self.log("Retrying Buzzheavier upload...", "INFO", host="buzzheavier")
        
        # Clear entry and reset status
        if self.buzzheavier_link_entry:
            self.buzzheavier_link_entry.delete(0, tk.END)
        self._update_status_emoji("buzzheavier", "⏳")

        parsed = self.last_upload_parsed_info
        
        def retry_thread():
            link = self._upload_to_buzzheavier(
                self.last_upload_file_path,
                parsed['package'],
                parsed['version'],
                parsed['full_name']
            )
            if not link:
                self.log("Retry failed", "ERROR", host="buzzheavier")

        thread = threading.Thread(target=retry_thread, daemon=True)
        thread.start()
    
    def retry_pixeldrain(self) -> None:
        """Retry upload to Pixeldrain for the last uploaded file."""
        if not self.last_upload_file_path or not self.last_upload_parsed_info:
            self.log("No previous upload to retry", "WARNING", host="pixeldrain")
            return

        if not self.pixeldrain_api:
            self.log("Pixeldrain not initialized", "ERROR", host="pixeldrain")
            return

        self.log("Retrying Pixeldrain upload...", "INFO", host="pixeldrain")
        
        # Clear entry and reset status
        if self.pixeldrain_link_entry:
            self.pixeldrain_link_entry.delete(0, tk.END)
        self._update_status_emoji("pixeldrain", "⏳")

        parsed = self.last_upload_parsed_info
        
        def retry_thread():
            link = self._upload_to_pixeldrain(
                self.last_upload_file_path,
                parsed['package'],
                parsed['version'],
                parsed['full_name']
            )
            if not link:
                self.log("Retry failed", "ERROR", host="pixeldrain")

        thread = threading.Thread(target=retry_thread, daemon=True)
        thread.start()

    def register_drop_target(self, widget, dnd_files_constant) -> None:
        """Register a widget as a drag-and-drop target."""
        widget.drop_target_register(dnd_files_constant)
        widget.dnd_bind('<<Drop>>', self.on_drop)

    def toggle_mini_mode(self) -> None:
        """Toggle between normal and mini mode."""
        if self.mini_mode.get():
            # Switch to mini mode
            self.main_frame.grid_remove()
            self.mini_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
            self.root.geometry(f"{self.MINI_MODE_WIDTH}x{self.MINI_MODE_HEIGHT}")
            self.root.attributes('-topmost', True)
        else:
            # Switch to normal mode
            self.mini_frame.grid_remove()
            self.main_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
            self.root.geometry(f"{self.NORMAL_MODE_WIDTH}x{self.NORMAL_MODE_HEIGHT}")
            self.root.attributes('-topmost', False)

    def run(self) -> None:
        """Run the application."""
        try:
            from tkinterdnd2 import TkinterDnD, DND_FILES

            # Recreate root with DnD support
            self.root = TkinterDnD.Tk()
            self.root.title("Gofile Drag & Drop Uploader")
            self.root.geometry(f"{self.NORMAL_MODE_WIDTH}x{self.NORMAL_MODE_HEIGHT}")

            # Create mini mode variable after root window
            self.mini_mode = tk.BooleanVar(value=False)

            # Style
            style = ttk.Style()
            style.theme_use('clam')

            # Configure root grid
            self.root.columnconfigure(0, weight=1)
            self.root.rowconfigure(0, weight=1)

            # ===== MAIN FRAME (Normal Mode) =====
            self.main_frame = ttk.Frame(self.root, padding="10")
            self.main_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
            self.main_frame.columnconfigure(0, weight=1)
            self.main_frame.rowconfigure(3, weight=1)

            # Drop zone
            self.drop_frame = ttk.LabelFrame(
                self.main_frame, text="Drop Zone", padding="20"
            )
            self.drop_frame.grid(row=0, column=0, sticky=(tk.W, tk.E),
                                pady=(0, 10))
            self.drop_frame.columnconfigure(0, weight=1)

            drop_label = ttk.Label(
                self.drop_frame,
                text="📁 Drag & Drop APK Files Here",
                font=('Arial', 14, 'bold'),
                anchor=tk.CENTER
            )
            drop_label.grid(row=0, column=0, pady=20)

            self.status_label = ttk.Label(
                self.drop_frame,
                text="Initializing...",
                font=('Arial', 10),
                anchor=tk.CENTER
            )
            self.status_label.grid(row=1, column=0)

            # Mini mode checkbox
            mini_check = ttk.Checkbutton(
                self.drop_frame,
                text="Mini Mode (Always on Top)",
                variable=self.mini_mode,
                command=self.toggle_mini_mode
            )
            mini_check.grid(row=2, column=0, pady=(10, 0))

            # Enable drag and drop on drop frame
            self.register_drop_target(self.drop_frame, DND_FILES)

            # Link frame (multi-host with settings button)
            link_header_frame = ttk.Frame(self.main_frame)
            link_header_frame.grid(row=1, column=0, sticky=(tk.W, tk.E), pady=(0, 5))
            link_header_frame.columnconfigure(0, weight=1)
            
            link_label = ttk.Label(link_header_frame, text="Public Links", font=('Arial', 10, 'bold'))
            link_label.grid(row=0, column=0, sticky=tk.W)
            
            copy_all_btn = ttk.Button(link_header_frame, text="Copy All Links", 
                                      command=self.copy_all_links, width=15)
            copy_all_btn.grid(row=0, column=1, sticky=tk.E, padx=(5, 0))
            
            clear_btn = ttk.Button(link_header_frame, text="Clear", 
                                   command=self.clear_all, width=8)
            clear_btn.grid(row=0, column=2, sticky=tk.E, padx=(5, 0))
            
            settings_btn = ttk.Button(link_header_frame, text="⚙️", width=3,
                                     command=self.show_settings_menu)
            settings_btn.grid(row=0, column=3, sticky=tk.E, padx=(5, 0))
            
            self.link_frame = ttk.Frame(self.main_frame, padding="10")
            self.link_frame.grid(row=2, column=0, sticky=(tk.W, tk.E), pady=(0, 10))
            self.link_frame.columnconfigure(1, weight=1)

            # Gofile row
            self.gofile_enabled = tk.BooleanVar(value=True)
            
            self.gofile_status_frame = ttk.Frame(self.link_frame)
            self.gofile_status_frame.grid(row=0, column=0, sticky=tk.W, padx=(0, 5))
            gofile_status_frame = self.gofile_status_frame
            
            self.gofile_status_indicator = ttk.Label(gofile_status_frame, text="⟳", 
                                                      font=('Arial', 9, 'bold'), foreground="orange")
            self.gofile_status_indicator.grid(row=0, column=0)
            
            self.gofile_status_label = ttk.Label(gofile_status_frame, text=" Gofile:", 
                                                  font=('Arial', 9, 'bold'))
            self.gofile_status_label.grid(row=0, column=1)
            
            self.gofile_link_entry = ttk.Entry(self.link_frame, font=('Arial', 9))
            self.gofile_link_entry.grid(row=0, column=1, sticky=(tk.W, tk.E), padx=(0, 5))
            self.link_entry = self.gofile_link_entry  # Backward compatibility

            self.gofile_buttons_frame = ttk.Frame(self.link_frame)
            self.gofile_buttons_frame.grid(row=0, column=2)
            gofile_buttons = self.gofile_buttons_frame

            gofile_copy_btn = ttk.Button(gofile_buttons, text="Copy", 
                                         command=lambda: self.copy_link("gofile"), width=6)
            gofile_copy_btn.grid(row=0, column=0, padx=2)

            gofile_open_btn = ttk.Button(gofile_buttons, text="Open", 
                                         command=lambda: self.open_link("gofile"), width=6)
            gofile_open_btn.grid(row=0, column=1, padx=2)

            gofile_retry_btn = ttk.Button(gofile_buttons, text="Retry", 
                                          command=self.retry_gofile, width=6)
            gofile_retry_btn.grid(row=0, column=2, padx=2)

            # Buzzheavier row
            self.buzzheavier_enabled = tk.BooleanVar(value=True)
            
            self.buzzheavier_status_frame = ttk.Frame(self.link_frame)
            self.buzzheavier_status_frame.grid(row=1, column=0, sticky=tk.W, padx=(0, 5), pady=(5, 0))
            buzzheavier_status_frame = self.buzzheavier_status_frame
            
            self.buzzheavier_status_indicator = ttk.Label(buzzheavier_status_frame, text="⟳", 
                                                            font=('Arial', 9, 'bold'), foreground="orange")
            self.buzzheavier_status_indicator.grid(row=0, column=0)
            
            self.buzzheavier_status_label = ttk.Label(buzzheavier_status_frame, text=" Buzzheavier:", 
                                                        font=('Arial', 9, 'bold'))
            self.buzzheavier_status_label.grid(row=0, column=1)
            
            self.buzzheavier_link_entry = ttk.Entry(self.link_frame, font=('Arial', 9))
            self.buzzheavier_link_entry.grid(row=1, column=1, sticky=(tk.W, tk.E), padx=(0, 5), pady=(5, 0))

            self.buzzheavier_buttons_frame = ttk.Frame(self.link_frame)
            self.buzzheavier_buttons_frame.grid(row=1, column=2, pady=(5, 0))
            buzzheavier_buttons = self.buzzheavier_buttons_frame

            buzzheavier_copy_btn = ttk.Button(buzzheavier_buttons, text="Copy", 
                                              command=lambda: self.copy_link("buzzheavier"), width=6)
            buzzheavier_copy_btn.grid(row=0, column=0, padx=2)

            buzzheavier_open_btn = ttk.Button(buzzheavier_buttons, text="Open", 
                                              command=lambda: self.open_link("buzzheavier"), width=6)
            buzzheavier_open_btn.grid(row=0, column=1, padx=2)

            buzzheavier_retry_btn = ttk.Button(buzzheavier_buttons, text="Retry", 
                                               command=self.retry_buzzheavier, width=6)
            buzzheavier_retry_btn.grid(row=0, column=2, padx=2)
            
            # Pixeldrain row
            self.pixeldrain_enabled = tk.BooleanVar(value=False)
            
            self.pixeldrain_status_frame = ttk.Frame(self.link_frame)
            self.pixeldrain_status_frame.grid(row=2, column=0, sticky=tk.W, padx=(0, 5), pady=(5, 0))
            pixeldrain_status_frame = self.pixeldrain_status_frame
            
            self.pixeldrain_status_indicator = ttk.Label(pixeldrain_status_frame, text="⟳", 
                                                           font=('Arial', 9, 'bold'), foreground="orange")
            self.pixeldrain_status_indicator.grid(row=0, column=0)
            
            self.pixeldrain_status_label = ttk.Label(pixeldrain_status_frame, text=" Pixeldrain:", 
                                                       font=('Arial', 9, 'bold'))
            self.pixeldrain_status_label.grid(row=0, column=1)
            
            self.pixeldrain_link_entry = ttk.Entry(self.link_frame, font=('Arial', 9))
            self.pixeldrain_link_entry.grid(row=2, column=1, sticky=(tk.W, tk.E), padx=(0, 5), pady=(5, 0))

            self.pixeldrain_buttons_frame = ttk.Frame(self.link_frame)
            self.pixeldrain_buttons_frame.grid(row=2, column=2, pady=(5, 0))
            pixeldrain_buttons = self.pixeldrain_buttons_frame

            pixeldrain_copy_btn = ttk.Button(pixeldrain_buttons, text="Copy", 
                                              command=lambda: self.copy_link("pixeldrain"), width=6)
            pixeldrain_copy_btn.grid(row=0, column=0, padx=2)

            pixeldrain_open_btn = ttk.Button(pixeldrain_buttons, text="Open", 
                                              command=lambda: self.open_link("pixeldrain"), width=6)
            pixeldrain_open_btn.grid(row=0, column=1, padx=2)

            pixeldrain_retry_btn = ttk.Button(pixeldrain_buttons, text="Retry", 
                                               command=self.retry_pixeldrain, width=6)
            pixeldrain_retry_btn.grid(row=0, column=2, padx=2)

            # Log frame (tri-column with dynamic visibility)
            self.log_frame = ttk.LabelFrame(self.main_frame, text="Activity Logs", padding="10")
            self.log_frame.grid(row=3, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
            self.log_frame.columnconfigure(0, weight=1)
            self.log_frame.columnconfigure(1, weight=1)
            self.log_frame.columnconfigure(2, weight=1)
            self.log_frame.rowconfigure(1, weight=1)

            # Gofile log column
            self.gofile_log_label = ttk.Label(self.log_frame, text="Gofile", font=('Arial', 9, 'bold'))
            self.gofile_log_label.grid(row=0, column=0, sticky=tk.W, pady=(0, 5))

            self.gofile_log_text = scrolledtext.ScrolledText(self.log_frame, height=15,
                                                             font=('Consolas', 8),
                                                             wrap=tk.WORD)
            self.gofile_log_text.grid(row=1, column=0, sticky=(tk.W, tk.E, tk.N, tk.S), padx=(0, 5))
            self.log_text = self.gofile_log_text  # Backward compatibility

            # Color tags for Gofile log
            self.gofile_log_text.tag_config("success", foreground="green")
            self.gofile_log_text.tag_config("error", foreground="red")

            # Buzzheavier log column
            self.buzzheavier_log_label = ttk.Label(self.log_frame, text="Buzzheavier", font=('Arial', 9, 'bold'))
            self.buzzheavier_log_label.grid(row=0, column=1, sticky=tk.W, pady=(0, 5))

            self.buzzheavier_log_text = scrolledtext.ScrolledText(self.log_frame, height=15,
                                                                  font=('Consolas', 8),
                                                                  wrap=tk.WORD)
            self.buzzheavier_log_text.grid(row=1, column=1, sticky=(tk.W, tk.E, tk.N, tk.S))

            # Color tags for Buzzheavier log
            self.buzzheavier_log_text.tag_config("success", foreground="green")
            self.buzzheavier_log_text.tag_config("error", foreground="red")
            
            # Pixeldrain log column
            self.pixeldrain_log_label = ttk.Label(self.log_frame, text="Pixeldrain", font=('Arial', 9, 'bold'))
            self.pixeldrain_log_label.grid(row=0, column=2, sticky=tk.W, pady=(0, 5))

            self.pixeldrain_log_text = scrolledtext.ScrolledText(self.log_frame, height=15,
                                                                  font=('Consolas', 8),
                                                                  wrap=tk.WORD)
            self.pixeldrain_log_text.grid(row=1, column=2, sticky=(tk.W, tk.E, tk.N, tk.S))

            # Color tags for Pixeldrain log
            self.pixeldrain_log_text.tag_config("success", foreground="green")
            self.pixeldrain_log_text.tag_config("error", foreground="red")

            # ===== MINI FRAME (Mini Mode) =====
            self.mini_frame = ttk.Frame(self.root, padding="10")
            self.mini_frame.columnconfigure(0, weight=1)

            # Mini drop zone
            mini_drop_frame = ttk.LabelFrame(self.mini_frame, text="", padding="15")
            mini_drop_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
            mini_drop_frame.columnconfigure(0, weight=1)

            # Drop APK Here label (centered)
            drop_here_label = ttk.Label(mini_drop_frame, text="Drop APK Here",
                                       font=('Arial', 9, 'bold'),
                                       anchor=tk.CENTER)
            drop_here_label.grid(row=0, column=0)

            mini_drop_label = ttk.Label(mini_drop_frame, text="📁",
                                       font=('Arial', 24),
                                       anchor=tk.CENTER)
            mini_drop_label.grid(row=1, column=0, pady=5)

            # Mini status
            self.mini_status_label = ttk.Label(
                mini_drop_frame,
                text="Ready",
                font=('Arial', 8),
                anchor=tk.CENTER
            )
            self.mini_status_label.grid(row=2, column=0)

            # Enable drag and drop on mini frame
            self.register_drop_target(mini_drop_frame, DND_FILES)
            self.register_drop_target(mini_drop_label, DND_FILES)

            # Mini link sections (dual-host stacked)
            mini_links_frame = ttk.Frame(self.mini_frame)
            mini_links_frame.grid(row=1, column=0, pady=(5, 0), sticky=(tk.W, tk.E))
            mini_links_frame.columnconfigure(0, weight=1)

            # Gofile mini section
            self.mini_gofile_indicator = ttk.Label(mini_links_frame, text="✓", font=('Arial', 8, 'bold'), foreground="green")
            self.mini_gofile_indicator.grid(row=0, column=0, sticky=tk.W)
            mini_gofile_name = ttk.Label(mini_links_frame, text=" Gofile", font=('Arial', 8, 'bold'))
            mini_gofile_name.grid(row=0, column=0, sticky=tk.W, padx=(15, 0))

            mini_gofile_buttons = ttk.Frame(mini_links_frame)
            mini_gofile_buttons.grid(row=1, column=0, pady=(2, 5))

            mini_gofile_copy = ttk.Button(mini_gofile_buttons, text="Copy",
                                         command=lambda: self.copy_link("gofile"), width=8)
            mini_gofile_copy.grid(row=0, column=0, padx=2)

            mini_gofile_open = ttk.Button(mini_gofile_buttons, text="Open",
                                         command=lambda: self.open_link("gofile"), width=8)
            mini_gofile_open.grid(row=0, column=1, padx=2)

            # Buzzheavier mini section
            self.mini_buzzheavier_indicator = ttk.Label(mini_links_frame, text="⟳", font=('Arial', 8, 'bold'), foreground="orange")
            self.mini_buzzheavier_indicator.grid(row=2, column=0, sticky=tk.W)
            mini_buzzheavier_name = ttk.Label(mini_links_frame, text=" Buzzheavier", font=('Arial', 8, 'bold'))
            mini_buzzheavier_name.grid(row=2, column=0, sticky=tk.W, padx=(15, 0))

            mini_buzzheavier_buttons = ttk.Frame(mini_links_frame)
            mini_buzzheavier_buttons.grid(row=3, column=0, pady=(2, 5))

            mini_buzzheavier_copy = ttk.Button(mini_buzzheavier_buttons, text="Copy",
                                              command=lambda: self.copy_link("buzzheavier"), width=8)
            mini_buzzheavier_copy.grid(row=0, column=0, padx=2)

            mini_buzzheavier_open = ttk.Button(mini_buzzheavier_buttons, text="Open",
                                              command=lambda: self.open_link("buzzheavier"), width=8)
            mini_buzzheavier_open.grid(row=0, column=1, padx=2)

            # Pixeldrain mini section
            self.mini_pixeldrain_indicator = ttk.Label(mini_links_frame, text="⟳", font=('Arial', 8, 'bold'), foreground="orange")
            self.mini_pixeldrain_indicator.grid(row=4, column=0, sticky=tk.W)
            mini_pixeldrain_name = ttk.Label(mini_links_frame, text=" Pixeldrain", font=('Arial', 8, 'bold'))
            mini_pixeldrain_name.grid(row=4, column=0, sticky=tk.W, padx=(15, 0))

            mini_pixeldrain_buttons = ttk.Frame(mini_links_frame)
            mini_pixeldrain_buttons.grid(row=5, column=0, pady=(2, 5))

            mini_pixeldrain_copy = ttk.Button(mini_pixeldrain_buttons, text="Copy",
                                             command=lambda: self.copy_link("pixeldrain"), width=8)
            mini_pixeldrain_copy.grid(row=0, column=0, padx=2)

            mini_pixeldrain_open = ttk.Button(mini_pixeldrain_buttons, text="Open",
                                             command=lambda: self.open_link("pixeldrain"), width=8)
            mini_pixeldrain_open.grid(row=0, column=1, padx=2)

            # Normal mode checkbox
            normal_check = ttk.Checkbutton(mini_links_frame, text="Normal Mode",
                                          variable=self.mini_mode,
                                          command=self.toggle_mini_mode)
            normal_check.grid(row=6, column=0, pady=(5, 0))

            # Start in normal mode (hide mini frame)
            self.mini_frame.grid_remove()

            # Initialize API in separate thread
            init_thread = threading.Thread(target=self.initialize_api)
            init_thread.daemon = True
            init_thread.start()

            # Run GUI
            self.root.mainloop()

        except ImportError:
            print("=" * 70)
            print("ERROR: tkinterdnd2 is not installed")
            print("=" * 70)
            print("\nThis application requires tkinterdnd2 for drag-and-drop support.")
            print("\nTo install:")
            print("  pip install tkinterdnd2")
            print("\nAlternatively, run:")
            print("  pip install -r requirements.txt")
            print("=" * 70)
            sys.exit(1)


def main():
    """Main function."""
    app = DragDropUploader()
    app.run()


if __name__ == "__main__":
    main()
