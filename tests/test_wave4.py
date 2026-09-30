"""v0.4.0 wave: lyrics, radio/autoplay, queue reorder, share, now view."""

import json

import pytest
from PyQt6.QtCore import Qt

from hearth import config
from hearth.catalog import Catalog
from hearth.config import get_palette
from hearth.player import PlaybackCore, QueueEngine
from hearth.share import (
    decode_playlists,
    decode_playlists_text,
    encode_playlist,
    encode_playlists,
)
from hearth.window import MainWindow, NowView
from hearth.lyrics import LrcLine

from .test_app_smoke import make_hearth
from .test_models import make_track


# ----------------------------------------------------------------- catalog


class FakeMediaClient:
    """Fake YTMusic client: lyrics + watch playlist radio."""

    def __init__(self, lyrics=None, radio=None, fail_times=0):
        self.lyrics = lyrics
        self.radio = radio
        self.fail_times = fail_times
        self.lyrics_calls = 0
        self.radio_calls = 0

    def get_lyrics(self, video_id):
        self.lyrics_calls += 1
        if self.lyrics_calls <= self.fail_times:
            raise ConnectionError("flaky")
        return self.lyrics

    def get_watch_playlist(self, videoId=None, radio=False, limit=None):  # noqa: A002
        self.radio_calls += 1
        if self.radio_calls <= self.fail_times:
            raise ConnectionError("flaky")
        return self.radio


RADIO_TRACKS = {
    "tracks": [
        {"videoId": "rad1", "title": "Radio One", "artists": [{"name": "A"}],
         "lengthSeconds": 200, "thumbnails": [{"url": "t1.jpg"}]},
        {"videoId": "rad2", "title": "Radio Two", "artists": [{"name": "B"}],
         "duration": "3:00", "duration_seconds": 180},
        {"nope": True},
    ]
}


def test_lyrics_returns_text():
    catalog = Catalog()
    client = FakeMediaClient(lyrics={"lyrics": " la la land ", "source": "x"})
    text = catalog.lyrics("v1", client_factory=lambda: client)
    assert text == "la la land"


def test_lyrics_none_when_empty_or_missing():
    catalog = Catalog()
    assert catalog.lyrics("v1", client_factory=lambda: FakeMediaClient(lyrics=None)) is None
    assert catalog.lyrics("v1", client_factory=lambda: FakeMediaClient(lyrics={"lyrics": "  "})) is None


def test_lyrics_failure_returns_none():
    catalog = Catalog()
    sleeps: list[float] = []
    text = catalog.lyrics("v1", attempts=2, base_delay=0.1, sleep=sleeps.append,
                          client_factory=lambda: FakeMediaClient(fail_times=5))
    assert text is None
    assert sleeps == [0.1]


def test_radio_maps_watch_playlist_tracks():
    catalog = Catalog()
    tracks = catalog.radio("seed1", client_factory=lambda: FakeMediaClient(radio=RADIO_TRACKS))
    assert [t.video_id for t in tracks] == ["rad1", "rad2"]
    assert tracks[0].duration_sec == 200
    assert tracks[0].duration == "3:20"          # derived from lengthSeconds
    assert tracks[0].thumbnail == "t1.jpg"
    assert tracks[1].duration == "3:00"


def test_radio_failure_returns_empty():
    catalog = Catalog()
    tracks = catalog.radio("seed1", attempts=2, base_delay=0.1, sleep=lambda s: None,
                           client_factory=lambda: FakeMediaClient(fail_times=5))
    assert tracks == []


# ----------------------------------------------------------------- queue


def test_queue_set_order_replaces_upcoming():
    engine = QueueEngine()
    a, b, c = _tracks("a", "b", "c")
    engine.start_queue([a, b, c], 0)
    engine.set_order([c, b])
    assert [t.video_id for t in engine.upcoming] == ["c", "b"]
    assert engine.current.video_id == "a"


# ----------------------------------------------------------------- autoplay


