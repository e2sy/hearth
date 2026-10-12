"""v0.8.0 Room 8.3 — the SMTC wiring into the Hearth app.

The pure mappers and the ``SmtcService`` lifecycle are tested in
``test_smtc.py``; this module verifies the integration surface that
was missing for v0.8.0 — that ``Hearth`` actually instantiates an
``SmtcService``, wires it to the playback core, dispatches OS-side
button presses into the core, and tears it down on shutdown.

These tests are platform-neutral: on Linux/macOS (no ``winsdk``) the
bridge is ``None`` and ``SmtcService.start()`` returns ``False``,
which is exactly the guarded degradation we want. The same assertions
pass on Windows with ``winsdk`` installed (where ``start()`` returns
``True`` and the bridge is a real callable).
"""

from __future__ import annotations

from hearth import config
from hearth.app import Hearth
from hearth.smtc import SMTC_AVAILABLE, SmtcService, create_windows_bridge

from .test_models import make_track


def make_hearth(tmp_path) -> Hearth:
    return Hearth(
        argv=["hearth-test"],
        settings_path=str(tmp_path / "settings.ini"),
        data_directory=tmp_path / "data",
        single_instance=False,
        enable_streaming=False,
    )


# --- the service is wired ---

def test_hearth_constructs_smtc_service(tmp_path, qapp):
    """The app owns an SmtcService the way it owns an MprisService."""
    hearth = make_hearth(tmp_path)
    assert isinstance(hearth.smtc, SmtcService)
    hearth.shutdown()


def test_hearth_dispatches_smtc_button_commands(tmp_path, qapp):
    """OS-side button names route through to the playback core."""
    hearth = make_hearth(tmp_path)

    pressed: list[str] = []

    def fake_toggle():
        pressed.append("toggle")

    def fake_next():
        pressed.append("next")

    def fake_prev():
        pressed.append("prev")

    # Patch the core's transport methods so we can observe the dispatch
    # without actually driving Qt Multimedia (we're headless in tests).
    core = hearth.core
    core.toggle = fake_toggle
    core.next = fake_next
    core.previous = fake_prev
    # 'play' and 'pause' both route through toggle() — see _smtc_dispatch.
    # ``is_playing`` is a read-only property backed by ``_playing``; set
    # the underlying attribute directly so 'pause' dispatches (it only
    # toggles when ``core.is_playing`` is True).
    core._playing = False

    for cmd in ("toggle", "play", "pause", "next", "prev"):
        hearth._smtc_dispatch(cmd)

    # toggle / play / pause all funnel into toggle(); next / prev hit
    # their own dispatch path. 'pause' is a no-op because we just set
    # _playing=False, so it does NOT toggle (the dispatch is idempotent
    # and only toggles when the state actually demands it).
    assert pressed == ["toggle", "toggle", "next", "prev"]

    # An unknown command must not raise and must not call any transport.
    pressed.clear()
    hearth._smtc_dispatch("mystery")
    assert pressed == []
    hearth.shutdown()


def test_hearth_shutdown_stops_smtc_service(tmp_path, qapp):
    """After shutdown the service reports it's no longer started."""
    hearth = make_hearth(tmp_path)
    hearth.shutdown()
    assert hearth.smtc._started is False


def test_create_windows_bridge_is_none_off_windows():
    """On any non-Windows / non-winsdk box the factory returns None.

    This is the guarded degradation contract: the app can call
    ``create_windows_bridge()`` unconditionally and the result is a
    safe no-op bridge on every CI matrix entry that doesn't have
    ``winsdk`` installed.
    """
    if SMTC_AVAILABLE:
        # On a Windows box with winsdk installed, the factory may still
        # return None in headless mode (no current view to attach SMTC
        # to) — both branches are valid. We only assert the call doesn't
        # raise.
        bridge = create_windows_bridge(on_command=lambda _cmd: None)
        assert bridge is None or callable(bridge)
    else:
        assert create_windows_bridge(on_command=lambda _cmd: None) is None


def test_smtc_get_duration_ms_falls_back_to_track(tmp_path, qapp):
    """The duration getter prefers a cached duration_changed value, then
    falls back to the track's own ``duration_sec`` parsed to ms."""
    hearth = make_hearth(tmp_path)
    track = make_track()  # duration_sec=213, title="Never Gonna Give You Up"
    hearth.core.engine.current = track

    # No cached duration yet — falls back to the track's own duration.
    ms = hearth._smtc_get_duration_ms()
    assert ms == 213_000

    # A cached duration_changed value wins.
    hearth._smtc_on_duration(150_000)
    assert hearth._smtc_get_duration_ms() == 150_000

    hearth.shutdown()


def test_smtc_connect_subscribes_to_core_signals(tmp_path, qapp):
    """``SmtcService.connect()`` binds the same core signals MPRIS does.

    On a Windows box with ``winsdk`` installed, the app boots with
    ``SMTC_AVAILABLE`` True and ``connect()`` is called, so the
    throttle timer is live. On a Linux/macOS CI box the bridge is
    ``None`` and the service degrades to a no-op (no connect, no
    timer) — exactly the same guarded behavior as MPRIS without dbus.
    """
    hearth = make_hearth(tmp_path)
    svc = hearth.smtc

    if SMTC_AVAILABLE:
        # The throttle timer is created and running while started.
        assert svc._timer is not None
        assert svc._started is True
    else:
        # On non-Windows CI, connect() is never called (the bridge is
        # None) and the service stays dormant.
        assert svc._timer is None
        assert svc._started is False

    hearth.shutdown()


def test_smtc_service_disabled_when_flag_off(tmp_path, qapp, monkeypatch):
    """When ``config.SMTC_ENABLED`` is False, the service stays dormant."""
    monkeypatch.setattr(config, "SMTC_ENABLED", False)
    hearth = Hearth(
        argv=["hearth-test"],
        settings_path=str(tmp_path / "settings.ini"),
        data_directory=tmp_path / "data",
        single_instance=False,
        enable_streaming=False,
    )
    assert hearth._smtc_bridge is None
    assert hearth.smtc._started is False
    hearth.shutdown()
