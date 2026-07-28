"""
Credential and host settings dialog.

Editing config.json by hand means a JSON typo breaks startup with no
explanation. This edits the same keys through a validated form.
"""

import os
import tkinter as tk
from tkinter import messagebox, ttk
from typing import Callable, Dict, List, NamedTuple, Optional

from host_workers import open_apkadmin_setup_guide


class Field(NamedTuple):
    """One editable config key."""

    key: str
    label: str
    secret: bool


class HostSpec(NamedTuple):
    """A host's enable flag and the credentials it needs."""

    name: str
    label: str
    enabled_key: str
    fields: List[Field]


HOSTS: List[HostSpec] = [
    HostSpec("gofile", "Gofile", "gofile_enabled", [
        Field("api_token", "API token", True),
        Field("account_id", "Account ID", False),
    ]),
    HostSpec("buzzheavier", "Buzzheavier", "buzzheavier_enabled", [
        Field("buzzheavier_account_id", "Account ID", True),
    ]),
    HostSpec("pixeldrain", "Pixeldrain", "pixeldrain_enabled", [
        Field("pixeldrain_api_key", "API key", True),
    ]),
    HostSpec("apkadmin", "Apkadmin", "apkadmin_enabled", [
        Field("apkadmin_cf_clearance", "cf_clearance cookie", True),
        Field("apkadmin_xfss", "xfss cookie", True),
        Field("apkadmin_user_agent", "User-Agent", False),
    ]),
]


class SettingsDialog:
    """Modal form for editing credentials and host toggles."""

    def __init__(self, parent, config, on_saved: Optional[Callable] = None):
        """
        Build and show the dialog.

        Parameters
        ----------
        parent : tkinter.Widget
            Window to attach the dialog to.
        config : config_loader.Config
            Config object to read from and save through.
        on_saved : Callable, optional
            Called after a successful save, e.g. to reconnect the hosts.
        """
        self.config = config
        self.on_saved = on_saved
        self.entries: Dict[str, tk.Entry] = {}
        self.enabled_vars: Dict[str, tk.BooleanVar] = {}
        self.secret_keys = {
            field.key for host in HOSTS for field in host.fields if field.secret
        }
        self.show_secrets = tk.BooleanVar(value=False)

        current = self._load_current()

        self.window = tk.Toplevel(parent)
        self.window.title("Settings")
        self.window.transient(parent)
        self.window.resizable(False, False)

        self._build_form(current)

        self.window.grab_set()
        self.window.protocol("WM_DELETE_WINDOW", self.window.destroy)

    def _load_current(self) -> Dict:
        """Read existing config values, tolerating a missing file."""
        try:
            return dict(self.config.load())
        except Exception:  # pylint: disable=broad-except
            # A missing or unreadable config is exactly the case this dialog
            # exists to fix, so open with empty fields rather than failing.
            return {}

    def _build_form(self, current: Dict) -> None:
        """Lay out one section per host, plus the action buttons."""
        frame = ttk.Frame(self.window, padding="12")
        frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))

        row = 0
        for host in HOSTS:
            var = tk.BooleanVar(value=bool(current.get(host.enabled_key, False)))
            self.enabled_vars[host.enabled_key] = var

            ttk.Checkbutton(frame, text=host.label, variable=var).grid(
                row=row, column=0, columnspan=2, sticky=tk.W, pady=(10, 2))
            row += 1

            for field in host.fields:
                ttk.Label(frame, text=f"    {field.label}:").grid(
                    row=row, column=0, sticky=tk.W, padx=(0, 8))

                entry = ttk.Entry(frame, width=46, font=('Consolas', 9))
                entry.insert(0, str(current.get(field.key, "")))
                if field.secret:
                    entry.config(show="*")
                entry.grid(row=row, column=1, sticky=(tk.W, tk.E), pady=1)

                self.entries[field.key] = entry
                row += 1

            if host.name == "apkadmin":
                ttk.Button(frame, text="How do I get these values?",
                          command=self._open_apkadmin_guide).grid(
                    row=row, column=1, sticky=tk.W, pady=(0, 4))
                row += 1

        ttk.Checkbutton(frame, text="Show secrets",
                        variable=self.show_secrets,
                        command=self._toggle_secret_visibility).grid(
            row=row, column=1, sticky=tk.W, pady=(10, 0))
        row += 1

        footer = ttk.Frame(frame)
        footer.grid(row=row, column=0, columnspan=2, pady=(14, 0), sticky=(tk.W, tk.E))
        footer.columnconfigure(0, weight=1)

        # Escape hatch for anything this form doesn't cover, e.g. a key this
        # dialog doesn't know about yet.
        ttk.Button(footer, text="Edit config.json…",
                  command=self._open_raw_config).grid(row=0, column=0, sticky=tk.W)

        buttons = ttk.Frame(footer)
        buttons.grid(row=0, column=1, sticky=tk.E)

        ttk.Button(buttons, text="Save", command=self._save, width=10).grid(
            row=0, column=0, padx=4)
        ttk.Button(buttons, text="Cancel", command=self.window.destroy,
                   width=10).grid(row=0, column=1, padx=4)

    def _open_apkadmin_guide(self) -> None:
        """Open the Apkadmin cookie setup guide, for filling in these fields."""
        open_apkadmin_setup_guide(self.window)

    def _open_raw_config(self) -> None:
        """Open config.json directly, for anything this form doesn't cover."""
        path = self.config.config_file
        if not os.path.exists(path):
            messagebox.showerror("Not Found", f"config.json not found at:\n{path}",
                                 parent=self.window)
            return
        os.startfile(path)

    def _toggle_secret_visibility(self) -> None:
        """Reveal or mask the credential fields."""
        show = "" if self.show_secrets.get() else "*"
        for key in self.secret_keys:
            self.entries[key].config(show=show)

    def _collect(self) -> Dict:
        """Read the form back into config values."""
        values = {key: entry.get().strip() for key, entry in self.entries.items()}
        values.update({key: var.get() for key, var in self.enabled_vars.items()})
        return values

    def validate(self, values: Dict) -> Optional[str]:
        """
        Check the form before saving.

        Returns
        -------
        Optional[str]
            An error message, or None if the values are usable.
        """
        if not any(values.get(host.enabled_key) for host in HOSTS):
            return "At least one file host must be enabled."

        for host in HOSTS:
            if not values.get(host.enabled_key):
                continue
            missing = [f.label for f in host.fields if not values.get(f.key)]
            if missing:
                return (f"{host.label} is enabled but missing: "
                        f"{', '.join(missing)}")

        return None

    def _save(self) -> None:
        """Validate, merge into the existing config, and write it out."""
        values = self._collect()

        error = self.validate(values)
        if error:
            messagebox.showwarning("Invalid Settings", error, parent=self.window)
            return

        # Merge rather than replace so the _comment_* keys and any settings
        # this dialog does not manage survive the round trip.
        merged = self._load_current()
        merged.update(values)

        try:
            self.config.save(merged)
        except OSError as e:
            messagebox.showerror("Save Failed",
                                 f"Could not write config file:\n{e}",
                                 parent=self.window)
            return

        self.window.destroy()

        if self.on_saved:
            self.on_saved()
