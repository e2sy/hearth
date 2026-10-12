# Roadmap — Android port for hearth

## TL;DR

A working `hearth.apk` is **not buildable today** from the existing
PyQt6 codebase. This document explains the hard technical constraint
and lays out the realistic paths forward, in priority order.

## The hard constraint

`hearth` is a **PyQt6** application. PyQt6 wraps the **Qt 6** toolkit
from The Qt Company, and Qt's official Android target (`qt5-android`
historically, `qt6-android` today) is a **native Java/Kotlin toolkit** —
the Python bindings (`PyQt6`, `PySide6`) do **not** expose the Android
backend.

Concretely:

| What you'd need                  | Status today                          |
| -------------------------------- | ------------------------------------- |
| `PyQt6` wheels for Android       | **does not exist** on PyPI            |
| `PySide6` wheels for Android     | experimental, ships a few modules    |
| `python-for-android` recipes      | only support Kivy / SDL2 / Toga       |
| Qt 6 Android module (`Qt6Android`)| exists in the native toolkit only    |
| Qt 6 Multimedia on Android       | uses Android `MediaPlayer`, **not**   |
|                                  | exposed via the Python bindings       |

Every "build a PyQt6 APK" tutorial on the internet from 2018 onward
either targets Qt5 (deprecated on Android), uses an unmaintained
fork, or quietly produces a non-functional stub. There is no path
from the current codebase to a working `.apk` without a UI rewrite.

## Realistic paths forward (in priority order)

### 1. Ship the existing phone-remote as an installable PWA

`hearth` already has a phone-friendly remote-control UI in
`hearth/remote.py`. Wrapping that URL in a service-worker manifest
gives users an "app" they can pin to their Android home screen with
one tap. Zero code rewrite. **~2 days of work.**

- Add `manifest.json` + `sw.js` served by the existing `RemoteServer`
- Generate the SVG hearth icons at 192×192 / 512×512
- Document the "Add to Home Screen" flow per browser
- Users get an icon, full-screen, offline-cached shell

### 2. Thin native wrapper around the remote

A tiny Kotlin app that's just a `WebView` pointed at
`http://hearth.local:8765/`. Gets a real APK, no PyQt anywhere,
behaves identically to the PWA but ships via the Play Store (or
sideload). **~1 week.**

- Single-activity Kotlin app
- WebView with `WebSettings.domStorageEnabled = true`
- Bundle the hearth SVG as the launcher icon
- ~50 KB APK, no Qt, no Python

### 3. Full port to BeeWare (Toga) or Kivy

A faithful rewrite that reuses the **non-UI** layers
(`hearth/catalog.py`, `hearth/storage.py`, `hearth/stream.py`,
`hearth/player.py`, `hearth/lyrics.py`) and replaces only the UI
(`hearth/window.py`, `hearth/panel.py`, `hearth/app.py`, all the
`*_dialog.py` files). **~4–6 weeks.**

- `catalog.py`, `storage.py`, `stream.py` are pure Python — they
  work on Android unchanged
- `player.py` would need a `MediaHandle` implementation that uses
  ExoPlayer instead of `QMediaPlayer` (~1 day)
- The 90+ UI files would need full rewrites in the new framework
- Toga is the cleanest cross-platform choice today (it has an
  Android backend shipping in 2024+)
- Kivy is more mature but its widget set doesn't map cleanly to a
  desktop-first design like hearth's

### 4. Wait for Qt for Android via Python

The Qt Company has signaled that Android is a first-class target for
Qt 6, but the Python bindings (`PyQt6`/`PySide6`) lag the native
release by 12–24 months. There is no announced timeline for a Python-
scriptable Android Qt. **Not actionable today.**

## Recommendation

**Ship #1 (the PWA) now.** It costs ~2 days, gives users something
to put on their phone home screen today, and unblocks the "I want
hearth on Android" requests while the long-term port is considered.
**Skip #2** unless Play Store distribution is a hard requirement
(sideload-only users get the same UX from #1). **Treat #3 as a
Q4 project**, not a build step.