def test_queue_dry_emits_when_autoplay_on(qapp):
    core = PlaybackCore(qapp)
    core.start_queue([_tracks("last")[0]], 0)
    fired: list[object] = []
    stopped: list[bool] = []
    core.queue_dry.connect(fired.append)
    core.state_changed.connect(lambda playing: stopped.append(playing))
    core.next()
    assert len(fired) == 1 and fired[0].video_id == "last"   # seed handed over
    assert stopped == []                                     # not stopped either


def test_queue_dry_silent_when_autoplay_off(qapp):
    core = PlaybackCore(qapp)
    core.set_autoplay(False)
    core.start_queue([_tracks("last")[0]], 0)
    fired: list[bool] = []
    core.queue_dry.connect(lambda: fired.append(True))
    core.next()
    assert fired == []
    assert core.engine.current is None


def test_queue_dry_not_emitted_without_current(qapp):
    core = PlaybackCore(qapp)
    fired: list[bool] = []
    core.queue_dry.connect(lambda: fired.append(True))
    core.next()
    assert fired == []


# ----------------------------------------------------------------- share


def _tracks(*ids):
    return [make_track(video_id=i, title=f"T {i}") for i in ids]


def test_share_roundtrip_single_playlist():
    data = json.loads(json.dumps(encode_playlist("mix", _tracks("a", "b"))))
    assert decode_playlists(data) == [("mix", _tracks("a", "b"))]


def test_share_envelope_and_flat_list():
    one = encode_playlist("one", _tracks("a"))
    two = encode_playlist("two", _tracks("b", "c"))
    envelope = json.loads(json.dumps(encode_playlists([("one", _tracks("a")),
                                                       ("two", _tracks("b", "c"))])))
    assert [name for name, _ in decode_playlists(envelope)] == ["one", "two"]
    assert [name for name, _ in decode_playlists([json.loads(json.dumps(one)),
                                                  json.loads(json.dumps(two))])] == ["one", "two"]


def test_share_dedupes_and_bumps_names():
    payload = {
        "playlists": [
            {"name": "mix", "tracks": [t.to_dict() for t in _tracks("a", "a", "b")]},
            {"name": "mix", "tracks": [t.to_dict() for t in _tracks("c")]},
            {"name": "", "tracks": [t.to_dict() for t in _tracks("d")]},      # dropped
            {"name": "empty", "tracks": []},                                   # dropped
            "garbage",                                                          # dropped
        ]
    }
    out = decode_playlists(payload)
    assert [(n, [t.video_id for t in ts]) for n, ts in out] == [
        ("mix", ["a", "b"]),
        ("mix (2)", ["c"]),
    ]


def test_share_garbage_text_never_raises():
    assert decode_playlists_text("not json at all {") == []
    assert decode_playlists_text(json.dumps({"nope": 1})) == []


# ----------------------------------------------------------------- now view


def test_now_view_track_and_lyrics_state(qapp):
    view = NowView(get_palette("grove"))
    assert view._title.text() == "Nothing playing"

    track = make_track(video_id="nv1", title="Now Song", artist="Now Artist")
    view.set_track(track)
    assert view._title.text() == "Now Song"
    assert view._artist.text() == "Now Artist"

    view.set_lyrics("different-id", "stale lyrics")
    assert view._lyrics._plain.toPlainText() == ""   # stale payload ignored

    view.set_lyrics_loading()
    assert view._lyrics._plain.toPlainText() == "Loading lyrics…"

    view.set_lyrics("nv1", None)
    assert "No lyrics" in view._lyrics._plain.toPlainText()

    view.set_lyrics("nv1", "la la")
    assert view._lyrics._plain.toPlainText() == "la la"

    view.set_track(None)
    assert view._lyrics._plain.toPlainText() == ""


