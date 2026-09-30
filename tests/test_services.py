"""v0.7.0 reach: MPRIS2 media keys, update whisper, diagnostics report,
stats dashboard — headless, offscreen, no network (urllib is stubbed)."""

import importlib
import json
import sys
import types
from datetime import datetime

import pytest
from PyQt6.QtCore import QObject, QSettings, pyqtSignal

from hearth import config
from hearth.diagnostics import gather_report
from hearth.models import Track
from hearth.mpris import metadata_map, status_map
from hearth.storage import HearthStore
from hearth.update_whisper import (
    RELEASES_API_URL,
    ReleaseCheckJob,
    UpdateWhisper,
    compare_versions,
    fetch_latest_release,
)
from hearth.window import MainWindow, StatsView, group_months

from .test_app_smoke import make_hearth
from .test_models import make_track


def local_noon(year: int, month: int, day: int) -> float:
    """Local noon of a calendar day — immune to any machine timezone."""
    return datetime(year, month, day, 12).timestamp()


def make_settings(tmp_path) -> QSettings:
    return QSettings(str(tmp_path / "whisper.ini"), QSettings.Format.IniFormat)


# ----------------------------------------------------------------- mpris: pure helpers

def test_mpris_metadata_map_formats_spec_fields():
    track = make_track(video_id="abc-XY 1", duration="3:33", duration_sec=213)
    meta = metadata_map(track)
    assert meta["mpris:trackid"].startswith("/org/mpris/MediaPlayer2/track/")
    assert meta["mpris:trackid"].endswith("abc_XY_1")   # path-legal id
    assert meta["mpris:length"] == 213 * 1_000_000       # µs per the spec
    assert meta["xesam:title"] == "Never Gonna Give You Up"
    assert meta["xesam:artist"] == ["Rick Astley"]        # artist is a LIST
    assert meta["xesam:album"] == ""                      # tracks carry no album
    assert meta["xesam:url"].endswith("watch?v=abc-XY 1")
    assert meta["mpris:artUrl"] == track.thumbnail


def test_mpris_metadata_map_edge_cases():
    assert metadata_map(None) == {}
    bare = metadata_map(make_track(video_id="x", artist="", thumbnail="",
                                   duration="1:02", duration_sec=0))
    assert bare["xesam:artist"] == []                # no artist, no ghost rows
    assert "mpris:artUrl" not in bare
    assert bare["mpris:length"] == 62 * 1_000_000    # "m:ss" string fallback
    override = metadata_map(make_track(duration_sec=213), length_us=1_500)
    assert override["mpris:length"] == 1_500         # live media length wins


def test_mpris_status_map_matrix():
    assert status_map(playing=True, stopped=False)["PlaybackStatus"] == "Playing"
    assert status_map(playing=False, stopped=False)["PlaybackStatus"] == "Paused"
    assert status_map(playing=False, stopped=True)["PlaybackStatus"] == "Stopped"
    props = status_map(playing=True, loop="all", shuffle=True,
                       volume=1.4, position_ms=1000)
    assert props["LoopStatus"] == "Playlist"          # off/all/one → None/Playlist/Track
    assert status_map(loop="one")["LoopStatus"] == "Track"
    assert status_map(loop="banana")["LoopStatus"] == "None"
    assert props["Shuffle"] is True
    assert props["Volume"] == 1.0                     # clamped into [0, 1]
    assert status_map(volume=-1.0)["Volume"] == 0.0
    assert props["Position"] == 1_000_000             # ms in, µs out


@pytest.fixture
def mpris_mod():
    """hearht.mpris reloaded fresh; the true env is restored afterwards."""
    import hearth.mpris as m
    try:
        yield m
    finally:
        sys.modules.pop("dbus", None)   # undo any test stub before restoring
        importlib.reload(m)


def _fake_dbus():
    """A dbus-shaped stub: just enough surface for hearth.mpris to wire."""
    mod = types.ModuleType("dbus")

    class DBusException(Exception):
        pass

    exceptions = types.ModuleType("dbus.exceptions")
    exceptions.DBusException = DBusException

    service = types.ModuleType("dbus.service")

    def _passthrough(*dargs, **dkwargs):
        def deco(fn):
            return fn
        return deco

    service.method = _passthrough
    service.signal = _passthrough

    class _Object:
        def __init__(self, conn=None, object_path=None, bus_name=None):
            self.object_path = object_path

        def remove_from_connection(self):
            pass

    service.Object = _Object

    class _BusName:
        def __init__(self, name, bus=None):
            self.name = name

    service.BusName = _BusName
    mod.SessionBus = lambda *a, **k: types.SimpleNamespace()
    mod.exceptions = exceptions
    mod.service = service
    return mod


