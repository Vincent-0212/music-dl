"""
gui.py — PyWebView GUI for MUSIC DL.

Native window hosting HTML/CSS/JS frontend with a Python API bridge.
"""

import os
import sys
import asyncio
import threading
import uuid
from typing import Dict, List

import webview

if getattr(sys, 'frozen', False):
    # Running as a PyInstaller bundle
    BASE_DIR = os.path.dirname(sys.executable)
    _BUNDLE_DIR = sys._MEIPASS
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    _BUNDLE_DIR = BASE_DIR

if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)
if _BUNDLE_DIR not in sys.path:
    sys.path.insert(0, _BUNDLE_DIR)

from platforms import (
    detect_platform, detect_kind, process_url, DownloadEvents,
    PLATFORM_LABELS, load_config, save_config,
)
from platforms.common import CancelledError
from platforms.spotify import build_spotify_client


FRONTEND_DIR = os.path.join(_BUNDLE_DIR, "frontend")


class Api:
    def __init__(self):
        self._progress: Dict[str, dict] = {}
        self._cancel_events: Dict[str, threading.Event] = {}
        self._spotify_client = None
        self._spotify_lock = threading.Lock()

    # --------- Config ---------

    def get_config(self):
        cfg = load_config()
        spo = cfg.get("spotify", {}) or {}
        return {
            "output_dir": cfg.get("output_dir", BASE_DIR),
            "audio_quality": cfg.get("audio_quality", "320"),
            "music_updater": bool(cfg.get("music_updater", True)),
            "spotify_configured": bool(spo.get("client_id") and spo.get("client_secret")),
            "spotify_client_id": spo.get("client_id", ""),
            # Secret is exposed only to this local UI (same machine, same process tree).
            "spotify_client_secret": spo.get("client_secret", ""),
        }

    def save_spotify_creds(self, client_id: str, client_secret: str):
        cfg = load_config()
        cfg["spotify"] = {
            "client_id": (client_id or "").strip(),
            "client_secret": (client_secret or "").strip(),
        }
        save_config(cfg)
        with self._spotify_lock:
            self._spotify_client = None
        return {"ok": True, "configured": bool(cfg["spotify"]["client_id"] and cfg["spotify"]["client_secret"])}

    def clear_spotify_creds(self):
        cfg = load_config()
        cfg["spotify"] = {"client_id": "", "client_secret": ""}
        save_config(cfg)
        with self._spotify_lock:
            self._spotify_client = None
        return {"ok": True}

    def set_music_updater(self, enabled: bool):
        cfg = load_config()
        cfg["music_updater"] = bool(enabled)
        save_config(cfg)
        return {"ok": True, "music_updater": cfg["music_updater"]}

    def update_settings(self, audio_quality: str = None, output_dir: str = None):
        cfg = load_config()
        if audio_quality:
            cfg["audio_quality"] = str(audio_quality)
        if output_dir:
            cfg["output_dir"] = output_dir
        save_config(cfg)
        return {"ok": True}

    def open_url(self, url: str):
        import webbrowser
        webbrowser.open(url)
        return {"ok": True}

    def pick_folder(self):
        try:
            result = webview.windows[0].create_file_dialog(webview.FOLDER_DIALOG)
        except Exception:
            result = None
        if result:
            path = result[0] if isinstance(result, (list, tuple)) else result
            cfg = load_config()
            cfg["output_dir"] = path
            save_config(cfg)
            return {"ok": True, "path": path}
        return {"ok": False}

    # --------- Detection ---------

    def detect_url(self, url: str):
        p = detect_platform(url)
        k = detect_kind(url) if p else None
        return {
            "platform": p,
            "kind": k,
            "label": PLATFORM_LABELS.get(p, ""),
        }

    # --------- Downloads ---------

    def start_downloads(self, urls: List[str]):
        cfg = load_config()
        spotify_needed = any(detect_platform(u) == "spotify" for u in urls)
        spo = cfg.get("spotify", {})
        if spotify_needed and not (spo.get("client_id") and spo.get("client_secret")):
            return {"ok": False, "error": "Spotify credentials are missing. Open Settings."}

        jobs = []
        for url in urls:
            if not url or not url.strip():
                continue
            platform = detect_platform(url)
            if platform is None:
                continue
            kind = detect_kind(url) or "playlist"
            job_id = str(uuid.uuid4())[:8]

            self._cancel_events[job_id] = threading.Event()
            self._progress[job_id] = {
                "job_id": job_id,
                "url": url,
                "platform": platform,
                "platform_label": PLATFORM_LABELS.get(platform, platform),
                "kind": kind,
                "status": "queued",
                "playlist_name": "",
                "folder_name": "",
                "total": 0,
                "resolved": 0,
                "resolved_failed": 0,
                "current_idx": 0,
                "current_label": "",
                "current_pct": 0.0,
                "current_speed": "",
                "downloaded": 0,
                "skipped": 0,
                "failed": 0,
                "log": [],
                "done": False,
                "cancelled": False,
                "error_message": "",
            }
            jobs.append({"job_id": job_id, "url": url, "platform": platform, "kind": kind})
            t = threading.Thread(target=self._run_job, args=(job_id, url, cfg), daemon=True)
            t.start()

        return {"ok": True, "jobs": jobs}

    def cancel_job(self, job_id: str):
        ev = self._cancel_events.get(job_id)
        if ev:
            ev.set()
            state = self._progress.get(job_id)
            if state:
                state["status"] = "cancelling"
        return {"ok": bool(ev)}

    def dismiss_job(self, job_id: str):
        self._progress.pop(job_id, None)
        self._cancel_events.pop(job_id, None)
        return {"ok": True}

    def clear_completed(self):
        keep = {}
        keep_evs = {}
        for k, v in self._progress.items():
            if not v.get("done"):
                keep[k] = v
                if k in self._cancel_events:
                    keep_evs[k] = self._cancel_events[k]
        self._progress = keep
        self._cancel_events = keep_evs
        return {"ok": True}

    def get_progress(self):
        return list(self._progress.values())

    # --------- Internals ---------

    def _run_job(self, job_id: str, url: str, cfg: dict):
        state = self._progress[job_id]
        cancel_ev = self._cancel_events[job_id]
        state["status"] = "running"

        def on_playlist_start(platform, name, total, folder_name):
            state["playlist_name"] = name
            state["total"] = total
            state["folder_name"] = folder_name
            state["status"] = "resolving" if platform == "spotify" and state["kind"] == "playlist" else "downloading"

        def on_resolve_progress(idx, total, label, ok):
            state["resolved"] = idx
            if not ok:
                state["resolved_failed"] = state.get("resolved_failed", 0) + 1
            state["current_label"] = label

        def on_track_start(idx, total, label):
            state["status"] = "downloading"
            state["current_idx"] = idx
            state["current_label"] = label
            state["current_pct"] = 0.0
            state["current_speed"] = ""

        def on_track_progress(idx, pct, speed):
            state["current_idx"] = idx
            state["current_pct"] = pct
            state["current_speed"] = speed

        def on_track_done(idx, success, error):
            if success:
                state["downloaded"] = state.get("downloaded", 0) + 1
            else:
                state["failed"] = state.get("failed", 0) + 1
                state["log"].append({"level": "error", "msg": f"Track {idx}: {error}"})
            state["current_pct"] = 100.0
            state["current_speed"] = ""

        def on_playlist_done(folder_name, downloaded, total, skipped):
            state["folder_name"] = folder_name
            state["downloaded"] = downloaded
            state["skipped"] = skipped
            state["status"] = "done"
            state["done"] = True

        def on_log(msg, level):
            state["log"].append({"level": level, "msg": msg})

        events = DownloadEvents(
            on_playlist_start=on_playlist_start,
            on_resolve_progress=on_resolve_progress,
            on_track_start=on_track_start,
            on_track_progress=on_track_progress,
            on_track_done=on_track_done,
            on_playlist_done=on_playlist_done,
            on_log=on_log,
            is_cancelled=lambda: cancel_ev.is_set(),
        )

        sp = None
        if detect_platform(url) == "spotify":
            with self._spotify_lock:
                if self._spotify_client is None:
                    try:
                        state["log"].append({"level": "info", "msg": "Connexion Spotify..."})
                        spo = cfg.get("spotify", {})
                        self._spotify_client = build_spotify_client(spo["client_id"], spo["client_secret"])
                    except Exception as e:
                        state["error_message"] = f"OAuth Spotify a echoue: {e}"
                        state["log"].append({"level": "error", "msg": state["error_message"]})
                        state["status"] = "error"
                        state["done"] = True
                        return
                sp = self._spotify_client

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result = loop.run_until_complete(process_url(url, events, cfg, spotify_client=sp))
            # If process_url returned None (e.g. yt-dlp couldn't extract info),
            # the job must still be marked done so the GUI doesn't hang.
            if result is None and not state.get("done"):
                state["status"] = "error"
                state["error_message"] = state.get("error_message") or "Aucune information récupérée (URL invalide ou inaccessible)."
                state["done"] = True
        except CancelledError:
            state["cancelled"] = True
            state["status"] = "cancelled"
            state["done"] = True
            state["log"].append({"level": "warn", "msg": "Cancelled by user."})
        except Exception as e:
            state["error_message"] = str(e)
            state["log"].append({"level": "error", "msg": f"Exception: {e}"})
            state["status"] = "error"
            state["done"] = True
        finally:
            try:
                loop.close()
            except Exception:
                pass


def main():
    api = Api()
    index_path = os.path.join(FRONTEND_DIR, "index.html")
    webview.create_window(
        title="MUSIC DL",
        url=index_path,
        js_api=api,
        width=1100,
        height=820,
        min_size=(880, 640),
        background_color="#faf8f5",
    )
    webview.start(debug=False)


if __name__ == "__main__":
    main()
