# Dual-Host Drag & Drop Uploader

A powerful GUI application that lets you drag and drop APK files to automatically upload them to **both Gofile and Buzzheavier** simultaneously with intelligent folder organization. Perfect for developers and testers who need reliable file hosting with redundancy.

![Version](https://img.shields.io/badge/version-2.0-blue)
![Python](https://img.shields.io/badge/python-3.6+-green)
![License](https://img.shields.io/badge/license-MIT-blue)

## ✨ Features

- 🚀 **Dual-Host Uploads**: Automatically uploads to both Gofile and Buzzheavier in parallel
- 📁 **Drag & Drop Interface**: Just drag APK files onto the window
- 🎯 **Mini Mode**: Compact always-on-top window (200x320) for keeping on your desktop
- 🤖 **Intelligent Folder Management**: Automatically finds or creates the appropriate folder structure on both hosts
- 🔗 **Dual Public Links**: Get public links from both hosts immediately as they finish
- 📊 **Dual Activity Logs**: Separate real-time logs for each host
- ⚡ **Status Indicators**: Visual emoji indicators (🟢 success, 🔴 failure, ⏳ uploading) for each host
- 🔄 **Individual Retry**: Retry failed uploads on either host independently
- 🚀 **Upload Speed Display**: Shows transfer speed in MB/s and Mbps for each host
- 💾 **Smart Caching**: Remembers folder structure for both hosts for lightning-fast uploads
- 🌍 **US Server Optimization**: Buzzheavier uses Eastern US servers by default for faster speeds

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
  "buzzheavier_account_id": "your_buzzheavier_account_id"
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

**Security Note**: Keep your `config.json` private! It contains your API credentials. Never commit it to public repositories.

## 🚀 Usage

### Running the Script

Simply run the script:
```powershell
python drag_drop_uploader.py
```

### Normal Mode (Full Window - 900x600)

A window will appear:
1. Wait for both hosts to initialize (shows connection status for Gofile and Buzzheavier)
2. Drag and drop an APK file onto the drop zone
3. Watch both activity logs simultaneously as each host:
   - Parses the APK filename
   - Finds or creates the parent folder
   - Creates the version folder
   - Uploads the file (shows speed in MB/s and Mbps)
   - Makes the folder public (Gofile) or generates direct link (Buzzheavier)
   - Displays the public link
4. Both public links appear in separate text boxes as each host completes
5. Status indicators show: ⏳ (uploading), 🟢 (success), or 🔴 (failure) for each host
6. Use "Copy" to copy a link, "Open" to open in browser, or "Retry" to retry a failed upload

### Mini Mode (Always on Top - 200x320)

1. Check the **"Mini Mode (Always on Top)"** checkbox
2. Window shrinks to a compact stacked layout
3. Window stays on top of all other windows
4. Shows:
   - Drop zone with folder icon
   - Status indicator
   - Both host links stacked vertically
   - Copy/Open/Retry buttons for each host
   - Normal checkbox (to return to full mode)
5. Perfect for keeping on your desktop while working

**Toggle back**: Uncheck the "Normal" checkbox in mini mode

## 🔧 How It Works

### Folder Organization

The uploader automatically organizes your APKs into a hierarchical structure on **both hosts**:

```
Gofile Root/                                    Buzzheavier Root/
├── com.example.app/                            ├── com.example.app/
│   ├── com.example.app-1.0.0-release/          │   ├── com.example.app-1.0.0-release/
│   │   └── com.example.app-1.0.0-release.apk   │   │   └── com.example.app-1.0.0-release.apk
│   └── com.example.app-2.0.0-beta/             │   └── com.example.app-2.0.0-beta/
│       └── com.example.app-2.0.0-beta.apk      │       └── com.example.app-2.0.0-beta.apk
└── com.another.app/                            └── com.another.app/
    └── com.another.app-1.5.0/                      └── com.another.app-1.5.0/
        └── com.another.app-1.5.0.apk                   └── com.another.app-1.5.0.apk
```

Both hosts maintain identical folder structures for consistency.

### File Processing

1. **Parse APK Filename**: Extracts package name and version from filename
   - Expected format: `com.company.app-1.2.3-suffix.apk`
   - Example: `com.example.myapp-2.0.1-release.apk`

2. **Parallel Upload to Both Hosts**:
   - Creates two threads for simultaneous uploads
   - Each host operates independently

3. **For Each Host (Gofile & Buzzheavier)**:
   - **Find/Create Parent Folder**: Searches for existing parent folder matching package name
   - **Create Version Folder**: Creates subfolder with full APK name (without .apk)
   - **Upload File**: Uploads APK to version folder with progress tracking
   - **Generate Public Link**: 
     - Gofile: Makes version folder public and retrieves link
     - Buzzheavier: Gets file ID and generates direct link
   - **Update UI**: Link appears immediately when host finishes (doesn't wait for the other)

4. **Status Updates**:
   - ⏳ emoji during upload
   - 🟢 emoji on success
   - 🔴 emoji on failure
   - Completion summary: "Gofile: 🟢 | Buzzheavier: 🟢"

### Smart Caching

The uploader maintains separate local caches for each host:
- **Cache Location**: `folder_structure_cache.json`
- **Cache Format**: Separate entries for `gofile` and `buzzheavier`
- **Cache Duration**: 24 hours per host
- **Benefits**: Lightning-fast folder lookups (no API calls needed)
- **Auto-Refresh**: Automatically rebuilds if stale or missing
- **Backward Compatible**: Auto-migrates old single-host cache format

## 📸 Screenshots

### Normal Mode (900x600)
```
┌────────────────────────────────────────────────────────────────┐
│ Drop Zone                                                      │
│  📁 Drag & Drop APK Files Here                                │
│  Status: Ready - Drop APK file here                           │
│  ☑ Mini Mode (Always on Top)                                 │
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

### Mini Mode (200x320)
```
┌─────────────────────┐
│                     │
│   Drop APK Here     │
│        📁           │
│      Ready          │
│                     │
│ 🟢 Gofile:         │
│ [link] [C][O][R]   │
│                     │
│ 🟢 Buzzheavier:    │
│ [link] [C][O][R]   │
│                     │
│      [Normal]       │
└─────────────────────┘
```
(Always stays on top of other windows)

## 💡 Features in Detail

### Dual-Host Redundancy
- Uploads to both Gofile and Buzzheavier simultaneously
- If one host fails, you still have the other
- Independent retry for each host
- Separate status tracking with emoji indicators

### Parallel Upload Performance
- Both uploads run simultaneously in separate threads
- Links appear immediately as each host finishes
- No waiting for the slowest host
- Typical scenario: Buzzheavier finishes first (US servers), then Gofile

### Mini Mode
- Compact 200x320 window with stacked layout
- Always stays on top of other windows
- Perfect for keeping accessible while working
- Quick access to both links and all controls
- Easy toggle back to normal mode

### Upload Speed Display
Shows real-time upload performance for each host:
- **MB/s**: Megabytes per second (file transfer rate)
- **Mbps**: Megabits per second (network speed)
- Helps you compare host performance
- Buzzheavier typically faster (80+ Mbps) due to US servers

### Individual Retry Functionality
- Retry button for each host independently
- Remembers last uploaded file info
- Clears entry and resets status to ⏳
- Uploads only to the failed host

### Status Indicators
Visual emoji indicators for each host:
- **⏳**: Upload in progress
- **🟢**: Upload successful
- **🔴**: Upload failed
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

2. Drag it onto the window

3. The app (simultaneously on both hosts):
   - Parses: package = `com.whatsapp.messenger`, version = `2.23.20.76`
   - Finds/creates parent folder: `com.whatsapp.messenger`
   - Creates version folder: `com.whatsapp.messenger-2.23.20.76-arm64-v8a`
   - Uploads the APK in parallel
   - Generates public links

4. Results appear as each completes:
   - Buzzheavier (faster, ~3s @ 80 Mbps): `https://buzzheavier.com/xyz123`
   - Gofile (~5s @ 40 Mbps): `https://gofile.io/d/AbCd12`

5. Status shows: `Gofile: 🟢 | Buzzheavier: 🟢`

6. Two links ready to share with redundancy!

## 🐛 Troubleshooting

### "tkinterdnd2 is not installed" error
Install the package:
```powershell
pip install tkinterdnd2
```

### "Failed to connect to Gofile" or "Failed to connect to Buzzheavier"
Check your `config.json` file and ensure all API credentials are valid. The app will still work if at least one host connects successfully.

### "Could not parse APK filename"
Ensure your APK follows the naming convention:
- Format: `package-version-suffix.apk`
- Package should have at least 2 dots (e.g., `com.company.app`)
- Version should start with a number

### Drag and drop not working
- Make sure you're dragging directly onto the "Drop Zone" area
- Try dragging from File Explorer (not from within ZIP files)
- On Windows, ensure the application has proper permissions

### Cache issues
If the folder structure seems outdated:
- Delete `folder_structure_cache.json`
- Restart the application to rebuild the cache

## ⚡ Performance

- **Initialization**: Both hosts connect in parallel (~2-3 seconds total)
- **Cold start** (no cache): ~5-10 seconds per host to scan and build folder structure (parallel)
- **Warm start** (with cache): <1 second to load both folder structures
- **Upload speed**: 
  - Buzzheavier: 80+ Mbps (US servers)
  - Gofile: 40+ Mbps (varies by location)
- **Parallel benefit**: Total upload time = slowest host (not sum of both)
- **GUI responsiveness**: All uploads in background threads, GUI never freezes

## 💡 Tips & Best Practices

- Keep the window open and ready - it uses minimal resources
- Use **Mini Mode** to keep it accessible on your desktop while working
- Both host caches last 24 hours, so subsequent uploads are very fast
- You can drop multiple files one at a time (wait for each to complete)
- The dual activity logs show detailed progress including upload speeds
- Compare upload speeds between hosts to diagnose connection issues
- If one host fails, you still have the other - use the Retry button to try again
- Buzzheavier typically finishes first due to US server optimization
- Both links provide the same file - choose whichever host works best for your recipients
- The status emoji indicators (🟢/🔴/⏳) make it easy to see what's happening at a glance

## 💻 Technical Requirements

- **Python**: 3.6 or higher
- **Operating System**: Windows (PowerShell)
- **Internet**: Active connection required
- **File Host Accounts**: 
  - Gofile account (Premium recommended for best performance)
  - Buzzheavier account (Free tier works well)
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