class _FakeCore(QObject):
    """Just enough PlaybackCore surface for the MPRIS wiring to ride."""

    track_changed = pyqtSignal(object)
    state_changed = pyqtSignal(bool)
    position_changed = pyqtSignal(int)
    duration_changed = pyqtSignal(int)
    repeat_changed = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.engine = types.SimpleNamespace(current=None, repeat="off")
        self._playing = False
        self.volume = 0.8
        self.toggles = 0
        self.seeks: list[int] = []
        self.nexts = 0
        self.prevs = 0
        self.stops = 0
        self.shuffles = 0
        self.repeats: list[str] = []

    @property
    def is_playing(self):
        return self._playing

    @property
    def position_ms(self):
        return 42_000

    def toggle(self):
        self.toggles += 1
        self._playing = not self._playing

    def next(self):
        self.nexts += 1

    def previous(self):
        self.prevs += 1

    def stop(self):
        self.stops += 1

    def seek(self, ms):
        self.seeks.append(int(ms))

    def set_repeat(self, mode):
        self.repeats.append(mode)
        self.engine.repeat = mode

    def set_volume(self, value):
        self.volume = float(value)

    def shuffle(self):
        self.shuffles += 1


def test_mpris_noop_when_dbus_missing(monkeypatch, mpris_mod, qapp):
    """Even where dbus exists, absence must be simulated and harmless."""
    monkeypatch.setitem(sys.modules, "dbus", None)
    importlib.reload(mpris_mod)
    assert mpris_mod.MPRIS_AVAILABLE is False
    svc = mpris_mod.MprisService()
    svc.connect(_FakeCore(), summon=lambda: None)   # swallowed, warm air
    assert svc.start() is False
    svc.stop()
    assert svc.stop() is None                       # idempotent, never raises


def test_mpris_service_fake_dbus_lifecycle_and_sync(monkeypatch, mpris_mod, qapp):
    monkeypatch.setitem(sys.modules, "dbus", _fake_dbus())
    importlib.reload(mpris_mod)
    m = mpris_mod
    assert m.MPRIS_AVAILABLE is True
    summon = []
    core = _FakeCore()
    svc = m.MprisService()
    svc.connect(core, summon=lambda: summon.append(1))
    assert svc.start() is True
    assert svc.start() is False                     # already on stage

    root = svc.all_properties(m.ROOT_IFACE)
    assert root["Identity"] == "Hearth"
    assert root["DesktopEntry"] == "hearth"
    assert root["CanRaise"] is True
    player = svc.all_properties(m.PLAYER_IFACE)
    assert player["PlaybackStatus"] == "Stopped"
    assert player["CanSeek"] is True

    # metadata + status ride the same signals the tray uses
    track = make_track(video_id="mx1", duration_sec=213)
    core.track_changed.emit(track)
    meta = svc.all_properties(m.PLAYER_IFACE)["Metadata"]
    assert meta["xesam:title"] == track.title
    assert meta["mpris:trackid"].endswith("mx1")
    core._playing = True                            # the backend reports audio
    core.state_changed.emit(True)
    assert svc.property_value(m.PLAYER_IFACE, "PlaybackStatus") == "Playing"
    core.position_changed.emit(42_000)
    assert svc.property_value(m.PLAYER_IFACE, "Position") == 42_000_000
    core.engine.repeat = "one"                      # the engine owns truth
    core.repeat_changed.emit("one")
    assert svc.property_value(m.PLAYER_IFACE, "LoopStatus") == "Track"
    svc._push_tick()                                # the 1s throttle, by hand
    assert svc.property_value(m.PLAYER_IFACE, "Volume") == 0.8

    # the desk's transport + dials route into the core, never raises
    svc.play_pause()                                # playing → paused
    assert core.toggles == 1 and not core.is_playing
    svc.play()                                      # paused → playing
    assert core.toggles == 2 and core.is_playing
    svc.pause()                                     # playing → paused again
    assert core.toggles == 3 and not core.is_playing
    svc.next(), svc.previous(), svc.stop_playback()
    assert (core.nexts, core.prevs, core.stops) == (1, 1, 1)
    svc.raise_window()
    assert summon == [1]
    svc.seek_relative(5_000_000)                    # +5s, in microseconds
    assert core.seeks[-1] == 47_000                 # 42s + 5s, back in ms
    svc.seek_absolute(12_000_000)
    assert core.seeks[-1] == 12_000
    svc.set_property("Volume", 0.5)
    assert core.volume == 0.5
    svc.set_property("LoopStatus", "Playlist")
    assert core.repeats == ["all"]
    svc.set_property("Shuffle", True)
    assert core.shuffles == 1
    svc.set_property("Bogus", 1)                    # unknown dial: swallowed
    with pytest.raises(Exception):
        svc.property_value(m.ROOT_IFACE, "Nope")    # the shim must reject it

    # a core that explodes can never take the desk down with it
    core.toggle = lambda: 1 / 0
    svc.play_pause()                                # swallowed
    core.engine.current = None
    core.track_changed.emit(None)
    assert svc.all_properties(m.PLAYER_IFACE)["Metadata"] == {}

    svc.stop()
    assert svc._started is False
    svc.stop()                                      # idempotent


