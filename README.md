# MUSIC DL

Bulk playlist downloader with a minimalist desktop GUI. Supports Spotify, SoundCloud, and YouTube. Downloads MP3 at 320 kbps.

---

## Features

- **Multi-platform** — Spotify playlists & tracks, SoundCloud sets & tracks, YouTube playlists & videos
- **Pipelined download** — resolve and download concurrently (2 workers) for maximum speed
- **Music Updater** — incremental sync: skip already-downloaded tracks on re-run
- **Single tracks** — non-playlist links go to a `SINGLES/` folder
- **Cancel anytime** — per-job cancel button in the GUI
- **One-click launch** — `MUSIC DL.bat` opens the GUI directly

---

## Installation

### 1. Clone

```bash
git clone https://github.com/YOUR_USERNAME/DL_MUSIC.git
cd DL_MUSIC
```

### 2. Install dependencies

```bash
pip install -r requirements.txt -r SpotdlRip/requirements.txt
```

> Requires Python 3.10+ and [FFmpeg](https://ffmpeg.org/download.html) on PATH.

### 3. Configure

Copy the example config and fill in your values:

```bash
cp config.example.json config.json
```

Edit `config.json`:

```json
{
  "spotify": {
    "client_id": "YOUR_SPOTIFY_CLIENT_ID",
    "client_secret": "YOUR_SPOTIFY_CLIENT_SECRET"
  },
  "output_dir": "C:/Users/YOU/Desktop/DL_MUSIC",
  "audio_quality": "320",
  "music_updater": true
}
```

> Get Spotify credentials at [developer.spotify.com](https://developer.spotify.com/dashboard).  
> Set the redirect URI to `http://127.0.0.1:8888/callback` in your app settings.

---

## Usage

### GUI (recommended)

Double-click `MUSIC DL.bat` or run:

```bash
pythonw gui.py
```

### CLI

```bash
python DL.py <url1> [url2] [url3] ...

# Examples
python DL.py https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M
python DL.py https://soundcloud.com/user/sets/my-playlist
python DL.py https://www.youtube.com/playlist?list=PLxxxxxxx
```

---

## Project structure

```
DL_MUSIC/
├── gui.py                  # PyWebView desktop app
├── DL.py                   # CLI entry point
├── MUSIC DL.bat            # One-click Windows launcher
├── SPOT.py                 # Legacy Spotify metadata tool
├── config.json             # ← NOT in Git (add your own)
├── config.example.json     # Template
├── requirements.txt
├── platforms/
│   ├── __init__.py         # Platform detection + dispatcher
│   ├── common.py           # Shared utilities, DownloadEvents
│   ├── spotify.py          # Spotify OAuth + pipeline
│   ├── soundcloud.py       # SoundCloud via yt-dlp
│   └── youtube.py          # YouTube via yt-dlp
├── SpotdlRip/
│   ├── spotdlrip.py        # Spotify → YouTube Music resolver
│   └── requirements.txt
└── frontend/
    ├── index.html
    ├── styles.css
    └── app.js
```

---

## Spotify setup

1. Go to [Spotify Developer Dashboard](https://developer.spotify.com/dashboard)
2. Create an app
3. Add `http://127.0.0.1:8888/callback` as a Redirect URI
4. Copy Client ID and Client Secret into `config.json` (or via the Settings panel in the GUI)

---

## License

MIT
