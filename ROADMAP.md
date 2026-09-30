# 🗺️ Hearth Roadmap — the road to the warmest player on every desktop

> This file is about **what burns next**. Shipped features live in the
> [README](README.md). It is revisited every release — waves get promoted,
> re-scoped, or retired, but the fire never gets a "maybe".
>
> Last stoked: **2026-09-18** (v0.7.2 shipped; v0.8.0 "The Long Winter Nights"
> charted). Earlier, by crew decision, every wave was folded into
> **one main version** — all four themes, one fire, built in order. Every
> add-on discussed with the crew has a row here; nothing lives only in a
> chat log anymore.

---

## ✅ Where we are

| Release | Theme | Highlights |
|---------|-------|------------|
| v0.4.0 | The cozy core | floating panel, queue tools, pinning, hotkeys, radio |
| v0.5.0 | The library | search scopes, album pages, top tracks, shortcuts |
| v0.6.0 | The wide world | Discover (charts / moods / ~280 playlists) + World Explorer (74 genre stations) |
| v0.6.1 | The spotlight | **artist pages** (face, top tracks, releases, kindred acts) + **synced lyrics** (LRCLIB, glowing line, click-to-seek) |
| v0.6.2 | Glass & Motion | gradients, glass surfaces, shadows & accent glows, 3D rounded covers + floor reflection, view crossfades, glossy EQ bars |
| v0.6.3 | Keep the Fire Burning | self-healing playback: EndOfMedia relay, mid-song rejoin, stall watchdog, guarded error-skip |
| v0.7.0 | The Big Burn | memory & rituals (On Repeat, day history, Glow Mix, queue persistence, stats, export/import), the wider stage (lyrics overlay, theater, style closet, Ctrl+K, smart shuffle, wake-up alarm), reach (MPRIS, update whisper, diagnostics, AUR/winget/brew drafts), the festival (crossfade, plugin hooks, local library, ambient mixer, i18n scaffold, Discord RPC) |
| v0.7.1 | Smarts & reach | smart shelves (Most played, Recently loved, Rare gems), Rewind story, phone remote (LAN web remote) |
| v0.7.2 | Ember tending | the completers: ☕ café ambience, per-track volume nudges, play-count-weighted smart shuffle, per-leg fetch counters in diagnostics, the shareable Rewind card (📋 copy + 🖼 save-PNG) |
| v0.8.0 | The Long Winter Nights *(charted)* | the Sound Forge (EQ, loudness, karaoke, gapless), the Memory Palace (Rewind, rules, scrobbles, lyrics search, cache), Around the Fire (ambient mode, visualizer, share cards), the Far Reaches (web remote, parties, SMTC), the Open Hearth (gallery, docs, community kit) |

646 tests and counting, headless on a 3 OS × 2 Python CI matrix. Every
network layer is *never-raises*; the UI never blocks on the world.

---

## 🎯 How waves are chosen

1. **Cozy first** — an upgrade ships only if it makes the daily loop
   (open → play → sing along) warmer, not just feature-richer.
2. **Off the main thread** — anything that touches the network goes through
   the job pool; the UI is never allowed to wait.
3. **Headless or it didn't happen** — every wave lands with tests that run
   under `QT_QPA_PLATFORM=offscreen`, same as CI.
4. **No account walls** — Hearth stays keyless where its sources are
   keyless (YT Music, LRCLIB). Opt-in bridges are the only exceptions.

---

## 🔥 v0.7.0 — The Big Burn *(the one main version)*

*Shipped in v0.7.0.*

*Every add-on, one fire. Four rooms, built in order — Memory & Rituals →
The Wider Stage → Reach → The Festival. 🚧 marks the rows already under
construction.*

### 🕯️ Room 1 — Memory & Rituals

*The hearth should know you. This room makes Hearth remember.*

1. ✅ **Listen history** — `storage.log_play()` already records every play;
   surface it as a "Recently played" shelf and a full history page with
   day-jumps. Your past becomes a playlist. *(day-grouped storage + the
   full 🕘 History page with day chips and paging landed)*
