"""Tests for the playlist store: CRUD, dedupe, ordering, cascade delete."""

from hearth.models import Track
from hearth.storage import HearthStore

from .test_models import make_track


def make_store(tmp_path) -> HearthStore:
    return HearthStore(tmp_path / "library.db")


def test_playlist_crud_roundtrip(tmp_path):
    store = make_store(tmp_path)
    pid = store.create_playlist("late night drive")
    assert store.playlist_name(pid) == "late night drive"

    store.rename_playlist(pid, "sunset drive")
    assert store.playlist_name(pid) == "sunset drive"

    playlists = store.playlists()
    assert [(p[0], p[1], p[2]) for p in playlists] == [(pid, "sunset drive", 0)]

    store.delete_playlist(pid)
    assert store.playlist_name(pid) is None
    assert store.playlists() == []
    store.close()


def test_playlist_tracks_append_dedupe_and_order(tmp_path):
    store = make_store(tmp_path)
    pid = store.create_playlist("mixtape")
    a = make_track(video_id="aaa", title="Alpha")
    b = make_track(video_id="bbb", title="Beta")

    assert store.add_to_playlist(pid, a) is True
    assert store.add_to_playlist(pid, b) is True
    assert store.add_to_playlist(pid, a) is False  # duplicate skipped

    tracks = store.playlist_tracks(pid)
    assert [t.video_id for t in tracks] == ["aaa", "bbb"]

    store.remove_from_playlist(pid, "aaa")
    tracks = store.playlist_tracks(pid)
    assert [t.video_id for t in tracks] == ["bbb"]
    assert store.playlists()[0][2] == 1
    store.close()


def test_delete_playlist_drops_tracks(tmp_path):
    store = make_store(tmp_path)
    pid = store.create_playlist("doomed")
    store.add_to_playlist(pid, make_track(video_id="xyz"))
    store.delete_playlist(pid)
    assert store.playlist_tracks(pid) == []
    store.close()


def test_favorites_still_work_alongside(tmp_path):
    store = make_store(tmp_path)
    track = make_track(video_id="pin1")
    store.pin(track)
    assert store.is_pinned("pin1") is True
    assert store.favorites()[0].video_id == "pin1"
    store.unpin("pin1")
    assert store.is_pinned("pin1") is False
    store.close()


def test_history_separate_from_playlists(tmp_path):
    store = make_store(tmp_path)
    pid = store.create_playlist("quiet")
    track = make_track(video_id="h1")
    store.log_play(track)
    store.add_to_playlist(pid, track)
    assert len(store.history()) == 1
    assert len(store.playlist_tracks(pid)) == 1
    store.close()
