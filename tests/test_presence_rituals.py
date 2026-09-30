"""v0.7.0 finale: Discord Rich Presence, the Glow Mix, the full history
page, playlist export/import — headless, offscreen, no network, and no
real Discord (pypresence is stubbed or absent throughout)."""

import importlib
import json
import sys
import time
from datetime import datetime
from pathlib import Path

import pytest
from PyQt6.QtCore import Qt

from hearth import config
from hearth.app import GlowMixJob, blend_glow, glow_seeds
from hearth.discord_presence import DiscordPresence, Throttle, presence_payload
from hearth.models import Track
from hearth.storage import HearthStore
from hearth.window import HistoryView, MainWindow, day_label
from hearth.config import get_palette

from .test_app_smoke import make_hearth
from .test_models import make_track


def local_noon(year: int, month: int, day: int) -> float:
    """Local noon of a calendar day — immune to any machine timezone."""
    return datetime(year, month, day, 12).timestamp()


@pytest.fixture
def status_notes():
    """Capture the surface's status notes (the real handlers stay wired)."""
    def _spy(surface) -> list:
        notes: list = []
        original = surface.set_status

        def _capture(text) -> None:
            notes.append(text)
            original(text)   # the label still paints; tests just watch

        surface.set_status = _capture
        return notes

    return _spy


def seed_rotation(store: HearthStore, n: int = 12) -> None:
    """A believable rotation: n plays spread over a few artists, recent."""
    now = time.time()
    for i in range(n):
        track = make_track(video_id=f"rot{i}", title=f"Rotation {i}",
                           artist=f"Artist {i // 3}")
        store.log_play(track, played_at=now - i * 10)


# =================================================================
# Discord Rich Presence — the guarded module
# =================================================================

@pytest.fixture
def presence_mod():
    """hearth.discord_presence reloaded with pypresence forced absent."""
    import hearth.discord_presence as dp

    saved = sys.modules.pop("pypresence", None)
    importlib.reload(dp)
    try:
        yield dp
    finally:
        if saved is not None:
            sys.modules["pypresence"] = saved
        importlib.reload(dp)


def test_module_imports_and_noops_without_pypresence(presence_mod):
    """No pypresence anywhere: clean import, silent no-op twin, no ok."""
    assert presence_mod.AVAILABLE is False
    presence = presence_mod.DiscordPresence()
    assert presence.ok is False
    assert presence.start("1234567890") is False
    assert presence.update_track(make_track(), 1.0, 213.0, "https://x") is False
    presence.clear()
    presence.stop()
    assert presence.ok is False
    assert presence.update_track(None) is False     # nothing to say, no crash


def test_throttle_first_passes_within_suppressed_boundary_passes():
    clock = {"t": 0.0}
    th = Throttle(15.0, clock=lambda: clock["t"])
    assert th.allow() is True               # the first call always passes
    clock["t"] = 5.0
    assert th.allow() is False              # inside the window
    clock["t"] = 14.999
    assert th.allow() is False
    clock["t"] = 15.0
    assert th.allow() is True               # exactly the boundary: passes
    clock["t"] = 29.999
    assert th.allow() is False
    clock["t"] = 30.0
    assert th.allow() is True
    th.reset()
    assert th.allow() is True               # reset re-arms immediately


def test_throttle_stamp_rearms_without_passing():
    clock = {"t": 0.0}
    th = Throttle(15.0, clock=lambda: clock["t"])
    th.stamp()                              # an out-of-band push owns the window
    clock["t"] = 10.0
    assert th.allow() is False
    clock["t"] = 15.0
    assert th.allow() is True


def test_payload_builder_title_artist_elapsed_buttons():
    track = make_track()
    payload = presence_payload(
        track, elapsed_s=30.0, duration_s=213.0,
        youtube_url="https://www.youtube.com/watch?v=dQw4w9WgXcQ", now=1000.0,
    )
    assert payload["details"] == "Never Gonna Give You Up"
    assert payload["state"] == "Rick Astley"
    assert payload["large_text"] == "Rick Astley"       # album-ish: the artist
    assert payload["start"] == 970                      # now - elapsed
    assert payload["end"] == 970 + 213                  # start + duration
    assert payload["buttons"] == [{
        "label": "Listen along",
        "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
    }]


