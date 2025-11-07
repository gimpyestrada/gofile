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
from typing import Dict, List, Optional
import threading
from gofile_api import GofileAPI
from config_loader import load_config


class DragDropUploader:
    """Drag and drop uploader with GUI."""
    
    FOLDER_CACHE_FILE = "folder_structure_cache.json"
    CACHE_EXPIRY_HOURS = 24
    
    def __init__(self):
        """Initialize the uploader."""
        self.api = None
        self.root_folder_id = None
        self.folder_structure = {}  # package -> parent_folder_id
        self.cache_data = None
        self.config = None
        
        # GUI components
        self.root = None
        self.log_text = None
        self.status_label = None
        self.link_entry = None
        self.is_ready = False
        self.mini_mode = None  # Will be set after root window created
        
        # Store frames for show/hide
        self.main_frame = None
        self.drop_frame = None
        self.link_frame = None
        self.log_frame = None
        self.mini_frame = None
        
    def log(self, message: str, level: str = "INFO") -> None:
        """
        Log message to GUI and print.
        
        Args:
            message: Message to log
            level: Log level (INFO, SUCCESS, ERROR, WARNING)
        """
        timestamp = datetime.now().strftime("%H:%M:%S")
        formatted_msg = f"[{timestamp}] {message}\n"
        
        print(message)
        
        if self.log_text:
            self.log_text.insert(tk.END, formatted_msg)
            self.log_text.see(tk.END)
            
            # Color coding
            if level == "SUCCESS":
                line_start = self.log_text.index("end-2c linestart")
                line_end = self.log_text.index("end-1c lineend")
                self.log_text.tag_add("success", line_start, line_end)
            elif level == "ERROR":
                line_start = self.log_text.index("end-2c linestart")
                line_end = self.log_text.index("end-1c lineend")
                self.log_text.tag_add("error", line_start, line_end)
    
    def update_status(self, message: str) -> None:
        """Update status label in both normal and mini mode."""
        if self.status_label:
            self.status_label.config(text=message)
        if hasattr(self, 'mini_status_label') and self.mini_status_label:
            core_status = message.split(' - ')[-1] if ' - ' in message else message
            self.mini_status_label.config(text=core_status)
    
    def parse_apk_filename(self, filename: str) -> Optional[Dict[str, str]]:
        """
        Parse APK filename to extract package name and version.
        
        Args:
            filename: APK filename
        
        Returns:
            Dict with 'package', 'version', 'full_name' or None
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
    
    def load_folder_cache(self) -> Optional[Dict]:
        """Load cached folder structure."""
        cache_path = Path(self.FOLDER_CACHE_FILE)
        
        if not cache_path.exists():
            return None
        
        try:
            with open(cache_path, 'r', encoding='utf-8') as f:
                cache_data = json.load(f)
            
            cache_time = datetime.fromisoformat(cache_data.get('timestamp', ''))
            cache_age = datetime.now() - cache_time
            
            if cache_age > timedelta(hours=self.CACHE_EXPIRY_HOURS):
                return None
            
            if cache_data.get('root_folder_id') != self.root_folder_id:
                return None
            
            return cache_data
            
        except Exception as e:
            self.log(f"Error loading cache: {e}", "ERROR")
            return None
    
    def build_folder_structure(self) -> None:
        """Build mapping of package names to parent folder IDs."""
        self.log("Building folder structure...")
        
        self.cache_data = self.load_folder_cache()
        
        if self.cache_data:
            self.log("Using cached folder structure")
            folders = self.cache_data.get('folders', {})
            
            for folder_id, folder_info in folders.items():
                parsed = folder_info.get('parsed', {})
                folder_type = parsed.get('type')
                
                if folder_type == 'parent':
                    package = parsed.get('package')
                    if package:
                        self.folder_structure[package] = folder_id
            
            self.log(f"Loaded {len(self.folder_structure)} parent folders from cache", "SUCCESS")
        else:
            self.log("No cache found - scanning Gofile...")
            
            try:
                root_contents = self.api.get_content(self.root_folder_id)
                children = root_contents.get('children', {})
                
                folders = [(cid, cdata) for cid, cdata in children.items() 
                          if cdata.get('type') == 'folder']
                
                for folder_id, folder_data in folders:
                    folder_name = folder_data.get('name')
                    
                    # Check if it's a parent folder (package name without version)
                    if folder_name.count('.') >= 2 and '-' not in folder_name:
                        self.folder_structure[folder_name] = folder_id
                
                self.log(f"Found {len(self.folder_structure)} parent folders", "SUCCESS")
                
            except Exception as e:
                self.log(f"Error scanning folders: {e}", "ERROR")
    
    def create_parent_folder(self, package: str) -> Optional[str]:
        """
        Create a new parent folder for a package.
        
        Args:
            package: Package name
        
        Returns:
            Parent folder ID or None
        """
        try:
            self.log(f"Creating parent folder: {package}")
            result = self.api.create_folder(self.root_folder_id, package)
            parent_id = result.get('id')
            self.log(f"Created parent folder with ID: {parent_id}", "SUCCESS")
            
            # Add to structure
            self.folder_structure[package] = parent_id
            
            time.sleep(2)
            return parent_id
            
        except Exception as e:
            self.log(f"Error creating parent folder: {e}", "ERROR")
            return None
    
    def create_version_folder(self, parent_id: str, version_folder_name: str) -> Optional[str]:
        """
        Create or get version folder.
        
        Args:
            parent_id: Parent folder ID
            version_folder_name: Name of version folder
        
        Returns:
            Version folder ID or None
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
            
            time.sleep(2)
            return version_id
            
        except Exception as e:
            self.log(f"Error with version folder: {e}", "ERROR")
            self.log("This may indicate the parent folder no longer exists or the cache is stale", "WARNING")
            return None
    
    def make_folder_public(self, folder_id: str) -> bool:
        """
        Make a folder public.
        
        Args:
            folder_id: Folder ID to make public
        
        Returns:
            True if successful
        """
        try:
            self.log("Setting folder to public...")
            self.api.update_content(folder_id, 'public', 'true')
            time.sleep(1)
            return True
        except Exception as e:
            self.log(f"Error making folder public: {e}", "ERROR")
            return False
    
    def get_folder_link(self, folder_id: str) -> Optional[str]:
        """
        Get public link for a folder.
        
        Args:
            folder_id: Folder ID
        
        Returns:
            Public link or None
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
                
        except Exception as e:
            self.log(f"Error getting folder link: {e}", "ERROR")
            return None
    
    def upload_file(self, file_path: str) -> None:
        """
        Upload file to appropriate folder.
        
        Args:
            file_path: Path to file to upload
        """
        self.update_status("Processing...")
        self.link_entry.delete(0, tk.END)
        
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
            
            # Get or create parent folder
            parent_id = self.folder_structure.get(package)
            
            if not parent_id:
                self.log(f"No parent folder found for {package}", "WARNING")
                parent_id = self.create_parent_folder(package)
                
                if not parent_id:
                    self.log("Failed to create parent folder", "ERROR")
                    self.update_status("Ready - Drop APK file here")
                    return
            else:
                self.log(f"Found parent folder: {package}")
            
            # Create or get version folder
            version_id = self.create_version_folder(parent_id, full_name)
            
            if not version_id:
                self.log("Failed to create/get version folder", "ERROR")
                self.log("Attempting to recreate parent folder...", "WARNING")
                
                # Try recreating parent folder (cache might be stale)
                parent_id = self.create_parent_folder(package)
                
                if parent_id:
                    self.log("Parent folder recreated, retrying version folder creation...", "INFO")
                    version_id = self.create_version_folder(parent_id, full_name)
                
                if not version_id:
                    self.log("Failed after retry - cannot proceed", "ERROR")
                    self.update_status("Ready - Drop APK file here")
                    return
            
            # Upload file
            file_size_bytes = os.path.getsize(file_path)
            file_size_mb = file_size_bytes / (1024 * 1024)
            self.log(f"Uploading file ({file_size_mb:.2f} MB)...")
            self.update_status(f"Uploading {filename}...")
            
            start_time = time.time()
            result = self.api.upload_file(file_path, folder_id=version_id)
            upload_time = time.time() - start_time
            
            # Calculate upload speed
            upload_speed_mbps = (file_size_bytes * 8) / (upload_time * 1_000_000)  # Megabits per second
            upload_speed_MBps = file_size_mb / upload_time  # Megabytes per second
            
            self.log(f"Upload complete! ({upload_time:.1f} seconds)", "SUCCESS")
            self.log(f"Upload speed: {upload_speed_MBps:.2f} MB/s ({upload_speed_mbps:.2f} Mbps)", "SUCCESS")
            self.log(f"File ID: {result.get('fileId')}")
            
            # Make version folder public
            self.log("Making folder public...")
            if self.make_folder_public(version_id):
                self.log("Folder is now public", "SUCCESS")
            
            # Get public link
            self.log("Getting public link...")
            link = self.get_folder_link(version_id)
            
            if link:
                self.log(f"Public link: {link}", "SUCCESS")
                self.link_entry.delete(0, tk.END)
                self.link_entry.insert(0, link)
                
                # Copy to clipboard
                self.root.clipboard_clear()
                self.root.clipboard_append(link)
                self.log("Link copied to clipboard!", "SUCCESS")
            else:
                self.log("Could not retrieve public link", "ERROR")
            
            self.log("=" * 50)
            self.update_status("Ready - Drop APK file here")
            
        except Exception as e:
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
    
    def initialize_api(self) -> None:
        """Initialize Gofile API connection."""
        try:
            self.log("Connecting to Gofile...")
            self.config = load_config()
            self.api = GofileAPI(api_token=self.config.api_token)
            
            account_details = self.api.get_account_details(self.config.account_id)
            self.root_folder_id = account_details.get('rootFolder')
            
            email = account_details.get('email')
            tier = account_details.get('tier')
            
            self.log(f"Connected to Gofile account", "SUCCESS")
            self.log(f"Email: {email}")
            self.log(f"Tier: {tier}")
            
            # Build folder structure
            self.build_folder_structure()
            
            self.is_ready = True
            self.update_status("Ready - Drop APK file here")
            self.log("=" * 50)
            self.log("Ready! Drag and drop APK files here", "SUCCESS")
            self.log("=" * 50)
            
        except Exception as e:
            self.log(f"Failed to connect to Gofile: {e}", "ERROR")
            self.update_status("Error - Check credentials")
            messagebox.showerror("Connection Error", 
                               f"Failed to connect to Gofile:\n{e}\n\nCheck your config.json file.")
    
    def copy_link(self) -> None:
        """Copy link to clipboard."""
        link = self.link_entry.get()
        if link:
            self.root.clipboard_clear()
            self.root.clipboard_append(link)
            self.log("Link copied to clipboard!", "SUCCESS")
    
    def open_link(self) -> None:
        """Open link in browser."""
        link = self.link_entry.get()
        if link:
            import webbrowser
            webbrowser.open(link)
            self.log("Opened link in browser")
    
    def toggle_mini_mode(self) -> None:
        """Toggle between normal and mini mode."""
        if self.mini_mode.get():
            # Switch to mini mode
            self.main_frame.grid_remove()
            self.mini_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
            self.root.geometry("200x190")
            self.root.attributes('-topmost', True)
        else:
            # Switch to normal mode
            self.mini_frame.grid_remove()
            self.main_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
            self.root.geometry("700x600")
            self.root.attributes('-topmost', False)
    
    def run(self) -> None:
        """Run the application."""
        try:
            from tkinterdnd2 import TkinterDnD, DND_FILES
            
            # Recreate root with DnD support
            self.root = TkinterDnD.Tk()
            self.root.title("Gofile Drag & Drop Uploader")
            self.root.geometry("700x600")
            
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
            self.main_frame.rowconfigure(2, weight=1)
            
            # Drop zone
            self.drop_frame = ttk.LabelFrame(self.main_frame, text="Drop Zone", padding="20")
            self.drop_frame.grid(row=0, column=0, sticky=(tk.W, tk.E), pady=(0, 10))
            self.drop_frame.columnconfigure(0, weight=1)
            
            drop_label = ttk.Label(self.drop_frame, text="📁 Drag & Drop APK Files Here", 
                                  font=('Arial', 14, 'bold'),
                                  anchor=tk.CENTER)
            drop_label.grid(row=0, column=0, pady=20)
            
            self.status_label = ttk.Label(self.drop_frame, text="Initializing...", 
                                         font=('Arial', 10),
                                         anchor=tk.CENTER)
            self.status_label.grid(row=1, column=0)
            
            # Mini mode checkbox
            mini_check = ttk.Checkbutton(self.drop_frame, text="Mini Mode (Always on Top)", 
                                        variable=self.mini_mode, 
                                        command=self.toggle_mini_mode)
            mini_check.grid(row=2, column=0, pady=(10, 0))
            
            # Enable drag and drop on drop frame
            self.drop_frame.drop_target_register(DND_FILES)
            self.drop_frame.dnd_bind('<<Drop>>', self.on_drop)
            
            # Link frame
            self.link_frame = ttk.LabelFrame(self.main_frame, text="Public Link", padding="10")
            self.link_frame.grid(row=1, column=0, sticky=(tk.W, tk.E), pady=(0, 10))
            self.link_frame.columnconfigure(0, weight=1)
            
            self.link_entry = ttk.Entry(self.link_frame, font=('Arial', 10))
            self.link_entry.grid(row=0, column=0, sticky=(tk.W, tk.E), padx=(0, 5))
            
            link_buttons_frame = ttk.Frame(self.link_frame)
            link_buttons_frame.grid(row=0, column=1)
            
            copy_btn = ttk.Button(link_buttons_frame, text="Copy", command=self.copy_link, width=8)
            copy_btn.grid(row=0, column=0, padx=2)
            
            open_btn = ttk.Button(link_buttons_frame, text="Open", command=self.open_link, width=8)
            open_btn.grid(row=0, column=1, padx=2)
            
            # Log frame
            self.log_frame = ttk.LabelFrame(self.main_frame, text="Activity Log", padding="10")
            self.log_frame.grid(row=2, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
            self.log_frame.columnconfigure(0, weight=1)
            self.log_frame.rowconfigure(0, weight=1)
            
            self.log_text = scrolledtext.ScrolledText(self.log_frame, height=15, 
                                                      font=('Consolas', 9),
                                                      wrap=tk.WORD)
            self.log_text.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
            
            # Color tags
            self.log_text.tag_config("success", foreground="green")
            self.log_text.tag_config("error", foreground="red")
            
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
            self.mini_status_label = ttk.Label(mini_drop_frame, text="Ready", 
                                              font=('Arial', 8),
                                              anchor=tk.CENTER)
            self.mini_status_label.grid(row=2, column=0)
            
            # Enable drag and drop on mini frame
            mini_drop_frame.drop_target_register(DND_FILES)
            mini_drop_frame.dnd_bind('<<Drop>>', self.on_drop)
            mini_drop_label.drop_target_register(DND_FILES)
            mini_drop_label.dnd_bind('<<Drop>>', self.on_drop)
            
            # Mini buttons frame
            mini_buttons = ttk.Frame(self.mini_frame)
            mini_buttons.grid(row=1, column=0, pady=(5, 0))
            
            mini_copy_btn = ttk.Button(mini_buttons, text="Copy Link", 
                                      command=self.copy_link, width=10)
            mini_copy_btn.grid(row=0, column=0, padx=2)
            
            # Normal mode checkbox
            normal_check = ttk.Checkbutton(mini_buttons, text="Normal", 
                                          variable=self.mini_mode, 
                                          command=self.toggle_mini_mode)
            normal_check.grid(row=0, column=1, padx=2)
            
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
