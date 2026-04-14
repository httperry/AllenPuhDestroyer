@echo off
setlocal
title AllenPuhDestroyer — Build
cd /d "%~dp0"

echo.
echo  ╔═══════════════════════════════════════╗
echo  ║   AllenPuhDestroyer — EXE Builder     ║
echo  ╚═══════════════════════════════════════╝
echo.

:: ── Step 1: Install build dependencies ──────────────────────────────────────
echo [1/5] Installing build dependencies...
pip install pyinstaller --quiet
if errorlevel 1 ( echo ERROR: pip install failed & pause & exit /b 1 )

:: ── Step 2: Ensure Playwright Chromium is installed ──────────────────────────
echo [2/5] Ensuring Playwright Chromium is installed...
playwright install chromium
if errorlevel 1 ( echo ERROR: playwright install failed & pause & exit /b 1 )

:: ── Step 3: Ensure ffmpeg.exe is present to bundle ──────────────────────────
echo [3/5] Checking for ffmpeg...
if not exist "bin\ffmpeg.exe" (
    echo  ffmpeg not found — downloading portable build...
    python -c "from app_exe import download_ffmpeg; download_ffmpeg()"
    if errorlevel 1 ( echo ERROR: ffmpeg download failed & pause & exit /b 1 )
) else (
    echo  ffmpeg found: bin\ffmpeg.exe
)

:: ── Step 4: Build EXE ───────────────────────────────────────────────────────
echo [4/5] Building EXE ^(this takes 1-3 minutes^)...
pyinstaller AllenPuhDestroyer.spec --clean --noconfirm
if errorlevel 1 ( echo ERROR: PyInstaller build failed & pause & exit /b 1 )

:: ── Step 5: Done ─────────────────────────────────────────────────────────────
echo.
echo [5/5] Done!
echo.
echo  Output: dist\AllenPuhDestroyer.exe
for %%F in ("dist\AllenPuhDestroyer.exe") do echo  Size:   %%~zF bytes
echo.
echo  NOTE: Users without Playwright installed will see a one-time prompt to run:
echo        playwright install chromium
echo.
pause
