API Documentation
Last Updated: May 16, 2025
Integrate Gofile's powerful storage and content delivery capabilities into your applications with our REST API.

BETA Status
🧪 This API is currently in BETA and may undergo changes and improvements. We recommend checking this documentation regularly for updates and new features.

Authentication
All API requests require an API token for authentication. Include your token in the request headers:

Authorization: Bearer YOUR_API_TOKEN
Get your API token from your profile page.

Premium Requirement: Most API endpoints require a premium account. Only basic operations like uploading, creating folders, and removing content are accessible with free accounts.

Rate Limits
Rate limits are enforced on a per-endpoint basis. When exceeded, requests will receive a 429 Too Many Requests response.

For security reasons, specific rate limit values are not publicly disclosed. Normal API usage should not trigger these limits.

⚠️ Repeatedly exceeding rate limits may result in automatic IP bans.
💡 Need higher limits for your use case? Contact our support team to discuss custom solutions.

Account Structure
Each account is assigned a permanent root folder that serves as the base for all content organization:

Account → Root Folder → Contents (Files & Subfolders)

All files and subfolders must exist within this root structure. The root folder cannot be deleted or moved.

Endpoints
POST
https://upload.gofile.io/uploadfile
Upload files directly using our global upload endpoint.

ℹ️ When uploading without parameters, the system will:
Create a guest account
Generate a new public folder in the root directory
Upload the file to this folder
Regional Upload Endpoints
You can choose specific regional upload proxies for optimized performance:

upload.gofile.io Automatic (Closest Region)
upload-eu-par.gofile.io Europe (Paris)
upload-na-phx.gofile.io North America (Phoenix)
upload-ap-sgp.gofile.io Asia Pacific (Singapore)
upload-ap-hkg.gofile.io Asia Pacific (Hong Kong)
upload-ap-tyo.gofile.io Asia Pacific (Tokyo)
upload-sa-sao.gofile.io South America (São Paulo)
Parameters Content-Type: multipart/form-data
file
file
required
The file to be uploaded to the server

folderId
string
optional
Identifier of the destination folder. If not provided, a new public folder will be created.

💡 You can reuse the guest account ID and folder ID from previous uploads to add more files to the same folder in subsequent requests.

POST
https://api.gofile.io/contents/createFolder
Creates a new folder within your specified parent folder. Use this endpoint to organize your content hierarchically.

ℹ️ The newly created folder inherits access permissions from its parent folder. You can later modify these permissions through the folder settings.
Parameters Content-Type: application/json
parentFolderId
string
required
The identifier of the parent folder where the new folder will be created. Must be a valid folder ID from your account.

folderName
string
optional
Custom name for the new folder. If not provided, the system will generate a unique folder name automatically.

PUT
https://api.gofile.io/contents/{contentId}/update
Modify specific attributes of a file or folder. Different attributes are available depending on the content type.

Parameters Content-Type: application/json
attribute
string
required
The attribute to modify. Available options:

name Content name (files & folders)
description Download page description (folders only)
tags Comma-separated tags (folders only)
public Public access status (folders only)
expiry Expiration date timestamp (folders only)
password Access password (folders only)
attributeValue
mixed
required
The new value for the specified attribute. Expected format depends on the attribute:

name	String value for the content name
description	Text description for the download page
tags	Comma-separated string (e.g., "tag1,tag2,tag3")
public	Boolean string ("true" or "false")
expiry	Unix timestamp (e.g., 1704067200)
password	String value for the access password
⚠️ Some attributes are only available for folders. Attempting to modify these attributes on files will result in an error response.
DELETE
https://api.gofile.io/contents
Permanently deletes specified files and folders from your account. This action cannot be undone.

🚨 Warning: Deleting a folder will also remove all its contents, including subfolders and files.
Parameters Content-Type: application/json
contentsId
string
required
A comma-separated list of content IDs to delete.

ℹ️ You can only delete content that belongs to your account. Attempting to delete content you don't own will result in an error.

GET
https://api.gofile.io/contents/{contentId}
Retrieves detailed information about a folder and its contents, including metadata and file listings.

ℹ️ This endpoint only works with folder IDs. File information is included within the folder details when present.
Parameters Query Parameters
password
string
optional
SHA-256 hash of the password for accessing password-protected content

🔒 Required only when accessing password-protected folders
GET
https://api.gofile.io/contents/search
Search for files and folders within a specific parent folder based on name or tags.

