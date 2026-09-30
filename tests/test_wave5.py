"""v0.5.0 wave: search scopes + albums, top tracks, library backup, shortcuts."""

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QShortcut
from PyQt6.QtWidgets import QApplication, QMenu

from hearth.catalog import Catalog
from hearth.models import Album, Track
from hearth.storage import HearthStore
from hearth.window import AlbumView, SearchView

from .test_app_smoke import make_hearth
from .test_models import make_track


# ----------------------------------------------------------------- catalog


class FakeSearchClient:
    """Fake YTMusic client: scoped search + album pages."""

    def __init__(self, songs=None, videos=None, albums=None, album_page=None):
        self._songs = songs or []
        self._videos = videos or []
        self._albums = albums or []
        self._album_page = album_page or {}

    def search(self, query, filter="songs", limit=20):  # noqa: A002
        return {"songs": self._songs, "videos": self._videos,
                "albums": self._albums}[filter][:limit]

    def get_album(self, browseId):
        return self._album_page


SONG_ROWS = [
    {"videoId": "s1", "title": "One", "artists": [{"name": "Alpha"}],
     "duration": "1:00", "duration_seconds": 60},
    {"videoId": "s2", "title": "Two", "artist": {"name": "Beta"},
     "lengthSeconds": 90},
    {"videoId": "s3", "title": "Three", "author": "Gamma"},
]

ALBUM_ROWS = [
    {"browseId": "MPRE1", "title": "Great Hits", "artists": [{"name": "Alpha"}],
     "year": "2020", "thumbnails": [{"url": "a.jpg"}]},
    {"title": "no browse id — must be skipped"},
]


def test_scoped_search_videos_maps_single_artist_shapes():
    catalog = Catalog()
    scope, tracks = catalog.scoped_search(
        "lofi", scope="videos",
        client_factory=lambda: FakeSearchClient(videos=SONG_ROWS),
    )
    assert scope == "videos"
    assert [t.video_id for t in tracks] == ["s1", "s2", "s3"]
    assert tracks[0].artist == "Alpha"
    assert tracks[1].artist == "Beta"
    assert tracks[2].artist == "Gamma"


def test_scoped_search_albums_returns_albums_and_skips_broken_rows():
    catalog = Catalog()
    scope, albums = catalog.scoped_search(
        "alpha", scope="albums",
        client_factory=lambda: FakeSearchClient(albums=ALBUM_ROWS),
    )
    assert scope == "albums"
    assert len(albums) == 1
    assert isinstance(albums[0], Album)
    assert albums[0].title == "Great Hits"
    assert albums[0].year == "2020"


def test_scoped_search_unknown_scope_falls_back_to_songs():
    catalog = Catalog()
    scope, tracks = catalog.scoped_search(
        "x", scope="playlists",
        client_factory=lambda: FakeSearchClient(songs=SONG_ROWS),
    )
    assert scope == "songs"
    assert len(tracks) == 3


def test_search_aliases_songs_scope():
    catalog = Catalog()
    tracks = catalog.search("x", client_factory=lambda: FakeSearchClient(songs=SONG_ROWS))
    assert [t.video_id for t in tracks] == ["s1", "s2", "s3"]


def test_album_page_maps_tracks():
    page = {
        "title": "Great Hits",
        "artists": [{"name": "Alpha"}],
        "year": "2020",
        "thumbnails": [{"url": "big.jpg"}],
        "tracks": SONG_ROWS,
    }
    catalog = Catalog()
    payload = catalog.album(
        "MPRE1", client_factory=lambda: FakeSearchClient(album_page=page)
    )
    assert payload is not None
    album, tracks = payload
    assert album.title == "Great Hits"
    assert album.artist == "Alpha"
    assert [t.video_id for t in tracks] == ["s1", "s2", "s3"]


