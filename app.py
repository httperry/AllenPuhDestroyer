"""
AllenPuhDestroyer — Automated Allen PDF Bulk Downloader
=========================================================
Launches a headless Chrome instance using your existing Chrome
login session, auto-detects your batch/course/subject configuration
directly from the Allen API, then downloads every PDF you have
access to into a neat, categorized folder structure.

No hardcoded IDs. No tokens to manage. Works for any Allen account.
"""

import os
import re
import json
import time
import shutil
import urllib.request
import urllib.error
import urllib.parse
from playwright.sync_api import sync_playwright, Response

# ─── PATHS (adjust only if Chrome is installed in a non-default location) ─────

CHROME_EXE            = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
REAL_PROFILE_DEFAULT  = os.path.expanduser(r"~\AppData\Local\Google\Chrome\User Data\Default")
LOCAL_PROFILE_DIR     = os.path.join(os.getcwd(), "chrome_profile")
LOCAL_PROFILE_DEFAULT = os.path.join(LOCAL_PROFILE_DIR, "Default")

ALLEN_BASE      = "https://allen.in"
CLOUDFRONT_BASE = "https://d2b4i7hu6z450i.cloudfront.net"
DOWNLOAD_DIR    = "Allen_Materials"

SKIP_DIRS = {"Cache", "Code Cache", "GPUCache", "DawnCache", "ShaderCache",
             "Service Worker", "CacheStorage", "blob_storage"}

# ─── helpers ──────────────────────────────────────────────────────────────────

def safe_name(s: str) -> str:
    s = re.sub(r'[<>:"/\\|?*]', '', s)
    return re.sub(r'\s+', ' ', s).strip() or 'Untitled'

def card_type_to_folder(card_type: str) -> list:
    """
    'Additional Materials - RACE & Solutions - Content' ->
    ['Additional Materials', 'RACE & Solutions']
    """
    ct = re.sub(r'\s*-\s*Content\s*$', '', card_type, flags=re.IGNORECASE).strip()
    return [safe_name(p) for p in ct.split(' - ') if p.strip()] or ['Extra']

# ─── auto-configuration detection ────────────────────────────────────────────

def detect_config(data: dict) -> dict:
    """
    Recursively scan any getPage API response and extract:
      - batch_list      : your enrolled batch IDs (comma-separated)
      - course_id       : your course ID
      - taxonomy_id     : your taxonomy ID
      - subjects        : {subject_id: subject_name} for all subjects in your course

    These values are embedded throughout the JSON as query parameters
    inside navigation action data objects.
    """
    cfg = {
        'batch_list':  '',
        'course_id':   '',
        'taxonomy_id': '',
        'subjects':    {},
    }

    def walk(obj):
        if isinstance(obj, dict):
            # Grab IDs from any action data that contains them
            batch  = obj.get('selected_batch_list') or obj.get('batch_id') or ''
            course = obj.get('selected_course_id') or ''
            tax    = obj.get('taxonomy_id') or ''

            if batch  and not cfg['batch_list']:  cfg['batch_list']  = batch
            if course and not cfg['course_id']:   cfg['course_id']   = course
            if tax    and not cfg['taxonomy_id']: cfg['taxonomy_id'] = tax

            # Grab subject entries from any card that has both subject_id and subject_name
            sid   = str(obj.get('subject_id') or '')
            sname = (obj.get('subject_name') or '').strip()
            if sid and sname and sid not in cfg['subjects']:
                cfg['subjects'][sid] = sname

            for v in obj.values():
                walk(v)

        elif isinstance(obj, list):
            for v in obj:
                walk(v)

    walk(data)
    return cfg

# ─── recursive PDF collector ──────────────────────────────────────────────────

def collect_pdfs(obj, results=None):
    """
    Walk any JSON structure and collect every item with an OPEN_PDF action.
    Returns a list of dicts: {title, content_id, category}
    """
    if results is None:
        results = []
    if isinstance(obj, list):
        for item in obj:
            collect_pdfs(item, results)
    elif isinstance(obj, dict):
        action = obj.get('content_action') or {}
        if isinstance(action, dict) and action.get('type') == 'OPEN_PDF':
            ad  = action.get('data') or {}
            uri = ad.get('uri', '')
            cid = ad.get('content_id', '')
            if not cid:
                m = re.search(
                    r'/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})/original',
                    uri
                )
                cid = m.group(1) if m else ''
            title    = safe_name(obj.get('content_title') or ad.get('title') or 'Document')
            tracking = (action.get('tracking_params') or {}).get('current') or {}
            ct       = tracking.get('card_type', '')
            cat      = card_type_to_folder(ct) if ct else ['Misc']
            if cid:
                results.append({'title': title, 'content_id': cid, 'category': cat})
            return
        for v in obj.values():
            collect_pdfs(v, results)
    return results

