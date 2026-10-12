"""Windows SMTC: the hearth answers the lockscreen and media keys (guarded).

The MPRIS row's twin. Room 8.3 calls for the same test discipline as
the Linux side, so the whole SMTC surface lives in three pure mappers
— ``metadata_map`` / ``timeline_map`` / ``button_command`` — that build
plain dicts with zero winsdk in sight. A platform bridge is *injected*
(the fake-bus pattern): tests pass a recorder, the future Windows
bridge passes the real ``SystemMediaTransportControls`` applier.

On any box without the optional ``winsdk`` binding the module still
imports cleanly, ``SMTC_AVAILABLE`` is False, and ``SmtcService``
degrades to a silent no-op with the same API — exactly like the MPRIS
service does without dbus. The audio path is never touched.

The real Windows bridge lives in :class:`_WindowsBridge` below; it is
constructed lazily via :func:`create_windows_bridge` (returns ``None``
on any non-Windows / non-winsdk box, or on any failure to claim the
SMTC slot, e.g. when running headless in tests). The bridge is a
``(metadata, timeline) -> None`` callable plus an optional
``on_command`` callback wired to the OS's ``ButtonPressed`` event —
the same fake-bus contract the tests use.
"""

from __future__ import annotations

import logging
from typing import Any, Callable

from .models import Track, parse_duration

log = logging.getLogger(__name__)

try:                       # optional Windows binding — absent on Linux/macOS CI
    import winsdk.windows.media.control as _wmc  # type: ignore[import-not-found]
    _WINSDK_WHY = ""
except Exception as _exc:  # noqa: BLE001 - ImportError *or* broken native lib
    _wmc = None            # type: ignore[assignment]
    _WINSDK_WHY = str(_exc)

SMTC_AVAILABLE = _wmc is not None

# The desk gets a position tick once a second — the firehose of position
# updates is throttled into one polite push per period (mirrors MPRIS).
POSITION_THROTTLE_MS = 1000

# SMTC button labels → the hearth remote's command names
_BUTTON_COMMANDS = {
    "playpause": "toggle",
    "play": "play",
    "pause": "pause",
    "stop": "pause",
    "next": "next",
    "previous": "prev",
}

# playback states the lockscreen understands
STATUS_PLAYING = "PLAYING"
STATUS_PAUSED = "PAUSED"
STATUS_STOPPED = "STOPPED"


# ----------------------------------------------------------------- pure mappers

def playback_status(playing: bool | None) -> str:
    """True → PLAYING, False → PAUSED, None → STOPPED."""
    if playing is None:
        return STATUS_STOPPED
    return STATUS_PLAYING if playing else STATUS_PAUSED


def button_command(name: str) -> str | None:
    """An SMTC button press → the hearth command it means (None = ignore)."""
    return _BUTTON_COMMANDS.get((name or "").strip().lower())


def metadata_map(track: Track | None) -> dict:
    """The SMTC-shaped metadata dict for one track — plain types only.

    Mirrors MPRIS's ``metadata_map``: the lockscreen gets a title, an
    artist, the art, and the music.youtube.com URL, all strings.
    """
    if track is None:
        return {}
    seconds = track.duration_sec or parse_duration(track.duration)
    meta: dict[str, Any] = {
        "video_id": str(track.video_id or ""),
        "title": str(track.title or ""),
        "artist": str(track.artist or ""),
        "album": str(getattr(track, "album", "") or ""),
        "url": f"https://music.youtube.com/watch?v={track.video_id}",
        "duration_ms": int(max(0.0, float(seconds)) * 1000),
    }
    if track.thumbnail:
        meta["thumbnail"] = str(track.thumbnail)
    return meta