2. ✅ **"On Repeat" smart playlist** — an auto-updating top-25 computed
   from play counts decayed so last week beats last year. Appears on Home
   next to your pins. *(decayed `on_repeat()` engine + Home shelf landed)*
3. ✅ **The Glow Mix** — a Friday-evening ritual: one tap builds a fresh mix
   from your heavy rotation + the related artists the v0.6.1 pages gave us.
4. ✅ **Queue persistence** — the queue, its order, and its position
   survive a restart. Close the laptop mid-song, open it on the same beat.
   *(snapshot save/restore + resume-on-play landed under test)*
5. ✅ **Discord Rich Presence** 🎮 — show the burning track on your profile
   via `pypresence` (opt-in): title, artist, elapsed time, "Listen along"
   button linking the YouTube URL Hearth already copies.
6. ✅ **Playlist export & import** — M3U plus a full JSON backup of
   playlists, favorites and history. Your library leaves the machine only
   when *you* say so, and comes back in one tap.
7. ✅ **Stats dashboard** — minutes listened, top artists and tracks,
   month-at-a-glance — all from the same play log. *(the shareable
   Rewind card — 📋 copy + 🖼 save-PNG — landed in v0.7.2)*

**Room bar:** history & On Repeat fully headless-tested; queue restores
in <1 s; Rich Presence never touches the audio path and degrades silently
when Discord is absent; export round-trips (export → wipe → import →
identical library) are covered by tests.

### 🎭 Room 2 — The Wider Stage

*The same fire, more rooms.*

1. ✅ **Desktop lyrics overlay** — the synced-lyrics engine steps out of the
   window: a frameless, always-on-top, click-through-except-draggable strip
   glowing the current line over any app. Karaoke for your whole desktop.
2. ✅ **Theater mode** — full-screen Now Playing: giant cover, huge synced
   lines, ambient palette glow. For the TV on the wall.
3. ✅ **Palette packs + theme editor** — `theme.py` palettes become importable
   packs; a small editor tweaks accent, glow and wallpaper with live
   preview. Your hearth, your colors. *(landed as the style closet +
   accent picker + wallpaper engine; glow fine-tuning is still ahead)*
4. ✅ **Per-track memory** — playback rate and volume nudges remembered per
   track (podcast at 1.75×, concert film at 1.0×, automatically). *(rate
   memory shipped; volume nudges landed in v0.7.2)*
5. ✅ **Lyrics settings & translation** — font, size and brightness controls
   for the lyric stage, plus an optional romanization / translation line
   beside the original text (keyless sources first). *(font, size & family
   settings shipped; brightness and the translation line are still ahead)*
6. ✅ **Ctrl+K command palette** — every action reachable from one fuzzy
   palette, keyboard-only from launch to full-volume. Power users, met.
7. ✅ **Ambient mixer** — campfire, rain and café loops layered under the
   music at their own volume. It's called Hearth; the fire should be
   audible. *(procedural campfire & rain shipped; the café loop landed
   in v0.7.1)*
8. ✅ **Wake-up alarm** — the sleep timer's sibling: fade in a station or
   playlist at a set time, gentle exponential ramp in reverse.

**Room bar:** overlay composites at 60 fps with zero audio interference;
themes are pure data files (no code); lyrics rendering changes never block
the audio path; everything survives the offscreen suite.

### 📦 Room 3 — Reach

*Every desktop means every desktop.*

1. ✅ **AUR publication** — `hearth-music` on the Arch User Repository
   (the `packaging/` recipes graduate to a real PKGBUILD + git tag flow).
   *(the `hearth-music` PKGBUILD draft ships in `packaging/`; publication
   itself waits on the first tagged release artifact)*
2. ✅ **Windows winget + macOS Homebrew/cask manifests** — one-command installs
   on the other two CI platforms. *(draft manifests ship in `packaging/`,
   placeholder digests until the first release artifacts)*
