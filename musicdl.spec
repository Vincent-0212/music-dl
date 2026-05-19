# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec — Windows — MUSIC DL"""

import os
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

# ─── Data / binary / hiddenimport collection ───────────────────────────────────
datas = []
binaries = []
hiddenimports = []

# collect_all = data files + binaries + hidden imports for each package
for pkg in ('spotdl', 'ytmusicapi', 'yt_dlp', 'certifi', 'spotipy'):
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h

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
