# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for MUSIC DL
Entry point : gui.py
"""

import os
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

block_cipher = None

# ─── Data files to bundle ────────────────────────────────────────────────────

datas = []

# pywebview JS glue + Windows native lib
datas += collect_data_files('webview', subdir='js')
datas += collect_data_files('webview', subdir='lib')

# spotdl needs its own data (cookie templates, etc.)
datas += collect_data_files('spotdl')

# ytmusicapi data files
datas += collect_data_files('ytmusicapi')

# Frontend (HTML/CSS/JS)
datas += [('frontend', 'frontend')]

# SpotdlRip resolver
datas += [('SpotdlRip/spotdlrip.py', 'SpotdlRip')]

# platforms package
datas += [('platforms', 'platforms')]

# ─── Hidden imports ───────────────────────────────────────────────────────────

hiddenimports = [
    # pywebview backends
    'webview.platforms.winforms',
    'webview.platforms.edgechromium',
    # clr / pythonnet for winforms backend
    'clr',
    # spotipy
    'spotipy',
    'spotipy.oauth2',
    # spotdl internals used by SpotdlRip
    'spotdl.providers.audio.ytmusic',
    'spotdl.types.song',
    # ytmusicapi
    'ytmusicapi',
    # aiohttp
    'aiohttp',
    'aiohttp.resolver',
    'aiohttp.connector',
    # pyotp
    'pyotp',
    # yt-dlp
    'yt_dlp',
    'yt_dlp.postprocessor',
    # mutagen tags
    'mutagen',
    'mutagen.id3',
    'mutagen.mp3',
    # misc
    'certifi',
    'charset_normalizer',
    'urllib3',
]

hiddenimports += collect_submodules('yt_dlp')
hiddenimports += collect_submodules('spotdl')

# ─── Analysis ─────────────────────────────────────────────────────────────────

a = Analysis(
    ['gui.py'],
    pathex=['.', 'SpotdlRip'],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Heavy unused packages
        'matplotlib', 'numpy', 'pandas', 'PIL', 'tk', 'tkinter',
        'PyQt5', 'PyQt6', 'wx',
        # Test frameworks
        'pytest', 'unittest',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

# ─── One-file EXE ─────────────────────────────────────────────────────────────

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='MUSIC DL',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,          # No console window (GUI app)
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    # icon='frontend/icon.ico',   # Uncomment if you add an icon
)
