"""v0.8.0 Room 6.4 — lyrics-line search: scoring, offline cache, LRCLIB leg."""

import json

from hearth import lyrics
from hearth.lyrics import (
    LyricHit,
    normalize_line,
    score_line,
    search_cache,
    search_cache_entries,
    search_online,
)
from hearth.storage import HearthStore


# --- normalization & scoring ---


def test_normalize_line_strips_punct_and_case():
    assert normalize_line("  Never Gonna, GIVE you up!!  ") == "never gonna give you up"
    assert normalize_line("") == ""
    assert normalize_line("— — —") == ""


def test_score_line_exact_and_substring():
    assert score_line("never gonna give you up", "Never Gonna Give You Up!") == 1.0
    contained = score_line("never gonna give you up",
                           "we're never gonna give you up, never gonna let you down")
    assert 0.9 <= contained < 1.0


def test_score_line_orders_beats_shuffled():
    line = "one two three four"
    assert score_line("one two three", line) > score_line("three one two", line)
    assert score_line("three one two", line) > 0.7  # all words still present


def test_score_line_partial_overlap_is_fraction():
    score = score_line("never gonna give", "you know the rules and so do i")
    assert score == 0.0
    partial = score_line("never gonna give you", "never gonna run around")
    assert 0.0 < partial < 0.72


def test_score_line_empty_is_zero():
    assert score_line("", "anything") == 0.0
    assert score_line("anything", "") == 0.0


# --- offline cache leg ---


def make_store(tmp_path) -> HearthStore:
    return HearthStore(tmp_path / "hearth.db")


def test_cache_lyrics_roundtrip(tmp_path):
    store = make_store(tmp_path)
    assert store.cache_lyrics("vid1", "Amy", "Cool Song",
                              "first line\nsecond line", None) is True
    assert store.cached_lyrics("vid1") == ("first line\nsecond line", None)
    assert store.cached_lyrics("missing") == (None, None)


def test_cache_lyrics_rejects_empty_payloads(tmp_path):
    store = make_store(tmp_path)
    assert store.cache_lyrics("", "A", "T", "text", None) is False
    assert store.cache_lyrics("vid", "A", "T", "", "") is False


def test_cache_lyrics_upsert_touches_age(tmp_path):
    store = make_store(tmp_path)
    store.cache_lyrics("vid", "A", "Old Title", "one", None)
    store.cache_lyrics("vid", "A", "New Title", "one\ntwo", "[00:01]two")
    plain, synced = store.cached_lyrics("vid")
    assert plain == "one\ntwo"
    assert synced == "[00:01]two"
    entries = store.lyric_entries()
    assert len(entries) == 1
    assert entries[0][2] == "New Title"


def test_lyrics_cache_trims_to_max(tmp_path, monkeypatch):
    from hearth import config
    monkeypatch.setattr(config, "LYRICS_CACHE_MAX", 5, raising=False)
    store = make_store(tmp_path)
    for i in range(8):
        store.cache_lyrics(f"v{i}", "A", f"T{i}", f"unique words number {i}", None)
    assert len(store.lyric_entries()) == 5
    assert store.cached_lyrics("v7")[0] is not None      # newest survive
    assert store.cached_lyrics("v0") == (None, None)     # oldest trimmed


def test_clear_lyrics_cache(tmp_path):
    store = make_store(tmp_path)
    store.cache_lyrics("v", "A", "T", "text", None)
    assert store.clear_lyrics_cache() == 1
    assert store.lyric_entries() == []


def test_search_cache_finds_and_ranks(tmp_path):
    store = make_store(tmp_path)
    store.cache_lyrics("hit1", "Rick Astley", "NGGYU",
                       None, "[00:10]Never gonna give you up\n[00:14]Never gonna let you down")
    store.cache_lyrics("hit2", "Someone", "Other Song",
                       "we're never gonna give you up tonight\nquiet line", None)
    store.cache_lyrics("miss", "Nobody", "Silent Song", "totally different words", None)
    hits = search_cache(store, "never gonna give you up")
    assert hits[0].video_id in ("hit1", "hit2")
    assert all(h.source == "cache" for h in hits)
    assert all("never gonna" in h.line.lower() for h in hits)
    assert len(hits) == 2
    # the exact-line hit outranks the "tonight" variant
    assert hits[0].score >= hits[1].score
    assert hits[0].line.lower().startswith("never gonna give you up")


def test_search_cache_prefers_synced_lrc_lines(tmp_path):
    store = make_store(tmp_path)
    store.cache_lyrics("v", "A", "T", "plain fallback", "[00:05]synced wins")
    hits = search_cache(store, "synced wins")
    assert hits[0].line == "synced wins"


def test_search_cache_limit(tmp_path, monkeypatch):
    store = make_store(tmp_path)
    for i in range(6):
        store.cache_lyrics(f"v{i}", "A", f"T{i}", f"common phrase line {i}", None)
    hits = search_cache(store, "common phrase", limit=3)
    assert len(hits) == 3


def test_search_cache_entries_pure_function():
    entries = [
        ("v1", "A", "T1", "the answer is forty two"),
        ("v2", "B", "T2", "nothing here"),
    ]
    hits = search_cache_entries(entries, "answer is forty two")
    assert len(hits) == 1
    assert isinstance(hits[0], LyricHit)
    assert hits[0].video_id == "v1"


def test_search_cache_survives_broken_store(tmp_path):
    class Boom:
        def lyric_entries(self):
            raise RuntimeError("disk on fire")
    assert search_cache(Boom(), "anything") == []


# --- LRCLIB online leg (mocked HTTP) ---


def test_search_online_matches_and_scores(monkeypatch):
    payload = [
        {"artistName": "Rick Astley", "trackName": "NGGYU",
         "plainLyrics": "we're never gonna give you up\nquiet line"},
        {"artistName": "Cover Band", "trackName": "NGGYU Cover",
         "syncedLyrics": "[00:10]never gonna give you up"},
        {"artistName": "Unrelated", "trackName": "Nope", "plainLyrics": "different words"},
        "not-a-dict",
    ]
    monkeypatch.setattr(lyrics, "_http_get_json", lambda url, timeout: payload)
    hits = search_online("never gonna give you up")
    assert len(hits) == 2
    assert hits[0].artist == "Cover Band"       # the exact 1.0 line leads
    assert hits[0].source == "lrclib"
    assert hits[0].score >= hits[1].score       # Rick's contained phrase trails


def test_search_online_exact_line_first(monkeypatch):
    payload = [
        {"artistName": "B", "trackName": "T2",
         "plainLyrics": "we are never gonna give you up tonight"},
        {"artistName": "A", "trackName": "T1",
         "plainLyrics": "never gonna give you up"},
    ]
    monkeypatch.setattr(lyrics, "_http_get_json", lambda url, timeout: payload)
    hits = search_online("never gonna give you up")
    assert hits[0].artist == "A"                # the exact 1.0 line leads
    assert hits[0].score == 1.0


def test_search_online_garbage_and_empty(monkeypatch):
    monkeypatch.setattr(lyrics, "_http_get_json", lambda url, timeout: None)
    assert search_online("anything") == []
    monkeypatch.setattr(lyrics, "_http_get_json",
                        lambda url, timeout: json.dumps({"nope": True}))
    assert search_online("anything") == []
    assert search_online("   ") == []
