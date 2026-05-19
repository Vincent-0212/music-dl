"""Spotify pipeline: OAuth → metadata → YT Music resolution → download.

Supports both playlists and single tracks. Implements incremental sync
(music_updater) by reusing existing folders and skipping already-present tracks.
"""

import os
import asyncio
import threading
import webbrowser
from functools import partial
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

import spotipy
from spotipy.oauth2 import SpotifyOAuth

from .common import (
    BASE_DIR, DownloadEvents, PlaylistResult, CancelledError,
    sanitize_filename, get_playlist_folder, get_singles_folder,
    load_existing_track_ids, load_existing_filenames, track_id_key,
    log_failure, download_audio, save_playlist_meta, merge_meta,
    ensure_spotdlrip_on_path,
)

REDIRECT_URI = "http://127.0.0.1:8888/callback"
SCOPE = "playlist-read-private playlist-read-collaborative"


# ------------------------------------------------------------
# OAuth
# ------------------------------------------------------------

_captured_code = None
_code_event = threading.Event()


class _OAuthCallbackHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        global _captured_code
        query = parse_qs(urlparse(self.path).query)
        if "code" in query:
            _captured_code = query["code"][0]
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(
                b"<!doctype html><html><body style='font-family:system-ui;"
                b"text-align:center;padding:80px;background:#faf8f5;color:#1a1a1a'>"
                b"<h2 style='font-weight:400'>Autorisation reussie</h2>"
                b"<p style='color:#8a8680'>Tu peux fermer cet onglet.</p></body></html>"
            )
            _code_event.set()
        else:
            self.send_response(400)
            self.end_headers()

    def log_message(self, *args):
        pass


