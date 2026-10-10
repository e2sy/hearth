"""Wave 2 — the Welcome Mat: Spotify JSON / Exportify CSV / embed parsing."""

import json

from hearth.models import Track
from hearth.storage import HearthStore
from hearth.switchboard import (
    ImportReport,
    SongRef,
    clean_query,
    clean_title,
    import_spotify,
    match_songs,
    parse_embed_html,
    parse_exportify_csv,
    parse_source,
    parse_spotify_json,
)

from .test_models import make_track


# --- JSON export parsing ---


def test_json_bare_list():
    text = json.dumps([
        {"title": "Song One", "artist": "A", "duration_ms": 200000},
        {"trackName": "Song Two", "artistName": "B", "albumName": "X"},
    ])
    refs = parse_spotify_json(text)
    assert [r.title for r in refs] == ["Song One", "Song Two"]
    assert refs[0].duration_sec == 200
    assert refs[1].album == "X"


def test_json_wrapped_shapes():
    wrapped = json.dumps({"tracks": [{"name": "Wrapped", "artists": [{"name": "Who"}]}]})
    items = json.dumps({"items": [{"track": None, "name": "From Items", "artist": "A"}]})
    assert parse_spotify_json(wrapped)[0].artist == "Who"
    assert parse_spotify_json(items)[0].title == "From Items"


def test_json_garbage_returns_empty():
    assert parse_spotify_json("not json at all {") == []
    assert parse_spotify_json(json.dumps({"tracks": "nope"})) == []
    assert parse_spotify_json(json.dumps([{"artist": "no title here"}])) == []


def test_json_artists_list_takes_lead():
    text = json.dumps([{"title": "T", "artists": [{"name": "Lead"}, {"name": "Second"}]}])
    assert parse_spotify_json(text)[0].artist == "Lead"


# --- CSV parsing ---


CSV_FIXTURE = (
    "Track Name,Artist Name(s),Album Name,Duration (ms)\n"
    '"Cool Song, The","Amy, Bob",Nice Album,210000\n'
    '"Second Song",Carl,,95000\n'
    ',Missing Title,,\n'
)


def test_csv_exportify_columns():
    refs = parse_exportify_csv(CSV_FIXTURE)
    assert len(refs) == 2
    assert refs[0].title == "Cool Song, The"
    assert refs[0].artist == "Amy, Bob"
    assert refs[0].duration_sec == 210
    assert refs[1].duration_sec == 95
    assert refs[1].album == ""


def test_csv_garbage_returns_empty():
    assert parse_exportify_csv("") == []
    assert parse_exportify_csv("not,a,real\ncsv,with,no,headers,we,care,about") == []


# --- embed HTML parsing ---


EMBED = (
    '<html><script id="__NEXT_DATA__">{"pageProps":{"state":{'
    '"trackList":[{"title":"Embed Song","uri":"spotify:track:abc",'
    '"subtitle":"Lead Artist, Friend Artist"},{"title":""}]}}}</script></html>'
)


def test_embed_html_tracklist():
    refs = parse_embed_html(EMBED)
    assert len(refs) == 1
    assert refs[0].title == "Embed Song"
    assert refs[0].artist == "Lead Artist"


def test_embed_html_without_tracklist():
    assert parse_embed_html("<html><body>nothing here</body></html>") == []


# --- auto-detection ---


def test_parse_source_autodetect():
    assert parse_source(CSV_FIXTURE)[0].title == "Cool Song, The"
    assert parse_source(EMBED)[0].title == "Embed Song"
    assert parse_source(json.dumps([{"title": "J"}]))[0].title == "J"
    assert parse_source("   ") == []


# --- title cleaning ---


def test_clean_title_strips_video_noise():
    assert clean_title("Song (Official Music Video)") == "Song"
    assert clean_title("Song [Official Audio]") == "Song"
    assert clean_title("Song (Lyric Video)") == "Song"
    assert clean_title("Song feat. Someone") == "Song"
    assert clean_title("Song ft. A & B") == "Song"
    assert clean_title("Song【MV】") == "Song"
    assert clean_title("Just A Song") == "Just A Song"


