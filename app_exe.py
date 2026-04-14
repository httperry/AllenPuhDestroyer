"""
AllenPuhDestroyer — Allen Study Material Bulk Downloader
=========================================================
Arrow keys = navigate   Space = toggle   Enter = confirm   Esc = go back

asyncio note: sync_playwright() and InquirerPy both own an event loop.
They cannot coexist.  Every with sync_playwright() block is closed
before the next InquirerPy prompt is shown.
"""

import os, re, json, sys, time, shutil, subprocess, zipfile, threading
import urllib.request, urllib.error, urllib.parse
import concurrent.futures

# ── Dependency gate ───────────────────────────────────────────────────────────

def _check_deps():
    missing = []
    for pkg in ("rich", "InquirerPy", "playwright"):
        try: __import__(pkg)
        except ImportError: missing.append(pkg)
    if missing:
        print(f"Missing packages: {', '.join(missing)}")
        print(f"  pip install {' '.join(missing)}")
        if "playwright" in missing:
            print("  playwright install chromium")
        sys.exit(1)

_check_deps()

from rich.console import Console
from rich.panel   import Panel
from rich.table   import Table
from rich.text    import Text
from rich.rule    import Rule
from rich.live    import Live
from rich.columns import Columns
from rich.progress import (
    Progress, SpinnerColumn, BarColumn, TextColumn,
    DownloadColumn, TransferSpeedColumn, TimeRemainingColumn,
    MofNCompleteColumn, TaskProgressColumn,
)
from rich import box
from rich.console import Group

from InquirerPy import inquirer
from InquirerPy.utils import get_style
from InquirerPy.base.control import Choice

from playwright.sync_api import sync_playwright, Response

console = Console()

# ── Theme ─────────────────────────────────────────────────────────────────────

THEME = get_style({
    "questionmark":      "#e5c07b bold",
    "answermark":        "#e5c07b",
    "answer":            "#61afef bold",
    "input":             "#98c379",
    "question":          "#ffffff bold",
    "answered_question": "#5c6370",
    "instruction":       "#5c6370 italic",
    "long_instruction":  "#5c6370",
    "pointer":           "#61afef bold",
    "checkbox":          "#98c379",
    "marker":            "#98c379 bold",
    "validator":         "#e06c75",
    "separator":         "#3e4452",
})

# ── Constants ─────────────────────────────────────────────────────────────────

VERSION      = "1.0.0"
PROFILE_DIR  = os.path.join(os.getcwd(), "chrome_profile")
PROFILE_DEF  = os.path.join(PROFILE_DIR, "Default")
ALLEN_BASE   = "https://allen.in"
CLOUDFRONT   = "https://d2b4i7hu6z450i.cloudfront.net"
SESSION_FILE = "session.json"
CONFIG_FILE  = "browser_config.json"
FFMPEG_DIR   = os.path.join(os.getcwd(), "bin")
FFMPEG_PATH  = os.path.join(FFMPEG_DIR, "ffmpeg.exe")
FFMPEG_URL   = ("https://github.com/BtbN/FFmpeg-Builds/releases/download/"
                "latest/ffmpeg-master-latest-win64-gpl.zip")
SKIP_DIRS    = {"Cache", "Code Cache", "GPUCache", "DawnCache", "ShaderCache",
                "Service Worker", "CacheStorage", "blob_storage"}

STEP_NAMES = ["Content", "Storage", "Account", "Subjects", "Chapters", "Download"]

# Set dynamically by load_browser_config() / setup_browser_config()
CHROME_EXE   = None
REAL_PROFILE = None

# Supported browsers with candidate exe paths and User Data directories
SUPPORTED_BROWSERS = {
    "Google Chrome": {
        "exe_candidates": [
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        ],
        "user_data": os.path.expanduser(r"~\AppData\Local\Google\Chrome\User Data"),
    },
    "Microsoft Edge": {
        "exe_candidates": [
            r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        ],
        "user_data": os.path.expanduser(r"~\AppData\Local\Microsoft\Edge\User Data"),
    },
    "Brave": {
        "exe_candidates": [
            r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe",
            r"C:\Program Files (x86)\BraveSoftware\Brave-Browser\Application\brave.exe",
        ],
        "user_data": os.path.expanduser(r"~\AppData\Local\BraveSoftware\Brave-Browser\User Data"),
    },
}

# ── Logo ─────────────────────────────────────────────────────────────────────

LOGO = r"""
 ╔═╗ ╦   ╦   ╔═╗ ╔╗╔     ╔═╗ ╦ ╦ ╦ ╦
 ╠═╣ ║   ║   ║╣  ║║║     ╠═╝ ║ ║ ╠═╣
 ╩ ╩ ╩═╝ ╩═╝ ╚═╝ ╝╚╝     ╩   ╚═╝ ╩ ╩
 ╔╦╗ ╔═╗ ╔═╗ ╔╦╗ ╦═╗ ╔═╗ ╦ ╦ ╔═╗ ╦═╗
  ║║ ║╣  ╚═╗  ║  ╠╦╝ ║ ║ ╚╦╝ ║╣  ╠╦╝
 ═╩╝ ╚═╝ ╚═╝  ╩  ╩╚═ ╚═╝  ╩  ╚═╝ ╩╚═
"""

# ── ESC sentinel ─────────────────────────────────────────────────────────────

class _GoBack(Exception): pass

def ask(prompt_obj):
    """Execute an InquirerPy prompt; raise _GoBack if user presses Esc (returns None)."""
    try:
        @prompt_obj.register_kb("escape")
        def _handle_escape(event):
            event.app.exit(result=None)
            
        res = prompt_obj.execute()
        if res is None:
            raise _GoBack()
        return res
    except KeyboardInterrupt:
        console.print("\n  [red]Exited via Ctrl+C[/]\n")
        sys.exit(0)

from InquirerPy.prompts.list import ListPrompt
from InquirerPy.separator import Separator
def _smart_toggle_all(self, _, value=None):
    choices = [c for c in self.content_control.choices if not isinstance(c["value"], Separator)]
    if not choices: return
    all_enabled = all(c["enabled"] for c in choices)
    target = not all_enabled  # if all selected → deselect all; otherwise → select all
    for c in choices:
        c["enabled"] = target
ListPrompt._handle_toggle_all = _smart_toggle_all

# ── Screen rendering ──────────────────────────────────────────────────────────

def _fmt_type(k):
    return {"pdfs": "PDFs", "concept_videos": "Concept Videos",
            "live_lectures": "Live Lectures"}.get(k, k)

