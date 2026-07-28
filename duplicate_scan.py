"""
Duplicate detection for queued uploads.

Files are scanned against every enabled host up front so the user answers one
dialog for the whole batch instead of being interrupted per file. Mixed into
DragDropUploader: these methods drive the GUI and the queue state that the
uploader owns.
"""

import os
import tkinter as tk
from tkinter import ttk
from typing import Dict, List, Optional


# Per-file choices offered in the batch decision dialog.
DUPLICATE_ACTIONS = ["skip", "overwrite", "upload_again"]


class DuplicateScanMixin:
    """Find files that already exist on a host and ask what to do about them."""

    def _detect_duplicates(self, file_path: str, package: str, full_name: str) -> Dict[str, Dict[str, Optional[str]]]:
        """
        Check each enabled host for an already existing file and/or folder.

        Returns a dict per host with keys: {'folder_id', 'file_id'} when found.
        """
        filename = os.path.basename(file_path)
        version_folder_name = self._normalize_version_folder_name(full_name)
        alt_names = [full_name] if full_name != version_folder_name else None

        results: Dict[str, Dict[str, Optional[str]]] = {}

        # Gofile
        if self.gofile_enabled and self.gofile_enabled.get() and self.api and self.root_folder_id:
            folder_id = self.folder_structure.get(package)
            version_id = None
            file_id = None
            if folder_id:
                version_id = self._find_existing_version_folder(folder_id, version_folder_name, alt_names)
                if version_id:
                    try:
                        contents = self.api.get_content(version_id)
                        for cid, cdata in contents.get('children', {}).items():
                            if cdata.get('type') == 'file' and cdata.get('name') == filename:
                                file_id = cid
                                break
                    except (RuntimeError, KeyError, ValueError, OSError, IOError):
                        pass
            if version_id or file_id:
                results['gofile'] = {'folder_id': version_id, 'file_id': file_id}

        # Buzzheavier
        if self.buzzheavier_enabled and self.buzzheavier_enabled.get() and self.buzzheavier_api and self.buzzheavier_root_folder_id:
            parent_id = self.buzzheavier_folder_structure.get(package)
            version_id = None
            file_id = None
            try:
                if parent_id:
                    parent_contents = self.buzzheavier_api.get_content(parent_id)
                    children = parent_contents.get('children', [])
                    # Find existing version folder (normalized or legacy)
                    candidate_names = [version_folder_name] + ([full_name] if full_name != version_folder_name else [])
                    version_folder = next((c for c in children if c.get('isDirectory') and c.get('name') in candidate_names), None)
                    if version_folder:
                        version_id = version_folder.get('id')
                        # Check for existing file by name
                        v_contents = self.buzzheavier_api.get_content(version_id)
                        v_children = v_contents.get('children', [])
                        existing_file = next((c for c in v_children if not c.get('isDirectory') and c.get('name') == filename), None)
                        if existing_file:
                            file_id = existing_file.get('id')
                if version_id or file_id:
                    results['buzzheavier'] = {'folder_id': version_id, 'file_id': file_id}
            except (RuntimeError, KeyError, ValueError, OSError, IOError):
                pass

        # Pixeldrain (flat, check by filename in user files)
        if self.pixeldrain_enabled and self.pixeldrain_enabled.get() and self.pixeldrain_api:
            try:
                user_files = self.pixeldrain_api.get_user_files()
                files = user_files.get('files', [])
                existing = next((f for f in files if f.get('name') == filename), None)
                if existing:
                    results['pixeldrain'] = {'folder_id': None, 'file_id': existing.get('id')}
            except (RuntimeError, KeyError, ValueError, OSError, IOError):
                pass

        return results

    def _prompt_duplicate_action(self, hosts: List[str], package: str = "") -> Optional[str]:
        """
        Ask user to choose Overwrite (delete then upload), Upload again, or Skip.
        Returns 'overwrite', 'upload', or 'cancel'.
        """
        msg = (
            f"Package: {package}\n\n"
            "Duplicates detected on: " + ", ".join([h.capitalize() for h in hosts]) + "\n\n"
            "Overwrite = Delete then upload\n"
            "Upload Again = Upload a second copy\n"
            "Skip = Abort"
        )

        root = tk.Tk()
        root.withdraw()

        result = [None]

        def on_overwrite():
            result[0] = "overwrite"
            dialog.destroy()

        def on_upload():
            result[0] = "upload"
            dialog.destroy()

        def on_skip():
            result[0] = "cancel"
            dialog.destroy()

        dialog = tk.Toplevel(root)
        dialog.title("Duplicates Detected")
        dialog.geometry("400x200")
        dialog.resizable(False, False)

        label = tk.Label(dialog, text=msg, justify=tk.LEFT, wraplength=350, padx=20, pady=20)
        label.pack()

        button_frame = tk.Frame(dialog)
        button_frame.pack(pady=10)

        tk.Button(button_frame, text="Overwrite", command=on_overwrite, width=12).pack(side=tk.LEFT, padx=5)
        tk.Button(button_frame, text="Upload Again", command=on_upload, width=12).pack(side=tk.LEFT, padx=5)
        tk.Button(button_frame, text="Skip", command=on_skip, width=12).pack(side=tk.LEFT, padx=5)

        root.after(0, dialog.lift)
        root.after(0, dialog.focus)
        root.wait_window(dialog)
        root.destroy()

        return result[0]

    def _batch_scan_duplicates(self, file_list: List[str]) -> Dict[str, Dict[str, Dict[str, Optional[str]]]]:
        """
        Scan multiple files for duplicates across all enabled hosts.

        Returns dict: {file_path: {host: {'folder_id': ..., 'file_id': ...}}}
        """
        duplicates_found = {}
        total = len(file_list)

        for idx, file_path in enumerate(file_list, start=1):
            filename = os.path.basename(file_path)

            # Update progress dialog on GUI thread
            if self.root:
                self.root.after(0, self._update_scan_progress, idx, total, filename)

            # Parse filename to get package and version info
            parsed = self.parse_apk_filename(filename)
            if not parsed:
                continue

            package = parsed['package']
            full_name = parsed['full_name']

            # Use existing duplicate detection logic
            try:
                dups = self._detect_duplicates(file_path, package, full_name)
                if dups:
                    duplicates_found[file_path] = dups
            except Exception as e:  # pylint: disable=broad-except
                self.log(f"Error checking duplicates for {filename}: {e}", "WARNING", host="general")
                continue

        return duplicates_found

    def _show_scan_progress_dialog(self):
        """Create and show the scanning progress dialog."""
        if self.scan_progress_window:
            return

        self.scan_progress_window = tk.Toplevel(self.root)
        self.scan_progress_window.title("Scanning for Duplicates")
        self.scan_progress_window.geometry("450x120")
        self.scan_progress_window.resizable(False, False)
        self.scan_progress_window.transient(self.root)

        frame = tk.Frame(self.scan_progress_window, padx=20, pady=20)
        frame.pack(fill=tk.BOTH, expand=True)

        self.scan_status_label = tk.Label(frame, text="Scanning for duplicates...", font=("Arial", 10))
        self.scan_status_label.pack(pady=(0, 10))

        self.scan_file_label = tk.Label(frame, text="", font=("Arial", 9), fg="gray")
        self.scan_file_label.pack()

    def _update_scan_progress(self, current: int, total: int, filename: str):
        """Update the scan progress dialog."""
        if not self.scan_progress_window:
            self._show_scan_progress_dialog()

        if self.scan_progress_window:
            self.scan_status_label.config(text=f"Checking file {current} of {total} for duplicates...")
            self.scan_file_label.config(text=filename)

    def _close_scan_progress_dialog(self):
        """Close the scanning progress dialog."""
        if self.scan_progress_window:
            self.scan_progress_window.destroy()
            self.scan_progress_window = None

    def _batch_scan_and_prompt(self, file_list: List[str]):
        """
        Batch scan files for duplicates and prompt user for decisions.
        Runs in background thread but signals queue processor to wait.
        """
        # scanning_in_progress is already set by _enqueue_files

        # Show progress dialog
        if self.root:
            self.root.after(0, self._show_scan_progress_dialog)

        # Scan all files
        duplicates_found = self._batch_scan_duplicates(file_list)

        # Mark all files as scanned
        for file_path in file_list:
            self.scanned_files.add(file_path)

        # Close progress dialog
        if self.root:
            self.root.after(0, self._close_scan_progress_dialog)

        # If duplicates found, schedule dialog on main thread (non-blocking)
        if duplicates_found:
            if self.root:
                # Schedule dialog and pass completion callback
                self.root.after(0, lambda: self._show_duplicate_decision_dialog_and_continue(duplicates_found))
        else:
            self.log(f"No duplicates found for {len(file_list)} file(s)", "INFO", host="general")
            self._finish_scanning()

    def _finish_scanning(self):
        """
        Release the queue worker waiting on the scan.

        Every exit path from the scan must reach this, including dialog
        failures, or the queue blocks forever on scan_complete_event.
        """
        with self.queue_lock:
            self.scanning_in_progress = False
            self.scan_complete_event.set()

    def _show_duplicate_decision_dialog_and_continue(self, duplicates_dict: Dict[str, Dict[str, Dict[str, Optional[str]]]]):
        """
        Show dialog on main thread and signal completion when done.
        This runs on the main GUI thread.
        """
        if not duplicates_dict:
            self._finish_scanning()
            return

        try:
            dialog = tk.Toplevel(self.root)
            dialog.title("Duplicate Files Detected")

            # Set size and center on screen
            dialog_width = 700
            dialog_height = 500
            screen_width = dialog.winfo_screenwidth()
            screen_height = dialog.winfo_screenheight()
            x = (screen_width - dialog_width) // 2
            y = (screen_height - dialog_height) // 2
            dialog.geometry(f"{dialog_width}x{dialog_height}+{x}+{y}")
            dialog.resizable(True, True)

            # Make dialog modal
            dialog.transient(self.root)
            dialog.grab_set()

            # Header
            header = tk.Label(
                dialog,
                text="The following files already exist on one or more hosts.\nChoose an action for each file:",
                font=("Arial", 10, "bold"),
                justify=tk.LEFT,
                padx=10,
                pady=10
            )
            header.pack(anchor=tk.W)

            # Scrollable frame for file list
            canvas = tk.Canvas(dialog)
            scrollbar = tk.Scrollbar(dialog, orient="vertical", command=canvas.yview)
            scrollable_frame = tk.Frame(canvas)

            scrollable_frame.bind(
                "<Configure>",
                lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
            )

            canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
            canvas.configure(yscrollcommand=scrollbar.set)

            # Store dropdown variables and widgets for each file
            file_decisions = {}
            file_comboboxes = {}

            # Create row for each duplicate file
            for file_path, hosts_dict in duplicates_dict.items():
                filename = os.path.basename(file_path)
                hosts = [h.capitalize() for h in hosts_dict.keys()]

                row_frame = tk.Frame(scrollable_frame, relief=tk.RIDGE, borderwidth=1, padx=10, pady=8)
                row_frame.pack(fill=tk.X, padx=10, pady=5)

                # File info
                info_frame = tk.Frame(row_frame)
                info_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

                name_label = tk.Label(info_frame, text=filename, font=("Arial", 9, "bold"), anchor=tk.W)
                name_label.pack(anchor=tk.W)

                hosts_label = tk.Label(info_frame, text=f"Duplicates on: {', '.join(hosts)}", font=("Arial", 8), fg="gray", anchor=tk.W)
                hosts_label.pack(anchor=tk.W)

                # Action dropdown
                action_var = tk.StringVar(value="skip")
                file_decisions[file_path] = action_var

                action_menu = ttk.Combobox(
                    row_frame,
                    textvariable=action_var,
                    values=DUPLICATE_ACTIONS,
                    state="readonly",
                    width=15
                )
                action_menu.pack(side=tk.RIGHT, padx=5)
                file_comboboxes[file_path] = action_menu

            canvas.pack(side="left", fill="both", expand=True, padx=(10, 0), pady=10)
            scrollbar.pack(side="right", fill="y", pady=10, padx=(0, 10))

            # Button frame
            button_frame = tk.Frame(dialog)
            button_frame.pack(pady=10)

            def apply_to_all(action: str):
                """Apply the same action to all files."""
                for file_path in file_decisions.keys():
                    file_decisions[file_path].set(action)
                    file_comboboxes[file_path].current(DUPLICATE_ACTIONS.index(action))
                dialog.update_idletasks()

            def on_confirm():
                """Store decisions, close dialog, and signal completion."""
                for file_path, var in file_decisions.items():
                    action = var.get()
                    # Store decision for each host that has duplicates
                    self.duplicate_decisions[file_path] = {}
                    for host in duplicates_dict[file_path].keys():
                        self.duplicate_decisions[file_path][host] = action

                self.log(f"Duplicate decisions recorded for {len(file_decisions)} file(s)", "INFO", host="general")
                dialog.destroy()

                self._finish_scanning()

            def on_cancel():
                """Cancel upload, clear queue, and reset to ready state."""
                with self.queue_lock:
                    queue_size = len(self.upload_queue)
                    self.upload_queue.clear()
                    self.duplicate_decisions.clear()
                    self.scanned_files.clear()
                    self.scanning_in_progress = False
                    self.scan_complete_event.set()

                self.log(f"Upload cancelled, cleared {queue_size} file(s) from queue", "INFO", host="general")
                self.update_status("Ready - Drop APK file here")
                dialog.destroy()

            # Apply to All buttons (vertical stack)
            apply_frame = tk.LabelFrame(button_frame, text="Apply to All", padx=15, pady=10)
            apply_frame.pack(pady=5)

            tk.Button(apply_frame, text="Skip All", command=lambda: apply_to_all("skip"), width=20).pack(pady=3)
            tk.Button(apply_frame, text="Overwrite All", command=lambda: apply_to_all("overwrite"), width=20).pack(pady=3)
            tk.Button(apply_frame, text="Upload All Again", command=lambda: apply_to_all("upload_again"), width=20).pack(pady=3)

            # Confirm and Cancel buttons
            tk.Button(button_frame, text="Confirm Choices", command=on_confirm, width=20, bg="lightblue", font=("Arial", 10, "bold")).pack(pady=5)
            tk.Button(button_frame, text="Cancel", command=on_cancel, width=20, bg="lightcoral", font=("Arial", 10, "bold")).pack(pady=5)

            dialog.protocol("WM_DELETE_WINDOW", on_cancel)
            dialog.lift()
            dialog.focus_force()

        except Exception as e:  # pylint: disable=broad-except
            self.log(f"Error showing duplicate dialog: {e}", "ERROR", host="general")
            # Ensure we signal completion even if dialog fails
            self._finish_scanning()

    def _clear_duplicate_state(self):
        """Clear duplicate checking state after queue completes."""
        with self.queue_lock:
            self.duplicate_decisions.clear()
            self.scanned_files.clear()
            # Reset scanning state in case it's stuck
            self.scanning_in_progress = False
            self.scan_complete_event.set()
        self.log("Duplicate state cleared", "INFO", host="general")
