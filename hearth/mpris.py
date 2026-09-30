"""MPRIS2: the hearth answers the desk's media keys (Linux, guarded).

When a session bus and the optional ``dbus`` binding are available, a
tiny ``org.mpris.MediaPlayer2.hearth`` service is published so desktop
shells (GNOME, KDE, playerctl…) can see, control, and scrobble Hearth.
Everything here rides the SAME core signals the tray uses — the audio
path is never touched.

The import is guarded: on Windows/macOS (or any box without dbus) the
module still imports cleanly, ``MPRIS_AVAILABLE`` is False, and
``MprisService`` degrades to a silent no-op with the same API. The pure
formatters ``metadata_map`` / ``status_map`` live above the guard so
they are testable with zero dbus installed.
"""

from __future__ import annotations

import logging

from PyQt6.QtCore import QTimer

from . import config
from .models import Track, parse_duration

log = logging.getLogger(__name__)

try:                       # optional system binding — absent on most CI boxes
    import dbus
    _DBUS_WHY = ""
except Exception as _exc:  # noqa: BLE001 - ImportError *or* broken native lib
    dbus = None            # type: ignore[assignment]
    _DBUS_WHY = str(_exc)

MPRIS_AVAILABLE = dbus is not None

MPRIS_BUS_NAME = "org.mpris.MediaPlayer2.hearth"
MPRIS_PATH = "/org/mpris/MediaPlayer2"
MPRIS_TRACK_PREFIX = MPRIS_PATH + "/track/"
ROOT_IFACE = "org.mpris.MediaPlayer2"
PLAYER_IFACE = "org.mpris.MediaPlayer2.Player"
PROPS_IFACE = "org.freedesktop.DBus.Properties"

# hearth repeat modes → MPRIS LoopStatus, and back again
_LOOP_OUT = {"off": "None", "all": "Playlist", "one": "Track"}
_LOOP_IN = {"None": "off", "Playlist": "all", "Track": "one"}

POSITION_THROTTLE_MS = 1000   # the desk gets a position tick once a second


# ----------------------------------------------------------------- pure helpers

def _sanitize_id(raw: str) -> str:
    """Any video id becomes a legal D-Bus object-path fragment."""
    cleaned = "".join(c if (c.isalnum() or c == "_") else "_" for c in str(raw))
    return cleaned or "track"


def metadata_map(track: Track | None, length_us: int | None = None) -> dict:
    """The MPRIS metadata dict for one track — plain types, zero dbus.

    `length_us` overrides the track's own duration (the live media
    length, when the player knows it); otherwise it is derived from
    `duration_sec` with an "m:ss" string fallback.
    """
    if track is None:
        return {}
    seconds = track.duration_sec or parse_duration(track.duration)
    if length_us is None:
        length_us = int(max(0.0, float(seconds)) * 1_000_000)
    meta: dict = {
        "mpris:trackid": MPRIS_TRACK_PREFIX + _sanitize_id(track.video_id),
        "mpris:length": max(0, int(length_us)),
        "xesam:title": str(track.title or ""),
        "xesam:artist": [str(track.artist)] if track.artist else [],
        "xesam:album": str(getattr(track, "album", "") or ""),
        "xesam:url": f"https://music.youtube.com/watch?v={track.video_id}",
    }
    if track.thumbnail:
        meta["mpris:artUrl"] = str(track.thumbnail)
    return meta


def status_map(
    playing: bool = False,
    stopped: bool = False,
    loop: str = "off",
    shuffle: bool = False,
    volume: float = 1.0,
    position_ms: int = 0,
) -> dict:
    """The MPRIS player-property dict — plain types, zero dbus.

    `stopped` wins over `paused` (a bool from the caller that knows
    whether anything is loaded); Position arrives in hearth's ms and
    leaves in the spec's microseconds.
    """
    if stopped:
        status = "Stopped"
    elif playing:
        status = "Playing"
    else:
        status = "Paused"
    return {
        "PlaybackStatus": status,
        "LoopStatus": _LOOP_OUT.get(str(loop), "None"),
        "Shuffle": bool(shuffle),
        "Volume": max(0.0, min(1.0, float(volume))),
        "Position": max(0, int(position_ms)) * 1000,
        "CanPlay": True,
        "CanPause": True,
        "CanSeek": True,
        "CanControl": True,
        "CanGoNext": True,
        "CanGoPrevious": True,
    }


