"""v0.6.1 wave: artist pages — catalog mapping, jobs, view, and app wiring."""

import sys
import types

from hearth.catalog import Catalog, web_search_tracks
from hearth.config import get_palette
from hearth.jobs import ArtistJob, ArtistLookupJob
from hearth.models import Album, Artist, Track
from hearth.window import ArtistView, MainWindow

from .test_app_smoke import make_hearth
from .test_models import make_track


# ----------------------------------------------------------------- catalog

def test_map_results_keeps_artist_id():
    tracks = Catalog._map_results([
        {
            "videoId": "aaaaaaaaaaa", "title": "One",
            "artists": [{"name": "Duo", "id": "UCduo01"}],
        },
        {"videoId": "bbbbbbbbbbb", "title": "No ids", "artists": [{"name": "Solo"}]},
    ])
    assert tracks[0].artist_id == "UCduo01"
    assert tracks[1].artist_id == ""


def test_map_results_owner_id_fallback():
    tracks = Catalog._map_results([
        {"videoId": "ccccccccccc", "title": "Video",
         "owner": {"name": "Channel", "id": "UCchannel"}},
    ])
    assert tracks[0].artist_id == "UCchannel"


def test_map_albums_keeps_artist_id():
    albums = Catalog._map_albums([
        {"browseId": "MPREb1", "title": "Record",
         "artists": [{"name": "Duo", "id": "UCduo01"}]},
    ])
    assert albums[0].artist_id == "UCduo01"


class FakeArtistClient:
    """Mimics the ytmusicapi artist surface; the search gets artists only."""

    def __init__(self, artist_page=None, artist_results=None, fail_times=0):
        self.artist_page = artist_page if artist_page is not None else {}
        self.artist_results = artist_results if artist_results is not None else []
        self.fail_times = fail_times
        self.calls: list[str] = []

    def _maybe_fail(self, label):
        self.calls.append(label)
        if self.fail_times > 0:
            self.fail_times -= 1
            raise ConnectionError("flaky network")

    def search(self, query, filter=None, limit=20):  # noqa: A002 - api shape
        self.calls.append(f"search:{filter}")
        if filter != "artists":
            return []
        if self.fail_times > 0:
            self.fail_times -= 1
            raise ConnectionError("flaky network")
        return self.artist_results

    def get_artist(self, channelId):
        self.calls.append(f"get_artist:{channelId}")
        self._maybe_fail("get_artist")
        return self.artist_page


def catalog_with(client) -> Catalog:
    catalog = Catalog()
    catalog._get_client = lambda factory=None: client
    return catalog


def test_search_artists_mapping():
    client = FakeArtistClient(artist_results=[
        {"browseId": "UCone01", "artist": "Alpha",
         "thumbnails": [{"url": "a.png"}]},
        {"browseId": "UCtwo02", "artist": {"name": "Beta"}},
        {"browseId": "UCthree3"},                        # nameless
        {"no browse id": True},                          # skipped
    ])
    artists = catalog_with(client).search_artists("who", attempts=1)
    assert [a.channel_id for a in artists] == ["UCone01", "UCtwo02", "UCthree3"]
    assert artists[0].name == "Alpha"
    assert artists[1].name == "Beta"
    assert artists[2].name == "Unknown artist"
    assert artists[0].thumbnail == "a.png"


def test_search_artists_network_failure_returns_empty():
    client = FakeArtistClient(artist_results=[{"browseId": "UCone01"}], fail_times=3)
    assert catalog_with(client).search_artists("who", attempts=1) == []


FULL_PAGE = {
    "name": "The Embers",
    "description": "Fire-side folk from the north.",
    "subscribers": "12.4K",
    "thumbnails": [{"url": "face.png"}],
    "songs": {"results": [
        {"videoId": "aaaaaaaaaaa", "title": "Kindling",
         "artists": [{"name": "The Embers", "id": "UCembers"}],
         "duration": "3:21", "duration_seconds": 201},
    ]},
    "albums": {"results": [
        {"browseId": "MPREb1", "title": "Slow Burn",
         "artists": [{"name": "The Embers", "id": "UCembers"}], "year": "2025"},
    ]},
    "singles": {"results": [
        {"browseId": "MPREb2", "title": "Spark", "year": "2024"},
    ]},
    "related": {"results": [
        {"browseId": "UCash", "title": "Ash & Oak",
         "thumbnails": [{"url": "ash.png"}]},
        {"no id": True},
    ]},
}


