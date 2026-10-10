# Changelog

All notable changes are documented here. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- **Wave 3 — the living room (motion + muscle)**: the 3D room answers the
  hand and the listener gets new power. *Motion*: a pure lift ladder
  (`hearth/motion.py`) drives hover-lift and press-plant on shelf/discover
  cards and the transport flats, staggered "grounding" entrances for shelf
  cards, a rise-in command palette, a breathing shadow on the mini player,
  a breathing accent glow on the playing row in the queue, pressed slider
  faces, and findable keyboard-focus rims — all switchable off with
  `config.MOTION_ENABLED` (reduced motion keeps every resting shadow).
  *Muscle*: queue dock shows the remaining time plus Reverse / Dedup / Now
  (jump to playing) / Shuffle-upcoming; two new palettes (Ember Dusk,
  Lantern high-contrast); a text-size dial (Ctrl+K "Bigger/Smaller text",
  85–130%, restart-safe and compounding-proof); four new global hotkeys
  (mute, volume up/down, repeat cycle); Ctrl+1..9 jumps straight to views;
  the History page grows a client-side filter box; the Stats dashboard
  gains a live "day streak" tile (`rewind.current_streak`); the app reopens
  on the last view you used and the mini player remembers its corner.
  The glass test no longer leaks its style into other tests.
- **The 3D pass — Hearth in Relief** (`docs/UI-DEPTH.md`): Spotify is a flat
  poster; Hearth locks into depth. One light from above — a radial spotlight
  floor the whole room sits on — and every surface at a height: carved cards
  and buttons with bright top lips and dark under-lips, pressed-in search
  fields and slider grooves, a glossy accent ramp that sinks when pressed,
  3D sphere slider handles, and a player bar that now floats as a rounded
  card with a real drop shadow. The mini player, command palette (now a
  translucent rounded shell), floating panel, and toasts all hover with real
  or painted ground shadows; home shelf cards lift off the floor. Every tone
  is derived from the active palette at compile time (no new color fields);
  strength dials live in `config.py` (`DEPTH_RADIUS`, `DEPTH_SHADOWS`) and
  every pack (glass, veil, neon) inherits the depth for free. 864 tests green.
- This changelog.
- **UI redesign, act II — the last emoji leave the building**: menus,
  status-bar messages, the World Explorer's 74 genre chips, the Rewind
  story, the tray icon, toasts, the party inbox, diagnostics, the update
  whisper, and even the phone-remote web page now speak the same clean
  design language — plain text, vector flame marks, and inline SVG
  transport buttons (play/pause swaps itself live). The tray and taskbar
  icon is painted from the same in-memory vector flame as the app
  (palette-tinted), the Rewind share card colors its headline by position
  instead of emoji sniffing, and world genre chips read as honest text.
- **UI redesign — the slop purge**: every emoji icon in the visible chrome
  (sidebar, player bar, headers, chips, dialogs, ribbon, mini player,
  cover placeholder) is replaced by a 44-icon in-memory vector set
  (`hearth/icons.py`, QSvgRenderer, no assets, retina-crisp, palette-tinted).
  The stylesheet is rebuilt flat and modern: honest surfaces instead of
  2020s gradients, softer hairlines, tighter radii, a real wordmark with a
  painted vector flame, accent-tinted active nav pills, slimmer sliders,
  and a calmer play-button glow. Icons re-tint themselves when the theme
  or accent changes.
- **Wave-2 wiring — the engines became buttons** (854 tests green):
  - **🪟 Pocket hearth (floating mini player)**: Ctrl+K → "Mini player"
    opens a frameless, always-on-top pocket transport you can drag
    anywhere — cover dot, marquee title (ping-pong walk, rests at the
    seams), artist + clock, transport, slim seek, and ⤢ / double-click
    to hand the stage back to the main room. The pure model
    (`hearth/minimode.py`: `Marquee`, `fmt_clock`, `MiniPlayerModel`)
    is headless-tested with no Qt; the widget is built lazily and only
    mirrors what the model says. Playback mirrors into the model from
    boot, so the pocket never opens stale.
  - **📝 Lyrics chip** on the search page: a remembered line becomes the
    song. Cache hits play directly; LRCLIB hits earn one catalog search
    each via `resolve_lyric_hits` (pure, injected, never raises).
    `LyricSearchJob` runs both legs off the UI thread.
  - **✨ Enhance button** on every playlist: `EnhanceJob` sprinkles
    radio-shaped picks via `catalog.radio` and refreshes the view.
  - **🟢 From Spotify** button in Your Library: the `ImportDialog` takes
    a pasted JSON export / Exportify CSV / embed page (name + format
    override), `ImportJob` runs `switchboard.import_spotify` on the
    worker pool, and the rebuilt playlist opens itself.
  - **🎉 Party suggestions reach the host**: the remote Bridge gained
    `suggest`/`pending_suggestions` (the `/api/suggest` route was live
    but unanswered), a 4 s poller nudges the status bar, and the
    `PartyInboxDialog` (Ctrl+K → "Party suggestions") queues or skips
    every guest pick. Host playback stays authoritative.
  - **🎚️ Sound Forge bench**: `hearth/sound_shape.py` (10-band EQ table,
    presets, karaoke mid/side DSP, preamp math — all clamped, pure,
    tested) plus the `SoundForgeDialog` panel. The **preamp is real
    today**: `PlaybackCore.set_preamp` folds it into the master volume
    and the crossfade ramp; band gains and the karaoke cut wait for a
    PCM tap (Qt Multimedia exposes none). Settings persist in the new
    `sound_settings` table and restore at startup.
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
