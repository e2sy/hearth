"""Smart shelves: Most played, Recently loved, Rare gems (v0.7.1)."""

import time

from hearth.storage import HearthStore

from .test_models import make_track


def make_store(tmp_path) -> HearthStore:
    return HearthStore(tmp_path / "hearth.db")


# --- Most played ---


def test_most_played_orders_by_play_count(tmp_path):
    store = make_store(tmp_path)
    for _ in range(5):
        store.log_play(make_track(video_id="hot"), played_at=time.time())
    for _ in range(2):
        store.log_play(make_track(video_id="warm"), played_at=time.time())
    store.log_play(make_track(video_id="cold"), played_at=time.time())
    ids = [t.video_id for t in store.smart_most_played()]
    assert ids == ["hot", "warm", "cold"]


def test_most_played_limit_and_empty(tmp_path):
    store = make_store(tmp_path)
    assert store.smart_most_played() == []
    for n in range(6):
        store.log_play(make_track(video_id=f"t{n}"), played_at=time.time())
    assert len(store.smart_most_played(limit=3)) == 3


def test_most_played_skips_corrupt_rows(tmp_path):
    store = make_store(tmp_path)
    store.log_play(make_track(video_id="good"), played_at=time.time())
    store._db.execute(
        "INSERT INTO history (video_id, payload, played_at) VALUES (?, ?, ?)",
        ("bad", "{not json", time.time()),
    )
    store._db.commit()
    ids = [t.video_id for t in store.smart_most_played()]
    assert ids == ["good"]


# --- Recently loved ---


def test_recently_loved_newest_pin_first(tmp_path):
    store = make_store(tmp_path)
    now = time.time()
    store.pin(make_track(video_id="older"))
    store.pin(make_track(video_id="newer"))
    # unixepoch('now') has 1-second granularity — set pins a day apart
    store._db.execute("UPDATE favorites SET created_at = ? WHERE video_id = 'older'",
                      (now - 86400,))
    store._db.commit()
    loved = [t.video_id for t in store.smart_recently_loved(days=365)]
    assert loved == ["newer", "older"]


def test_recently_loved_window_excludes_old_pins(tmp_path):
    store = make_store(tmp_path)
    store.pin(make_track(video_id="fresh"))
    store._db.execute(
        "UPDATE favorites SET created_at = ? WHERE video_id = 'fresh'",
        (time.time() - 90 * 86400,),
    )
    store._db.commit()
    store.pin(make_track(video_id="today"))
    loved = [t.video_id for t in store.smart_recently_loved(days=30)]
    assert loved == ["today"]


def test_recently_loved_unfavorite_removes(tmp_path):
    store = make_store(tmp_path)
    track = make_track(video_id="bye")
    store.pin(track)
    store.unpin("bye")
    assert store.smart_recently_loved(days=365) == []


# --- Rare gems ---


def test_rare_gems_pinned_but_rarely_played(tmp_path):
    store = make_store(tmp_path)
    now = time.time()
    store.pin(make_track(video_id="gem"))
    store.pin(make_track(video_id="popular"))
    for _ in range(3):
        store.log_play(make_track(video_id="popular"), played_at=now)
    gems = [t.video_id for t in store.smart_rare_gems(max_plays=2)]
    assert gems == ["gem"]


def test_rare_gems_unplayed_first_by_newest_pin(tmp_path):
    store = make_store(tmp_path)
    store.pin(make_track(video_id="a"))
    store.pin(make_track(video_id="b"))
    store._db.execute("UPDATE favorites SET created_at = created_at - 1 "
                      "WHERE video_id = 'a'")   # a pinned one second earlier
    store._db.commit()
    assert [t.video_id for t in store.smart_rare_gems()] == ["b", "a"]


def test_rare_gems_limit_zero_safe(tmp_path):
    store = make_store(tmp_path)
    store.pin(make_track(video_id="x"))
    assert store.smart_rare_gems(limit=0) == []