def test_payload_builder_edge_cases():
    assert presence_payload(None) == {}                 # no track, no presence
    bare = presence_payload(make_track(artist=""))
    assert bare["state"] == "Unknown artist"
    plain = presence_payload(make_track())              # no timing, no URL
    assert "start" not in plain and "end" not in plain
    assert "buttons" not in plain
    assert presence_payload(make_track(title="   ")) == {}   # nothing to say
    no_dur = presence_payload(make_track(), elapsed_s=5.0, duration_s=0, now=9.0)
    assert no_dur["start"] == 4 and "end" not in no_dur


class _FakeRpc:
    """The pypresence surface, stubbed: connect/update/clear/close."""

    fail_connect = False
    fail_update = False
    instances: list = []

    def __init__(self, client_id=""):
        self.client_id = client_id
        self.updates: list = []
        self.cleared = 0
        self.closed = 0
        type(self).instances.append(self)

    def connect(self) -> None:
        if type(self).fail_connect:
            raise RuntimeError("Discord is not running")

    def update(self, **payload) -> None:
        if type(self).fail_update:
            raise RuntimeError("IPC died")
        self.updates.append(payload)

    def clear(self) -> None:
        self.cleared += 1

    def close(self) -> None:
        self.closed += 1


@pytest.fixture
def fake_rpc(monkeypatch):
    """Point the presence module at _FakeRpc as if pypresence were real."""
    import hearth.discord_presence as dp

    _FakeRpc.instances = []
    _FakeRpc.fail_connect = False
    _FakeRpc.fail_update = False
    monkeypatch.setattr(dp, "AVAILABLE", True)
    monkeypatch.setattr(dp, "_RealPresence", _FakeRpc)
    return _FakeRpc


def test_presence_lifecycle_with_fake_rpc(fake_rpc):
    clock = {"t": 100.0}
    presence = DiscordPresence(backoff_s=60.0, clock=lambda: clock["t"])
    assert presence.start("app-id") is True
    assert presence.ok is True
    assert _FakeRpc.instances[0].client_id == "app-id"
    track = make_track()
    assert presence.update_track(track, 10.0, 213.0, "https://youtu.be/x") is True
    rpc = _FakeRpc.instances[0]
    assert rpc.updates[0]["details"] == "Never Gonna Give You Up"
    assert rpc.updates[0]["buttons"][0]["label"] == "Listen along"
    presence.clear()
    assert rpc.cleared == 1
    presence.stop()
    assert rpc.closed == 1
    assert presence.ok is False
    presence.stop()   # idempotent


def test_presence_connect_failure_earns_backoff_not_a_storm(fake_rpc):
    fake_rpc.fail_connect = True
    clock = {"t": 0.0}
    presence = DiscordPresence(backoff_s=60.0, clock=lambda: clock["t"])
    assert presence.start("app-id") is False
    assert presence.ok is False
    assert presence.update_track(make_track()) is False   # inside backoff
    assert len(_FakeRpc.instances) == 1                   # no retry spam
    clock["t"] = 61.0                                     # past the window…
    assert presence.update_track(make_track()) is False   # …one polite retry
    assert len(_FakeRpc.instances) == 2
    clock["t"] = 62.0
    assert presence.update_track(make_track()) is False   # and quiet again
    assert len(_FakeRpc.instances) == 2


def test_presence_update_failure_drops_ok_and_recovers(fake_rpc):
    clock = {"t": 0.0}
    presence = DiscordPresence(backoff_s=60.0, clock=lambda: clock["t"])
    presence.start("app-id")
    fake_rpc.fail_update = True
    assert presence.update_track(make_track(), 1.0, 10.0) is False
    assert presence.ok is False
    fake_rpc.fail_update = False
    clock["t"] = 120.0   # well past the backoff
    assert presence.update_track(make_track(), 1.0, 10.0) is True
    assert presence.ok is True


def test_presence_clear_failure_is_swallowed(fake_rpc):
    clock = {"t": 0.0}
    presence = DiscordPresence(backoff_s=60.0, clock=lambda: clock["t"])
    presence.start("app-id")
    _FakeRpc.instances[0].cleared = None   # raise TypeError inside clear()
    presence.clear()
    assert presence.ok is False


# =================================================================
# Discord Rich Presence — app wiring (gated, throttled)
# =================================================================

