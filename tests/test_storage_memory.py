"""v0.7.0 storage memory core: day jumps, On Repeat scoring, queue snapshots,
per-track prefs, stats summary, and playlist file import/export."""

import json
import time
from datetime import datetime

import pytest

from hearth.config import ON_REPEAT_DECAY_DAYS
from hearth.models import Track
from hearth.storage import HearthStore

from .test_models import make_track


def make_store(tmp_path) -> HearthStore:
    return HearthStore(tmp_path / "memory.db")


def local_noon(year: int, month: int, day: int) -> float:
    """Local noon of a calendar day — immune to any machine timezone."""
    return datetime(year, month, day, 12).timestamp()


# --- history: day jumps & paging ---


def test_history_days_grouping_and_order(tmp_path):
    store = make_store(tmp_path)
    assert store.history_days() == []
    d1, d2 = local_noon(2024, 3, 15), local_noon(2024, 3, 16)
    store.log_play(make_track(video_id="a"), played_at=d1)
    store.log_play(make_track(video_id="b"), played_at=d1 + 60)
    store.log_play(make_track(video_id="c"), played_at=d2)
    assert store.history_days() == [("2024-03-16", 1), ("2024-03-15", 2)]
    store.close()


def test_history_on_filters_one_day_newest_first(tmp_path):
    store = make_store(tmp_path)
    d1, d2 = local_noon(2024, 3, 15), local_noon(2024, 3, 16)
    store.log_play(make_track(video_id="old1"), played_at=d1)
    store.log_play(make_track(video_id="old2"), played_at=d1 + 120)
    store.log_play(make_track(video_id="next-day"), played_at=d2)
    assert [t.video_id for t in store.history_on("2024-03-15")] == ["old2", "old1"]
    assert [t.video_id for t in store.history_on("2024-03-16")] == ["next-day"]
    assert store.history_on("1999-01-01") == []
    store.close()


def test_history_on_respects_limit(tmp_path):
    store = make_store(tmp_path)
    noon = local_noon(2024, 3, 15)
    for i in range(3):
        store.log_play(make_track(video_id=f"v{i}"), played_at=noon + i * 60)
    assert [t.video_id for t in store.history_on("2024-03-15", limit=2)] == ["v2", "v1"]
    store.close()


def test_history_slice_pages_with_has_more(tmp_path):
    store = make_store(tmp_path)
    for i in range(7):
        store.log_play(make_track(video_id=f"v{i}"), played_at=time.time() - i * 60)
    page0, more0 = store.history_slice(page=0, page_size=3)
    page1, more1 = store.history_slice(page=1, page_size=3)
    page2, more2 = store.history_slice(page=2, page_size=3)
    page3, more3 = store.history_slice(page=3, page_size=3)
    assert [t.video_id for t in page0] == ["v6", "v5", "v4"] and more0
    assert [t.video_id for t in page1] == ["v3", "v2", "v1"] and more1
    assert [t.video_id for t in page2] == ["v0"] and not more2
    assert page3 == [] and not more3
    store.close()


def test_history_slice_empty_db(tmp_path):
    store = make_store(tmp_path)
    assert store.history_slice() == ([], False)
    store.close()


# --- on repeat: recency-weighted scoring ---


def test_on_repeat_scores_recent_beats_old(tmp_path):
    store = make_store(tmp_path)
    now = time.time()
    store.log_play(make_track(video_id="recent"), played_at=now - 3600)
    store.log_play(make_track(video_id="ancient"), played_at=now - 90 * 86400)
    ranked = store.on_repeat_scores()
    assert [t.video_id for t, _s in ranked] == ["recent", "ancient"]
    assert ranked[0][1] > 0.9 and ranked[1][1] < 0.1
    store.close()


def test_on_repeat_scores_sum_decayed_plays_and_dedupe(tmp_path):
    store = make_store(tmp_path)
    ts = time.time() - 3600
    for _ in range(3):
        store.log_play(make_track(video_id="one"), played_at=ts)
    ranked = store.on_repeat_scores()
    assert len(ranked) == 1  # deduped by video_id
    score = ranked[0][1]
    assert 1.0 < score < 3.0  # three decayed plays summed, not three entries
    store.close()


def test_on_repeat_dedupe_keeps_newest_payload(tmp_path):
    store = make_store(tmp_path)
    now = time.time()
    store.log_play(make_track(video_id="same", title="Old Name"), played_at=now - 7200)
    store.log_play(make_track(video_id="same", title="New Name"), played_at=now - 60)
    top = store.on_repeat()
    assert len(top) == 1 and top[0].title == "New Name"
    store.close()


def test_on_repeat_tie_break_by_plays_then_title(tmp_path):
    store = make_store(tmp_path)
    ts = time.time() - 100
    store.log_play(make_track(video_id="aaa", title="Zulu"), played_at=ts)
    store.log_play(make_track(video_id="bbb", title="Alpha"), played_at=ts)
    store.log_play(make_track(video_id="ccc", title="Middle"), played_at=ts)
    store.log_play(make_track(video_id="ccc", title="Middle"), played_at=ts)
    assert [t.video_id for t in store.on_repeat()] == ["ccc", "bbb", "aaa"]
    store.close()


