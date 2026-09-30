"""Crossfade + gapless pre-resolve (v1.0.0 groundwork).

Everything here is headless: the controller drives injectable fake
handles (test_player.py conventions), no real timers, no network. The
one thing these tests guard hardest is the double-advance bug class:
EndOfMedia during the ramp must NEVER skip two tracks.
"""

import math

import pytest

from hearth import config
from hearth.models import Track
from hearth.player import (
    CrossfadeController,
    PlaybackCore,
    fade_pair,
)

from .test_app_smoke import make_hearth
from .test_models import make_track


def tracks(n) -> list[Track]:
    return [make_track(video_id=f"t{i}", title=f"Song {i}") for i in range(n)]


class FakeHandle:
    """A MediaHandle fake that records everything done to it.

    Doubles as a duck-typed core backend after a promotion (position()
    for the stall watchdog, setPlaybackRate() for the echo path), the
    same way test_player.py's fakes stand in for QMediaPlayer.
    """

    def __init__(self, duration_ms: int = 200_000):
        self.errors = 0
        self._pos = 0
        self._duration = duration_ms
        self.volumes: list[float] = []
        self.started: list[int] = []
        self.stopped = 0
        self.loaded: list[str] = []
        self.rates: list[float] = []

    def load(self, url: str) -> None:
        self.loaded.append(url)

    def start(self, position_ms: int = 0) -> None:
        self.started.append(int(position_ms))
        self._pos = int(position_ms)

    def stop(self) -> None:
        self.stopped += 1

    def set_volume(self, factor: float) -> None:
        self.volumes.append(round(float(factor), 6))

    def set_rate(self, rate: float) -> None:
        self.rates.append(float(rate))

    def setPlaybackRate(self, rate: float) -> None:
        self.rates.append(float(rate))   # Qt-style alias (echo path)

    def position(self) -> int:           # Qt-style (watchdog reads this)
        return self._pos

    @property
    def position_ms(self) -> int:
        return self._pos

    @property
    def duration_ms(self) -> int:
        return self._duration

    @property
    def error_count(self) -> int:
        return self.errors


# --- fade_pair: the pure ramp math ---


def test_fade_pair_endpoints():
    assert fade_pair(0.0, 2) == (1.0, 0.0)
    assert fade_pair(1.0, 2) == (0.0, 1.0)


def test_fade_pair_equal_power_midpoint():
    cur, nxt = fade_pair(0.5, 2)
    assert cur == pytest.approx(math.cos(math.pi / 4), abs=1e-9)
    assert nxt == pytest.approx(math.sin(math.pi / 4), abs=1e-9)
    # equal-power: the pair sums in quadrature to unity, no mid-dip
    assert math.hypot(cur, nxt) == pytest.approx(1.0, abs=1e-9)


def test_fade_pair_legs_are_monotone():
    for step in range(10):
        cur_a, nxt_a = fade_pair(step / 10, 2)
        cur_b, nxt_b = fade_pair((step + 1) / 10, 2)
        assert cur_b < cur_a            # current fades strictly out
        assert nxt_b > nxt_a            # next fades strictly in


def test_fade_pair_clamps_progress():
    assert fade_pair(-0.7, 2) == (1.0, 0.0)
    assert fade_pair(1.9, 2) == (0.0, 1.0)


def test_fade_pair_zero_seconds_is_no_fade():
    for progress in (0.0, 0.5, 1.0):
        assert fade_pair(progress, 0) == (1.0, 0.0)


# --- CrossfadeController: the pure state machine ---


def test_controller_walks_idle_primed_crossfading_done():
    promoted = []
    ctl = CrossfadeController(2, tick_ms=100, on_promote=lambda: promoted.append(1))
    current, shadow = FakeHandle(), FakeHandle()
    ctl.adopt(current)
    assert ctl.state == CrossfadeController.IDLE
    assert ctl.prime(shadow, "next-track") is True
    assert ctl.state == CrossfadeController.PRIMED
    assert ctl.end_of_media() is True
    assert ctl.state == CrossfadeController.CROSSFADING
    assert shadow.started == [0]          # shadow rolls from the top
    assert shadow.volumes == [0.0]        # ...from silence
    for _ in range(20):                   # 2s at 100ms ticks
        ctl.tick()
    assert ctl.state == CrossfadeController.DONE
    assert promoted == [1]                # exactly one promotion