def test_presence_wiring_gated_off_by_config(monkeypatch, tmp_path, qapp):
    monkeypatch.setattr(config, "DISCORD_RPC_ENABLED", False)
    hearth = make_hearth(tmp_path)
    calls: list = []
    monkeypatch.setattr(hearth.presence, "start",
                        lambda cid: calls.append(cid) or True)
    hearth._on_discord_action(True)   # a user flips the switch anyway
    assert calls == []                # the flag gates everything: no attempt
    hearth.shutdown()


def test_boot_with_flag_on_never_connects(monkeypatch, tmp_path, qapp):
    monkeypatch.setattr(config, "DISCORD_RPC_ENABLED", True)
    hearth = make_hearth(tmp_path)
    assert hearth.presence.ok is False   # presence waits for the user
    hearth.shutdown()


def test_presence_empty_client_id_status_note(monkeypatch, tmp_path, qapp,
                                              status_notes):
    monkeypatch.setattr(config, "DISCORD_RPC_ENABLED", True)
    monkeypatch.setattr(config, "DISCORD_CLIENT_ID", "")
    hearth = make_hearth(tmp_path)
    notes = status_notes(hearth.window)
    calls: list = []
    monkeypatch.setattr(hearth.presence, "start",
                        lambda cid: calls.append(cid) or True)
    hearth._on_discord_action(True)
    assert calls == []                              # no connection attempted
    assert "DISCORD_CLIENT_ID" in notes[-1]
    hearth.shutdown()


def test_presence_toggle_on_pushes_track_then_throttled(monkeypatch, tmp_path,
                                                        qapp, status_notes):
    monkeypatch.setattr(config, "DISCORD_RPC_ENABLED", True)
    monkeypatch.setattr(config, "DISCORD_CLIENT_ID", "app-id")
    hearth = make_hearth(tmp_path)
    notes = status_notes(hearth.window)
    started: list = []
    pushed: list = []
    monkeypatch.setattr(hearth.presence, "start",
                        lambda cid: started.append(cid) or True)
    monkeypatch.setattr(hearth.presence, "update_track",
                        lambda *a, **k: pushed.append((a, k)) or True)
    clock = {"t": 0.0}
    hearth._presence_throttle = Throttle(15.0, clock=lambda: clock["t"])
    hearth._on_discord_action(True)
    assert started == ["app-id"]
    assert "on" in notes[-1]

    track = make_track()
    hearth.core.engine.current = track
    hearth.core.track_changed.emit(track)           # track change: immediate
    assert len(pushed) == 1
    assert pushed[0][1]["youtube_url"].endswith(track.video_id)

    clock["t"] = 1.0
    hearth.core.position_changed.emit(1000)         # inside the stamped window
    assert len(pushed) == 1
    clock["t"] = 16.0
    hearth.core.position_changed.emit(16000)        # window over: one push
    assert len(pushed) == 2
    hearth.shutdown()


def test_presence_track_none_clears_and_toggle_off_disconnects(
        monkeypatch, tmp_path, qapp, status_notes):
    monkeypatch.setattr(config, "DISCORD_RPC_ENABLED", True)
    monkeypatch.setattr(config, "DISCORD_CLIENT_ID", "app-id")
    hearth = make_hearth(tmp_path)
    notes = status_notes(hearth.window)
    pushed: list = []
    cleared: list = []
    stopped: list = []
    monkeypatch.setattr(hearth.presence, "start", lambda cid: True)
    monkeypatch.setattr(hearth.presence, "update_track",
                        lambda *a, **k: pushed.append(a) or True)
    monkeypatch.setattr(hearth.presence, "clear", lambda: cleared.append(1))
    monkeypatch.setattr(hearth.presence, "stop", lambda: stopped.append(1))
    hearth._on_discord_action(True)
    track = make_track()
    hearth.core.engine.current = track
    hearth.core.track_changed.emit(track)
    assert len(pushed) == 1
    hearth.core.track_changed.emit(None)            # between tracks: clear
    assert len(cleared) == 1

    hearth._on_discord_action(False)
    assert len(stopped) == 1
    assert "off" in notes[-1]
    pushed.clear()
    hearth.core.track_changed.emit(track)           # disconnected: no push
    assert pushed == []
    hearth._on_discord_action(False)                # off twice: stop is idempotent
    assert len(stopped) == 2
    assert len(cleared) == 3   # between-tracks + one wipe per unwind (all no-ops)
    hearth.shutdown()


