"""
Apkadmin cookie setup guide, shown in-app.

Kept as a Python string rather than a file under docs/ so the guide is
available from the built exe: docs/ is not bundled as PyInstaller data (see
GofileUploader.spec), so a file-based guide 404s once the app is packaged.
The same content also lives in docs/APKADMIN_SETUP.md for anyone reading it
from the repository; keep the two in sync when the steps change.
"""

import tkinter as tk
from tkinter import ttk
from typing import Optional

GUIDE_TEXT = """\
APKADMIN SETUP

Apkadmin has no public API and sits behind Cloudflare, so the uploader
authenticates with cookies copied from a browser session. Cloudflare
challenges cannot be solved programmatically, which is why this host
needs manual setup while the other three only need an API key.

You need three values in config.json:

  apkadmin_cf_clearance   Proof that your browser passed the Cloudflare
                          challenge
  apkadmin_xfss           Your logged-in Apkadmin session
  apkadmin_user_agent     The browser User-Agent that solved the challenge

GETTING THE VALUES

1. Open https://apkadmin.com in your browser and log in. Wait for any
   "Checking your browser" screen to finish.
2. Open developer tools with F12 and select the Application tab
   (Storage in Firefox).
3. Expand Cookies in the left sidebar and select https://apkadmin.com.
4. Copy the Value of the cf_clearance cookie into apkadmin_cf_clearance.
5. Copy the Value of the xfss cookie into apkadmin_xfss.
6. Switch to the Console tab, run navigator.userAgent, and copy the
   result (without the surrounding quotes) into apkadmin_user_agent.
7. Set apkadmin_enabled to true.

Restart the uploader. The Apkadmin log column should show "Connected to
Apkadmin".

WHY THE USER-AGENT MUST MATCH

Cloudflare binds cf_clearance to the exact browser that solved the
challenge. Sending the cookie with a different User-Agent invalidates it,
and the uploader gets a challenge page instead of the upload form. Copy
the string exactly -- a version-number difference is enough to break it.

WHEN IT STOPS WORKING

cf_clearance expires regularly (often within a day), and xfss expires
when your Apkadmin session ends. The uploader detects this at startup
and reports:

    Auth error: Cloudflare challenge detected -- cf_clearance cookie is
    expired or the User-Agent does not match.

Repeat the steps above to refresh both cookies. If you have also
upgraded your browser since the last time, re-copy the User-Agent too.

TROUBLESHOOTING

"Upload form not found in page response" -- usually a stale xfss cookie,
so you are being served the logged-out page. Log in again and re-copy
xfss. If both cookies are fresh, the site layout may have changed and
the scraper in apkadmin_api.py needs updating.

Works, then fails partway through a batch -- a cookie expired mid-run.
Refresh both cookies and retry the remaining files.

Nothing appears in the Apkadmin column -- apkadmin_enabled is still
false, or the host is disabled in the settings menu.

A NOTE ON THESE CREDENTIALS

xfss is a live session cookie: anyone holding it can act as you on
Apkadmin. It is stored in plaintext in config.json, so keep that file
private and do not paste these values into bug reports.
"""


def open_apkadmin_setup_guide(parent: Optional[tk.Misc] = None) -> None:
    """Show the Apkadmin cookie setup guide in a read-only dialog."""
    window = tk.Toplevel(parent)
    window.title("Apkadmin Setup Guide")
    window.geometry("640x520")
    window.transient(parent)
    window.columnconfigure(0, weight=1)
    window.rowconfigure(0, weight=1)

    frame = ttk.Frame(window, padding=10)
    frame.grid(row=0, column=0, sticky=(tk.N, tk.S, tk.E, tk.W))
    frame.columnconfigure(0, weight=1)
    frame.rowconfigure(0, weight=1)

    text = tk.Text(frame, wrap=tk.WORD, font=('Consolas', 9))
    text.grid(row=0, column=0, sticky=(tk.N, tk.S, tk.E, tk.W))
    scrollbar = ttk.Scrollbar(frame, orient=tk.VERTICAL, command=text.yview)
    scrollbar.grid(row=0, column=1, sticky=(tk.N, tk.S))
    text.configure(yscrollcommand=scrollbar.set)

    text.insert("1.0", GUIDE_TEXT)
    text.configure(state=tk.DISABLED)

    ttk.Button(frame, text="Close", command=window.destroy).grid(
        row=1, column=0, columnspan=2, pady=(10, 0))

    window.grab_set()