def test_album_page_failure_returns_none():
    class Boom:
        def get_album(self, browseId):
            raise ConnectionError("down")

    catalog = Catalog()
    assert catalog.album("MPRE1", attempts=1,
                         client_factory=lambda: Boom()) is None


# ----------------------------------------------------------------- storage


def test_top_tracks_rank_by_play_count(tmp_path):
    store = HearthStore(tmp_path / "h.db")
    hot = make_track(video_id="hot", title="Hot Song")
    warm = make_track(video_id="warm", title="Warm Song")
    for _ in range(3):
        store.log_play(hot)
    store.log_play(warm)
    top = store.top_tracks(2)
    assert [t.video_id for t in top] == ["hot", "warm"]
    store.close()


def test_library_export_import_roundtrip(tmp_path):
    source = HearthStore(tmp_path / "a.db")
    source.pin(make_track(video_id="f1", title="Fav One"))
    pid = source.create_playlist("roadtrip")
    source.add_to_playlist(pid, make_track(video_id="r1", title="Road Song"))
    source.add_to_playlist(pid, make_track(video_id="r2", title="Night Drive"))
    data = source.export_library()
    source.close()

    target = HearthStore(tmp_path / "b.db")
    playlists, tracks = target.import_library(data)
    assert playlists == 1
    assert tracks == 3
    assert [t.video_id for t in target.favorites()] == ["f1"]
    restored = target.playlists()[0]
    assert restored[1] == "roadtrip"
    assert [t.video_id for t in target.playlist_tracks(restored[0])] == ["r1", "r2"]
    target.close()


def test_library_import_merge_skips_duplicates(tmp_path):
    store = HearthStore(tmp_path / "h.db")
    store.pin(make_track(video_id="f1"))
    pid = store.create_playlist("mix")
    store.add_to_playlist(pid, make_track(video_id="r1"))
    data = store.export_library()

    other = HearthStore(tmp_path / "other.db")
    playlists, tracks = other.import_library(data, merge=True)
    assert (playlists, tracks) == (1, 2)
    # re-importing is a no-op: same-named playlist is reused, entries dedupe
    playlists, tracks = other.import_library(data, merge=True)
    assert (playlists, tracks) == (0, 0)
    assert len(other.playlists()) == 1
    other.close()
    store.close()


def test_library_import_wipes_when_not_merging(tmp_path):
    store = HearthStore(tmp_path / "h.db")
    store.pin(make_track(video_id="old"))
    store.create_playlist("stale")
    data = store.export_library()

    fresh = HearthStore(tmp_path / "fresh.db")
    fresh.pin(make_track(video_id="temp"))
    fresh.import_library(data, merge=False)
    assert [t.video_id for t in fresh.favorites()] == ["old"]
    assert [name for _pid, name, _n in fresh.playlists()] == ["stale"]
    fresh.close()
    store.close()


def test_library_import_rejects_foreign_format(tmp_path):
    store = HearthStore(tmp_path / "h.db")
    with pytest.raises(ValueError):
        store.import_library({"format": "itunes-library"})
    # corrupt entries are skipped, not fatal
    playlists, tracks = store.import_library({
        "format": store.EXPORT_FORMAT,
        "favorites": [{"video_id": "ok1", "title": "Fine", "artist": "X"},
                      "junk", {"title": "no id"}],
        "playlists": [{"name": " "}, {"name": "good", "tracks": ["junk"]}],
    })
    assert playlists == 1
    assert tracks == 1
    store.close()


# ----------------------------------------------------------------- app wiring


def test_queue_jump_plays_track_and_promotes(tmp_path, qapp):
    hearth = make_hearth(tmp_path)
    a, b, c = (make_track(video_id=v) for v in ("a", "b", "c"))
    hearth.core.start_queue([a, b, c], 0)
    hearth._jump_to_queue_index(0)          # play the first upcoming ("b") now
    assert hearth.core.engine.current.video_id == "b"
    assert [t.video_id for t in hearth.core.engine.upcoming] == ["c"]
    assert hearth.core.engine.history[-1].video_id == "a"
    hearth.shutdown()