def test_on_repeat_default_decay_matches_config(tmp_path):
    store = make_store(tmp_path)
    store.log_play(
        make_track(video_id="x"), played_at=time.time() - ON_REPEAT_DECAY_DAYS * 86400
    )
    _track, score = store.on_repeat_scores()[0]
    assert score == pytest.approx(0.5, rel=1e-4)  # one half-life old = half weight
    store.close()


def test_on_repeat_limit(tmp_path):
    store = make_store(tmp_path)
    now = time.time()
    for i in range(4):
        store.log_play(make_track(video_id=f"v{i}"), played_at=now - i * 60)
    assert [t.video_id for t in store.on_repeat(limit=2)] == ["v0", "v1"]
    store.close()


# --- stats summary ---


def test_stats_summary_empty_db(tmp_path):
    store = make_store(tmp_path)
    stats = store.stats_summary()
    assert stats["total_plays"] == 0
    assert stats["unique_tracks"] == 0
    assert stats["est_minutes"] == 0
    assert stats["days_listened"] == 0
    assert stats["first_play"] is None
    assert stats["top_tracks"] == []
    assert stats["top_artists"] == []
    store.close()


def test_stats_summary_counts_minutes_and_artists(tmp_path):
    store = make_store(tmp_path)
    first = local_noon(2024, 1, 2)
    store.log_play(make_track(video_id="a", artist="Rick", duration_sec=213), played_at=first)
    store.log_play(make_track(video_id="a", artist="Rick", duration_sec=213))
    store.log_play(make_track(video_id="b", artist="Rick", duration_sec=60))
    store.log_play(
        make_track(video_id="c", artist="Bon", duration_sec=0, duration="5:00")
    )
    stats = store.stats_summary()
    assert stats["total_plays"] == 4
    assert stats["unique_tracks"] == 3
    assert stats["est_minutes"] == (213 * 2 + 60 + 300) // 60  # 13
    assert stats["days_listened"] == 2
    assert stats["first_play"] == datetime.fromtimestamp(first).isoformat(
        timespec="seconds"
    )
    assert stats["top_artists"] == [("Rick", 3), ("Bon", 1)]
    assert len(stats["top_tracks"]) == 3
    assert stats["top_tracks"][0].video_id == "a"  # 2 plays outranks the rest
    store.close()


# --- queue snapshot ---


def test_queue_roundtrip_overwrite_single_row(tmp_path):
    store = make_store(tmp_path)
    assert store.load_queue() is None
    store.save_queue(["a", "b", "c"], 1, 42_000)
    assert store.load_queue() == (["a", "b", "c"], 1, 42_000)
    store.save_queue(["d"], 0, 500)
    assert store.load_queue() == (["d"], 0, 500)
    count = store._db.execute("SELECT COUNT(*) FROM queue_snapshot").fetchone()[0]
    assert count == 1  # idempotent single-row snapshot
    store.close()


def test_queue_clear(tmp_path):
    store = make_store(tmp_path)
    store.save_queue(["a"], 0, 0)
    store.clear_queue()
    assert store.load_queue() is None
    store.close()


def test_queue_survives_reopen(tmp_path):
    db = tmp_path / "memory.db"
    store = HearthStore(db)
    store.save_queue(["a", "b"], 1, 1234)
    store.close()
    reopened = HearthStore(db)
    assert reopened.load_queue() == (["a", "b"], 1, 1234)
    reopened.close()


def test_schema_migration_upgrades_old_db(tmp_path):
    db = tmp_path / "upgrade.db"
    store = HearthStore(db)
    store.pin(make_track(video_id="keepme"))
    store._db.execute("DROP TABLE queue_snapshot")
    store._db.execute("DROP TABLE track_prefs")
    store._db.commit()
    store.close()
    reopened = HearthStore(db)  # old DB upgrades seamlessly on open
    assert reopened.is_pinned("keepme")  # existing tables untouched
    reopened.save_queue(["a"], 0, 0)
    reopened.set_track_pref("a", "speed", 1.25)
    assert reopened.load_queue() == (["a"], 0, 0)
    assert reopened.track_pref("a", "speed") == 1.25
    reopened.close()


# --- per-track preferences ---


def test_track_pref_upsert_overwrite_default(tmp_path):
    store = make_store(tmp_path)
    assert store.track_pref("vid", "speed") is None
    assert store.track_pref("vid", "speed", default=0.75) == 0.75
    store.set_track_pref("vid", "speed", 1.25)
    assert store.track_pref("vid", "speed") == 1.25
    store.set_track_pref("vid", "speed", 1.5)  # overwrite
    assert store.track_pref("vid", "speed") == 1.5
    store.close()


def test_track_prefs_all_isolated_per_video(tmp_path):
    store = make_store(tmp_path)
    store.set_track_pref("vid", "speed", 1.25)
    store.set_track_pref("vid", "volume", 0.4)
    store.set_track_pref("other", "speed", 0.5)
    assert store.track_prefs_all("vid") == {"speed": 1.25, "volume": 0.4}
    assert store.track_prefs_all("other") == {"speed": 0.5}
    assert store.track_prefs_all("missing") == {}
    store.close()


