# Gofile API Python Client

A comprehensive Python client library for interacting with the [Gofile.io](https://gofile.io) API. Upload files, manage folders, create direct links, and more with a simple, intuitive interface.

![Version](https://img.shields.io/badge/version-1.0-blue)
![Python](https://img.shields.io/badge/python-3.6+-green)
![License](https://img.shields.io/badge/license-MIT-blue)

## ✨ Features

- 📤 **File Uploads** - Guest and authenticated uploads with regional endpoint support
- 📁 **Folder Management** - Create, organize, and manage your folder structure
- ⚙️ **Content Operations** - Get, update, delete, copy, and move files/folders
- 🔍 **Search Functionality** - Find content quickly across your account
- 🔗 **Direct Links** - Create and manage direct download links (Premium)
- 👤 **Account Management** - Retrieve account information and statistics
- 🔒 **Password Protection** - Access and manage password-protected content
- 🌍 **Regional Endpoints** - Upload to nearest server for optimal performance
- 🚦 **Smart Rate Limiting** - Automatic exponential backoff retry logic
- ⏱️ **Configurable Timeouts** - Customize request timeout settings

## 📦 Installation

### Requirements
- Python 3.6 or higher
- `requests` library

### Setup

1. **Clone this repository**:
```bash
git clone https://github.com/yourusername/gofile-api-python.git
cd gofile-api-python
```

2. **Install dependencies**:
```bash
pip install requests
```

3. **Create your configuration file**:
```bash
cp config.template.json config.json
```

4. **Add your credentials** to `config.json`:
```json
{
  "account_id": "your-account-id-here",
  "api_token": "your-api-token-here"
}
```

### How to Get Your Credentials:

1. Log into [Gofile.io](https://gofile.io)
2. Go to **My Profile** → **Developer Information**
3. Copy your:
   - **Account ID**
   - **Account Token** (use this as `api_token` in config.json)

**Security Note**: Keep your `config.json` private! Never commit it to public repositories.

> **⚠️ Premium Requirement**: Most API endpoints require a premium account. Only basic operations like uploading, creating folders, and removing content are accessible with free accounts. Features like direct links, content copying/moving, and advanced operations require a premium subscription.

## 🚀 Quick Start

### Run the Example

The easiest way to get started is to run the included example:

```bash
python example.py
```

This demonstrates:
- ✅ Getting account information
- ✅ Creating folders
- ✅ Uploading files
- ✅ Retrieving folder contents
- ✅ Updating folder settings
- ✅ Searching for content
- ✅ Deleting content

### Basic Usage

```python
from gofile_api import GofileAPI
from config_loader import load_config

# Load credentials
config = load_config()
api = GofileAPI(api_token=config.api_token)

# Get account details
details = api.get_account_details(config.account_id)
print(f"Account: {details['email']}")
print(f"Tier: {details['tier']}")

# Upload a file
result = api.upload_file('myfile.txt', folder_id=details['rootFolder'])
print(f"Download page: {result['downloadPage']}")
```

### Guest Upload (No Account Required)

```python
from gofile_api import GofileAPI

api = GofileAPI()  # No token needed for guest uploads

result = api.upload_file('myfile.txt')
print(f"Download page: {result['downloadPage']}")
print(f"File ID: {result['fileId']}")
```

## 📚 Usage Examples

### Folder Management

```python
# Create a folder
folder = api.create_folder(parent_folder_id, "My New Folder")
folder_id = folder['id']

# Get folder contents
contents = api.get_content(folder_id)
print(f"Folder name: {contents['name']}")
for child_id, child in contents['children'].items():
    print(f"  - {child['name']} ({child['type']})")

# Update folder attributes
api.update_content(folder_id, 'name', 'Renamed Folder')
api.update_content(folder_id, 'public', 'false')  # Make private
api.update_content(folder_id, 'password', 'mysecretpass')
```

### Content Operations

```python
# Copy content to another folder
api.copy_content(content_id, destination_folder_id)

# Move content to another folder
api.move_content(content_id, destination_folder_id)

# Delete content (files or folders)
api.delete_content([file_id_1, folder_id_2])

# Search for content
results = api.search_content(root_folder_id, query="report")
```

### Direct Links

```python
# Create a direct download link (Premium only)
link = api.create_direct_link(content_id)
print(f"Direct link: {link['directLink']}")

# Update direct link
api.update_direct_link(direct_link_id, 'expiry', '1735689600')  # Unix timestamp

# Delete direct link
api.delete_direct_link(direct_link_id)
```

### Regional Upload

```python
# Upload to specific region for better performance
regions = ['eu-par', 'na-phx', 'ap-sgp', 'ap-hkg', 'ap-tyo', 'sa-sao']

result = api.upload_file('myfile.txt', region='eu-par')  # Europe (Paris)
result = api.upload_file('myfile.txt', region='na-phx')  # North America (Phoenix)
```

### Access Password-Protected Content

```python
# Access content with password
password_hash = api.hash_password('mysecretpass')
contents = api.get_content(folder_id, password=password_hash)
```

## ⚡ Rate Limiting

The API automatically handles rate limits (HTTP 429 responses) with exponential backoff:
- First retry: waits 5 seconds
- Second retry: waits 10 seconds
- Third retry: waits 20 seconds

Per Gofile support:
> "We send HTTP 429 when you exceed the limit. Use this as a signal to slow down. We only ban the IP when you repeatedly hit the limit without slowing down."

The client will automatically retry on rate limits up to 3 times before raising a `RateLimitException`.

## ⚙️ Configuration

### Timeout Settings

```python
# Default timeout is 30 seconds
api = GofileAPI(api_token=your_token)

# Custom timeout
api = GofileAPI(api_token=your_token, timeout=60)  # 60 seconds
```

### Using Config Loader

The `config_loader.py` module provides convenient credential management:

```python
from config_loader import load_config

config = load_config()  # Loads from config.json
print(config.api_token)
print(config.account_id)
```

## 📖 API Reference

### GofileAPI Class

#### `__init__(api_token=None, timeout=30)`
Initialize the API client.

#### `upload_file(file_path, folder_id=None, region='auto')`
Upload a file to Gofile.

#### `create_folder(parent_folder_id, folder_name=None)`
Create a new folder.

#### `get_content(content_id, password=None)`
Get information about a file or folder.

#### `update_content(content_id, attribute, value)`
Update file or folder attributes (name, description, public, password, etc.).

#### `delete_content(content_ids)`
Delete files or folders.

#### `copy_content(content_id, destination_folder_id)`
Copy content to another folder.

#### `move_content(content_id, destination_folder_id)`
Move content to another folder.

#### `search_content(root_folder_id, query)`
Search for content by name.

#### `import_content(content_ids, destination_folder_id)`
Import content from another account.

#### `create_direct_link(content_id)`
Create a direct download link (Premium required).

#### `update_direct_link(direct_link_id, attribute, value)`
Update direct link settings.

#### `delete_direct_link(direct_link_id)`
Delete a direct link.

#### `get_account_id()`
Get your account ID.

#### `get_account_details(account_id)`
Get detailed account information.

## 🚨 Error Handling

```python
from gofile_api import GofileAPI, RateLimitException

api = GofileAPI(api_token=your_token)

try:
    result = api.upload_file('large_file.zip')
except RateLimitException as e:
    print(f"Rate limit exceeded: {e}")
    # Wait and retry later
except Exception as e:
    print(f"Error: {e}")
```

## 🔒 Security Best Practices

1. **Never commit `config.json`** - It's already in `.gitignore`
2. **Keep your API token secret** - Treat it like a password
3. **Use environment variables** for production deployments
4. **Rotate your tokens regularly** from your Gofile profile

## 🤝 Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## �️ Development

This project uses GitHub Copilot to assist with code generation and optimization. All code has been reviewed and tested before deployment.

## �📄 License

MIT License - Feel free to use, modify, and distribute!

## ⚠️ Disclaimer

This is an unofficial client library. It is not affiliated with or endorsed by Gofile.io.

## 🔗 Links

- [Gofile.io](https://gofile.io) - Official website
- [Gofile API Documentation](https://gofile.io/api) - API reference
- [Developer Information](https://gofile.io/myprofile) - Get your credentials

## 💬 Support

- **For Gofile API issues**: Contact [Gofile Support](https://gofile.io/contact)
- **For library issues**: Open an issue on GitHub

---

**Made with ❤️ for the developer community**