# ----------------------------------------------------------------- update whisper

@pytest.mark.parametrize("current,tag,expected", [
    ("0.6.3", "v0.7.0", True),       # the "v" prefix is furniture
    ("0.6.3", "0.7.0", True),
    ("0.6.3", "v0.6.3", False),      # equal is not newer
    ("v0.7.0", "v0.6.3", False),     # older
    ("0.10.0", "v0.9.9", False),     # numeric compare, not string compare
    ("0.6.3", "banana", False),      # garbage is never newer
    ("banana", "v1.0.0", True),
    ("0.6.3", "", False),
    ("0.6.3", None, False),
])
def test_compare_versions_matrix(current, tag, expected):
    assert compare_versions(current, tag) is expected


def test_fetch_latest_release_parses_and_fails_soft(monkeypatch):
    assert RELEASES_API_URL == (
        "https://api.github.com/repos/qtjg/hearth/releases/latest")

    payload = {"tag_name": "v0.7.0",
               "html_url": "https://github.com/qtjg/hearth/releases/tag/v0.7.0",
               "name": "The Big Burn"}

    class _Resp:
        def __init__(self, body):
            self._body = body

        def read(self):
            return json.dumps(self._body).encode("utf-8")

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    monkeypatch.setattr("urllib.request.urlopen",
                        lambda req, timeout=None: _Resp(payload))
    result = fetch_latest_release(timeout=0.1)
    assert result == {"tag_name": "v0.7.0", "html_url": payload["html_url"],
                      "name": "The Big Burn"}

    import urllib.error

    def _boom(req, timeout=None):
        raise urllib.error.URLError("offline again")

    monkeypatch.setattr("urllib.request.urlopen", _boom)
    assert fetch_latest_release() is None

    monkeypatch.setattr("urllib.request.urlopen",
                        lambda req, timeout=None: _Resp(["not", "a", "dict"]))
    assert fetch_latest_release() is None
    monkeypatch.setattr("urllib.request.urlopen",
                        lambda req, timeout=None: _Resp({"html_url": "x"}))
    assert fetch_latest_release() is None           # no tag → no news


def test_release_check_job_emits_payload(monkeypatch, qapp):
    seen = []
    job = ReleaseCheckJob(timeout=0.1)
    job.signals.fetched.connect(seen.append)
    monkeypatch.setattr("hearth.update_whisper.fetch_latest_release",
                        lambda timeout=None: {"tag_name": "v9.9.9"})
    job.run()
    assert seen == [{"tag_name": "v9.9.9"}]
    monkeypatch.setattr("hearth.update_whisper.fetch_latest_release",
                        lambda timeout=None: None)
    job.run()
    assert seen[-1] is None                          # quiet failure still lands


def test_whisper_disabled_by_default_never_schedules(tmp_path):
    assert config.UPDATE_CHECK_ENABLED is False      # the contract: opt-in
    whisper = UpdateWhisper(make_settings(tmp_path))
    assert whisper.due() is False
    assert whisper.next_check_delay_s() is None
    assert whisper.schedule() is False
    heard = []
    whisper.whisper.connect(lambda m, u, t: heard.append(t))
    whisper.absorb({"tag_name": "v99.0.0"})
    assert heard == []                               # off is off everywhere


