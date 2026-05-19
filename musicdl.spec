# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec — Windows — MUSIC DL"""

import os
import re
import sys
from PyInstaller.utils.hooks import collect_all, collect_data_files, collect_submodules

block_cipher = None

# ─── FFmpeg binary — FAIL FAST if missing (CI must download it first) ──────────
if not os.path.exists('ffmpeg.exe'):
    raise SystemExit(
        "ERROR: ffmpeg.exe not found in project root.\n"
        "The CI must download it before running PyInstaller.\n"
        "Run the GitHub workflow, or manually place ffmpeg.exe here."
    )


# ─── Auto-discover all packages from requirements files ───────────────────────
# Instead of maintaining a manual list (and chasing each missing data file one
# at a time), enumerate every package declared in our requirements files and
# call collect_all on each. This bundles data files (DBs, JSON, templates,
# native DLLs) for every direct dep transparently.

def _read_req_pkgs(*paths):
    pkgs = []
    for path in paths:
        if not os.path.exists(path):
            continue
        with open(path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.split('#', 1)[0].strip()
                if not line:
                    continue
                m = re.match(r'^([A-Za-z0-9_.\-]+)', line)
                if m:
                    pkgs.append(m.group(1).lower())
    return list(dict.fromkeys(pkgs))


# Map PyPI dist names → Python import names (only for ones that differ)
_PIP_TO_IMPORT = {
    'pywebview': 'webview',
    'soundcloud-v2': 'soundcloud_v2',
    'beautifulsoup4': 'bs4',
    'python-dateutil': 'dateutil',
    'python-slugify': 'slugify',
    'python-multipart': 'multipart',
    'pyyaml': 'yaml',
    'pyinstaller': None,           # build tool, not a runtime dep
    'pycryptodome': 'Crypto',
    'pycryptodomex': 'Cryptodome',
    'protobuf': 'google.protobuf',
}

_pip_pkgs = _read_req_pkgs('requirements.txt', 'SpotdlRip/requirements.txt')

datas = []
binaries = []
hiddenimports = []

# Bulletproof collect_all loop: every package from requirements gets its
# data files + binaries + submodules included. Single-file modules emit a
# harmless "not a package" warning — we don't care.
for _pip_name in _pip_pkgs:
    if _pip_name in _PIP_TO_IMPORT:
        _import_name = _PIP_TO_IMPORT[_pip_name]
        if _import_name is None:
            continue
    else:
        _import_name = _pip_name.replace('-', '_')
    try:
        _d, _b, _h = collect_all(_import_name)
        datas += _d
        binaries += _b
        hiddenimports += _h
    except Exception:
        pass  # not installed or not collectable — non-fatal

# pywebview backends (Windows: winforms + edge)
datas += collect_data_files('webview', subdir='js')
datas += collect_data_files('webview', subdir='lib')

# App assets
datas += [('frontend', 'frontend')]
datas += [('SpotdlRip/spotdlrip.py', 'SpotdlRip')]
datas += [('platforms', 'platforms')]

# FFmpeg bundled binary
binaries.append(('ffmpeg.exe', '.'))

# ─── Hidden imports ─────────────────────────────────────────────────────────────
hiddenimports += [
    # pywebview Windows backends
    'webview.platforms.winforms',
    'webview.platforms.edgechromium',
    'clr',
    # spotdl audio/lyrics providers (loaded lazily by spotdl)
    'tls_client',
    'spotdl.providers.audio.youtube',
    'spotdl.providers.audio.ytmusic',
    'spotdl.providers.audio.soundcloud',
    'spotdl.providers.audio.bandcamp',
    'spotdl.providers.audio.piped',
    'spotdl.providers.lyrics.genius',
    'spotdl.providers.lyrics.azlyrics',
    'spotdl.providers.lyrics.musixmatch',
    'spotdl.providers.lyrics.synced',
    # yt-dlp
    'yt_dlp', 'yt_dlp.postprocessor',
    # audio metadata
    'mutagen', 'mutagen.id3', 'mutagen.mp3',
    # network
    'aiohttp', 'aiohttp.resolver', 'aiohttp.connector',
    'certifi', 'charset_normalizer', 'urllib3',
    # other
    'pyotp',
    # SSL (sometimes missing in frozen builds)
    '_ssl', '_hashlib', '_socket',
]

# ─── Analysis ──────────────────────────────────────────────────────────────────
a = Analysis(
    ['gui.py'],
    pathex=['.', 'SpotdlRip'],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=['matplotlib', 'numpy', 'pandas', 'PIL', 'tkinter', 'PyQt5', 'PyQt6', 'wx', 'pytest'],
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='MUSIC DL',
    debug=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    # icon='frontend/icon.ico',
)