def test_now_view_synced_lyrics_take_the_stage(qapp):
    view = NowView(get_palette("grove"))
    track = make_track(video_id="syn1", title="Sync Song", artist="Sync Artist")
    view.set_track(track)

    view.set_lyrics("syn1", None, [])                  # empty lines → plain fallback
    assert "No lyrics" in view._lyrics._plain.toPlainText()

    lines = [LrcLine(0, "first"), LrcLine(2_000, "second")]
    view.set_lyrics("syn1", "plain words", lines)
    assert view._lyrics._pages.currentWidget() is view._lyrics._sheet
    assert view._lyrics._sheet.count() == 2

    view.set_position(2_100)                           # second line lights up
    assert view._lyrics._active == 1
    view.set_position(2_900)                           # same line, no churn
    assert view._lyrics._active == 1
    view.set_position(4_500)                           # past the end keeps last line
    assert view._lyrics._active == 1

    seen: list[int] = []
    view.lyrics_seek_requested.connect(seen.append)
    view._lyrics._on_clicked(view._lyrics._sheet.item(0))
    assert seen == [0]

    view.set_track(None)
    assert view._lyrics._plain.toPlainText() == ""


def test_now_view_pin_signal(qapp):
    view = NowView(get_palette("grove"))
    view.set_track(make_track(video_id="nv2"))
    fired: list[bool] = []
    view.pin_toggled.connect(lambda: fired.append(True))
    view._pin.click()
    assert fired == [True]


# ----------------------------------------------------------------- window


def test_window_has_now_view_and_nav(tmp_path, qapp):
    hearth = make_hearth(tmp_path)
    window = hearth.window
    assert "now" in MainWindow.VIEWS
    window.show_view("now")
    assert window.stack.currentIndex() == MainWindow.VIEWS.index("now")
    assert window._nav["now"].isChecked()
    hearth.shutdown()


def test_lyrics_toggle_switches_to_now_view(tmp_path, qapp):
    hearth = make_hearth(tmp_path)
    hearth.window.player_bar.lyrics_toggled.emit()
    assert hearth.window.stack.currentWidget() is hearth.window.now_view
    hearth.shutdown()


def test_speed_button_cycles_rate_and_label(tmp_path, qapp):
    hearth = make_hearth(tmp_path)
    bar = hearth.window.player_bar
    bar.rate_cycled.emit()
    assert hearth.core.rate == pytest.approx(1.25)
    assert bar._btn_speed.text() == "1.25x"
    bar.rate_cycled.emit()
    assert bar._btn_speed.text() == "1.5x"
    hearth.shutdown()


def test_sleep_button_label_updates(tmp_path, qapp):
    hearth = make_hearth(tmp_path)
    bar = hearth.window.player_bar
    bar.sleep_requested.emit(15)
    assert bar._btn_sleep.text() == "⏾ 15"
    bar.sleep_requested.emit(0)
    assert bar._btn_sleep.text() == "⏾"
    hearth.shutdown()


def test_radio_request_reaches_app_test_mode(tmp_path, qapp):
    hearth = make_hearth(tmp_path)
    statuses: list[str] = []
    hearth.window.set_status = statuses.append
    track = make_track(video_id="rseed", title="Seed Song")
    hearth.core.play_track(track)
    hearth.window.radio_requested.emit(None)
    assert any("Radio from: Seed Song" in s for s in statuses)
    hearth.shutdown()


def test_radio_request_without_track_is_polite(tmp_path, qapp):
    hearth = make_hearth(tmp_path)
    statuses: list[str] = []
    hearth.window.set_status = statuses.append
    hearth.window.radio_requested.emit(None)
    assert any("Play something first" in s for s in statuses)
    hearth.shutdown()


# ----------------------------------------------------------------- radio wiring


def test_radio_ready_builds_queue_around_current(tmp_path, qapp):
    hearth = make_hearth(tmp_path)
    seed = make_track(video_id="seed")
    hearth.core.start_queue([seed], 0)
    hearth._on_radio_ready(("seed", _tracks("r1", "seed", "r2", "r1")))
    engine = hearth.core.engine
    assert engine.current.video_id == "seed"
    assert [t.video_id for t in engine.upcoming] == ["r1", "r2"]
    hearth.shutdown()


def test_radio_ready_empty_shows_status(tmp_path, qapp):
    hearth = make_hearth(tmp_path)
    seed = _tracks("seed")[0]
    hearth.core.start_queue([seed], 0)
    statuses: list[str] = []
    hearth.window.set_status = statuses.append
    hearth._on_radio_ready(("seed", []))
    assert any("empty" in s for s in statuses)
    hearth.shutdown()


