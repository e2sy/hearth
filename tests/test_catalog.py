"""Catalog: link parsing, retry backoff, result mapping (no network)."""

from hearth.catalog import Catalog, parse_video_id


class FakeClient:
    def __init__(self, fail_times=0, results=None, song=None):
        self.fail_times = fail_times
        self.calls = 0
        self.results = results or []
        self.song = song or {}

    def search(self, query, filter=None, limit=None):  # noqa: A002 - mirrors ytmusicapi
        self.calls += 1
        if self.calls <= self.fail_times:
            raise ConnectionError("flaky network")
        return self.results

    def get_song(self, video_id):
        self.calls += 1
        if self.calls <= self.fail_times:
            raise ConnectionError("flaky network")
        return self.song


def test_parse_watch_url():
    assert parse_video_id("https://www.youtube.com/watch?v=dQw4w9WgXcQ") == "dQw4w9WgXcQ"


def test_parse_short_and_music_urls():
    assert parse_video_id("https://youtu.be/dQw4w9WgXcQ") == "dQw4w9WgXcQ"
    assert parse_video_id("https://music.youtube.com/watch?v=dQw4w9WgXcQ&si=x") == "dQw4w9WgXcQ"


def test_parse_bare_id_and_reject_plain_text():
    assert parse_video_id("dQw4w9WgXcQ") == "dQw4w9WgXcQ"
    assert parse_video_id("daft punk one more time") is None
    assert parse_video_id("") is None


RESULTS = [
    {
        "videoId": "aaa11111111",
        "title": "One More Time",
        "artists": [{"name": "Daft Punk"}],
        "duration": "5:20",
        "duration_seconds": 320,
        "thumbnails": [{"url": "small.jpg"}, {"url": "big.jpg"}],
        "album": {"id": "alb1"},
    },
    {"no_video_id": True},
]


def test_search_maps_results():
    catalog = Catalog()
    tracks = catalog.search("one more time", client_factory=lambda: FakeClient(results=RESULTS))
    assert len(tracks) == 1
    assert tracks[0].video_id == "aaa11111111"
    assert tracks[0].artist == "Daft Punk"
    assert tracks[0].duration_sec == 320
    assert tracks[0].thumbnail == "big.jpg"


def test_search_retries_then_succeeds():
    catalog = Catalog()
    client = FakeClient(fail_times=1, results=RESULTS)
    sleeps: list[float] = []
    tracks = catalog.search("x", attempts=3, base_delay=0.25,
                            sleep=sleeps.append, client_factory=lambda: client)
    assert client.calls == 2
    assert sleeps == [0.25]
    assert len(tracks) == 1


def test_search_exhausted_returns_empty():
    catalog = Catalog()
    client = FakeClient(fail_times=10)
    sleeps: list[float] = []
    tracks = catalog.search("x", attempts=3, base_delay=0.5,
                            sleep=sleeps.append, client_factory=lambda: client)
    assert tracks == []
    assert client.calls == 3
    assert sleeps == [0.5, 1.0]


def test_song_details_from_link():
    catalog = Catalog()
    song = {
        "videoDetails": {
            "videoId": "dQw4w9WgXcQ",
            "title": "Never Gonna Give You Up",
            "author": "Rick Astley",
            "lengthSeconds": 213,
            "thumbnail": {"thumbnails": [{"url": "a.jpg"}, {"url": "b.jpg"}]},
        }
    }
    track = catalog.song_details("dQw4w9WgXcQ", client_factory=lambda: FakeClient(song=song))
    assert track is not None
    assert track.duration == "3:33"
    assert track.thumbnail == "b.jpg"
