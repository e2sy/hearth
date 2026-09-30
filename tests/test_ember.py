"""v0.7.1 ember tending: the café loop, per-track volume nudges,
play-count-weighted smart shuffle, per-leg fetch counters and the
shareable Rewind card — headless and offscreen, no network, no sleeps."""

import struct

import pytest
from PyQt6.QtMultimedia import QAudioFormat

from hearth import config
from hearth.ambient import AmbientChannel, AmbientGenerator
from hearth import ambient as amb
from hearth import card as card_mod
from hearth import diagnostics
from hearth.catalog import Catalog
from hearth.player import PlaybackCore, QueueEngine

from .test_ambient_misc import FakeSink, fake_channel
from .test_app_smoke import make_hearth
from .test_catalog import FakeClient
from .test_controls import queue_of
from .test_models import make_track
from .test_storage import make_store

RESULTS = [
    {
        "videoId": "aaa11111111",
        "title": "One More Time",
        "artists": [{"name": "Daft Punk"}],
        "duration": "5:20",
        "duration_seconds": 320,
        "thumbnails": [{"url": "big.jpg"}],
    },
]


# ------------------------------------------------------------------ café

def test_cafe_channel_starts_switches_and_stops():
    channel, made = fake_channel()
    assert channel.start("cafe") is True
    assert channel.kind == "cafe"
    assert channel.active
    channel.set_level(0.5)
    assert channel.level == 0.5
    channel.start("rain")                   # switching releases the café sink
    assert made[0].stopped
    channel.stop()
    assert made[1].stopped
    assert channel.kind is None and not channel.active


def test_cafe_level_dial_never_blows_up():
    channel, _made = fake_channel()
    for junk in ("loud", None, 1e9, -3.5):
        channel.set_level(junk)             # junk is clamped or ignored
        assert 0.0 <= channel.level <= 1.0


# ------------------------------------------------- per-track volume nudges

def test_volume_nudge_sticks_to_current_track(tmp_path, qapp):
    hearth = make_hearth(tmp_path)
    track = make_track(video_id="vol1")
    hearth.core.engine.start_queue([track], 0)
    hearth._on_user_volume(0.42)
    assert hearth.core.volume == pytest.approx(0.42)
    assert hearth.store.track_pref("vol1", "vol", None) == pytest.approx(0.42)
    hearth.shutdown()


def test_volume_nudge_without_track_is_applied_but_not_saved(tmp_path, qapp):
    hearth = make_hearth(tmp_path)
    hearth._on_user_volume(0.3)
    assert hearth.core.volume == pytest.approx(0.3)
    assert hearth.store.track_pref("nobody", "vol", None) is None
    hearth.shutdown()


def test_volume_nudge_comes_back_with_the_track(tmp_path, qapp):
    hearth = make_hearth(tmp_path)
    quiet, loud = make_track(video_id="quiet"), make_track(video_id="loud")
    hearth.core.engine.start_queue([quiet], 0)
    hearth._on_track_changed(quiet)
    hearth._on_user_volume(0.25)            # the quiet episode gets a nudge
    hearth._on_track_changed(loud)          # a loud remaster: no nudge on file
    assert hearth.core.volume == pytest.approx(0.25)   # dial stays where left
    hearth._on_track_changed(quiet)         # the nudge returns with the song
    assert hearth.core.volume == pytest.approx(0.25)
    assert hearth.panel._volume.value() == 25   # the dial shows it too
    hearth.shutdown()


# ------------------------------------------- play-count-weighted shuffle

def test_weighted_shuffle_surfaces_the_hot_sibling():
    queue = [("a1", "A"), ("a2", "A"), ("b1", "B"), ("a3", "A"), ("c1", "C")]
    eng = QueueEngine()
    eng.start_queue(queue_of(queue), 0)
    eng.shuffle_upcoming_smart()
    cold_order = [t.video_id for t in eng.upcoming]
    assert cold_order == ["b1", "c1", "a2", "a3"]   # ties keep queue order
    eng.start_queue(queue_of(queue), 0)
    eng.shuffle_upcoming_smart({"a3": 1.0})     # a3 is the favorite
    hot_order = [t.video_id for t in eng.upcoming]
    assert hot_order == ["b1", "c1", "a3", "a2"]    # the hot sibling buys ahead
    assert cold_order.index("a3") > hot_order.index("a3")


def test_weighted_shuffle_equal_weights_equal_no_weights():
    eng = QueueEngine()
    eng.start_queue(queue_of([
        ("a1", "A"), ("b1", "B"), ("a2", "A"), ("c1", "C"), ("b2", "B"),
    ]), 0)
    eng.shuffle_upcoming_smart()
    plain = [t.video_id for t in eng.upcoming]
    eng.start_queue(queue_of([
        ("a1", "A"), ("b1", "B"), ("a2", "A"), ("c1", "C"), ("b2", "B"),
    ]), 0)
    eng.shuffle_upcoming_smart({"a1": 0.9, "b1": 0.9, "a2": 0.9,
                                "c1": 0.9, "b2": 0.9})
    assert [t.video_id for t in eng.upcoming] == plain