def test_artist_page_full_mapping():
    artist = catalog_with(FakeArtistClient(artist_page=FULL_PAGE)).artist("UCembers")
    assert artist is not None
    assert artist.name == "The Embers"
    assert artist.description.startswith("Fire-side")
    assert artist.subscribers == "12.4K"
    assert artist.thumbnail == "face.png"
    assert [t.title for t in artist.top_tracks] == ["Kindling"]
    assert artist.top_tracks[0].duration_sec == 201
    assert [a.title for a in artist.albums] == ["Slow Burn"]
    assert artist.albums[0].year == "2025"
    assert [a.title for a in artist.singles] == ["Spark"]
    assert [r.name for r in artist.related] == ["Ash & Oak"]
    assert artist.related[0].channel_id == "UCash"
    assert artist.meta_line.startswith("12.4K")


def test_artist_page_partial_sections_do_not_explode():
    artist = catalog_with(FakeArtistClient(artist_page={"name": "Just A Name"})).artist(
        "UCwhatever"
    )
    assert artist is not None
    assert artist.top_tracks == []
    assert artist.albums == []
    assert artist.related == []


def test_artist_page_unnamed_is_none():
    assert catalog_with(FakeArtistClient(artist_page={})).artist("UCx") is None


def test_artist_page_network_failure_is_none():
    client = FakeArtistClient(artist_page=FULL_PAGE, fail_times=3)
    assert catalog_with(client).artist("UCembers", attempts=1) is None


def test_web_search_tracks_carries_channel_id(monkeypatch):
    entries = {"entries": [
        {"id": "ddddddddddd", "title": "Web Song", "uploader": "Some Band",
         "duration": 200, "channel_id": "UCweb123"},
        {"id": "eeeeeeeeeee", "title": "No Channel", "uploader": "Whoever",
         "duration": 100, "channel_id": "not-a-channel"},
    ]}

    class FakeYDL:
        def __init__(self, opts):
            pass

        def extract_info(self, url, download=False):
            return entries

    fake = types.ModuleType("yt_dlp")
    fake.YoutubeDL = FakeYDL
    monkeypatch.setitem(sys.modules, "yt_dlp", fake)
    tracks = web_search_tracks("query", limit=5)
    assert tracks[0].artist_id == "UCweb123"
    assert tracks[1].artist_id == ""


# ----------------------------------------------------------------- jobs

def test_artist_job_emits_page():
    catalog = catalog_with(FakeArtistClient(artist_page=FULL_PAGE))
    received: list = []
    job = ArtistJob(catalog, "UCembers")
    job.signals.finished.connect(received.append)
    job.run()
    assert received and received[0].name == "The Embers"


def test_artist_job_failed_on_dead_page():
    catalog = catalog_with(FakeArtistClient(artist_page={}))
    failures: list = []
    job = ArtistJob(catalog, "UCdead")
    job.signals.failed.connect(failures.append)
    job.run()
    assert failures == ["UCdead"]


def test_artist_lookup_job_emits_matches():
    client = FakeArtistClient(artist_results=[{"browseId": "UCone01", "artist": "Alpha"}])
    received: list = []
    job = ArtistLookupJob(catalog_with(client), "Alpha")
    job.signals.finished.connect(received.append)
    job.run()
    assert received and received[0][0].channel_id == "UCone01"


def test_artist_lookup_job_fails_when_nobody_home():
    client = FakeArtistClient(artist_results=[])
    failures: list = []
    job = ArtistLookupJob(catalog_with(client), "Ghost")
    job.signals.failed.connect(failures.append)
    job.run()
    assert failures == ["Ghost"]


# ----------------------------------------------------------------- view

def make_artist() -> Artist:
    return Artist(
        channel_id="UCembers",
        name="The Embers",
        description="Fire-side folk.",
        subscribers="12.4K",
        thumbnail="",
        top_tracks=[make_track(video_id="aaaaaaaaaaa", title="Kindling"),
                    make_track(video_id="bbbbbbbbbbb", title="Ashes")],
        albums=[Album(browse_id="MPREb1", title="Slow Burn", year="2025")],
        singles=[Album(browse_id="MPREb2", title="Spark", year="2024")],
        related=[Artist(channel_id="UCash", name="Ash & Oak")],
    )


