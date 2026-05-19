# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec — macOS — MUSIC DL"""

import os
import re
from PyInstaller.utils.hooks import collect_all, collect_data_files, collect_submodules

block_cipher = None

# ─── FFmpeg binary — FAIL FAST if missing ────────────────────────────────────
if not os.path.exists('ffmpeg'):
    raise SystemExit(
        "ERROR: ffmpeg not found in project root.\n"
        "The CI must download it before running PyInstaller."
    )


# ─── Auto-discover all packages from requirements files ───────────────────────
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


_PIP_TO_IMPORT = {
    'pywebview': 'webview',
    'soundcloud-v2': 'soundcloud_v2',
    'beautifulsoup4': 'bs4',
    'python-dateutil': 'dateutil',
    'python-slugify': 'slugify',
    'python-multipart': 'multipart',
    'pyyaml': 'yaml',
    'pyinstaller': None,
    'pycryptodome': 'Crypto',
    'pycryptodomex': 'Cryptodome',
    'protobuf': 'google.protobuf',
}

_pip_pkgs = _read_req_pkgs('requirements.txt', 'SpotdlRip/requirements.txt')

datas = []
binaries = []
hiddenimports = []

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
        pass

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
    console=False,
    # icon='frontend/icon.icns',
)

app = BUNDLE(
    exe,
    name='MUSIC DL.app',
    icon=None,
    bundle_identifier='com.vincentd.musicdl',
    info_plist={
        'NSHighResolutionCapable': True,
        'NSMicrophoneUsageDescription': 'Not used.',
        'CFBundleShortVersionString': '1.0.1',
    },
)