def timeline_map(
    position_ms: int | None,
    duration_ms: int | None,
    playing: bool | None,
) -> dict:
    """The SMTC timeline triple: position, window, and play state.

    Negative positions clamp to 0; the end time never lands before the
    position; ``None`` position means 'stopped at zero'.
    """
    position = max(0, int(position_ms or 0))
    duration = max(0, int(duration_ms or 0))
    return {
        "position_ms": position,
        "end_ms": max(position, duration),
        "status": playback_status(playing),
    }


# ----------------------------------------------------------------- the service

BridgeApplier = Callable[[dict, dict], None]


class SmtcService:
    """Feeds an injected bridge with SMTC-shaped snapshots.

    ``bridge`` is any callable ``(metadata, timeline) -> None`` — the
    fake-bus pattern from the MPRIS tests. Without one (and without a
    winsdk binding) the service is an honest no-op: ``start()`` returns
    False and every update is absorbed, so the app can wire it once and
    forget the platform question entirely.

    The optional :meth:`connect` mirrors :class:`MprisService.connect`:
    it subscribes the service to the playback core's signals and runs
    a one-second throttle so a busy lockscreen never sees a firehose of
    position ticks. ``on_command``, when supplied, is the conduit for
    OS-side transport button presses (play / pause / next / prev).
    """

    def __init__(
        self,
        bridge: BridgeApplier | None = None,
        get_track: Callable[[], Track | None] | None = None,
        is_playing: Callable[[], bool | None] | None = None,
        get_position_ms: Callable[[], int | None] | None = None,
        get_duration_ms: Callable[[], int | None] | None = None,
        on_command: Callable[[str], None] | None = None,
    ):
        self._bridge = bridge
        self._get_track = get_track
        self._is_playing = is_playing
        self._get_position = get_position_ms
        self._get_duration = get_duration_ms
        self._on_command = on_command
        self._started = False
        # Signal-wired state (only populated when connect() is called)
        self._core = None
        self._timer = None
        self._position_ms = 0
        self._duration_ms = 0
        self._last_pushed_pos = -1
        self._last_pushed_status = ""

    @property
    def available(self) -> bool:
        return self._bridge is not None or SMTC_AVAILABLE

    # --- lifecycle ---

    def start(self) -> bool:
        """Claim the lockscreen slot; True only when a bridge accepted."""
        self._started = self._bridge is not None or SMTC_AVAILABLE
        return self._started

    def stop(self) -> None:
        """Leave the stage quietly (idempotent).

        Stops the throttle timer (if one was started) and marks the
        service as not started. The bridge itself is owned by the
        caller (typically the app) and is not torn down here — the OS
        will reclaim the SMTC slot when the process exits.
        """
        if self._timer is not None:
            try:
                self._timer.stop()
            except Exception:  # noqa: BLE001 - shutdown must never bite
                pass
            self._timer = None
        # Push a final STOPPED so the lockscreen doesn't keep flashing
        # the last track as 'still playing' after we've gone away.
        try:
            self._push_final_stopped()
        except Exception:  # noqa: BLE001
            pass
        self._started = False

    def connect(self, core) -> None:
        """Subscribe to the core (never raises, even on a broken core).

        Mirrors :meth:`MprisService.connect`: binds the same signals
        the tray uses, starts a one-second throttle, and lets the OS
        push transport-button presses back through ``on_command``.
        Safe to call on any platform — when ``start()`` returned False
        (no bridge, no winsdk) the handlers early-out and the timer
        runs idle.
        """
        self._core = core
        try:
            from PyQt6.QtCore import QTimer

            core.track_changed.connect(self._on_track_changed)
            core.state_changed.connect(self._on_state_changed)
            core.position_changed.connect(self._on_position)
            core.duration_changed.connect(self._on_duration)
            self._timer = QTimer(core)
            self._timer.setInterval(POSITION_THROTTLE_MS)
            self._timer.timeout.connect(self._push_tick)
            self._timer.start()
        except Exception as exc:  # noqa: BLE001 - wiring must never bite
            log.debug("SMTC connect degraded: %s", exc)

    def handle_button(self, name: str) -> str | None:
        """Map an SMTC button press to the hearth command it means."""
        return button_command(name)

    def update(self) -> bool:
        """Push the current snapshot to the bridge. Never raises.

        Missing getters degrade field-by-field — a snapshot with an
        unknown position still updates the title. False means 'nothing
        to say' (no bridge, no track, or the bridge exploded).
        """
        if not self._started or self._bridge is None:
            return False
        track = self._safe(self._get_track)
        if track is None:
            return False
        metadata = metadata_map(track)
        timeline = timeline_map(
            self._safe(self._get_position),
            self._safe(self._get_duration) or metadata.get("duration_ms"),
            self._safe(self._is_playing),
        )
        try:
            self._bridge(metadata, timeline)
        except Exception as exc:  # noqa: BLE001 - lockscreen lies still lie quietly
            log.info("smtc bridge failed: %s", exc)
            return False
        return True

    # --- core signal handlers (each wrapped never-raises) ---

    def _on_track_changed(self, _track) -> None:
        """A new song clears the position; the next tick will push it."""
        try:
            self._position_ms = 0
            self._last_pushed_pos = -1
            self._duration_ms = max(0, int(self._safe(self._get_duration) or 0))
            self._push_now()
        except Exception as exc:  # noqa: BLE001
            log.debug("SMTC track push failed: %s", exc)

    def _on_state_changed(self, _playing: bool) -> None:
        try:
            self._push_now()
        except Exception as exc:  # noqa: BLE001
            log.debug("SMTC state push failed: %s", exc)

    def _on_position(self, position_ms: int) -> None:
        """Cheap: remember the tick; the 1s throttle does the talking."""
        try:
            self._position_ms = max(0, int(position_ms))
        except Exception:  # noqa: BLE001
            pass

    def _on_duration(self, duration_ms: int) -> None:
        try:
            self._duration_ms = max(0, int(duration_ms))
        except Exception:  # noqa: BLE001
            pass

    def _push_tick(self) -> None:
        """One polite push per second when something visibly changed."""
        try:
            core = self._core
            if core is not None:
                # The live backend's position always wins over the cached tick.
                live = self._safe(self._get_position)
                if live is not None:
                    self._position_ms = max(0, int(live))
            # Only push when something actually moved or the play state flipped.
            status = self._safe(self._is_playing)
            status_str = playback_status(status)
            if self._position_ms == self._last_pushed_pos and \
                    status_str == self._last_pushed_status:
                return
            self._push_now()
        except Exception as exc:  # noqa: BLE001
            log.debug("SMTC tick push failed: %s", exc)

    def _push_now(self) -> None:
        """Build a snapshot from the live getters and push it to the bridge."""
        if not self._started or self._bridge is None:
            return
        track = self._safe(self._get_track)
        if track is None:
            return
        metadata = metadata_map(track)
        timeline = timeline_map(
            self._position_ms,
            self._duration_ms or metadata.get("duration_ms"),
            self._safe(self._is_playing),
        )
        self._last_pushed_pos = timeline["position_ms"]
        self._last_pushed_status = timeline["status"]
        try:
            self._bridge(metadata, timeline)
        except Exception as exc:  # noqa: BLE001 - lockscreen lies still lie quietly
            log.info("smtc bridge failed: %s", exc)

    def _push_final_stopped(self) -> None:
        """Tell the lockscreen the music has gone quiet before we exit."""
        if not self._started or self._bridge is None:
            return
        track = self._safe(self._get_track)
        metadata = metadata_map(track) if track is not None else {}
        timeline = timeline_map(0, metadata.get("duration_ms", 0), None)
        try:
            self._bridge(metadata, timeline)
        except Exception:  # noqa: BLE001
            pass

    def _safe(self, getter: Callable | None) -> Any:
        try:
            return getter() if getter is not None else None
        except Exception:  # noqa: BLE001 - a getter hiccup is a missing field
            return None


