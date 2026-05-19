"""
DL.py — CLI orchestrator for DL_MUSIC bulk playlist downloader.

Usage:
    python DL.py <url1> [url2] [url3] ...

Supported platforms (auto-detected):
    - Spotify    : https://open.spotify.com/playlist/...
    - SoundCloud : https://soundcloud.com/user/sets/playlist-name
    - YouTube    : https://www.youtube.com/playlist?list=...
    - Deezer     : https://www.deezer.com/playlist/...

For Spotify, credentials must be stored in config.json (use the GUI to set them,
or copy-paste your CLIENT_ID / CLIENT_SECRET manually into config.json).
"""

import sys
import asyncio

from platforms import (
    detect_platform, process_playlist, DownloadEvents,
    load_config, PLATFORM_LABELS,
)
from platforms.spotify import build_spotify_client


def _sep(title=""):
    line = "=" * 60
    if title:
        print(f"\n{line}\n  {title}\n{line}")
    else:
        print(line)


def _make_cli_events() -> DownloadEvents:
    """Console-friendly event handlers."""

    def on_playlist_start(platform, name, total, folder_name=""):
        print(f"\n  Playlist : {name}  ({total} tracks) [{platform}] -> {folder_name}/")

    def on_resolve_progress(idx, total, label, ok):
        tag = "OK  " if ok else "FAIL"
        print(f"  [resolve {idx}/{total}] {tag}  {label}")

    def on_track_start(idx, total, label):
        print(f"  [{idx}/{total}] {label}")

    def on_track_progress(idx, pct, speed):
        print(f"    {pct:5.1f}%  {speed}               ", end="\r")

    def on_track_done(idx, success, error=""):
        if success:
            print(f"    -> OK                              ")
        else:
            print(f"    -> FAIL: {error}")

    def on_playlist_done(folder_name, downloaded, total, skipped=0):
        print(f"\n  Termine : {downloaded} dl, {skipped} skipped / {total} -> {folder_name}/\n")

    def on_log(msg, level):
        prefix = {"error": "ERR", "warn": "WRN"}.get(level, "   ")
        print(f"  [{prefix}] {msg}")

    return DownloadEvents(
        on_playlist_start=on_playlist_start,
        on_resolve_progress=on_resolve_progress,
        on_track_start=on_track_start,
        on_track_progress=on_track_progress,
        on_track_done=on_track_done,
        on_playlist_done=on_playlist_done,
        on_log=on_log,
    )


async def main():
    urls = sys.argv[1:]
    if not urls:
        print(__doc__)
        sys.exit(1)

    config = load_config()
    events = _make_cli_events()

    _sep(f"DL_MUSIC  —  {len(urls)} playlist(s)")

    # Authenticate Spotify once if any Spotify URL is present
    sp = None
    spotify_urls = [u for u in urls if detect_platform(u) == "spotify"]
    if spotify_urls:
        creds = config.get("spotify", {})
        if not creds.get("client_id") or not creds.get("client_secret"):
            print("\n  ERREUR : credentials Spotify manquants dans config.json")
            print("  Lance `python gui.py` pour les configurer via l'interface.")
            sys.exit(1)
        _sep("Connexion Spotify")
        sp = build_spotify_client(creds["client_id"], creds["client_secret"])
        print("  Connecte.")

    for idx, url in enumerate(urls, 1):
        platform = detect_platform(url)
        label = PLATFORM_LABELS.get(platform, "?")
        _sep(f"Playlist {idx}/{len(urls)}  [{label}]  {url}")

        if platform is None:
            print("  Plateforme non reconnue, on passe.")
            continue

        await process_playlist(url, events, config, spotify_client=sp)

    _sep("Termine !")


if __name__ == "__main__":
    asyncio.run(main())
