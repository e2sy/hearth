"""v0.7.0 memory slice: On Repeat, day history, stats, queue persistence."""

import time

import pytest

from hearth.app import Hearth
from hearth.models import Track
from hearth.player import PlaybackCore
from hearth.storage import HearthStore
from hearth.window import HomeView

from .test_app_smoke import make_hearth
from .test_models import make_track


def make_store(tmp_path) -> HearthStore:
    return HearthStore(tmp_path / "hearth.db")


def local_midnight(ts: float | None = None) -> float:
    """Local calendar midnight for the day containing `ts` (deterministic)."""
    lt = time.localtime(ts)
    return time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, 0, 0, 0, 0, 0, -1))


# --- On Repeat: the decayed most-played list ---


def test_on_repeat_empty_history(tmp_path):
    store = make_store(tmp_path)
    assert store.on_repeat() == []


def test_on_repeat_recent_outranks_old(tmp_path):
    store = make_store(tmp_path)
    now = time.time()
    store.log_play(make_track(video_id="old"), played_at=now - 30 * 86400)
    store.log_play(make_track(video_id="new"), played_at=now - 3600)
    top = store.on_repeat()
    assert [t.video_id for t in top] == ["new", "old"]


def test_on_repeat_fresh_beats_raw_count(tmp_path):
    """One play this hour beats three plays two months ago."""
    store = make_store(tmp_path)
    now = time.time()
    for _ in range(3):
        store.log_play(make_track(video_id="ancient"), played_at=now - 60 * 86400)
    store.log_play(make_track(video_id="fresh"), played_at=now - 1800)
    assert store.on_repeat()[0].video_id == "fresh"


def test_on_repeat_limit_and_tie_stability(tmp_path):
    store = make_store(tmp_path)
    now = time.time()
    for i in range(6):
        store.log_play(make_track(video_id=f"t{i}"), played_at=now - i * 3600)
    top = store.on_repeat(limit=4)
    assert len(top) == 4
    assert [t.video_id for t in top] == [t.video_id for t in store.on_repeat(limit=4)]


def test_on_repeat_skips_corrupt_payloads(tmp_path):
    store = make_store(tmp_path)
    store.log_play(make_track(video_id="good"))
    store._db.execute("INSERT INTO history (video_id, payload) VALUES ('x', '{bad')")
    store._db.commit()
    assert [t.video_id for t in store.on_repeat()] == ["good"]


# --- history page: day-jump groups ---


def test_history_page_groups_by_day_newest_first(tmp_path):
    store = make_store(tmp_path)
    midnight = local_midnight()
    store.log_play(make_track(video_id="yest"), played_at=midnight - 100)
    store.log_play(make_track(video_id="t1"), played_at=midnight + 100)
    store.log_play(make_track(video_id="t2"), played_at=midnight + 200)
    page = store.history_page()
    today = time.strftime("%Y-%m-%d", time.localtime(midnight + 100))
    yest = time.strftime("%Y-%m-%d", time.localtime(midnight - 100))
    assert [day for day, _tracks in page] == [today, yest]
    assert [t.video_id for t in page[0][1]] == ["t2", "t1"]
    assert [t.video_id for t in page[1][1]] == ["yest"]


def test_history_page_days_filter(tmp_path):
    store = make_store(tmp_path)
    store.log_play(make_track(video_id="ancient"), played_at=time.time() - 3 * 86400)
    store.log_play(make_track(video_id="fresh"))
    page = store.history_page(days=2)
    assert len(page) == 1
    assert [t.video_id for t in page[0][1]] == ["fresh"]


def test_history_page_limit(tmp_path):
    store = make_store(tmp_path)
    now = time.time()
    for i in range(5):
        store.log_play(make_track(video_id=f"t{i}"), played_at=now - i * 60)
    total = sum(len(tracks) for _day, tracks in store.history_page(limit=3))
    assert total == 3


def test_history_page_skips_corrupt_rows(tmp_path):
    store = make_store(tmp_path)
    store.log_play(make_track(video_id="good"))
    store._db.execute("INSERT INTO history (video_id, payload) VALUES ('x', '{bad')")
    store._db.commit()
    page = store.history_page()
    assert len(page) == 1 and [t.video_id for t in page[0][1]] == ["good"]


# --- listening stats ---


def test_listening_stats(tmp_path):
    store = make_store(tmp_path)
    midnight = local_midnight()
    store.log_play(Track(video_id="a", title="A", artist="Alpha"), played_at=midnight + 100)
    store.log_play(Track(video_id="a", title="A", artist="Alpha"), played_at=midnight + 200)
    store.log_play(Track(video_id="b", title="B", artist="Beta"), played_at=midnight - 100)
    stats = store.listening_stats()
    assert stats["total_plays"] == 3
    assert stats["unique_tracks"] == 2
    assert stats["top_artist"] == "Alpha"
    assert stats["top_artist_plays"] == 2
    assert stats["days_listened"] == 2