3. ✅ **Update whisper** — a polite, dismissible "a newer hearth is lit"
   note (checks GitHub releases; never auto-downloads, never nags twice).
4. ✅ **Diagnostics report** — one dialog that shows which fetch leg served
   each shelf (catalogue → web → flat index), powered by `ytm_resilience`
   counters. Bug reports go from "it's broken" to "leg 2 timed out".
   *(the tray report shipped — identity, look, database rows, resilience
   and log tail; per-leg fetch counters landed in v0.7.2)*
5. ✅ **MPRIS + media keys** — real desktop integration: MPRIS2 on Linux,
   SMTC on Windows — lockscreen and media-key play/pause/next work even
   when the window is buried. The desktop finally knows Hearth is lit.
   *(MPRIS2 shipped, fake-bus tested; Windows SMTC is still ahead)*

**Room bar:** fresh-machine installs verified on all three OSes; the
update check is off by default in tests and never blocks startup; MPRIS
signals are headless-tested with a fake bus.

### 🎪 Room 4 — The Festival

*The 1.0 bar: nothing left that a listener would call "missing".*

1. ✅ **Gapless playback** — pre-resolve the next track in the queue while the
   current one plays; crossfade option (0–3 s) on the player bar.
   *(the pre-resolve groundwork + equal-power crossfade shipped; a true
   gapless handoff is still ahead)*
2. **Native backend probe** — a pluggable playback core behind
   `PlaybackCore`, starting with an mpv-backed variant that unlocks a real
   equalizer and bit-perfect output where the OS allows it.
3. ✅ **Plugin hooks** — a tiny, versioned extension surface (one JSON
   manifest + one Python entry point) so shelf sources and palette packs
   can be added without forking.
4. ✅ **Multi-language UI** — strings extracted, community translations
   welcome; Hindi and Spanish first. *(the en/hi/es string-table scaffold
   shipped; full string extraction is still ahead)*
5. ✅ **Smart shuffle** — a shuffle that reads your play counts: artists
   spread out, nothing repeats until the queue is spent, favorites surface
   a little more often. Shuffle with taste. *(artist spread + recently-heard
   rest shipped; play-count-weighted surfacing landed in v0.7.2)*

---

## 🔮 v0.8.0 — The Long Winter Nights *(the next wave — charted 2026-09-18)*

*Every feature suggested in the crew chat, deduped against what v0.7.0
already shipped, gathered into five rooms. ♻️ marks stragglers —
half-shipped pieces already tracked elsewhere in this file — that this
wave closes out for good.*

### 🎛️ Room 5 — The Sound Forge

*Warmth you can hear. This room makes the audio itself cozy.*

1. **10-band equalizer + presets** — the native backend probe graduates: an
   mpv-backed `PlaybackCore` unlocks a real EQ (Flat, Bass Boost, Vocal
   Clamp, Late Night, plus a user preset slot). Presets are pure JSON —
   same data-file rule as palettes. *(accepts: A/B toggle, per-output-device
   memory, off-by-default when backend probe fails)*
2. **Loudness normalization** — the catalog's loudness hints become a
   ReplayGain-style pass: no more reaching for the volume knob when a
   quiet acoustic track follows a mastered-to-death single. *(accepts:
   per-track and per-playlist modes; measured once, cached in SQLite)*
3. **Global speed knob** — per-track rate memory already exists; add the
   session-wide 0.5×–2.0× dial on the player bar with pitch preservation.
   *(accepts: keyboard shortcuts, survives track changes, never fights
   per-track memory — session dial wins until cleared)*
4. **Karaoke mode** — center-channel cancellation ducks the vocal when the
   mix allows it; the synced-lyrics stage goes full-width while it's on.
   Keyless, DSP-only, honest failure: if the mix defeats the trick, the
   toggle says so instead of pretending. *(accepts: offscreen DSP tests on
   synthetic stereo fixtures; auto-off on mono sources)*