# --- playlist files: JSON export / import ---


def test_export_import_playlists_roundtrip(tmp_path):
    source = make_store(tmp_path)
    pid1 = source.create_playlist("late night drive")
    source.add_to_playlist(pid1, make_track(video_id="aaa", title="Alpha"))
    source.add_to_playlist(pid1, make_track(video_id="bbb", title="Beta"))
    pid2 = source.create_playlist("quiet hours")
    source.add_to_playlist(pid2, make_track(video_id="ccc", title="Gamma"))
    path = tmp_path / "playlists.json"
    assert source.export_playlists(path) is True

    target = HearthStore(tmp_path / "other.db")
    assert target.import_playlists(path) == 2
    by_name = {name: (pid, count) for pid, name, count in target.playlists()}
    assert by_name == {"late night drive": (by_name["late night drive"][0], 2),
                       "quiet hours": (by_name["quiet hours"][0], 1)}
    imported = {t.video_id for t in target.playlist_tracks(by_name["late night drive"][0])}
    assert imported == {"aaa", "bbb"}
    assert {t.video_id for t in target.playlist_tracks(by_name["quiet hours"][0])} == {"ccc"}

    # merging again folds into the same playlists, no duplicates
    assert target.import_playlists(path, merge=True) == 2
    assert target.playlists()[0][2] == 2
    source.close()
    target.close()


def test_import_playlists_degraded_inputs_return_zero(tmp_path):
    store = make_store(tmp_path)
    bad_json = tmp_path / "bad.json"
    bad_json.write_text("{not json", encoding="utf-8")
    not_object = tmp_path / "list.json"
    not_object.write_text("[1, 2]", encoding="utf-8")
    no_playlists = tmp_path / "empty.json"
    no_playlists.write_text('{"format": "hearth-library"}', encoding="utf-8")
    assert store.import_playlists(bad_json) == 0
    assert store.import_playlists(not_object) == 0
    assert store.import_playlists(no_playlists) == 0
    assert store.import_playlists(tmp_path / "missing.json") == 0
    unwritable = tmp_path / "no-such-dir" / "out.json"
    assert store.export_playlists(unwritable) is False
    store.close()


# --- playlist files: M3U export / import ---


def test_m3u_roundtrip(tmp_path):
    source = make_store(tmp_path)
    pid = source.create_playlist("road trip")
    source.add_to_playlist(pid, make_track(video_id="aaa", title="Alpha"))
    source.add_to_playlist(pid, make_track(video_id="bbb", title="Beta"))
    path = tmp_path / "road.m3u"
    assert source.export_m3u(pid, path) is True

    text = path.read_text(encoding="utf-8")
    assert text.startswith("#EXTM3U")
    assert "#EXTINF:213,Rick Astley - Alpha" in text
    assert "https://music.youtube.com/watch?v=aaa" in text

    target = HearthStore(tmp_path / "other.db")
    added = target.import_m3u(path, "from the road")
    assert added == 2
    new_pid = target.playlists()[0][0]
    assert target.playlist_name(new_pid) == "from the road"
    tracks = target.playlist_tracks(new_pid)
    assert [(t.video_id, t.artist, t.title, t.duration_sec) for t in tracks] == [
        ("aaa", "Rick Astley", "Alpha", 213),
        ("bbb", "Rick Astley", "Beta", 213),
    ]
    source.close()
    target.close()


def test_m3u_import_edge_cases(tmp_path):
    store = make_store(tmp_path)
    path = tmp_path / "edges.m3u"
    path.write_text(
        "#EXTM3U\n"
        "#EXTINF:99,Weird Name No Separator\n"
        "https://www.youtube.com/watch?v=haslabel\n"
        "\n"
        "https://www.youtube.com/watch?v=nolabel\n"
        "https://example.com/no-video-id\n",
        encoding="utf-8",
    )
    assert store.import_m3u(path, "edges") == 2  # the v=-less URL is skipped
    tracks = store.playlist_tracks(store.playlists()[0][0])
    assert (tracks[0].artist, tracks[0].title) == ("", "Weird Name No Separator")
    assert tracks[1].video_id == "nolabel" and tracks[1].title == "nolabel"
    assert len(tracks) == 2
    store.close()


def test_m3u_degraded_inputs_return_zero(tmp_path):
    store = make_store(tmp_path)
    garbage = tmp_path / "garbage.m3u"
    garbage.write_bytes(b"\xff\xfe\x00broken")
    assert store.import_m3u(garbage, "broken") == 0
    assert store.import_m3u(tmp_path / "missing.m3u", "missing") == 0
    valid = tmp_path / "valid.m3u"
    valid.write_text(
        "#EXTM3U\nhttps://music.youtube.com/watch?v=aaa\n", encoding="utf-8"
    )
    assert store.import_m3u(valid, "   ") == 0  # blank name
    assert store.export_m3u(999, tmp_path / "out.m3u") is False  # unknown playlist
    store.close()