def _tag(text: str, fg: str = "black", bg: str = "#61afef") -> Text:
    """Render a pill-style tag."""
    t = Text()
    t.append(f" {text} ", style=f"bold {fg} on {bg}")
    return t

def render_screen(step: int, ctx: dict = None):
    """Clear terminal — logo+breadcrumb left, selection tags right."""
    console.clear()

    # ── Left: branding + breadcrumb ───────────────────────────────────────
    left = Text()
    left.append(LOGO.strip("\n") + "\n\n", style="bold bright_cyan")
    left.append(f"  v{VERSION}  ", style="dim")
    for i, name in enumerate(STEP_NAMES):
        if i: left.append(" › ", style="dim")
        if i < step:
            left.append(f"✓ {name}", style="dim green")
        elif i == step:
            left.append(f" {name} ", style="bold black on cyan")
        else:
            left.append(name, style="dim")

    # ── Right: context tags ───────────────────────────────────────────────
    right = Text(justify="left")
    if ctx:
        # Content type tags
        if ctx.get("types"):
            colours = {"pdfs": "#3b82f6", "concept_videos": "#8b5cf6",
                       "live_lectures": "#ec4899"}
            for t in ctx["types"]:
                right.append_text(_tag(_fmt_type(t), bg=colours.get(t, "#61afef")))
                right.append(" ")
            right.append("\n")

        # Output path tag
        if ctx.get("output_dir"):
            right.append("\n")
            right.append_text(_tag(ctx["output_dir"], bg="#059669"))
            right.append("\n")

        # Subject tags
        if ctx.get("subjects"):
            right.append("\n")
            sbg = ["#b45309", "#0f766e", "#7c3aed", "#be185d", "#1d4ed8"]
            for i, s in enumerate(ctx["subjects"]):
                right.append_text(_tag(s, bg=sbg[i % len(sbg)]))
                right.append(" ")

    # ── Two-column grid ───────────────────────────────────────────────────
    grid = Table.grid(expand=True)
    grid.add_column(ratio=2)
    grid.add_column(ratio=3)
    grid.add_row(left, right)

    console.print(Panel(grid, border_style="bright_blue", padding=(0, 2)))
    console.print(Rule(style="blue dim"))
    console.print()

# ── Utilities ─────────────────────────────────────────────────────────────────

def safe_name(s: str) -> str:
    s = re.sub(r'[<>:"/\\|?*]', '', s)
    return re.sub(r'\s+', ' ', s).strip() or 'Untitled'

def card_type_to_folder(card_type: str) -> list:
    ct = re.sub(r'\s*-\s*Content\s*$', '', card_type, flags=re.IGNORECASE).strip()
    return [safe_name(p) for p in ct.split(' - ') if p.strip()] or ['Extra']

def build_qs(cfg: dict, extra: dict) -> str:
    params = {
        "batch_id":            cfg['batch_list'],
        "selected_batch_list": cfg['batch_list'],
        "selected_course_id":  cfg['course_id'],
        "stream":              cfg.get('stream', 'STREAM_JEE_MAIN_ADVANCED'),
        "taxonomy_id":         cfg['taxonomy_id'],
    }
    params.update(extra)
    return urllib.parse.urlencode(params)

def _human(n: int) -> str:
    for unit in ('B', 'KB', 'MB', 'GB'):
        if n < 1024: return f"{n:.0f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"

# ── FFmpeg ────────────────────────────────────────────────────────────────────

# Persistent location for extracted ffmpeg when running as a frozen EXE
APPDATA_DIR         = os.path.join(os.path.expanduser("~"), "AppData", "Roaming", "AllenPuhDestroyer")
BUNDLED_FFMPEG_PATH = os.path.join(APPDATA_DIR, "bin", "ffmpeg.exe")

def find_ffmpeg() -> str | None:
    # When frozen by PyInstaller, extract bundled ffmpeg to a persistent location
    if getattr(sys, 'frozen', False):
        if not os.path.isfile(BUNDLED_FFMPEG_PATH):
            bundled_src = os.path.join(sys._MEIPASS, 'bin', 'ffmpeg.exe')
            if os.path.isfile(bundled_src):
                os.makedirs(os.path.dirname(BUNDLED_FFMPEG_PATH), exist_ok=True)
                shutil.copy2(bundled_src, BUNDLED_FFMPEG_PATH)
        if os.path.isfile(BUNDLED_FFMPEG_PATH): return BUNDLED_FFMPEG_PATH
    if os.path.isfile(FFMPEG_PATH): return FFMPEG_PATH
    return shutil.which("ffmpeg")

def _ensure_playwright_browsers():
    """Check Chromium is installed for playwright (EXE mode only).
    Checks the standard ms-playwright install location directly — no subprocess,
    no re-launch loop, works regardless of PyInstaller bundling.
    If found, writes a flag so subsequent launches skip even this check.
    """
    if not getattr(sys, 'frozen', False): return
    flag = os.path.join(APPDATA_DIR, '.chromium_ready')
    if os.path.isfile(flag): return  # fast path — single file check

    # Check if chromium is in the standard playwright browser cache
    import glob
    local_app_data = os.environ.get('LOCALAPPDATA', '')
    pattern = os.path.join(local_app_data, 'ms-playwright', 'chromium-*', 'chrome-win', 'chrome.exe')
    if glob.glob(pattern):
        # Already installed — just stamp the flag
        os.makedirs(APPDATA_DIR, exist_ok=True)
        open(flag, 'w').close()
        return

    # Not installed — show instructions and exit cleanly
    console.print(Panel(
        "[bold yellow]One-time setup required:[/] Chromium browser not found.\n\n"
        "Run this command once in any terminal, then relaunch the app:\n\n"
        "  [bold cyan]playwright install chromium[/]",
        border_style="yellow", title="[bold]Setup Required[/]"
    ))
    sys.exit(0)

def download_ffmpeg() -> str:
    console.print("\n[bold yellow]FFmpeg not found — downloading portable build...[/]\n")
    os.makedirs(FFMPEG_DIR, exist_ok=True)
    zip_path = os.path.join(FFMPEG_DIR, "ffmpeg.zip")
    req  = urllib.request.Request(FFMPEG_URL, headers={"User-Agent": "Mozilla/5.0"})
    resp = urllib.request.urlopen(req, timeout=300)
    total = int(resp.headers.get('Content-Length', 0))
    with Progress(SpinnerColumn(), TextColumn("[bold blue]{task.description}"),
                  BarColumn(), DownloadColumn(), TransferSpeedColumn(),
                  TimeRemainingColumn()) as prog:
        task = prog.add_task("ffmpeg.zip", total=total)
        with open(zip_path, 'wb') as f:
            while chunk := resp.read(131072):
                f.write(chunk); prog.update(task, advance=len(chunk))
    console.print("[dim]Extracting...[/]")
    with zipfile.ZipFile(zip_path) as zf:
        for name in zf.namelist():
            if name.endswith('bin/ffmpeg.exe'):
                with zf.open(name) as src, open(FFMPEG_PATH, 'wb') as dst:
                    shutil.copyfileobj(src, dst)
                break
    os.remove(zip_path)
    console.print(f"[green]ffmpeg ready:[/] {FFMPEG_PATH}\n")
    return FFMPEG_PATH

