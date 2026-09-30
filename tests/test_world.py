"""World Explorer: genre universe integrity, search-everywhere, UI wiring.

The universe tests guard the data (it is the product: a dial with every
kind of music on it). The catalog tests pin the songs → videos → web
fallback ladder. The UI/app tests prove a chip click ends in a playing
queue — headless, offline, no guest API.
"""

import random
import sys

from hearth import world
from hearth.catalog import Catalog, web_search_tracks
from hearth.config import get_palette
from hearth.jobs import WorldJob
from hearth.models import Track
from hearth.window import MainWindow, WorldView

from .test_app_smoke import make_hearth
from .test_models import make_track


# ------------------------------------------------------- the universe

def test_universe_covers_nine_regions():
    regions = {g.region for g in world.genres()}
    assert regions == set(world.REGIONS)
    assert len(world.REGIONS) == 9


def test_universe_is_deep_enough_to_be_called_everything():
    # "all kinda musics in the world" — the dial must be big.
    assert len(world.genres()) >= 70


def test_every_genre_is_fully_described():
    keys = [g.key for g in world.genres()]
    assert len(keys) == len(set(keys)), "duplicate genre keys"
    for g in world.genres():
        assert g.emoji and g.label and g.blurb, g.key
        assert g.queries and all(q.strip() for q in g.queries), g.key
        assert g.key == g.key.strip() and " " not in g.key, g.key


def test_station_query_rotates_through_seeds():
    g = world.genre("kpop")
    assert g is not None and len(g.queries) >= 2
    assert world.station_query(g, 0) == g.queries[0]
    assert world.station_query(g, 1) == g.queries[1]
    # rotation wraps, and stays deterministic per spin
    assert world.station_query(g, len(g.queries)) == g.queries[0]
    assert world.station_query(g, 5) == world.station_query(g, 5)


def test_random_genre_is_always_a_member():
    rng = random.Random(7)
    assert world.random_genre(rng) in world.genres()
    assert world.random_genre() in world.genres()


def test_genre_lookup_and_match():
    assert world.genre("bhangra").region == "Asia"
    assert world.genre("no-such-dial") is None
    g = world.genre("flamenco")
    assert world.match(g, "flamenco")
    assert world.match(g, "EUROPE")          # region text matches too
    assert not world.match(g, "klezmer")


def test_genres_by_region_keeps_curated_order():
    order = [region for region, _items in world.genres_by_region()]
    assert order == [r for r in world.REGIONS if r in order]
    for _region, items in world.genres_by_region():
        assert items, "no empty region buckets"


# ------------------------------------------------- search everywhere

def _client_factory(results_by_scope: dict):
    class _Client:
        def search(self, query, filter="songs", limit=20):  # noqa: A002
            return results_by_scope.get(filter, [])

    return lambda: _Client()


def test_search_everywhere_prefers_songs():
    catalog = Catalog()
    tracks = catalog.search_everywhere(
        "afrobeat essentials", limit=5, attempts=1, sleep=lambda _s: None,
        client_factory=_client_factory({
            "songs": [{"videoId": "s1", "title": "Song", "artists": [{"name": "A"}]}],
        }),
        fallback=lambda q, l: [_ for _ in ()] or [make_track(video_id="web1")],
    )
    assert [t.video_id for t in tracks] == ["s1"]


def test_search_everywhere_falls_back_to_videos():
    catalog = Catalog()
    tracks = catalog.search_everywhere(
        "obscure live cut", limit=5, attempts=1, sleep=lambda _s: None,
        client_factory=_client_factory({
            "videos": [{"videoId": "v1", "title": "Live", "owner": {"name": "Chan"}}],
        }),
        fallback=lambda q, l: [make_track(video_id="web1")],
    )
    assert [t.video_id for t in tracks] == ["v1"]


def test_search_everywhere_web_fallback_gets_called_last():
    catalog = Catalog()
    seen = []
    tracks = catalog.search_everywhere(
        "never heard of it", limit=3, attempts=1, sleep=lambda _s: None,
        client_factory=_client_factory({}),
        fallback=lambda q, l: (seen.append((q, l)) or [make_track(video_id="w9")]),
    )
    assert seen == [("never heard of it", 3)]
    assert [t.video_id for t in tracks] == ["w9"]


def test_search_everywhere_survives_fallback_errors():
    catalog = Catalog()
    tracks = catalog.search_everywhere(
        "boom", limit=3, attempts=1, sleep=lambda _s: None,
        client_factory=_client_factory({}),
        fallback=lambda q, l: 1 / 0,
    )
    assert tracks == []


def test_search_everywhere_without_fallback_stays_offline():
    catalog = Catalog()
    tracks = catalog.search_everywhere(
        "anything", limit=3, attempts=1, sleep=lambda _s: None,
        client_factory=_client_factory({}),
    )
    assert tracks == []