def test_queue_jump_out_of_range_is_polite(tmp_path, qapp):
    hearth = make_hearth(tmp_path)
    hearth.core.start_queue([make_track(video_id="a")], 0)
    hearth._jump_to_queue_index(5)
    assert hearth.core.engine.current.video_id == "a"
    hearth.shutdown()


def test_clear_queue_empties_upcoming(tmp_path, qapp):
    hearth = make_hearth(tmp_path)
    tracks = [make_track(video_id=v) for v in ("a", "b", "c")]
    hearth.core.start_queue(tracks, 0)
    hearth._clear_queue()
    assert hearth.core.engine.upcoming == []
    assert hearth.core.engine.current.video_id == "a"
    hearth.shutdown()


def test_mute_toggle_roundtrip(tmp_path, qapp):
    hearth = make_hearth(tmp_path)
    hearth.core.set_volume(0.5)
    hearth._toggle_mute()
    assert hearth.core.volume == 0.0
    hearth._toggle_mute()
    assert hearth.core.volume == pytest.approx(0.5)
    hearth.shutdown()


def test_scoped_results_show_albums(tmp_path, qapp):
    hearth = make_hearth(tmp_path)
    album = Album(browse_id="MPRE1", title="Great Hits", artist="Alpha")
    hearth._show_scoped_results(("albums", [album]))
    assert hearth.window.search_view._list.count() == 1
    hearth.shutdown()


def test_album_open_populates_album_view(tmp_path, qapp):
    hearth = make_hearth(tmp_path)
    album = Album(browse_id="MPRE1", title="Great Hits")
    tracks = [make_track(video_id=f"t{i}") for i in range(3)]
    hearth._on_album_ready((album, tracks))
    assert hearth.window.stack.currentWidget() is hearth.window.album_view
    assert hearth.window.album_view.current_tracks == tracks
    hearth.shutdown()


def test_top_tracks_shelf_on_home(tmp_path, qapp):
    hearth = make_hearth(tmp_path)
    hot = make_track(video_id="hot", title="Hot Song")
    hearth.store.log_play(hot)
    hearth.store.log_play(hot)
    hearth._refresh_home()
    shelf = hearth.window.home_view.shelf("Top tracks")
    assert shelf._tracks[0].video_id == "hot"
    hearth.shutdown()


# ----------------------------------------------------------------- window


def test_search_scope_chips_resubmit(tmp_path, qapp):
    window = type(make_hearth(tmp_path)).__new__  # noqa: F841 - keep import symmetry
    hearth = make_hearth(tmp_path)
    view = hearth.window.search_view
    assert isinstance(view, SearchView)
    assert view.scope() == "songs"
    assert view._chips["songs"].isChecked()

    heard: list[tuple[str, str]] = []
    view.search_scoped.connect(lambda q, s: heard.append((q, s)))
    view.set_query("lofi")
    view.set_scope("albums")
    assert view.scope() == "albums"
    assert heard == [("lofi", "albums")]
    # same scope again -> no duplicate request
    view.set_scope("albums")
    assert heard == [("lofi", "albums")]
    hearth.shutdown()


def test_search_scope_enter_respects_scope(tmp_path, qapp):
    hearth = make_hearth(tmp_path)
    view = hearth.window.search_view
    songs: list[str] = []
    scoped: list[tuple[str, str]] = []
    view.search_submitted.connect(songs.append)
    view.search_scoped.connect(lambda q, s: scoped.append((q, s)))
    view.set_scope("videos")          # no query yet -> no request fires
    view.set_query("beach house")
    view._emit_search()
    assert songs == [] and scoped == [("beach house", "videos")]
    view.set_scope("songs")           # query present -> chip itself resubmits
    view._emit_search()
    assert songs == ["beach house"]
    hearth.shutdown()


