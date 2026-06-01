"""
Apkadmin API Client
A Python client for uploading files to apkadmin.com via web scraping.
Apkadmin has no public API; this client scrapes the XFileSharing upload form.

Authentication uses browser cookies (cf_clearance + xfss) because the site
sits behind Cloudflare, which cannot be bypassed programmatically. See
docs/APKADMIN_SETUP.md for instructions on obtaining the required values.

URL format for uploaded files: https://apkadmin.com/{file_code}/{filename}.html
"""

import json
import re
import time
from io import BufferedReader
from pathlib import Path
from typing import Any, Dict, Optional

import requests
from requests_toolbelt import MultipartEncoder


UPLOAD_MAX_RETRIES = 3
UPLOAD_RETRY_DELAY = 3


class ApkadminAPIError(Exception):
    """Base exception for Apkadmin errors."""


class ApkadminHTTPError(ApkadminAPIError):
    """Exception for HTTP-level errors (network, timeout, etc)."""


class ApkadminAuthError(ApkadminAPIError):
    """Exception for authentication and Cloudflare challenge failures."""


class NetworkException(ApkadminAPIError):
    """Exception for transient network errors that may be retryable."""


class ProgressTrackingFile:
    """
    Wrapper for file objects that tracks upload progress to prevent timeout
    on active uploads. Only triggers timeout if no data is being transferred.
    """

    def __init__(self, file_obj: BufferedReader, timeout_seconds: int = 60):
        self.file_obj = file_obj
        self.timeout_seconds = timeout_seconds
        self.last_read_time = time.time()

    def read(self, size: int = -1):
        """Read data and update progress timestamp."""
        current_time = time.time()
        elapsed = current_time - self.last_read_time

        if elapsed > self.timeout_seconds:
            raise TimeoutError(
                f"Upload stalled — no data transferred for {self.timeout_seconds}s"
            )

        data = self.file_obj.read(size)
        if data:
            self.last_read_time = time.time()
        return data

    def __getattr__(self, name):
        """Delegate other attributes to the wrapped file object."""
        return getattr(self.file_obj, name)


