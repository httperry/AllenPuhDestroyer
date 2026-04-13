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
echo [1/4] Installing build dependencies...
pip install pyinstaller --quiet
if errorlevel 1 ( echo ERROR: pip install failed & pause & exit /b 1 )

:: ── Step 2: Ensure ffmpeg.exe is present to bundle ──────────────────────────
echo [2/4] Checking for ffmpeg...
if not exist "bin\ffmpeg.exe" (
    echo  ffmpeg not found — downloading portable build...
    python -c "from app import download_ffmpeg; download_ffmpeg()"
    if errorlevel 1 ( echo ERROR: ffmpeg download failed & pause & exit /b 1 )
) else (
    echo  ffmpeg found: bin\ffmpeg.exe
)

:: ── Step 3: Build EXE ───────────────────────────────────────────────────────
echo [3/4] Building EXE ^(this takes 1-3 minutes^)...
pyinstaller AllenPuhDestroyer.spec --clean --noconfirm
if errorlevel 1 ( echo ERROR: PyInstaller build failed & pause & exit /b 1 )

:: ── Step 4: Done ─────────────────────────────────────────────────────────────
echo.
echo [4/4] Done!
echo.
echo  Output: dist\AllenPuhDestroyer.exe
for %%F in ("dist\AllenPuhDestroyer.exe") do echo  Size:   %%~zF bytes
echo.
echo  NOTE: On first run the EXE will auto-download Chromium (~120 MB, one-time).
echo.
pause
