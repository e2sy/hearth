"""Discover: the whole world's music — moods, genres, charts, explore, playlists.

Catalog mapping (fake clients, no network) + job tagging + view wiring.
"""

from hearth.catalog import Catalog
from hearth.jobs import DiscoverJob
from hearth.models import Album, Collection, Track
from hearth.window import DiscoverView, MainWindow, RemotePlaylistView

from .test_models import make_track


# ----------------------------------------------------------------- fakes

class FakeDiscoverClient:
    """Mimics the ytmusicapi discover surface; each knob can fail."""

    def __init__(self, fail_times=0, categories=None, playlists=None,
                 charts=None, explore=None, playlist=None):
        self.fail_times = fail_times
        self.calls: list[str] = []
        self.categories = categories if categories is not None else {}
        self.playlists = playlists or []
        self.charts = charts if charts is not None else {}
        self.explore = explore if explore is not None else {}
        self.playlist = playlist if playlist is not None else {}

    def _maybe_fail(self, label):
        self.calls.append(label)
        if self.fail_times > 0:
            self.fail_times -= 1
            raise ConnectionError("flaky network")

    def get_mood_categories(self):
        self._maybe_fail("categories")
        return self.categories

    def get_mood_playlists(self, params):
        self._maybe_fail("mood_playlists")
        return self.playlists

    def get_charts(self):
        self._maybe_fail("charts")
        return self.charts

    def get_explore(self):
        self._maybe_fail("explore")
        return self.explore

    def get_playlist(self, playlistId, limit=100):
        self._maybe_fail("playlist")
        if not self.playlist.get("title"):
            return {}
        return self.playlist


SECTIONS = {
    "Moods & moments": [
        {"title": "Chill", "params": "ggMPchill"},
        {"title": "Focus", "params": "ggMPfocus"},
    ],
    "Genres": [{"title": "Hip-hop", "params": "ggMPhiphop"}],
}

PLAYLIST_RAW = [
    {
        "title": "Pop Gold",
        "playlistId": "RDCLAK5uy_gold",
        "thumbnails": [{"url": "small.jpg"}, {"url": "big.jpg"}],
        "description": "Playlist • YouTube Music",
    },
    {"title": "No id here"},                       # dropped: no id
    {"title": "Chart One", "playlistId": "PL_chart1", "subtitle": "Chart"},
]

EXPLORE_RAW = {
    "new_releases": [
        {
            "title": "Blue Album",
            "artists": [{"name": "Nova"}],
            "browseId": "MPREb_blue",
            "thumbnails": [{"url": "a.jpg"}],
        },
    ],
    "trending": {
        "items": [
            {
                "title": "Hot Song",
                "videoId": "vid00000001",
                "artists": [{"name": "LISA"}],
                "thumbnails": [{"url": "t.jpg"}],
            },
        ],
    },
    "new_videos": [
        {
            "title": "Fresh Video",
            "videoId": "vid00000002",
            "artists": [{"name": "Jess Lee"}],
            "thumbnails": [{"url": "v.jpg"}],
        },
    ],
}

PLAYLIST_PAGE = {
    "title": "Pop Gold",
    "trackCount": "100",
    "tracks": [
        {
            "videoId": "hLQl3WQQoQ0",
            "title": "Someone Like You",
            "artists": [{"name": "Adele"}],
            "duration": "4:45",
            "duration_seconds": 285,
            "thumbnails": [{"url": "p.jpg"}],
        },
    ],
}


# ----------------------------------------------------------------- catalog

def test_mood_categories_maps_sections_in_order():
    catalog = Catalog()
    sections = catalog.mood_categories(
        client_factory=lambda: FakeDiscoverClient(categories=SECTIONS)
    )
    assert [title for title, _ in sections] == ["Moods & moments", "Genres"]
    assert sections[0][1][0]["title"] == "Chill"
    assert sections[0][1][0]["params"] == "ggMPchill"


def test_mood_categories_failure_returns_empty():
    catalog = Catalog()
    sections = catalog.mood_categories(
        attempts=2, base_delay=0.01, sleep=lambda _s: None,
        client_factory=lambda: FakeDiscoverClient(fail_times=99),
    )
    assert sections == []


def test_mood_playlists_maps_collections():
    catalog = Catalog()
    collections = catalog.mood_playlists(
        "ggMPchill", client_factory=lambda: FakeDiscoverClient(playlists=PLAYLIST_RAW)
    )
    assert len(collections) == 2
    first = collections[0]
    assert isinstance(first, Collection)
    assert first.playlist_id == "RDCLAK5uy_gold"
    assert first.title == "Pop Gold"
    assert first.thumbnail == "big.jpg"
    assert "YouTube Music" in first.subtitle