# ── Session ───────────────────────────────────────────────────────────────────

def load_session() -> dict | None:
    if not os.path.isfile(SESSION_FILE): return None
    try:
        with open(SESSION_FILE, encoding='utf-8') as f: return json.load(f)
    except Exception: return None

def save_session(s: dict):
    with open(SESSION_FILE, 'w', encoding='utf-8') as f:
        json.dump(s, f, indent=2, ensure_ascii=False)

def count_pending(s: dict) -> int:
    return sum(1 for it in s.get('queue', []) if it.get('status') != 'done')

# ── Browser setup wizard ─────────────────────────────────────────────────────

def _detect_browsers() -> list[str]:
    """Return names of SUPPORTED_BROWSERS that are actually installed."""
    found = []
    for name, info in SUPPORTED_BROWSERS.items():
        for exe in info["exe_candidates"]:
            if os.path.isfile(exe):
                found.append(name)
                break
    return found

def _list_profiles(user_data_dir: str) -> list[tuple[str, str]]:
    """Return [(dir_name, display_name), ...] for all profiles in user_data_dir."""
    info_cache = {}
    local_state = os.path.join(user_data_dir, "Local State")
    if os.path.isfile(local_state):
        try:
            with open(local_state, encoding="utf-8") as f:
                data = json.load(f)
            info_cache = data.get("profile", {}).get("info_cache", {})
        except Exception:
            pass
    profiles = []
    try:
        for entry in os.listdir(user_data_dir):
            full = os.path.join(user_data_dir, entry)
            if os.path.isdir(full) and (entry == "Default" or entry.startswith("Profile ")):
                display = info_cache.get(entry, {}).get("name", entry)
                profiles.append((entry, display))
    except Exception:
        pass
    if not profiles:
        profiles = [("Default", "Default")]
    return sorted(profiles, key=lambda x: (x[0] != "Default", x[0]))

def load_browser_config() -> bool:
    """Load saved browser/profile config. Returns True if loaded successfully."""
    global CHROME_EXE, REAL_PROFILE
    if not os.path.isfile(CONFIG_FILE):
        return False
    try:
        with open(CONFIG_FILE, encoding="utf-8") as f:
            cfg = json.load(f)
        CHROME_EXE   = cfg["exe"]
        REAL_PROFILE = cfg["real_profile"]
        return bool(CHROME_EXE and REAL_PROFILE)
    except Exception:
        return False

def setup_browser_config():
    """First-run wizard: pick browser → pick profile → save to browser_config.json."""
    global CHROME_EXE, REAL_PROFILE

    console.clear()
    console.print(Panel(
        Text.assemble(
            (LOGO.strip("\n"), "bold bright_cyan"), "\n\n",
            ("  First-Run Setup\n", "bold white"),
            ("  Choose the browser you have Allen logged into.", "dim"),
        ),
        border_style="bright_blue", padding=(1, 2)
    ))
    console.print()

    # ── Step 1: browser ───────────────────────────────────────────────────
    available = _detect_browsers()
    if not available:
        console.print(Panel(
            "[red]No supported browser found.[/]\n"
            "Install Chrome, Edge, or Brave and log into Allen, then run again.",
            border_style="red", title="[bold red]Error[/]"
        ))
        sys.exit(1)

    browser_name = ask(inquirer.select(
        message="Which browser do you have Allen logged into?",
        choices=available,
        style=THEME,
    ))

    info         = SUPPORTED_BROWSERS[browser_name]
    user_data    = info["user_data"]
    exe          = next((e for e in info["exe_candidates"] if os.path.isfile(e)), None)

    # ── Step 2: profile ───────────────────────────────────────────────────
    profiles = _list_profiles(user_data)

    if len(profiles) == 1:
        profile_dir, profile_display = profiles[0]
        console.print(f"\n  [dim]Only one profile found:[/] [cyan]{profile_display}[/]")
    else:
        profile_choices = [
            Choice(value=d, name=f"{n}  [dim]({d})[/dim]")
            for d, n in profiles
        ]
        profile_dir = ask(inquirer.select(
            message="Which profile is Allen logged into?",
            choices=profile_choices,
            style=THEME,
        ))

    real_profile = os.path.join(user_data, profile_dir)

    # ── Save ──────────────────────────────────────────────────────────────
    cfg = {"browser": browser_name, "exe": exe, "real_profile": real_profile}
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)

    # Wipe any old synced profile so it re-syncs cleanly
    if os.path.exists(PROFILE_DIR):
        shutil.rmtree(PROFILE_DIR, ignore_errors=True)

    CHROME_EXE   = exe
    REAL_PROFILE = real_profile

    console.print()
    console.print(f"  [green]✓[/] Browser: [cyan]{browser_name}[/]")
    console.print(f"  [green]✓[/] Profile: [cyan]{real_profile}[/]")
    console.print(f"  [dim]Config saved. Delete {CONFIG_FILE} to reconfigure.[/]\n")
    input("  Press Enter to continue...")

# ── Browser profile sync ──────────────────────────────────────────────────────

def sync_profile():
    if os.path.exists(PROFILE_DEF): return
    console.print("[dim]Syncing browser session...[/]")
    os.makedirs(PROFILE_DEF, exist_ok=True)
    for item in os.listdir(REAL_PROFILE):
        if item in SKIP_DIRS: continue
        src = os.path.join(REAL_PROFILE, item)
        dst = os.path.join(PROFILE_DEF, item)
        try:
            if os.path.isdir(src):
                if os.path.exists(dst): shutil.rmtree(dst)
                shutil.copytree(src, dst)
            else:
                shutil.copy2(src, dst)
        except Exception: pass

# ── Browser helpers ───────────────────────────────────────────────────────────

def launch_browser(pw):
    return pw.chromium.launch_persistent_context(
        user_data_dir=PROFILE_DIR, executable_path=CHROME_EXE, headless=True,
        args=["--disable-blink-features=AutomationControlled",
              "--disable-restore-session-state",
              "--no-first-run", "--no-default-browser-check"])

