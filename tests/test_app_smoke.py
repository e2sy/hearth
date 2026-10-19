"""App-level smoke test: full wiring headless, settings persistence roundtrip."""

from hearth import config
from hearth.app import Hearth


def make_hearth(tmp_path) -> Hearth:
    return Hearth(
        argv=["hearth-test"],
        settings_path=str(tmp_path / "settings.ini"),
        data_directory=tmp_path / "data",
        single_instance=False,
        enable_streaming=False,  # keep pool jobs out of unit tests
    )


def test_app_boots_all_components(tmp_path, qapp):
    hearth = make_hearth(tmp_path)
    assert hearth.core is not None
    assert hearth.panel is not None
    assert hearth.toast is not None
    assert hearth.store is not None
    hearth.shutdown()


def test_settings_persist_volume_repeat_rate(tmp_path, qapp):
    hearth = make_hearth(tmp_path)
    hearth.core.set_volume(0.55)
    hearth.core.set_repeat(config.REPEAT_ONE)
    hearth.core.set_rate(1.25)
    hearth.shutdown()

    reopened = make_hearth(tmp_path)
    assert reopened.core.volume == 0.55
    assert reopened.core.engine.repeat == config.REPEAT_ONE
    assert reopened.core.rate == 1.25
    reopened.shutdown()


def test_pick_track_writes_history_and_updates_panel(tmp_path, qapp):
    hearth = make_hearth(tmp_path)
    from .test_models import make_track

    hearth._pick_track(make_track())
    assert len(hearth.store.history()) == 1
    assert hearth.panel._title.text() != "Hearth — nothing playing yet"
    hearth.shutdown()


# --- Qt message bridge: the terminal firehose tamer (v0.6.3 audit) ---


def test_qt_messages_route_to_logging_not_stderr(caplog):
    import logging
    from types import SimpleNamespace

    from PyQt6.QtCore import QtMsgType

    from hearth.app import _qt_message

    with caplog.at_level(logging.DEBUG, logger="qt"):
        # the exact line that flooded MAYANK's terminal, now file-only DEBUG
        _qt_message(
            QtMsgType.QtWarningMsg,
            SimpleNamespace(category=b"qt.multimedia.ffmpeg.mediadataholder"),
            b"Could not open media. FFmpeg error 403",
        )
        # ordinary Qt warnings keep their natural severity
        _qt_message(
            QtMsgType.QtWarningMsg,
            SimpleNamespace(category=b"qt.qpa.xcb"),
            b"could not connect to display",
        )
        # str payloads and empty categories must not crash the handler
        _qt_message(QtMsgType.QtCriticalMsg, SimpleNamespace(category=None), "plain text")

    by_name = {r.name: r for r in caplog.records}
    multimedia = by_name["qt.qt.multimedia.ffmpeg.mediadataholder"]
    assert multimedia.levelno == logging.DEBUG
    assert "Could not open media" in multimedia.message
    assert by_name["qt.qt.qpa.xcb"].levelno == logging.WARNING
    assert by_name["qt"].levelno == logging.ERROR


def test_qt_bridge_is_installed_on_boot(tmp_path, qapp):
    from PyQt6.QtCore import qInstallMessageHandler

    make_hearth(tmp_path).shutdown()
    assert qInstallMessageHandler(None) is not None  # something was installed


# --- the pocket hearth: the floating mini player (wave 2) ---


def test_mini_player_opens_mirrors_and_closes(tmp_path, qapp):
    from .test_models import make_track

    hearth = make_hearth(tmp_path)
    track = make_track()
    hearth._pick_track(track)

    hearth._toggle_mini_player()
    assert hearth._mini_window is not None
    assert hearth._mini_window.isVisible()
    assert hearth._mini_model.title == track.title
    assert hearth._mini_model.artist == track.artist

    # second toggle → closed, not rebuilt blank
    hearth._toggle_mini_player()
    assert not hearth._mini_window.isVisible()
    hearth._toggle_mini_player()
    assert hearth._mini_window.isVisible()
    hearth.shutdown()


def test_mini_model_mirrors_playback_even_while_closed(tmp_path, qapp):
    from .test_models import make_track

    hearth = make_hearth(tmp_path)
    hearth._pick_track(make_track())
    # the window was never opened, but the model still follows the core
    assert hearth._mini_model.title == make_track().title
    hearth._mini_on_duration(150_000)
    assert hearth._mini_model.duration_ms == 150_000
    hearth._mini_on_state(True)
    assert hearth._mini_model.playing is True
    hearth.shutdown()


