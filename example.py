"""
Gofile API - Simple Example
Demonstrates basic operations with the Gofile API
"""

from gofile_api import GofileAPI
from config_loader import load_config

def main():
    print("=" * 60)
    print("Gofile API - Simple Example")
    print("=" * 60)
    
    # Load your credentials from config.json
    config = load_config()
    api = GofileAPI(api_token=config.api_token)
    
    # 1. Get your account information
    print("\n1. Getting account information...")
    account_details = api.get_account_details(config.account_id)
    print(f"   Email: {account_details['email']}")
    print(f"   Tier: {account_details['tier']}")
    print(f"   Root folder ID: {account_details['rootFolder']}")
    
    root_folder = account_details['rootFolder']
    
    # 2. Create a new folder
    print("\n2. Creating a new folder...")
    new_folder = api.create_folder(root_folder, "Example Folder")
    folder_id = new_folder['id']
    print(f"   ✓ Created folder: {new_folder['name']}")
    print(f"   Folder ID: {folder_id}")
    
    # 3. Upload a file to the folder
    print("\n3. Uploading a test file...")
    # First, create a test file
    test_filename = "test_upload.txt"
    with open(test_filename, 'w') as f:
        f.write("Hello from Gofile API!\nThis is a test upload.")
    
    upload_result = api.upload_file(test_filename, folder_id=folder_id)
    print(f"   ✓ Uploaded: {test_filename}")
    print(f"   Download page: {upload_result['downloadPage']}")
    
    # 4. Get folder contents
    print("\n4. Getting folder contents...")
    contents = api.get_content(folder_id)
    print(f"   Folder: {contents['name']}")
    print(f"   Public: {contents.get('public', 'N/A')}")
    print(f"   Files in folder:")
    for child_id, child in contents.get('children', {}).items():
        print(f"      - {child['name']} ({child['type']}) - {child.get('size', 0)} bytes")
    
    # 5. Update folder settings
    print("\n5. Updating folder settings...")
    api.update_content(folder_id, 'description', 'This is an example folder created via API')
    api.update_content(folder_id, 'tags', 'example,test,api')
    print(f"   ✓ Updated folder description and tags")
    
    # 6. Search for content
    print("\n6. Searching for 'test'...")
    search_results = api.search_content(root_folder, 'test')
    found_count = len(search_results.get('contents', {}))
    print(f"   ✓ Found {found_count} items matching 'test'")
    
    # 7. Clean up - Delete the test folder
    print("\n7. Cleaning up...")
    response = input("   Delete the example folder? (yes/no): ").strip().lower()
    if response == 'yes':
        api.delete_content([folder_id])
        print(f"   ✓ Deleted example folder")
    else:
        print(f"   ⊘ Kept example folder")
        print(f"   You can access it at: https://gofile.io/d/{folder_id}")
    
    # Clean up local test file
    import os
    if os.path.exists(test_filename):
        os.remove(test_filename)
    
    print("\n" + "=" * 60)
    print("Example completed!")
    print("=" * 60)


if __name__ == "__main__":
    try:
        main()
    except FileNotFoundError:
        print("\n✗ Error: config.json not found!")
        print("Please copy config.template.json to config.json and add your credentials.")
    except Exception as e:
        print(f"\n✗ Error: {e}")
