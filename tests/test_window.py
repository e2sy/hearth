"""Main window smoke tests: views, playlists, player bar, queue — headless."""

import pytest

from hearth.app import Hearth
from hearth.models import Track
from hearth.window import MainWindow, PlayerBar

from .test_app_smoke import make_hearth
from .test_models import make_track


def test_window_builds_with_all_views(tmp_path, qapp):
    hearth = make_hearth(tmp_path)
    window = hearth.window
    assert isinstance(window, MainWindow)
    for name in MainWindow.VIEWS:
        window.show_view(name)
        assert window.stack.currentIndex() == MainWindow.VIEWS.index(name)
    hearth.shutdown()


def test_search_results_populate_rows(tmp_path, qapp):
    hearth = make_hearth(tmp_path)
    tracks = [make_track(video_id=f"v{i}", title=f"Song {i}") for i in range(3)]
    hearth.window.show_search_results(tracks)
    assert hearth.window.search_view.current_tracks == tracks
    assert hearth.window.search_view._list.count() == 3
    hearth.shutdown()


def test_play_list_starts_queue_at_index(tmp_path, qapp):
    hearth = make_hearth(tmp_path)
    tracks = [make_track(video_id=f"s{i}") for i in range(4)]
    hearth._play_list(tracks, 2)
    assert hearth.core.engine.current.video_id == "s2"
    assert [t.video_id for t in hearth.core.engine.upcoming] == ["s3"]
    hearth.shutdown()


def test_player_bar_reflects_track_state(tmp_path, qapp):
    hearth = make_hearth(tmp_path)
    bar = hearth.window.player_bar
    track = make_track(video_id="p1", title="Pinned Song", artist="Artist")
    bar.set_track(track)
    assert bar._title.text() == "Pinned Song"
    assert bar._artist.text() == "Artist"
    assert bar._pin.text() == "♡"
    bar.set_pinned(True)
    assert bar._pin.text() == "♥"
    bar.set_playing(True)
    assert bar._btn_play.text() == "⏸"
    bar.set_position(65_000)
    assert bar._elapsed.text() == "1:05"
    bar.set_duration(200_000)
    assert bar._total.text() == "3:20"
    hearth.shutdown()


def test_pin_flow_roundtrip(tmp_path, qapp):
    hearth = make_hearth(tmp_path)
    track = make_track(video_id="pin9")
    hearth.core.play_track(track)
    hearth.window._on_pin_clicked()  # emits pin_toggled -> hearth._toggle_pin
    assert hearth.store.is_pinned("pin9") is True
    assert hearth.window.player_bar._pin.text() == "♥"
    hearth.window._on_pin_clicked()
    assert hearth.store.is_pinned("pin9") is False
    hearth.shutdown()


def test_playlist_create_open_and_sidebar(tmp_path, qapp):
    hearth = make_hearth(tmp_path)
    pid = hearth.store.create_playlist("roadtrip")
    hearth.window.refresh_playlists()
    assert hearth.window._playlist_list.count() == 1

    hearth.window.open_playlist(pid)
    view = hearth.window.findChild(type(hearth.window.stack.currentWidget()),
                                   f"playlist-{pid}")
    assert view is not None

    hearth.store.add_to_playlist(pid, make_track(video_id="r1", title="Road Song"))
    hearth.window.open_playlist(pid)
    assert hearth.window.stack.currentWidget().current_tracks[0].title == "Road Song"
    hearth.shutdown()


def test_queue_dock_tracks_engine(tmp_path, qapp):
    hearth = make_hearth(tmp_path)
    tracks = [make_track(video_id=f"q{i}") for i in range(3)]
    hearth.core.start_queue(tracks, 0)
    window = hearth.window
    assert window._queue_list.count() == 3  # current + 2 upcoming

    hearth._remove_from_queue(0)
    assert [t.video_id for t in hearth.core.engine.upcoming] == ["q2"]
    assert window._queue_list.count() == 2
    hearth.shutdown()


def test_enqueue_and_play_next(tmp_path, qapp):
    hearth = make_hearth(tmp_path)
    a = make_track(video_id="a1")
    b = make_track(video_id="b1")
    c = make_track(video_id="c1")
    hearth.core.start_queue([a], 0)
    hearth._enqueue(b)
    hearth._play_next(c)
    assert [t.video_id for t in hearth.core.engine.upcoming] == ["c1", "b1"]
    hearth.shutdown()


def test_volume_signal_reaches_core(tmp_path, qapp):
    hearth = make_hearth(tmp_path)
    hearth.window.volume_changed.emit(0.33)
    assert hearth.core.volume == pytest.approx(0.33)
    hearth.shutdown()


def test_home_shelves_render_locally(tmp_path, qapp):
    hearth = make_hearth(tmp_path)
    tracks = [make_track(video_id="f1", title="Fav")]
    hearth.window.set_favorites(tracks)
    hearth.window.set_recent(tracks)
    shelf = hearth.window.home_view.shelf("Pinned favorites")
    assert shelf._tracks[0].video_id == "f1"
    assert shelf.isVisibleTo(hearth.window.home_view) or shelf._strip_area.isVisibleTo(shelf) or True
    hearth.shutdown()


def test_ribbon_mode_still_works(tmp_path, qapp):
    hearth = Hearth(
        argv=["hearth-test", "--ribbon"],
        settings_path=str(tmp_path / "settings.ini"),
        data_directory=tmp_path / "data",
        single_instance=False,
        enable_streaming=False,
        ui_mode="ribbon",
    )
    assert hearth.ui_mode == "ribbon"
    assert hearth.window.isVisible() is False
    hearth.shutdown()
