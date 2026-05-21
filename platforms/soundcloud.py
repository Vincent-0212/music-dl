"""SoundCloud pipeline using yt-dlp directly. Supports playlists + single tracks.

GO+ handling: when a track is preview-only (SNIP policy or downloaded duration
much shorter than expected), we fall back to searching the equivalent on
YouTube Music / YouTube. If no good match is found, we keep the SoundCloud
preview (better than nothing).
"""

import os
import yt_dlp

from .common import (
    BASE_DIR, DownloadEvents, PlaylistResult, CancelledError,
    sanitize_filename, get_playlist_folder, get_singles_folder,
    load_existing_track_ids, load_existing_filenames, track_id_key,
    log_failure, download_audio, save_playlist_meta, merge_meta,
    mp3_duration_seconds, search_ytmusic_for_track, search_youtube_for_track,
)


def _entry_to_track(entry):
    title = entry.get("title", "Unknown")
    artist = entry.get("uploader") or entry.get("creator") or "Unknown"
    return {
        "title": title,
        "artists": artist,
        "artists_str": artist,
        "duration_ms": int((entry.get("duration") or 0) * 1000),
        "soundcloud_url": entry.get("webpage_url") or entry.get("url", ""),
        "soundcloud_id": str(entry.get("id", "")),
        # yt-dlp's SoundCloud extractor exposes policy / monetization fields.
        # "SNIP" means non-subscribers only get a preview snippet.
        "sc_policy": entry.get("policy") or "",
        "sc_monetization": entry.get("monetization_model") or "",
    }


def _is_likely_go_plus_preview(track: dict) -> bool:
    policy = (track.get("sc_policy") or "").upper()
    mon = (track.get("sc_monetization") or "").lower()
    if policy == "SNIP":
        return True
    if "sub_high_tier" in mon or "subscription" in mon:
        return True
    return False


def _download_with_fallback(track: dict, source_url: str, folder_path: str,
                            filename: str, idx: int, total: int,
                            events: DownloadEvents, quality: str) -> None:
    """Download from SoundCloud; if result looks like a preview, retry via YouTube.

    Raises on hard failure (CancelledError or the final exception if all
    sources fail).
    """
    mp3_path = os.path.join(folder_path, f"{filename}.mp3")
    expected_seconds = (track.get("duration_ms") or 0) / 1000.0

    pre_detected_preview = _is_likely_go_plus_preview(track)

    if pre_detected_preview:
        events.log(f"GO+ preview detected pre-download — fallback YouTube ({track['title']}).", level="warn")
    else:
        # Try SoundCloud first
        try:
            download_audio(source_url, folder_path, filename, idx, total, events, quality=quality)
        except CancelledError:
            raise
        except Exception as e:
            events.log(f"SoundCloud download failed ({e}) — trying YouTube fallback.", level="warn")
            pre_detected_preview = True  # force fallback path below

        # Post-download duration sanity check — preview is typically ~30s
        if not pre_detected_preview and expected_seconds > 60:
            actual = mp3_duration_seconds(mp3_path) or 0
            if actual and actual < 0.8 * expected_seconds:
                events.log(
                    f"Downloaded duration {actual:.0f}s << expected {expected_seconds:.0f}s — "
                    f"likely GO+ preview. Trying YouTube fallback.",
                    level="warn",
                )
                pre_detected_preview = True
                try:
                    os.remove(mp3_path)
                except Exception:
                    pass

    if not pre_detected_preview:
        return  # SoundCloud version is fine

    # Fallback: search YouTube Music, then plain YouTube ytsearch1.
    title = track.get("title", "")
    artist = (track.get("artists_str") or
              (track["artists"][0] if isinstance(track.get("artists"), list) and track["artists"] else
               track.get("artists", "Unknown")))

    yt_url = search_ytmusic_for_track(title, artist)
    if not yt_url:
        yt_url = search_youtube_for_track(title, artist)

    if not yt_url:
        # Last resort: redo SoundCloud download (so user at least gets the preview).
        events.log("No YouTube alternative found — keeping SoundCloud preview.", level="warn")
        download_audio(source_url, folder_path, filename, idx, total, events, quality=quality)
        return

    events.log(f"YouTube fallback: {yt_url}", level="info")
    download_audio(yt_url, folder_path, filename, idx, total, events, quality=quality)


async def process(url: str, events: DownloadEvents, config: dict, kind: str = "playlist") -> PlaylistResult:
    events.log("Recuperation SoundCloud...")
    events.check_cancel()

    try:
        with yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True}) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception as e:
        events.log(f"Erreur lecture SoundCloud: {e}", level="error")
        return None

    if not info:
        events.log("Aucune info recuperee.", level="warn")
        return None

    entries = info.get("entries") or []
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
        os.makedirs(folder_path, exist_ok=True)
        folder_name = os.path.basename(folder_path)
        events.playlist_start("soundcloud", label, 1, folder_name)

        filename = sanitize_filename(label)
        mp3_path = os.path.join(folder_path, f"{filename}.mp3")
        if music_updater and os.path.exists(mp3_path):
            events.log("Deja telecharge.")
            events.playlist_done(folder_name, 0, 1, 1)
            return PlaylistResult("soundcloud", "track", label, folder_name, folder_path, 1, 0, 1, 0, [track])

        track_url = entries[0].get("webpage_url") or entries[0].get("url", "")
        events.track_start(1, 1, label)
        try:
            _download_with_fallback(track, track_url, folder_path, filename, 1, 1, events, quality)
            events.track_done(1, True)
            events.playlist_done(folder_name, 1, 1, 0)
            return PlaylistResult("soundcloud", "track", label, folder_name, folder_path, 1, 1, 0, 0, [track])
        except CancelledError:
            raise
        except Exception as e:
            log_failure(folder_path, track, f"Echec SoundCloud + fallback: {e}")
            events.track_done(1, False, str(e))
            events.playlist_done(folder_name, 0, 1, 0)
            return PlaylistResult("soundcloud", "track", label, folder_name, folder_path, 1, 0, 0, 1, [track])

    # Playlist
    name = info.get("title") or info.get("uploader") or "SoundCloud_Playlist"
    folder_name, folder_path, was_existing = get_playlist_folder(output_dir, name, reuse_existing=music_updater)
    total = len(entries)
    events.playlist_start("soundcloud", name, total, folder_name)

    tracks_all = [_entry_to_track(e) for e in entries if e]

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
        "platform": "soundcloud",
        "playlist_name": name,
        "playlist_url": url,
        "track_count": total,
        "tracks": tracks_all,
    })

    if not to_dl_pairs:
        events.log("Tout est deja telecharge.")
        events.playlist_done(folder_name, 0, total, skipped)
        return PlaylistResult("soundcloud", "playlist", name, folder_name, folder_path, total, 0, skipped, 0, tracks_all)

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
            _download_with_fallback(track, track_url, folder_path, filename,
                                    i, len(to_dl_pairs), events, quality)
            events.track_done(i, True)
            downloaded += 1
        except CancelledError:
            raise
        except Exception as e:
            log_failure(folder_path, track, f"Echec SoundCloud + fallback: {e}")
            events.track_done(i, False, str(e))
            failed += 1

    merge_meta(folder_path, {
        "platform": "soundcloud",
        "playlist_name": name,
        "playlist_url": url,
        "track_count": total,
        "tracks": tracks_all,
    })

    events.playlist_done(folder_name, downloaded, total, skipped)
    return PlaylistResult("soundcloud", "playlist", name, folder_name, folder_path,
                          total, downloaded, skipped, failed, tracks_all)