def test_whisper_interval_gate_with_injected_clock(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "UPDATE_CHECK_ENABLED", True)
    clock = {"t": 1_700_000_000.0}   # a realistic epoch, not near zero
    whisper = UpdateWhisper(make_settings(tmp_path), clock=lambda: clock["t"])
    interval = config.UPDATE_CHECK_INTERVAL_H * 3600

    # never checked: the first look is already due — but scheduled ≥60s
    # after boot, so startup never waits on (or races into) the network
    assert whisper.next_check_delay_s() == 60.0
    assert whisper.due() is True

    whisper._note_checked()                          # a check just ran
    assert whisper.due() is False
    assert whisper.next_check_delay_s() == interval  # full interval ahead

    clock["t"] += interval - 120                     # 2 minutes still owed
    assert whisper.due() is False
    assert whisper.next_check_delay_s() == 120.0

    clock["t"] += 300                                # interval long since passed
    assert whisper.due() is True
    assert whisper.next_check_delay_s() == 60.0      # but never before 60s


def test_whisper_absorb_and_dismiss_suppression(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "UPDATE_CHECK_ENABLED", True)
    settings = make_settings(tmp_path)
    heard = []
    whisper = UpdateWhisper(settings)
    whisper.whisper.connect(lambda m, u, t: heard.append((m, u, t)))

    whisper.absorb(None)                             # offline check: silent
    assert heard == []
    whisper.absorb({"tag_name": config.VERSION})     # same version: no news
    whisper.absorb({"tag_name": "v0.1.0"})           # ancient: no news
    assert heard == []

    url = "https://github.com/qtjg/hearth/releases/tag/v99.0.0"
    whisper.absorb({"tag_name": "v99.0.0", "html_url": url})
    assert len(heard) == 1
    message, got_url, tag = heard[0]
    assert "v99.0.0" in message and "🕯️" in message
    assert got_url == url and tag == "v99.0.0"

    whisper.dismiss("v99.0.0")                       # "don't nag again"
    assert settings.value("update/dismissed_tag") == "v99.0.0"
    whisper.absorb({"tag_name": "v99.0.0", "html_url": url})
    assert len(heard) == 1                           # silenced for this tag
    whisper.absorb({"tag_name": "v100.0.0", "html_url": ""})
    assert len(heard) == 2                           # a new tag may speak


# ----------------------------------------------------------------- diagnostics

def test_diagnostics_report_contains_core_sections(tmp_path):
    store = HearthStore(tmp_path / "hearth.db")
    base = local_noon(2025, 1, 10)
    store.log_play(make_track(video_id="a", artist="Aster"), played_at=base)
    store.log_play(make_track(video_id="b", artist="Birch"), played_at=base + 60)
    store.log_play(make_track(video_id="a", artist="Aster"), played_at=base + 120)
    store.pin(make_track(video_id="a"))
    counters = {"catalogue": 5, "web": 1, "flat": 0}
    report = gather_report(store, resilience=counters)
    assert "Hearth diagnostics" in report
    assert config.VERSION in report
    assert str(store.db_path) in report
    assert "history" in report and "  3 rows" in report
    assert "favorites" in report and "  1 rows" in report
    assert "catalogue fetch legs" in report
    assert "catalogue: 5" in report and "web: 1" in report
    store.close()


def test_diagnostics_never_raises_on_empty_or_missing_store(tmp_path):
    store = HearthStore(tmp_path / "hearth.db")
    report = gather_report(store, resilience=None)
    assert isinstance(report, str)
    assert "database:" in report
    assert "favorites" in report
    assert report.strip().endswith("keep the fire warm 🔥")
    store.close()
    # no store at all — the page still prints, politely
    assert isinstance(gather_report(None, resilience=None), str)
    assert isinstance(gather_report(None, resilience=object()), str)


def test_diagnostics_log_tail_and_resilience_module(tmp_path):
    store = HearthStore(tmp_path / "hearth.db")
    (tmp_path / "hearth.log").write_text(
        "2026-01-01 INFO boot: fire lit\n"
        "\n"
        "2026-01-02 DEBUG watchdog tick\n",
        encoding="utf-8",
    )
    from hearth import ytm_resilience

    report = gather_report(store, resilience=ytm_resilience)
    assert "log tail" in report
    assert "watchdog tick" in report
    assert "junk-card tolerance:" in report          # the module's real counter
    store.close()


