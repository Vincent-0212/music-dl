# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec — macOS — MUSIC DL"""

import os
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

block_cipher = None

# ─── Data files ───────────────────────────────────────────────────────────────
datas = []
datas += collect_data_files('webview', subdir='js')
datas += collect_data_files('spotdl')
datas += collect_data_files('ytmusicapi')
datas += [('frontend', 'frontend')]
datas += [('SpotdlRip/spotdlrip.py', 'SpotdlRip')]
datas += [('platforms', 'platforms')]

# ─── FFmpeg binary (downloaded by CI to project root before build) ─────────────
binaries = []
if os.path.exists('ffmpeg'):
    binaries.append(('ffmpeg', '.'))

# ─── Hidden imports ────────────────────────────────────────────────────────────
hiddenimports = [
    'webview.platforms.cocoa',
    'objc',
    'Foundation', 'AppKit', 'WebKit',
    'spotipy', 'spotipy.oauth2',
    'spotdl.providers.audio.ytmusic', 'spotdl.types.song',
    'ytmusicapi',
    'aiohttp', 'aiohttp.resolver', 'aiohttp.connector',
    'pyotp',
    'yt_dlp', 'yt_dlp.postprocessor',
    'mutagen', 'mutagen.id3', 'mutagen.mp3',
    'certifi', 'charset_normalizer', 'urllib3',
]
hiddenimports += collect_submodules('yt_dlp')
hiddenimports += collect_submodules('spotdl')

# ─── Analysis ─────────────────────────────────────────────────────────────────
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
    upx=False,          # UPX not recommended on macOS
    console=False,
    # icon='frontend/icon.icns',
)

# macOS .app bundle
app = BUNDLE(
    exe,
    name='MUSIC DL.app',
    icon=None,          # replace with 'frontend/icon.icns' if you add one
    bundle_identifier='com.vincentd.musicdl',
    info_plist={
        'NSHighResolutionCapable': True,
        'NSMicrophoneUsageDescription': 'Not used.',
        'CFBundleShortVersionString': '1.0.1',
    },
)
