"""v0.9.0 Room 10 — the Ember Feed: weekly mix, daylist, release radar."""

import time

from hearth.feeds import (
    day_bucket,
    daylist,
    queue_suggestions,
    sweep_artist,
    weekly_ember_feed,
)
from hearth.models import Track
from hearth.storage import HearthStore

from .test_models import make_track


def make_store(tmp_path) -> HearthStore:
    return HearthStore(tmp_path / "hearth.db")


def local_stamp(days_ago: int, hour: int) -> float:
    """A deterministic epoch at `hour` local time, `days_ago` days back."""
    lt = time.localtime()
    day = time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, hour, 0, 0, 0, 0, -1))
    return day - days_ago * 86400.0


# --- day buckets ---


def test_day_bucket_names():
    assert day_bucket(6) == "morning"
    assert day_bucket(13) == "afternoon"
    assert day_bucket(18) == "evening"
    assert day_bucket(23) == "night"
    assert day_bucket(2) == "night"


# --- daylist ---


def test_daylist_empty_library_falls_back_to_on_repeat(tmp_path):
    store = make_store(tmp_path)
    store.log_play(make_track(video_id="warm"), played_at=local_stamp(0, 9))
    mix = daylist(store, now=local_stamp(0, 20))  # evening query, morning plays
    # The morning track is not an evening track, but On Repeat backs it up.
    assert mix.bucket == "evening"
    assert [t.video_id for t in mix.tracks] == ["warm"]


def test_daylist_prefers_hour_matches(tmp_path):
    store = make_store(tmp_path)
    for _ in range(4):
        store.log_play(make_track(video_id="nightowl"), played_at=local_stamp(1, 23))
    store.log_play(make_track(video_id="sunrise"), played_at=local_stamp(1, 7))
    mix = daylist(store, now=local_stamp(0, 23))  # asked at night
    assert mix.bucket == "night"
    assert mix.tracks[0].video_id == "nightowl"


def test_daylist_wraps_midnight_bucket(tmp_path):
    store = make_store(tmp_path)
    store.log_play(make_track(video_id="late"), played_at=local_stamp(1, 1))
    mix = daylist(store, now=local_stamp(0, 2))
    assert mix.bucket == "night"
    assert [t.video_id for t in mix.tracks] == ["late"]


def test_daylist_is_deterministic(tmp_path):
    store = make_store(tmp_path)
    for i in range(5):
        store.log_play(make_track(video_id=f"t{i}"), played_at=local_stamp(i, 21))
    a = daylist(store, now=local_stamp(0, 21))
    b = daylist(store, now=local_stamp(0, 21))
    assert [t.video_id for t in a.tracks] == [t.video_id for t in b.tracks]


# --- weekly ember feed ---


def test_ember_feed_empty_library(tmp_path):
    store = make_store(tmp_path)
    assert weekly_ember_feed(store) == []


def test_ember_feed_cold_library_falls_back_to_on_repeat(tmp_path):
    store = make_store(tmp_path)
    now = time.time()
    store.log_play(make_track(video_id="only"), played_at=now - 86400)
    feed = weekly_ember_feed(store)
    assert [t.video_id for t in feed] == ["only"]


def test_ember_feed_skips_tracks_played_today(tmp_path):
    store = make_store(tmp_path)
    now = time.time()
    store.log_play(make_track(video_id="today"), played_at=now - 60)
    store.log_play(make_track(video_id="lastweek"), played_at=now - 7 * 86400)
    feed = weekly_ember_feed(store)
    ids = [t.video_id for t in feed]
    assert "today" not in ids
    assert "lastweek" in ids


def test_ember_feed_dedupes_and_limits(tmp_path):
    store = make_store(tmp_path)
    now = time.time()
    for i in range(40):
        track = make_track(video_id=f"t{i:02d}")
        store.log_play(track, played_at=now - (i + 2) * 86400)
        store.log_play(track, played_at=now - (i + 2) * 86400 - 3600)
    feed = weekly_ember_feed(store, limit=10)
    ids = [t.video_id for t in feed]
    assert len(ids) == len(set(ids)) <= 10


