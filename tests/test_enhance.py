"""Wave 2 — the Enhance sprinkle: pick_seed, enhance, store integration."""

from hearth.enhance import enhance, enhance_into_playlist, pick_seed
from hearth.storage import HearthStore

from .test_models import make_track


# --- pick_seed ---


def test_pick_seed_most_frequent_artist():
    tracks = [
        make_track(video_id="a1", artist="Amy"),
        make_track(video_id="b1", artist="Bob"),
        make_track(video_id="a2", artist="Amy"),
        make_track(video_id="c1", artist="Cara"),
    ]
    assert pick_seed(tracks).video_id == "a1"    # first-seen among the tied max


def test_pick_seed_tie_goes_to_earliest_track():
    tracks = [
        make_track(video_id="b1", artist="Bob"),
        make_track(video_id="a1", artist="Amy"),
        make_track(video_id="b2", artist="Bob"),
        make_track(video_id="a2", artist="Amy"),
    ]
    assert pick_seed(tracks).video_id == "b1"    # both have 2; Bob seen first


def test_pick_seed_empty_and_single():
    assert pick_seed([]) is None
    assert pick_seed([make_track(video_id="solo")]).video_id == "solo"


def test_pick_seed_ignores_blank_artists():
    tracks = [make_track(video_id="x", artist=""), make_track(video_id="y", artist="  ")]
    assert pick_seed(tracks).video_id == "x"     # fallback to first track


# --- enhance ---


def _radio(table: dict[str, list]):
    def suggester(seed, n):
        return table.get(seed.video_id, [])[:n]
    return suggester


def test_enhance_fills_up_to_n():
    tracks = [make_track(video_id="a1", artist="Amy")]
    table = {"a1": [make_track(video_id="r1"), make_track(video_id="r2"), make_track(video_id="r3")]}
    picks = enhance(tracks, _radio(table), n=2)
    assert [p.track.video_id for p in picks] == ["r1", "r2"]
    assert all(p.seed.video_id == "a1" for p in picks)
    assert "radio from" in picks[0].reason


def test_enhance_skips_playlist_tracks_and_picked_ones():
    tracks = [
        make_track(video_id="a1", artist="Amy"),
        make_track(video_id="a2", artist="Amy"),
    ]
    table = {
        "a1": [make_track(video_id="a2"), make_track(video_id="r1"), make_track(video_id="r2")],
        "a2": [make_track(video_id="r3"), make_track(video_id="r1")],
    }
    picks = enhance(tracks, _radio(table), n=3)
    got = [p.track.video_id for p in picks]
    assert got == ["r1", "r2", "r3"]             # a2 suggested back → skipped; r1 dup → skipped


def test_enhance_respects_exclude_list():
    tracks = [make_track(video_id="a1")]
    table = {"a1": [make_track(video_id="r1"), make_track(video_id="r2")]}
    picks = enhance(tracks, _radio(table), n=2, exclude=[make_track(video_id="r1")])
    assert [p.track.video_id for p in picks] == ["r2"]


def test_enhance_short_result_is_honest():
    tracks = [make_track(video_id="a1")]
    table = {"a1": [make_track(video_id="r1")]}
    picks = enhance(tracks, _radio(table), n=5)
    assert [p.track.video_id for p in picks] == ["r1"]


def test_enhance_survives_raising_suggester():
    tracks = [
        make_track(video_id="a1"),
        make_track(video_id="a2"),
    ]

    def boom(seed, n):
        if seed.video_id == "a1":
            raise RuntimeError("radio down")
        return [make_track(video_id="r9")]

    picks = enhance(tracks, boom, n=1)
    assert [p.track.video_id for p in picks] == ["r9"]


def test_enhance_drops_junk_candidates():
    tracks = [make_track(video_id="a1")]
    picks = enhance(tracks, lambda seed, n: ["not a track", make_track(video_id=""), None], n=3)
    assert picks == []


def test_enhance_zero_n_and_empty_playlist():
    tracks = [make_track(video_id="a1")]
    assert enhance(tracks, lambda s, n: [make_track()], n=0) == []
    assert enhance([], lambda s, n: [make_track()], n=3) == []


# --- store integration ---


def test_enhance_into_playlist_adds(tmp_path):
    store = HearthStore(tmp_path / "hearth.db")
    pid = store.create_playlist("Road trip")
    store.add_to_playlist(pid, make_track(video_id="a1", artist="Amy"))
    table = {"a1": [make_track(video_id="r1", title="Radio One"), make_track(video_id="a1")]}
    added, picks = enhance_into_playlist(store, pid, _radio(table), n=2)
    assert [t.video_id for t in added] == ["r1"]
    assert len(picks) == 1                       # the a1 echo is skipped, not a pick
    ids = [t.video_id for t in store.playlist_tracks(pid)]
    assert ids == ["a1", "r1"]


def test_enhance_into_playlist_missing_playlist_is_safe(tmp_path):
    store = HearthStore(tmp_path / "hearth.db")
    added, picks = enhance_into_playlist(store, 999, lambda s, n: [], n=2)
    assert added == []
    assert picks == []