def test_mini_expand_hides_pocket_and_raises_the_room(tmp_path, qapp):
    hearth = make_hearth(tmp_path)
    hearth._toggle_mini_player()
    hearth._expand_mini()
    assert not hearth._mini_window.isVisible()
    hearth.shutdown()


def test_mini_player_has_a_palette_entry(tmp_path, qapp):
    hearth = make_hearth(tmp_path)
    labels = [a.label for a in hearth._palette_actions()]
    assert "Mini player" in labels
    hearth.shutdown()


# --- wave 3: reopen where you left off ---

def test_last_view_roundtrip(tmp_path, qapp):
    hearth = make_hearth(tmp_path)
    hearth.window.show_view("stats")
    assert hearth.window._last_view == "stats"
    hearth.shutdown()

    reopened = make_hearth(tmp_path)
    assert reopened.window._last_view == "stats"
    reopened.shutdown()


def test_last_view_unknown_value_falls_back_home(tmp_path, qapp):
    hearth = make_hearth(tmp_path)
    hearth.settings.setValue("last_view", "narnia")
    hearth.shutdown()

    reopened = make_hearth(tmp_path)
    assert reopened.window._last_view in ("home", reopened.window.VIEWS[0])
    reopened.shutdown()


# --- wave 3: the pocket's spot survives ---

def test_mini_position_survives_reopen(tmp_path, qapp):
    from PyQt6.QtCore import QPoint

    hearth = make_hearth(tmp_path)
    hearth._open_mini_player()
    hearth._mini_window.move(QPoint(64, 48))
    hearth._remember_mini_position()
    hearth.shutdown()

    reopened = make_hearth(tmp_path)
    reopened._open_mini_player()
    assert reopened._mini_window.pos().x() == 64
    assert reopened._mini_window.pos().y() == 48
    reopened.shutdown()


def test_mini_position_offscreen_is_ignored(tmp_path, qapp):
    from PyQt6.QtCore import QPoint

    hearth = make_hearth(tmp_path)
    hearth.settings.setValue("mini/pos", QPoint(-99999, -99999))
    hearth._open_mini_player()
    # the window must not be dragged off-screen by a stale spot
    assert hearth._mini_window.pos().x() > -99999
    hearth.shutdown()


# --- wave 3b: maximized is a state, not a size ---

def test_bool_setting_reads_strings_and_bools(tmp_path, qapp):
    hearth = make_hearth(tmp_path)
    hearth.settings.setValue("flag/yes", "true")
    hearth.settings.setValue("flag/no", "false")
    hearth.settings.setValue("flag/one", "1")
    assert hearth._bool_setting("flag/yes") is True
    assert hearth._bool_setting("flag/no") is False
    assert hearth._bool_setting("flag/one") is True
    assert hearth._bool_setting("flag/missing", True) is True
    hearth.shutdown()


# --- the Quick picks blend (v0.7.6 audit) ---
#
# Six seeded queries race the same home shelf; the last finisher used to
# wipe the five before it, so Quick picks could land as one lonely card.
# Results now fold into a deduped blend in config order.


def test_quick_picks_queries_accumulate_never_overwrite(tmp_path, qapp):
    hearth = make_hearth(tmp_path)
    from .test_models import make_track

    first = [make_track(video_id=f"q{i}") for i in range(3)]
    second = [make_track(video_id=f"r{i}") for i in range(3)]

    blend = hearth._merge_quick_picks(config.QUICK_PICKS[0], first)
    assert [t.video_id for t in blend] == [t.video_id for t in first]

    blend = hearth._merge_quick_picks(config.QUICK_PICKS[1], second)
    # the first query's cards survive the second query's arrival
    assert [t.video_id for t in blend] == (
        [t.video_id for t in first] + [t.video_id for t in second])
    hearth.shutdown()


def test_quick_picks_blend_dedupes_and_orders_by_config(tmp_path, qapp):
    hearth = make_hearth(tmp_path)
    from .test_models import make_track

    late_query = config.QUICK_PICKS[2]
    shared = make_track(video_id="shared")
    # the later-config query lands FIRST at runtime — networks race
    hearth._merge_quick_picks(late_query, [shared, make_track(video_id="b2")])
    blend = hearth._merge_quick_picks(
        config.QUICK_PICKS[0], [shared, make_track(video_id="a1")])
    # the earlier-config query renders first; within it, landed order
    # stands; the shared video_id is shown exactly once
    ids = [t.video_id for t in blend]
    assert ids == ["shared", "a1", "b2"]
    hearth.shutdown()


