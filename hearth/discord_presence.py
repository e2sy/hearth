"""Discord Rich Presence — the hearth goes social (opt-in).

While enabled, hearth whispers what's playing to your Discord profile:
title, artist, elapsed timestamps, and a "Listen along" button straight
to the track. The bridge is deliberately guarded — pypresence is an
optional extra, not a dependency::

    pip install hearth-music[discord]

Where pypresence is absent the module still imports cleanly (CI, plain
installs) and :class:`DiscordPresence` becomes a silent no-op twin with
the exact same API: ``start`` reports False, ``update_track``/``clear``
do nothing, ``stop`` tidies nothing. Every network surprise is swallowed
— a dead Discord client degrades to ``ok=False`` with a ≥60 s retry
backoff, never an exception, and the audio path never hears about it.

The pure pieces (:class:`Throttle`, :func:`presence_payload`) carry no
Qt and no I/O, so the rate limiting and the payload shape are testable
headless.
"""

from __future__ import annotations

import time
from typing import Callable

from .models import Track

try:                     # pragma: no cover - exercised only where installed
    from pypresence import Presence as _RealPresence

    AVAILABLE = True
except Exception:        # noqa: BLE001 - ImportError, and exotic installs too
    _RealPresence = None  # type: ignore[assignment]
    AVAILABLE = False

__all__ = ["AVAILABLE", "DiscordPresence", "Throttle", "presence_payload"]


class Throttle:
    """Pure rate limiter: at most one pass per ``window_s`` seconds.

    The first call always passes; calls inside the window are refused;
    a call at (or past) the boundary passes and re-arms. ``stamp()``
    re-arms without passing (used right after an out-of-band push so
    the next tick waits a full window). The clock is injectable so
    tests can walk time by hand — no Qt, no sleeping.
    """

    def __init__(self, window_s: float, clock: Callable[[], float] | None = None):
        self._window = max(0.0, float(window_s))
        self._now = clock or time.monotonic
        self._last: float | None = None

    def allow(self) -> bool:
        """True once per window; the passing call stamps the clock."""
        now = self._now()
        if self._last is None or (now - self._last) >= self._window:
            self._last = now
            return True
        return False

    def stamp(self) -> None:
        """Mark 'just pushed' — the next ``allow()`` waits a full window."""
        self._last = self._now()

    def reset(self) -> None:
        """Forget the last pass — the next call goes through immediately."""
        self._last = None


def presence_payload(
    track: Track | None,
    elapsed_s: float | None = None,
    duration_s: float | None = None,
    youtube_url: str = "",
    now: float | None = None,
) -> dict:
    """The pypresence ``update()`` dict for one track — pure and testable.

    ``start``/``end`` are epoch seconds (what Discord expects): start is
    rewound from the live elapsed time, end extends it by the duration
    when one is known. The "Listen along" button appears only when a
    URL exists; a missing track yields an empty dict (nothing to show).
    ``now`` is injectable for tests; real callers use the wall clock.
    """
    if track is None:
        return {}
    title = str(track.title or "").strip()
    if not title:
        return {}
    artist = str(track.artist or "").strip()
    payload: dict = {
        "details": title,
        "state": artist or "Unknown artist",
        # tracks carry no album field — the artist is the honest "album-ish"
        "large_image": "hearth",
        "large_text": artist or "Hearth",
    }
    stamp = time.time() if now is None else float(now)
    if elapsed_s is not None and elapsed_s >= 0:
        start = int(stamp - float(elapsed_s))
        payload["start"] = start
        if duration_s is not None and duration_s > 0:
            payload["end"] = start + int(duration_s)
    if youtube_url:
        payload["buttons"] = [{"label": "Listen along", "url": youtube_url}]
    return payload


class DiscordPresence:
    """Rich presence bridge that never raises and never touches audio.

    One instance per app. ``start(client_id)`` connects (False on any
    failure, with ``ok`` flipped accordingly); ``update_track`` pushes
    one track's presence; ``clear`` wipes it between tracks/stops;
    ``stop`` closes the IPC on shutdown. With pypresence absent the
    whole class degrades to a no-op with the same API. After a failed
    connect or a dead RPC, retries are held back for
    ``backoff_s`` (≥60 s) so a closed Discord client is never spammed.
    """

    def __init__(self, backoff_s: float = 60.0,
                 clock: Callable[[], float] | None = None):
        self.ok = False
        self._backoff = max(0.0, float(backoff_s))
        self._now = clock or time.monotonic
        self._last_fail = float("-inf")   # monotonic stamp of the last failure
        self._client_id = ""
        self._rpc = None

    # --- lifecycle ---

    def start(self, client_id: str) -> bool:
        """Connect to Discord. False when unavailable/off/failed — never raises."""
        self._client_id = str(client_id or "").strip()
        self.ok = False
        if not AVAILABLE or not self._client_id:
            return self.ok
        return self._connect()

    def _connect(self) -> bool:
        if self._now() - self._last_fail < self._backoff:
            return self.ok   # a dead Discord earns silence, not a retry storm
        try:
            self._rpc = _RealPresence(client_id=self._client_id)
            self._rpc.connect()
            self.ok = True
        except Exception:    # noqa: BLE001 - IPC trouble is a fact of life here
            self._rpc = None
            self.ok = False
            self._last_fail = self._now()
        return self.ok

    def stop(self) -> None:
        """Drop the IPC quietly (idempotent, safe at interpreter shutdown)."""
        if self._rpc is not None:
            try:
                self._rpc.close()
            except Exception:  # noqa: BLE001 - the way out must stay open
                pass
        self._rpc = None
        self.ok = False

    # --- presence ---

    def update_track(
        self,
        track: Track | None,
        elapsed_s: float | None = None,
        duration_s: float | None = None,
        youtube_url: str = "",
    ) -> bool:
        """Push presence for one track. False when down (or nothing to say)."""
        if track is None:
            return False
        if not self.ok or self._rpc is None:
            # one polite reconnect attempt per backoff window, not per tick
            if not self._client_id or not self._connect() or self._rpc is None:
                return False
        payload = presence_payload(track, elapsed_s, duration_s, youtube_url)
        if not payload:
            return False
        try:
            self._rpc.update(**payload)
            return True
        except Exception:    # noqa: BLE001 - Discord vanished mid-song
            self.ok = False
            self._rpc = None
            self._last_fail = self._now()
            return False

    def clear(self) -> None:
        """Wipe the presence (between tracks / when playback stops)."""
        if not self.ok or self._rpc is None:
            return
        try:
            self._rpc.clear()
        except Exception:    # noqa: BLE001 - already gone: just mark it
            self.ok = False
            self._rpc = None
            self._last_fail = self._now()