def test_clean_query_pairs_artist_and_title():
    ref = SongRef(title="Song (Official Video)", artist="Artist feat. Buddy")
    assert clean_query(ref) == "Artist Song"


# --- matching ---


def _search_factory(table: dict[str, Track]):
    def search(query: str):
        return table.get(query)
    return search


def test_match_songs_matches_dedupes_and_reports():
    table = {
        "Amy Cool Song": make_track(video_id="aaa", title="Cool Song", artist="Amy"),
        "Second Song": make_track(video_id="bbb"),
    }
    refs = [
        SongRef(title="Cool Song (Official Video)", artist="Amy"),
        SongRef(title="Second Song", artist="Carl"),
        SongRef(title="Ghost Song", artist="Nobody"),
    ]
    tracks, skipped, dupes = match_songs(refs, _search_factory(table))
    assert [t.video_id for t in tracks] == ["aaa", "bbb"]
    assert skipped == ["Nobody — Ghost Song"]
    assert dupes == 0


def test_match_songs_collapses_duplicate_videos():
    table = {"Same Song": make_track(video_id="aaa")}
    refs = [SongRef(title="Same Song"), SongRef(title="Same Song (Audio)")]
    tracks, skipped, dupes = match_songs(refs, _search_factory(table))
    assert [t.video_id for t in tracks] == ["aaa"]
    assert dupes == 1
    assert skipped == []


def test_match_songs_survives_raising_search():
    def boom(_query):
        raise RuntimeError("network down")
    tracks, skipped, _ = match_songs([SongRef(title="X")], boom)
    assert tracks == []
    assert skipped == ["X"]


# --- full import ---


def test_import_spotify_creates_playlist(tmp_path):
    store = HearthStore(tmp_path / "hearth.db")
    table = {
        "Amy Cool Song, The": make_track(video_id="aaa", title="Cool Song", artist="Amy"),
        "Second Song": make_track(video_id="bbb"),
    }
    report = import_spotify(store, CSV_FIXTURE, _search_factory(table), name="My Past")
    assert isinstance(report, ImportReport)
    assert report.name == "My Past"
    assert report.added == 2
    assert report.total == 2
    assert report.playlist_id > 0
    names = {pid: nm for pid, nm, _ in store.playlists()}
    assert names[report.playlist_id] == "My Past"
    assert [t.video_id for t in store.playlist_tracks(report.playlist_id)] == ["aaa", "bbb"]
    assert "2/2 matched" in report.summary


def test_import_spotify_default_name_and_unmatched(tmp_path):
    store = HearthStore(tmp_path / "hearth.db")
    report = import_spotify(store, CSV_FIXTURE, lambda _q: None)
    assert report.name == "Spotify import"
    assert report.added == 0
    assert report.playlist_id == 0          # nothing landed → no empty playlist
    assert len(report.skipped) == 2
    assert report.playlist_id == 0 or report.playlist_id not in [
        pid for pid, _n, _c in store.playlists()
    ]


def test_import_spotify_garbage_is_honest(tmp_path):
    store = HearthStore(tmp_path / "hearth.db")
    report = import_spotify(store, "total nonsense", lambda _q: None)
    assert report.total == 0
    assert report.added == 0


def test_import_spotify_caps_track_count(tmp_path, monkeypatch):
    from hearth import config, switchboard
    monkeypatch.setattr(config, "IMPORT_MAX_TRACKS", 3, raising=False)
    store = HearthStore(tmp_path / "hearth.db")
    big = json.dumps([{"title": f"s{i}", "artist": "a"} for i in range(50)])
    seen: list[int] = []

    def search(_q):
        seen.append(1)
        return make_track(video_id=f"v{len(seen)}")

    report = import_spotify(store, big, search)
    assert report.total == 3
    assert report.added == 3
