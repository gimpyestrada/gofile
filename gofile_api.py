"""
Gofile API Client
A Python client for interacting with the Gofile API.
Supports file uploads, folder management, content operations, and more.
"""

import hashlib
import time
from pathlib import Path
from typing import Optional, List, Dict, Any, Union

import requests
from requests_toolbelt import MultipartEncoder

from upload_common import (
    BACKOFF_BASE_SECONDS,
    UPLOAD_CONNECT_TIMEOUT,
    ProgressCallback,
    ProgressTrackingFile,
)


class GofileAPIError(Exception):
    """Base exception for Gofile API errors."""


class GofileHTTPError(GofileAPIError):
    """Exception for HTTP-level errors (network, timeout, etc)."""


class GofileResponseError(GofileAPIError):
    """Exception for API response errors (invalid status, etc)."""


class RateLimitException(GofileAPIError):
    """Exception raised when API rate limit is exceeded."""


class GofileAPI:
    """Client for interacting with the Gofile API."""

    # Base URLs
    BASE_API_URL = "https://api.gofile.io"
    BASE_UPLOAD_URL = "https://upload.gofile.io"

    # Regional upload endpoints
    UPLOAD_REGIONS = {
        'auto': 'https://upload.gofile.io',
        'eu-par': 'https://upload-eu-par.gofile.io',
        'na-phx': 'https://upload-na-phx.gofile.io',
        'ap-sgp': 'https://upload-ap-sgp.gofile.io',
        'ap-hkg': 'https://upload-ap-hkg.gofile.io',
        'ap-tyo': 'https://upload-ap-tyo.gofile.io',
        'sa-sao': 'https://upload-sa-sao.gofile.io',
    }

    def __init__(self, api_token: Optional[str] = None, timeout: int = 30, upload_stall_timeout: int = 120):
        """
        Initialize the Gofile API client.

        Args:
            api_token: Your Gofile API token (optional for guest uploads)
            timeout: Request timeout in seconds for non-upload requests (default: 30)
            upload_stall_timeout: Seconds of no upload progress before timing out (default: 120)
        """
        self.api_token = api_token
        self.timeout = timeout
        self.upload_stall_timeout = upload_stall_timeout
        self.session = requests.Session()
        if api_token:
            self.session.headers.update({
                'Authorization': f'Bearer {api_token}'
            })

    def _handle_response(self, response: requests.Response) -> Dict[str, Any]:
        """
        Handle API response and extract data.

        Rate limits are signalled by raising RateLimitException; backoff is
        owned by _make_request_with_retry, which is the only layer that can
        actually reissue the request.
        """
        try:
            response.raise_for_status()
            data = response.json()
            if data.get('status') == 'ok':
                return data.get('data', {})

            raise GofileResponseError(f"API Error: {data}")
        except requests.exceptions.HTTPError as e:
            if response.status_code == 429:
                raise RateLimitException(f"Rate limit exceeded: {e}") from e
            raise GofileHTTPError(f"HTTP Error: {e}") from e
        except GofileAPIError:
            raise
        except Exception as e:
            raise GofileAPIError(f"Error: {e}") from e


    def _execute_request(self, method: str, url: str, **kwargs):
        """Execute HTTP request based on method type."""
        if method == 'get':
            return self.session.get(url, timeout=self.timeout, **kwargs)
        if method == 'post':
            return self.session.post(url, timeout=self.timeout, **kwargs)
        if method == 'put':
            return self.session.put(url, timeout=self.timeout, **kwargs)
        if method == 'delete':
            return self.session.delete(url, timeout=self.timeout, **kwargs)

        raise ValueError(f"Unsupported HTTP method: {method}")

    def _handle_rate_limit(self, attempt: int, max_retries: int):
        """Handle rate limit with exponential backoff.

        Uses exponential backoff (2^attempt * base) to avoid overwhelming the API
        while giving progressively longer recovery time as failures increase.
        This is the standard approach for handling rate limits in distributed systems.
        """
        if attempt < max_retries:
            wait_time = (2 ** attempt) * BACKOFF_BASE_SECONDS
            print(f"⚠ Rate limit (429) - Waiting {wait_time}s before retry {attempt + 1}/{max_retries}...")
            time.sleep(wait_time)
            return True

        raise RateLimitException(f"Rate limit exceeded after {max_retries} retries. Please wait a few minutes.")

    def _make_request_with_retry(self, method: str, url: str, max_retries: int = 3, **kwargs):
        """
        Make an API request, retrying on rate limits and transient failures.

        Args:
            method: HTTP method ('get', 'post', 'put', 'delete')
            url: Request URL
            max_retries: Maximum number of retries
            **kwargs: Additional arguments to pass to requests

        Returns:
            Response data
        """
        for attempt in range(max_retries + 1):
            try:
                response = self._execute_request(method, url, **kwargs)

                if response.status_code == 429:
                    self._handle_rate_limit(attempt, max_retries)
                    continue

                return self._handle_response(response)

            except (requests.exceptions.ConnectionError,
                    requests.exceptions.Timeout) as e:
                # Only transient network faults are worth reissuing; an auth
                # failure or a malformed request will fail identically.
                if attempt == max_retries:
                    raise GofileHTTPError(
                        f"Request failed after {max_retries} retries: {e}"
                    ) from e
                time.sleep((2 ** attempt) * BACKOFF_BASE_SECONDS)

        raise RateLimitException("Max retries exceeded")

    # ===== UPLOAD OPERATIONS =====

    def upload_file(self,
                    file_path: str,
                    folder_id: Optional[str] = None,
                    region: str = 'auto',
                    progress_callback: Optional[ProgressCallback] = None) -> Dict[str, Any]:
        """
        Upload a file to Gofile.

        Args:
            file_path: Path to the file to upload
            folder_id: Destination folder ID (optional, creates new folder if not provided)
            region: Upload region ('auto', 'eu-par', 'na-phx', 'ap-sgp', 'ap-hkg', 'ap-tyo', 'sa-sao')
            progress_callback: Called with (bytes_sent, total_size) as the
                upload proceeds (optional)

        Returns:
            Dictionary containing upload response with file information
        """
        upload_url = self.UPLOAD_REGIONS.get(region, self.BASE_UPLOAD_URL)
        url = f"{upload_url}/uploadfile"

        file_path_obj = Path(file_path)
        if not file_path_obj.exists():
            raise FileNotFoundError(f"File not found: {file_path}")
        if not file_path_obj.is_file():
            raise ValueError(f"Path is not a file: {file_path}")

        total_size = file_path_obj.stat().st_size

        with open(file_path, 'rb') as f:
            tracked = ProgressTrackingFile(
                f, self.upload_stall_timeout, progress_callback, total_size
            )

            # MultipartEncoder streams the body in chunks. Passing the file via
            # requests' files= would buffer the whole multipart body in memory
            # and read the file in a single call, leaving no progress steps.
            fields = {'file': (file_path_obj.name, tracked,
                               'application/octet-stream')}
            if folder_id:
                fields['folderId'] = folder_id
            encoder = MultipartEncoder(fields=fields)

            # ProgressTrackingFile only fires while the body is still being
            # read, so a read timeout is still needed to catch a connection
            # that dies while we wait for the server's response.
            response = self.session.post(
                url, data=encoder,
                headers={'Content-Type': encoder.content_type},
                timeout=(UPLOAD_CONNECT_TIMEOUT, self.upload_stall_timeout)
            )
            return self._handle_response(response)

    # ===== FOLDER OPERATIONS =====

    def create_folder(self,
                      parent_folder_id: str,
                      folder_name: Optional[str] = None) -> Dict[str, Any]:
        """
        Create a new folder.

        Args:
            parent_folder_id: ID of the parent folder
            folder_name: Name for the new folder (optional, auto-generated if not provided)

        Returns:
            Dictionary containing the new folder information
        """
        url = f"{self.BASE_API_URL}/contents/createFolder"

        payload = {'parentFolderId': parent_folder_id}
        if folder_name:
            payload['folderName'] = folder_name

        response = self.session.post(url, json=payload, timeout=self.timeout)
        return self._handle_response(response)

    def get_content(self,
                    content_id: str,
                    password: Optional[str] = None,
                    is_hashed: bool = False) -> Dict[str, Any]:
        """
        Get detailed information about a folder and its contents.

        Args:
            content_id: ID of the folder
            password: Password for protected content (optional)
            is_hashed: Set True when password is already a SHA-256 hex digest.
                Defaults to False, so a plain password is hashed here.

        Returns:
            Dictionary containing folder details and contents
        """
        url = f"{self.BASE_API_URL}/contents/{content_id}"

        params = {}
        if password:
            # The API expects a SHA-256 hex digest. Whether the caller already
            # hashed it must be stated, not guessed: a 64-character plaintext
            # password would otherwise be sent unhashed.
            if not is_hashed:
                password = hashlib.sha256(password.encode()).hexdigest()
            params['password'] = password

        response = self.session.get(url, params=params, timeout=self.timeout)
        return self._handle_response(response)

    # ===== CONTENT OPERATIONS =====

    def update_content(self,
                       content_id: str,
                       attribute: str,
                       attribute_value: Union[str, bool, int]) -> Dict[str, Any]:
        """
        Update a specific attribute of a file or folder.

        Args:
            content_id: ID of the content to update
            attribute: Attribute to modify ('name', 'description', 'tags', 'public', 'expiry', 'password')
            attribute_value: New value for the attribute

        Returns:
            Dictionary containing update confirmation
        """
        url = f"{self.BASE_API_URL}/contents/{content_id}/update"

        # Convert boolean to string if needed
        if isinstance(attribute_value, bool):
            attribute_value = str(attribute_value).lower()

        payload = {
            'attribute': attribute,
            'attributeValue': attribute_value
        }

        response = self.session.put(url, json=payload, timeout=self.timeout)
        return self._handle_response(response)

    def delete_content(self, content_ids: Union[str, List[str]]) -> Dict[str, Any]:
        """
        Delete files and/or folders permanently.

        Args:
            content_ids: Single content ID or list of content IDs to delete

        Returns:
            Dictionary containing deletion confirmation
        """
        url = f"{self.BASE_API_URL}/contents"

        if isinstance(content_ids, list):
            content_ids = ','.join(content_ids)

        payload = {'contentsId': content_ids}

        response = self.session.delete(url, json=payload, timeout=self.timeout)
        return self._handle_response(response)

    def search_content(self,
                       folder_id: str,
                       search_string: str) -> Dict[str, Any]:
        """
        Search for files and folders within a specific folder.

        Args:
            folder_id: ID of the folder to search within
            search_string: Search string to match against names or tags

        Returns:
            Dictionary containing search results
        """
        url = f"{self.BASE_API_URL}/contents/search"

        params = {
            'contentId': folder_id,
            'searchedString': search_string
        }

        response = self.session.get(url, params=params, timeout=self.timeout)
        return self._handle_response(response)

    def copy_content(self,
                     content_ids: Union[str, List[str]],
                     destination_folder_id: str) -> Dict[str, Any]:
        """
        Copy files and/or folders to a destination folder.

        Args:
            content_ids: Single content ID or list of content IDs to copy
            destination_folder_id: ID of the destination folder

        Returns:
            Dictionary containing copy confirmation
        """
        url = f"{self.BASE_API_URL}/contents/copy"

        if isinstance(content_ids, list):
            content_ids = ','.join(content_ids)

        payload = {
            'contentsId': content_ids,
            'folderId': destination_folder_id
        }

        response = self.session.post(url, json=payload, timeout=self.timeout)
        return self._handle_response(response)

    def move_content(self,
                     content_ids: Union[str, List[str]],
                     destination_folder_id: str) -> Dict[str, Any]:
        """
        Move files and/or folders to a destination folder.

        Args:
            content_ids: Single content ID or list of content IDs to move
            destination_folder_id: ID of the destination folder

        Returns:
            Dictionary containing move confirmation
        """
        url = f"{self.BASE_API_URL}/contents/move"

        if isinstance(content_ids, list):
            content_ids = ','.join(content_ids)

        payload = {
            'contentsId': content_ids,
            'folderId': destination_folder_id
        }

        response = self.session.put(url, json=payload, timeout=self.timeout)
        return self._handle_response(response)

    def import_content(self, content_ids: Union[str, List[str]]) -> Dict[str, Any]:
        """
        Import public content into your account's root folder.

        Args:
            content_ids: Single content ID or list of content IDs to import

        Returns:
            Dictionary containing import confirmation
        """
        url = f"{self.BASE_API_URL}/contents/import"

        if isinstance(content_ids, list):
            content_ids = ','.join(content_ids)

        payload = {'contentsId': content_ids}

        response = self.session.post(url, json=payload, timeout=self.timeout)
        return self._handle_response(response)

    # ===== DIRECT LINK OPERATIONS =====

    def create_direct_link(self,
                          content_id: str,
                          expire_time: Optional[int] = None,
                          source_ips_allowed: Optional[List[str]] = None,
                          domains_allowed: Optional[List[str]] = None,
                          auth: Optional[List[str]] = None) -> Dict[str, Any]:
        """
        Create a direct access link to content.

        Args:
            content_id: ID of the content
            expire_time: Unix timestamp for link expiration (optional)
            source_ips_allowed: List of allowed IP addresses (optional)
            domains_allowed: List of allowed domains (optional)
            auth: List of username:password combinations (optional)

        Returns:
            Dictionary containing direct link information
        """
        url = f"{self.BASE_API_URL}/contents/{content_id}/directlinks"

        payload = {}
        if expire_time:
            payload['expireTime'] = expire_time
        if source_ips_allowed:
            payload['sourceIpsAllowed'] = source_ips_allowed
        if domains_allowed:
            payload['domainsAllowed'] = domains_allowed
        if auth:
            payload['auth'] = auth

        response = self.session.post(url, json=payload, timeout=self.timeout)
        return self._handle_response(response)

    def update_direct_link(self,
                          content_id: str,
                          direct_link_id: str,
                          expire_time: Optional[int] = None,
                          source_ips_allowed: Optional[List[str]] = None,
                          domains_allowed: Optional[List[str]] = None,
                          auth: Optional[List[str]] = None) -> Dict[str, Any]:
        """
        Update an existing direct link configuration.

        Args:
            content_id: ID of the content
            direct_link_id: ID of the direct link to update
            expire_time: New Unix timestamp for expiration (optional)
            source_ips_allowed: Updated list of allowed IPs (optional)
            domains_allowed: Updated list of allowed domains (optional)
            auth: Updated list of username:password pairs (optional)

        Returns:
            Dictionary containing update confirmation
        """
        url = f"{self.BASE_API_URL}/contents/{content_id}/directlinks/{direct_link_id}"

        payload = {}
        if expire_time:
            payload['expireTime'] = expire_time
        if source_ips_allowed:
            payload['sourceIpsAllowed'] = source_ips_allowed
        if domains_allowed:
            payload['domainsAllowed'] = domains_allowed
        if auth:
            payload['auth'] = auth

        response = self.session.put(url, json=payload, timeout=self.timeout)
        return self._handle_response(response)

    def delete_direct_link(self,
                          content_id: str,
                          direct_link_id: str) -> Dict[str, Any]:
        """
        Delete a direct link.

        Args:
            content_id: ID of the content
            direct_link_id: ID of the direct link to delete

        Returns:
            Dictionary containing deletion confirmation
        """
        url = f"{self.BASE_API_URL}/contents/{content_id}/directlinks/{direct_link_id}"

        response = self.session.delete(url, timeout=self.timeout)
        return self._handle_response(response)

    # ===== ACCOUNT OPERATIONS =====

    def get_account_id(self) -> Dict[str, Any]:
        """
        Get the account ID associated with the API token.

        Returns:
            Dictionary containing account ID
        """
        url = f"{self.BASE_API_URL}/accounts/getid"

        response = self.session.get(url, timeout=self.timeout)
        return self._handle_response(response)

    def get_account_details(self, account_id: str) -> Dict[str, Any]:
        """
        Get detailed information about an account.

        Args:
            account_id: The account ID

        Returns:
            Dictionary containing account details
        """
        url = f"{self.BASE_API_URL}/accounts/{account_id}"

        response = self.session.get(url, timeout=self.timeout)
        return self._handle_response(response)

    def reset_token(self, account_id: str) -> Dict[str, Any]:
        """
        Reset the API token (new token will be sent to email).

        Args:
            account_id: The account ID

        Returns:
            Dictionary containing reset confirmation
        """
        url = f"{self.BASE_API_URL}/accounts/{account_id}/resettoken"

        response = self.session.post(url, timeout=self.timeout)
        return self._handle_response(response)


