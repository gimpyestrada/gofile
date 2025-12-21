"""
Pixeldrain API Client
A Python client for interacting with the Pixeldrain API.
Supports file uploads and list management.
"""

import time
import base64
from pathlib import Path
from typing import Optional, Dict, Any
from io import BufferedReader

import requests


class PixeldrainAPIError(Exception):
    """Base exception for Pixeldrain API errors."""


class PixeldrainHTTPError(PixeldrainAPIError):
    """Exception for HTTP-level errors (network, timeout, etc)."""


class RateLimitException(PixeldrainAPIError):
    """Exception raised when API rate limit is exceeded."""


class NetworkException(PixeldrainAPIError):
    """Exception for network-related issues."""


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
            raise TimeoutError(f"Upload stalled - no data transferred for {self.timeout_seconds}s")
        
        data = self.file_obj.read(size)
        if data:
            self.last_read_time = time.time()
        return data
    
    def __getattr__(self, name):
        """Delegate other attributes to the wrapped file object."""
        return getattr(self.file_obj, name)


class PixeldrainAPI:
    """Client for interacting with the Pixeldrain API."""

    BASE_API_URL = "https://pixeldrain.com/api"

    def __init__(self, api_key: Optional[str] = None, timeout: int = 30, upload_stall_timeout: int = 120):
        """
        Initialize the Pixeldrain API client.

        Args:
            api_key: Your Pixeldrain API key
            timeout: Request timeout in seconds for non-upload requests (default: 30)
            upload_stall_timeout: Seconds of no upload progress before timing out (default: 120)
        """
        self.api_key = api_key
        self.timeout = timeout
        self.upload_stall_timeout = upload_stall_timeout
        self.session = requests.Session()
        
        if api_key:
            self.session.auth = ("", api_key)

    def _handle_response(self, response: requests.Response) -> Dict[str, Any]:
        """Handle API response and extract data."""
        try:
            response.raise_for_status()
            
            content_type = response.headers.get('content-type', '')
            
            if content_type.startswith('application/json'):
                return response.json()
            elif content_type.startswith('text/plain'):
                # Pixeldrain PUT returns JSON as text/plain, parse it
                import json
                try:
                    return json.loads(response.text.strip())
                except json.JSONDecodeError:
                    # Fallback if it's actually plain text
                    return {"id": response.text.strip()}
            
            return {"success": True}
            
        except requests.exceptions.HTTPError as e:
            if response.status_code == 429:
                raise RateLimitException(f"Rate limit exceeded: {e}")
            elif response.status_code >= 500:
                raise NetworkException(f"Server error: {e}")
            else:
                try:
                    error_data = response.json()
                    raise PixeldrainHTTPError(f"HTTP Error {response.status_code}: {error_data}")
                except:
                    raise PixeldrainHTTPError(f"HTTP Error: {e}")
        except requests.exceptions.ConnectionError as e:
            raise NetworkException(f"Connection error: {e}")
        except requests.exceptions.Timeout as e:
            raise NetworkException(f"Request timeout: {e}")
        except requests.exceptions.RequestException as e:
            raise NetworkException(f"Network error: {e}")
        except Exception as e:
            raise PixeldrainAPIError(f"Unexpected error: {e}")

    def _make_request_with_retry(self, method: str, url: str, max_retries: int = 3, **kwargs):
        """Execute request with retry logic for rate limits and network errors."""
        for attempt in range(max_retries):
            try:
                if method == 'get':
                    response = self.session.get(url, timeout=self.timeout, **kwargs)
                elif method == 'post':
                    response = self.session.post(url, timeout=self.timeout, **kwargs)
                elif method == 'put':
                    response = self.session.put(url, timeout=self.timeout, **kwargs)
                elif method == 'delete':
                    response = self.session.delete(url, timeout=self.timeout, **kwargs)
                else:
                    raise ValueError(f"Unsupported HTTP method: {method}")
                
                return self._handle_response(response)
                
            except RateLimitException as e:
                if attempt < max_retries - 1:
                    wait_time = (2 ** attempt) * 5
                    time.sleep(wait_time)
                    continue
                raise
            except NetworkException as e:
                if attempt < max_retries - 1:
                    wait_time = (2 ** attempt) * 2
                    time.sleep(wait_time)
                    continue
                raise

    def upload_file(self, file_path: str, list_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Upload a file to Pixeldrain using PUT method.

        Args:
            file_path: Path to the file to upload
            list_id: Optional list ID to add the file to after upload

        Returns:
            Dict containing file information including 'id' (file ID)
        """
        file_path = Path(file_path)
        
        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")
        
        # Use PUT /file/{name} as recommended in documentation
        url = f"{self.BASE_API_URL}/file/{file_path.name}"
        
        with open(file_path, 'rb') as f:
            tracked_file = ProgressTrackingFile(f, self.upload_stall_timeout)
            
            try:
                response = self.session.put(url, data=tracked_file, timeout=None)
                return self._handle_response(response)
            except TimeoutError as e:
                raise NetworkException(str(e))

    def get_file_info(self, file_id: str) -> Dict[str, Any]:
        """
        Get information about a file.

        Args:
            file_id: The file ID

        Returns:
            Dict containing file information
        """
        url = f"{self.BASE_API_URL}/file/{file_id}/info"
        return self._make_request_with_retry('get', url)

    def get_user_files(self) -> Dict[str, Any]:
        """
        Get all files for the authenticated user.

        Returns:
            Dict containing list of user files
        """
        if not self.api_key:
            raise PixeldrainAPIError("Authentication required for this endpoint")
        
        url = f"{self.BASE_API_URL}/user/files"
        return self._make_request_with_retry('get', url)

    def get_user_lists(self) -> Dict[str, Any]:
        """
        Get all lists for the authenticated user.

        Returns:
            Dict containing list of user lists
        """
        if not self.api_key:
            raise PixeldrainAPIError("Authentication required for this endpoint")
        
        url = f"{self.BASE_API_URL}/user/lists"
        return self._make_request_with_retry('get', url)

    def create_list(self, title: str, files: Optional[list] = None, anonymous: bool = False) -> Dict[str, Any]:
        """
        Create a new list.

        Args:
            title: List title
            files: Optional list of file IDs to include
            anonymous: Whether the list should be anonymous

        Returns:
            Dict containing list information including 'id'
        """
        if not self.api_key:
            raise PixeldrainAPIError("Authentication required for this endpoint")
        
        url = f"{self.BASE_API_URL}/list"
        
        data = {
            "title": title,
            "anonymous": anonymous
        }
        
        if files:
            data["files"] = files
        
        return self._make_request_with_retry('post', url, json=data)

    def get_list(self, list_id: str) -> Dict[str, Any]:
        """
        Get list contents.

        Args:
            list_id: The list ID

        Returns:
            Dict containing list information and files
        """
        url = f"{self.BASE_API_URL}/list/{list_id}"
        return self._make_request_with_retry('get', url)
