import spotipy
from spotipy.oauth2 import SpotifyOAuth
import csv
import json
import sys
import os

CLIENT_ID = "3bd68303e9a84235ab5028c2e789fb33"
CLIENT_SECRET = "d3e51726d1d949a0aa94f05146b08afe"
REDIRECT_URI = "http://127.0.0.1:8888/callback"
DEFAULT_PLAYLIST_ID = "7cj55Z5bENhKylC9crQn3X"
OUTPUT_CSV = "playlist_tracks.csv"
OUTPUT_JSON = "playlist_tracks.json"

def extract_playlist_id(arg):
    if "spotify.com/playlist/" in arg:
        return arg.split("spotify.com/playlist/")[1].split("?")[0]
    return arg

def get_all_tracks(sp, playlist_id):
    tracks = []
    results = sp.playlist_tracks(playlist_id)

    while results:
        for item in results.get("items", []):
            # Spotify renvoie parfois "track", parfois "item"
            track = item.get("track") or item.get("item")
            if not track or not track.get("id"):
                continue
            artists = ", ".join(a["name"] for a in track.get("artists", []))
            tracks.append({
                "title": track.get("name", ""),
                "artists": artists,
                "album": track.get("album", {}).get("name", ""),
                "release_date": track.get("album", {}).get("release_date", ""),
                "duration_ms": track.get("duration_ms", 0),
                "spotify_url": track.get("external_urls", {}).get("spotify", ""),
                "spotify_id": track.get("id", ""),
            })
        results = sp.next(results) if results.get("next") else None
        print(f"  {len(tracks)} tracks récupérés...", end="\r")

    return tracks

def main():
    if len(sys.argv) > 1:
        playlist_id = extract_playlist_id(sys.argv[1])
    else:
        playlist_id = DEFAULT_PLAYLIST_ID

    print(f"Playlist ID : {playlist_id}")

    cache_path = ".cache"
    if os.path.exists(cache_path):
        os.remove(cache_path)

    auth_manager = SpotifyOAuth(
        client_id=CLIENT_ID,
        client_secret=CLIENT_SECRET,
        redirect_uri=REDIRECT_URI,
        scope="playlist-read-private playlist-read-collaborative",
        open_browser=False,
        cache_path=cache_path
    )

    auth_url = auth_manager.get_authorize_url()
    print(f"\nOuvre ce lien dans ton navigateur :\n{auth_url}\n")
    print("Colle l'URL de callback ici :")
    response_url = input("URL de callback : ").strip()
    code = auth_manager.parse_response_code(response_url)
    token_info = auth_manager.get_access_token(code)

    sp = spotipy.Spotify(auth=token_info["access_token"])

    print("\nRécupération des tracks...")
    tracks = get_all_tracks(sp, playlist_id)
    print(f"\nTotal : {len(tracks)} tracks\n")

    if len(tracks) == 0:
        print("Aucun track récupéré.")
        return

    with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["title","artists","album","release_date","duration_ms","spotify_url","spotify_id"])
        writer.writeheader()
        writer.writerows(tracks)
    print(f"CSV exporté : {OUTPUT_CSV}")

    with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
        json.dump(tracks, f, ensure_ascii=False, indent=2)
    print(f"JSON exporté : {OUTPUT_JSON}")

if __name__ == "__main__":
    main()