def test_presence_shutdown_stops_the_bridge(monkeypatch, tmp_path, qapp):
    monkeypatch.setattr(config, "DISCORD_RPC_ENABLED", True)
    hearth = make_hearth(tmp_path)
    stopped: list = []
    monkeypatch.setattr(hearth.presence, "stop", lambda: stopped.append(1))
    hearth.shutdown()
    assert stopped == [1]


# =================================================================
# The Glow Mix — pure blend + controller with fakes
# =================================================================

def test_blend_glow_proportions_dedupe_cap():
    rotation = [make_track(video_id=f"rot{i}") for i in range(30)]
    kindred = [make_track(video_id=f"kin{i}") for i in range(20)]
    mix = blend_glow(rotation, kindred, config.GLOW_MIX_SIZE)
    assert len(mix) == 30
    ids = [t.video_id for t in mix]
    assert len(set(ids)) == 30                       # fully deduped
    rot = sum(1 for t in mix if t.video_id.startswith("rot"))
    assert rot == 18                                 # the ~60% rotation share
    assert all(t.video_id.startswith("rot") for t in mix[:18])
    assert all(t.video_id.startswith("kin") for t in mix[18:])


def test_blend_glow_dedupes_kindred_against_rotation():
    rotation = [make_track(video_id="a"), make_track(video_id="b")]
    kindred = [make_track(video_id="b"), make_track(video_id="b"),
               make_track(video_id="c"), make_track(video_id="c")]
    mix = blend_glow(rotation, kindred, 10)
    ids = [t.video_id for t in mix]
    assert ids.count("b") == 1 and ids.count("c") == 1


def test_blend_glow_short_kindred_topped_up_by_rotation():
    rotation = [make_track(video_id=f"r{i}") for i in range(10)]
    kindred = [make_track(video_id="k0")]
    mix = blend_glow(rotation, kindred, 5)
    assert [t.video_id for t in mix] == ["r0", "r1", "r2", "k0", "r3"]
    assert [t.video_id for t in blend_glow([], [], 30)] == []
    assert blend_glow([make_track()], [], 0) == []


def test_glow_seeds_one_per_distinct_artist():
    rotation = [
        make_track(video_id="a1", artist="A"),
        make_track(video_id="a2", artist="A"),
        make_track(video_id="b1", artist="B"),
        make_track(video_id="c1", artist=""),
        make_track(video_id="d1", artist="D"),
    ]
    assert [t.video_id for t in glow_seeds(rotation, 3)] == ["a1", "b1", "c1"]
    assert len(glow_seeds(rotation, 10)) == 4        # artist-less is its own seed
    assert glow_seeds([], 3) == []


def test_glow_mix_job_harvests_and_survives_bad_seeds(qapp):
    calls: list = []

    class FakeCatalog:
        def radio(self, video_id, limit=25):
            calls.append((video_id, limit))
            if video_id == "boom":
                raise RuntimeError("network down")
            return [make_track(video_id=f"k-{video_id}")]

    job = GlowMixJob(FakeCatalog(),
                     [make_track(video_id="s1"), make_track(video_id="boom")],
                     [make_track(video_id="rot")])
    got: list = []
    job.signals.finished.connect(lambda payload: got.append(payload))
    job.run()
    rotation, kindred = got[0]
    assert [t.video_id for t in rotation] == ["rot"]
    assert [t.video_id for t in kindred] == ["k-s1"]   # the boom seed skipped
    assert calls[0][1] == config.RADIO_LIMIT


def test_glow_mix_empty_rotation_gets_a_note(tmp_path, qapp, status_notes):
    hearth = make_hearth(tmp_path)
    notes = status_notes(hearth.window)
    hearth._glow_mix()
    assert "Nothing on repeat" in notes[-1]
    assert hearth.core.engine.current is None
    hearth.shutdown()


class _FakeStore:
    """Just the one method the Glow Mix needs from a store."""

    def __init__(self, rotation):
        self._rotation = list(rotation)

    def on_repeat(self, limit):
        return self._rotation[:limit]


