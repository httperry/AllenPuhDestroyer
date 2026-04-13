# AllenPuhDestroyer

A fully automated, zero-configuration bulk PDF downloader for the Allen digital study platform. Built for students who want their paid study materials organized and available offline, permanently.

---

## How It Works

The Allen web app is a server-driven UI. Every page you navigate to fires a single POST request to their internal API endpoint (`/api/v1/pages/getPage`), which returns a structured JSON payload describing the entire page — including signed CloudFront URLs for every PDF on that page.

This script uses Playwright to launch a headless instance of your real Chrome browser (with your existing login session intact), programmatically navigates to every subject and chapter page in your enrolled course, and intercepts those API responses as they arrive. It then recursively walks the JSON tree to find every `OPEN_PDF` action, extracts the content UUID, and downloads directly from CloudFront.

The CloudFront distribution does not enforce its signed URL parameters. A bare URL of the form `https://d2b4i7hu6z450i.cloudfront.net/{content_id}/original.pdf` is sufficient to download any PDF you have access to through the API.

---

## Output Structure

All files are saved to an `Allen_Materials/` directory with the following hierarchy:

```
Allen_Materials/
    Chemistry/
        Coordination Compounds/
            Study Modules/
                Coordination Compounds.pdf
            Class Notes/
                Coordination Compounds - L4-01.pdf
                Coordination Compounds - L4-02.pdf
            Additional Materials/
                RACE & Solutions/
                    Race - Coordination Compounds.pdf
                    Solutions RACE - Coordination Compounds.pdf
                Exercises & Solutions/
                    Exercise - Coordination Compounds.pdf
                    Solutions Exercise - Coordination Compounds.pdf
        The D And F Block Elements/
            ...
    Physics/
        ...
    Maths/
        ...
```

Folder names and file names are taken directly from Allen's API metadata — the same names shown in the UI — so nothing is guessed or generated.

---

## Requirements

- Python 3.10 or later
- Google Chrome installed at the default path (`C:\Program Files\Google\Chrome\Application\chrome.exe`)
- An active Allen account with a valid login session in Chrome
- Playwright with the Chromium driver

Install dependencies:

```bash
pip install -r requirements.txt
playwright install chromium
```

---

## Usage

1. **Close all Chrome windows.** Chrome places a file lock on its profile directory while running. The script copies your profile before launch, so Chrome must be fully closed first.

2. **Run the script:**

```bash
python app.py
```

3. The script will copy your Chrome session data to a local `chrome_profile/` directory (skipping large cache folders, so this takes only a few seconds), launch a headless Chrome instance, and begin scraping.

4. Watch the terminal for live progress. Downloaded files appear in `Allen_Materials/` as they complete. Already-downloaded files are skipped automatically, so the script is safe to re-run if interrupted.

---

## Configuration

Open `app.py` and edit the constants near the top if needed:

| Constant | Description |
|---|---|
| `CHROME_EXE` | Path to your Chrome executable |
| `REAL_PROFILE_DEFAULT` | Path to your Chrome `Default` profile folder |
| `SUBJECTS` | Dictionary of `subject_id -> subject name` for your enrolled course |
| `BATCH_LIST` | Your batch IDs (found in any Allen page URL) |
| `COURSE_ID` | Your course ID (found in any Allen page URL) |

These values are pre-populated from a JEE Main + Advanced enrollment. If you are on a different course (NEET, etc.), update the `SUBJECTS` dictionary and the batch/course IDs from your browser's URL bar when logged into Allen.

---

## Notes

- This script only downloads content that your enrolled account has legitimate access to. It does not bypass any paywall — it uses your own authenticated session to retrieve exactly what the Allen app would show you.
- The `chrome_profile/` folder contains a copy of your browser session. It is excluded from version control via `.gitignore`. Do not share it.
- Bearer tokens embedded in API responses expire periodically. If downloads start failing with HTTP 401 errors, delete the `chrome_profile/` folder and re-run to pick up a fresh session.

---

## License

MIT License. See [LICENSE](LICENSE) for details.