def _capture_oauth_code(auth_url: str, timeout: int = 120) -> str:
    _code_event.clear()
    server = HTTPServer(("127.0.0.1", 8888), _OAuthCallbackHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    webbrowser.open(auth_url)
    try:
        if not _code_event.wait(timeout=timeout):
            raise TimeoutError("Timeout: pas de callback Spotify recu")
        return _captured_code
    finally:
        server.shutdown()


def build_spotify_client(client_id: str, client_secret: str) -> spotipy.Spotify:
    cache_path = os.path.join(BASE_DIR, ".cache")
    if os.path.exists(cache_path):
        os.remove(cache_path)
    auth_manager = SpotifyOAuth(
        client_id=client_id,
        client_secret=client_secret,
        redirect_uri=REDIRECT_URI,
        scope=SCOPE,
        open_browser=False,
        cache_path=cache_path,
    )
    code = _capture_oauth_code(auth_manager.get_authorize_url())
    token_info = auth_manager.get_access_token(code)
    access_token = token_info["access_token"] if isinstance(token_info, dict) else token_info
    return spotipy.Spotify(auth=access_token)


# ------------------------------------------------------------
# URL parsing
# ------------------------------------------------------------

def _extract_playlist_id(url: str) -> str:
    if "spotify.com/playlist/" in url:
        return url.split("spotify.com/playlist/")[1].split("?")[0].split("/")[0]
    if url.startswith("spotify:playlist:"):
        return url.split(":")[-1]
    return url


def _extract_track_id(url: str) -> str:
    if "spotify.com/track/" in url:
        return url.split("spotify.com/track/")[1].split("?")[0].split("/")[0]
    if url.startswith("spotify:track:"):
        return url.split(":")[-1]
    return url


def _extract_album_id(url: str) -> str:
    if "spotify.com/album/" in url:
        return url.split("spotify.com/album/")[1].split("?")[0].split("/")[0]
    if url.startswith("spotify:album:"):
        return url.split(":")[-1]
    return url


# ------------------------------------------------------------
# Playlist fetch
# ------------------------------------------------------------

def _fetch_playlist(sp, playlist_id: str):
    name = sp.playlist(playlist_id, fields="name")["name"]
    tracks = []
    results = sp.playlist_tracks(playlist_id)
    while results:
        for item in results.get("items", []):
            t = item.get("track") or item.get("item")
            if not t or not t.get("id"):
                continue
            artists = [a["name"] for a in t.get("artists", [])]
            tracks.append({
                "title": t.get("name", ""),
                "artists": artists,
                "artists_str": ", ".join(artists),
                "album": t.get("album", {}).get("name", ""),
                "release_date": t.get("album", {}).get("release_date", ""),
                "duration_ms": t.get("duration_ms", 0),
                "spotify_url": t.get("external_urls", {}).get("spotify", ""),
                "spotify_id": t.get("id", ""),
            })
        results = sp.next(results) if results.get("next") else None
    return name, tracks


def _fetch_album(sp, album_id: str):
    """Fetch album metadata and its full track list."""
    album = sp.album(album_id)
    album_name = album.get("name", "")
    album_artist = album.get("artists", [{}])[0].get("name", "Unknown")
    release_date = album.get("release_date", "")

    tracks = []
    results = sp.album_tracks(album_id)
    while results:
        for t in results.get("items", []):
            if not t or not t.get("id"):
                continue
            artists = [a["name"] for a in t.get("artists", [])]
            tracks.append({
                "title": t.get("name", ""),
                "artists": artists,
                "artists_str": ", ".join(artists),
                "album": album_name,
                "release_date": release_date,
                "duration_ms": t.get("duration_ms", 0),
                "spotify_url": t.get("external_urls", {}).get("spotify", ""),
                "spotify_id": t.get("id", ""),
            })
        results = sp.next(results) if results.get("next") else None

    folder_name = f"{album_artist} - {album_name}"
    return folder_name, tracks


def _fetch_track(sp, track_id: str) -> dict:
    t = sp.track(track_id)
    artists = [a["name"] for a in t.get("artists", [])]
    return {
        "title": t.get("name", ""),
        "artists": artists,
        "artists_str": ", ".join(artists),
        "album": t.get("album", {}).get("name", ""),
        "release_date": t.get("album", {}).get("release_date", ""),
        "duration_ms": t.get("duration_ms", 0),
        "spotify_url": t.get("external_urls", {}).get("spotify", ""),
        "spotify_id": t.get("id", ""),
    }


# ------------------------------------------------------------
# YT Music resolution + download pipeline
#
# Producer/consumer pattern: as each track is resolved to a YT Music URL,
# it is pushed into a queue. Two download workers pull from the queue and
# run download_audio() concurrently via the default thread pool executor.
# This pipelines resolution and downloading instead of running them in
# sequential phases — roughly cuts total wall-clock time on large playlists.
# ------------------------------------------------------------

NUM_DOWNLOAD_WORKERS = 2
QUEUE_BUFFER = 8


# ------------------------------------------------------------
# Playlist pipeline
# ------------------------------------------------------------

async def _ensure_client(config: dict, sp, events: DownloadEvents):
    if sp is not None:
        return sp
    creds = config.get("spotify", {})
    cid = creds.get("client_id", "")
    secret = creds.get("client_secret", "")
    if not cid or not secret:
        raise RuntimeError("Spotify credentials are missing.")
    events.log("Connexion Spotify...")
    return build_spotify_client(cid, secret)


async def process(url: str, events: DownloadEvents, config: dict, sp=None) -> PlaylistResult:
    sp = await _ensure_client(config, sp, events)

    playlist_id = _extract_playlist_id(url)
    events.log(f"Recuperation playlist Spotify {playlist_id}...")
    events.check_cancel()
    name, tracks = _fetch_playlist(sp, playlist_id)
    total_remote = len(tracks)

    output_dir = config.get("output_dir", BASE_DIR)
    music_updater = bool(config.get("music_updater", True))
    folder_name, folder_path, was_existing = get_playlist_folder(output_dir, name, reuse_existing=music_updater)
    events.playlist_start("spotify", name, total_remote, folder_name)

    if not tracks:
        events.log("Playlist vide.", level="warn")
        events.playlist_done(folder_name, 0, 0, 0)
        return PlaylistResult("spotify", "playlist", name, folder_name, folder_path, 0, 0, 0, 0, [])

    # Incremental sync: filter out already-downloaded tracks
    existing_ids = load_existing_track_ids(folder_path) if music_updater else set()
    existing_files = load_existing_filenames(folder_path) if music_updater else set()

    to_resolve = []
    skipped_count = 0
    for t in tracks:
        key = track_id_key(t)
        artist0 = t["artists"][0] if t.get("artists") else "Unknown"
        expected_file = sanitize_filename(f"{artist0} - {t['title']}") + ".mp3"
        if music_updater and (
            (key and key in existing_ids) or expected_file.lower() in existing_files
        ):
            skipped_count += 1
            continue
        to_resolve.append(t)

    if was_existing and music_updater:
        events.log(f"Updater: {skipped_count} deja present, {len(to_resolve)} a telecharger")

    if not to_resolve:
        events.log("Tout est deja telecharge.")
        events.playlist_done(folder_name, 0, total_remote, skipped_count)
        return PlaylistResult("spotify", "playlist", name, folder_name, folder_path,
                              total_remote, 0, skipped_count, 0, tracks)

    save_playlist_meta(folder_path, {
        "platform": "spotify",
        "playlist_name": name,
        "playlist_id": playlist_id,
        "playlist_url": url,
        "track_count": total_remote,
        "tracks": tracks,
    })

    events.log(f"Pipeline resolve+download ({len(to_resolve)} tracks, {NUM_DOWNLOAD_WORKERS} workers)...")

    quality = config.get("audio_quality", "320")
    total_to_process = len(to_resolve)
    queue: asyncio.Queue = asyncio.Queue(maxsize=QUEUE_BUFFER)
    counters = {"downloaded": 0, "failed": 0, "resolve_failed": 0, "dl_index": 0}

    # Initialize SpotdlRip once, shared by all resolver coroutines.
    # If Spotify rotated its TOTP key (happens periodically), initialization
    # fails gracefully and we fall back to yt-dlp YouTube search per track.
    ensure_spotdlrip_on_path()
    from spotdlrip import SpotdlRip
    rip = None
    try:
        _rip = SpotdlRip(logs=False)
        await _rip.initialize()
        rip = _rip
    except Exception as _init_err:
        events.log(
            f"SpotdlRip indisponible ({_init_err}) — recherche YouTube activee en fallback.",
            level="warn",
        )

    resolver_sem = asyncio.Semaphore(3)

    async def resolve_one(track, idx):
        """Resolve one track; falls back to YouTube search if SpotdlRip is down."""
        async with resolver_sem:
            events.check_cancel()
            label = f"{track['artists_str']} - {track['title']}"
            yt_url = None

            # Primary: SpotdlRip → YouTube Music (most accurate match)
            if rip is not None:
                try:
                    yt_url = await rip.spotify_to_ytmusic(track_id=track["spotify_id"], only_verified=True)
                    if not yt_url:
                        yt_url = await rip.spotify_to_ytmusic(track_id=track["spotify_id"], only_verified=False)
                except CancelledError:
                    raise
                except Exception as e:
                    events.log(f"SpotdlRip [{label}]: {e}", level="warn")

            # Fallback: yt-dlp YouTube search (always works)
            if not yt_url:
                yt_url = f"ytsearch1:{label}"

            track["yt_url"] = yt_url
            events.resolve_progress(idx + 1, total_to_process, label, True)
            await queue.put(track)

    async def producer():
        """Run all resolutions concurrently, then push N sentinels to stop workers."""
        try:
            await asyncio.gather(*(resolve_one(t, i) for i, t in enumerate(to_resolve)))
        finally:
            for _ in range(NUM_DOWNLOAD_WORKERS):
                await queue.put(None)

    async def downloader(worker_id: int):
        """Consume resolved tracks and download in parallel via thread pool."""
        loop = asyncio.get_running_loop()
        while True:
            track = await queue.get()
            if track is None:
                return

            try:
                events.check_cancel()
            except CancelledError:
                # Drain queue (without blocking the producer) and exit
                while True:
                    t = await queue.get()
                    if t is None:
                        break
                raise

            counters["dl_index"] += 1
            idx = counters["dl_index"]
            artist = track["artists"][0] if track["artists"] else "Unknown"
            filename = sanitize_filename(f"{artist} - {track['title']}")
            mp3_path = os.path.join(folder_path, f"{filename}.mp3")
            label = f"{artist} - {track['title']}"

            events.track_start(idx, total_to_process, label)

            if os.path.exists(mp3_path):
                events.track_done(idx, True, "already present")
                counters["downloaded"] += 1
                continue

            try:
                await loop.run_in_executor(
                    None,
                    partial(download_audio, track["yt_url"], folder_path, filename,
                            idx, total_to_process, events, quality),
                )
                events.track_done(idx, True)
                counters["downloaded"] += 1
            except CancelledError:
                raise
            except Exception as e:
                log_failure(folder_path, track, f"Echec yt-dlp: {e}")
                events.track_done(idx, False, str(e))
                counters["failed"] += 1

    # Run producer + N consumers concurrently
    await asyncio.gather(
        producer(),
        *(downloader(i) for i in range(NUM_DOWNLOAD_WORKERS)),
    )

    downloaded = counters["downloaded"]
    failed = counters["failed"] + counters["resolve_failed"]

    # Update meta with merged tracks (preserves history)
    merge_meta(folder_path, {
        "platform": "spotify",
        "playlist_name": name,
        "playlist_id": playlist_id,
        "playlist_url": url,
        "track_count": total_remote,
        "resolved_count": sum(1 for t in tracks if t.get("yt_url")),
        "tracks": tracks,
    })

    events.playlist_done(folder_name, downloaded, total_remote, skipped_count)
    return PlaylistResult("spotify", "playlist", name, folder_name, folder_path,
                          total_remote, downloaded, skipped_count, failed, tracks)


# ------------------------------------------------------------
# Single-track pipeline
# ------------------------------------------------------------

async def process_track(url: str, events: DownloadEvents, config: dict, sp=None) -> PlaylistResult:
    sp = await _ensure_client(config, sp, events)

    track_id = _extract_track_id(url)
    events.log(f"Recuperation track Spotify {track_id}...")
    events.check_cancel()
    track = _fetch_track(sp, track_id)
    if not track or not track.get("spotify_id"):
        events.log("Track introuvable.", level="error")
        return None

    artist = track["artists"][0] if track["artists"] else "Unknown"
    label = f"{artist} - {track['title']}"

    output_dir = config.get("output_dir", BASE_DIR)
    singles_dir = output_dir
    os.makedirs(singles_dir, exist_ok=True)
    folder_name = os.path.basename(singles_dir)

    events.playlist_start("spotify", label, 1, folder_name)

    music_updater = bool(config.get("music_updater", True))
    filename = sanitize_filename(label)
    mp3_path = os.path.join(singles_dir, f"{filename}.mp3")
    if music_updater and os.path.exists(mp3_path):
        events.log("Deja telecharge.")
        events.playlist_done(folder_name, 0, 1, 1)
        return PlaylistResult("spotify", "track", label, folder_name, singles_dir, 1, 0, 1, 0, [track])

    # Resolve to YT Music via SpotdlRip, fallback to YouTube search
    ensure_spotdlrip_on_path()
    from spotdlrip import SpotdlRip
    events.check_cancel()
    yt_url = None
    try:
        rip = SpotdlRip(logs=False)
        await rip.initialize()
        yt_url = await rip.spotify_to_ytmusic(track_id=track_id, only_verified=True)
        if not yt_url:
            yt_url = await rip.spotify_to_ytmusic(track_id=track_id, only_verified=False)
    except CancelledError:
        raise
    except Exception as _e:
        events.log(f"SpotdlRip: {_e} — recherche YouTube utilisee.", level="warn")
    if not yt_url:
        yt_url = f"ytsearch1:{label}"
    track["yt_url"] = yt_url

    events.track_start(1, 1, label)
    try:
        download_audio(yt_url, singles_dir, filename, 1, 1, events, quality=config.get("audio_quality", "320"))
        events.track_done(1, True)
        events.playlist_done(folder_name, 1, 1, 0)
        return PlaylistResult("spotify", "track", label, folder_name, singles_dir, 1, 1, 0, 0, [track])
    except CancelledError:
        raise
    except Exception as e:
        log_failure(singles_dir, track, f"Echec yt-dlp: {e}")
        events.track_done(1, False, str(e))
        events.playlist_done(folder_name, 0, 1, 0)
        return PlaylistResult("spotify", "track", label, folder_name, singles_dir, 1, 0, 0, 1, [track])


# ------------------------------------------------------------
# Album pipeline (reuses the same producer/consumer as process())
# ------------------------------------------------------------

async def process_album(url: str, events: DownloadEvents, config: dict, sp=None) -> PlaylistResult:
    sp = await _ensure_client(config, sp, events)

    album_id = _extract_album_id(url)
    events.log(f"Recuperation album Spotify {album_id}...")
    events.check_cancel()
    name, tracks = _fetch_album(sp, album_id)
    total_remote = len(tracks)

    output_dir = config.get("output_dir", BASE_DIR)
    music_updater = bool(config.get("music_updater", True))
    folder_name, folder_path, was_existing = get_playlist_folder(output_dir, name, reuse_existing=music_updater)
    events.playlist_start("spotify", name, total_remote, folder_name)

    if not tracks:
        events.log("Album vide.", level="warn")
        events.playlist_done(folder_name, 0, 0, 0)
        return PlaylistResult("spotify", "album", name, folder_name, folder_path, 0, 0, 0, 0, [])

    existing_ids = load_existing_track_ids(folder_path) if music_updater else set()
    existing_files = load_existing_filenames(folder_path) if music_updater else set()

    to_resolve = []
    skipped_count = 0
    for t in tracks:
        key = track_id_key(t)
        artist0 = t["artists"][0] if t.get("artists") else "Unknown"
        expected_file = sanitize_filename(f"{artist0} - {t['title']}") + ".mp3"
        if music_updater and (
            (key and key in existing_ids) or expected_file.lower() in existing_files
        ):
            skipped_count += 1
            continue
        to_resolve.append(t)

    if was_existing and music_updater:
        events.log(f"Updater: {skipped_count} deja present, {len(to_resolve)} a telecharger")

    if not to_resolve:
        events.log("Tout est deja telecharge.")
        events.playlist_done(folder_name, 0, total_remote, skipped_count)
        return PlaylistResult("spotify", "album", name, folder_name, folder_path,
                              total_remote, 0, skipped_count, 0, tracks)

    save_playlist_meta(folder_path, {
        "platform": "spotify",
        "kind": "album",
        "playlist_name": name,
        "album_id": album_id,
        "album_url": url,
        "track_count": total_remote,
        "tracks": tracks,
    })

    events.log(f"Pipeline resolve+download ({len(to_resolve)} tracks, {NUM_DOWNLOAD_WORKERS} workers)...")

    quality = config.get("audio_quality", "320")
    total_to_process = len(to_resolve)
    queue: asyncio.Queue = asyncio.Queue(maxsize=QUEUE_BUFFER)
    counters = {"downloaded": 0, "failed": 0, "resolve_failed": 0, "dl_index": 0}

    ensure_spotdlrip_on_path()
    from spotdlrip import SpotdlRip
    rip = None
    try:
        _rip = SpotdlRip(logs=False)
        await _rip.initialize()
        rip = _rip
    except Exception as _init_err:
        events.log(
            f"SpotdlRip indisponible ({_init_err}) — recherche YouTube activee en fallback.",
            level="warn",
        )

    resolver_sem = asyncio.Semaphore(3)

    async def resolve_one(track, idx):
        async with resolver_sem:
            events.check_cancel()
            label = f"{track['artists_str']} - {track['title']}"
            yt_url = None
            if rip is not None:
                try:
                    yt_url = await rip.spotify_to_ytmusic(track_id=track["spotify_id"], only_verified=True)
                    if not yt_url:
                        yt_url = await rip.spotify_to_ytmusic(track_id=track["spotify_id"], only_verified=False)
                except CancelledError:
                    raise
                except Exception as e:
                    events.log(f"SpotdlRip [{label}]: {e}", level="warn")
            if not yt_url:
                yt_url = f"ytsearch1:{label}"
            track["yt_url"] = yt_url
            events.resolve_progress(idx + 1, total_to_process, label, True)
            await queue.put(track)

    async def producer():
        try:
            await asyncio.gather(*(resolve_one(t, i) for i, t in enumerate(to_resolve)))
        finally:
            for _ in range(NUM_DOWNLOAD_WORKERS):
                await queue.put(None)

    async def downloader(worker_id: int):
        loop = asyncio.get_running_loop()
        while True:
            track = await queue.get()
            if track is None:
                return
            try:
                events.check_cancel()
            except CancelledError:
                while True:
                    t = await queue.get()
                    if t is None:
                        break
                raise

            counters["dl_index"] += 1
            idx = counters["dl_index"]
            artist = track["artists"][0] if track["artists"] else "Unknown"
            filename = sanitize_filename(f"{artist} - {track['title']}")
            mp3_path = os.path.join(folder_path, f"{filename}.mp3")
            label = f"{artist} - {track['title']}"

            events.track_start(idx, total_to_process, label)

            if os.path.exists(mp3_path):
                events.track_done(idx, True, "already present")
                counters["downloaded"] += 1
                continue

            try:
                await loop.run_in_executor(
                    None,
                    partial(download_audio, track["yt_url"], folder_path, filename,
                            idx, total_to_process, events, quality),
                )
                events.track_done(idx, True)
                counters["downloaded"] += 1
            except CancelledError:
                raise
            except Exception as e:
                log_failure(folder_path, track, f"Echec yt-dlp: {e}")
                events.track_done(idx, False, str(e))
                counters["failed"] += 1

    await asyncio.gather(
        producer(),
        *(downloader(i) for i in range(NUM_DOWNLOAD_WORKERS)),
    )

    downloaded = counters["downloaded"]
    failed = counters["failed"] + counters["resolve_failed"]

    merge_meta(folder_path, {
        "platform": "spotify",
        "kind": "album",
        "playlist_name": name,
        "album_id": album_id,
        "album_url": url,
        "track_count": total_remote,
        "resolved_count": sum(1 for t in tracks if t.get("yt_url")),
        "tracks": tracks,
    })

    events.playlist_done(folder_name, downloaded, total_remote, skipped_count)
    return PlaylistResult("spotify", "album", name, folder_name, folder_path,
                          total_remote, downloaded, skipped_count, failed, tracks)