5. ♻️ **True gapless handoff** — crossfade shipped in v0.7.0; finish the
   pre-resolved next-track handoff so live albums and DJ mixes play like
   the artist intended. *(accepts: <50 ms seam on synthetic fixtures,
   fallback to crossfade when pre-resolve fails)*

**Room bar:** EQ and normalization never touch the UI thread; every DSP
toggle is headless-tested; disabling a DSP feature restores bit-identical
output paths.

---

### 🏮 Room 6 — The Memory Palace

*The hearth should know you — and show off what it knows.*

1. **Listening Rewind** 🎁 — the Wrapped-style year-in-review the stats
   dashboard promised: top tracks, artists, genres, minutes by the fire,
   listening personality card, all rendered as a shareable swipeable story
   from the same play log. *(accepts: headless-rendered cards, one-tap
   export as PNG set, zero data leaves the machine)*
2. **Smart-playlist rules builder** — On Repeat and Glow Mix were the
   prototypes; this is the general case: "played ≥5 times last month",
   "added this week AND artist ~likes", genre moods — rules stored as
   data, evaluated on the job pool, refreshed on Home like any shelf.
   *(accepts: rules import/export as JSON, honest empty state, no query
   ever blocks the UI)*
3. **Scrobble bridges, finished** — the v0.7.0 keyed queue + signing grows
   its opt-in onboarding (Last.fm), and gains a **ListenBrainz** bridge
   (open protocol, fits the keyless spirit). Offline scrobbles queue and
   drain when the network returns. *(accepts: never gates playback, fail
   silently into the queue, full payload round-trip tests)*
4. **Lyrics-line search** — paste a line you half-remember into the search
   box; Hearth matches against the LRCLIB text it already caches. The
   fastest "what song says…" answer on any desktop. *(accepts: works from
   cache offline, scores results, deep-links to the glowing line)*
5. **Cache manager** — diagnostics grew a log tail; now show the caches
   themselves: covers, lyrics, stream pre-resolve — with sizes and a
   broom. *(accepts: per-cache clear with one tap, size shown without
   blocking, safe-while-playing guarantee)*

**Room bar:** Rewind renders from local data only; rules engine ships
with its own fuzz tests; scrobble failures can never surface as UI errors.

---

### 🔥 Room 7 — Around the Fire

*The brand, turned up. Nobody else can ship these.*

1. **Ambient Hearth mode** 🪵 — the signature feature: one toggle dims the
   UI, brings up the animated fireplace, layers the procedural campfire
   under the music, and lets the full-screen visualizer dance in the
   flames. A screensaver, a mood, and an identity in one. *(accepts:
   GPU-cheap at 60 fps, pairs with the existing ambient mixer volumes,
   auto-exits on any playback interaction)*
2. **Full Now-Playing visualizer** — the mini bars in the player bar grow
   up: a spectrum / waveform / ember-particle mode for the Now Playing
   pane, palette-colored per the style closet. *(accepts: three modes,
   fps floor of 60 on the CI machines, degrades to the mini bars
   gracefully on weak GPUs)*
3. **Share cards** — a gorgeous auto-composed PNG of what's burning: cover
   art, title/artist, one glowing lyric line, and a QR to the track.
   Styled by the active palette so every card looks like its hearth.
   *(accepts: rendered offscreen with the same engine as the screenshots,
   no network calls, one-tap save/copy)*

**Room bar:** visualizer samples never block or allocate per-frame on the
audio path; share cards are byte-identical across renders of the same
state; all three features survive the offscreen suite.

---

### 🕹️ Room 8 — The Far Reaches

*Every desktop, and now the phone on the couch.*

1. **Web remote** — scan a QR, open a tiny LAN-only page: play/pause, next,
   volume, queue reorder, and a "send to queue" search. Zero accounts, zero
   cloud — the phone and the hearth just talk. *(accepts: binds to LAN by
   default with a confirm dialog, token-paired on first scan, headless
   API tests)*
