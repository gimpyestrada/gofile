"""
Gofile Drag & Drop Uploader
A GUI application that accepts drag-and-drop APK files and uploads them to the appropriate
Gofile folder structure, then returns a public link.
"""

import hashlib
import os
import re
import sys
import queue
import time
import tkinter as tk
import webbrowser
from collections import deque
from urllib.parse import urlparse
from tkinter import ttk, scrolledtext, messagebox
from datetime import datetime
from typing import Callable, Dict, List, Optional
import threading
from PIL import Image, UnidentifiedImageError
import pystray
from gofile_api import GofileAPIError
from buzzheavier_api import BuzzheavierAPIError, NetworkException
from config_loader import get_app_dir, load_config
from apk_naming import normalize_version_folder_name, parse_apk_filename
from duplicate_scan import DuplicateScanMixin
from host_workers import HostWorkersMixin
from widgets import Tooltip
from settings_dialog import SettingsDialog
import folder_cache


class DragDropUploader(HostWorkersMixin, DuplicateScanMixin):
    """Drag and drop uploader with GUI."""

    CACHE_EXPIRY_HOURS = 24

    # Window dimensions
    WINDOW_WIDTH = 900
    WINDOW_HEIGHT = 800

    # API delays (seconds)
    API_FOLDER_CREATE_DELAY = 2
    API_FOLDER_UPDATE_DELAY = 1

    # How often the main thread drains GUI updates queued by worker threads.
    GUI_QUEUE_POLL_MS = 50

    PROGRESS_BAR_WIDTH = 110

    # Only links to these hosts become clickable in the logs. Server responses
    # are echoed into the logs on error, so an arbitrary URL in one must not
    # turn into something the user can click.
    LINK_ALLOWED_HOSTS = frozenset({
        'gofile.io',
        'buzzheavier.com',
        'pixeldrain.com',
        'apkadmin.com',
    })

    def __init__(self):
        """Initialize the uploader."""
        # Set cache file path
        self.FOLDER_CACHE_FILE = os.path.join(get_app_dir(), "folder_structure_cache.json")
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

        # Apkadmin API
        self.apkadmin_api = None

        # Cache and config
        self.cache_data = None
        self.config = None

        # Thread safety
        self._gui_queue = queue.Queue()
        self._ready_lock = threading.Lock()
        self._is_ready = False
        self._gofile_ready = False
        self._buzzheavier_ready = False
        self._pixeldrain_ready = False
        self._apkadmin_ready = False
        self.queue_lock = threading.Lock()
        self.upload_queue = deque()
        self.queue_processing = False
        self.queue_thread = None
        self.abort_uploading = False
        
        # Duplicate checking state
        self.duplicate_decisions = {}  # {file_path: {'gofile': action, 'buzzheavier': action, 'pixeldrain': action, 'apkadmin': action}}
        self.scanned_files = set()  # Track which files have been scanned for duplicates
        self.scan_progress_window = None
        self.scan_status_label = None
        self.scan_file_label = None
        self.scanning_in_progress = False
        self.scan_complete_event = threading.Event()
        self.scan_complete_event.set()  # Start in "set" state (no scan in progress)

        # Upload tracking for retry functionality
        self.last_upload_file_path = None
        self.last_upload_parsed_info = None
        self.last_upload_status = {}
        
        # Host toggle settings
        self.gofile_enabled = None
        self.buzzheavier_enabled = None
        self.pixeldrain_enabled = None
        self.apkadmin_enabled = None

        # GUI components
        self.root = None
        self.log_text = None  # Backward compatibility alias for gofile_log_text
        self.gofile_log_text = None
        self.buzzheavier_log_text = None
        self.pixeldrain_log_text = None
        self.apkadmin_log_text = None
        self.general_log_text = None
        self.status_label = None
        self.gofile_status_label = None
        self.buzzheavier_status_label = None
        self.pixeldrain_status_label = None
        self.apkadmin_status_label = None
        self.link_entry = None  # Backward compatibility alias for gofile_link_entry
        self.gofile_link_entry = None
        self.buzzheavier_link_entry = None
        self.pixeldrain_link_entry = None
        self.apkadmin_link_entry = None
        self.is_ready = False

        # Frames and widgets
        self.main_frame = None
        self.drop_frame = None
        self.link_frame = None
        self.log_frame = None
        self.file_info_frame = None
        self.file_name_label = None
        self.file_size_label = None

        # Log column widgets
        self.gofile_log_label = None
        self.buzzheavier_log_label = None
        self.pixeldrain_log_label = None
        self.apkadmin_log_label = None
        self.general_log_label = None

        # Button frames
        self.gofile_buttons_frame = None
        self.buzzheavier_buttons_frame = None
        self.pixeldrain_buttons_frame = None
        self.apkadmin_buttons_frame = None

        # Status indicators
        self.gofile_status_indicator = None
        self.buzzheavier_status_indicator = None
        self.pixeldrain_status_indicator = None
        self.apkadmin_status_indicator = None

        # Status frames
        self.gofile_status_frame = None
        self.buzzheavier_status_frame = None
        self.pixeldrain_status_frame = None
        self.apkadmin_status_frame = None

        # Per-host upload progress bars
        self.host_progress_bars = {}
        self.host_progress_labels = {}

        # Tray icon
        self._tray = None

    def _resource_path(self, name: str) -> str:
        """Resolve a bundled resource path.

        If running under PyInstaller, use the temporary extraction
        directory; otherwise resolve relative to this file.
        """
        base = getattr(sys, '_MEIPASS', None)
        if base:
            return os.path.join(base, name)
        return os.path.join(os.path.dirname(os.path.abspath(__file__)), name)

    def _start_tray_icon(self) -> None:
        """Start the system tray icon with basic menu actions."""
        try:
            image = Image.open(self._resource_path('upload_cloud_file_icon_181534.ico'))
        except (FileNotFoundError, UnidentifiedImageError, OSError):
            return

        menu = pystray.Menu(
            pystray.MenuItem('Show', self._show_window),
            pystray.MenuItem('Exit', self._exit_app)
        )

        self._tray = pystray.Icon('GofileUploader', image, 'Gofile Uploader', menu)
        threading.Thread(target=self._tray.run, daemon=True).start()

    def _show_window(self) -> None:
        """Show and focus the main application window."""
        if self.root:
            self.root.after(0, self._bring_to_front)

    def _bring_to_front(self) -> None:
        """Bring the window to the foreground and focus it."""
        if not self.root:
            return
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()

    def _run_on_gui_thread(self, action: Callable[[], None]) -> None:
        """
        Run a widget update on the Tk main thread.

        Tkinter is not thread-safe, and uploads, duplicate scans, and host
        initialization all run on background threads. Updates from those
        threads go onto a queue that ``_pump_gui_queue`` drains on the main
        thread.

        Calling ``root.after`` from a worker thread is not an option here:
        host initialization starts before ``mainloop()`` does, and ``after``
        raises RuntimeError when the loop is not yet running. Queueing keeps
        those early messages instead of dropping them.
        """
        if threading.current_thread() is threading.main_thread():
            self._safe_gui_call(action)
        else:
            self._gui_queue.put(action)

    @staticmethod
    def _safe_gui_call(action: Callable[[], None]) -> None:
        """Run a GUI update, ignoring failures from a torn-down window."""
        try:
            action()
        except tk.TclError:
            pass

    def _pump_gui_queue(self) -> None:
        """Drain queued GUI updates. Reschedules itself on the main thread."""
        try:
            while True:
                self._safe_gui_call(self._gui_queue.get_nowait())
        except queue.Empty:
            pass

        if self.root:
            self.root.after(self.GUI_QUEUE_POLL_MS, self._pump_gui_queue)

    def _exit_app(self) -> None:
        """Gracefully stop the tray icon and exit the GUI loop."""
        if self._tray:
            self._tray.stop()
        if self.root:
            self.root.after(0, self.root.quit)

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
            Which host log to write to: 'gofile', 'buzzheavier', 'pixeldrain', 'apkadmin', 'general', or 'both'.
            Default is 'both'.
        """
        timestamp = datetime.now().strftime("%H:%M:%S")
        formatted_msg = f"[{timestamp}] {message}\n"

        print(message)

        widgets = self._log_widgets_for_host(host)
        if not widgets:
            return

        self._run_on_gui_thread(
            lambda: [self._append_to_log(w, formatted_msg, level)
                     for w in widgets]
        )

    def _log_widgets_for_host(self, host: str) -> List:
        """Resolve which log widgets a message should be written to."""
        routes = {
            "general": [self.general_log_text],
            "gofile": [self.gofile_log_text],
            "buzzheavier": [self.buzzheavier_log_text],
            "pixeldrain": [self.pixeldrain_log_text],
            "apkadmin": [self.apkadmin_log_text],
            "both": [self.gofile_log_text, self.buzzheavier_log_text],
        }
        widgets = list(routes.get(host, []))

        # Backward compatibility with the pre-multi-host single log widget.
        if self.log_text and self.log_text is not self.gofile_log_text:
            widgets.append(self.log_text)

        return [w for w in widgets if w]

    def _append_to_log(self, log_widget, formatted_msg: str,
                       level: str) -> None:
        """Insert one line into a log widget. Must run on the GUI thread."""
        if "url" not in log_widget.tag_names():
            log_widget.tag_config("url", foreground="blue", underline=True)
            log_widget.tag_bind("url", "<Button-1>", self._open_url_from_event, add="+")
            log_widget.tag_bind("url", "<Enter>", lambda e: e.widget.config(cursor="hand2"), add="+")
            log_widget.tag_bind("url", "<Leave>", lambda e: e.widget.config(cursor=""), add="+")

        log_widget.insert(tk.END, formatted_msg)
        log_widget.see(tk.END)

        line_start = log_widget.index("end-2c linestart")
        line_end = log_widget.index("end-1c lineend")

        if level == "SUCCESS":
            log_widget.tag_add("success", line_start, line_end)
        elif level == "ERROR":
            log_widget.tag_add("error", line_start, line_end)

        link_match = re.search(r"(https?://\S+)", formatted_msg)
        if link_match and self._is_allowed_link(link_match.group(1)):
            link_text = link_match.group(1)
            line_text = log_widget.get(line_start, line_end)
            pos = line_text.find(link_text)
            if pos >= 0:
                start_idx = f"{line_start}+{pos}c"
                end_idx = f"{start_idx}+{len(link_text)}c"
                log_widget.tag_add("url", start_idx, end_idx)

    @staticmethod
    def _mask_email(email: Optional[str]) -> str:
        """
        Partially redact an email for display.

        The log is visible in screenshots and screen shares, so it shows just
        enough to confirm which account is connected.
        """
        if not email or '@' not in email:
            return "(unknown)"

        local, _, domain = email.partition('@')
        visible = local[:2] if len(local) > 2 else local[:1]
        return f"{visible}{'*' * 3}@{domain}"

    @classmethod
    def _is_allowed_link(cls, url: str) -> bool:
        """
        Check whether a URL points at one of the configured file hosts.

        Matches the host exactly or as a subdomain, so 'gofile.io.evil.com'
        and 'notgofile.io' are both rejected.
        """
        try:
            parsed = urlparse(url)
        except ValueError:
            return False

        if parsed.scheme not in ('http', 'https'):
            return False

        hostname = (parsed.hostname or '').lower().rstrip('.')
        return any(
            hostname == allowed or hostname.endswith('.' + allowed)
            for allowed in cls.LINK_ALLOWED_HOSTS
        )

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
        """Update the status label from any thread."""
        if self.status_label:
            self._run_on_gui_thread(
                lambda: self.status_label.config(text=message)
            )

    def save_host_settings(self) -> None:
        """Save enabled host settings to config.json."""
        if self.config and self.gofile_enabled and self.buzzheavier_enabled and self.pixeldrain_enabled:
            try:
                self.config.update('gofile_enabled', self.gofile_enabled.get())
                self.config.update('buzzheavier_enabled', self.buzzheavier_enabled.get())
                self.config.update('pixeldrain_enabled', self.pixeldrain_enabled.get())
                if self.apkadmin_enabled:
                    self.config.update('apkadmin_enabled', self.apkadmin_enabled.get())
                
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
            apkadmin_enabled = self.config.get('apkadmin_enabled', False)

            if self.gofile_enabled:
                self.gofile_enabled.set(gofile_enabled)
            if self.buzzheavier_enabled:
                self.buzzheavier_enabled.set(buzzheavier_enabled)
            if self.pixeldrain_enabled:
                self.pixeldrain_enabled.set(pixeldrain_enabled)
            if self.apkadmin_enabled:
                self.apkadmin_enabled.set(apkadmin_enabled)
    
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
        menu.add_checkbutton(
            label="Apkadmin",
            variable=self.apkadmin_enabled,
            command=self._validate_and_save_host_settings
        )

        menu.add_separator()
        menu.add_command(label="Credentials…", command=self.open_settings_dialog)

        # Display menu at mouse position
        try:
            menu.tk_popup(self.root.winfo_pointerx(), self.root.winfo_pointery())
        finally:
            menu.grab_release()

    def open_settings_dialog(self) -> None:
        """Open the credential editor and offer to reconnect after saving."""
        if not self.config:
            self.config = load_config()

        SettingsDialog(self.root, self.config, on_saved=self._on_settings_saved)

    def _on_settings_saved(self) -> None:
        """Refresh host toggles and offer to reconnect with the new values."""
        self.load_host_settings()
        self.update_visibility()

        reconnect = messagebox.askyesno(
            "Settings Saved",
            "Credentials saved.\n\nReconnect to the file hosts now?",
        )
        if not reconnect:
            return

        # Drop the cached config so initialize_api re-reads the new values.
        self.config = None
        self.is_ready = False
        self.update_status("Reconnecting...")
        threading.Thread(target=self.initialize_api, daemon=True).start()

    def _validate_and_save_host_settings(self) -> None:
        """Validate at least one host is enabled before saving."""
        if not (self.gofile_enabled.get() or self.buzzheavier_enabled.get() or self.pixeldrain_enabled.get() or (self.apkadmin_enabled and self.apkadmin_enabled.get())):
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
        if self.apkadmin_enabled and self.apkadmin_enabled.get():
            enabled_hosts.append(('apkadmin', self.apkadmin_log_label, self.apkadmin_log_text,
                                 self.apkadmin_status_frame, self.apkadmin_link_entry))
        
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
        if self.apkadmin_log_label:
            self.apkadmin_log_label.grid_remove()
        if self.apkadmin_log_text:
            self.apkadmin_log_text.grid_remove()
        
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

        if self.apkadmin_status_frame:
            self.apkadmin_status_frame.grid_remove()
        if self.apkadmin_link_entry:
            self.apkadmin_link_entry.grid_remove()
        if self.apkadmin_buttons_frame:
            self.apkadmin_buttons_frame.grid_remove()

        # Reset column weights
        for i in range(4):
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
            elif name == 'apkadmin' and self.apkadmin_buttons_frame:
                self.apkadmin_buttons_frame.grid(row=row, column=2, pady=(5, 0) if row > 0 else (0, 0))
        
        # Show enabled logs with new column positions
        for col, (name, label_widget, log_widget, _status_label, link_entry) in enumerate(enabled_hosts):
            if label_widget:
                label_widget.grid(row=0, column=col, sticky=tk.W, pady=(0, 5), padx=(0, 5) if col < len(enabled_hosts)-1 else (0, 0))
            if log_widget:
                log_widget.grid(row=1, column=col, sticky=(tk.W, tk.E, tk.N, tk.S), 
                              padx=(0, 5) if col < len(enabled_hosts)-1 else (0, 0))
            self.log_frame.columnconfigure(col, weight=1)
    
    def parse_apk_filename(self, filename: str) -> Optional[Dict[str, str]]:
        """Parse an APK filename. See apk_naming.parse_apk_filename."""
        return parse_apk_filename(filename)

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
        try:
            folder_cache.save_host_folders(
                self.FOLDER_CACHE_FILE, host, root_folder_id, folders
            )
            self.log(f"Saved {host} cache with {len(folders)} folders", "SUCCESS", host=host)
        except folder_cache.FolderCacheError as e:
            self.log(f"Error saving {host} cache: {e}", "ERROR", host=host)

    def load_folder_cache(self) -> Optional[Dict]:
        """
        Load cached folder structure.

        Migrates the original single-host format to the multi-host layout.
        """
        try:
            cache_data = folder_cache.read_cache(self.FOLDER_CACHE_FILE)
        except folder_cache.FolderCacheError as e:
            self.log(f"{e}", "ERROR")
            return None

        if cache_data is None:
            return None

        if folder_cache.needs_migration(cache_data):
            self.log("Migrating old cache format to multi-host structure...")
            cache_data = folder_cache.migrate(cache_data)
            try:
                folder_cache.write_cache(self.FOLDER_CACHE_FILE, cache_data)
                self.log("Cache migration complete", "SUCCESS")
            except folder_cache.FolderCacheError as e:
                self.log(f"Warning: Could not save migrated cache: {e}", "WARNING")

        return cache_data

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
        host_cache, reason = folder_cache.get_valid_host_cache(
            self.cache_data, host, root_folder_id, self.CACHE_EXPIRY_HOURS
        )

        if host_cache:
            self.log(f"Using cached {host} folder structure", host=host)
            folder_structure_dict.update(
                folder_cache.extract_parent_folders(host_cache)
            )
            parent_count = len(folder_structure_dict)
            self.log(f"Loaded {parent_count} {host} parent folders from cache", "SUCCESS", host=host)
            return

        self.log(f"No valid {host} cache ({reason}) - scanning folders...", host=host)
        
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
        Create a new parent folder for a package, or return existing folder ID.

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
            # First check if folder already exists in root
            self.log(f"Checking for existing parent folder: {package}")
            root_contents = self.api.get_content(self.root_folder_id)
            
            if root_contents and 'children' in root_contents:
                children = root_contents.get('children', {})
                
                # Check if parent folder already exists
                for child_id, child_data in children.items():
                    if child_data.get('type') != 'folder':
                        continue
                    if child_data.get('name') == package:
                        self.log(f"Parent folder already exists: {package}")
                        # Add to structure cache
                        self.folder_structure[package] = child_id
                        return child_id
            
            # Folder doesn't exist, create it
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

    def _normalize_version_folder_name(self, folder_name: str) -> str:
        """Normalize a version folder name. See apk_naming."""
        return normalize_version_folder_name(folder_name)

    def create_version_folder(
        self,
        parent_id: str,
        version_folder_name: str,
        alt_version_names: Optional[List[str]] = None
    ) -> Optional[str]:
        """
        Create or get version folder within a parent folder.

        Parameters
        ----------
        parent_id : str
            The parent folder ID where the version folder will be created.
        version_folder_name : str
            The name for the version folder (e.g., 'com.app.name-1.0-release').
        alt_version_names : Optional[List[str]]
            Alternative names that should be treated as equivalent (used to
            detect legacy folders such as ones that include '-release').

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
            candidate_names = [version_folder_name]
            if alt_version_names:
                candidate_names.extend(alt_version_names)

            # Check if version folder already exists
            for child_id, child_data in children.items():
                if child_data.get('type') != 'folder':
                    continue
                if child_data.get('name') in candidate_names:
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

        # Reaching a terminal state means this host's transfer is over, so the
        # progress bar should not linger at whatever percentage it stopped at.
        if emoji in ("🟢", "🔴"):
            self._reset_host_progress(host)

        if host == "gofile" and self.gofile_status_indicator:
            self.root.after(0, lambda: self.gofile_status_indicator.config(
                text=indicator, foreground=color))
        elif host == "buzzheavier" and self.buzzheavier_status_indicator:
            self.root.after(0, lambda: self.buzzheavier_status_indicator.config(
                text=indicator, foreground=color))
        elif host == "pixeldrain" and self.pixeldrain_status_indicator:
            self.root.after(0, lambda: self.pixeldrain_status_indicator.config(
                text=indicator, foreground=color))
        elif host == "apkadmin" and self.apkadmin_status_indicator:
            self.root.after(0, lambda: self.apkadmin_status_indicator.config(
                text=indicator, foreground=color))

    def _create_host_progress_bar(self, host: str, parent) -> None:
        """
        Add a hidden progress bar beneath a host's status label.

        Lives inside the status frame so update_visibility, which grids that
        frame as a unit, keeps working unchanged. A percentage label is
        overlaid on top of the bar via place(), which positions relative to
        the bar's own geometry without disturbing the grid layout everything
        else uses.
        """
        bar = ttk.Progressbar(parent, orient=tk.HORIZONTAL, mode='determinate',
                              maximum=100, length=self.PROGRESS_BAR_WIDTH)
        bar.grid(row=1, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=(2, 0))
        bar.grid_remove()
        self.host_progress_bars[host] = bar

        label = ttk.Label(parent, text="", font=('Arial', 7, 'bold'),
                          anchor=tk.CENTER)
        self.host_progress_labels[host] = label

    def _make_progress_callback(self, host: str) -> Callable[[int, Optional[int]], None]:
        """
        Build a throttled progress callback for one host's upload.

        The callback runs on the upload thread once per chunk, which is far
        more often than the display needs. Updates are emitted only when the
        whole-percent value changes, so a large upload queues about a hundred
        GUI updates instead of thousands.
        """
        last_percent = [-1]

        def report(bytes_sent: int, total_size: Optional[int]) -> None:
            if not total_size:
                return

            percent = int(bytes_sent * 100 / total_size)
            if percent == last_percent[0]:
                return
            last_percent[0] = percent
            self._set_host_progress(host, percent)

        return report

    def _set_host_progress(self, host: str, percent: int) -> None:
        """Show a host's progress bar at the given percentage, with the
        percentage overlaid as text centered on the bar."""
        bar = self.host_progress_bars.get(host)
        if not bar:
            return
        label = self.host_progress_labels.get(host)

        def update():
            bar.grid()
            bar['value'] = percent
            if label:
                label.config(text=f"{percent}%")
                # in_=bar tracks the bar's live position/size, so this only
                # needs to be issued once per show rather than per update.
                label.place(in_=bar, relx=0.5, rely=0.5, anchor=tk.CENTER)

        self._run_on_gui_thread(update)

    def _reset_host_progress(self, host: str) -> None:
        """Hide a host's progress bar and its percentage label, and zero it."""
        bar = self.host_progress_bars.get(host)
        if not bar:
            return
        label = self.host_progress_labels.get(host)

        def update():
            bar['value'] = 0
            bar.grid_remove()
            if label:
                label.place_forget()

        self._run_on_gui_thread(update)

    def _reset_all_progress(self) -> None:
        """Hide every progress bar, e.g. when clearing or starting a batch."""
        for host in self.host_progress_bars:
            self._reset_host_progress(host)

    def _open_url_from_event(self, event):
        """Open clicked URL inside a log widget."""
        widget = event.widget
        index = widget.index("current")

        # Find the tagged range that includes the click position
        start_end = None
        if "url" in widget.tag_names(index):
            prev_range = widget.tag_prevrange("url", index)
            if prev_range and len(prev_range) == 2 and widget.compare(prev_range[0], "<=", index) and widget.compare(index, "<", prev_range[1]):
                start_end = prev_range
            else:
                next_range = widget.tag_nextrange("url", index)
                if next_range and len(next_range) == 2 and widget.compare(next_range[0], "<=", index) and widget.compare(index, "<", next_range[1]):
                    start_end = next_range

        if start_end:
            url = widget.get(start_end[0], start_end[1]).strip()
            # Re-check rather than trusting the tag: the widget text is what
            # actually gets handed to the browser.
            if self._is_allowed_link(url):
                webbrowser.open(url)
        return "break"

    def _find_existing_version_folder(self, parent_id: str, version_folder_name: str, alt_version_names: Optional[List[str]] = None) -> Optional[str]:
        """
        Return version folder ID if it already exists under the parent; do not create.

        Checks both normalized and legacy names when provided.
        """
        try:
            parent_contents = self.api.get_content(parent_id)
            children = parent_contents.get('children', {})

            candidate_names = [version_folder_name]
            if alt_version_names:
                candidate_names.extend(alt_version_names)

            for child_id, child_data in children.items():
                if child_data.get('type') != 'folder':
                    continue
                if child_data.get('name') in candidate_names:
                    return child_id
            return None
        except (RuntimeError, KeyError, ValueError, OSError, IOError):
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
        self.last_upload_status = {
            "gofile": None,
            "buzzheavier": None,
            "pixeldrain": None,
            "apkadmin": None,
        }

        self._clear_link_entries()

        try:
            file_path = file_path.strip()

            # Validate file existence
            if not os.path.exists(file_path):
                self.log(f"File not found: {file_path}", "ERROR", host="general")
                self.update_status("Ready - Drop APK file here")
                return

            if not os.path.isfile(file_path):
                self.log(f"Not a file: {file_path}", "ERROR", host="general")
                self.update_status("Ready - Drop APK file here")
                return

            filename = os.path.basename(file_path)

            self.log("=" * 50, host="general")
            self.log(f"Processing: {filename}", "INFO", host="general")

            # Parse filename
            parsed = self.parse_apk_filename(filename)

            if not parsed:
                self.log("Could not parse APK filename", "ERROR", host="general")
                self.log("Expected format: package-version-suffix.apk", "ERROR", host="general")
                self.update_status("Ready - Drop APK file here")
                self.last_upload_status = {}
                return

            package = parsed['package']
            version = parsed['version']
            full_name = parsed['full_name']

            self.log(f"Package: {package}", host="general")
            self.log(f"Version: {version}", host="general")

            # Update file info immediately
            self.update_file_info(file_path)

            # Store for retry functionality
            self.last_upload_file_path = file_path
            self.last_upload_parsed_info = parsed

            # Apply stored duplicate decisions from batch scan
            hosts_to_skip = set()
            
            if file_path in self.duplicate_decisions:
                decisions = self.duplicate_decisions[file_path]
                self.log("Applying duplicate handling decisions from batch scan...", "INFO", host="general")
                
                for host, action in decisions.items():
                    if action == "skip":
                        hosts_to_skip.add(host)
                        self.log(f"{host.capitalize()}: Skip (duplicate)", "WARNING", host="general")
                    elif action == "overwrite":
                        self.log(f"{host.capitalize()}: Overwrite (deleting existing file)", "INFO", host="general")
                        # Perform deletion per host
                        if host == "gofile" and self.api:
                            # Need to detect duplicate again to get file_id for deletion
                            dups = self._detect_duplicates(file_path, package, full_name)
                            info = dups.get('gofile')
                            if info and info.get('file_id'):
                                try:
                                    self.log("Deleting existing Gofile file...", host="gofile")
                                    self.api.delete_content(info['file_id'])
                                    self.log("Deleted existing file", "SUCCESS", host="gofile")
                                except GofileAPIError as e:
                                    self.log(f"Gofile delete failed: {e}", "ERROR", host="gofile")
                        elif host == "buzzheavier" and self.buzzheavier_api:
                            dups = self._detect_duplicates(file_path, package, full_name)
                            info = dups.get('buzzheavier')
                            if info and info.get('file_id'):
                                try:
                                    self.log("Deleting existing Buzzheavier file...", host="buzzheavier")
                                    self.buzzheavier_api.delete_file(info['file_id'])
                                    self.log("Deleted existing file", "SUCCESS", host="buzzheavier")
                                except (BuzzheavierAPIError, NetworkException) as e:
                                    self.log(f"Buzzheavier delete failed: {e}", "ERROR", host="buzzheavier")
                        elif host == "pixeldrain" and self.pixeldrain_api:
                            self.log("Pixeldrain overwrite not supported by client; uploading new copy", "WARNING", host="pixeldrain")
                    elif action == "upload_again":
                        self.log(f"{host.capitalize()}: Upload again (allow duplicate)", "INFO", host="general")

            # Reset status emojis to uploading
            self._update_status_emoji("gofile", "⏳")
            self._update_status_emoji("buzzheavier", "⏳")
            self._update_status_emoji("pixeldrain", "⏳")
            self._update_status_emoji("apkadmin", "⏳")

            # Upload to all hosts in parallel
            self.update_status("Uploading to enabled hosts...")

            gofile_link = None
            buzzheavier_link = None
            pixeldrain_link = None
            apkadmin_link = None

            # Track status for each host: 'success', 'skipped', or 'failed'
            gofile_state = 'skipped'
            buzzheavier_state = 'skipped'
            pixeldrain_state = 'skipped'
            apkadmin_state = 'skipped'

            def upload_gofile():
                nonlocal gofile_link, gofile_state
                if 'gofile' in hosts_to_skip:
                    self.log("Gofile upload skipped (duplicate detected)", "WARNING", host="gofile")
                    gofile_state = 'skipped'
                    self.log("-" * 25, host="gofile")
                elif self.gofile_enabled and not self.gofile_enabled.get():
                    self.log("Gofile upload skipped (disabled)", "WARNING", host="gofile")
                    gofile_state = 'skipped'
                    self.log("-" * 25, host="gofile")
                elif self.api and self.root_folder_id:
                    gofile_link = self._upload_to_gofile(file_path, package, version, full_name)
                    gofile_state = 'success' if gofile_link else 'failed'

            def upload_buzzheavier():
                nonlocal buzzheavier_link, buzzheavier_state
                if 'buzzheavier' in hosts_to_skip:
                    self.log("Buzzheavier upload skipped (duplicate detected)", "WARNING", host="buzzheavier")
                    buzzheavier_state = 'skipped'
                    self.log("-" * 25, host="buzzheavier")
                elif self.buzzheavier_enabled and not self.buzzheavier_enabled.get():
                    self.log("Buzzheavier upload skipped (disabled)", "WARNING", host="buzzheavier")
                    buzzheavier_state = 'skipped'
                    self.log("-" * 25, host="buzzheavier")
                elif self.buzzheavier_api and self.buzzheavier_root_folder_id:
                    buzzheavier_link = self._upload_to_buzzheavier(file_path, package, version, full_name)
                    buzzheavier_state = 'success' if buzzheavier_link else 'failed'
            
            def upload_pixeldrain():
                nonlocal pixeldrain_link, pixeldrain_state
                if 'pixeldrain' in hosts_to_skip:
                    self.log("Pixeldrain upload skipped (duplicate detected)", "WARNING", host="pixeldrain")
                    pixeldrain_state = 'skipped'
                    self.log("-" * 25, host="pixeldrain")
                elif self.pixeldrain_enabled and not self.pixeldrain_enabled.get():
                    self.log("Pixeldrain upload skipped (disabled)", "WARNING", host="pixeldrain")
                    pixeldrain_state = 'skipped'
                    self.log("-" * 25, host="pixeldrain")
                elif self.pixeldrain_api:
                    pixeldrain_link = self._upload_to_pixeldrain(file_path, package, version, full_name)
                    pixeldrain_state = 'success' if pixeldrain_link else 'failed'

            def upload_apkadmin():
                nonlocal apkadmin_link, apkadmin_state
                if self.apkadmin_enabled and not self.apkadmin_enabled.get():
                    self.log("Apkadmin upload skipped (disabled)", "WARNING", host="apkadmin")
                    apkadmin_state = 'skipped'
                    self.log("-" * 25, host="apkadmin")
                elif self.apkadmin_api:
                    apkadmin_link = self._upload_to_apkadmin(file_path, package, version, full_name)
                    apkadmin_state = 'success' if apkadmin_link else 'failed'

            # Start parallel uploads
            gofile_thread = threading.Thread(target=upload_gofile)
            buzzheavier_thread = threading.Thread(target=upload_buzzheavier)
            pixeldrain_thread = threading.Thread(target=upload_pixeldrain)
            apkadmin_thread = threading.Thread(target=upload_apkadmin)

            gofile_thread.start()
            buzzheavier_thread.start()
            pixeldrain_thread.start()
            apkadmin_thread.start()

            # Wait for all to complete
            gofile_thread.join()
            buzzheavier_thread.join()
            pixeldrain_thread.join()
            apkadmin_thread.join()

            self.last_upload_status = {
                "gofile": bool(gofile_link) if (self.gofile_enabled and self.gofile_enabled.get()) else None,
                "buzzheavier": bool(buzzheavier_link) if (self.buzzheavier_enabled and self.buzzheavier_enabled.get()) else None,
                "pixeldrain": bool(pixeldrain_link) if (self.pixeldrain_enabled and self.pixeldrain_enabled.get()) else None,
                "apkadmin": bool(apkadmin_link) if (self.apkadmin_enabled and self.apkadmin_enabled.get()) else None,
            }

            # Log completion summary with clear status indicators
            self.log("=" * 50, host="general")
            
            # Format status for each host
            def format_status(state):
                if state == 'success':
                    return "✓ SUCCESS"
                elif state == 'skipped':
                    return "○ SKIPPED"
                else:
                    return "✗ FAILED"
            
            gofile_status = format_status(gofile_state)
            buzzheavier_status = format_status(buzzheavier_state)
            pixeldrain_status = format_status(pixeldrain_state)
            
            # Count enabled hosts
            enabled_count = sum([
                bool(self.gofile_enabled and self.gofile_enabled.get()),
                bool(self.buzzheavier_enabled and self.buzzheavier_enabled.get()),
                bool(self.pixeldrain_enabled and self.pixeldrain_enabled.get()),
                bool(self.apkadmin_enabled and self.apkadmin_enabled.get()),
            ])
            success_count = sum([bool(gofile_link), bool(buzzheavier_link), bool(pixeldrain_link), bool(apkadmin_link)])

            # Log status with appropriate color coding
            status_line = f"Gofile: {gofile_status} | Buzzheavier: {buzzheavier_status} | Pixeldrain: {pixeldrain_status} | Apkadmin: {format_status(apkadmin_state)}"
            if success_count == enabled_count:
                self.log(status_line, "SUCCESS", host="general")
            elif success_count > 0:
                self.log(status_line, "WARNING", host="general")
            else:
                self.log(status_line, "ERROR", host="general")
            
            if success_count == enabled_count:
                self.log(f"Upload complete to {success_count} host{'s' if success_count != 1 else ''}!", "SUCCESS", host="general")
            elif success_count > 0:
                self.log(f"Upload complete to {success_count}/{enabled_count} host{'s' if enabled_count != 1 else ''} (check logs)", "WARNING", host="general")
            else:
                self.log(f"Upload failed on all enabled host{'s' if enabled_count != 1 else ''}", "ERROR", host="general")
            self.log("=" * 50, host="general")
            
            self.update_status("Ready - Drop APK file here")

        except (OSError, IOError, RuntimeError) as e:
            self.log(f"Upload failed: {e}", "ERROR", host="general")
            self.update_status("Ready - Drop APK file here")

    def browse_file(self) -> None:
        """Open file dialog to browse for APK file."""
        from tkinter import filedialog
        
        file_path = filedialog.askopenfilename(
            title="Select APK File",
            filetypes=[("APK Files", "*.apk"), ("All Files", "*.*")]
        )
        
        if file_path:
            self._enqueue_files([file_path])

    def _sanitize_dropped_path(self, raw_path: str) -> str:
        """Normalize dropped file paths by trimming whitespace and braces."""
        if not raw_path:
            return ""

        cleaned_path = raw_path.strip()
        if cleaned_path.startswith('{') and cleaned_path.endswith('}'):
            return cleaned_path[1:-1]
        return cleaned_path

    def _start_queue_worker(self) -> None:
        """Start a background worker to process queued files sequentially."""
        with self.queue_lock:
            if self.queue_processing:
                return
            self.queue_processing = True

        worker = threading.Thread(target=self._process_upload_queue, daemon=True)
        worker.start()
        self.queue_thread = worker

    def _enqueue_files(self, file_paths: List[str]) -> None:
        """Enqueue valid APK files and kick off the queue worker if idle."""
        if not file_paths:
            return

        valid_files = []
        seen_paths = set()

        for raw_path in file_paths:
            cleaned_path = self._sanitize_dropped_path(raw_path)
            if not cleaned_path:
                continue

            if cleaned_path in seen_paths:
                continue
            seen_paths.add(cleaned_path)

            if not cleaned_path.lower().endswith('.apk'):
                self.log(f"Skipping non-APK: {cleaned_path}", "ERROR", host="general")
                continue
            if not os.path.exists(cleaned_path):
                self.log(f"Skipping missing file: {cleaned_path}", "ERROR", host="general")
                continue
            if not os.path.isfile(cleaned_path):
                self.log(f"Skipping path (not a file): {cleaned_path}", "ERROR", host="general")
                continue

            valid_files.append(cleaned_path)

        if not valid_files:
            self.log("No valid APK files to upload", "ERROR")
            return

        with self.queue_lock:
            was_processing = self.queue_processing
            for path in valid_files:
                self.upload_queue.append(path)

        self.log(f"Queued {len(valid_files)} file(s) for upload", "INFO")
        
        # Identify newly added files that haven't been scanned
        new_files = [f for f in valid_files if f not in self.scanned_files]
        
        if new_files:
            # Set scanning flag before starting thread to prevent race condition
            with self.queue_lock:
                self.scanning_in_progress = True
                self.scan_complete_event.clear()
            
            self.log(f"Starting duplicate scan for {len(new_files)} new file(s)", "INFO", host="general")
            
            # Start batch duplicate scan in background thread
            scan_thread = threading.Thread(target=self._batch_scan_and_prompt, args=(new_files,))
            scan_thread.daemon = True
            scan_thread.start()
        else:
            # No new files to scan, ensure scan_complete_event is set
            self.log(f"All {len(valid_files)} file(s) already scanned, skipping duplicate check", "INFO", host="general")
            with self.queue_lock:
                self.scanning_in_progress = False
                self.scan_complete_event.set()

        if not was_processing:
            self._start_queue_worker()

    def _process_upload_queue(self) -> None:
        """Drain the upload queue one file at a time."""
        batch_cleared = False
        total_files = 0
        processed_files = 0

        # Wait for any ongoing duplicate scan to complete (with timeout)
        scan_was_in_progress = self.scanning_in_progress
        if scan_was_in_progress:
            self.log("Waiting for duplicate scan to complete...", "INFO", host="general")
            # Wait with 30 second timeout to prevent indefinite hang
            if not self.scan_complete_event.wait(timeout=30.0):
                self.log("Scan timeout - proceeding with upload", "WARNING", host="general")
                with self.queue_lock:
                    self.scanning_in_progress = False
            else:
                self.log("Duplicate scan complete, starting uploads", "INFO", host="general")

        try:
            with self.queue_lock:
                total_files = len(self.upload_queue)
            
            while True:
                with self.queue_lock:
                    if self.abort_uploading:
                        self.queue_processing = False
                        self.log("Upload aborted by user", "WARNING", host="general")
                        self.abort_uploading = False
                        return
                    if not self.upload_queue:
                        self.queue_processing = False
                        # Don't call _clear_duplicate_state here - it will deadlock on queue_lock
                        break
                    next_file = self.upload_queue.popleft()

                if not batch_cleared and self.root:
                    self.root.after(0, self.clear_all)
                    batch_cleared = True

                processed_files += 1
                self.log(f"Processing file {processed_files} of {total_files}", "INFO", host="general")
                self.upload_file(next_file)
            
            # Clear duplicate state after releasing lock
            self._clear_duplicate_state()
            self.log("Upload queue complete", "SUCCESS", host="general")
            
        finally:
            with self.queue_lock:
                self.queue_processing = False
                self.abort_uploading = False

    def on_drop(self, event) -> None:
        """Handle file drop event."""
        files = self.root.tk.splitlist(event.data)

        if files:
            self._enqueue_files(list(files))

    def initialize_api(self) -> None:
        """Initialize API connections for all hosts in parallel."""
        try:
            self.config = load_config()

            # Initialize all APIs in parallel
            gofile_thread = threading.Thread(target=lambda: setattr(self, '_gofile_ready', self._initialize_gofile()))
            buzzheavier_thread = threading.Thread(target=lambda: setattr(self, '_buzzheavier_ready', self._initialize_buzzheavier()))
            pixeldrain_thread = threading.Thread(target=lambda: setattr(self, '_pixeldrain_ready', self._initialize_pixeldrain()))
            apkadmin_thread = threading.Thread(target=lambda: setattr(self, '_apkadmin_ready', self._initialize_apkadmin()))

            self._gofile_ready = False
            self._buzzheavier_ready = False
            self._pixeldrain_ready = False
            self._apkadmin_ready = False

            gofile_thread.start()
            buzzheavier_thread.start()
            pixeldrain_thread.start()
            apkadmin_thread.start()

            # Wait for all to complete
            gofile_thread.join()
            buzzheavier_thread.join()
            pixeldrain_thread.join()
            apkadmin_thread.join()

            # Build folder structures for successful connections
            self.build_folder_structure()
            
            # Load host settings from config after GUI is ready
            if self.root:
                self.root.after(100, self.load_host_settings)
                # Update visibility after loading settings
                self.root.after(200, self.update_visibility)

            # Set ready if at least one host connected
            if self._gofile_ready or self._buzzheavier_ready or self._pixeldrain_ready or self._apkadmin_ready:
                self.is_ready = True
                self.update_status("Ready - Drop APK file here")
                self.log("=" * 50)
                self.log("Ready! Drag and drop APK files here", "SUCCESS")
                self.log("=" * 50)
            else:
                self.update_status("Error - Check credentials")
                self._run_on_gui_thread(lambda: messagebox.showerror(
                    "Connection Error",
                    "Failed to connect to all file hosts.\n\n"
                    "Check your config.json file."))

        except (RuntimeError, KeyError, ValueError, OSError, IOError) as e:
            self.log(f"Initialization error: {e}", "ERROR")
            self.update_status("Error - Check credentials")
            self._run_on_gui_thread(lambda: messagebox.showerror(
                "Connection Error", f"Failed to initialize:\n{e}"))

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
        elif host == "apkadmin":
            link_entry = self.apkadmin_link_entry
        else:
            link_entry = None
            
        link = link_entry.get() if link_entry else ""
        if link:
            self.root.clipboard_clear()
            self.root.clipboard_append(link)
            self.log(f"{host.capitalize()} link copied to clipboard!", "SUCCESS", host=host)

    def copy_file_name(self) -> None:
        """Copy file name to clipboard."""
        if self.file_name_label:
            file_name = self.file_name_label.cget("text")
            if file_name:
                self.root.clipboard_clear()
                self.root.clipboard_append(file_name)

    def copy_file_size(self) -> None:
        """Copy file size to clipboard."""
        if self.file_size_label:
            file_size = self.file_size_label.cget("text")
            if file_size:
                self.root.clipboard_clear()
                self.root.clipboard_append(file_size)

    def _clear_link_entries(self) -> None:
        """Blank every public-link entry. Safe to call from any thread."""
        entries = [
            self.gofile_link_entry,
            self.buzzheavier_link_entry,
            self.pixeldrain_link_entry,
            self.apkadmin_link_entry,
        ]
        present = [e for e in entries if e]
        if present:
            self._run_on_gui_thread(
                lambda: [e.delete(0, tk.END) for e in present]
            )

    def update_file_info(self, file_path: str) -> None:
        """Update file info display with current file name and size."""
        if not self.file_name_label or not self.file_size_label:
            return

        file_name = os.path.basename(file_path)
        file_size_bytes = os.path.getsize(file_path)
        file_size_mb = round(file_size_bytes / (1024 * 1024))

        self._run_on_gui_thread(lambda: (
            self.file_name_label.config(text=file_name),
            self.file_size_label.config(text=f"{file_size_mb} MB"),
        ))

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
        
        if self.apkadmin_enabled and self.apkadmin_enabled.get():
            link = self.apkadmin_link_entry.get() if self.apkadmin_link_entry else ""
            links.append(link if link else "https://apkadmin.com")
        
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
            elif self.apkadmin_enabled and self.apkadmin_enabled.get():
                self.log(f"Copied {len(links)} link(s) to clipboard!", "SUCCESS", host="apkadmin")

    def clear_all(self) -> None:
        """Clear all public links and reset logs."""
        self._reset_all_progress()
        if self.gofile_link_entry:
            self.gofile_link_entry.delete(0, tk.END)
        if self.buzzheavier_link_entry:
            self.buzzheavier_link_entry.delete(0, tk.END)
        if self.pixeldrain_link_entry:
            self.pixeldrain_link_entry.delete(0, tk.END)
        if self.apkadmin_link_entry:
            self.apkadmin_link_entry.delete(0, tk.END)
        
        if self.gofile_log_text:
            self.gofile_log_text.delete(1.0, tk.END)
        if self.buzzheavier_log_text:
            self.buzzheavier_log_text.delete(1.0, tk.END)
        if self.pixeldrain_log_text:
            self.pixeldrain_log_text.delete(1.0, tk.END)
        if self.apkadmin_log_text:
            self.apkadmin_log_text.delete(1.0, tk.END)
        
        if self.log_text and self.log_text != self.gofile_log_text:
            self.log_text.delete(1.0, tk.END)
        
        if self.file_name_label:
            self.file_name_label.config(text="")
        if self.file_size_label:
            self.file_size_label.config(text="")

    def on_abort(self) -> None:
        """Stop any in-progress uploads and clear the pending queue."""
        with self.queue_lock:
            self.abort_uploading = True
            queue_size = len(self.upload_queue)
            self.upload_queue.clear()
        
        if queue_size > 0:
            self.log(f"Cleared {queue_size} pending file(s) from queue", "WARNING")
        
        self.log("Abort requested - stopping uploads", "WARNING")
        self.update_status("Ready - Drop APK file here")
        
        self._update_status_emoji("gofile", "⟳")
        self._update_status_emoji("buzzheavier", "⟳")
        self._update_status_emoji("pixeldrain", "⟳")

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
        elif host == "apkadmin":
            link_entry = self.apkadmin_link_entry
        else:
            link_entry = None

        link = link_entry.get() if link_entry else ""
        if link:
            webbrowser.open(link)
            self.log(f"Opened {host.capitalize()} link in browser", host=host)

    def register_drop_target(self, widget, dnd_files_constant) -> None:
        """Register a widget as a drag-and-drop target."""
        widget.drop_target_register(dnd_files_constant)
        widget.dnd_bind('<<Drop>>', self.on_drop)

    def run(self) -> None:
        """Run the application."""
        try:
            from tkinterdnd2 import TkinterDnD, DND_FILES

            # Recreate root with DnD support
            self.root = TkinterDnD.Tk()
            self.root.title("Gofile Drag & Drop Uploader")
            self.root.geometry(f"{self.WINDOW_WIDTH}x{self.WINDOW_HEIGHT}")

            # Set AppUserModelID for consistent taskbar icon (Windows only)
            try:
                import ctypes
                myappid = 'gofileuploader.dragdrop.1.0'
                ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)
            except (AttributeError, OSError):
                pass

            # Window icon (Windows)
            icon_path = self._resource_path('upload_cloud_file_icon_181534.ico')
            try:
                self.root.iconbitmap(icon_path)
                # Also set as default icon for all windows
                self.root.iconbitmap(default=icon_path)
            except tk.TclError:
                pass

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
            self.main_frame.rowconfigure(4, weight=1)

            # Drop zone
            self.drop_frame = ttk.LabelFrame(
                self.main_frame, text="Drop Zone", padding="20"
            )
            self.drop_frame.grid(row=0, column=0, sticky=(tk.W, tk.E),
                                pady=(0, 10))
            self.drop_frame.columnconfigure(0, weight=1)
            self.drop_frame.configure(cursor="hand2")

            drop_label = ttk.Label(
                self.drop_frame,
                text="📁 Drop APK File Here or Click to Browse",
                font=('Arial', 14, 'bold'),
                anchor=tk.CENTER,
                cursor="hand2"
            )
            drop_label.grid(row=0, column=0, pady=20)

            self.status_label = ttk.Label(
                self.drop_frame,
                text="Initializing...",
                font=('Arial', 10),
                anchor=tk.CENTER,
                cursor="hand2"
            )
            self.status_label.grid(row=1, column=0)

            # Make drop zone clickable
            self.drop_frame.bind("<Button-1>", lambda e: self.browse_file())
            drop_label.bind("<Button-1>", lambda e: self.browse_file())
            self.status_label.bind("<Button-1>", lambda e: self.browse_file())

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
            
            abort_btn = ttk.Button(link_header_frame, text="Abort", 
                                   command=self.on_abort, width=8)
            abort_btn.grid(row=0, column=3, sticky=tk.E, padx=(5, 0))
            Tooltip(abort_btn, "Stop uploads and clear queue")
            
            settings_btn = ttk.Button(link_header_frame, text="⚙️", width=3,
                                     command=self.show_settings_menu)
            settings_btn.grid(row=0, column=4, sticky=tk.E, padx=(5, 0))
            Tooltip(settings_btn, "Select Hosts")

            credentials_btn = ttk.Button(link_header_frame, text="🔑", width=3,
                                        command=self.open_settings_dialog)
            credentials_btn.grid(row=0, column=5, sticky=tk.E, padx=(5, 0))
            Tooltip(credentials_btn, "Edit credentials & settings")
            
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
            self.gofile_status_indicator.grid(row=0, column=0, sticky=tk.W)

            self.gofile_status_label = ttk.Label(gofile_status_frame, text=" Gofile:",
                                                  font=('Arial', 9, 'bold'))
            self.gofile_status_label.grid(row=0, column=1, sticky=tk.W)
            self._create_host_progress_bar('gofile', gofile_status_frame)
            
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
            self.buzzheavier_status_indicator.grid(row=0, column=0, sticky=tk.W)

            self.buzzheavier_status_label = ttk.Label(buzzheavier_status_frame, text=" Buzzheavier:",
                                                        font=('Arial', 9, 'bold'))
            self.buzzheavier_status_label.grid(row=0, column=1, sticky=tk.W)
            self._create_host_progress_bar('buzzheavier', buzzheavier_status_frame)

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
            self.pixeldrain_status_indicator.grid(row=0, column=0, sticky=tk.W)

            self.pixeldrain_status_label = ttk.Label(pixeldrain_status_frame, text=" Pixeldrain:",
                                                       font=('Arial', 9, 'bold'))
            self.pixeldrain_status_label.grid(row=0, column=1, sticky=tk.W)
            self._create_host_progress_bar('pixeldrain', pixeldrain_status_frame)

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

            # Apkadmin row
            self.apkadmin_enabled = tk.BooleanVar(value=False)

            self.apkadmin_status_frame = ttk.Frame(self.link_frame)
            self.apkadmin_status_frame.grid(row=3, column=0, sticky=tk.W, padx=(0, 5), pady=(5, 0))
            apkadmin_status_frame = self.apkadmin_status_frame

            self.apkadmin_status_indicator = ttk.Label(apkadmin_status_frame, text="⏳",
                                                        font=('Arial', 9, 'bold'), foreground="orange")
            self.apkadmin_status_indicator.grid(row=0, column=0, sticky=tk.W)

            self.apkadmin_status_label = ttk.Label(apkadmin_status_frame, text=" Apkadmin:",
                                                    font=('Arial', 9, 'bold'))
            self.apkadmin_status_label.grid(row=0, column=1, sticky=tk.W)
            Tooltip(self.apkadmin_status_label,
                    "Scraping-based host. Requires manual cookie refresh from browser. See docs/APKADMIN_SETUP.md")
            self._create_host_progress_bar('apkadmin', apkadmin_status_frame)

            self.apkadmin_link_entry = ttk.Entry(self.link_frame, font=('Arial', 9))
            self.apkadmin_link_entry.grid(row=3, column=1, sticky=(tk.W, tk.E), padx=(0, 5), pady=(5, 0))

            self.apkadmin_buttons_frame = ttk.Frame(self.link_frame)
            self.apkadmin_buttons_frame.grid(row=3, column=2, pady=(5, 0))
            apkadmin_buttons = self.apkadmin_buttons_frame

            apkadmin_copy_btn = ttk.Button(apkadmin_buttons, text="Copy",
                                           command=lambda: self.copy_link("apkadmin"), width=6)
            apkadmin_copy_btn.grid(row=0, column=0, padx=2)

            apkadmin_open_btn = ttk.Button(apkadmin_buttons, text="Open",
                                           command=lambda: self.open_link("apkadmin"), width=6)
            apkadmin_open_btn.grid(row=0, column=1, padx=2)

            apkadmin_retry_btn = ttk.Button(apkadmin_buttons, text="Retry",
                                            command=self.retry_apkadmin, width=6)
            apkadmin_retry_btn.grid(row=0, column=2, padx=2)

            self.file_info_frame = ttk.Frame(self.main_frame, padding="0")
            self.file_info_frame.grid(row=3, column=0, sticky=(tk.W, tk.E), pady=(0, 2))
            self.file_info_frame.columnconfigure(0, weight=1)
            self.file_info_frame.columnconfigure(1, weight=1)

            # File name box
            file_name_box = ttk.Frame(self.file_info_frame, padding="5")
            file_name_box.grid(row=0, column=0, sticky=(tk.W, tk.E), padx=(0, 5))
            file_name_box.columnconfigure(0, weight=0)
            file_name_box.columnconfigure(1, weight=1)

            file_name_label_header = ttk.Label(file_name_box, text="File Name", font=('Arial', 8, 'bold'))
            file_name_label_header.grid(row=0, column=0, columnspan=2, sticky=tk.W, pady=(0, 3))

            copy_name_btn = ttk.Button(file_name_box, text="📋", width=3,
                                       command=self.copy_file_name)
            copy_name_btn.grid(row=1, column=0, padx=(0, 5))

            self.file_name_label = ttk.Label(file_name_box, text="", font=('Arial', 9))
            self.file_name_label.grid(row=1, column=1, sticky=(tk.W, tk.E))
            Tooltip(copy_name_btn, "Copy file name")

            # File size box
            file_size_box = ttk.Frame(self.file_info_frame, padding="5")
            file_size_box.grid(row=0, column=1, sticky=(tk.W, tk.E))
            file_size_box.columnconfigure(0, weight=0)
            file_size_box.columnconfigure(1, weight=1)

            file_size_label_header = ttk.Label(file_size_box, text="File Size", font=('Arial', 8, 'bold'))
            file_size_label_header.grid(row=0, column=0, columnspan=2, sticky=tk.W, pady=(0, 3))

            copy_size_btn = ttk.Button(file_size_box, text="📋", width=3,
                                       command=self.copy_file_size)
            copy_size_btn.grid(row=1, column=0, padx=(0, 5))

            self.file_size_label = ttk.Label(file_size_box, text="", font=('Arial', 9))
            self.file_size_label.grid(row=1, column=1, sticky=(tk.W, tk.E))
            Tooltip(copy_size_btn, "Copy file size")

            # Log frame (quad-column with dynamic visibility)
            self.log_frame = ttk.LabelFrame(self.main_frame, text="Activity Logs", padding="10")
            self.log_frame.grid(row=4, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
            self.log_frame.columnconfigure(0, weight=1)
            self.log_frame.columnconfigure(1, weight=1)
            self.log_frame.columnconfigure(2, weight=1)
            self.log_frame.columnconfigure(3, weight=1)
            self.log_frame.rowconfigure(1, weight=1)
            self.log_frame.rowconfigure(3, weight=1)

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

            # Apkadmin log column
            self.apkadmin_log_label = ttk.Label(self.log_frame, text="Apkadmin", font=('Arial', 9, 'bold'))
            self.apkadmin_log_label.grid(row=0, column=3, sticky=tk.W, pady=(0, 5))

            self.apkadmin_log_text = scrolledtext.ScrolledText(self.log_frame, height=15,
                                                               font=('Consolas', 8),
                                                               wrap=tk.WORD)
            self.apkadmin_log_text.grid(row=1, column=3, sticky=(tk.W, tk.E, tk.N, tk.S))

            # Color tags for Apkadmin log
            self.apkadmin_log_text.tag_config("success", foreground="green")
            self.apkadmin_log_text.tag_config("error", foreground="red")

            # General log (bottom row, spanning all columns)
            self.general_log_label = ttk.Label(self.log_frame, text="General", font=('Arial', 9, 'bold'))
            self.general_log_label.grid(row=2, column=0, columnspan=4, sticky=tk.W, pady=(10, 5))

            self.general_log_text = scrolledtext.ScrolledText(self.log_frame, height=8,
                                                              font=('Consolas', 8),
                                                              wrap=tk.WORD)
            self.general_log_text.grid(row=3, column=0, columnspan=4, sticky=(tk.W, tk.E, tk.N, tk.S))

            # Color tags for General log
            self.general_log_text.tag_config("success", foreground="green")
            self.general_log_text.tag_config("error", foreground="red")

            # Start draining worker-thread GUI updates before any thread runs
            self.root.after(self.GUI_QUEUE_POLL_MS, self._pump_gui_queue)

            # Initialize API in separate thread
            init_thread = threading.Thread(target=self.initialize_api)
            init_thread.daemon = True
            init_thread.start()

            # Start system tray icon
            self._start_tray_icon()

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