def test_glow_mix_blend_flow_with_injected_fetcher(tmp_path, qapp, status_notes):
    hearth = make_hearth(tmp_path)
    notes = status_notes(hearth.window)
    seed_rotation(hearth.store, 30)                 # enough for the ~60% share
    kindred = [make_track(video_id=f"kin{i}", artist=f"Kindred {i}")
               for i in range(30)]
    hearth._start_glow_mix(fetch_kindred=lambda seeds: kindred)
    engine = hearth.core.engine
    played = ([engine.current] if engine.current else []) + list(engine.upcoming)
    ids = [t.video_id for t in played]
    assert len(ids) == config.GLOW_MIX_SIZE
    assert len(set(ids)) == config.GLOW_MIX_SIZE
    assert sum(1 for v in ids if v.startswith("rot")) == 18
    assert "Glow Mix" in notes[-1]
    hearth.shutdown()


def test_glow_mix_fetch_failure_falls_back_to_rotation(tmp_path, qapp,
                                                       status_notes):
    hearth = make_hearth(tmp_path)
    notes = status_notes(hearth.window)
    seed_rotation(hearth.store)

    def boom(seeds):
        raise RuntimeError("the catalog is a smoking crater")

    hearth._start_glow_mix(fetch_kindred=boom)
    engine = hearth.core.engine
    played = ([engine.current] if engine.current else []) + list(engine.upcoming)
    assert {t.video_id for t in played} == {f"rot{i}" for i in range(12)}
    assert "straight up" in notes[-1]
    hearth.shutdown()


def test_glow_mix_empty_fetch_also_falls_back(tmp_path, qapp):
    hearth = make_hearth(tmp_path)
    seed_rotation(hearth.store, 3)
    hearth._start_glow_mix(store=_FakeStore(
        [make_track(video_id="f0", artist="F")]),
        fetch_kindred=lambda seeds: [])
    engine = hearth.core.engine
    played = ([engine.current] if engine.current else []) + list(engine.upcoming)
    assert [t.video_id for t in played] == ["f0"]
    hearth.shutdown()


def test_glow_mix_test_mode_plays_rotation_without_network(tmp_path, qapp,
                                                           status_notes):
    hearth = make_hearth(tmp_path)   # enable_streaming=False
    notes = status_notes(hearth.window)
    seed_rotation(hearth.store, 5)
    hearth._glow_mix()
    engine = hearth.core.engine
    played = ([engine.current] if engine.current else []) + list(engine.upcoming)
    assert {t.video_id for t in played} == {f"rot{i}" for i in range(5)}
    assert "Glow Mix" in notes[-1]
    hearth.shutdown()


def test_glow_mix_button_end_to_end_through_the_window(tmp_path, qapp,
                                                       status_notes):
    hearth = make_hearth(tmp_path)
    notes = status_notes(hearth.window)
    seed_rotation(hearth.store, 12)
    hearth.window.home_view._glow_button.click()   # the ✨ button, the real path
    engine = hearth.core.engine
    played = ([engine.current] if engine.current else []) + list(engine.upcoming)
    assert len(played) == 12
    assert "Glow Mix" in notes[-1]
    hearth.shutdown()


# =================================================================
# The history page
# =================================================================

def test_history_view_day_chips_newest_first(qapp, tmp_path):
    store = HearthStore(tmp_path / "hist.db")
    store.log_play(make_track(video_id="old"), played_at=local_noon(2026, 2, 1))
    store.log_play(make_track(video_id="new2"), played_at=local_noon(2026, 2, 16))
    store.log_play(make_track(video_id="new1"), played_at=local_noon(2026, 2, 16))
    view = HistoryView(get_palette("grove"), store=store)
    view.refresh()
    assert list(view._chips.keys()) == [None, "2026-02-16", "2026-02-01"]
    assert view._chips[None].text() == "All"
    assert view._chips["2026-02-16"].text() == day_label("2026-02-16") == "Feb 16"
    assert view._chips["2026-02-16"].toolTip() == "2 plays"
    assert view._chips[None].isChecked()            # "All" is the default
    assert view._chips["2026-02-01"].isChecked() is False
    store.close()


def test_history_view_day_selection_lists_that_day(qapp, tmp_path):
    store = HearthStore(tmp_path / "hist.db")
    store.log_play(make_track(video_id="old"), played_at=local_noon(2026, 2, 1))
    store.log_play(make_track(video_id="new1"), played_at=local_noon(2026, 2, 16))
    store.log_play(make_track(video_id="new2"), played_at=local_noon(2026, 2, 16))
    view = HistoryView(get_palette("grove"), store=store)
    view.refresh()
    view._select_day("2026-02-01")
    assert [t.video_id for t in view.current_tracks] == ["old"]
    view._select_day("2026-02-16")
    assert [t.video_id for t in view.current_tracks] == ["new2", "new1"]
    assert view._chips["2026-02-16"].isChecked()
    view._select_day(None)
    assert len(view.current_tracks) == 3
    store.close()