# ===== UTILITY FUNCTIONS =====

def hash_password(password: str) -> str:
    """
    Hash a password using SHA-256.

    Args:
        password: Plain text password

    Returns:
        SHA-256 hash of the password
    """
    return hashlib.sha256(password.encode()).hexdigest()


if __name__ == "__main__":
    # Example usage
    print("Gofile API Client")
    print("-" * 50)

    # Example 1: Guest upload (no token required)
    print("\nExample 1: Guest Upload")
    print("api = GofileAPI()")
    print("result = api.upload_file('myfile.txt')")

    # Example 2: Upload with token to specific folder
    print("\nExample 2: Authenticated Upload")
    print("api = GofileAPI(api_token='YOUR_TOKEN')")
    print("result = api.upload_file('myfile.txt', folder_id='abc123')")

    # Example 3: Create folder and manage content
    print("\nExample 3: Folder Management")
    print("folder = api.create_folder('parent_folder_id', 'My New Folder')")
    print("content = api.get_content('folder_id')")

    # Example 4: Update content settings
    print("\nExample 4: Update Content")
    print("api.update_content('content_id', 'public', True)")
    print("api.update_content('content_id', 'name', 'New Name')")

    print("\n" + "-" * 50)
    print("For full documentation, see API Documentation.md")