def test_album_results_double_click_signals_open(tmp_path, qapp):
    hearth = make_hearth(tmp_path)
    view = hearth.window.search_view
    album = Album(browse_id="MPRE1", title="Great Hits", artist="Alpha")
    view.set_albums([album])
    assert view._list.count() == 1
    opened: list[Album] = []
    view.album_opened.connect(opened.append)
    view._on_double(view._list.item(0))
    assert opened == [album]
    hearth.shutdown()


def test_track_menu_has_copy_link_action(tmp_path, qapp):
    hearth = make_hearth(tmp_path)
    menu = QMenu(hearth.window)
    hearth.window._track_menu(make_track(video_id="abc123"), menu)
    labels = [act.text() for act in menu.actions()]
    assert any("Copy YouTube link" in text for text in labels)
    menu.deleteLater()
    hearth.shutdown()


def test_copy_link_puts_url_on_clipboard(tmp_path, qapp):
    hearth = make_hearth(tmp_path)
    menu = QMenu(hearth.window)
    hearth.window._track_menu(make_track(video_id="abc123xyz"), menu)
    action = next(a for a in menu.actions() if "Copy YouTube link" in a.text())
    action.trigger()
    clipboard = QApplication.clipboard().text()
    assert clipboard == "https://www.youtube.com/watch?v=abc123xyz"
    menu.deleteLater()
    hearth.shutdown()


def test_shortcuts_installed_and_guarded(tmp_path, qapp):
    hearth = make_hearth(tmp_path)
    window = hearth.window
    chords = {s.key().toString() for s in window.findChildren(QShortcut)}
    for expected in ("Space", "M", "S", "R", "N", "Q", "/", "Right", "Left"):
        assert expected in chords
    # typing guard: M while the search box has focus must not reach the app
    window.show()
    qapp.processEvents()
    window.search_view._box.setFocus()
    qapp.processEvents()
    fired: list[str] = []
    window.mute_toggled.connect(lambda: fired.append("mute"))
    for shortcut in window.findChildren(QShortcut):
        if shortcut.key().toString() == "M":
            shortcut.activated.emit()
    assert fired == []
    hearth.shutdown()


def test_seek_and_volume_shortcuts_emit(tmp_path, qapp):
    hearth = make_hearth(tmp_path)
    window = hearth.window
    seeks: list[int] = []
    volumes: list[float] = []
    window.seek_requested.connect(seeks.append)
    window.volume_changed.connect(volumes.append)
    window.player_bar.set_duration(200_000)   # seek slider gets its range
    # seed slider values BEFORE spying: programmatic setValue also emits
    window.player_bar._seek.setValue(60_000)
    window.player_bar._volume.setValue(50)
    seeks.clear()
    volumes.clear()
    # the shared QApplication may still carry focus in a text field from a
    # previous test's window — put focus on this window so shortcuts can fire
    window.show()
    window.setFocus()
    qapp.processEvents()
    for shortcut in window.findChildren(QShortcut):
        key = shortcut.key().toString()
        if key == "Right":
            shortcut.activated.emit()
        if key == "Up":
            shortcut.activated.emit()
    assert seeks == [70_000]
    assert volumes == [pytest.approx(0.55)]
    hearth.shutdown()


def test_album_view_play_all_starts_queue(tmp_path, qapp):
    hearth = make_hearth(tmp_path)
    album = Album(browse_id="MPRE1", title="Great Hits")
    tracks = [make_track(video_id=f"t{i}") for i in range(3)]
    hearth.window.open_album(album, tracks)
    view = hearth.window.album_view
    assert isinstance(view, AlbumView)
    view.play_all_requested.emit(list(tracks), 0)
    assert hearth.core.engine.current.video_id == "t0"
    assert [t.video_id for t in hearth.core.engine.upcoming] == ["t1", "t2"]
    hearth.shutdown()