def test_web_search_tracks_maps_entries(monkeypatch):
    class _FakeYDL:
        def __init__(self, *_a, **_k):
            pass

        def extract_info(self, url, download=False):
            assert url.startswith("ytsearch3:")
            return {"entries": [
                {"id": "abc12345678", "title": "T1", "uploader": "U1",
                 "duration": 200, "thumbnails": [{"url": "th"}]},
                {"id": None, "title": "junk"},                      # skipped
                {"id": "def87654321", "title": "T2", "channel": "C2",
                 "duration": None, "thumbnail": "single.jpg"},
            ]}

    class _FakeModule:
        YoutubeDL = _FakeYDL

    monkeypatch.setitem(sys.modules, "yt_dlp", _FakeModule)
    tracks = web_search_tracks("y.ma nawal", limit=3)
    assert [t.video_id for t in tracks] == ["abc12345678", "def87654321"]
    assert tracks[0].artist == "U1" and tracks[0].duration == "3:20"
    assert tracks[0].thumbnail == "th"
    assert tracks[1].artist == "C2" and tracks[1].thumbnail == "single.jpg"


def test_web_search_tracks_never_raises(monkeypatch):
    class _Boom:
        def __init__(self, *_a, **_k):
            raise RuntimeError("no network")

    class _FakeModule:
        YoutubeDL = _Boom

    monkeypatch.setitem(sys.modules, "yt_dlp", _FakeModule)
    assert web_search_tracks("anything", limit=3) == []


# --------------------------------------------------------- WorldJob

class _DummyCatalog:
    def __init__(self, tracks):
        self.tracks = tracks
        self.calls = []

    def search_everywhere(self, query, limit=20, fallback=None):
        self.calls.append((query, limit, fallback))
        return list(self.tracks)


def test_world_job_emits_label_and_tracks(qapp):
    from hearth.catalog import web_search_tracks

    catalog = _DummyCatalog([make_track()])
    job = WorldJob(catalog, "amapiano hits", "Amapiano", limit=7)
    got = []
    job.signals.finished.connect(lambda payload: got.append(payload))
    job.run()
    assert got == [("Amapiano", [catalog.tracks[0]])]
    query, limit, fallback = catalog.calls[0]
    assert (query, limit) == ("amapiano hits", 7)
    assert fallback is web_search_tracks


def test_world_job_custom_fallback_wins(qapp):
    custom = lambda q, l: []  # noqa: E731
    catalog = _DummyCatalog([])
    job = WorldJob(catalog, "q", "L", fallback=custom)
    job.run()          # must route the custom fallback, not the web search
    query, limit, fallback = catalog.calls[0]
    assert limit == 20                 # default limit when none given
    assert fallback is custom


# ------------------------------------------------------------- UI

def test_world_view_builds_full_dial(qapp):
    view = WorldView(get_palette("grove"))
    chips = [
        w for row in view._sections for w in row[1]
    ]
    assert len(chips) == len(world.genres())


def test_world_view_filter_hides_other_regions(qapp):
    view = WorldView(get_palette("grove"))
    # "latin america" can only match the region of that exact name
    view._filter.setText("latin america")
    for cap, chips in view._sections:
        for chip in chips:
            g = chip.property("genre")
            hidden = g.region != "Latin America"
            assert chip.isHidden() == hidden, g.key
    # a needle that matches exactly one dial position
    view._filter.setText("bhangra")
    for cap, chips in view._sections:
        for chip in chips:
            assert chip.isHidden() == (chip.property("genre").key != "bhangra")
    view._filter.setText("")
    for _cap, chips in view._sections:
        assert all(not chip.isHidden() for chip in chips)


def test_world_view_chip_click_requests_station(qapp):
    from PyQt6.QtCore import QCoreApplication

    view = WorldView(get_palette("grove"))
    got = []
    view.station_requested.connect(lambda g: got.append(g))
    first_chip = view._sections[0][1][0]
    first_chip.click()
    assert got and got[0] is first_chip.property("genre")
    view._surprise()
    assert isinstance(got[-1], world.Genre)
    QCoreApplication.processEvents()


def test_main_window_world_nav(qapp):
    win = MainWindow("grove")
    assert "world" in MainWindow.VIEWS
    assert win._nav["world"].text().startswith("🗺️")
    win.show_view("world")
    assert win.stack.currentWidget() is win.world_view

    got = []
    win.world_station_requested.connect(lambda g: got.append(g))
    win.world_view._sections[0][1][0].click()
    assert got, "chip click must reach the window signal"


# ------------------------------------------------------- app wiring

def test_hearth_world_station_test_mode(tmp_path, qapp):
    hearth = make_hearth(tmp_path)
    genre = world.genre("kpop")
    hearth._start_world_station(genre)
    assert f"{genre.label} station (test mode)" in \
        hearth.window.player_bar._artist.text()
    assert hearth.core.engine.current is None   # nothing started offline
    hearth.shutdown()


def test_hearth_on_world_ready_queues_and_plays(tmp_path, qapp):
    hearth = make_hearth(tmp_path)
    tracks = [
        make_track(video_id="aaa11111111"),
        make_track(video_id="bbb22222222"),
        make_track(video_id="ccc33333333"),
    ]
    hearth._on_world_ready(("Amapiano", tracks))
    assert hearth.core.engine.current is tracks[0]
    assert [t.video_id for t in hearth.core.engine.upcoming] == [
        "bbb22222222", "ccc33333333"
    ]
    assert hearth.window.search_view._head.text().startswith("🗺️ Amapiano")
    assert hearth.window.stack.currentWidget() is hearth.window.search_view
    hearth.shutdown()
