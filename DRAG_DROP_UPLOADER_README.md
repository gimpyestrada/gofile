# Multi-Host Drag & Drop Uploader

A powerful GUI application that lets you drag and drop APK files to automatically upload them to **Gofile, Buzzheavier, and Pixeldrain** with intelligent folder organization and configurable host selection. Perfect for developers and testers who need reliable file hosting with maximum redundancy.

![Version](https://img.shields.io/badge/version-3.0-blue)
![Python](https://img.shields.io/badge/python-3.6+-green)
![License](https://img.shields.io/badge/license-MIT-blue)

## ✨ Features

- 🚀 **Multi-Host Uploads**: Automatically uploads to Gofile, Buzzheavier, and/or Pixeldrain in parallel
- ⚙️ **Configurable Hosts**: Choose which hosts to upload to via settings menu
- 📁 **Drag & Drop Interface**: Just drag APK files onto the window
- 📚 **Multi-File Drop Queue**: Drop multiple APKs at once; uploads run sequentially
- 🔍 **Batch Duplicate Detection**: Scans all queued files upfront with single decision dialog for unattended uploads
- 🤖 **Intelligent Folder Management**: Automatically organizes files on Gofile and Buzzheavier
- 🔗 **Multi-Host Public Links**: Get public links from all enabled hosts immediately as they finish
- � **Copy All Links**: One-click button to copy all enabled host links to clipboard (one per line)
- �📊 **Dynamic Activity Logs**: Separate real-time logs for each enabled host
- ⚡ **Colored Status Indicators**: Text indicators (✓ success, ✗ failure, ⟳ uploading) for each host
- 🔄 **Individual Retry**: Retry failed uploads on any host independently
- 🚀 **Upload Speed Display**: Shows transfer speed in MB/s and Mbps for each host
- 💾 **Smart Caching**: Remembers folder structure for Gofile and Buzzheavier
- 👁️ **Dynamic Visibility**: Only shows logs and links for enabled hosts

## 📦 Installation

1. **Clone or download** this repository

2. **Install Python dependencies**:
```powershell
pip install requests tkinterdnd2
```

3. **Create your config file** (see Configuration section below)

4. **Run the application**:
```powershell
python drag_drop_uploader.py
```

### Optional: Build Your Own Executable

If you want a standalone .exe file, you can build it yourself:

```powershell
pip install pyinstaller
python -m PyInstaller --onefile --windowed --name "GofileUploader" drag_drop_uploader.py
```

The executable will be in the `dist/` folder. Remember to keep `config.json` in the same directory as the .exe!

## ⚙️ Configuration

Create a `config.json` file in the same directory as the application:

```json
{
  "api_token": "your_gofile_api_token",
  "account_id": "your_gofile_account_id",
  "buzzheavier_account_id": "your_buzzheavier_account_id",
  "pixeldrain_api_key": "your_pixeldrain_api_key",
  "gofile_enabled": true,
  "buzzheavier_enabled": false,
  "pixeldrain_enabled": false
}
```

### How to Get Your Credentials:

**Gofile:**
1. Log into [Gofile.io](https://gofile.io)
2. Go to **My Profile** → **Developer Information**
3. Copy your:
   - **Account ID** (use as `account_id`)
   - **Account Token** (use as `api_token`)

**Buzzheavier:**
1. Log into [Buzzheavier.com](https://buzzheavier.com)
2. Go to **My Profile** → **API Settings**
3. Copy your:
   - **Account ID** (20-character alphanumeric, use as `buzzheavier_account_id`)

**Pixeldrain:**
1. Log into [Pixeldrain.com](https://pixeldrain.com)
2. Go to **User** → **API Keys**
3. Create or copy your API key (use as `pixeldrain_api_key`)

### Host Settings:

- `gofile_enabled`: Set to `true` to enable Gofile uploads (default: true)
- `buzzheavier_enabled`: Set to `true` to enable Buzzheavier uploads (default: false)
- `pixeldrain_enabled`: Set to `true` to enable Pixeldrain uploads (default: false)

You can also change these settings at runtime using the gear icon (⚙️) in the application.

**Security Note**: Keep your `config.json` private! It contains your API credentials. Never commit it to public repositories.

## 🚀 Usage

### Running the Script

Simply run the script:
```powershell
python drag_drop_uploader.py
```

### Normal Mode (Full Window - 900x650)

A window will appear:
1. Wait for enabled hosts to initialize (shows connection status)
2. Click the gear icon (⚙️) to configure which hosts to use
3. Drag and drop one or more APK files onto the drop zone
4. Watch activity logs for each enabled host simultaneously:
   - Parses the APK filename
   - Finds or creates the parent folder (Gofile/Buzzheavier)
   - Creates the version folder (Gofile/Buzzheavier)
   - Uploads the file (shows speed in MB/s and Mbps)
   - Makes the folder public (Gofile) or generates direct link (Buzzheavier/Pixeldrain)
   - Displays the public link
5. Public links appear in separate text boxes as each host completes
6. Status indicators show: ⟳ orange (uploading), ✓ green (success), or ✗ red (failure) for each host
7. Use "Copy" to copy a link, "Open" to open in browser, or "Retry" to retry a failed upload
8. Use "Copy All Links" button to copy all enabled host links at once (one per line)
9. Only enabled hosts are visible in the UI
10. Non-APK drops are skipped automatically with highlighted log entries

## 🔧 How It Works

### Folder Organization

**Gofile & Buzzheavier**: The uploader automatically organizes your APKs into a hierarchical structure. Trailing `-release` is trimmed from the folder name, but the uploaded APK file name is kept as-is:

```
Gofile/Buzzheavier Root/
├── com.example.app/
│   ├── com.example.app-1.0.0/
│   │   └── com.example.app-1.0.0-release.apk
│   └── com.example.app-2.0.0-beta/
│       └── com.example.app-2.0.0-beta.apk
└── com.another.app/
    └── com.another.app-1.5.0/
        └── com.another.app-1.5.0.apk
```

Both Gofile and Buzzheavier maintain identical folder structures for consistency.

**Pixeldrain**: Uses a flat structure - files are uploaded directly to your account root without folder organization.

### File Processing

1. **Parse APK Filename**: Extracts package name and version from filename
   - Expected format: `package-version[-suffix].apk`
   - Versions can be numeric, alphanumeric, or words (e.g., `prologue`)
   - Known trailing suffix tokens like `-release`, `-fix`, `-hotfix`, `-patch` are ignored for version parsing
   - Example: `com.example.myapp-2.0.1-release.apk` → version `2.0.1`; `com.estrada777.inizialization-prologue-release.apk` → version `prologue`
   - Dropped batches are queued; files upload sequentially while logs accumulate

2. **Batch Duplicate Check**: Before uploads begin, scans all queued files for duplicates
   - Shows progress dialog during scanning
   - If duplicates found, displays single decision dialog with all affected files
   - Choose action per file (skip/overwrite/upload_again) or use "Apply to All" buttons
   - Enables unattended multi-file uploads after making all decisions upfront

3. **Parallel Upload to Enabled Hosts**:
   - Creates separate threads for simultaneous uploads
   - Each host operates independently

4. **For Gofile & Buzzheavier**:
   - **Find/Create Parent Folder**: Searches for existing parent folder matching package name
   - **Create Version Folder**: Creates subfolder with full APK name (without .apk)
   - **Upload File**: Uploads APK to version folder with progress tracking
   - **Generate Public Link**: 
     - Gofile: Makes version folder public and retrieves link
     - Buzzheavier: Gets file ID and generates direct link
   - **Update UI**: Link appears immediately when host finishes

5. **For Pixeldrain**:
   - **Upload File**: Uploads APK directly to account root (flat structure)
   - **Generate Public Link**: Creates direct link from file ID
   - **Update UI**: Link appears immediately

6. **Status Updates**:
   - ⟳ orange indicator during upload
   - ✓ green indicator on success
   - ✗ red indicator on failure
   - Completion summary shows status for all enabled hosts

### Smart Caching

The uploader maintains separate local caches for each host:
- **Cache Location**: `folder_structure_cache.json`
- **Cache Format**: Separate entries for `gofile` and `buzzheavier`
- **Cache Duration**: 24 hours per host
- **Benefits**: Lightning-fast folder lookups (no API calls needed)
- **Auto-Refresh**: Automatically rebuilds if stale or missing
- **Backward Compatible**: Auto-migrates old single-host cache format

## 📸 Screenshots

### Main Window (900x800)
```
┌────────────────────────────────────────────────────────────────┐
│ Drop Zone                                                      │
│  📁 Drag & Drop APK Files Here                                │
│  Status: Ready - Drop APK file here                           │
└────────────────────────────────────────────────────────────────┘

┌────────────────────────────────────────────────────────────────┐
│ Public Links                                                   │
│  🟢 Gofile:      [https://gofile.io/d/xxxxx] [Copy][Open][Retry]│
│  🟢 Buzzheavier: [https://buzzheavier.com/yyyyy] [Copy][Open][Retry]│
└────────────────────────────────────────────────────────────────┘

┌──────────────────────────────┬─────────────────────────────────┐
│ Gofile Activity Log          │ Buzzheavier Activity Log        │
│  [09:30:15] Processing...    │  [09:30:15] Processing...       │
│  [09:30:16] Package: com...  │  [09:30:16] Package: com...     │
│  [09:30:17] Uploading (5MB)  │  [09:30:17] Uploading (5MB)     │
│  [09:30:22] Upload complete! │  [09:30:20] Upload complete!    │
│  [09:30:22] Speed: 8.37 Mbps │  [09:30:20] Speed: 80.5 Mbps    │
│  [09:30:23] Public link ready│  [09:30:21] Public link ready   │
└──────────────────────────────┴─────────────────────────────────┘
```

## 💡 Features in Detail

### Multi-Host Redundancy
- Upload to any combination of Gofile, Buzzheavier, and Pixeldrain
- Configure which hosts to use via settings menu (⚙️)
- If one host fails, you still have the others
- Independent retry for each host
- Separate status tracking with colored text indicators

### Parallel Upload Performance
- All enabled hosts upload simultaneously in separate threads
- Links appear immediately as each host finishes
- No waiting for the slowest host
- Typical scenario: Pixeldrain fastest, then Buzzheavier, then Gofile

### Dynamic Host Configuration
- Settings menu accessible via gear icon (⚙️)
- Enable/disable hosts on the fly
- Changes saved automatically to config.json
- UI updates dynamically to show only enabled hosts
- Must have at least one host enabled

### Copy All Links
- One-click button in the Public Links header
- Copies all enabled host links to clipboard
- Formats links one per line for easy sharing
- Uses base URLs (e.g., https://gofile.io) if no links generated yet
- Perfect for quickly sharing all mirror links

### Upload Speed Display
Shows real-time upload performance for each host:
- **MB/s**: Megabytes per second (file transfer rate)
- **Mbps**: Megabits per second (network speed)
- Helps you compare host performance
- Buzzheavier typically faster (80+ Mbps) due to US servers

### Batch Duplicate Detection
- Scans all queued files before uploads begin
- Progress dialog shows "Scanning file X/Y" with file names
- Single decision dialog for all duplicates found across all hosts
- Three "Apply to All" buttons: Skip All, Overwrite All, Upload All Again
- Per-file dropdowns for individual control
- Enables unattended multi-file uploads - decide once for the entire batch
- Incremental scanning: new files added later are scanned separately

### Individual Retry Functionality
- Retry button for each host independently
- Remembers last uploaded file info
- Clears entry and resets status to ⏳
- Uploads only to the failed host

### Status Indicators
Visual colored text indicators for each host:
- **⟳ (orange)**: Upload in progress
- **✓ (green)**: Upload successful
- **✗ (red)**: Upload failed
- Updates in real-time during upload

### Color-Coded Logs
Each host has its own log with color coding:
- **Green**: Success messages
- **Red**: Error messages
- **Black**: Info messages
- **Orange**: Warning messages

### Browser Integration
Click the "Open" button for either host to open the public link directly in your default browser.

### Thread Safety
All uploads run in background threads so the GUI stays responsive during file transfers. UI updates are safely queued.

## ⚠️ Error Handling

The application handles various error scenarios:

- **Invalid filename format**: Shows error if APK doesn't match expected naming pattern
- **Non-APK files**: Rejects files that aren't .apk files
- **Connection errors**: Shows error if can't connect to Gofile
- **Upload failures**: Logs detailed error messages
- **Permission errors**: Reports if folder operations fail
- **Stale cache**: Automatically recreates folders and retries
- **Missing config**: Shows clear error message with instructions

##  Example Workflow

1. You have: `com.whatsapp.messenger-2.23.20.76-arm64-v8a.apk`

2. Configure hosts via settings menu (e.g., enable all three)

3. Drag it onto the window

4. The app uploads simultaneously to all enabled hosts:
   - **Gofile & Buzzheavier**: Parse package/version, create folder structure, upload to version folder
   - **Pixeldrain**: Upload directly to account root (flat structure)

5. Results appear as each completes:
   - Pixeldrain (fastest, ~2s @ 100 Mbps): `https://pixeldrain.com/u/AbCd1234`
   - Buzzheavier (~3s @ 80 Mbps): `https://buzzheavier.com/xyz123`
   - Gofile (~5s @ 40 Mbps): `https://gofile.io/d/AbCd12`

6. Status shows: `Gofile: ✓ | Buzzheavier: ✓ | Pixeldrain: ✓`

7. Three links ready to share with maximum redundancy!

## 🐛 Troubleshooting

### "tkinterdnd2 is not installed" error
Install the package:
```powershell
pip install tkinterdnd2
```

### "Failed to connect to Gofile", "Failed to connect to Buzzheavier", or "Failed to connect to Pixeldrain"
Check your `config.json` file and ensure all API credentials are valid for the hosts you want to use. The app will work if at least one host connects successfully.

### "Could not parse APK filename"
Ensure your APK follows the naming convention:
- Format: `package-version[-suffix].apk`
- Package should have at least 2 dots (e.g., `com.company.app`)
- Version can be numeric or text (e.g., `1.2.3`, `ch1`, `prologue`)

### Drag and drop not working
- Make sure you're dragging directly onto the "Drop Zone" area
- Try dragging from File Explorer (not from within ZIP files)
- On Windows, ensure the application has proper permissions

### Cache issues
If the folder structure seems outdated:
- Delete `folder_structure_cache.json`
- Restart the application to rebuild the cache

## ⚡ Performance

- **Initialization**: All enabled hosts connect in parallel (~2-3 seconds total)
- **Cold start** (no cache): ~5-10 seconds for Gofile/Buzzheavier to scan and build folder structure (parallel)
- **Warm start** (with cache): <1 second to load folder structures
- **Upload speed**: 
  - Pixeldrain: 100+ Mbps (varies by location)
  - Buzzheavier: 80+ Mbps (US servers)
  - Gofile: 40+ Mbps (varies by location)
- **Parallel benefit**: Total upload time = slowest enabled host (not sum of all)
- **GUI responsiveness**: All uploads in background threads, GUI never freezes

## 💡 Tips & Best Practices

- Keep the window open and ready - it uses minimal resources
- Minimize to the system tray to keep it out of the way while working
- Configure which hosts to use based on your needs (more hosts = more redundancy)
- Use **Copy All Links** button to quickly grab all mirror links for sharing
- Gofile/Buzzheavier caches last 24 hours for fast folder lookups
- You can drop multiple files one at a time (wait for each to complete)
- The dynamic activity logs show detailed progress for enabled hosts only
- Compare upload speeds between hosts to diagnose connection issues
- If one host fails, you still have the others - use the Retry button to try again
- Pixeldrain typically finishes first, followed by Buzzheavier, then Gofile
- All links provide the same file - choose whichever host works best for your recipients
- The status indicators (✓/✗/⟳) make it easy to see what's happening at a glance
- Settings menu (⚙️) allows you to quickly enable/disable hosts without editing config.json

## 💻 Technical Requirements

- **Python**: 3.6 or higher
- **Operating System**: Windows (PowerShell)
- **Internet**: Active connection required
- **File Host Accounts** (at least one required): 
  - Gofile account (Premium recommended for best performance)
  - Buzzheavier account (Free tier works well)
  - Pixeldrain account (Free tier works well)
- **Dependencies**: 
  - `requests` - HTTP library for API calls
  - `tkinterdnd2` - Drag and drop support for Tkinter

## 📄 License

MIT License - Feel free to use, modify, and distribute!

## 🤝 Contributing

Found a bug or have a feature request? Please open an issue on GitHub!

## ⭐ Support

If you find this tool helpful, please give it a star on GitHub!

---

**Made with ❤️ for the Android development community**
