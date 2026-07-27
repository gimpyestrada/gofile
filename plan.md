# Multi-Host Uploader — Review Remediation Plan

## Context

A code review of the uploader (GUI app + 4 host API clients) found stability bugs,
security hygiene gaps, heavy code duplication, and several missing quality-of-life
features. This plan implements the agreed fixes in five phases, ordered so bug fixes
land on stable ground before the refactor, and features land in the refactored structure.

Coding standards: follow `.github/instructions/python.instructions.md` (PEP 8, type
hints, PEP 257 docstrings) and `self-explanatory-code-commenting.instructions.md`
(WHY-only comments).

## Commit strategy

Each numbered item below is its own commit. Phases group related commits but are not
squashed. After each commit: `python -m py_compile` on changed files plus a quick app
launch before moving on.

---

## Phase 0 — Remove mini mode

The app has outgrown this feature. Removing it first means later work (threading fix,
refactor, progress bars) never has to account for mini widgets.

- [x] **`refactor: remove mini mode`** — all in `drag_drop_uploader.py` unless noted:
  - Constants `MINI_MODE_WIDTH` / `MINI_MODE_HEIGHT`.
  - `__init__` attrs: `mini_mode`, `mini_frame`, `mini_status_label`, and the four
    `mini_*_indicator` attributes.
  - `toggle_mini_mode()` method.
  - In `run()`: the `mini_mode` BooleanVar, the "Mini Mode (Always on Top)" checkbutton,
    and the entire mini-frame build block (drop zone, status, link sections with
    copy/open buttons, drop-target registrations).
  - Mini branches in `update_status()` and `_update_status_emoji()`.
  - Any remaining `-topmost` toggling tied to mini mode.
  - `DRAG_DROP_UPLOADER_README.md`: remove the mini-mode documentation section.

---

## Phase 1 — Shared module + bug fixes