def test_quick_picks_empty_result_never_erases_the_blend(tmp_path, qapp):
    hearth = make_hearth(tmp_path)
    from .test_models import make_track

    hearth._merge_quick_picks(
        config.QUICK_PICKS[0], [make_track(video_id="keep")])
    blend = hearth._merge_quick_picks(config.QUICK_PICKS[1], [])
    assert [t.video_id for t in blend] == ["keep"]
    # junk rows are folded out, not crashed on
    blend = hearth._merge_quick_picks(config.QUICK_PICKS[2], ["nope", None])
    assert [t.video_id for t in blend] == ["keep"]
    hearth.shutdown()


def test_quick_picks_blend_is_capped_to_a_shelf_row(tmp_path, qapp):
    hearth = make_hearth(tmp_path)
    from .test_models import make_track

    for i, query in enumerate(config.QUICK_PICKS[:3]):
        hearth._merge_quick_picks(
            query, [make_track(video_id=f"{i}-{j}") for j in range(8)])
    blend = hearth._merge_quick_picks(
        config.QUICK_PICKS[3], [make_track(video_id="tail")])
    assert len(blend) == config.QUICK_PICKS_SHELF_LIMIT
    hearth.shutdown()


def test_quick_picks_refresh_resets_the_sweep(tmp_path, qapp):
    """A new home sweep starts clean; stale results don't haunt it."""
    hearth = make_hearth(tmp_path)
    from .test_models import make_track

    hearth._merge_quick_picks(
        config.QUICK_PICKS[0], [make_track(video_id="old")])
    hearth._refresh_home()   # enable_streaming=False: no jobs, sweep reset
    blend = hearth._merge_quick_picks(
        config.QUICK_PICKS[1], [make_track(video_id="new")])
    assert [t.video_id for t in blend] == ["new"]
    hearth.shutdown()


# --- the home-shelf render regression (the empty Top tracks screenshot) ---
#
# Boot-populated shelves (Top tracks / On Repeat) rendered as visible
# headers over empty strips: the page's entrance fade parked an opacity
# effect on the home view, and Qt doesn't compose effects down the
# ancestor chain — every shadow-carrying shelf card went blank beneath
# it. After the fix the composite must carry the cards' pixels.


def _spin(qapp, ms: int) -> None:
    from PyQt6.QtCore import QEventLoop, QTimer

    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def test_home_shelves_render_cards_after_the_fade(tmp_path, qapp):
    hearth = make_hearth(tmp_path)
    from .test_models import make_track

    import time as _time

    now = _time.time()
    for i in range(4):
        hearth.store.log_play(
            make_track(video_id=f"hot{i}"), played_at=now - i * 60)

    hearth.window.show()
    hearth.window.show_view("home")
    _spin(qapp, 600)   # entrance fade lands + deferred effect release

    hv = hearth.window.home_view
    # the fade's rental is handed back: no effect parked on the page
    assert hv.graphicsEffect() is None

    shelf = hv._shelves["Top tracks"]
    assert len(shelf._tracks) == 4
    assert shelf._strip_lay.count() == 4

    img = hv.grab().toImage()
    tl = shelf._strip_area.mapTo(hv, shelf._strip_area.rect().topLeft())
    lit = sum(
        1
        for x in range(tl.x() + 5, min(tl.x() + 240, img.width()), 6)
        for y in range(tl.y() + 10, min(tl.y() + 200, img.height()), 6)
        if img.pixelColor(x, y).lightness() > 40
    )
    assert lit > 50, f"shelf cards blank in the composite ({lit} lit samples)"
    hearth.shutdown()


def test_home_view_never_keeps_the_fade_effect_between_visits(tmp_path, qapp):
    """Leaving and re-entering Home never parks a stale effect."""
    hearth = make_hearth(tmp_path)
    from .test_models import make_track

    hearth.store.log_play(make_track(video_id="one"))
    hearth.window.show()
    for view in ("stats", "home", "history", "home"):
        hearth.window.show_view(view)
        _spin(qapp, 350)
        assert hearth.window.home_view.graphicsEffect() is None
    hearth.shutdown()