def test_history_view_all_paging_appends(qapp, tmp_path):
    store = HearthStore(tmp_path / "hist.db")
    base = local_noon(2026, 2, 10)
    for i in range(5):
        store.log_play(make_track(video_id=f"t{i}"), played_at=base + i)
    view = HistoryView(get_palette("grove"), store=store, page_size=3)
    view.refresh()
    assert [t.video_id for t in view.current_tracks] == ["t4", "t3", "t2"]
    assert not view._more_btn.isHidden()            # has_more → Show more
    view._show_more()
    assert [t.video_id for t in view.current_tracks] == ["t4", "t3", "t2",
                                                         "t1", "t0"]
    assert view._more_btn.isHidden()                # nothing left to page
    view._select_day("2026-02-10")                  # a day view never pages
    assert view._more_btn.isHidden()
    store.close()


def test_history_view_empty_state(qapp, tmp_path):
    store = HearthStore(tmp_path / "hist.db")
    view = HistoryView(get_palette("grove"), store=store)
    view.refresh()
    assert not view._empty.isHidden()
    assert "light the fire" in view._empty.text()
    assert view._list.isHidden()
    assert view._chips_area.isHidden()
    store.close()


def test_history_view_registered_in_navigation(qapp):
    window = MainWindow("grove")
    assert "history" in MainWindow.VIEWS
    window.show_view("history")
    assert window.stack.currentIndex() == MainWindow.VIEWS.index("history")
    assert window._nav["history"].isChecked()
    assert window._nav["history"].text().startswith("🕘")


def test_history_double_click_plays_via_core(tmp_path, qapp):
    hearth = make_hearth(tmp_path)
    hearth.store.log_play(make_track(video_id="h1"),
                          played_at=local_noon(2026, 2, 10))
    hearth.window.show_view("history")   # opening the page refreshes it
    view = hearth.window.history_view
    assert view._list.count() == 1
    view._list.itemDoubleClicked.emit(view._list.item(0))
    current = hearth.core.engine.current
    assert current is not None and current.video_id == "h1"
    assert len(hearth.store.history()) == 2   # the original + the fresh play
    hearth.shutdown()


# =================================================================
# Playlist export / import UI
# =================================================================

def test_export_all_json_then_import_roundtrip(qapp, tmp_path):
    store = HearthStore(tmp_path / "a.db")
    pid = store.create_playlist("Road trip")
    store.add_to_playlist(pid, make_track(video_id="abc"))
    store.add_to_playlist(pid, make_track(video_id="def"))
    win = MainWindow("grove", store=store)
    path = tmp_path / "all.json"
    assert win._export_all_playlists_to(str(path)) is True
    assert path.exists()
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["playlists"][0]["name"] == "Road trip"

    store2 = HearthStore(tmp_path / "b.db")
    win2 = MainWindow("grove", store=store2)
    note = win2._import_playlist_file(str(path))
    assert "1 playlist(s)" in note
    playlists = store2.playlists()
    assert len(playlists) == 1 and playlists[0][1] == "Road trip"
    assert [t.video_id for t in store2.playlist_tracks(playlists[0][0])] == [
        "abc", "def"]
    store.close()
    store2.close()


def test_export_m3u_then_import_roundtrip(qapp, tmp_path):
    store = HearthStore(tmp_path / "a.db")
    pid = store.create_playlist("Fireside")
    store.add_to_playlist(pid, make_track(video_id="v1", title="Ember",
                                          artist="Woods", duration="3:00",
                                          duration_sec=180))
    win = MainWindow("grove", store=store)
    path = tmp_path / "Fireside.m3u"
    assert win._export_playlist_m3u_to(pid, str(path)) is True
    text = path.read_text(encoding="utf-8")
    assert text.startswith("#EXTM3U")
    assert "music.youtube.com/watch?v=v1" in text

    store2 = HearthStore(tmp_path / "b.db")
    win2 = MainWindow("grove", store=store2)
    note = win2._import_playlist_file(str(path))   # .m3u → import_m3u, stem name
    assert "Fireside" in note
    playlists = store2.playlists()
    assert len(playlists) == 1 and playlists[0][1] == "Fireside"
    tracks = store2.playlist_tracks(playlists[0][0])
    assert [t.video_id for t in tracks] == ["v1"]
    assert tracks[0].title == "Ember" and tracks[0].duration_sec == 180
    store.close()
    store2.close()


