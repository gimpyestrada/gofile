"""
Gofile API Client
A Python client for interacting with the Gofile API.
Supports file uploads, folder management, content operations, and more.
"""

import hashlib
from pathlib import Path
from typing import Optional, List, Dict, Any, Union

import requests


# Constants for rate limiting and hashing
BACKOFF_BASE_SECONDS = 5
SHA256_HASH_LENGTH = 64


class RateLimitException(Exception):
    """Exception raised when API rate limit is exceeded."""
    pass


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
    
    def __init__(self, api_token: Optional[str] = None, timeout: int = 30):
        """
        Initialize the Gofile API client.
        
        Args:
            api_token: Your Gofile API token (optional for guest uploads)
            timeout: Request timeout in seconds (default: 30)
        """
        self.api_token = api_token
        self.timeout = timeout
        self.session = requests.Session()
        if api_token:
            self.session.headers.update({
                'Authorization': f'Bearer {api_token}'
            })
    
    def _handle_response(self, response: requests.Response, retry_count: int = 0, max_retries: int = 3) -> Dict[str, Any]:
        """
        Handle API response and extract data.
        
        Implements exponential backoff for rate limiting (429 errors).
        Per Gofile support: "We send HTTP 429 when you exceed the limit. 
        Use this as a signal to slow down."
        """
        try:
            response.raise_for_status()
            data = response.json()
            if data.get('status') == 'ok':
                return data.get('data', {})
            else:
                raise Exception(f"API Error: {data}")
        except requests.exceptions.HTTPError as e:
            if response.status_code == 429:
                # Rate limit hit - use exponential backoff
                if retry_count < max_retries:
                    import time
                    wait_time = (2 ** retry_count) * 5  # 5, 10, 20 seconds
                    print(f"⚠ Rate limit (429) - Waiting {wait_time}s before retry {retry_count + 1}/{max_retries}...")
                    time.sleep(wait_time)
                    # Note: Caller needs to retry the actual request
                    raise RateLimitException(f"Rate limit exceeded. Waited {wait_time}s. Retry attempt {retry_count + 1}/{max_retries}")
                else:
                    raise RateLimitException(f"Rate limit exceeded after {max_retries} retries. Please wait a few minutes before trying again.")
            raise Exception(f"HTTP Error: {e}")
        except RateLimitException:
            raise
        except Exception as e:
            raise Exception(f"Error: {e}")


    def _make_request_with_retry(self, method: str, url: str, max_retries: int = 3, **kwargs):
        """
        Make an API request with automatic retry on rate limit (429).
        
        Args:
            method: HTTP method ('get', 'post', 'put', 'delete')
            url: Request URL
            max_retries: Maximum number of retries for 429 errors
            **kwargs: Additional arguments to pass to requests
        
        Returns:
            Response data
        """
        import time
        
        for attempt in range(max_retries + 1):
            try:
                # Make the request
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
                
                # Check for rate limit before processing response
                if response.status_code == 429:
                    if attempt < max_retries:
                        wait_time = (2 ** attempt) * BACKOFF_BASE_SECONDS
                        print(f"⚠ Rate limit (429) - Waiting {wait_time}s before retry {attempt + 1}/{max_retries}...")
                        time.sleep(wait_time)
                        continue
                    else:
                        raise RateLimitException(f"Rate limit exceeded after {max_retries} retries. Please wait a few minutes.")
                
                # Process successful response
                return self._handle_response(response)

            except RateLimitException:
                raise
            except Exception:
                if attempt == max_retries:
                    raise
                raise
        
        raise RateLimitException("Max retries exceeded")
    
    # ===== UPLOAD OPERATIONS =====
    
    def upload_file(self, 
                    file_path: str, 
                    folder_id: Optional[str] = None,
                    region: str = 'auto') -> Dict[str, Any]:
        """
        Upload a file to Gofile.
        
        Args:
            file_path: Path to the file to upload
            folder_id: Destination folder ID (optional, creates new folder if not provided)
            region: Upload region ('auto', 'eu-par', 'na-phx', 'ap-sgp', 'ap-hkg', 'ap-tyo', 'sa-sao')
        
        Returns:
            Dictionary containing upload response with file information
        """
        upload_url = self.UPLOAD_REGIONS.get(region, self.BASE_UPLOAD_URL)
        url = f"{upload_url}/uploadfile"
        
        file_path_obj = Path(file_path)
        if not file_path_obj.exists():
            raise FileNotFoundError(f"File not found: {file_path}")
        
        with open(file_path, 'rb') as f:
            files = {'file': (file_path_obj.name, f)}
            data = {}
            if folder_id:
                data['folderId'] = folder_id
            
            response = self.session.post(url, files=files, data=data, timeout=self.timeout)
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
                    password: Optional[str] = None) -> Dict[str, Any]:
        """
        Get detailed information about a folder and its contents.
        
        Args:
            content_id: ID of the folder
            password: SHA-256 hash of password for protected content (optional)
        
        Returns:
            Dictionary containing folder details and contents
        """
        url = f"{self.BASE_API_URL}/contents/{content_id}"
        
        params = {}
        if password:
            # If password is provided, hash it with SHA-256
            if len(password) != SHA256_HASH_LENGTH:
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