2. **Listening parties** 🎉 *(promoted from the wish pool)* — the web
   remote's big sibling: a shared queue link where everyone adds tracks
   and votes the next one up. Party mode keeps host playback authoritative.
   *(accepts: host-only transport, vote settles <1 s on LAN, spectator
   mode can never pause the host's music)*
3. ♻️ **Windows SMTC** — the MPRIS2 row's twin finishes: lockscreen and
   media keys on Windows, same fake-bus test discipline via the SMTC
   shim. *(accepts: CI on windows-latest asserts play/pause/next events)*
4. ♻️ **Per-leg fetch counters** — the diagnostics dialog starts showing
   which fetch leg served each shelf, finishing the tray-report promise.
   *(accepts: counters visible in the existing dialog, zero overhead when
   diagnostics is closed)*

**Room bar:** the remote server starts only from an explicit user action;
party queues degrade to solo mode when peers vanish; SMTC events are
tested with the same rigor as MPRIS.

---

### 🧱 Room 9 — The Open Hearth

*So the crew can grow the fire without forking it.*

1. **Palette & shelf gallery** — plugin hooks v0.7.0 shipped the surface;
   this ships the venue: a browsable gallery of community palette packs
   and shelf sources, installed from a URL or a local file, reviewed by
   the same headless test harness before they can land. *(accepts:
   manifest versioning enforced, one-click install/remove, sandboxed to
   the documented surface)*
2. **Docs site** — the README's warmth, expanded: install guides per OS,
   hotkey cheatsheet, plugin authoring tutorial, and the architecture
   diagrams already committed as SVGs. Static, keyless, fast.
3. **Community kit** — CONTRIBUTING.md, issue templates (bug / feature /
   the inevitable "lyrics wrong" triage), `good first issue` labels, and a
   PR checklist that mirrors the wave rules. *(accepts: a brand-new
   contributor can go from fork to green CI without asking in chat)*

**Room bar:** gallery items are pure data/entry-point plugins — no
forking required; docs build in CI; every template links back to the
standing guardrails.

---

### 🧹 Stragglers ledger *(already tracked — closed inside this wave)*

- Café loop for the ambient mixer *(Room 2 follow-up → ships with Room 7.1)*
- Glow fine-tuning in the style closet *(→ ships with Room 7.2's palette work)*
- Volume nudges in per-track memory *(→ ships with Room 5.3's speed knob)*
- Lyrics brightness + translation line *(→ ships with Room 6.4's lyrics work)*
- Play-count-weighted smart shuffle *(→ ships with Room 6.2's rules engine)*

---

## 🌱 Wish pool

*Not scheduled, not forgotten — promoted into a room when the fire is ready:*

- ✅ Last.fm scrobbling bridge (opt-in, keyed) — *(groundwork shipped in
  v0.7.0: the keyed scrobble queue, signing and payload builder live in
  `hearth/scrobble.py`; wiring it into playback waits for account
  onboarding)*
- ✅ Local music library side-by-side with YT Music shelves — *(shipped in
  v0.7.0 as the 📁 Local tab + folder scanner)*
- Podcasts & audiobooks shelf (per-track speed memory makes this sing)
- Listening parties — share a queue link, synced "next track" voting —
  *(promoted into v0.8 Room 8 — The Far Reaches)*
- ✅ Mini-visualizer in the player bar (palette-colored, GPU-cheap) —
  *(shipped in v0.7.0)*

---

## 🛡️ Standing guardrails

- The catalogue never raises; a dead shelf is an empty shelf with a note.
- Every job runs on the worker pools; the UI thread only paints.
- Lyrics and metadata stay keyless; opt-in bridges never gate core playback.
- Every room lands with headless tests; CI stays 3 OS × 2 Python green.
- Only this repo's own shelves are touched — no account data leaves the
  machine except to the services the user chose.
- New in v0.8: **audio DSP may add latency to *start*, never to
  *control*** — seek/pause/volume respond instantly even while the Forge
  is churning.