# ----------------------------------------------------------------- stats dashboard

def test_group_months_buckets_zero_fill_and_clamp():
    days = [("2024-03-15", 2), ("2024-03-16", 1), ("2024-01-31", 4),
            ("weird", 9)]
    assert group_months(days, months=4, today="2024-04-10") == [
        ("2024-01", 4), ("2024-02", 0), ("2024-03", 3), ("2024-04", 0)]
    assert group_months([], months=3, today="2024-04-10") == [
        ("2024-02", 0), ("2024-03", 0), ("2024-04", 0)]
    assert group_months([("2024-03-15", 2)], months=36, today="2024-04-10")
    assert len(group_months([("2024-03-15", 2)], months=99,
                            today="2024-04-10")) == 36   # clamped


def test_stats_view_populates_hero_artists_and_months(tmp_path, qapp):
    from hearth.config import get_palette

    store = HearthStore(tmp_path / "stats.db")
    base = local_noon(2025, 1, 10)
    store.log_play(make_track(video_id="a", artist="Aster"), played_at=base)
    store.log_play(make_track(video_id="a", artist="Aster"), played_at=base + 600)
    store.log_play(make_track(video_id="b", artist="Aster"), played_at=base + 1200)
    store.log_play(make_track(video_id="c", artist="Birch"),
                   played_at=base + 86_400)
    view = StatsView(get_palette("grove"), store=store)
    view.refresh()

    assert view.empty_state is False
    assert view._tiles["plays"].text() == "4"
    assert view._tiles["uniques"].text() == "3"
    assert view._tiles["days"].text() == "2"
    assert view._tiles["minutes"].text() == str((213 * 4) // 60)
    assert "2025-01-10" in view._first_lit.text()

    artists = []
    for i in range(view._artist_lay.count()):
        holder = view._artist_lay.itemAt(i).widget()
        if holder is None:
            continue
        row = holder.layout()
        artists.append((row.itemAt(0).widget().text(),
                        row.itemAt(1).widget().text()))
    assert artists[0] == ("Aster", "3 plays")        # 3 plays outrank 1
    assert artists[1] == ("Birch", "1 play")

    assert [t.video_id for t in view._top.current_tracks] == ["a", "c", "b"]
    assert len(view._months_chart._months) == 12     # a full year of slots
    store.close()


def test_stats_view_empty_state(tmp_path, qapp):
    from hearth.config import get_palette

    view = StatsView(get_palette("grove"))            # no store at all
    view.refresh()
    assert view.empty_state is True
    assert view._empty.text() == "no plays yet — light the fire"
    assert view._pages.currentIndex() == 1

    window = MainWindow(None, store=HearthStore(tmp_path / "empty.db"))
    window.show_view("stats")
    assert window.stack.currentWidget() is window.stats_view
    assert window.stats_view.empty_state is True
    assert window._nav["stats"].isChecked()
    assert any(btn.text() == "📊 Stats" for btn in window._nav.values())


def test_stats_view_refreshes_on_open(tmp_path, qapp):
    """Opening 📊 Stats re-reads the store — the numbers are never stale."""
    store = HearthStore(tmp_path / "open.db")
    store.log_play(make_track(video_id="a", artist="Aster"),
                   played_at=local_noon(2025, 3, 4))
    window = MainWindow(None, store=store)
    assert window.stats_view.empty_state is True     # never opened yet
    window.show_view("stats")
    assert window.stack.currentWidget() is window.stats_view
    assert window.stats_view.empty_state is False    # opening pulled the numbers
    store.close()


def test_stats_view_double_click_plays_via_playlist_picked(tmp_path, qapp):
    store = HearthStore(tmp_path / "play.db")
    base = local_noon(2025, 2, 1)
    store.log_play(make_track(video_id="a"), played_at=base)
    store.log_play(make_track(video_id="a"), played_at=base + 60)
    store.log_play(make_track(video_id="b"), played_at=base + 120)
    window = MainWindow(None, store=store)
    window.show_view("stats")
    picked = []
    window.playlist_picked.connect(
        lambda tracks, start: picked.append((list(tracks), start)))
    first = window.stats_view._top._list.item(0)
    window.stats_view._top._list.itemDoubleClicked.emit(first)
    assert picked and picked[0][1] == 0
    assert picked[0][0][0].video_id == "a"           # most-played sits on top
    assert [t.video_id for t in picked[0][0]] == ["a", "b"]
    store.close()


# ----------------------------------------------------------------- config & wiring

def test_config_service_flags_exist():
    assert config.MPRIS_ENABLED is True              # on by default, guarded
    assert config.UPDATE_CHECK_ENABLED is False      # the whisper is opt-in
    assert config.UPDATE_CHECK_INTERVAL_H == 12
    assert config.STATS_TOP_LIMIT >= 5
    assert config.REPO_URL == "https://github.com/qtjg/hearth"
    assert config.VERSION


def test_app_boots_whisper_mpris_and_stats(tmp_path, qapp):
    from hearth.update_whisper import UpdateWhisper

    hearth = make_hearth(tmp_path)
    assert isinstance(hearth.whisper, UpdateWhisper)
    assert hearth.whisper.due() is False             # default off → no checks
    # the service is either the real one or the guarded no-op twin —
    # both answer the same three-call API
    for call in (hearth.mpris.connect, hearth.mpris.start, hearth.mpris.stop):
        assert callable(call)
    assert hearth.mpris.stop() is None
    assert "stats" in hearth.window.VIEWS
    labels = [a.label for a in hearth.command_palette.actions]
    assert "Go to Stats" in labels
    hearth.shutdown()


def test_app_mpris_gate_and_core_wiring(monkeypatch, tmp_path, qapp):
    """The config gate is real: MPRIS_ENABLED=False must leave the bus
    unclaimed even where dbus works, and True must wire the very core
    the tray rides."""
    import hearth.app as app_mod

    class _SpyMpris:
        def __init__(self):
            self.connected_core = None
            self.starts = 0
            self.stops = 0

        def connect(self, core, summon=None, quit=None):
            self.connected_core = core

        def start(self):
            self.starts += 1
            return True

        def stop(self):
            self.stops += 1
            return None

    monkeypatch.setattr(app_mod, "MPRIS_AVAILABLE", True)
    monkeypatch.setattr(app_mod, "MprisService", _SpyMpris)

    # gate closed: the twin is built, but nothing wired, nothing claimed
    monkeypatch.setattr(config, "MPRIS_ENABLED", False)
    hearth = make_hearth(tmp_path / "gate-off")
    assert hearth.mpris.starts == 0
    assert hearth.mpris.connected_core is None
    hearth.shutdown()
    assert hearth.mpris.stops == 1                   # shutdown still tidies up

    # gate open: started exactly once, on the app's own playback core
    monkeypatch.setattr(config, "MPRIS_ENABLED", True)
    hearth = make_hearth(tmp_path / "gate-on")
    assert hearth.mpris.starts == 1
    assert hearth.mpris.connected_core is hearth.core
    hearth.shutdown()


def test_app_update_whisper_wiring_and_dismissal(monkeypatch, tmp_path, qapp):
    monkeypatch.setattr(config, "UPDATE_CHECK_ENABLED", True)
    hearth = make_hearth(tmp_path)
    heard = []
    hearth.whisper.whisper.connect(
        lambda m, u, t: heard.append((m, u, t)))
    url = "https://github.com/qtjg/hearth/releases/tag/v99.0.0"
    hearth.whisper.absorb({"tag_name": "v99.0.0", "html_url": url})
    assert heard and heard[0][2] == "v99.0.0"
    status = hearth.window.player_bar._artist.text()
    assert "v99.0.0" in status and url in status     # message + link delivered

    hearth._dismiss_update_whisper()
    assert hearth.settings.value("update/dismissed_tag") == "v99.0.0"
    hearth.whisper.absorb({"tag_name": "v99.0.0", "html_url": url})
    assert len(heard) == 1                           # never nags the same tag
    hearth.shutdown()


def test_app_diagnostics_dialog(tmp_path, qapp):
    hearth = make_hearth(tmp_path)
    hearth._show_diagnostics()
    dlg = hearth._diag_dlg
    report = dlg._text.toPlainText()
    assert "Hearth diagnostics" in report
    assert "database:" in report
    dlg._copy()
    assert dlg._text.toPlainText() in \
        hearth.qapp.clipboard().text()
    dlg.close()
    dlg.deleteLater()
    hearth.shutdown()