def test_autoplay_ready_extends_queue_and_advances(tmp_path, qapp):
    hearth = make_hearth(tmp_path)
    a, b = _tracks("a", "b")
    hearth.core.start_queue([a, b], 0)
    # a is playing, b upcoming; queue ran dry → radio returns c, d (b/a already known)
    hearth._on_autoplay_ready(("a", _tracks("c", "a", "b", "d")))
    engine = hearth.core.engine
    assert engine.current.video_id == "b"                        # autoplay advanced
    assert [t.video_id for t in engine.upcoming] == ["c", "d"]   # fresh tail appended
    hearth.shutdown()


def test_autoplay_ready_stale_seed_ignored(tmp_path, qapp):
    hearth = make_hearth(tmp_path)
    a, b = _tracks("a", "b")
    hearth.core.start_queue([a, b], 0)
    hearth._on_autoplay_ready(("some-other-track", _tracks("z")))
    engine = hearth.core.engine
    assert engine.current.video_id == "a"
    assert [t.video_id for t in engine.upcoming] == ["b"]
    hearth.shutdown()


def test_autoplay_ready_nothing_new_stops(tmp_path, qapp):
    hearth = make_hearth(tmp_path)
    a = _tracks("a")[0]
    hearth.core.start_queue([a], 0)
    statuses: list[str] = []
    hearth.core.status.connect(statuses.append)
    hearth._on_autoplay_ready(("a", [a]))
    assert any("nothing new" in s for s in statuses)
    hearth.shutdown()


# ----------------------------------------------------------------- queue dock


def test_queue_dock_pins_current_row(tmp_path, qapp):
    hearth = make_hearth(tmp_path)
    tracks = _tracks("q0", "q1", "q2")
    hearth.core.start_queue(tracks, 0)
    window = hearth.window
    current_item = window._queue_list.item(0)
    upcoming_item = window._queue_list.item(1)
    assert Qt.ItemFlag.ItemIsDragEnabled not in current_item.flags()
    assert Qt.ItemFlag.ItemIsDragEnabled in upcoming_item.flags()
    assert current_item.data(Qt.ItemDataRole.UserRole + 1) == "current"
    assert upcoming_item.data(Qt.ItemDataRole.UserRole + 1) == "upcoming"
    hearth.shutdown()


def test_queue_reorder_roundtrip(tmp_path, qapp):
    hearth = make_hearth(tmp_path)
    hearth.core.start_queue(_tracks("q0", "q1", "q2", "q3"), 0)
    window = hearth.window
    # simulate the drop: move the widget rows, then fire the handler
    taken = window._queue_list.takeItem(2)               # q2
    window._queue_list.insertItem(3, taken)              # q1, q3, q2
    window._on_queue_rows_moved()
    assert [t.video_id for t in hearth.core.engine.upcoming] == ["q1", "q3", "q2"]
    hearth.shutdown()


# ----------------------------------------------------------------- lyrics wiring


def test_lyrics_flow_writes_into_now_view(tmp_path, qapp):
    hearth = make_hearth(tmp_path)
    track = make_track(video_id="lyr1", title="Lyric Song")
    hearth._on_lyrics_ready((track.video_id, "words go here", None))
    hearth.window.now_view.set_track(track)
    hearth._on_lyrics_ready((track.video_id, "words go here", None))
    assert hearth.window.now_view._lyrics._plain.toPlainText() == "words go here"
    assert hearth._lyrics_cache["lyr1"] == ("words go here", None)
    hearth._on_lyrics_ready((track.video_id, None, [LrcLine(0, "hi")]))
    assert hearth.window.now_view._lyrics._pages.currentWidget() is \
        hearth.window.now_view._lyrics._sheet
    hearth.shutdown()


# ----------------------------------------------------------------- persistence


def test_autoplay_persists_across_restart(tmp_path, qapp):
    hearth = make_hearth(tmp_path)
    hearth.core.set_autoplay(False)
    hearth._persist()
    hearth.shutdown()

    reopened = make_hearth(tmp_path)
    assert reopened.core.autoplay is False
    reopened.core.set_autoplay(True)
    reopened.shutdown()