def test_charts_maps_playlist_cards():
    catalog = Catalog()
    charts = catalog.charts(
        client_factory=lambda: FakeDiscoverClient(
            charts={"videos": PLAYLIST_RAW, "artists": [{"title": "x"}]}
        )
    )
    assert len(charts) == 2
    assert charts[1].playlist_id == "PL_chart1"


def test_explore_shelves_maps_three_shelves():
    catalog = Catalog()
    albums, trending, videos = catalog.explore_shelves(
        client_factory=lambda: FakeDiscoverClient(explore=EXPLORE_RAW)
    )
    assert isinstance(albums[0], Album)
    assert albums[0].browse_id == "MPREb_blue"
    assert albums[0].artist == "Nova"
    assert isinstance(trending[0], Track)
    assert trending[0].video_id == "vid00000001"
    assert trending[0].artist == "LISA"
    assert videos[0].video_id == "vid00000002"


def test_playlist_returns_title_and_tracks():
    catalog = Catalog()
    page = catalog.playlist(
        "RDCLAK5uy_gold", client_factory=lambda: FakeDiscoverClient(playlist=PLAYLIST_PAGE)
    )
    assert page is not None
    title, tracks = page
    assert title == "Pop Gold"
    assert len(tracks) == 1
    assert tracks[0].video_id == "hLQl3WQQoQ0"
    assert tracks[0].artist == "Adele"
    assert tracks[0].duration == "4:45"


def test_playlist_without_title_returns_none():
    catalog = Catalog()
    page = catalog.playlist(
        "dead", attempts=2, base_delay=0.01, sleep=lambda _s: None,
        client_factory=lambda: FakeDiscoverClient(playlist={}),
    )
    assert page is None


def test_playlist_retries_then_succeeds():
    catalog = Catalog()
    client = FakeDiscoverClient(fail_times=1, playlist=PLAYLIST_PAGE)
    sleeps: list[float] = []
    page = catalog.playlist("RDCLAK5uy_gold", attempts=3, base_delay=0.25,
                            sleep=sleeps.append, client_factory=lambda: client)
    assert sleeps == [0.25]
    assert page is not None and page[0] == "Pop Gold"


# ----------------------------------------------------------------- job

def test_discover_job_emits_tagged_payload(qapp):
    class _Stub:
        def mood_categories(self):
            return [("Genres", [])]
    seen = []
    job = DiscoverJob(_Stub(), "moods")
    job.signals.finished.connect(lambda payload: seen.append(payload))
    job.run()
    assert seen == [("moods", [("Genres", [])])]


def test_discover_job_playlist_failure_emits_failed(qapp):
    class _Stub:
        def playlist(self, playlist_id):
            return None
    seen_failed = []
    job = DiscoverJob(_Stub(), "playlist", "dead-id")
    job.signals.failed.connect(seen_failed.append)
    job.run()
    assert seen_failed == ["dead-id"]


def test_discover_job_unknown_kind_is_silent(qapp):
    seen = []
    job = DiscoverJob(Catalog(), "bogus")
    job.signals.finished.connect(seen.append)
    job.run()
    assert seen == []


# ----------------------------------------------------------------- view

def make_view(qapp):
    from hearth.config import get_palette
    return DiscoverView(get_palette("frost"))


def test_discover_view_builds_with_builtin_chips(qapp):
    view = make_view(qapp)
    assert set(("charts", "new_releases", "trending", "new_videos")) <= set(view._chips)


def test_discover_view_set_sections_selects_first_category(qapp):
    view = make_view(qapp)
    picked = []
    view.category_selected.connect(picked.append)
    view.set_sections(
        [("Moods & moments", [{"title": "Chill", "params": "ggMPchill"}])]
    )
    assert view._chips["section-0"].text() == "Moods & moments"
    assert picked == ["ggMPchill"]
    assert view._cat_list.count() == 1


def test_discover_view_set_collections_fills_grid_and_caps(qapp):
    view = make_view(qapp)
    view._mode = "section"
    many = [Collection(playlist_id=f"pl{i}", title=f"List {i}") for i in range(70)]
    view.set_collections(many)
    cards = view._grid_lay.count()
    assert cards == view.MAX_GRID_CARDS + 1          # 60 cards + overflow note
    view.set_collections([Collection(playlist_id="a", title="One")])
    assert view._grid_lay.count() == 1


def test_discover_view_collection_click_emits_card(qapp):
    view = make_view(qapp)
    seen = []
    view.collection_opened.connect(seen.append)
    card = view._make_card(Collection(playlist_id="pl1", title="Pop Gold"))
    card.click()
    assert seen and seen[0].playlist_id == "pl1"