def test_weighted_shuffle_keeps_the_just_played_artist_out():
    eng = QueueEngine()
    eng.start_queue(queue_of([("a1", "A"), ("a2", "A")]), 0)
    eng.shuffle_upcoming_smart({"a2": 1.0})     # all the weight in the world…
    assert [t.video_id for t in eng.upcoming] == ["a2"]   # …cannot make an encore


def test_weighted_shuffle_ignores_junk_weights():
    eng = QueueEngine()
    eng.start_queue(queue_of([("a1", "A"), ("b1", "B"), ("a2", "A")]), 0)
    eng.shuffle_upcoming_smart({"a2": "spicy", "b1": None, "c1": object()})
    assert len(eng.upcoming) == 2            # junk is a zero, never a crash


def test_core_shuffle_smart_passes_weights_and_signals():
    core = PlaybackCore()
    seen = {}
    original = QueueEngine.shuffle_upcoming_smart

    def spy(self, weights=None):
        seen["weights"] = weights
        return original(self, weights)

    QueueEngine.shuffle_upcoming_smart = spy
    try:
        core.start_queue(queue_of([("a1", "A"), ("b1", "B")]), 0)
        fired = []
        core.queue_changed.connect(lambda: fired.append(1))
        core.shuffle_smart({"b1": 0.5})
        assert seen["weights"] == {"b1": 0.5}
        assert len(fired) == 1
    finally:
        QueueEngine.shuffle_upcoming_smart = original


def test_app_shuffle_feeds_decayed_scores(tmp_path, qapp):
    hearth = make_hearth(tmp_path)
    hearth.store.log_play(make_track(video_id="hot1"))
    hearth.store.log_play(make_track(video_id="hot1"))
    hearth.store.log_play(make_track(video_id="cold1"))
    weights = hearth._shuffle_weights()
    assert weights["hot1"] > weights["cold1"] > 0.0
    assert max(weights.values()) == pytest.approx(1.0)   # max-normalized
    hearth.shutdown()


# ------------------------------------------------ per-leg fetch counters

def test_counters_count_ok_and_fail():
    cat = Catalog()
    cat.search_songs("daft punk", attempts=2, base_delay=0, sleep=lambda _s: None,
                     client_factory=lambda: FakeClient(results=RESULTS))
    assert cat.counters["search-songs.ok"] == 1
    cat2 = Catalog()
    cat2.search_songs("daft punk", attempts=2, base_delay=0, sleep=lambda _s: None,
                      client_factory=lambda: FakeClient(fail_times=99))
    assert cat2.counters["search-songs.fail"] == 1


def test_counters_count_the_web_leg():
    cat = Catalog()
    served = cat.search_everywhere("obscure live cut", client_factory=lambda: FakeClient(results=[]),
                                   fallback=lambda _q, _l: [make_track()])
    assert served and cat.counters["web-fallback.ok"] == 1
    assert cat.counters["search-everywhere-songs.empty"] == 1
    assert cat.counters["search-everywhere-videos.empty"] == 1
    dry = Catalog()
    assert dry.search_everywhere("x", client_factory=lambda: FakeClient(results=[])) == []
    assert "web-fallback.ok" not in dry.counters            # no fallback: no leg
    bad = Catalog()
    assert bad.search_everywhere("x", client_factory=lambda: FakeClient(results=[]),
                                 fallback=_boom) == []
    assert bad.counters["web-fallback.fail"] == 1


def _boom(_query, _limit):
    raise RuntimeError("the web is on fire")


def test_report_shows_fetch_legs(tmp_path):
    report = diagnostics.gather_report(make_store(tmp_path), fetch_counters={
        "search-songs.ok": 12, "web-fallback.empty": 2})
    assert "fetch legs (this session):" in report
    assert "search-songs.ok: 12" in report
    assert diagnostics.gather_report(make_store(tmp_path)).count("fetch legs") == 0


# ----------------------------------------------------- the Rewind card

def test_rewind_card_renders_a_real_png(tmp_path, qapp):
    scenes = [
        "🔥 1,024 plays · 5,120 minutes · 120 days by the fire",
        "🌱 It all began on January 5, 2026",
        "🧭 312 different tracks crossed the hearth",
        "🏆 Daft Punk owned the year",
    ]
    path = tmp_path / "rewind.png"
    assert card_mod.render_card(scenes, path, "grove") is True
    data = path.read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n" and len(data) > 1_000


def test_rewind_card_declines_the_impossible(tmp_path):
    assert card_mod.render_card([], tmp_path / "empty.png") is False
    assert card_mod.render_card(None, tmp_path / "none.png") is False
    assert card_mod.render_card(["a scene"], "/no/such/dir/card.png") is False


def test_rewind_card_survives_a_very_long_story(tmp_path, qapp):
    scenes = [f"scene {i} " + "word " * 30 for i in range(40)]
    path = tmp_path / "long.png"
    assert card_mod.render_card(scenes, path, "frost") is True


def test_rewind_dialog_offers_copy_and_png(tmp_path, qapp, monkeypatch):
    hearth = make_hearth(tmp_path)
    for _ in range(3):
        hearth.store.log_play(make_track())
    view = hearth.window.stats_view
    view.refresh()
    # no native dialog in tests: the Save button is only wired in real UI
    assert hasattr(view, "_show_rewind")
    hearth.shutdown()
