# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec — macOS — MUSIC DL"""

import os
from PyInstaller.utils.hooks import collect_all, collect_data_files, collect_submodules

block_cipher = None

# ─── FFmpeg binary — FAIL FAST if missing ────────────────────────────────────
if not os.path.exists('ffmpeg'):
    raise SystemExit(
        "ERROR: ffmpeg not found in project root.\n"
        "The CI must download it before running PyInstaller."
    )

# ─── Data / binary / hiddenimport collection ──────────────────────────────────
datas = []
binaries = []
hiddenimports = []

for pkg in (
    'spotdl', 'ytmusicapi', 'yt_dlp', 'certifi', 'spotipy', 'tls_client',
    'pykakasi', 'syncedlyrics', 'soundcloud_v2',
):
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h

datas += collect_data_files('webview', subdir='js')
datas += collect_data_files('webview', subdir='lib')
datas += [('frontend', 'frontend')]
datas += [('SpotdlRip/spotdlrip.py', 'SpotdlRip')]
datas += [('platforms', 'platforms')]

binaries.append(('ffmpeg', '.'))

# ─── Hidden imports ───────────────────────────────────────────────────────────
hiddenimports += [
    'webview.platforms.cocoa',
    'objc',
    'Foundation', 'AppKit', 'WebKit',
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
    'yt_dlp', 'yt_dlp.postprocessor',
    'mutagen', 'mutagen.id3', 'mutagen.mp3',
    'aiohttp', 'aiohttp.resolver', 'aiohttp.connector',
    'certifi', 'charset_normalizer', 'urllib3',
    'pyotp',
    '_ssl', '_hashlib', '_socket',
]

# ─── Analysis ────────────────────────────────────────────────────────────────
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

_icns = 'frontend/icon.icns' if os.path.exists('frontend/icon.icns') else None

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='MusicDL',
    debug=False,
    strip=False,
    upx=False,
    console=False,
    icon=_icns,
)

app = BUNDLE(
    exe,
    name='MusicDL.app',
    icon=_icns,
    bundle_identifier='com.vincentd.musicdl',
    info_plist={
        'NSHighResolutionCapable': True,
        'NSMicrophoneUsageDescription': 'Not used.',
        'CFBundleShortVersionString': '2.0.0',
    },
)
