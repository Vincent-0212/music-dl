# MusicDL — Instructions pour Claude

Réponds toujours en français, quoi qu'il arrive.

## Vue d'ensemble

Application desktop de téléchargement musical en masse. Interface graphique native (PyWebView) avec un backend Python et un frontend HTML/CSS/JS. L'utilisateur colle des URLs Spotify, SoundCloud ou YouTube, l'app télécharge les pistes en MP3 320 kbps.

Développeur : Vincent (non-développeur de formation, utilise Claude Code pour coder). Communique en français.
Branche principale : `main` (buildv2 a été mergée).

---

## Graphify — navigation du codebase

Ce projet a un graphe de connaissance dans `graphify-out/` avec les nœuds centraux (god nodes), la structure communautaire et les relations cross-fichiers.

Règles :
- Pour les questions sur le codebase, lancer d'abord `graphify query "<question>"` si `graphify-out/graph.json` existe. Utiliser `graphify path "<A>" "<B>"` pour les relations entre fichiers et `graphify explain "<concept>"` pour un concept précis. Ces commandes retournent un sous-graphe ciblé, bien plus petit que `GRAPH_REPORT.md` ou un grep brut.
- Si `graphify-out/wiki/index.md` existe, l'utiliser pour la navigation large plutôt que de parcourir les sources brutes.
- Lire `graphify-out/GRAPH_REPORT.md` uniquement pour une revue d'architecture globale ou quand query/path/explain ne donnent pas assez de contexte.
- Après modification du code, lancer `graphify update .` pour maintenir le graphe à jour (AST uniquement, sans coût API).

---

## Stack technique

| Composant | Technologie |
|-----------|-------------|
| UI native | `pywebview >= 4.4` — fenêtre native OS hébergeant du HTML |
| Frontend | HTML + CSS + JS vanilla (dans `frontend/`) |
| Backend Python | `gui.py` — pont API entre JS et Python via `js_api` |
| Téléchargement | `yt-dlp >= 2026.3.17` (YouTube, SoundCloud) |
| Spotify | `spotipy >= 2.23` + OAuth PKCE |
| Résolution Spotify→YTMusic | `SpotdlRip/spotdlrip.py` (sous-module git) |
| Métadonnées | `mutagen` |
| Build | `PyInstaller` (specs : `musicdl.spec` Windows, `musicdl-mac.spec` macOS) |
| Python requis | **3.12** |
| FFmpeg | Doit être sur le PATH (ou bundlé dans le .exe) |

---

## Architecture du projet

```
music-dl/
├── gui.py                  # Point d'entrée. PyWebView + classe Api (pont JS↔Python)
├── config.json             # ← JAMAIS COMMITTER (dans .gitignore). Créé au runtime.
├── config.example.json     # Template de config pour l'utilisateur
├── requirements.txt        # Dépendances principales
├── musicdl.spec            # PyInstaller — build Windows (.exe)
├── musicdl-mac.spec        # PyInstaller — build macOS (.app)
├── MUSIC DL.bat            # Lanceur batch Windows pour dev
│
├── platforms/
│   ├── __init__.py         # detect_platform(), detect_kind(), process_url(), PLATFORM_LABELS
│   │                       # load_config(), save_config(), DownloadEvents
│   ├── common.py           # Utilitaires partagés, CancelledError, get_bundled_ffmpeg()
│   ├── spotify.py          # OAuth Spotify (build_spotify_client), pipeline de téléchargement
│   ├── soundcloud.py       # Téléchargement SoundCloud via yt-dlp
│   └── youtube.py          # Téléchargement YouTube via yt-dlp
│
├── SpotdlRip/              # Sous-module git
│   ├── spotdlrip.py        # Résolution Spotify → YouTube Music
│   └── requirements.txt    # Dépendances supplémentaires (spotdl, aiohttp, ytmusicapi...)
│
├── frontend/
│   ├── index.html          # SPA — une seule page
│   ├── styles.css
│   ├── app.js              # Toute la logique UI, appels à window.pywebview.api.*
│   └── icon.png
│
├── graphify-out/           # Généré par graphify — NE PAS COMMITTER
└── .github/workflows/      # CI/CD GitHub Actions
```

---

## Comment fonctionne le système de jobs (point central)

Comprendre ce pattern est crucial avant de toucher au code :