def test_controller_ramp_drives_volume_factors():
    ctl = CrossfadeController(2, tick_ms=100)
    current, shadow = FakeHandle(), FakeHandle()
    ctl.adopt(current)
    ctl.base_volume = 0.8
    ctl.prime(shadow, "next-track")
    ctl.end_of_media()
    for _ in range(20):
        ctl.tick()
    assert all(a > b for a, b in zip(current.volumes, current.volumes[1:]))
    assert all(a < b for a, b in zip(shadow.volumes[1:], shadow.volumes[2:]))
    assert shadow.volumes[-1] == pytest.approx(0.8)   # ends at master volume
    assert current.volumes[-1] == pytest.approx(0.0)  # old track ends silent


def test_controller_promotes_exactly_once_despite_extra_ticks():
    promoted = []
    ctl = CrossfadeController(1, tick_ms=100, on_promote=lambda: promoted.append(1))
    ctl.adopt(FakeHandle())
    ctl.prime(FakeHandle(), "next-track")
    ctl.end_of_media()
    for _ in range(40):                   # 4x the ramp length
        ctl.tick()
    assert promoted == [1]                # late ticks never re-promote


def test_controller_duplicate_end_of_media_is_absorbed():
    promoted = []
    ctl = CrossfadeController(1, tick_ms=100, on_promote=lambda: promoted.append(1))
    ctl.adopt(FakeHandle())
    ctl.prime(FakeHandle(), "next-track")
    assert ctl.end_of_media() is True
    assert ctl.end_of_media() is True     # relay again mid-ramp: absorbed
    assert promoted == []
    for _ in range(10):
        ctl.tick()
    assert promoted == [1]
    assert ctl.end_of_media() is True     # post-promotion relay: absorbed too
    assert promoted == [1]                # still exactly one promotion


def test_controller_falls_back_without_primed_shadow():
    ctl = CrossfadeController(2, tick_ms=100)
    ctl.adopt(FakeHandle())
    assert ctl.end_of_media() is False    # nothing primed -> legacy path
    assert ctl.state == CrossfadeController.IDLE


def test_controller_falls_back_when_shadow_errored():
    ctl = CrossfadeController(2, tick_ms=100)
    shadow = FakeHandle()
    shadow.errors = 1
    ctl.adopt(FakeHandle())
    ctl.prime(shadow, "next-track")
    assert ctl.end_of_media() is False    # a sick shadow is no better than none


def test_controller_zero_seconds_never_engages():
    ctl = CrossfadeController(0, tick_ms=100)
    ctl.adopt(FakeHandle())
    ctl.prime(FakeHandle(), "next-track")
    assert ctl.state == CrossfadeController.PRIMED
    assert ctl.end_of_media() is False    # crossfade off -> legacy path


# --- PlaybackCore integration ---


@pytest.fixture()
def enabled(qapp, monkeypatch):
    monkeypatch.setattr(config, "CROSSFADE_ENABLED", True)
    return qapp


def make_primed_core(seconds: int = 2):
    """A flag-on core with the queue rolling and the next track primed."""
    core = PlaybackCore()
    shadows: list[FakeHandle] = []

    def factory() -> FakeHandle:
        shadows.append(FakeHandle())
        return shadows[-1]

    core.shadow_factory = factory
    core.set_crossfade(seconds)
    core.start_queue(tracks(3))
    core._playing = True
    core._xf_maybe_preresolve()           # asks the app to resolve t1
    core.prime_shadow(tracks(3)[1], "https://example.com/t1")
    return core, shadows


def test_core_disabled_by_default_no_controller_no_shadow(qapp):
    core = PlaybackCore()
    assert core._xf is None               # flag off: the machine is never built
    core.start_queue(tracks(3))
    seen = []
    core.track_changed.connect(seen.append)
    core._on_end_of_media()               # advances exactly as v0.6.3 left it
    assert core.engine.current.video_id == "t1"
    assert len(seen) == 1
    core.prime_shadow(tracks(3)[2], "https://example.com/t2")   # silently inert
    assert core._xf is None


