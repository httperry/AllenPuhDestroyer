# AllenPuhDestroyer

A zero-configuration tool that downloads all your Allen study materials
(PDFs and video lectures) into a neatly organized folder structure.
Works with any Allen account that is logged into Chrome.


> [!WARNING]
> **Use at your own risk.** This tool interacts with Allen's platform in ways that may violate their Terms of Service. The creator is not responsible for any consequences including but not limited to account suspension, bans, or loss of access. By using this tool, you accept full responsibility for any outcome.


## How It Works

1. The tool copies your existing Chrome session to authenticate with the
   Allen API. No tokens to manage, no passwords to enter.

2. The tool bypasses the new Allen WAF (Web Application Firewall) checks by extracting validation metadata dynamically from the hydration payload.
   
3. A headless browser captures your secure `Cookie` session tokens, handing them off to a lightning-fast native `urllib` API fetcher to traverse your batches, subjects, and chapters without triggering rate limits.

4. PDFs are downloaded directly. Videos are downloaded from the Akamai CDN via `ffmpeg`, which is armed with your active session cookies to bypass HTTP 403 Forbidden checks and stream the encrypted HLS chunks directly into a single `.mp4` file.

5. A session file tracks progress. If the download is interrupted, just
   run the tool again and it picks up exactly where it left off.


## Features

- Interactive CLI with Rich TUI -- select subjects, chapters, and
  content types from a multi-select menu
- Auto-detects your batch, course, and subject IDs from the API
- Downloads PDFs and video lectures (concept videos and live lectures)
- Organizes files into Subject / Chapter / Category folders
- Serial-numbered video files (e.g., #01 - Introduction.mp4)
- Resume support -- interrupted downloads continue from the last item
- Portable ffmpeg auto-download -- no manual installation needed
- Folder picker for choosing your output directory (supports external drives)


## Requirements

- Python 3.10 or later
- Google Chrome, logged into your Allen account
- Windows (uses Chrome profile paths specific to Windows)


## Setup

### Option 1: Prebuilt Executable (Recommended)

Starting from **v1.1.0**, pre-compiled, standalone executables are available on the [GitHub Releases](https://github.com/httperry/AllenPuhDestroyer/releases) page. 
You do not need to install Python, Node.js, or manage any packages. Just download `AllenPuhDestroyer.exe` and run it!

### Option 2: Running from Source

```
git clone https://github.com/httperry/AllenPuhDestroyer.git
cd AllenPuhDestroyer
pip install -r requirements.txt
playwright install chromium
```

## Usage

**If using the executable:**
Simply double-click `AllenPuhDestroyer.exe`.

**If running from source:**
```
python app.py
```

Close all Chrome/Brave/Edge windows before running. The tool will guide you through:


1. Content type selection (PDFs, concept videos, live lectures)
2. Output directory (default or browse for an external drive)
3. Subject and chapter selection with select-all / toggle controls
4. Download with progress logging and failure reports

If the download is interrupted (Ctrl+C, network loss, power cut), just
run the same command again. The tool detects the previous session and
offers to resume.


## Output Structure

```
Allen_Materials/
  Chemistry/
    Coordination Compounds/
      Study Modules/
        Coordination Compounds Theory.pdf
      Concept Videos/
        #01 - L01_Coordination Compounds.mp4
        #02 - L02_Coordination Compounds.mp4
      Live Lectures/
        #01 - Live Session 01.mp4
  Physics/
    Kinematics/
      ...
```


## Troubleshooting

If you get 401 Unauthorized errors, delete the `chrome_profile/` folder
and run the tool again. This forces a fresh copy of your Chrome session.

If Chrome is not found, edit the `CHROME_EXE` constant at the top of
`app.py` to match your Chrome installation path.

If ffmpeg auto-download fails (e.g., firewall), install it manually with
`winget install --id Gyan.FFmpeg` and make sure it is in your PATH.


## License

MIT