def test_listening_stats_empty(tmp_path):
    store = make_store(tmp_path)
    stats = store.listening_stats()
    assert stats["total_plays"] == 0
    assert stats["unique_tracks"] == 0
    assert stats["top_artist"] == ""
    assert stats["days_listened"] == 0


# --- queue persistence: restore without a sound ---


def test_restore_queue_rebuilds_silently(qapp):
    core = PlaybackCore(None)
    changed, queued = [], []
    core.track_changed.connect(lambda t: changed.append(t))
    core.queue_changed.connect(lambda: queued.append(1))
    current, past, nxt = (
        make_track(video_id="cur"),
        make_track(video_id="past"),
        make_track(video_id="next"),
    )
    core.restore_queue(current, [past], [nxt], resume_ms=42_000)
    assert core.engine.current.video_id == "cur"
    assert [t.video_id for t in core.engine.history] == ["past"]
    assert [t.video_id for t in core.engine.upcoming] == ["next"]
    assert changed == []           # nothing resolved, nothing plays
    assert queued                  # but the UI repaints the queue dock
    assert core._resume_ms == 42_000


def test_toggle_consumes_restored_resume(qapp):
    core = PlaybackCore(None)
    changed = []
    core.track_changed.connect(lambda t: changed.append(t))
    core.restore_queue(make_track(video_id="cur"), [], [], resume_ms=90_000)
    core.toggle()   # headless-safe: the pending resume short-circuits the backend
    assert [t.video_id for t in changed] == ["cur"]
    assert core._resume_pending is None
    assert core._resume_ms == 0
    assert core._armed_resume_ms == 90_000


def test_user_movement_clears_resume(qapp):
    core = PlaybackCore(None)
    core.restore_queue(make_track(video_id="a"), [], [], resume_ms=90_000)
    core.start_queue([make_track(video_id="z")], 0)
    core.play_track(make_track(video_id="w"))
    assert core._resume_pending is None
    assert core._armed_resume_ms == 0


def test_effective_resume_consumed_once(qapp):
    core = PlaybackCore(None)
    core._armed_resume_ms = 88_000
    assert core._effective_resume(0) == 88_000
    assert core._armed_resume_ms == 0
    assert core._effective_resume(0) == 0


def test_effective_resume_explicit_wins(qapp):
    core = PlaybackCore(None)
    core._armed_resume_ms = 88_000
    assert core._effective_resume(5_000) == 5_000
    assert core._armed_resume_ms == 88_000   # untouched: explicit bypasses the slot


def test_position_ms_falls_back_to_observed(qapp):
    core = PlaybackCore(None)
    core._last_pos_ms = 12_345
    assert core.position_ms == 12_345


# --- the whole roundtrip: close the laptop, reopen on the same beat ---


def test_session_snapshot_roundtrip(tmp_path, qapp):
    hearth = make_hearth(tmp_path)
    current, nxt = make_track(video_id="cur"), make_track(video_id="next")
    hearth.core.restore_queue(current, [], [nxt], resume_ms=77_000)
    hearth.core.set_volume(0.42)
    hearth.shutdown()   # _persist writes the snapshot

    reopened = make_hearth(tmp_path)
    engine = reopened.core.engine
    assert engine.current is not None and engine.current.video_id == "cur"
    assert [t.video_id for t in engine.upcoming] == ["next"]
    assert reopened.core._resume_ms == 77_000
    assert reopened.core.volume == pytest.approx(0.42)
    assert reopened.panel._title.text() == current.display_name
    reopened.shutdown()


def test_session_snapshot_absent_is_noop(tmp_path, qapp):
    hearth = make_hearth(tmp_path)   # no session.json anywhere
    assert hearth._load_session_snapshot() is None
    assert hearth._apply_session_snapshot({"format": "hearth-session"}) is False
    assert hearth.core.engine.current is None
    hearth.shutdown()


def test_session_snapshot_survives_garbage(tmp_path, qapp):
    hearth = make_hearth(tmp_path)
    hearth._snapshot_path.write_text("{not json", encoding="utf-8")
    assert hearth._load_session_snapshot() is None
    hearth._snapshot_path.write_text('{"format": "other"}', encoding="utf-8")
    assert hearth._load_session_snapshot() is None
    hearth.shutdown()


def test_shutdown_writes_snapshot_file(tmp_path, qapp):
    hearth = make_hearth(tmp_path)
    hearth.core.play_track(make_track(video_id="alive"))
    hearth.shutdown()
    assert (tmp_path / "data" / "session.json").exists()


# --- the On Repeat shelf exists on Home ---


def test_home_registers_on_repeat_shelf(qapp):
    from hearth import config
    from hearth.config import get_palette

    view = HomeView(get_palette(config.DEFAULT_PALETTE))
    for name in ("Quick picks", "Top tracks", "On Repeat", "Pinned favorites",
                 "Recently played"):
        assert name in view._shelves
    view.set_shelf("On Repeat", [make_track()])
    view.set_shelf("On Repeat", [])   # empty shelves hide, never raise