def test_discover_view_track_list_page(qapp):
    view = make_view(qapp)
    activated = []
    view.track_activated.connect(lambda t, ctx: activated.append((t, ctx)))
    tracks = [make_track(video_id="aaa"), make_track(video_id="bbb")]
    view.set_track_list("🔥 Trending now", tracks)
    view._track_page.track_activated.emit(tracks[0], tracks)
    assert activated[0][0].video_id == "aaa"
    assert view._body.currentIndex() == 1


def test_remote_playlist_view_signals(qapp):
    from hearth.config import get_palette
    view = RemotePlaylistView(get_palette("moss"))
    play, enqueue = [], []
    view.play_all_requested.connect(lambda tracks, i: play.append((tracks, i)))
    view.enqueue_all_requested.connect(enqueue.append)
    tracks = [make_track(video_id="x1"), make_track(video_id="x2")]
    view.set_tracks(tracks)
    view.play_all_requested.emit(list(view._tracks), 0)
    view.enqueue_all_requested.emit(list(view._tracks))
    assert play[0] == (tracks, 0)
    assert enqueue[0] == tracks


# ----------------------------------------------------------------- resilience

def test_resilient_parse_skips_junk_cards():
    from hearth.ytm_resilience import _resilient_parse_content_list

    def parse_card(card):
        if card["title"] == "junk":
            raise KeyError("navigationEndpoint")
        return {"title": card["title"]}

    raw = [
        {"musicTwoRowItemRenderer": {"title": "good"}},
        {"musicTwoRowItemRenderer": {"title": "junk"}},
        {"other": "shape"},                       # missing key: skipped
    ]
    out = _resilient_parse_content_list(raw, parse_card)
    assert out == [{"title": "good"}]


def test_resilient_parse_handles_empty_and_custom_key():
    from hearth.ytm_resilience import _resilient_parse_content_list
    assert _resilient_parse_content_list(None, lambda c: c) == []
    assert _resilient_parse_content_list(
        [{"MTRIR": {"a": 1}}], lambda c: c, key="MTRIR"
    ) == [{"a": 1}]


def test_resilience_apply_is_idempotent_and_rebinds_modules():
    import sys

    import ytmusicapi
    from ytmusicapi.parsers import browsing

    from hearth import ytm_resilience
    ytm_resilience._APPLIED = False            # force a fresh pass for the test
    ytm_resilience.apply()
    ytm_resilience.apply()                     # second call: no-op, no crash
    sentinel = browsing.parse_content_list
    assert sentinel.__name__ == "_resilient_parse_content_list"
    rebound = sum(
        1 for mod in sys.modules.values()
        if mod is not None
        and getattr(mod, "__name__", "").startswith("ytmusicapi")
        and getattr(mod, "parse_content_list", None) is sentinel
    )
    assert rebound >= 2                        # defining module + at least one importer
    assert ytmusicapi  # imported for the side effect of populating sys.modules


def test_catalog_get_client_applies_resilience_once(monkeypatch, qapp):

    from hearth import ytm_resilience

    calls = []
    monkeypatch.setattr(
        ytm_resilience, "apply", lambda: calls.append(True)
    )
    catalog = Catalog()
    monkeypatch.setattr(
        "ytmusicapi.YTMusic", lambda: object(), raising=False
    )
    client = catalog._get_client()
    assert client is not None
    assert calls == [True]
    again = catalog._get_client()
    assert again is client
    assert calls == [True]                     # applied exactly once per process


# ----------------------------------------------------------------- window

def test_main_window_discover_is_second_view(qapp):
    window = MainWindow("frost")
    assert "discover" in window.VIEWS
    assert window.VIEWS.index("discover") == 1
    assert window.stack.indexOf(window.discover_view) == 1


def test_main_window_show_discover_emits_refresh(qapp):
    window = MainWindow("frost")
    seen = []
    window.discover_refresh_requested.connect(lambda: seen.append(True))
    window.show_view("discover")
    assert seen == [True]
    assert window._nav["discover"].isChecked()


def test_main_window_open_remote_playlist(qapp):
    window = MainWindow("frost")
    tracks = [make_track(video_id="t1"), make_track(video_id="t2")]
    window.open_remote_playlist("Pop Gold", tracks)
    assert window.stack.currentWidget() is window.remote_playlist_view
    assert "Pop Gold" in window.remote_playlist_view._head.text()
    assert window.remote_playlist_view.current_tracks == tracks
    assert window._nav["discover"].isChecked()