def _root_properties() -> dict:
    """The static org.mpris.MediaPlayer2 (Root) property set."""
    return {
        "CanQuit": True,
        "CanRaise": True,
        "HasTrackList": False,
        "Identity": str(config.APP_NAME),
        "DesktopEntry": "hearth",
        "SupportedUriSchemes": [],
        "SupportedMimeTypes": [],
    }


# ----------------------------------------------------------------- dbus shim

_DBusShim = None
if dbus is not None:          # only compiled when the binding is present

    class _DBusShim(dbus.service.Object):   # type: ignore[misc]
        """One D-Bus object exporting Root + Player for a MprisService."""

        def __init__(self, service, bus):
            self._svc = service
            super().__init__(conn=bus, object_path=MPRIS_PATH)

        # --- incoming: properties ---

        @dbus.service.method(PROPS_IFACE, in_signature="ss", out_signature="v")
        def Get(self, interface: str, prop: str):
            # unknown interface/property raises DBusException straight from
            # the service — dbus-python turns it into an InvalidArgs reply
            return self._svc.property_value(interface, prop)

        @dbus.service.method(PROPS_IFACE, in_signature="s", out_signature="a{sv}")
        def GetAll(self, interface: str) -> dict:
            props = self._svc.all_properties(interface)
            if props is None:
                raise dbus.exceptions.DBusException(
                    f"{PROPS_IFACE}.InvalidArgs: unknown interface {interface!r}"
                )
            return props

        @dbus.service.method(PROPS_IFACE, in_signature="ssv", out_signature="")
        def Set(self, interface: str, prop: str, value) -> None:
            self._svc.set_property(prop, value)

        # --- outgoing: the change broadcast ---

        @dbus.service.signal(PROPS_IFACE, signature="sa{sv}as")
        def PropertiesChanged(self, interface: str, changed: dict,
                              invalidated: list) -> None:
            pass

        # --- incoming: Root ---

        @dbus.service.method(ROOT_IFACE)
        def Raise(self) -> None:
            self._svc.raise_window()

        @dbus.service.method(ROOT_IFACE)
        def Quit(self) -> None:
            self._svc.quit_app()

        # --- incoming: Player ---

        @dbus.service.method(PLAYER_IFACE)
        def Play(self) -> None:
            self._svc.play()

        @dbus.service.method(PLAYER_IFACE)
        def Pause(self) -> None:
            self._svc.pause()

        @dbus.service.method(PLAYER_IFACE)
        def PlayPause(self) -> None:
            self._svc.play_pause()

        @dbus.service.method(PLAYER_IFACE)
        def Next(self) -> None:
            self._svc.next()

        @dbus.service.method(PLAYER_IFACE)
        def Previous(self) -> None:
            self._svc.previous()

        @dbus.service.method(PLAYER_IFACE)
        def Stop(self) -> None:
            self._svc.stop_playback()

        @dbus.service.method(PLAYER_IFACE, in_signature="x", out_signature="")
        def Seek(self, offset_us: int) -> None:
            self._svc.seek_relative(int(offset_us))

        @dbus.service.method(PLAYER_IFACE, out_signature="x")
        def GetPosition(self) -> int:
            return self._svc.position_us()

        @dbus.service.method(PLAYER_IFACE, in_signature="ox")
        def SetPosition(self, trackid: str, position_us: int) -> None:
            self._svc.seek_absolute(int(position_us))


# ----------------------------------------------------------------- the service