def get_topics_from_data(data: dict) -> list:
    """Extract (topic_id, topic_name) pairs from a subject page response."""
    topics, seen = [], set()
    def walk(obj):
        if isinstance(obj, dict):
            tid   = str(obj.get('topic_id') or '')
            tname = (obj.get('topic_name') or obj.get('card_name') or '').strip()
            if tid and tname and tid not in seen:
                seen.add(tid)
                topics.append((tid, tname))
            for v in obj.values():
                walk(v)
        elif isinstance(obj, list):
            for v in obj:
                walk(v)
    walk(data)
    return topics

# ─── download ─────────────────────────────────────────────────────────────────

def download_pdf(content_id: str, folder: str, filename: str):
    os.makedirs(folder, exist_ok=True)
    filepath = os.path.join(folder, f"{filename}.pdf")
    if os.path.exists(filepath):
        print(f"        [SKIP]  {filename}.pdf")
        return
    url = f"{CLOUDFRONT_BASE}/{content_id}/original.pdf"
    print(f"        [DL]    {filename}.pdf")
    try:
        req = urllib.request.Request(url, headers={"Referer": "https://allen.in/"})
        with urllib.request.urlopen(req, timeout=60) as r, open(filepath, "wb") as f:
            f.write(r.read())
        size_kb = os.path.getsize(filepath) // 1024
        print(f"        [OK]    {size_kb} KB")
    except urllib.error.HTTPError as e:
        print(f"        [HTTP {e.code}] Could not download {filename}")
    except Exception as e:
        print(f"        [ERR]   {e}")

# ─── profile sync ─────────────────────────────────────────────────────────────

def sync_profile():
    if os.path.exists(LOCAL_PROFILE_DEFAULT):
        print("[Profile] Using existing local profile copy.\n")
        return
    print("[Profile] Copying Chrome session data (skipping cache)...")
    os.makedirs(LOCAL_PROFILE_DEFAULT, exist_ok=True)
    copied = 0
    for item in os.listdir(REAL_PROFILE_DEFAULT):
        if item in SKIP_DIRS:
            continue
        src = os.path.join(REAL_PROFILE_DEFAULT, item)
        dst = os.path.join(LOCAL_PROFILE_DEFAULT, item)
        try:
            if os.path.isdir(src):
                if os.path.exists(dst):
                    shutil.rmtree(dst)
                shutil.copytree(src, dst)
            else:
                shutil.copy2(src, dst)
            copied += 1
        except Exception:
            pass
    print(f"[Profile] Done ({copied} items copied).\n")

# ─── browser page fetch ───────────────────────────────────────────────────────

