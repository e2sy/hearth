"""The bridge from lyric hits to playable tracks (resolve_lyric_hits)."""

from hearth.lyrics import LyricHit, resolve_lyric_hits
from hearth.models import Track


def cache_hit(video_id="abc12345678", artist="Aurora", title="Runaway"):
    return LyricHit(line="I was listening to the ocean",
                    score=1.0, source="cache",
                    artist=artist, title=title, video_id=video_id)


def online_hit(artist="Aurora", title="Runaway"):
    return LyricHit(line="I was listening to the ocean",
                    score=0.9, source="lrclib",
                    artist=artist, title=title)


def test_cache_hits_become_tracks_without_searching():
    calls = []
    tracks = resolve_lyric_hits([cache_hit()], lambda q: calls.append(q))
    assert len(tracks) == 1
    assert tracks[0].video_id == "abc12345678"
    assert tracks[0].title == "Runaway"
    assert calls == []                      # the cache already knew the video


def test_online_hits_earn_one_catalog_search_each():
    seen = []

    def search(query):
        seen.append(query)
        return [Track(video_id="yt111111111", title="Runaway", artist="Aurora")]

    tracks = resolve_lyric_hits([online_hit()], search)
    assert seen == ["Aurora Runaway"]
    assert tracks[0].video_id == "yt111111111"


def test_search_failures_cost_their_hit_nothing():
    def search(query):
        raise RuntimeError("network on fire")

    hits = [cache_hit("ccc11111111"), online_hit()]
    tracks = resolve_lyric_hits(hits, search)
    assert [t.video_id for t in tracks] == ["ccc11111111"]


def test_junk_search_results_are_skipped():
    def search(query):
        return ["not a track", None, 42]

    tracks = resolve_lyric_hits([online_hit()], search)
    assert tracks == []


def test_duplicate_videos_land_once():
    hits = [cache_hit("dup11111111"), online_hit()]

    def search(query):
        return Track(video_id="dup11111111", title="Runaway", artist="Aurora")

    tracks = resolve_lyric_hits(hits, search)
    assert len(tracks) == 1


def test_limit_caps_the_result_list():
    hits = [cache_hit(f"id{i:09d}") for i in range(10)]
    tracks = resolve_lyric_hits(hits, lambda q: None, limit=3)
    assert len(tracks) == 3


def test_online_hit_with_no_name_is_skipped():
    tracks = resolve_lyric_hits([online_hit(artist="", title="")], lambda q: [])
    assert tracks == []
