"""YouTube pipeline (regular YouTube + YouTube Music). Playlists + single tracks."""

import os
import yt_dlp

from .common import (
    BASE_DIR, DownloadEvents, PlaylistResult, CancelledError,
    sanitize_filename, get_playlist_folder, get_singles_folder,
    load_existing_track_ids, load_existing_filenames, track_id_key,
    log_failure, download_audio, save_playlist_meta, merge_meta,
)


def _entry_to_track(entry):
    title = entry.get("title", "Unknown")
    artist = entry.get("artist") or entry.get("uploader") or entry.get("channel") or "Unknown"
    return {
        "title": title,
        "artists": artist,
        "artists_str": artist,
        "duration_ms": int((entry.get("duration") or 0) * 1000),
        "youtube_url": entry.get("webpage_url") or entry.get("url", ""),
        "youtube_id": str(entry.get("id", "")),
    }


async def process(url: str, events: DownloadEvents, config: dict, kind: str = "playlist") -> PlaylistResult:
    events.log("Recuperation YouTube...")
    events.check_cancel()

    opts = {"quiet": True, "no_warnings": True, "ignoreerrors": True, "extract_flat": False}
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception as e:
        events.log(f"Erreur lecture YouTube: {e}", level="error")
        return None

    if not info:
        events.log("Aucune info recuperee.", level="warn")
        return None

    entries = info.get("entries") or []
    entries = [e for e in entries if e] if entries else []
    is_single = (kind == "track") or (not entries)
    if is_single:
        entries = [info]

    output_dir = config.get("output_dir", BASE_DIR)
    music_updater = bool(config.get("music_updater", True))
    quality = config.get("audio_quality", "320")

    if is_single:
        track = _entry_to_track(entries[0])
        label = f"{track['artists']} - {track['title']}"
        folder_path = output_dir
        folder_name = os.path.basename(output_dir)
        events.playlist_start("youtube", label, 1, folder_name)

        filename = sanitize_filename(label)
        mp3_path = os.path.join(folder_path, f"{filename}.mp3")
        if music_updater and os.path.exists(mp3_path):
            events.log("Deja telecharge.")
            events.playlist_done(folder_name, 0, 1, 1)
            return PlaylistResult("youtube", "track", label, folder_name, folder_path, 1, 0, 1, 0, [track])

        track_url = entries[0].get("webpage_url") or entries[0].get("url", "")
        events.track_start(1, 1, label)
        try:
            download_audio(track_url, folder_path, filename, 1, 1, events, quality=quality)
            events.track_done(1, True)
            events.playlist_done(folder_name, 1, 1, 0)
            return PlaylistResult("youtube", "track", label, folder_name, folder_path, 1, 1, 0, 0, [track])
        except CancelledError:
            raise
        except Exception as e:
            log_failure(folder_path, track, f"Echec yt-dlp YouTube: {e}")
            events.track_done(1, False, str(e))
            events.playlist_done(folder_name, 0, 1, 0)
            return PlaylistResult("youtube", "track", label, folder_name, folder_path, 1, 0, 0, 1, [track])

    # Playlist
    name = info.get("title") or info.get("uploader") or "YouTube_Playlist"
    folder_name, folder_path, was_existing = get_playlist_folder(output_dir, name, reuse_existing=music_updater)
    total = len(entries)
    events.playlist_start("youtube", name, total, folder_name)

    tracks_all = [_entry_to_track(e) for e in entries]

    existing_ids = load_existing_track_ids(folder_path) if music_updater else set()
    existing_files = load_existing_filenames(folder_path) if music_updater else set()

    to_dl_pairs = []
    skipped = 0
    for entry, track in zip(entries, tracks_all):
        key = track_id_key(track)
        expected_file = sanitize_filename(f"{track['artists']} - {track['title']}") + ".mp3"
        if music_updater and (
            (key and key in existing_ids) or expected_file.lower() in existing_files
        ):
            skipped += 1
            continue
        to_dl_pairs.append((entry, track))

    if was_existing and music_updater:
        events.log(f"Updater: {skipped} deja present, {len(to_dl_pairs)} a telecharger")

    save_playlist_meta(folder_path, {
        "platform": "youtube",
        "playlist_name": name,
        "playlist_url": url,
        "track_count": total,
        "tracks": tracks_all,
    })

    if not to_dl_pairs:
        events.log("Tout est deja telecharge.")
        events.playlist_done(folder_name, 0, total, skipped)
        return PlaylistResult("youtube", "playlist", name, folder_name, folder_path, total, 0, skipped, 0, tracks_all)

    downloaded = 0
    failed = 0

    for i, (entry, track) in enumerate(to_dl_pairs, 1):
        events.check_cancel()
        track_url = entry.get("webpage_url") or entry.get("url", "")
        filename = sanitize_filename(f"{track['artists']} - {track['title']}")
        label = f"{track['artists']} - {track['title']}"
        events.track_start(i, len(to_dl_pairs), label)

        mp3_path = os.path.join(folder_path, f"{filename}.mp3")
        if os.path.exists(mp3_path):
            events.track_done(i, True, "already present")
            downloaded += 1
            continue

        try:
            download_audio(track_url, folder_path, filename, i, len(to_dl_pairs), events, quality=quality)
            events.track_done(i, True)
            downloaded += 1
        except CancelledError:
            raise
        except Exception as e:
            log_failure(folder_path, track, f"Echec yt-dlp YouTube: {e}")
            events.track_done(i, False, str(e))
            failed += 1

    merge_meta(folder_path, {
        "platform": "youtube",
        "playlist_name": name,
        "playlist_url": url,
        "track_count": total,
        "tracks": tracks_all,
    })

    events.playlist_done(folder_name, downloaded, total, skipped)
    return PlaylistResult("youtube", "playlist", name, folder_name, folder_path,
                          total, downloaded, skipped, failed, tracks_all)
