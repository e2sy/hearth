"""SQLite favorites & history storage."""

from hearth.models import Track
from hearth.storage import HearthStore

from .test_models import make_track


def make_store(tmp_path) -> HearthStore:
    return HearthStore(tmp_path / "hearth.db")


def test_pin_and_unpin(tmp_path):
    store = make_store(tmp_path)
    store.pin(make_track())
    assert store.is_pinned("dQw4w9WgXcQ")
    store.unpin("dQw4w9WgXcQ")
    assert not store.is_pinned("dQw4w9WgXcQ")
    store.close()


def test_favorites_ordering_newest_first(tmp_path):
    store = make_store(tmp_path)
    store.pin(make_track(video_id="aaa", title="First"))
    store.pin(make_track(video_id="bbb", title="Second"))
    favs = store.favorites()
    assert [t.video_id for t in favs] == ["bbb", "aaa"]
    store.close()


def test_pin_replaces_duplicate(tmp_path):
    store = make_store(tmp_path)
    store.pin(make_track(video_id="aaa", title="V1"))
    store.pin(make_track(video_id="aaa", title="V2"))
    favs = store.favorites()
    assert len(favs) == 1
    assert favs[0].title == "V2"
    store.close()


def test_history_and_prune(tmp_path):
    store = make_store(tmp_path)
    for i in range(12):
        store.log_play(make_track(video_id=f"vid{i}"))
    recent = store.history(limit=5)
    assert [t.video_id for t in recent] == [f"vid{i}" for i in range(11, 6, -1)]
    removed = store.prune_history(keep=8)
    assert removed == 4
    assert len(store.history()) == 8
    store.close()


def test_persistence_across_connections(tmp_path):
    store = make_store(tmp_path)
    store.pin(make_track(video_id="keepme"))
    store.close()
    reopened = HearthStore(tmp_path / "hearth.db")
    assert reopened.is_pinned("keepme")
    reopened.close()
