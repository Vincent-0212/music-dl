"""Shared helpers: config, folders, events, yt-dlp download wrapper, cancellation."""

import os
import re
import json
import sys
import shutil
import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Optional, List, Dict, Any

import yt_dlp

# When frozen by PyInstaller, the exe lives next to config.json / downloads.
# sys._MEIPASS is the read-only temp dir; sys.executable is the actual exe.
if getattr(sys, 'frozen', False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

CONFIG_PATH = os.path.join(BASE_DIR, "config.json")
SINGLES_FOLDER_NAME = "SINGLES"

DEFAULT_CONFIG = {
    "spotify": {"client_id": "", "client_secret": ""},
    "output_dir": BASE_DIR,
    "audio_quality": "320",
    "music_updater": True,
}


# ------------------------------------------------------------
# Cancellation
# ------------------------------------------------------------

class CancelledError(Exception):
    """Raised when the user cancels a running job."""
    pass


# ------------------------------------------------------------
# Config
# ------------------------------------------------------------

def load_config() -> dict:
    if not os.path.exists(CONFIG_PATH):
        return dict(DEFAULT_CONFIG)
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            cfg = json.load(f)
    except Exception:
        return dict(DEFAULT_CONFIG)
    merged = dict(DEFAULT_CONFIG)
    merged.update(cfg)
    if "spotify" not in merged or not isinstance(merged["spotify"], dict):
        merged["spotify"] = dict(DEFAULT_CONFIG["spotify"])
    return merged


def save_config(cfg: dict) -> None:
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


# ------------------------------------------------------------
# Filename / folder helpers
# ------------------------------------------------------------

def sanitize_filename(name: str) -> str:
    name = re.sub(r'[\\/:*?"<>|]', "_", name or "")
    name = name.strip(". ").strip()
    if not name:
        name = "untitled"
    return name[:200] if len(name) > 200 else name


def find_existing_playlist_folder(base_dir: str, playlist_name: str) -> Optional[str]:
    """Return the existing folder path for this playlist, or None.

    Matches:
      1. Exact sanitized name (new format)
      2. Legacy numbered format: NN_<sanitized name>
    """
    target = sanitize_filename(playlist_name)
    if not os.path.isdir(base_dir):
        return None
    # 1. Exact match
    exact = os.path.join(base_dir, target)
    if os.path.isdir(exact):
        return exact
    # 2. Numbered legacy match
    for entry in os.listdir(base_dir):
        m = re.match(r"^\d{2}_(.*)$", entry)
        if m and m.group(1) == target:
            full = os.path.join(base_dir, entry)
            if os.path.isdir(full):
                return full
    return None


def get_playlist_folder(base_dir: str, playlist_name: str, reuse_existing: bool) -> tuple:
    """Return (folder_name, folder_path, was_existing).

    If `reuse_existing` is True and a folder for this playlist already exists
    (new or legacy numbered format), reuse it. Otherwise create a fresh folder
    using the exact sanitized name (no numeric prefix).
    """
    sanitized = sanitize_filename(playlist_name)
    if reuse_existing:
        existing = find_existing_playlist_folder(base_dir, playlist_name)
        if existing:
            return os.path.basename(existing), existing, True
    folder_path = os.path.join(base_dir, sanitized)
    os.makedirs(folder_path, exist_ok=True)
    return sanitized, folder_path, False


def get_singles_folder(base_dir: str) -> str:
    path = os.path.join(base_dir, SINGLES_FOLDER_NAME)
    os.makedirs(path, exist_ok=True)
    return path


# ------------------------------------------------------------
# Existing tracks index (for incremental sync / music updater)
# ------------------------------------------------------------

def load_existing_track_ids(folder_path: str) -> set:
    """Return set of stable IDs already downloaded in this folder.

    Reads playlist_meta.json if present + scans mp3 filenames as fallback.
    """
    ids = set()
    meta_path = os.path.join(folder_path, "playlist_meta.json")
    if os.path.exists(meta_path):
        try:
            with open(meta_path, "r", encoding="utf-8") as f:
                meta = json.load(f)
            for t in meta.get("tracks", []):
                for key in ("spotify_id", "soundcloud_id", "youtube_id", "deezer_id"):
                    v = t.get(key)
                    if v:
                        ids.add(f"{key}:{v}")
        except Exception:
            pass
    return ids


def load_existing_filenames(folder_path: str) -> set:
    """Lowercase set of mp3 basenames already in the folder."""
    if not os.path.isdir(folder_path):
        return set()
    return {f.lower() for f in os.listdir(folder_path) if f.lower().endswith(".mp3")}


def track_id_key(track: dict) -> Optional[str]:
    for key in ("spotify_id", "soundcloud_id", "youtube_id"):
        v = track.get(key)
        if v:
            return f"{key}:{v}"
    return None


def merge_meta(folder_path: str, new_meta: dict) -> None:
    """Merge new tracks into existing playlist_meta.json (dedup by stable id)."""
    meta_path = os.path.join(folder_path, "playlist_meta.json")
    existing_meta = None
    if os.path.exists(meta_path):
        try:
            with open(meta_path, "r", encoding="utf-8") as f:
                existing_meta = json.load(f)
        except Exception:
            existing_meta = None

    if not existing_meta:
        save_playlist_meta(folder_path, new_meta)
        return

    seen = set()
    merged = []
    for t in existing_meta.get("tracks", []) + new_meta.get("tracks", []):
        k = track_id_key(t) or f"name:{t.get('title','')}:{t.get('artists_str','')}"
        if k in seen:
            continue
        seen.add(k)
        merged.append(t)

    out = dict(new_meta)
    out["tracks"] = merged
    out["track_count"] = len(merged)
    out["last_updated"] = datetime.now().isoformat()
    save_playlist_meta(folder_path, out)


def save_playlist_meta(folder_path: str, meta: dict) -> str:
    path = os.path.join(folder_path, "playlist_meta.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    return path


def log_failure(folder_path: str, track_info: dict, error_msg: str) -> None:
    log_path = os.path.join(folder_path, "failed_tracks.json")
    entry = {
        "timestamp": datetime.now().isoformat(),
        "title": track_info.get("title", "Unknown"),
        "artists": track_info.get("artists_str") or track_info.get("artists", "Unknown"),
        "spotify_id": track_info.get("spotify_id", ""),
        "spotify_url": track_info.get("spotify_url", ""),
        "soundcloud_url": track_info.get("soundcloud_url", ""),
        "youtube_url": track_info.get("youtube_url", ""),
        "yt_url": track_info.get("yt_url", ""),
        "error": error_msg,
    }
    existing = []
    if os.path.exists(log_path):
        try:
            with open(log_path, "r", encoding="utf-8") as f:
                existing = json.load(f)
        except Exception:
            existing = []
    existing.append(entry)
    with open(log_path, "w", encoding="utf-8") as f:
        json.dump(existing, f, ensure_ascii=False, indent=2)


# ------------------------------------------------------------
# Event bus
# ------------------------------------------------------------

@dataclass
class DownloadEvents:
    on_playlist_start: Optional[Callable[[str, str, int, str], None]] = None  # platform, name, total, folder_name
    on_resolve_progress: Optional[Callable[[int, int, str, bool], None]] = None
    on_track_start: Optional[Callable[[int, int, str], None]] = None
    on_track_progress: Optional[Callable[[int, float, str], None]] = None
    on_track_done: Optional[Callable[[int, bool, str], None]] = None
    on_track_skipped: Optional[Callable[[int, str], None]] = None
    on_playlist_done: Optional[Callable[[str, int, int, int], None]] = None  # folder, dl, total, skipped
    on_log: Optional[Callable[[str, str], None]] = None
    is_cancelled: Optional[Callable[[], bool]] = None

    def check_cancel(self):
        if self.is_cancelled and self.is_cancelled():
            raise CancelledError("Job cancelled by user")

    def playlist_start(self, platform, name, total, folder_name=""):
        self.check_cancel()
        if self.on_playlist_start:
            try: self.on_playlist_start(platform, name, total, folder_name)
            except Exception: pass

    def resolve_progress(self, idx, total, label, ok):
        if self.on_resolve_progress:
            try: self.on_resolve_progress(idx, total, label, ok)
            except Exception: pass

    def track_start(self, idx, total, label):
        if self.on_track_start:
            try: self.on_track_start(idx, total, label)
            except Exception: pass

    def track_progress(self, idx, pct, speed):
        if self.on_track_progress:
            try: self.on_track_progress(idx, pct, speed)
            except Exception: pass

    def track_done(self, idx, success, error=""):
        if self.on_track_done:
            try: self.on_track_done(idx, success, error)
            except Exception: pass

    def track_skipped(self, idx, reason):
        if self.on_track_skipped:
            try: self.on_track_skipped(idx, reason)
            except Exception: pass

    def playlist_done(self, folder_name, downloaded, total, skipped=0):
        if self.on_playlist_done:
            try: self.on_playlist_done(folder_name, downloaded, total, skipped)
            except Exception: pass

    def log(self, message, level="info"):
        if self.on_log:
            try: self.on_log(message, level)
            except Exception: pass
        try:
            print(message)
        except Exception:
            pass


@dataclass
class PlaylistResult:
    platform: str
    kind: str  # "playlist" | "track"
    playlist_name: str
    folder_name: str
    folder_path: str
    total: int
    downloaded: int
    skipped: int
    failed: int
    tracks: List[dict] = field(default_factory=list)


# ------------------------------------------------------------
# Audio download
# ------------------------------------------------------------

def download_audio(source_url: str, output_dir: str, filename: str,
                   track_num: int, total: int, events: DownloadEvents,
                   quality: str = "320") -> None:
    """Download one track. Raises CancelledError if cancelled mid-download."""

    def progress_hook(d):
        # Cancel check inside the hook (called by yt-dlp every chunk)
        if events.is_cancelled and events.is_cancelled():
            raise CancelledError("Cancelled")
        if d["status"] == "downloading":
            pct_str = (d.get("_percent_str") or "0%").strip()
            try:
                pct = float(re.sub(r"[^\d.]", "", pct_str) or "0")
            except Exception:
                pct = 0.0
            speed = (d.get("_speed_str") or "").strip()
            events.track_progress(track_num, pct, speed)
        elif d["status"] == "finished":
            events.track_progress(track_num, 100.0, "converting...")

    opts = {
        # Prefer m4a (always available on ios/android clients) then any audio stream.
        "format": "bestaudio[ext=m4a]/bestaudio/best",
        "outtmpl": os.path.join(output_dir, f"{filename}.%(ext)s"),
        "postprocessors": [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
            "preferredquality": str(quality),
        }],
        "progress_hooks": [progress_hook],
        "quiet": True,
        "no_warnings": True,
        # ios + android clients don't require a JS runtime AND have full
        # format access for music content. tv_embedded is an iframe client
        # with restricted format access for copyrighted music — avoid it.
        # (Ignored by yt-dlp for non-YouTube sources like SoundCloud.)
        "extractor_args": {"youtube": {"player_client": ["ios", "android"]}},
    }
    ffmpeg = get_bundled_ffmpeg()
    if ffmpeg:
        opts["ffmpeg_location"] = os.path.dirname(ffmpeg)
    with yt_dlp.YoutubeDL(opts) as ydl:
        ydl.download([source_url])


def get_bundled_ffmpeg() -> Optional[str]:
    """Return path to FFmpeg: bundled bundle > exe dir > PATH. Logs result."""
    candidates = []
    if getattr(sys, 'frozen', False):
        meipass = getattr(sys, '_MEIPASS', None)
        if meipass:
            candidates += [os.path.join(meipass, n) for n in ('ffmpeg.exe', 'ffmpeg')]
        exe_dir = os.path.dirname(sys.executable)
        candidates += [os.path.join(exe_dir, n) for n in ('ffmpeg.exe', 'ffmpeg')]
    path_ff = shutil.which('ffmpeg')
    if path_ff:
        candidates.append(path_ff)
    for p in candidates:
        if p and os.path.isfile(p):
            logging.info("ffmpeg resolved: %s", p)
            return p
    logging.error("ffmpeg NOT FOUND — candidates tried: %s", candidates)
    return None


def ensure_spotdlrip_on_path():
    if getattr(sys, 'frozen', False):
        sp_dir = os.path.join(sys._MEIPASS, "SpotdlRip")
    else:
        sp_dir = os.path.join(BASE_DIR, "SpotdlRip")
    if sp_dir not in sys.path:
        sys.path.insert(0, sp_dir)