def test_core_flag_on_zero_seconds_stays_legacy(enabled):
    core = PlaybackCore()
    made: list[FakeHandle] = []

    def factory() -> FakeHandle:
        made.append(FakeHandle())
        return made[-1]

    core.shadow_factory = factory
    core.set_crossfade(0)
    core.start_queue(tracks(2))
    core._playing = True
    core.queue_changed.emit()
    assert not made                       # 0s: no pre-resolve, no shadow ever
    seen = []
    core.track_changed.connect(seen.append)
    core._on_end_of_media()
    assert core.engine.current.video_id == "t1"
    assert len(seen) == 1                 # plain relay, exactly once


def test_core_preresolve_requested_once_cached_and_rearmed(enabled):
    core = PlaybackCore()
    core.set_crossfade(2)
    asked = []
    core.preresolve_requested.connect(asked.append)
    core.start_queue(tracks(3))           # not playing yet: nothing asked
    assert asked == []
    core._playing = True
    core.queue_changed.emit()             # re-arms on every queue change
    assert [t.video_id for t in asked] == ["t1"]
    core.queue_changed.emit()             # same pair: cached, not re-asked
    core.enqueue(make_track(video_id="extra"))
    assert len(asked) == 1
    core.engine.set_order([tracks(3)[2], tracks(3)[1], make_track(video_id="x")])
    core.queue_changed.emit()             # the next track changed: re-armed
    assert [t.video_id for t in asked] == ["t1", "t2"]


def test_core_prime_shadow_stale_dropped_valid_primed(enabled):
    core = PlaybackCore()
    core.set_crossfade(2)
    made: list[FakeHandle] = []

    def factory() -> FakeHandle:
        made.append(FakeHandle())
        return made[-1]

    core.shadow_factory = factory
    core.start_queue(tracks(3))
    core.prime_shadow(make_track(video_id="nope"), "https://example.com/x")
    assert not made                       # stale result: dropped, no shadow
    core.prime_shadow(tracks(3)[1], "https://example.com/t1")
    assert len(made) == 1                 # exactly one shadow, built lazily
    shadow = core._xf.shadow
    assert shadow.loaded == ["https://example.com/t1"]
    assert shadow.volumes == [0.0]        # primed silent
    assert 1.0 in shadow.rates            # primed at the core's rate
    assert core._xf.primed_track.video_id == "t1"
    core.prime_shadow(tracks(3)[2], "https://example.com/t2")
    assert core._xf.shadow is shadow      # already primed: second is dropped
    assert len(made) == 1


def test_core_crossfade_promotes_once_and_rewires(enabled):
    core, shadows = make_primed_core()
    seen = []
    core.track_changed.connect(seen.append)
    assert core._xf.state == CrossfadeController.PRIMED
    core._on_end_of_media()               # engages the fade instead
    assert core.engine.current.video_id == "t0"   # NOT advanced yet
    assert seen == []                     # no track_changed yet either
    assert core._xf.state == CrossfadeController.CROSSFADING
    shadow = shadows[0]
    assert shadow.started == [0] and shadow.volumes[0] == 0.0
    for _ in range(20):                   # 2s ramp, 100ms ticks
        core._xf_tick()
    # the promotion: one advance, one track_changed, backend swapped
    assert core.engine.current.video_id == "t1"
    assert [t.video_id for t in seen] == ["t1"]
    assert [t.video_id for t in core.engine.upcoming] == ["t2"]
    assert core._player is shadow         # the shadow IS the backend now
    assert core._xf_promoted_id == "t1"   # echo guard armed for the app
    assert core._xf.state == CrossfadeController.IDLE
    # healing ledger reset for the new stream (v0.6.3 guarantees carry over)
    assert core._recovered_id == "t1"
    assert core._retries == 0
    assert not core._stream_played
    assert core._playing


def test_core_double_relay_mid_ramp_never_double_advances(enabled):
    core, _shadows = make_primed_core()
    seen = []
    core.track_changed.connect(seen.append)
    core._on_end_of_media()               # engage
    core._on_end_of_media()               # duplicate relay mid-ramp
    assert core.engine.current.video_id == "t0"   # still holding
    for _ in range(20):
        core._xf_tick()
    assert [t.video_id for t in seen] == ["t1"]   # advanced EXACTLY once
    assert core.engine.current.video_id == "t1"
    assert [t.video_id for t in core.engine.upcoming] == ["t2"]


