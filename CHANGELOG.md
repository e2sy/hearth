# Changelog

All notable changes are documented here. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- This changelog.
- **Room 10 — The Ember Feed (engines)**: `hearth/feeds.py` — the weekly
  Ember Feed (cooling rotation + deep cuts + rotation B-sides), the
  Daylist (hour-of-day mixes from history), release radar
  (`follows`/`radar_releases` tables, `sweep_artist()`), and marked
  queue suggestions. Local-first; the only network lives in injected
  fetchers the job pool controls.
- **Room 12 — The Pantry (engine)**: `hearth/stream_cache.py` — a
  size-capped disk LRU of resolved streams (mtime-ordered, touch-on-hit,
  safe-while-playing broom). A replay shelf, not a download store.
- **Room 13 — The Broadcast Tower (engines)**: `hearth/podcasts.py` —
  keyless RSS parsing (iTunes namespace aware), OPML import/export,
  open iTunes discovery (search + charts + feed lookup), and
  `podcast_*` storage with per-episode position/played memory that
  survives refreshes.
- **Room 15 — The Wise Fire (engines)**: `hearth/prompts.py` —
  natural-language prompt playlists via a mood-word → YTM-query map
  (no LLM in the loop, zero-network fallback always exists), with
  round-robin, dedupe, and per-query failure isolation in assembly.
- 60 new headless tests covering the four engine rooms (706 total).
- **Room 6.4 groundwork — lyrics-line search**: a capped
  `lyrics_cache` table in the store plus scoring and search in
  `hearth/lyrics.py` — the offline leg (`search_cache`) works with the
  network unplugged, the keyless LRCLIB leg (`search_online`) sweeps
  for lines nobody has played yet, and both return ranked `LyricHit`s
  without ever raising.
- **Room 8.2 groundwork — party suggestions**: `hearth/remote.py`
  grows a bounded, dedupe-bumping `SuggestionInbox`, a token-gated
  `/api/suggest` route, a paste-anything `parse_video_id`, and a
  "Suggest a song for the host" card on the remote page. Host playback
  stays authoritative — guests can only whisper into the inbox.
- **Room 8.3 groundwork — Windows SMTC shim**: `hearth/smtc.py` — pure
  `metadata_map` / `timeline_map` / `button_command` mappers and a
  fake-bus `SmtcService`, mirroring the MPRIS guarded-import
  discipline (silent no-op wherever winsdk is absent).
- **The Welcome Mat — Spotify playlist importer**: `hearth/switchboard.py`
  — parses Spotify JSON exports, Exportify CSVs, and embed-page HTML;
  cleans video-noise, queries under the lead artist, collapses
  duplicate videos, and files an honest `ImportReport` into a real
  playlist. No login, no keys, no crawler.
- **Playlist Enhance**: `hearth/enhance.py` — the one-tap sprinkle
  with per-pick seed attribution ("radio from …") and store
  integration.
- 75 new headless tests (781 total).

## [0.1.0] — earlier

See `git log` for the history before this changelog was introduced.