def test_artist_view_renders_every_section(qapp):
    view = ArtistView(get_palette("grove"))
    view.set_artist(make_artist())

    assert view._name.text() == "The Embers"
    assert "12.4K" in view._meta.text()
    assert view._top._list.count() == 2
    assert view._albums_grid.count() == 1
    assert view._singles_grid.count() == 1
    assert view._related_row.count() == 2          # chip + stretch


def test_artist_view_empty_sections_hide_themselves(qapp):
    view = ArtistView(get_palette("grove"))
    bare = Artist(channel_id="UCbare", name="Bare")
    view.set_artist(bare)
    assert not view._albums_cap.isVisibleTo(view)
    assert not view._singles_cap.isVisibleTo(view)
    assert not view._related_cap.isVisibleTo(view)
    assert view._top._list.count() == 0


def test_artist_view_signals(qapp):
    view = ArtistView(get_palette("grove"))
    view.set_artist(make_artist())

    activated: list = []
    view.track_activated.connect(lambda track, ctx: activated.append((track, ctx)))
    opened_albums: list = []
    view.album_opened.connect(opened_albums.append)
    opened_artists: list = []
    view.artist_opened.connect(opened_artists.append)

    view._top._list.itemDoubleClicked.emit(view._top._list.item(0))
    assert activated and activated[0][0].title == "Kindling"

    view._albums_grid.itemAtPosition(0, 0).widget().click()
    assert opened_albums and opened_albums[0].title == "Slow Burn"

    view._related_row.itemAt(0).widget().click()
    assert opened_artists and opened_artists[0].name == "Ash & Oak"


def test_main_window_opens_artist_page(qapp):
    window = MainWindow("frost")
    window.open_artist(make_artist())
    assert window.stack.currentWidget() is window.artist_view
    assert window.artist_view.current_artist.name == "The Embers"


# ----------------------------------------------------------------- app wiring

class StubCatalog:
    """Artist legs only — enough for the drill-down flows."""

    def __init__(self, page=None, matches=None):
        self.page = page
        self.matches = matches if matches is not None else []

    def artist(self, channel_id):
        return self.page

    def search_artists(self, name, limit=5):
        return self.matches


def test_hearth_open_artist_from_track(tmp_path, qapp, monkeypatch):
    hearth = make_hearth(tmp_path)
    hearth.catalog = StubCatalog(page=make_artist())
    monkeypatch.setattr(hearth, "_launch", lambda job: job.run())

    track = make_track(video_id="aaaaaaaaaaa", artist="The Embers",
                       artist_id="UCembers")
    hearth._open_artist(track)
    assert hearth.window.stack.currentWidget() is hearth.window.artist_view
    assert hearth.window.artist_view.current_artist.name == "The Embers"
    hearth.shutdown()


def test_hearth_open_artist_by_name_when_no_id(tmp_path, qapp, monkeypatch):
    hearth = make_hearth(tmp_path)
    hearth.catalog = StubCatalog(
        page=make_artist(), matches=[Artist(channel_id="UCembers", name="The Embers")]
    )
    monkeypatch.setattr(hearth, "_launch", lambda job: job.run())

    track = make_track(video_id="aaaaaaaaaaa", artist="The Embers")  # no artist_id
    hearth._open_artist(track)
    assert hearth.window.stack.currentWidget() is hearth.window.artist_view
    hearth.shutdown()


def test_hearth_open_artist_lookup_miss(tmp_path, qapp, monkeypatch):
    hearth = make_hearth(tmp_path)
    hearth.catalog = StubCatalog(matches=[])
    monkeypatch.setattr(hearth, "_launch", lambda job: job.run())

    track = make_track(video_id="aaaaaaaaaaa", artist="Ghost Act")
    hearth._open_artist(track)
    assert "Could not find" in hearth.window.player_bar._artist.text()
    assert hearth.window.stack.currentWidget() is not hearth.window.artist_view
    hearth.shutdown()


def test_hearth_open_artist_ignores_unknown_artists(tmp_path, qapp):
    hearth = make_hearth(tmp_path)
    track = make_track(video_id="aaaaaaaaaaa", artist="Unknown artist")
    hearth._open_artist(track)
    assert "No artist to open here" in hearth.window.player_bar._artist.text()
    hearth.shutdown()