def get_page(ctx):
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    return page

HEADERS_CACHE = {}

PLAYWRIGHT_LOCK = threading.Lock()

def fetch_page(page, url: str) -> dict:
    try:
        with PLAYWRIGHT_LOCK:
            with page.expect_response(lambda r: "/api/v1/pages/getPage" in r.url and r.status == 200, timeout=10000) as resp_info:
                page.goto(url, wait_until="domcontentloaded")
            return resp_info.value.json().get('data', {})
    except Exception:
        return {}

def fast_fetch_page(page, url: str) -> dict:
    from urllib.parse import urlparse
    parsed = urlparse(url)
    rel_url = parsed.path
    if parsed.query: rel_url += "?" + parsed.query

    req_headers = {
        "content-type": "application/json",
        "origin": "https://allen.in",
        "referer": "https://allen.in/",
    }
    for k, v in HEADERS_CACHE.items():
        k_low = k.lower()
        if k_low not in ["content-length", "host", "connection", "accept-encoding", "content-type", "origin", "referer", "cookie"]:
            req_headers[k_low] = v
        
    cookies = page.context.cookies()
    cookie_str = "; ".join([f"{c['name']}={c['value']}" for c in cookies])
    if cookie_str: req_headers["cookie"] = cookie_str
    
    req = urllib.request.Request(
        "https://api.allen-live.in/api/v1/pages/getPage",
        data=json.dumps({"page_url": rel_url}).encode("utf-8"),
        headers=req_headers,
        method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            res_data = json.loads(r.read().decode("utf-8")).get("data", {})
            page_content = res_data.get('page_content')
            if isinstance(page_content, dict) and 'widgets' in page_content and not page_content['widgets']:
                return fetch_page(page, url)
            return res_data
    except Exception:
        return fetch_page(page, url)  # Fallback

def warmup(page):
    def on_req(req):
        if "/api/v1/pages/getPage" in req.url:
            HEADERS_CACHE.update(req.headers)
            
    page.on("request", on_req)
    with PLAYWRIGHT_LOCK:
        page.goto(f"{ALLEN_BASE}/", wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(2000)
    page.remove_listener("request", on_req)

def get_video_m3u8(page, content_id: str, batch_id: str) -> tuple[str | None, str]:
    err_msg = "Unknown error"
    result = {}
    for attempt in range(3):
        try:
            with PLAYWRIGHT_LOCK:
                with page.expect_response(lambda r: "/api/v1/video/play" in r.url and r.status == 200, timeout=10000) as resp_info:
                    page.goto(f"{ALLEN_BASE}/videoPlayer?content_id={content_id}&batch_id={batch_id}", wait_until="domcontentloaded")
                result = resp_info.value.json().get('data', {})
                break
        except Exception as e:
            err_msg = str(e)
            time.sleep(1)
            
    if not result:
        return None, err_msg or "Timeout extracting m3u8"

    m3u8 = None
    def find(obj):
        nonlocal m3u8
        if isinstance(obj, str) and 'master.m3u8' in obj: m3u8 = obj; return
        if isinstance(obj, dict):
            for v in obj.values():
                find(v)
                if m3u8: return
        elif isinstance(obj, list):
            for v in obj:
                find(v)
                if m3u8: return
    find(result)
    return m3u8, "" if m3u8 else "No master.m3u8 in stream response"

# ── API parsers ───────────────────────────────────────────────────────────────

def detect_config(data: dict) -> dict:
    cfg = {'batch_list': '', 'course_id': '', 'taxonomy_id': '',
           'stream': '', 'subjects': {}}
    def walk(obj):
        if isinstance(obj, dict):
            for key in ('selected_batch_list', 'batch_id'):
                v = obj.get(key, '')
                if v and not cfg['batch_list']: cfg['batch_list'] = v
            for key, field in [('selected_course_id','course_id'),
                                ('taxonomy_id','taxonomy_id'), ('stream','stream')]:
                v = obj.get(key, '')
                if v and not cfg[field]: cfg[field] = v
            sid = str(obj.get('subject_id') or '')
            sn  = (obj.get('subject_name') or '').strip()
            if sid and sn and sid not in cfg['subjects']:
                cfg['subjects'][sid] = sn
            for v in obj.values(): walk(v)
        elif isinstance(obj, list):
            for v in obj: walk(v)
    walk(data)
    if not cfg['stream']: cfg['stream'] = 'STREAM_JEE_MAIN_ADVANCED'
    return cfg

def get_topics(data: dict) -> list:
    topics, seen = [], set()
    def walk(obj):
        if isinstance(obj, dict):
            tid = str(obj.get('topic_id') or '')
            tn  = (obj.get('topic_name') or obj.get('card_name') or '').strip()
            if tid and tn and tid not in seen:
                seen.add(tid); topics.append((tid, tn))
            for v in obj.values(): walk(v)
        elif isinstance(obj, list):
            for v in obj: walk(v)
    walk(data)
    return topics

def collect_pdfs(obj, results=None):
    if results is None: results = []
    if isinstance(obj, list):
        for it in obj: collect_pdfs(it, results)
    elif isinstance(obj, dict):
        action = obj.get('content_action') or {}
        if isinstance(action, dict) and action.get('type') == 'OPEN_PDF':
            ad  = action.get('data') or {}
            cid = ad.get('content_id', '')
            if not cid:
                m = re.search(r'/([0-9a-f-]{36})/original', ad.get('uri', ''))
                cid = m.group(1) if m else ''
            title    = safe_name(obj.get('content_title') or ad.get('title') or 'Document')
            tracking = (action.get('tracking_params') or {}).get('current') or {}
            ct       = tracking.get('card_type', '')
            cat      = card_type_to_folder(ct) if ct else ['Misc']
            if cid: results.append({'title': title, 'content_id': cid, 'category': cat})
            return
        for v in obj.values(): collect_pdfs(v, results)
    return results

def collect_videos(obj, results=None):
    if results is None: results = []
    if isinstance(obj, list):
        for it in obj: collect_videos(it, results)
    elif isinstance(obj, dict):
        action = obj.get('content_action') or {}
        if isinstance(action, dict) and action.get('type') == 'PLAY_VIDEO':
            ad       = action.get('data') or {}
            tracking = (action.get('tracking_params') or {}).get('current') or {}
            cid      = ad.get('content_id', '')
            bid      = ad.get('batch_id', '')
            title    = safe_name(obj.get('content_title') or ad.get('title') or 'Video')
            seq      = obj.get('sequence') or 0
            section  = tracking.get('section_name', 'Videos')
            if cid:
                results.append({'content_id': cid, 'batch_id': bid,
                                'title': title, 'sequence': seq, 'section': section})
            return
        for v in obj.values(): collect_videos(v, results)
    return results

# ── Download primitives ───────────────────────────────────────────────────────

def dl_pdf(content_id: str, filepath: str, overwrite: bool,
           on_progress=None) -> tuple[bool, str]:
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    if os.path.exists(filepath) and not overwrite:
        return True, ""  # skip
    url = f"{CLOUDFRONT}/{content_id}/original.pdf"
    
    err_msg = "Unknown error"
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers={"Referer": "https://allen.in/"})
            with urllib.request.urlopen(req, timeout=60) as r:
                total = int(r.headers.get('Content-Length', 0))
                with open(filepath, 'wb') as f:
                    done = 0
                    while chunk := r.read(131072):
                        f.write(chunk); done += len(chunk)
                        if on_progress: on_progress(done, total)
            if os.path.getsize(filepath) > 0:
                return True, ""
        except Exception as e:
            if os.path.exists(filepath): os.remove(filepath)
            err_msg = str(e)
            time.sleep(2)
            
    return False, err_msg or "Failed to establish stream or 0 bytes"

def dl_video(ffmpeg: str, m3u8_url: str, filepath: str, overwrite: bool,
             on_size=None) -> tuple[bool, str]:
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    if os.path.exists(filepath) and not overwrite:
        return True, ""  # skip
    tmp = filepath + ".part"
    
    err_msg = "Unknown error"
    for attempt in range(3):
        cmd = [ffmpeg, '-y', '-loglevel', 'error',
               '-headers', 'Referer: https://allen.in/\r\nOrigin: https://allen.in\r\n',
               '-i', m3u8_url, '-c', 'copy', '-movflags', '+faststart', tmp]
        proc = subprocess.Popen(cmd, stderr=subprocess.PIPE, text=True)
        stop = threading.Event()
        def _monitor():
            while not stop.is_set():
                if os.path.exists(tmp) and on_size:
                    on_size(os.path.getsize(tmp))
                time.sleep(0.4)
        t = threading.Thread(target=_monitor, daemon=True); t.start()
        _, err = proc.communicate()
        stop.set(); t.join(timeout=1)
        if proc.returncode == 0 and os.path.exists(tmp):
            os.rename(tmp, filepath)
            return True, ""
        if os.path.exists(tmp): os.remove(tmp)
        
        if "403 Forbidden" in err: err_msg = "403 Forbidden"
        elif "Input/output error" in err: err_msg = "I/O Error"
        else: err_msg = err.strip().split('\n')[0] if err.strip() else f"exit code {proc.returncode}"
        time.sleep(2)
        
    return False, err_msg or "ffmpeg processing failed completely"

# ── Download engine with Rich Live ───────────────────────────────────────────

def do_download(ctx, page, session: dict, ffmpeg: str):
    queue      = session['queue']
    total      = len(queue)
    overwrite  = session.get('overwrite', False)
    done_count = sum(1 for q in queue if q['status'] == 'done')
    fail_count = 0
    skip_count = 0
    failures   = []
    log_lines  = []   # list of Text objects (recent N)
    MAX_LOG    = 10
    downloaded_bytes = 0
    start_time = time.time()

    # Overall progress
    overall = Progress(
        TextColumn("  [bold]{task.description}"),
        BarColumn(bar_width=None),
        MofNCompleteColumn(),
        TimeRemainingColumn(),
        expand=True,
    )
    overall_task = overall.add_task("Overall", total=total, completed=done_count)

    # Per-file progress
    file_prog = Progress(
        SpinnerColumn(),
        TextColumn("  [bold]{task.description}"),
        BarColumn(bar_width=None),
        DownloadColumn(),
        TransferSpeedColumn(),
        expand=True,
    )

    def make_log_table() -> Table:
        t = Table.grid(padding=(0, 1))
        t.add_column(width=2, no_wrap=True)
        t.add_column(no_wrap=False)
        t.add_column(justify="right", style="dim", no_wrap=True)
        for row in log_lines[-MAX_LOG:]:
            t.add_row(*row)
        return t

    def make_display() -> Panel:
        sep   = Rule(style="dim")
        inner = Group(overall, sep, file_prog, sep, make_log_table())
        return Panel(inner, title="[bold cyan]Downloading[/]",
                     border_style="cyan", padding=(0, 1))

    try:
        with Live(get_renderable=make_display, refresh_per_second=8,
                  console=console, vertical_overflow="visible") as live:

            pool_lock = threading.Lock()
            
            def process_item(item):
                nonlocal done_count, fail_count, skip_count, downloaded_bytes
                
                if item['status'] == 'done':
                    with pool_lock:
                        overall.update(overall_task, advance=1)
                    return

                tag   = "PDF" if item['type'] == 'pdf' else "VID"
                label = f"[dim]{item['chapter']}[/]  {item['title']}"
                
                with pool_lock:
                    task_id = file_prog.add_task(f"[{tag}] {label}", total=None, completed=0, visible=True)

                ok = False
                skipped = False
                err_msg = ""

                if item['type'] == 'pdf':
                    existed = os.path.exists(item['filepath'])

                    def pdf_progress(done, total_bytes):
                        file_prog.update(task_id, completed=done, total=total_bytes if total_bytes else None)

                    ok, err_msg = dl_pdf(item['content_id'], item['filepath'], overwrite, pdf_progress)
                    if ok and existed and not overwrite:
                        skipped = True

                else:
                    existed = os.path.exists(item['filepath'])

                    m3u8, err_m3u8 = get_video_m3u8(page, item['content_id'], item.get('batch_id', ''))
                    
                    if not m3u8:
                        icon = "[red]✗[/]"
                        with pool_lock:
                            log_lines.append((icon, item['title'], "no stream"))
                            fail_count += 1
                            item['error'] = err_m3u8
                            failures.append(item)
                            overall.update(overall_task, advance=1)
                            file_prog.update(task_id, visible=False)
                        save_session(session)
                        return

                    def vid_size(sz):
                        file_prog.update(task_id, completed=sz, total=None)

                    ok, err_msg = dl_video(ffmpeg, m3u8, item['filepath'], overwrite, vid_size)
                    if ok and existed and not overwrite:
                        skipped = True

                with pool_lock:
                    if ok:
                        item['status'] = 'done'
                        if skipped:
                            skip_count += 1
                            icon = "[dim]–[/]"
                            size_str = "skipped"
                        else:
                            sz = os.path.getsize(item['filepath'])
                            size_str  = _human(sz)
                            icon = "[green]✓[/]"
                            downloaded_bytes += sz
                        log_lines.append((icon, item['title'], size_str))
                        done_count += 1
                    else:
                        icon = "[red]✗[/]"
                        log_lines.append((icon, item['title'], "error"))
                        fail_count += 1
                        item['error'] = err_msg
                        failures.append(item)

                    overall.update(overall_task, advance=1)
                    file_prog.update(task_id, visible=False)
                save_session(session)

            with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
                futures = [pool.submit(process_item, it) for it in queue]
                concurrent.futures.wait(futures)

    except KeyboardInterrupt:
        save_session(session)
        console.print("\n  [bold yellow]Interrupted — progress saved.[/]")
        console.print("  [dim]Run again to resume.[/]\n")
        sys.exit(0)

    # Final summary
    console.print()
    succeeded = (total - done_count) - fail_count - skip_count + (done_count)
    console.print(Rule(title="[bold]Results[/]", style="bright_blue"))
    t = Table.grid(padding=(0, 3))
    t.add_column(); t.add_column(); t.add_column(); t.add_column()
    t.add_row(f"[green]✓  Done: {succeeded}[/]",
              f"[red]✗  Failed: {fail_count}[/]",
              f"[dim]–  Skipped: {skip_count}[/]",
              f"[dim]Total: {total}[/]")
    console.print(t)
    console.print()

    if failures:
        ft = Table(title="Failed Items", box=box.SIMPLE_HEAD, border_style="red")
        ft.add_column("Type", width=5, style="bold")
        ft.add_column("Chapter", style="dim")
        ft.add_column("Title")
        ft.add_column("Error Reason", style="yellow")
        for f in failures:
            ft.add_row(f['type'].upper(), f['chapter'][:25], f['title'][:35], f.get('error', 'Unknown Error')[:40])
        console.print(ft)

def show_completion(session: dict, stats: tuple = None):
    pending = count_pending(session)
    total   = len(session.get('queue', []))
    if pending == 0:
        try: os.remove(SESSION_FILE)
        except: pass
        console.print(Panel(
            f"[bold green]All {total} items downloaded successfully.[/]\n"
            f"Saved to: [cyan]{session.get('output_dir', '.')}[/]",
            title="[bold green]Complete[/]", border_style="green"))
    else:
        console.print(Panel(
            f"Downloaded {total-pending}/{total}. [yellow]{pending} remaining.[/]\n"
            f"Run [bold cyan]python app.py[/] again to resume.",
            title="[bold yellow]Partial[/]", border_style="yellow"))

    if stats:
        downloaded_bytes, elapsed_time = stats
        speed = downloaded_bytes / elapsed_time if elapsed_time > 0 else 0
        console.print(f"\n  [dim]Speed: {_human(speed)}/s  •  Time: {int(elapsed_time)}s  •  Data: {_human(downloaded_bytes)}[/]\n")

# ── Browser phases (return data, no prompts inside) ───────────────────────────

def browser_detect_account() -> dict:
    with sync_playwright() as pw:
        ctx  = launch_browser(pw)
        page = get_page(ctx)
        with console.status("[bold blue]Loading Allen...[/]"):
            warmup(page)
        with console.status("[bold blue]Detecting account...[/]"):
            lib_data = fetch_page(page, f"{ALLEN_BASE}/library-web")
            cfg      = detect_config(lib_data)
            if not cfg['batch_list'] or not cfg['subjects']:
                hdata = fetch_page(page, f"{ALLEN_BASE}/home")
                hcfg  = detect_config(hdata)
                for k in ('batch_list', 'course_id', 'taxonomy_id', 'stream'):
                    if not cfg[k]: cfg[k] = hcfg[k]
                cfg['subjects'].update(hcfg['subjects'])
        ctx.close()
    return cfg

def browser_fetch_chapters(cfg: dict, sel_sids: list) -> dict:
    topics_by_sid = {}
    with sync_playwright() as pw:
        ctx  = launch_browser(pw)
        page = get_page(ctx)
        for sid in sel_sids:
            sname = cfg['subjects'][sid]
            with console.status(f"[bold blue]Fetching topics for {sname}...[/]"):
                qs   = build_qs(cfg, {"subject_id": sid})
                data = fast_fetch_page(page, f"{ALLEN_BASE}/subject-details?{qs}")
            topics = get_topics(data)
            topics_by_sid[sid] = topics
            console.print(f"  [dim]{sname}:[/] {len(topics)} chapters")
        ctx.close()
    return topics_by_sid

def browser_enumerate_content(cfg: dict, sel_chapters: dict,
                               selected_types: list, need_videos: bool,
                               output_dir: str) -> list:
    queue = []
    with sync_playwright() as pw:
        ctx  = launch_browser(pw)
        page = get_page(ctx)
        total_ch = sum(len(c) for c in sel_chapters.values())
        ch_i     = 0
        console.print(f"\n  [bold]Scanning {total_ch} chapters...[/]\n")
        for sid, chapters in sel_chapters.items():
            sname = cfg['subjects'][sid]
            for tid, tname in chapters:
                ch_i += 1
                console.print(f"  [dim][{ch_i}/{total_ch}][/]  {sname} › {tname}", end="")
                qs   = build_qs(cfg, {"subject_id": sid, "topic_id": tid})
                data = fast_fetch_page(page, f"{ALLEN_BASE}/topic-details?{qs}")
                if not data:
                    console.print("  [yellow]— no data[/]"); continue
                ch_safe = safe_name(tname)
                p_count = v_count = 0
                if "pdfs" in selected_types:
                    for pdf in collect_pdfs(data):
                        folder = os.path.join(output_dir, sname, ch_safe, *pdf['category'])
                        queue.append({
                            'type': 'pdf', 'subject': sname, 'chapter': ch_safe,
                            'category': pdf['category'], 'title': pdf['title'],
                            'content_id': pdf['content_id'],
                            'filepath': os.path.join(folder, f"{pdf['title']}.pdf"),
                            'status': 'pending',
                        })
                        p_count += 1
                if need_videos:
                    groups = {}
                    for v in collect_videos(data):
                        groups.setdefault(v['section'], []).append(v)
                    for sec_name, vids in groups.items():
                        sl = sec_name.lower()
                        if 'concept' in sl and 'concept_videos' not in selected_types: continue
                        if 'live'    in sl and 'live_lectures'  not in selected_types: continue
                        vids.sort(key=lambda v: v['sequence'])
                        for i, vid in enumerate(vids, 1):
                            fname  = f"#{i:02d} - {vid['title']}"
                            folder = os.path.join(output_dir, sname, ch_safe, safe_name(sec_name))
                            queue.append({
                                'type': 'video', 'subject': sname, 'chapter': ch_safe,
                                'category': [safe_name(sec_name)], 'title': fname,
                                'content_id': vid['content_id'],
                                'batch_id':   vid['batch_id'],
                                'filepath':   os.path.join(folder, f"{fname}.mp4"),
                                'status': 'pending',
                            })
                            v_count += 1
                parts = []
                if p_count: parts.append(f"{p_count} PDFs")
                if v_count: parts.append(f"{v_count} videos")
                console.print(f"  — {', '.join(parts) if parts else 'nothing'}")
                time.sleep(0.3)
        ctx.close()
    return queue

# ── Interactive prompts (all return result or raise _GoBack) ──────────────────

def prompt_content_types(ctx=None, prev=None) -> list:
    render_screen(0, ctx)
    choices = [
        Choice("pdfs",           "PDF Study Materials",       enabled=False),
        Choice("concept_videos", "Concept Videos",            enabled=False),
        Choice("live_lectures",  "Live Lecture Recordings",   enabled=False),
    ]
    # Restore previous if coming back
    if prev:
        for c in choices: c.enabled = c.value in prev
    return ask(inquirer.checkbox(
        message="What do you want to download?",
        choices=choices, style=THEME,
        instruction="(Alt+A=Select All, Space=toggle, Enter=confirm, Esc=back)",
        validate=lambda r: len(r) > 0,
        invalid_message="Pick at least one.",
        cycle=True, max_height="60%", mandatory=False,
    ))

def prompt_overwrite(ctx=None, prev=None) -> bool:
    render_screen(1, ctx)
    choices = [
        Choice(False, "Skip — keep files already downloaded"),
        Choice(True,  "Overwrite — re-download everything"),
    ]
    default_idx = 1 if prev else 0
    return ask(inquirer.select(
        message="Files that already exist:",
        choices=choices, style=THEME,
        instruction="(Arrow keys, Enter, Esc=back)",
        default=choices[default_idx].value, mandatory=False,
    ))

def prompt_output_dir(ctx=None, prev=None) -> str:
    default = os.path.abspath("Allen_Materials")
    render_screen(1, ctx)
    method = ask(inquirer.select(
        message="Where should downloads go?",
        choices=[
            Choice("default", f"Default folder  →  {default}"),
            Choice("browse",  "Browse with Windows file explorer"),
            Choice("type",    "Type a path manually"),
        ],
        style=THEME,
        instruction="(Arrow keys, Enter, Esc=back)",
        default="default" if not prev or prev == default else "type", mandatory=False,
    ))
    if method == "default": return default
    if method == "browse":
        try:
            import tkinter as tk
            from tkinter import filedialog
            root = tk.Tk(); root.withdraw()
            root.attributes('-topmost', True)
            folder = filedialog.askdirectory(title="Select Download Folder")
            root.destroy()
            if folder:
                console.print(f"\n  [green]Selected:[/] {folder}")
                return folder
        except Exception:
            console.print("\n  [yellow]File dialog unavailable — type path instead.[/]")
    return os.path.abspath(ask(inquirer.text(
        message="Enter path:", default=prev or default, style=THEME, mandatory=False,
    )))

def prompt_chrome_close(ctx=None) -> bool:
    render_screen(2, ctx)
    console.print(
        Panel(
            "[yellow]Close every Chrome window before continuing.[/]\n"
            "[dim]The tool copies your Chrome profile to authenticate.[/]",
            border_style="yellow", padding=(0, 2),
        )
    )
    console.print()
    return ask(inquirer.confirm(
        message="All Chrome windows are closed — ready?",
        default=True, style=THEME, mandatory=False,
    ))

def prompt_subjects(cfg: dict, ctx=None, prev=None) -> list:
    render_screen(3, ctx)
    choices = [Choice(sid, sname, enabled=False)
               for sid, sname in cfg['subjects'].items()]
    if prev:
        for c in choices: c.enabled = c.value in prev
    return ask(inquirer.checkbox(
        message="Which subjects?",
        choices=choices, style=THEME,
        instruction="(Alt+A=Select All, Space=toggle, Enter=confirm, Esc=back)",
        validate=lambda r: len(r) > 0,
        invalid_message="Select at least one subject.",
        cycle=True, max_height="75%", mandatory=False,
    ))

def prompt_chapters(sname: str, topics: list, ctx=None, prev_set=None) -> list:
    render_screen(4, ctx)
    choices = [Choice(tid, tname,
                      enabled=(prev_set is not None and tid in prev_set))
               for tid, tname in topics]
    return ask(inquirer.checkbox(
        message=f"{sname}  —  select chapters:",
        choices=choices, style=THEME,
        instruction=f"({len(topics)} total — Alt+A=Select All, Space=toggle, Enter=confirm, Esc=back)",
        validate=lambda r: len(r) > 0,
        invalid_message="Select at least one chapter.",
        cycle=True, max_height="75%", mandatory=False,
    ))

def prompt_confirm(queue: list, output_dir: str, ctx=None) -> bool:
    render_screen(5, ctx)
    n_pdf = sum(1 for q in queue if q['type'] == 'pdf')
    n_vid = sum(1 for q in queue if q['type'] == 'video')
    t = Table(title="Ready to Download", box=box.ROUNDED,
              border_style="cyan", show_lines=False, padding=(0, 2))
    t.add_column("", style="bold", min_width=16)
    t.add_column("", justify="right")
    if n_pdf: t.add_row("PDF files",  str(n_pdf))
    if n_vid: t.add_row("Videos",     str(n_vid))
    t.add_row("[bold]Total items[/]", f"[bold cyan]{len(queue)}[/]")
    t.add_row("Output",               output_dir)
    console.print(t); console.print()
    return ask(inquirer.confirm(
        message="Start download?",
        default=True, style=THEME, mandatory=False,
    ))

# ── Main state machine ────────────────────────────────────────────────────────

def main():
    _ensure_playwright_browsers()
    if not load_browser_config():
        setup_browser_config()
    ffmpeg = find_ffmpeg()

    # ── Welcome ───────────────────────────────────────────────────────────
    console.clear()
    console.print(Panel(
        Text.assemble(
            (LOGO.strip("\n"), "bold bright_cyan"), "\n\n",
            (f"  v{VERSION}  —  Keyboard-driven Allen study downloader", "dim"),
        ),
        border_style="bright_blue", padding=(1, 4),
        subtitle=(
            "[green]ffmpeg: ready[/]" if ffmpeg
            else "[yellow]ffmpeg: will auto-download[/]"
        ),
    ))
    console.print(Rule(style="blue dim"))
    console.print()

    # ── Resume check ──────────────────────────────────────────────────────
    prev_session = load_session()
    if prev_session and count_pending(prev_session) > 0:
        pending = count_pending(prev_session)
        total   = len(prev_session['queue'])
        try:
            resume = ask(inquirer.select(
                message=f"Previous session found — {total-pending}/{total} done, {pending} left.",
                choices=[
                    Choice(True,  "Resume where I left off"),
                    Choice(False, "Start fresh"),
                ],
                style=THEME,
            ))
        except _GoBack:
            resume = False

        if resume:
            if not ffmpeg: ffmpeg = download_ffmpeg()
            try:
                ask(inquirer.confirm(
                    message="Close all Chrome windows then press Enter.",
                    default=True, style=THEME,
                ))
            except _GoBack:
                pass
            sync_profile()
            with sync_playwright() as pw:
                ctx  = launch_browser(pw)
                page = get_page(ctx)
                with console.status("[bold blue]Loading Allen...[/]"):
                    warmup(page)
                do_download(ctx, page, prev_session, ffmpeg)
                ctx.close()
            show_completion(prev_session)
            return
        else:
            try: os.remove(SESSION_FILE)
            except: pass

    # ────────────────────────────────────────────────────────────────────
    # State machine — step is the current "screen index".
    # Each prompt raises _GoBack to step back or returns its value.
    # Browser phases run synchronously (their own with sync_playwright block)
    # and results are cached so we only re-run when inputs change.
    # ────────────────────────────────────────────────────────────────────

    step = 0

    # Cached state (avoids re-running browser phases unnecessarily)
    selected_types  = None
    overwrite       = False
    output_dir      = None
    cfg             = None          # set once; subjects don't change per session
    sel_sids        = None
    topics_by_sid   = {}
    prev_sel_sids   = None          # detect changes → invalidate topics cache
    sel_chapters    = {}
    prev_sel_chaps  = None
    queue           = []

    while True:

        ctx_summary = {
            "types":      selected_types,
            "output_dir": output_dir,
            "subjects":   [cfg['subjects'][s] for s in (sel_sids or [])] if cfg else None,
        }

        # ── Step 0: Content types ─────────────────────────────────────
        if step == 0:
            try:
                selected_types = prompt_content_types(ctx=None, prev=selected_types)
                step = 1
            except _GoBack:
                sys.exit(0)

        # ── Step 1: Overwrite + Output dir ────────────────────────────
        elif step == 1:
            try:
                overwrite  = prompt_overwrite(ctx=ctx_summary, prev=overwrite)
                output_dir = prompt_output_dir(ctx=ctx_summary, prev=output_dir)
                os.makedirs(output_dir, exist_ok=True)
                step = 2
            except _GoBack:
                step = 0

        # ── Step 2: Chrome close + account detection ──────────────────
        elif step == 2:
            try:
                prompt_chrome_close(ctx=ctx_summary)
            except _GoBack:
                step = 1; continue

            sync_profile()
            if cfg is None:   # only run browser 1 once
                cfg = browser_detect_account()
                if not cfg.get('batch_list') or not cfg.get('subjects'):
                    console.print("[bold red]Could not detect your account.[/]")
                    console.print("[dim]Log into Allen in Chrome and try again.[/]\n")
                    cfg = None; step = 1; continue

            console.print(f"\n  [green]Detected:[/] "
                          f"{', '.join(cfg['subjects'].values())}\n")
            step = 3

        # ── Step 3: Subject selection ─────────────────────────────────
        elif step == 3:
            try:
                sel_sids = prompt_subjects(cfg, ctx=ctx_summary, prev=sel_sids)
            except _GoBack:
                step = 1; continue   # go back before chrome/browser

            # Invalidate chapters cache if subjects changed
            if sel_sids != prev_sel_sids:
                topics_by_sid = {}
                prev_sel_sids = sel_sids[:]
                sel_chapters  = {}

            if not topics_by_sid:
                topics_by_sid = browser_fetch_chapters(cfg, sel_sids)

            step = 4

        # ── Step 4: Chapter selection (one subject at a time) ─────────
        elif step == 4:
            new_sel_chapters = {}
            backed_out = False
            for sid in sel_sids:
                sname  = cfg['subjects'][sid]
                topics = topics_by_sid.get(sid, [])
                if not topics:
                    console.print(f"  [yellow]{sname}: no chapters — skipping[/]")
                    continue
                prev_tids = set(tid for tid, _ in sel_chapters.get(sid, []))
                try:
                    chosen = prompt_chapters(sname, topics, ctx=ctx_summary,
                                             prev_set=prev_tids if prev_tids else None)
                    new_sel_chapters[sid] = [(tid, tn) for tid, tn in topics
                                             if tid in chosen]
                except _GoBack:
                    backed_out = True; break

            if backed_out:
                step = 3; continue

            if not new_sel_chapters:
                console.print("[yellow]No chapters selected.[/]")
                step = 3; continue

            # Invalidate queue if chapters changed
            if new_sel_chapters != prev_sel_chaps:
                prev_sel_chaps = new_sel_chapters
                sel_chapters   = new_sel_chapters
                need_videos    = ("concept_videos" in selected_types or
                                  "live_lectures"  in selected_types)
                if not ffmpeg and need_videos:
                    ffmpeg = download_ffmpeg()
                queue = browser_enumerate_content(
                    cfg, sel_chapters, selected_types, need_videos, output_dir)
            else:
                sel_chapters = new_sel_chapters

            step = 5

        # ── Step 5: Confirm + download ────────────────────────────────
        elif step == 5:
            if not queue:
                console.print("  [yellow]Nothing to download — adjust your selection.[/]")
                step = 4; continue

            try:
                go = prompt_confirm(queue, output_dir, ctx=ctx_summary)
            except _GoBack:
                step = 4; continue

            if not go:
                step = 4; continue

            session = {
                'version': 1, 'output_dir': output_dir,
                'overwrite': overwrite, 'config': cfg, 'queue': queue,
            }
            save_session(session)

            need_videos = ("concept_videos" in selected_types or
                           "live_lectures"  in selected_types)
            with sync_playwright() as pw:
                ctx_b  = launch_browser(pw)
                page   = get_page(ctx_b)
                do_download(ctx_b, page, session, ffmpeg)
                ctx_b.close()

            show_completion(session)
            break

# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    main()
