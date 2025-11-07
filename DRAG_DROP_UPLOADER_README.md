# Gofile Drag & Drop Uploader

A simple, elegant GUI application that lets you drag and drop APK files to automatically upload them to your Gofile account with intelligent folder organization. Perfect for developers and testers who frequently share APK builds.

![Version](https://img.shields.io/badge/version-1.0-blue)
![Python](https://img.shields.io/badge/python-3.6+-green)
![License](https://img.shields.io/badge/license-MIT-blue)

## ✨ Features

- 📁 **Drag & Drop Interface**: Just drag APK files onto the window
- 🎯 **Mini Mode**: Compact always-on-top window (300x180) for keeping on your desktop
- 🤖 **Intelligent Folder Management**: Automatically finds or creates the appropriate folder structure
- 🔗 **Public Link Generation**: Automatically makes the version folder public and provides the link
- 📋 **Clipboard Integration**: Automatically copies the public link to your clipboard
- 🚀 **Upload Speed Display**: Shows transfer speed in MB/s and Mbps
- 📊 **Real-time Activity Log**: See what's happening during the upload process
- 🔄 **Auto-Retry**: Automatically recreates folders if cache is stale
- 💾 **Smart Caching**: Remembers your folder structure for lightning-fast uploads

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
  "account_id": "your_account_id"
}
```

### How to Get Your Credentials:

1. **API Token**: Log into [Gofile.io](https://gofile.io) → Account Settings → API Token
2. **Account ID**: Found in your account settings or profile URL

**Security Note**: Keep your `config.json` private! It contains your API credentials. Never commit it to public repositories.

## 🚀 Usage

### Running the Script

Simply run the script:
```powershell
python drag_drop_uploader.py
```

### Normal Mode (Full Window)

A window will appear:
1. Wait for "Ready - Drop APK file here" status
2. Drag and drop an APK file onto the drop zone
3. Watch the activity log as it:
   - Parses the APK filename
   - Finds or creates the parent folder
   - Creates the version folder
   - Uploads the file (shows speed in MB/s and Mbps)
   - Makes the folder public
   - Retrieves the public link
4. The public link appears in the text box and is automatically copied to clipboard
5. Click "Copy" to copy again or "Open" to open in browser

### Mini Mode (Always on Top)

1. Check the **"Mini Mode (Always on Top)"** checkbox
2. Window shrinks to a compact 300x180 size
3. Window stays on top of all other windows
4. Shows:
   - Drop zone with folder icon
   - Status indicator
   - Copy Link button
   - Normal checkbox (to return to full mode)
5. Perfect for keeping on your desktop while working

**Toggle back**: Uncheck the "Normal" checkbox in mini mode

## 🔧 How It Works

### Folder Organization

The uploader automatically organizes your APKs into a hierarchical structure:

```
Your Gofile Root/
├── com.example.app/                    (Parent Folder - Package Name)
│   ├── com.example.app-1.0.0-release/  (Version Folder)
│   │   └── com.example.app-1.0.0-release.apk
│   └── com.example.app-2.0.0-beta/
│       └── com.example.app-2.0.0-beta.apk
└── com.another.app/
    └── com.another.app-1.5.0/
        └── com.another.app-1.5.0.apk
```

### File Processing

1. **Parse APK Filename**: Extracts package name and version from filename
   - Expected format: `com.company.app-1.2.3-suffix.apk`
   - Example: `com.example.myapp-2.0.1-release.apk`

2. **Find/Create Parent Folder**: 
   - Searches for existing parent folder matching the package name
   - Creates new parent folder if not found
   - Uses cached folder structure for speed

3. **Create Version Folder**:
   - Creates a subfolder with the full APK name (without .apk extension)
   - Example: `com.example.myapp-2.0.1-release`

4. **Upload File**:
   - Uploads the APK to the version folder
   - Shows progress in activity log

5. **Make Public & Get Link**:
   - Sets the **version folder** (not parent) to public
   - Retrieves the public link
   - Copies link to clipboard automatically

### Smart Caching

The uploader maintains a local cache of your folder structure:
- **Cache Location**: `folder_structure_cache.json`
- **Cache Duration**: 24 hours
- **Benefits**: Lightning-fast folder lookups (no API calls needed)
- **Auto-Refresh**: Automatically rebuilds if stale or missing

## 📸 Screenshots

### Normal Mode (700x600)
```
┌──────────────────────────────────────────┐
│ Drop Zone                                │
│  📁 Drag & Drop APK Files Here          │
│  Status: Ready - Drop APK file here     │
│  ☑ Mini Mode (Always on Top)           │
└──────────────────────────────────────────┘

┌──────────────────────────────────────────┐
│ Public Link                              │
│  [https://gofile.io/d/xxxxx] [Copy][Open]│
└──────────────────────────────────────────┘

┌──────────────────────────────────────────┐
│ Activity Log                             │
│  [09:30:15] Processing: app-1.0.apk     │
│  [09:30:16] Package: com.example.app    │
│  [09:30:17] Uploading file (5.23 MB)... │
│  [09:30:22] Upload complete! (5.0s)     │
│  [09:30:22] Upload speed: 1.05 MB/s     │
│  [09:30:22]                (8.37 Mbps)  │
│  [09:30:23] Public link: https://...    │
└──────────────────────────────────────────┘
```

### Mini Mode (300x180)
```
┌──────────────────────┐
│                      │
│   Drop APK Here      │
│         📁           │
│       Ready          │
│                      │
│ [Copy Link] [Normal] │
└──────────────────────┘
```
(Always stays on top of other windows)

## 💡 Features in Detail

### Mini Mode
- Compact 300x180 window
- Always stays on top of other windows
- Perfect for keeping accessible while working
- Quick access to Copy Link button
- Easy toggle back to normal mode

### Upload Speed Display
Shows real-time upload performance:
- **MB/s**: Megabytes per second (file transfer rate)
- **Mbps**: Megabits per second (network speed)
- Helps you understand your connection performance

### Automatic Link Copying
When upload completes successfully, the public link is automatically copied to your clipboard - just paste it wherever you need it!

### Automatic Retry Logic
If folder creation fails (e.g., stale cache), the app automatically:
- Recreates the parent folder
- Retries version folder creation
- Continues with upload if successful

### Color-Coded Logs
- **Green**: Success messages
- **Red**: Error messages
- **Black**: Info messages

### Browser Integration
Click the "Open" button to open the public link directly in your default browser.

### Thread Safety
Uploads run in a background thread so the GUI stays responsive during file transfers.

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

3. The app:
   - Parses: package = `com.whatsapp.messenger`, version = `2.23.20.76`
   - Finds/creates parent folder: `com.whatsapp.messenger`
   - Creates version folder: `com.whatsapp.messenger-2.23.20.76-arm64-v8a`
   - Uploads the APK
   - Makes version folder public
   - Returns link: `https://gofile.io/d/AbCd12`

4. Link is in clipboard, ready to share!

## 🐛 Troubleshooting

### "tkinterdnd2 is not installed" error
Install the package:
```powershell
pip install tkinterdnd2
```

### "Failed to connect to Gofile"
Check your `config.json` file and ensure API token is valid.

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

- **Cold start** (no cache): ~5-10 seconds to scan and build folder structure
- **Warm start** (with cache): <1 second to load folder structure
- **Upload speed**: Depends on file size and internet connection
- **GUI responsiveness**: Uploads in background thread, GUI never freezes

## � Tips & Best Practices

- Keep the window open and ready - it uses minimal resources
- Use **Mini Mode** to keep it accessible on your desktop while working
- The cache lasts 24 hours, so subsequent uploads are very fast
- You can drop multiple files one at a time (wait for each to complete)
- The activity log shows detailed progress including upload speed
- Upload speed helps diagnose connection issues
- If you get errors about missing folders, the app will automatically retry

## 💻 Technical Requirements

- **Python**: 3.6 or higher
- **Operating System**: Windows (PowerShell)
- **Internet**: Active connection required
- **Gofile Account**: Premium account recommended for best performance
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