class ApkadminAPI:
    """
    Client for uploading files to apkadmin.com via web scraping.

    Cloudflare protects the site, so authentication requires manually-obtained
    browser cookies rather than a username/password login flow. The cf_clearance
    cookie is bound to the exact User-Agent string used when the Cloudflare
    challenge was solved, so the same User-Agent must be supplied here.

    See docs/APKADMIN_SETUP.md for step-by-step instructions.
    """

    BASE_URL = "https://apkadmin.com"
    UPLOAD_FORM_URL = f"{BASE_URL}/?op=upload_form"

    def __init__(
        self,
        cf_clearance: str,
        xfss: str,
        user_agent: str,
        timeout: int = 30,
        upload_stall_timeout: int = 120,
    ):
        """
        Initialize the Apkadmin client.

        Args:
            cf_clearance: The cf_clearance cookie value from your browser.
            xfss:         The xfss session cookie value from your browser.
            user_agent:   The exact browser User-Agent string used when solving
                          the Cloudflare challenge. Must match cf_clearance.
            timeout:      Request timeout in seconds for non-upload requests.
            upload_stall_timeout: Seconds of no upload progress before timing out.
        """
        self.timeout = timeout
        self.upload_stall_timeout = upload_stall_timeout

        self.session = requests.Session()
        self.session.cookies.set("cf_clearance", cf_clearance, domain="apkadmin.com")
        self.session.cookies.set("xfss", xfss, domain="apkadmin.com")
        self.session.headers.update({"User-Agent": user_agent})

    def _get_upload_form(self) -> tuple[str, Dict[str, str]]:
        """
        Fetch the upload form page and extract the action URL + hidden fields.

        Returns:
            Tuple of (action_url, hidden_fields_dict).

        Raises:
            ApkadminAuthError: If a Cloudflare challenge page is detected,
                               indicating the cf_clearance cookie is expired or
                               the User-Agent does not match.
            NetworkException:  On connection/timeout errors.
            ApkadminAPIError:  If the upload form cannot be found in the response.
        """
        try:
            resp = self.session.get(self.UPLOAD_FORM_URL, timeout=self.timeout)
            resp.raise_for_status()
        except requests.exceptions.HTTPError as e:
            raise ApkadminHTTPError(f"HTTP error fetching upload form: {e}") from e
        except requests.exceptions.ConnectionError as e:
            raise NetworkException(f"Connection error: {e}") from e
        except requests.exceptions.Timeout as e:
            raise NetworkException(f"Request timed out: {e}") from e
        except requests.exceptions.RequestException as e:
            raise NetworkException(f"Network error: {e}") from e

        # Cloudflare challenge detection: real page has an upload <form>;
        # CF challenge pages do not, and typically contain CF-specific text.
        is_cf_challenge = (
            "just a moment" in resp.text.lower()
            and "cloudflare" in resp.text.lower()
        ) or (
            "cf_clearance" in resp.text
            and "<form" not in resp.text.lower()
        )

        if is_cf_challenge:
            raise ApkadminAuthError(
                "Cloudflare challenge detected — cf_clearance cookie is expired "
                "or the User-Agent does not match. "
                "See docs/APKADMIN_SETUP.md to refresh your cookies."
            )

        action_match = re.search(
            r'<form[^>]+action=["\']([^"\']+)["\']', resp.text, re.IGNORECASE
        )
        if not action_match:
            raise ApkadminAPIError(
                "Upload form not found in page response. "
                "The site layout may have changed, or the xfss cookie has expired."
            )

        action_url = action_match.group(1)
        if action_url.startswith("/"):
            action_url = self.BASE_URL + action_url

        # Extract hidden fields — handle both attribute orderings
        hidden_fields: Dict[str, str] = {}

        for name, value in re.findall(
            r'<input[^>]+type=["\']hidden["\'][^>]+name=["\']([^"\']+)["\'][^>]+value=["\']([^"\']*)["\']',
            resp.text,
            re.IGNORECASE,
        ):
            hidden_fields[name] = value

        for value, name in re.findall(
            r'<input[^>]+type=["\']hidden["\'][^>]+value=["\']([^"\']*)["\'][^>]+name=["\']([^"\']+)["\']',
            resp.text,
            re.IGNORECASE,
        ):
            hidden_fields.setdefault(name, value)

        return action_url, hidden_fields

    def _parse_upload_response(self, resp: requests.Response) -> str:
        """
        Parse the upload response to extract the file code.

        The server returns JSON: [{"file_code": "...", "file_status": "OK"}]
        Falls back to legacy XFileSharing HTML textarea format.

        Returns:
            The file code string.

        Raises:
            ApkadminAPIError: If the file code cannot be extracted or status != OK.
        """
        file_code: Optional[str] = None
        status: Optional[str] = None

        content_type = resp.headers.get("content-type", "")
        if "json" in content_type or resp.text.lstrip().startswith("["):
            try:
                data = json.loads(resp.text)
                if isinstance(data, list) and data:
                    file_code = data[0].get("file_code")
                    status = data[0].get("file_status", "")
            except (json.JSONDecodeError, KeyError, IndexError):
                pass

        if not file_code:
            st_match = re.search(
                r'<textarea[^>]+name=["\']st["\'][^>]*>(.*?)</textarea>',
                resp.text,
                re.IGNORECASE | re.DOTALL,
            )
            fn_match = re.search(
                r'<textarea[^>]+name=["\']fn["\'][^>]*>(.*?)</textarea>',
                resp.text,
                re.IGNORECASE | re.DOTALL,
            )
            status = st_match.group(1).strip() if st_match else None
            file_code = fn_match.group(1).strip() if fn_match else None

        if status and status.upper() != "OK":
            raise ApkadminAPIError(f"Upload rejected by server: {status}")

        if not file_code:
            raise ApkadminAPIError(
                f"Could not extract file code from server response. "
                f"Response excerpt: {resp.text[:200]}"
            )

        return file_code

    def upload_file(self, file_path: str) -> Dict[str, Any]:
        """
        Upload a file to apkadmin.com.

        Fetches a fresh upload form on every call — the form's action URL
        contains a unique upload_id that must not be reused across uploads.

        Args:
            file_path: Path to the file to upload.

        Returns:
            Dict with keys:
                'file_code' — the server-assigned code (e.g. '76spb4lnznjp')
                'url'       — the full public URL
                              (https://apkadmin.com/{code}/{filename}.html)

        Raises:
            FileNotFoundError:  If file_path does not exist.
            ApkadminAuthError:  If Cloudflare rejects the session.
            ApkadminAPIError:   If the upload or response parsing fails.
            NetworkException:   On connection/timeout errors.
        """
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        for attempt in range(UPLOAD_MAX_RETRIES):
            try:
                # Fetch a fresh form each upload — action URL contains a unique upload_id
                action_url, hidden_fields = self._get_upload_form()

                with open(path, "rb") as f:
                    tracked = ProgressTrackingFile(f, self.upload_stall_timeout)

                    # MultipartEncoder streams the body without buffering the
                    # entire file in memory, which is essential for large uploads.
                    fields = dict(hidden_fields)
                    fields["file_0"] = (path.name, tracked, "application/octet-stream")
                    encoder = MultipartEncoder(fields=fields)

                    resp = self.session.post(
                        action_url,
                        data=encoder,
                        headers={"Content-Type": encoder.content_type},
                        timeout=None,
                    )

                resp.raise_for_status()
                file_code = self._parse_upload_response(resp)
                url = f"{self.BASE_URL}/{file_code}/{path.name}.html"
                return {"file_code": file_code, "url": url}

            except ApkadminAuthError:
                raise
            except (ApkadminAPIError, TimeoutError) as e:
                raise ApkadminAPIError(str(e)) from e
            except requests.exceptions.HTTPError as e:
                if attempt < UPLOAD_MAX_RETRIES - 1:
                    time.sleep(UPLOAD_RETRY_DELAY * (attempt + 1))
                    continue
                raise ApkadminHTTPError(f"HTTP error during upload: {e}") from e
            except requests.exceptions.ConnectionError as e:
                if attempt < UPLOAD_MAX_RETRIES - 1:
                    time.sleep(UPLOAD_RETRY_DELAY * (attempt + 1))
                    continue
                raise NetworkException(f"Connection error during upload: {e}") from e
            except requests.exceptions.Timeout as e:
                if attempt < UPLOAD_MAX_RETRIES - 1:
                    time.sleep(UPLOAD_RETRY_DELAY * (attempt + 1))
                    continue
                raise NetworkException(f"Upload timed out: {e}") from e
            except requests.exceptions.RequestException as e:
                if attempt < UPLOAD_MAX_RETRIES - 1:
                    time.sleep(UPLOAD_RETRY_DELAY * (attempt + 1))
                    continue
                raise NetworkException(f"Network error during upload: {e}") from e

        raise ApkadminAPIError("Upload failed after maximum retries")

    def verify_connection(self) -> bool:
        """
        Verify that the session cookies are valid by fetching the upload form.

        Returns:
            True if the session is valid and the upload form is accessible.

        Raises:
            ApkadminAuthError: If Cloudflare blocks the request.
            ApkadminAPIError:  If the form cannot be found.
            NetworkException:  On connection errors.
        """
        self._get_upload_form()
        return True