1. L'utilisateur colle une URL dans le frontend JS.
2. `app.js` appelle `window.pywebview.api.start_downloads([url])`.
3. `gui.py → Api.start_downloads()` crée un dict `state` par job (avec un `job_id` UUID court) et lance un thread `_run_job()`.
4. `_run_job()` instancie un objet `DownloadEvents` avec des callbacks (on_playlist_start, on_track_start, on_track_done, etc.) qui mettent à jour le dict `state` en temps réel.
5. Le frontend JS poll `Api.get_progress()` à intervalle régulier et re-rend les cartes de job.
6. L'annulation : un `threading.Event` par job. Le frontend appelle `cancel_job(job_id)`, l'event est set, le backend le vérifie via `events.is_cancelled()`.

**Ne jamais** appeler directement les fonctions de `platforms/` depuis le frontend. Toujours passer par `Api`.

---

## Conventions de code

- Commentaires et messages de log en **français** dans le code (ex: `"Connexion Spotify OK"`, `"Termine"`)
- Messages d'erreur côté UI en **anglais** (ex: `"Spotify credentials are missing. Open Settings."`)
- Logging via `logging` (module standard), jamais `print()` sauf dans `_clog()` qui est intentionnel pour le debug console structuré
- Pattern `_clog(msg, tag)` dans `_run_job` pour les logs avec préfixe tag (`JOB`, `SPO`, `DL`, `ERR`...)
- Async : `asyncio.new_event_loop()` + `loop.run_until_complete()` dans chaque thread de job (pas de boucle event partagée)
- Config : toujours via `load_config()` / `save_config()` de `platforms/__init__.py`, jamais lire `config.json` directement

---

## Points critiques à ne pas casser

### Mode frozen (PyInstaller)
Quand l'app tourne en `.exe` compilé, `sys.frozen == True`. Plusieurs comportements changent :
- `BASE_DIR = os.path.dirname(sys.executable)` (pas `__file__`)
- `_BUNDLE_DIR = sys._MEIPASS` (dossier temporaire PyInstaller)
- stdout/stderr sont redirigés vers le fichier log
- Le selftest (`--selftest`) valide tous les imports au démarrage de l'exe

**Ne jamais** utiliser `__file__` pour des chemins en dehors du mode dev. Toujours vérifier `sys.frozen`.

### Spotify OAuth
- Un seul `_spotify_client` partagé entre tous les jobs, protégé par `_spotify_lock`
- Le client est créé à la première demande (lazy init), pas au démarrage
- Si les credentials changent (via `save_spotify_creds`), le client est reset à `None`

### yt-dlp
- Version minimale `>= 2026.3.17` — les versions plus anciennes cassent sur YouTube
- Dans le CI/CD GitHub Actions, la dernière pre-release est installée pour rester à jour

### Logging
- `_setup_logging()` est appelé **avant** tout import susceptible d'échouer — intentionnel pour capturer les erreurs d'import dans le log
- Log path : `%APPDATA%\MusicDL\musicdl.log` (Windows)

---

## Ce qu'il ne faut pas faire

- Ne pas committer `config.json` (contient les credentials Spotify)
- Ne pas committer `graphify-out/` (graphe local généré)
- Ne pas utiliser `print()` pour le debug (utiliser `logging.info/debug/error`)
- Ne pas changer la signature de `DownloadEvents` sans mettre à jour tous les `platforms/*.py` qui l'utilisent
- Ne pas faire d'appels réseau synchrones dans `_run_job()` sans passer par `asyncio`

---

## Workflow de build

```bash
# Windows — génère dist/MusicDL.exe
pyinstaller musicdl.spec --clean

# macOS — génère dist/MusicDL.app
pyinstaller musicdl-mac.spec --clean
```

Les releases GitHub sont créées automatiquement via `.github/workflows/`.

---

## Structure de config.json

```json
{
  "spotify": {
    "client_id": "...",
    "client_secret": "..."
  },
  "output_dir": "C:/Users/Vincent/Music",
  "audio_quality": "320",
  "music_updater": true
}
```

- `music_updater: true` = skip les pistes déjà téléchargées lors d'une re-sync
- `audio_quality` : valeur string (`"320"`, `"256"`, `"128"`)
- Les credentials Spotify peuvent aussi être entrés dans le panneau Settings de l'UI (préféré)