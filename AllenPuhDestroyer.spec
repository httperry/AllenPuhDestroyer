# AllenPuhDestroyer.spec
from PyInstaller.utils.hooks import collect_all, collect_data_files

datas, binaries, hiddenimports = [], [], []

# Collect all playwright internals (data + binaries + hidden imports)
tmp_d, tmp_b, tmp_h = collect_all('playwright')
datas         += tmp_d
binaries      += tmp_b
hiddenimports += tmp_h

# Collect InquirerPy data files (prompts, keybindings, etc.)
tmp_d, tmp_b, tmp_h = collect_all('InquirerPy')
datas         += tmp_d
binaries      += tmp_b
hiddenimports += tmp_h

# Bundle ffmpeg
datas += [('bin\\ffmpeg.exe', 'bin')]

a = Analysis(
    ['app_exe.py'],
    pathex=[],
    datas=datas,
    binaries=binaries,
    hiddenimports=hiddenimports + [
        'rich', 'rich.console', 'rich.panel', 'rich.table', 'rich.text',
        'rich.rule', 'rich.live', 'rich.columns', 'rich.progress', 'rich.box',
        'InquirerPy', 'InquirerPy.utils', 'InquirerPy.base.control',
        'InquirerPy.prompts.checkbox', 'InquirerPy.prompts.list',
        'InquirerPy.separator',
        'playwright.sync_api',
        'concurrent.futures', 'urllib.request', 'urllib.error', 'urllib.parse',
    ],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='AllenPuhDestroyer',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,          # keep console — it's a TUI app
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    onefile=True,
    icon='Assets\\Logo\\Allen_Puh_Destroyer_Icon.ico',
)
