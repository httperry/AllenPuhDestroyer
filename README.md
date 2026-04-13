# AllenPuhDestroyer

A zero-configuration tool that downloads all your Allen study materials
(PDFs and video lectures) into a neatly organized folder structure.
Works with any Allen account that is logged into Chrome.


## How It Works

1. The tool copies your existing Chrome session to authenticate with the
   Allen API. No tokens to manage, no passwords to enter.

2. A headless browser navigates the Allen platform, intercepting API
   responses to discover your subjects, chapters, and content.

3. PDFs are downloaded directly from CloudFront. Videos are downloaded
   from the Akamai CDN via ffmpeg, which handles the encrypted HLS
   streams and muxes audio + video into a single MP4 file.

4. A session file tracks progress. If the download is interrupted, just
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

```
git clone https://github.com/httperry/AllenPuhDestroyer.git
cd AllenPuhDestroyer
pip install -r requirements.txt
playwright install chromium
```


## Usage

```
python app.py
```

Close all Chrome windows before running. The tool will guide you through:

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