# ----------------------------------------------------------------- Windows bridge


def create_windows_bridge(
    on_command: Callable[[str], None] | None = None,
) -> BridgeApplier | None:
    """Build a real ``winsdk``-backed SMTC bridge, or ``None`` on any failure.

    Returns a callable ``(metadata, timeline) -> None`` that pushes the
    snapshot to the live ``SystemMediaTransportControls`` for the
    current view. Button presses from the OS (play / pause / next /
    prev) are routed through :func:`button_command` and then
    ``on_command(cmd)`` if provided — passing ``None`` for
    ``on_command`` makes button presses silently ignored (the lockscreen
    still displays, the controls just don't drive the app).

    On any non-Windows box, on any box without ``winsdk`` installed,
    when the SMTC slot can't be claimed (e.g. headless test mode), or
    when any of the late imports fail, this returns ``None`` so the
    caller can wire :class:`SmtcService` with no bridge and degrade
    cleanly to the no-op twin.
    """
    if _wmc is None:
        return None
    try:
        return _WindowsBridge(on_command)
    except Exception as exc:  # noqa: BLE001 - any setup failure is a no-bridge
        log.info(
            "SMTC bridge unavailable (%s) — running without lockscreen integration",
            exc,
        )
        return None


class _WindowsBridge:
    """Pushes snapshots to a real ``SystemMediaTransportControls`` instance.

    Constructed lazily by :func:`create_windows_bridge` so the winsdk
    imports stay inside a single late-import path. The bridge is a
    callable ``(metadata, timeline) -> None``; the SMTC controls,
    display updater, and timeline properties are claimed once at
    construction and reused across calls. Cheap field-level diffing
    keeps the per-tick work small (the lockscreen only sees an update
    when the title, the artist, or the playback state actually changes).

    Thumbnail loading is *not* attempted here — the lockscreen still
    shows the title/artist without art, which is a known first-cut.
    Fetching a remote URL into a ``RandomAccessStream`` requires an
    async round-trip per track; that's a follow-on, not a blocker.
    """

    # SystemMediaTransportControlsButton enum value (as string) → SMTC name.
    # The winsdk binding exposes the enum values as small ints; the names
    # below match the canonical enum labels so `button_command` can map them.
    _BUTTON_NAMES = {
        0: "play",
        1: "pause",
        2: "stop",
        3: "next",
        4: "previous",
        5: "fast_forward",
        6: "rewind",
        7: "channel_up",
        8: "channel_down",
        9: "record",
        10: "play_pause",
    }

    def __init__(self, on_command: Callable[[str], None] | None = None):
        self._on_command = on_command
        self._smtc = None
        self._updater = None
        self._music = None
        self._timeline = None
        # Cache the winsdk enum singletons so we don't repeatedly
        # re-resolve them through getattr() in the hot path.
        self._status_playing = None
        self._status_paused = None
        self._status_stopped = None
        self._last_title = ""
        self._last_artist = ""
        self._last_status = ""
        self._last_pos_ms = -1
        self._last_end_ms = -1
        self._setup()

    def _setup(self) -> None:
        """Late-import winsdk and claim the SMTC slot. Raises on any failure."""
        # Late imports — keeps the module's import-time surface tiny and
        # lets the SMTC_AVAILABLE guard in the parent module fire first.
        from winsdk.windows.media import MediaPlaybackStatus, MediaPlaybackType
        from winsdk.windows.media.control import SystemMediaTransportControls

        self._status_playing = MediaPlaybackStatus.PLAYING
        self._status_paused = MediaPlaybackStatus.PAUSED
        self._status_stopped = MediaPlaybackStatus.STOPPED

        self._smtc = SystemMediaTransportControls.get_for_current_view()
        self._smtc.is_enabled = True
        # Only the four transport buttons we actually handle are enabled.
        self._smtc.is_play_enabled = True
        self._smtc.is_pause_enabled = True
        self._smtc.is_next_enabled = True
        self._smtc.is_previous_enabled = True
        self._smtc.is_stop_enabled = True
        # The rest are off so the lockscreen doesn't offer dead controls.
        self._smtc.is_fast_forward_enabled = False
        self._smtc.is_rewind_enabled = False
        self._smtc.is_channel_up_enabled = False
        self._smtc.is_channel_down_enabled = False
        self._smtc.is_record_enabled = False

        # Display updater — the music_properties subobject holds the
        # title/artist fields the lockscreen renders.
        self._updater = self._smtc.display_updater
        self._updater.type = MediaPlaybackType.MUSIC
        self._music = self._updater.music_properties

        # Timeline properties — start_time/position/end_time, in 100ns ticks.
        self._timeline = self._smtc.timeline_properties

        # Route OS button presses back into the app via on_command.
        self._smtc.add_button_pressed(self._on_button_pressed)

        log.info("SMTC bridge live — lockscreen integration enabled")

    def _on_button_pressed(self, sender, args) -> None:
        """Translate the OS's ButtonPressed event into a hearth command."""
        try:
            raw = args.button
            # The winsdk binding exposes the enum value as either a small
            # int or a named enum; try both forms so we're robust to
            # binding version drift.
            key = raw if isinstance(raw, int) else int(raw)
            name = self._BUTTON_NAMES.get(key)
            if name is None:
                # Fall back to the str() form (enum name) lowercased.
                name = str(raw).split(".")[-1].split("_")[-1].lower()
                if name not in _BUTTON_COMMANDS:
                    return
            cmd = button_command(name)
            if cmd is None or self._on_command is None:
                return
            self._on_command(cmd)
        except Exception as exc:  # noqa: BLE001 - a bad button event never bites
            log.debug("SMTC button press ignored: %s", exc)

    def __call__(self, metadata: dict, timeline: dict) -> None:
        """Push one snapshot to the live SMTC (cheap field-level diffing)."""
        # --- metadata (title / artist / thumbnail) ---
        if metadata:
            title = str(metadata.get("title", "") or "")
            artist = str(metadata.get("artist", "") or "")
            if title and title != self._last_title:
                self._music.title = title
                self._last_title = title
            if artist and artist != self._last_artist:
                self._music.artist = artist
                self._last_artist = artist
            # Thumbnail fetching is intentionally skipped in this first
            # cut — see the class docstring. The lockscreen still shows
            # the title and artist, which is the bulk of the value.
            try:
                self._updater.update()
            except Exception as exc:  # noqa: BLE001
                log.debug("SMTC display_updater.update swallowed: %s", exc)

        # --- timeline + playback status ---
        position_ms = max(0, int(timeline.get("position_ms", 0)))
        end_ms = max(0, int(timeline.get("end_ms", 0)))
        status = str(timeline.get("status", STATUS_STOPPED))

        # SMTC expects TimeSpan in 100ns ticks. The winsdk binding accepts
        # a plain int and wraps it; we keep the multiplication explicit.
        TICKS_PER_MS = 10_000
        if position_ms != self._last_pos_ms or end_ms != self._last_end_ms:
            try:
                self._timeline.start_time = 0
                self._timeline.position = position_ms * TICKS_PER_MS
                self._timeline.end_time = end_ms * TICKS_PER_MS
            except Exception as exc:  # noqa: BLE001
                log.debug("SMTC timeline push swallowed: %s", exc)
            self._last_pos_ms = position_ms
            self._last_end_ms = end_ms

        if status != self._last_status:
            status_enum = {
                STATUS_PLAYING: self._status_playing,
                STATUS_PAUSED: self._status_paused,
                STATUS_STOPPED: self._status_stopped,
            }.get(status, self._status_stopped)
            try:
                self._smtc.playback_status = status_enum
            except Exception as exc:  # noqa: BLE001
                log.debug("SMTC playback_status push swallowed: %s", exc)
            self._last_status = status
