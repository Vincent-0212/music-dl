"""Platform dispatcher for MUSIC DL."""

import re

from .common import DownloadEvents, PlaylistResult, load_config, save_config


# YouTube Mix / Radio prefixes: RD = Radio/Mix, UL = Uploads, PU = Personal Uploads,
# OL = Other List, LL = Liked, MM = Music Mix. All should be treated as playlists.
_YT_MIX_RE = re.compile(r'[?&]list=(?:RD|UL|PU|OL|LL|MM)', re.IGNORECASE)


def detect_platform(url: str):
    """Return platform id or None."""
    if not url:
        return None
    u = url.lower().strip()
    if "spotify.com" in u or u.startswith("spotify:"):
        return "spotify"
    if "soundcloud.com" in u:
        return "soundcloud"
    if "music.youtube.com" in u:
        return "ytmusic"
    if "youtube.com" in u or "youtu.be" in u:
        return "youtube"
    return None


def detect_kind(url: str):
    """Return 'track', 'playlist', or 'album' (best guess from URL)."""
    if not url:
        return None
    u = url.lower().strip()
    # Spotify — handle locale-prefixed URLs like /intl-fr/track/, /intl-en/album/
    if "spotify.com" in u:
        if "/playlist/" in u or u.startswith("spotify:playlist:"):
            return "playlist"
        if "/track/" in u or u.startswith("spotify:track:"):
            return "track"
        if "/album/" in u or u.startswith("spotify:album:"):
            return "album"
    # YouTube Mix / Radio (list=RD*, UL*, etc.) — even with watch?v= prefix
    if _YT_MIX_RE.search(u):
        return "playlist"
    # YouTube
    if "youtube.com/playlist" in u or ("list=" in u and "watch?" not in u):
        return "playlist"
    if "music.youtube.com/playlist" in u:
        return "playlist"
    if "music.youtube.com/browse/" in u:
        return "album"
    if "youtu.be/" in u or "watch?v=" in u or "music.youtube.com/watch" in u:
        return "track"
    if "youtube.com" in u and "list=" in u:
        return "playlist"
    # SoundCloud: /sets/ is a playlist, otherwise probably a track
    if "soundcloud.com" in u:
        if "/sets/" in u:
            return "playlist"
        return "track"
    return None


PLATFORM_LABELS = {
    "spotify": "Spotify",
    "soundcloud": "SoundCloud",
    "youtube": "YouTube",
    "ytmusic": "YouTube Music",
}


async def process_url(url: str, events: DownloadEvents, config: dict, spotify_client=None):
    """Dispatch any URL to the right platform + kind handler."""
    platform = detect_platform(url)
    kind = detect_kind(url) or "playlist"

    if platform == "spotify":
        from . import spotify
        if kind == "track":
            return await spotify.process_track(url, events, config, spotify_client)
        if kind == "album":
            return await spotify.process_album(url, events, config, spotify_client)
        return await spotify.process(url, events, config, spotify_client)
    if platform == "soundcloud":
        from . import soundcloud
        return await soundcloud.process(url, events, config, kind=kind)
    if platform in ("youtube", "ytmusic"):
        # YouTube Music URLs route to the same yt-dlp pipeline as YouTube —
        # extractor handles both domains identically.
        from . import youtube
        return await youtube.process(url, events, config, kind=kind)
    events.log(f"Platform not recognized: {url}", level="error")
    return None


# Backwards compatibility shim
process_playlist = process_url


__all__ = [
    "detect_platform",
    "detect_kind",
    "process_url",
    "process_playlist",
    "DownloadEvents",
    "PlaylistResult",
    "PLATFORM_LABELS",
    "load_config",
    "save_config",
]