class MprisService:
    """Hearth on the desk's media radar (real when dbus is around).

    `connect()` subscribes to the same core signals the tray uses and
    keeps a cached property set in step; a one-second throttle turns the
    firehose of position ticks into one polite PropertiesChanged per
    second. Every dbus touch is wrapped — a missing or grumpy bus can
    never reach playback.
    """

    def __init__(self) -> None:
        self._core = None
        self._summon = None
        self._quit = None
        self._bus = None
        self._shim = None
        self._started = False
        self._position_ms = 0
        self._duration_ms = 0
        self._last_pushed_pos = -1
        self._last_pushed_vol = -1.0
        self._metadata: dict = {}
        self._timer: QTimer | None = None

    # --- lifecycle ---

    def connect(self, core, summon=None, quit=None) -> None:
        """Subscribe to the core (never raises, even on a broken core)."""
        self._core = core
        self._summon = summon
        self._quit = quit
        try:
            core.track_changed.connect(self._on_track_changed)
            core.state_changed.connect(self._on_state_changed)
            core.repeat_changed.connect(self._on_repeat_changed)
            core.position_changed.connect(self._on_position)
            core.duration_changed.connect(self._on_duration)
            self._timer = QTimer(core)
            self._timer.setInterval(POSITION_THROTTLE_MS)
            self._timer.timeout.connect(self._push_tick)
            self._timer.start()
        except Exception as exc:  # noqa: BLE001 - wiring must never bite
            log.debug("MPRIS connect degraded: %s", exc)

    def start(self) -> bool:
        """Claim the bus name. False when dbus is absent or the bus refuses."""
        if dbus is None or self._started or _DBusShim is None:
            return False
        try:
            self._bus = dbus.SessionBus()
            self._shim = _DBusShim(self, self._bus)
            self._name = dbus.service.BusName(MPRIS_BUS_NAME, self._bus)
            self._started = True
            log.info("MPRIS2 service live as %s", MPRIS_BUS_NAME)
            return True
        except Exception as exc:  # noqa: BLE001 - no bus, no drama
            log.info("MPRIS unavailable (%s) — the desk plays without it", exc)
            self._bus = None
            self._shim = None
            return False

    def stop(self) -> None:
        """Leave the stage quietly (idempotent)."""
        if self._timer is not None:
            try:
                self._timer.stop()
            except Exception:  # noqa: BLE001
                pass
            self._timer = None
        if self._shim is not None:
            try:
                self._shim.remove_from_connection()
            except Exception:  # noqa: BLE001
                pass
        self._shim = None
        self._bus = None
        self._started = False

    # --- property plumbing (called by the shim) ---

    def all_properties(self, interface: str) -> dict | None:
        if interface == ROOT_IFACE:
            return _root_properties()
        if interface == PLAYER_IFACE:
            props = self._status_properties()
            props["Metadata"] = dict(self._metadata)   # a{sv} nested per spec
            return props
        return None

    def property_value(self, interface: str, prop: str):
        """One property read; unknown names raise (the spec's InvalidArgs).

        org.freedesktop.DBus.Properties.Get must answer a bogus name
        with an error, never a made-up value — so the rejection happens
        here, and the shim just lets it travel to the bus.
        """
        props = self.all_properties(interface)
        if props is None or prop not in props:
            raise dbus.exceptions.DBusException(
                f"{PROPS_IFACE}.InvalidArgs: no such property {prop!r} "
                f"on {interface!r}"
            )
        return props[prop]

    def set_property(self, prop: str, value) -> None:
        """The desk turned a dial (volume / loop / shuffle). Never raises."""
        def _apply() -> None:
            core = self._core
            if core is None:
                return
            if prop == "Volume":
                core.set_volume(max(0.0, min(1.0, float(value))))
            elif prop == "LoopStatus":
                mode = _LOOP_IN.get(str(value))
                if mode is not None:
                    core.set_repeat(mode)
            elif prop == "Shuffle":
                if bool(value):
                    core.shuffle()
        try:
            _apply()
        except Exception as exc:  # noqa: BLE001
            log.debug("MPRIS Set(%s) ignored: %s", prop, exc)

    def _status_properties(self) -> dict:
        core = self._core
        playing = bool(getattr(core, "is_playing", False)) if core else False
        current = getattr(getattr(core, "engine", None), "current", None)
        repeat = str(getattr(getattr(core, "engine", None), "repeat", "off")
                     or "off") if core else "off"
        volume = float(getattr(core, "volume", 1.0)) if core else 1.0
        return status_map(
            playing=playing,
            stopped=(current is None and not playing),
            loop=repeat,
            volume=volume,
            position_ms=self._position_ms,
        )

    # --- core signal handlers (each wrapped never-raises) ---

    def _on_track_changed(self, track) -> None:
        try:
            length_us = int(self._duration_ms * 1000) if self._duration_ms else None
            self._metadata = metadata_map(track, length_us=length_us)
            self._position_ms = 0
            self._last_pushed_pos = -1
            self._emit_changed({"Metadata": dict(self._metadata),
                                "PlaybackStatus": self._status_properties()[
                                    "PlaybackStatus"]})
        except Exception as exc:  # noqa: BLE001
            log.debug("MPRIS track push failed: %s", exc)

    def _on_state_changed(self, _playing: bool) -> None:
        try:
            self._emit_changed(
                {"PlaybackStatus": self._status_properties()["PlaybackStatus"]})
        except Exception as exc:  # noqa: BLE001
            log.debug("MPRIS state push failed: %s", exc)

    def _on_repeat_changed(self, _mode: str) -> None:
        try:
            self._emit_changed(
                {"LoopStatus": self._status_properties()["LoopStatus"]})
        except Exception as exc:  # noqa: BLE001
            log.debug("MPRIS loop push failed: %s", exc)

    def _on_position(self, position_ms: int) -> None:
        """Cheap: remember the tick; the 1s throttle does the talking."""
        self._position_ms = max(0, int(position_ms))

    def _on_duration(self, duration_ms: int) -> None:
        self._duration_ms = max(0, int(duration_ms))

    def _push_tick(self) -> None:
        """One polite push per second: Position (always moving) + Volume."""
        try:
            core = self._core
            if core is None:
                return
            self._position_ms = max(0, int(getattr(core, "position_ms",
                                                   self._position_ms)))
            changed: dict = {}
            if self._position_ms != self._last_pushed_pos:
                self._last_pushed_pos = self._position_ms
                changed["Position"] = self._position_ms * 1000
            volume = float(getattr(core, "volume", 0.0))
            if abs(volume - self._last_pushed_vol) > 1e-9:
                self._last_pushed_vol = volume
                changed["Volume"] = volume
            if changed and self._started:
                self._emit_changed(changed)
        except Exception as exc:  # noqa: BLE001
            log.debug("MPRIS tick push failed: %s", exc)

    def _emit_changed(self, changed: dict) -> None:
        """The one dbus call in the room — wrapped, and only once started."""
        if not self._started or self._shim is None:
            return
        try:
            self._shim.PropertiesChanged(PLAYER_IFACE, dict(changed), [])
        except Exception as exc:  # noqa: BLE001
            log.debug("MPRIS PropertiesChanged swallowed: %s", exc)

    # --- transport actions the desk may ask for ---

    def raise_window(self) -> None:
        try:
            if self._summon is not None:
                self._summon()
        except Exception as exc:  # noqa: BLE001
            log.debug("MPRIS Raise swallowed: %s", exc)

    def quit_app(self) -> None:
        try:
            if self._quit is not None:
                self._quit()
        except Exception as exc:  # noqa: BLE001
            log.debug("MPRIS Quit swallowed: %s", exc)

    def play(self) -> None:
        try:
            core = self._core
            if core is not None and not core.is_playing:
                core.toggle()
        except Exception as exc:  # noqa: BLE001
            log.debug("MPRIS Play swallowed: %s", exc)

    def pause(self) -> None:
        try:
            core = self._core
            if core is not None and core.is_playing:
                core.toggle()
        except Exception as exc:  # noqa: BLE001
            log.debug("MPRIS Pause swallowed: %s", exc)

    def play_pause(self) -> None:
        try:
            if self._core is not None:
                self._core.toggle()
        except Exception as exc:  # noqa: BLE001
            log.debug("MPRIS PlayPause swallowed: %s", exc)

    def next(self) -> None:
        try:
            if self._core is not None:
                self._core.next()
        except Exception as exc:  # noqa: BLE001
            log.debug("MPRIS Next swallowed: %s", exc)

    def previous(self) -> None:
        try:
            if self._core is not None:
                self._core.previous()
        except Exception as exc:  # noqa: BLE001
            log.debug("MPRIS Previous swallowed: %s", exc)

    def stop_playback(self) -> None:
        """The Player's Stop: silence, queue kept (lifecycle stop is separate)."""
        try:
            if self._core is not None:
                self._core.stop()
        except Exception as exc:  # noqa: BLE001
            log.debug("MPRIS Stop swallowed: %s", exc)

    def seek_relative(self, offset_us: int) -> None:
        try:
            core = self._core
            if core is None:
                return
            target = self._position_ms + int(offset_us) // 1000
            core.seek(max(0, int(target)))
        except Exception as exc:  # noqa: BLE001
            log.debug("MPRIS Seek swallowed: %s", exc)

    def seek_absolute(self, position_us: int) -> None:
        try:
            if self._core is not None:
                self._core.seek(max(0, int(position_us) // 1000))
        except Exception as exc:  # noqa: BLE001
            log.debug("MPRIS SetPosition swallowed: %s", exc)

    def position_us(self) -> int:
        return max(0, int(self._position_ms)) * 1000


class _NoopMpris:
    """The guarded twin: same API as MprisService, does nothing at all.

    This is what ``MprisService`` resolves to on systems without the
    optional ``dbus`` binding (Windows, macOS, most CI) — boot, wiring
    and shutdown call straight into warm air, safely.
    """

    def __init__(self, *args, **kwargs) -> None:  # noqa: D401 - tiny twin
        self._core = None

    def connect(self, core, summon=None, quit=None) -> None:
        self._core = core

    def start(self) -> bool:
        return False

    def stop(self) -> None:
        self._core = None


if dbus is None:
    MprisService = _NoopMpris  # type: ignore[misc,assignment]
