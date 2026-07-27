"""
Buzzheavier API Client
A Python client for interacting with the Buzzheavier API.
Supports file uploads, folder management, and content operations.
"""

import time
from pathlib import Path
from typing import Optional, Dict, Any
from urllib.parse import quote

import requests

from upload_common import (
    BACKOFF_BASE_SECONDS,
    UPLOAD_CONNECT_TIMEOUT,
    UPLOAD_MAX_RETRIES,
    UPLOAD_RETRY_DELAY,
    ProgressTrackingFile,
)


class BuzzheavierAPIError(Exception):
    """Base exception for Buzzheavier API errors."""


class BuzzheavierHTTPError(BuzzheavierAPIError):
    """Exception for HTTP-level errors (network, timeout, etc)."""


class BuzzheavierResponseError(BuzzheavierAPIError):
    """Exception for API response errors (invalid status, etc)."""


class RateLimitException(BuzzheavierAPIError):
    """Exception raised when API rate limit is exceeded."""


class NetworkException(BuzzheavierAPIError):
    """Exception raised for transient network errors that may be retryable."""


class BuzzheavierAPI:
    """Client for interacting with the Buzzheavier API."""

    # Base URLs
    BASE_API_URL = "https://buzzheavier.com/api"
    BASE_UPLOAD_URL = "https://w.buzzheavier.com"
    
    # Upload location IDs
    LOCATION_CENTRAL_EUROPE = "3eb9t1559lkv"
    LOCATION_EASTERN_US = "12brteedoy0f"
    LOCATION_WESTERN_US = "95542dt0et21"

    def __init__(self, account_id: Optional[str] = None, timeout: int = 30, upload_stall_timeout: int = 120, 
                 preferred_location: Optional[str] = None):
        """
        Initialize the Buzzheavier API client.

        Args:
            account_id: Your Buzzheavier account ID (required for authenticated operations)
            timeout: Request timeout in seconds for non-upload requests (default: 30)
            upload_stall_timeout: Seconds of no upload progress before timing out (default: 120)
            preferred_location: Preferred upload location ID (defaults to Eastern US for best US performance)
        """
        self.account_id = account_id
        self.timeout = timeout
        self.upload_stall_timeout = upload_stall_timeout
        # Default to Eastern US for best US coverage, user can override with Western US if preferred
        self.preferred_location = preferred_location or self.LOCATION_EASTERN_US
        self.session = requests.Session()
        if account_id:
            self.session.headers.update({
                'Authorization': f'Bearer {account_id}'
            })

    def _handle_response(self, response: requests.Response) -> Dict[str, Any]:
        """
        Handle API response and extract data.

        Implements exponential backoff for rate limiting (429 errors).
        """
        try:
            response.raise_for_status()
            data = response.json()
            
            # Buzzheavier wraps responses in {"code": 200, "data": {...}}
            # Extract the nested data if present
            if 'data' in data:
                return data['data']
            
            return data
            
        except requests.exceptions.HTTPError as e:
            if response.status_code == 429:
                raise RateLimitException(f"Rate limit exceeded: {e}") from e
            raise BuzzheavierHTTPError(f"HTTP Error: {e}") from e
        except RateLimitException:
            raise
        except BuzzheavierAPIError:
            raise
        except Exception as e:
            raise BuzzheavierAPIError(f"Error: {e}") from e

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
        if method == 'patch':
            return self.session.patch(url, timeout=self.timeout, **kwargs)

        raise ValueError(f"Unsupported HTTP method: {method}")

    def _handle_rate_limit(self, attempt: int, max_retries: int):
        """
        Handle rate limit with exponential backoff.

        Uses exponential backoff (2^attempt * base) to avoid overwhelming the API
        while giving progressively longer recovery time as failures increase.
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
            method: HTTP method ('get', 'post', 'put', 'delete', 'patch')
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
                    raise NetworkException(
                        f"Request failed after {max_retries} retries: {e}"
                    ) from e
                time.sleep((2 ** attempt) * BACKOFF_BASE_SECONDS)

        raise RateLimitException("Max retries exceeded")

    # ===== UPLOAD OPERATIONS =====

    def upload_file(self,
                    file_path: str,
                    parent_id: Optional[str] = None,
                    location_id: Optional[str] = None,
                    max_retries: int = UPLOAD_MAX_RETRIES) -> Dict[str, Any]:
        """
        Upload a file to Buzzheavier with automatic retry on network errors.

        Args:
            file_path: Path to the file to upload
            parent_id: Destination parent directory ID (optional, uploads to root if not provided)
            location_id: Upload location ID (optional, uses preferred_location if not specified)
            max_retries: Maximum retry attempts for network errors (default: 3)

        Returns:
            Dictionary containing upload response with file information
        """
        file_path_obj = Path(file_path)
        if not file_path_obj.exists():
            raise FileNotFoundError(f"File not found: {file_path}")
        if not file_path_obj.is_file():
            raise ValueError(f"Path is not a file: {file_path}")

        # Use specified location or fall back to preferred location
        upload_location = location_id or self.preferred_location

        # Percent-encode the name: '#', '?', and '%' in a filename would
        # otherwise truncate the path or corrupt the query string.
        encoded_name = quote(file_path_obj.name, safe='')

        if parent_id:
            url = f"{self.BASE_UPLOAD_URL}/{parent_id}/{encoded_name}?locationId={upload_location}"
        else:
            url = f"{self.BASE_UPLOAD_URL}/{encoded_name}?locationId={upload_location}"

        # Retry loop for transient network errors
        last_exception = None
        for attempt in range(max_retries + 1):
            try:
                with open(file_path, 'rb') as f:
                    # Wrap file with progress tracker to prevent timeout during active uploads
                    progress_file = ProgressTrackingFile(f, self.upload_stall_timeout)
                    
                    # ProgressTrackingFile only fires while the body is still
                    # being read, so a read timeout is still needed to catch a
                    # connection that dies while awaiting the response.
                    response = self.session.put(
                        url, data=progress_file,
                        timeout=(UPLOAD_CONNECT_TIMEOUT,
                                 self.upload_stall_timeout)
                    )
                    return self._handle_response(response)
                    
            except requests.exceptions.RequestException as e:
                # Catch all requests-related exceptions (ConnectionError, Timeout, etc.)
                last_exception = e
                error_msg = str(e)
                
                # Check if this is the last attempt
                if attempt < max_retries:
                    wait_time = UPLOAD_RETRY_DELAY * (attempt + 1)
                    print(f"⚠ Network error during upload: {error_msg}")
                    print(f"   Retrying in {wait_time}s (attempt {attempt + 1}/{max_retries})...")
                    time.sleep(wait_time)
                    continue
                else:
                    # All retries exhausted
                    raise NetworkException(
                        f"Upload failed after {max_retries} retries. Last error: {error_msg}"
                    ) from e
            
            except Exception:
                # Non-retryable errors (permissions, file not found, API errors, etc.)
                raise
        
        # This should not be reached, but just in case
        if last_exception:
            raise NetworkException(
                f"Upload failed after {max_retries} retries"
            ) from last_exception

    # ===== FOLDER OPERATIONS =====

    def create_folder(self,
                      parent_directory_id: str,
                      folder_name: str) -> Dict[str, Any]:
        """
        Create a new directory.

        Args:
            parent_directory_id: ID of the parent directory
            folder_name: Name for the new directory

        Returns:
            Dictionary containing the new directory information
        """
        url = f"{self.BASE_API_URL}/fs/{parent_directory_id}"

        payload = {'name': folder_name}

        response = self.session.post(url, json=payload, timeout=self.timeout)
        return self._handle_response(response)

    def get_content(self, directory_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Get detailed information about a directory and its contents.

        Args:
            directory_id: ID of the directory (optional, retrieves root if not provided)

        Returns:
            Dictionary containing directory details and contents
        """
        if directory_id:
            url = f"{self.BASE_API_URL}/fs/{directory_id}"
        else:
            # Get root directory
            url = f"{self.BASE_API_URL}/fs"

        response = self.session.get(url, timeout=self.timeout)
        return self._handle_response(response)

    # ===== CONTENT OPERATIONS =====

    def rename_directory(self, directory_id: str, new_name: str) -> Dict[str, Any]:
        """
        Rename a directory.

        Args:
            directory_id: ID of the directory to rename
            new_name: New name for the directory

        Returns:
            Dictionary containing update confirmation
        """
        url = f"{self.BASE_API_URL}/fs/{directory_id}"

        payload = {'name': new_name}

        response = self.session.patch(url, json=payload, timeout=self.timeout)
        return self._handle_response(response)

    def rename_file(self, file_id: str, new_name: str) -> Dict[str, Any]:
        """
        Rename a file.

        Args:
            file_id: ID of the file to rename
            new_name: New name for the file

        Returns:
            Dictionary containing update confirmation
        """
        url = f"{self.BASE_API_URL}/fs/{file_id}"

        payload = {'name': new_name}

        response = self.session.patch(url, json=payload, timeout=self.timeout)
        return self._handle_response(response)

    def move_directory(self, directory_id: str, new_parent_id: str) -> Dict[str, Any]:
        """
        Move a directory to a new parent directory.

        Args:
            directory_id: ID of the directory to move
            new_parent_id: ID of the new parent directory

        Returns:
            Dictionary containing move confirmation
        """
        url = f"{self.BASE_API_URL}/fs/{directory_id}"

        payload = {'parentId': new_parent_id}

        response = self.session.put(url, json=payload, timeout=self.timeout)
        return self._handle_response(response)

    def move_file(self, file_id: str, new_parent_id: str) -> Dict[str, Any]:
        """
        Move a file to a new parent directory.

        Args:
            file_id: ID of the file to move
            new_parent_id: ID of the new parent directory

        Returns:
            Dictionary containing move confirmation
        """
        url = f"{self.BASE_API_URL}/fs/{file_id}"

        payload = {'parentId': new_parent_id}

        response = self.session.put(url, json=payload, timeout=self.timeout)
        return self._handle_response(response)

    def add_note_to_file(self, file_id: str, note: str) -> Dict[str, Any]:
        """
        Add or change note for a file.

        Args:
            file_id: ID of the file
            note: Note text to add to the file

        Returns:
            Dictionary containing update confirmation
        """
        url = f"{self.BASE_API_URL}/fs/{file_id}"

        payload = {'note': note}

        response = self.session.put(url, json=payload, timeout=self.timeout)
        return self._handle_response(response)

    def delete_directory(self, directory_id: str) -> Dict[str, Any]:
        """
        Delete a directory and its subdirectories.

        Args:
            directory_id: ID of the directory to delete

        Returns:
            Dictionary containing deletion confirmation
        """
        url = f"{self.BASE_API_URL}/fs/{directory_id}"

        response = self.session.delete(url, timeout=self.timeout)
        return self._handle_response(response)

    def delete_file(self, file_id: str) -> Dict[str, Any]:
        """
        Delete a file by ID.

        Args:
            file_id: ID of the file to delete

        Returns:
            Dictionary containing deletion confirmation
        """
        url = f"{self.BASE_API_URL}/fs/{file_id}"
        response = self.session.delete(url, timeout=self.timeout)
        return self._handle_response(response)

    # ===== ACCOUNT OPERATIONS =====

    def get_account_details(self) -> Dict[str, Any]:
        """
        Get detailed information about the authenticated account.

        Returns:
            Dictionary containing account details
        """
        url = f"{self.BASE_API_URL}/account"

        response = self.session.get(url, timeout=self.timeout)
        return self._handle_response(response)


if __name__ == "__main__":
    # Example usage
    print("Buzzheavier API Client")
    print("-" * 50)

    # Example 1: Authenticated upload to root
    print("\nExample 1: Authenticated Upload to Root")
    print("api = BuzzheavierAPI(account_id='YOUR_ACCOUNT_ID')")
    print("result = api.upload_file('myfile.txt')")

    # Example 2: Upload to specific directory
    print("\nExample 2: Upload to Specific Directory")
    print("result = api.upload_file('myfile.txt', parent_id='dir_id')")

    # Example 3: Create directory and manage content
    print("\nExample 3: Directory Management")
    print("root = api.get_content()  # Get root directory")
    print("folder = api.create_folder('parent_id', 'My New Folder')")
    print("content = api.get_content('folder_id')")

    # Example 4: Account information
    print("\nExample 4: Account Information")
    print("account = api.get_account_details()")

    print("\n" + "-" * 50)