def test_core_watchdog_rejoin_works_after_promotion(enabled):
    core, shadows = make_primed_core()
    lost = []
    core.stream_lost.connect(lambda t, ms: lost.append((t.video_id, ms)))
    core._on_end_of_media()               # engage the fade
    for _ in range(20):
        core._xf_tick()
    shadow = shadows[0]
    shadow._pos = 90_000                  # the promoted stream is underway
    core._note_playing(True)
    core._emit_position()                 # observed motion -> proof of audio
    assert core._last_pos_ms == 90_000
    for _ in range(config.STALL_POLLS):   # then it freezes mid-song...
        core._emit_position()
    assert lost == [("t1", 90_000)]       # ...watchdog rejoins the NEW primary
    assert core.engine.current.video_id == "t1"


def test_core_promotion_absorbs_resolve_echo(enabled):
    core, shadows = make_primed_core()
    core._on_end_of_media()               # engage the fade
    for _ in range(20):
        core._xf_tick()
    shadow = shadows[0]
    assert core._player is shadow
    # the app's LoadJob echo for the promoted track: must NOT reload it
    core.set_stream(tracks(3)[1], "https://example.com/fresh")
    assert shadow.loaded == ["https://example.com/t1"]   # source untouched
    assert core._xf_promoted_id is None                  # echo consumed
    assert core.engine.current.video_id == "t1"
    assert core._playing


def test_core_error_paths_unaffected_when_flag_on(enabled):
    core = PlaybackCore()
    core.set_crossfade(2)
    core.start_queue(tracks(3))
    core._on_error(0, "dead")             # nothing played -> skip, as ever
    assert core.engine.current.video_id == "t1"
    core._on_error(0, "dead again")       # duplicate before audio: ignored
    assert core.engine.current.video_id == "t1"


def test_set_crossfade_clamps_and_zero_disables(enabled):
    core = PlaybackCore()
    core.shadow_factory = FakeHandle
    core.set_crossfade(2)
    core.start_queue(tracks(2))
    core._playing = True
    core._xf_maybe_preresolve()
    core.prime_shadow(tracks(2)[1], "https://example.com/t1")
    assert core._xf.state == CrossfadeController.PRIMED
    shadow = core._xf.shadow
    core.set_crossfade(99)
    assert core.crossfade_seconds == config.CROSSFADE_MAX_MS // 1000
    core.set_crossfade(-4)
    assert core.crossfade_seconds == 0
    core.set_crossfade("banana")
    assert core.crossfade_seconds == 0
    assert core._xf.state == CrossfadeController.IDLE    # primed shadow dropped
    assert shadow.stopped == 1


# --- UI: the crossfade row on Now Playing + app settings roundtrip ---


def test_now_view_crossfade_row_gated_on_flag(qapp):
    from hearth.config import get_palette
    from hearth.window import NowView

    view = NowView(get_palette(config.DEFAULT_PALETTE))
    assert view._xf_slider is None        # flag off (default): no row at all
    assert view.crossfade_seconds == 0
    view.set_crossfade(2)                 # silent no-op, never raises
    assert view.crossfade_seconds == 0


def test_now_view_crossfade_slider_roundtrip(qapp, monkeypatch):
    from hearth.config import get_palette
    from hearth.window import NowView

    monkeypatch.setattr(config, "CROSSFADE_ENABLED", True)
    view = NowView(get_palette(config.DEFAULT_PALETTE))
    assert view._xf_slider is not None
    seen = []
    view.crossfade_changed.connect(seen.append)
    view._xf_slider.setValue(2)           # user drags: emits live
    assert seen[-1] == 2
    assert view._xf_label.text() == "2s"
    view._xf_slider.setValue(0)
    assert seen[-1] == 0
    assert view._xf_label.text() == "off"
    view.set_crossfade(3)                 # restore path: silent, clamped
    assert view.crossfade_seconds == 3
    view.set_crossfade(99)
    assert view.crossfade_seconds == view._xf_slider.maximum()


def test_app_crossfade_setting_roundtrip(tmp_path, qapp, monkeypatch):
    monkeypatch.setattr(config, "CROSSFADE_ENABLED", True)
    hearth = make_hearth(tmp_path)
    hearth.window.now_view._xf_slider.setValue(2)   # the user drags the slider
    assert hearth.core.crossfade_seconds == 2
    assert str(hearth.settings.value("crossfade")) == "2"
    hearth.shutdown()

    reopened = make_hearth(tmp_path)
    assert reopened.core.crossfade_seconds == 2       # restored at boot
    assert reopened.window.now_view.crossfade_seconds == 2
    reopened.shutdown()
