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
    """

    def __init__(
        self,
        bridge: BridgeApplier | None = None,
        get_track: Callable[[], Track | None] | None = None,
        is_playing: Callable[[], bool | None] | None = None,
        get_position_ms: Callable[[], int | None] | None = None,
        get_duration_ms: Callable[[], int | None] | None = None,
    ):
        self._bridge = bridge
        self._get_track = get_track
        self._is_playing = is_playing
        self._get_position = get_position_ms
        self._get_duration = get_duration_ms
        self._started = False

    @property
    def available(self) -> bool:
        return self._bridge is not None or SMTC_AVAILABLE

    def start(self) -> bool:
        """Claim the lockscreen slot; True only when a bridge accepted."""
        self._started = self._bridge is not None or SMTC_AVAILABLE
        return self._started

    def stop(self) -> None:
        self._started = False

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

    def _safe(self, getter: Callable | None) -> Any:
        try:
            return getter() if getter is not None else None
        except Exception:  # noqa: BLE001 - a getter hiccup is a missing field
            return None
