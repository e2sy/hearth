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

## [0.1.0] — earlier

See `git log` for the history before this changelog was introduced.