def test_ember_feed_includes_rare_gems(tmp_path):
    store = make_store(tmp_path)
    now = time.time()
    store.log_play(make_track(video_id="spun"), played_at=now - 5 * 86400)
    store.pin(make_track(video_id="gem"))  # pinned, never played
    feed = weekly_ember_feed(store)
    assert "gem" in [t.video_id for t in feed]


def test_ember_feed_is_deterministic(tmp_path):
    store = make_store(tmp_path)
    now = time.time()
    for i in range(12):
        store.log_play(make_track(video_id=f"t{i}"), played_at=now - (i + 2) * 86400)
    a = weekly_ember_feed(store)
    b = weekly_ember_feed(store)
    assert [t.video_id for t in a] == [t.video_id for t in b]


# --- release radar ---


def test_radar_first_sweep_returns_everything_then_nothing(tmp_path):
    store = make_store(tmp_path)
    store.follow_artist("UC1", "Kindred")
    releases = [make_track(video_id=f"r{i}", title=f"Song {i}") for i in range(3)]
    new = sweep_artist(store, "UC1", lambda aid: releases, now=1000.0)
    assert [t.video_id for t in new] == ["r0", "r1", "r2"]
    again = sweep_artist(store, "UC1", lambda aid: releases, now=2000.0)
    assert again == []


def test_radar_only_new_releases_come_back(tmp_path):
    store = make_store(tmp_path)
    store.follow_artist("UC1", "Kindred")
    old = [make_track(video_id="old1"), make_track(video_id="old2")]
    sweep_artist(store, "UC1", lambda aid: old, now=1000.0)
    fresh = [make_track(video_id="old1"), make_track(video_id="old2"),
             make_track(video_id="new1", title="Brand New")]
    new = sweep_artist(store, "UC1", lambda aid: fresh, now=2000.0)
    assert [t.video_id for t in new] == ["new1"]


def test_radar_shelf_reads_offline_from_payloads(tmp_path):
    store = make_store(tmp_path)
    store.follow_artist("UC1", "Kindred")
    sweep_artist(store, "UC1", lambda aid: [make_track(video_id="r1")], now=1000.0)
    shelf = store.radar_new_releases()
    assert [t.video_id for t in shelf] == ["r1"]
    assert store.radar_new_count(since=500.0) == 1


def test_radar_fetch_failure_is_an_honest_noop(tmp_path):
    store = make_store(tmp_path)
    store.follow_artist("UC1", "Kindred")
    assert sweep_artist(store, "UC1", lambda aid: [], now=1000.0) == []
    assert store.radar_new_releases() == []


def test_unfollow_cascades_radar_releases(tmp_path):
    store = make_store(tmp_path)
    store.follow_artist("UC1", "Kindred")
    sweep_artist(store, "UC1", lambda aid: [make_track(video_id="r1")], now=1000.0)
    assert store.unfollow_artist("UC1") is True
    assert store.radar_new_releases() == []
    assert store.is_following("UC1") is False


def test_follow_is_idempotent_and_keeps_added_at(tmp_path):
    store = make_store(tmp_path)
    assert store.follow_artist("UC1", "Kindred") is True
    added = store.follows()[0]["added_at"]
    assert store.follow_artist("UC1", "Kindred") is False
    assert store.follows()[0]["added_at"] == added


# --- queue suggestions ---


def test_queue_suggestions_skip_queued_and_cap():
    queue = ["a", "b"]
    radio = lambda vid: [make_track(video_id=vid), make_track(video_id="x"),
                         make_track(video_id="b"), make_track(video_id="y")]
    out = queue_suggestions(queue, radio, seed_id="a", n=3)
    assert [t.video_id for t in out] == ["x", "y"]  # b already queued


def test_queue_suggestions_radio_failure_is_empty():
    def boom(_vid):
        raise RuntimeError("radio is down")
    assert queue_suggestions(["a"], boom) == []


def test_queue_suggestions_empty_queue_no_seed():
    assert queue_suggestions([], lambda vid: []) == []


def test_queue_suggestions_n_zero():
    assert queue_suggestions(["a"], lambda vid: [make_track()], n=0) == []