- [x] **1.1 `refactor: extract shared ProgressTrackingFile into upload_common.py`**
  - Move the 4 identical `ProgressTrackingFile` classes (from `gofile_api.py`,
    `buzzheavier_api.py`, `pixeldrain_api.py`, `apkadmin_api.py`) into one shared class.
    Add an optional `progress_callback(bytes_read, total_size)` parameter now (used by
    Phase 4's progress bars; no-op otherwise).
  - Move shared constants (`BACKOFF_BASE_SECONDS`, `UPLOAD_MAX_RETRIES`,
    `UPLOAD_RETRY_DELAY`).
  - Each API client imports from `upload_common`; delete the local copies. Keep each
    client's exception hierarchy where it is (the GUI imports them per-module).

- [x] **1.2 `fix: use (connect, read) timeouts so uploads cannot hang forever`**
  - Replace `timeout=None` on the upload request in all 4 clients with
    `timeout=(30, self.upload_stall_timeout)`. Currently, once the request body is fully
    sent, nothing can time out and a dead connection hangs the upload thread forever.
  - Keep `ProgressTrackingFile` stall detection as a second layer. The read timeout
    applies between socket operations, so slow-but-alive transfers are unaffected.

- [x] **1.3 `fix: marshal all GUI updates to the Tk main thread`** (`drag_drop_uploader.py`)
  - `log()`: `print()` immediately, but marshal all widget work through
    `self.root.after(0, ...)`. Guard for `self.root is None` (early startup) by printing
    only. Callers stay unchanged.
  - `update_status()`: same treatment.
  - `initialize_api()` runs on a background thread — marshal its `messagebox.showerror`
    calls too.
  - Existing correct uses of `root.after` (link entries, status emojis, scan dialogs)
    stay as-is.

- [x] **1.4 `fix: surface host init failures in the GUI log`** (`drag_drop_uploader.py`)
  - `_initialize_gofile`: also catch `GofileAPIError`, `requests.RequestException`, and a
    broad `Exception` fallback (mirroring `_initialize_pixeldrain`'s structure) so
    failures appear in the GUI instead of killing the init thread with a console-only
    traceback.
  - `_initialize_buzzheavier`: same, with `BuzzheavierAPIError` / `NetworkException`.
  - `_initialize_pixeldrain` currently catches `NetworkException` imported from
    `buzzheavier_api`, but Pixeldrain raises its own class — import and catch
    `pixeldrain_api.NetworkException`.

- [x] **1.5 `fix: URL-quote filenames, resolve config path from app dir, repair dead retry logic`**
  - **URL-quote filenames**: `urllib.parse.quote(name, safe='')` in `buzzheavier_api.py`
    upload URL construction and `pixeldrain_api.py` (`PUT /file/{name}`). A filename
    containing `#`, `?`, or `%` currently corrupts the URL.
  - **Config path vs CWD**: add a `get_app_dir()` helper in `config_loader.py` (same
    `sys.frozen` logic as `DragDropUploader._get_cache_dir`) and default `Config` /
    `load_config` to `<app_dir>/config.json`. Use the same resolution in
    `open_config_file()`. Launching the exe from a different working directory currently
    fails to find the config.
  - **Dead 429 retry logic**: in `gofile_api.py` `_handle_response`, drop the
    sleep-then-raise on 429 (the caller never retries, so the sleep is wasted time) and
    let `_handle_rate_limit` own backoff. In `gofile_api.py` and `buzzheavier_api.py`
    `_make_request_with_retry`, the generic `except Exception` branch raises on every
    path so retries can never happen — retry only transient errors
    (`requests.ConnectionError`, `requests.Timeout`) and re-raise everything else.

- [x] **1.6 `chore: remove duplicate pixeldrain state and clarify get_content password hashing`**
  - `drag_drop_uploader.py` `__init__`: remove the duplicate Pixeldrain state block
    (second init of `pixeldrain_api` / `pixeldrain_folder_structure`, plus
    `self.pixeldrain_ready` which shadows the `_pixeldrain_ready` flag actually used).
  - `gofile_api.py` `get_content`: replace the 64-char "looks like a hash" heuristic with
    an explicit `is_hashed: bool = False` parameter (a real 64-char password is currently
    sent unhashed).

---

## Phase 2 — Security hygiene

- [x] **2.1 `chore: pin dependency versions`**
  - Pin exact versions in `requirements.txt` for all 5 packages using what is currently
    installed in `.venv` (read via `pip freeze`). Matters especially since the app ships
    as a PyInstaller exe.

- [x] **2.2 `security: tighten logging and restrict clickable log links to known hosts`**
  - `_initialize_gofile`: stop logging the account email (log tier only, or mask it).
  - `apkadmin_api.py` `_parse_upload_response`: sanitize the response excerpt embedded in
    the error (strip tags/URLs, keep it short) so hostile server text cannot inject
    clickable content into the log.
  - `log()` linkification: only tag URLs whose host is (a subdomain of) an allowlist —
    `gofile.io`, `buzzheavier.com`, `pixeldrain.com`, `apkadmin.com` — parsed with
    `urllib.parse.urlparse`. `_open_url_from_event` re-checks the allowlist before
    `webbrowser.open`.

---

## Phase 3 — Split `drag_drop_uploader.py` (~3,300 lines)

Low-risk mixin/extraction split; `DragDropUploader`'s public surface and behavior are
unchanged. One commit per extracted module, safest first, smoke-testing between commits.

- [x] **`refactor: extract apk filename parsing into apk_naming.py`** — pure functions:
  `parse_apk_filename`, version-folder normalization. No `self` dependencies, so fully
  unit-testable.
- [x] **`refactor: extract Tooltip and GUI helpers into widgets.py`**
- [x] **`refactor: extract folder cache I/O into folder_cache.py`** — `save_folder_cache`
  / `load_folder_cache` file I/O, parameterized by cache path.
- [x] **`refactor: extract per-host workers into host_workers.py`** — `HostWorkersMixin`
  with the `_initialize_*`, `_upload_to_*`, and `retry_*` methods.
- [x] **`refactor: extract duplicate scanning into duplicate_scan.py`** —
  `DuplicateScanMixin` with `_detect_duplicates`, `_batch_scan_*`, scan progress dialog,
  decision dialog.

`drag_drop_uploader.py` remains the entry point: `DragDropUploader(HostWorkersMixin,
DuplicateScanMixin)`, GUI layout (`run()`), queue worker, tray, `main()`. Confirmed the
PyInstaller build still resolves the new modules; no spec change was needed.

**Result:** 3,307 lines down to 2,134, with the extracted logic in seven focused modules
(`apk_naming`, `widgets`, `folder_cache`, `host_workers`, `duplicate_scan`,
`settings_dialog`, `upload_common`).

---

## Phase 4 — Features

- [x] **4.1 `feat: per-host upload progress bars`**
  - Each `_upload_to_*` passes a throttled `progress_callback` (report at most ~4×/sec or
    per 1% step) that marshals via `root.after` to a per-host `ttk.Progressbar` under the
    host status frame; hidden/reset when idle.
  - **Gofile memory + progress fix**: switch `gofile_api.upload_file` from `files=`
    (requests buffers the whole multipart body in memory and reads the file in one
    `read()` call, so there is no progress granularity) to
    `requests_toolbelt.MultipartEncoder`, matching the existing pattern in
    `apkadmin_api.upload_file`. `requests-toolbelt` is already a dependency.
  - Buzzheavier/Pixeldrain stream via `data=file`, so chunked reads already flow through
    `ProgressTrackingFile`.

- [x] **4.2 `feat: verify Gofile uploads against local MD5`**
  - Compute the file's MD5 locally in the queue worker (chunked `hashlib.md5`, before
    upload, logged to the general column).
  - Compare against the `md5` field in Gofile's upload response; log SUCCESS on match,
    ERROR on mismatch (keep the link — the user decides). Skip silently if absent.

- [x] **4.3 `feat: warn on expired Apkadmin cookies with setup guide`**
  - On `ApkadminAuthError` during `_initialize_apkadmin` (startup `verify_connection()`
    already detects expired `cf_clearance`), show a marshaled `messagebox.askyesno`
    explaining the cookies expired, with an option to open the setup guide.
  - Create the missing **`docs/APKADMIN_SETUP.md`** — referenced throughout
    `apkadmin_api.py` and `config.json` but does not exist. Brief steps to grab
    `cf_clearance`, `xfss`, and the User-Agent from browser dev tools.

- [x] **4.4 `feat: in-app settings dialog`**
  - New `settings_dialog.py`: a `Toplevel` form with entries for every config key
    (secrets masked with `show='*'` plus a reveal toggle), host-enable checkboxes,
    Save/Cancel.
  - Validation before save: non-empty credentials for enabled hosts, at least one host
    enabled (reuse the rule from `_validate_and_save_host_settings`).
  - Save writes through the existing `Config.save`, round-tripping the loaded dict so the
    `_comment_*` keys survive, then offers to reconnect (re-run `initialize_api` on a
    background thread).
  - `show_settings_menu` gains a "Settings…" item; keep "open config file" as a fallback.

---

## Tests

No test infrastructure exists. Add a `tests/` directory with `unittest`-based tests for
the pure/parseable parts (`python -m unittest discover tests`), committed alongside the
code they cover:

- `tests/test_upload_common.py` — `ProgressTrackingFile` read/stall/callback behavior
  using `io.BytesIO` (lands with 1.1).
- `tests/test_url_quoting.py` — Buzzheavier/Pixeldrain URL construction with awkward
  filenames: `#`, space, `%` (lands with 1.5).
- `tests/test_apk_naming.py` — filename parsing and version normalization cases (lands
  with the Phase 3 extraction).

## Verification

Per commit: `python -m py_compile` on changed files, `python -m unittest discover tests`,
and launch the app.

- **Phase 0** — no mini-mode checkbox; `grep -i mini` returns nothing in
  `drag_drop_uploader.py`; drop a file and confirm status/emoji updates still work.
- **Phase 1** — launch with the real config, drop a small test APK, confirm link and 🟢
  status. Batch-drop 3+ files to stress the queue and thread-marshaled logging (no Tk
  errors). Temporarily break a credential → the failure must appear in that host's GUI log
  column (1.4). Rename a test file to include `#` and a space → Buzzheavier/Pixeldrain
  uploads still succeed (1.5). Launch from a different working directory → config still
  found (1.5).
- **Phase 3** — full manual smoke test (drop, retry buttons, duplicate dialog, tray) plus
  a PyInstaller build via `build_uploader.bat`.
- **Phase 4** — watch progress bars during a large upload; verify the MD5 match log; test
  the settings dialog round-trip (edit → save → `config.json` intact including comments →
  reconnect).