def test_import_garbage_and_unsupported_files_stay_boring(qapp, tmp_path):
    store = HearthStore(tmp_path / "a.db")
    win = MainWindow("grove", store=store)
    garbage = tmp_path / "garbage.json"
    garbage.write_text("not json at all {{{", encoding="utf-8")
    assert "No playlists" in win._import_playlist_file(str(garbage))
    assert store.playlists() == []

    hostile = tmp_path / "hostile.m3u8"
    hostile.write_text("#EXTM3U\n#EXTINF:10,Name - No URL\n", encoding="utf-8")
    assert "No playable entries" in win._import_playlist_file(str(hostile))
    # storage quirk (documented): import_m3u creates the named list first, so
    # an entry-less file leaves a 0-track playlist — returned 0 either way
    assert store.playlist_tracks(store.playlists()[0][0]) == []
    win.store.delete_playlist(store.playlists()[0][0])

    txt = tmp_path / "list.txt"
    txt.write_text("whatever", encoding="utf-8")
    notes: list = []
    original = win.set_status

    def _capture(text) -> None:
        notes.append(text)
        original(text)

    win.set_status = _capture
    win._import_playlist_file(str(txt))
    assert notes and "Unsupported" in notes[-1]    # a note reached the status line
    store.close()


def test_import_refreshes_the_playlist_list(qapp, tmp_path):
    store = HearthStore(tmp_path / "a.db")
    pid = store.create_playlist("Exported")
    store.add_to_playlist(pid, make_track())
    win = MainWindow("grove", store=store)
    path = tmp_path / "out.json"
    assert win._export_all_playlists_to(str(path)) is True
    store.delete_playlist(pid)
    win.refresh_playlists()
    assert win._playlist_list.count() == 0
    win._import_playlist_file(str(path))           # handler refreshes by contract
    assert win._playlist_list.count() == 1
    store.close()


def test_playlist_menu_offers_storage_exports(qapp, tmp_path):
    store = HearthStore(tmp_path / "a.db")
    pid = store.create_playlist("Mix")
    win = MainWindow("grove", store=store)
    menu = win._build_playlist_menu(pid)
    texts = [act.text() for act in menu.actions()]
    assert "📤 Export all (JSON)…" in texts        # export_playlists = every list
    assert "📤 Export M3U…" in texts               # export_m3u = this list
    assert "Rename" in texts and "Delete" in texts
    assert "⬆ Export…" in texts                    # the original share export stays
    menu.deleteLater()
    store.close()


def test_library_import_button_drives_the_dialog(qapp, tmp_path, monkeypatch,
                                                 status_notes):
    from PyQt6.QtWidgets import QFileDialog

    store = HearthStore(tmp_path / "a.db")
    win = MainWindow("grove", store=store)
    notes = status_notes(win)
    pid = store.create_playlist("From dialog")
    store.add_to_playlist(pid, make_track(video_id="dlg1"))
    out = tmp_path / "dialog.json"
    win._export_all_playlists_to(str(out))
    store.delete_playlist(pid)
    win.refresh_playlists()
    assert win._playlist_list.count() == 0

    picked: list = []
    monkeypatch.setattr(
        QFileDialog, "getOpenFileName",
        staticmethod(lambda *a, **k: picked.append(a) or (str(out), "")))
    win.library_view._import_btn.click()           # the hero-row button, for real
    assert picked, "the import dialog was never asked"
    assert win._playlist_list.count() == 1         # imported + refreshed
    assert "Imported 1 playlist(s)" in notes[-1]
    store.close()


# =================================================================
# packaging: the optional extra
# =================================================================

def test_pyproject_declares_discord_extra():
    import tomllib

    root = Path(__file__).resolve().parents[1]
    data = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    extra = data["project"]["optional-dependencies"]["discord"]
    assert any("pypresence" in dep for dep in extra)
    assert config.DISCORD_RPC_ENABLED is False     # asleep in tests/CI
    assert config.DISCORD_CLIENT_ID == ""          # user-set, empty by default