def fetch_page_via_browser(page, url: str) -> dict:
    """Navigate to a URL and capture the first getPage API response."""
    result = {}

    def on_response(response: Response):
        if "/api/v1/pages/getPage" in response.url and response.status == 200:
            if 'data' not in result:
                try:
                    result['data'] = response.json()
                except Exception:
                    pass

    page.on("response", on_response)
    page.goto(url, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(2500)
    page.remove_listener("response", on_response)
    return result.get('data', {})

# ─── main ─────────────────────────────────────────────────────────────────────

def main():
    print("=" * 65)
    print("  AllenPuhDestroyer — PDF Bulk Downloader")
    print("=" * 65)
    print(f"  Output: {os.path.abspath(DOWNLOAD_DIR)}\n")

    print("Close ALL Chrome windows before continuing.")
    input("Press ENTER when Chrome is fully closed...")

    sync_profile()

    with sync_playwright() as p:
        print("[Launch] Starting headless Chrome with your session...\n")
        context = p.chromium.launch_persistent_context(
            user_data_dir=LOCAL_PROFILE_DIR,
            executable_path=CHROME_EXE,
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--disable-restore-session-state",
                "--no-first-run",
                "--no-default-browser-check",
            ],
        )
        page = context.pages[0] if context.pages else context.new_page()

        # ── Warmup: dismiss promo/splash page ─────────────────────────────────
        print("[Warmup] Loading home page to dismiss promo splash...")
        page.goto(f"{ALLEN_BASE}/", wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(3000)
        page.reload(wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(2000)
        print("[Warmup] Done.\n")

        # ── Auto-detect: fetch study/library page to get all config IDs ───────
        print("[Detect] Reading your account configuration...")
        library_data = fetch_page_via_browser(page, f"{ALLEN_BASE}/library-web")
        cfg = detect_config(library_data)

        # Fallback: also check home page data if library page was sparse
        if not cfg['batch_list'] or not cfg['subjects']:
            home_data = fetch_page_via_browser(page, f"{ALLEN_BASE}/home")
            home_cfg  = detect_config(home_data)
            if not cfg['batch_list']:  cfg['batch_list']  = home_cfg['batch_list']
            if not cfg['course_id']:   cfg['course_id']   = home_cfg['course_id']
            if not cfg['taxonomy_id']: cfg['taxonomy_id'] = home_cfg['taxonomy_id']
            cfg['subjects'].update(home_cfg['subjects'])

        if not cfg['batch_list'] or not cfg['course_id']:
            print("[ERROR] Could not detect your account configuration.")
            print("        Make sure you are logged into Allen in Chrome and try again.")
            context.close()
            return

        print(f"[Detect] Course ID   : {cfg['course_id']}")
        print(f"[Detect] Batch list  : {cfg['batch_list'][:40]}...")
        print(f"[Detect] Subjects    : {cfg['subjects']}\n")

        # ── Scrape each subject ────────────────────────────────────────────────
        total = 0

        for subject_id, subject_name in cfg['subjects'].items():
            print(f"\n{'─'*65}")
            print(f"  SUBJECT: {subject_name}  (id={subject_id})")
            print(f"{'─'*65}")

            qs = urllib.parse.urlencode({
                "batch_id":            cfg['batch_list'],
                "selected_batch_list": cfg['batch_list'],
                "selected_course_id":  cfg['course_id'],
                "stream":              "STREAM_JEE_MAIN_ADVANCED",
                "subject_id":          subject_id,
                "taxonomy_id":         cfg['taxonomy_id'],
            })
            subject_url  = f"{ALLEN_BASE}/subject-details?{qs}"
            subject_data = fetch_page_via_browser(page, subject_url)

            if not subject_data:
                print("  [WARN] No response — skipping this subject.")
                continue

            topics = get_topics_from_data(subject_data)
            print(f"  {len(topics)} chapters found.\n")

            for topic_id, topic_name in topics:
                print(f"  Chapter: {topic_name}")
                qs2 = urllib.parse.urlencode({
                    "batch_id":            cfg['batch_list'],
                    "selected_batch_list": cfg['batch_list'],
                    "selected_course_id":  cfg['course_id'],
                    "stream":              "STREAM_JEE_MAIN_ADVANCED",
                    "subject_id":          subject_id,
                    "taxonomy_id":         cfg['taxonomy_id'],
                    "topic_id":            topic_id,
                })
                topic_url  = f"{ALLEN_BASE}/topic-details?{qs2}"
                topic_data = fetch_page_via_browser(page, topic_url)

                if not topic_data:
                    print("      [WARN] No data received.")
                    time.sleep(1)
                    continue

                pdfs = collect_pdfs(topic_data)
                if not pdfs:
                    print("      (no PDFs in this chapter)")
                else:
                    chapter_dir = os.path.join(DOWNLOAD_DIR, subject_name, safe_name(topic_name))
                    for pdf in pdfs:
                        folder = os.path.join(chapter_dir, *pdf['category'])
                        print(f"      [{' > '.join(pdf['category'])}]  {pdf['title']}")
                        download_pdf(pdf['content_id'], folder, pdf['title'])
                        total += 1

                time.sleep(0.5)

        context.close()

    print(f"\n{'='*65}")
    print(f"  Done.  Total PDFs downloaded: {total}")
    print(f"  Saved to: {os.path.abspath(DOWNLOAD_DIR)}")
    print(f"{'='*65}\n")

if __name__ == "__main__":
    main()