ℹ️ The search is performed recursively through all subfolders of the specified folder. Results include both files and folders that match the search criteria.
Parameters Query Parameters
contentId
string
required
The identifier of the folder to search within. Must be a valid folder ID from your account.

searchedString
string
required
Search string to match against content names or tags.

Search Behavior
✅ Matches are case-insensitive
✅ Partial matches are supported (e.g., searching "doc" will match "document.pdf")
✅ Results include matches in both content names and tags
POST
https://api.gofile.io/contents/{contentId}/directlinks
Creates a direct access link to your content. For folders, the system automatically generates a ZIP archive containing all files.

ℹ️ Direct links provide immediate access to content without going through the download page interface. You can secure access using various restrictions like IP whitelist, domain limitations, or basic authentication.
Parameters Content-Type: application/json
expireTime
integer
optional
Unix timestamp when the direct link should expire. If not specified, the link will remain active indefinitely.

sourceIpsAllowed
array
optional
Array of IP addresses allowed to access the direct link. Access will be restricted to these IPs only.

["192.168.1.1", "10.0.0.1"]
domainsAllowed
array
optional
Array of domains allowed to embed or access the direct link. Useful for restricting content embedding.

["example.com", "subdomain.example.com"]
auth
array
optional
Array of username:password combinations required for basic authentication access.

["user1:pass1", "user2:pass2"]
PUT
https://api.gofile.io/contents/{contentId}/directlinks/{directLinkId}
Updates the configuration of an existing direct link. Use this endpoint to modify access restrictions or update expiration settings.

Parameters Content-Type: application/json
expireTime
integer
optional
New Unix timestamp for link expiration.

sourceIpsAllowed
array
optional
Updated list of allowed IP addresses.

["192.168.1.1", "10.0.0.1"]
domainsAllowed
array
optional
Updated list of allowed domains.

["example.com", "subdomain.example.com"]
auth
array
optional
Updated list of username:password pairs.

["user1:pass1", "user2:pass2"]
ℹ️ If a parameter is not included in the request, its corresponding restriction will be removed. To maintain existing restrictions, you must include the parameter with its desired value in the request.
DELETE
https://api.gofile.io/contents/{contentId}/directlinks/{directLinkId}
Permanently removes a direct link to content. Once deleted, the link cannot be recovered.

ℹ️ This action only removes the direct link access - it does not affect the underlying content or other existing direct links to the same content.
POST
https://api.gofile.io/contents/copy
Copy multiple files or folders to a specified destination folder.

Parameters Content-Type: application/json
contentsId
string
required
Comma-separated list of content IDs to copy.

folderId
string
required
The identifier of the destination folder where contents will be copied to.

PUT
https://api.gofile.io/contents/move
Move multiple files and/or folders to a specified destination folder. This operation preserves all content attributes and permissions while updating their location in your storage hierarchy.

ℹ️ Moving contents is an atomic operation - either all specified contents are moved successfully, or none are moved if an error occurs.
Parameters Content-Type: application/json
contentsId
string
required
Comma-separated list of content IDs to be moved. Can include both file and folder IDs.

folderId
string
required
The identifier of the destination folder where the contents will be moved. Must be a valid folder ID from your account.

⚠️ Moving folders will also move all their contents recursively. Ensure you have sufficient permissions in both source and destination locations.
POST
https://api.gofile.io/contents/import
Import public content into your account's root folder. This is useful for saving shared content to your personal storage space.

Parameters Content-Type: application/json
contentsId
string
required
Comma-separated list of content IDs to import into your root folder

⚠️ Only publicly accessible content can be imported. Attempting to import private or password-protected content will result in an error.
GET
https://api.gofile.io/accounts/getid
Retrieves the account ID associated with the provided API token. This endpoint is useful for identifying your account when making subsequent API calls.

ℹ️ The account ID is a unique identifier that represents your Gofile account and is required for various operations involving account-specific resources.
GET
https://api.gofile.io/accounts/{accountId}
Retrieves detailed information about a specific account.

ℹ️ The account ID can be obtained using the /accounts/getid endpoint.
POST
https://api.gofile.io/accounts/{accountId}/resettoken
Resets your current authentication token and generates a new one. A login link containing the new token will be sent to your registered email address.

ℹ️ The account ID can be obtained using the /accounts/getid endpoint.
⚠️ Warning: Your current token will be immediately invalidated upon request. Make sure to update your applications with the new token once received.
Need help with integration? Contact our support team.

Home
|
Terms of Service
|
Privacy Policy
|
Copyright
|
Contact
WOJTEK SAS © 2025, made with ❤️ by Gofile Team