"""The pocket hearth: marquee math, clock honesty, and a draggable ember.

The model is pure — no Qt at all. The widget tests run offscreen and
only assert mirrors and gestures, never internals.
"""

import pytest
from PyQt6.QtCore import Qt

from hearth import minimode
from hearth.minimode import Marquee, MiniPlayerModel, fmt_clock


def _palette():
    from hearth.config import get_palette

    return get_palette("hearthlight")


# --- fmt_clock ---------------------------------------------------------------


def test_clock_formats_minutes_and_seconds():
    assert fmt_clock(83_000) == "1:23"
    assert fmt_clock(0) == "0:00"
    assert fmt_clock(3_600_000) == "60:00"


def test_clock_never_raises_on_junk():
    assert fmt_clock(None) == "0:00"
    assert fmt_clock(-5) == "0:00"
    assert fmt_clock("banana") == "0:00"


# --- the marquee walk --------------------------------------------------------


def test_marquee_shows_short_text_verbatim_and_never_walks():
    m = Marquee(text="Tiny", width=24)
    assert m.visible == "Tiny"
    assert m.fits
    m.tick()
    m.tick()
    assert m.visible == "Tiny"


def test_marquee_walks_a_long_line_forward():
    text = "a" * 10 + "b" * 10 + "c" * 10
    m = Marquee(text=text, width=8, rest_ticks=0)
    assert m.visible == text[:8]
    m.tick()
    assert m.visible == text[1:9]


def test_marquee_rests_then_bounces_at_the_right_edge():
    text = "a" * 20
    m = Marquee(text=text, width=10, rest_ticks=2)
    for _ in range(10):
        m.tick()
    assert m.offset == 10                    # clamped at the edge
    assert m.direction == -1
    assert m._rest == 2                      # resting before walking back
    m.tick()
    m.tick()                                 # rest spent
    m.tick()                                 # actually walks back
    assert m.offset == 9


def test_marquee_resets_when_text_changes():
    m = Marquee(text="first line", width=5)
    for _ in range(6):
        m.tick()
    m.set_text("brand new song title")
    assert m.offset == 0
    assert m.direction == 1


def test_marquee_visible_never_raises_or_slips_past_the_end():
    m = Marquee(text="12345", width=24, rest_ticks=0)
    for _ in range(50):
        m.tick()
    assert m.visible == "12345"


# --- the pure model ----------------------------------------------------------


def test_model_starts_as_a_quiet_hearth():
    m = MiniPlayerModel()
    assert m.empty
    assert m.title_window() == "Hearth"
    assert m.artist_label() == "nothing playing"
    assert m.play_glyph() == "▶"
    assert m.clock() == "0:00 / --:--"


def test_model_mirrors_a_track_and_resets_progress():
    m = MiniPlayerModel()
    m.set_position(90_000)
    m.set_duration(200_000)
    m.set_track("Nightdrive", "Neon Fox")
    assert not m.empty
    assert m.title == "Nightdrive"
    assert m.artist_label() == "Neon Fox"
    assert m.progress() == (0, 0)            # new song, fresh clock


def test_model_position_and_duration_are_clamped():
    m = MiniPlayerModel()
    m.set_position(-100)
    assert m.position_ms == 0
    m.set_duration("junk")
    assert m.duration_ms == 0
    m.set_position(5_000)
    m.set_duration(10_000)
    assert m.progress_fraction() == 0.5


def test_model_progress_fraction_never_exceeds_one():
    m = MiniPlayerModel()
    m.set_position(99_000)
    m.set_duration(10_000)
    assert m.progress_fraction() == 1.0
    m.set_duration(0)
    assert m.progress_fraction() == 0.0


def test_model_clock_shows_dashes_until_duration_arrives():
    m = MiniPlayerModel()
    m.set_position(65_000)
    assert m.clock() == "1:05 / --:--"
    m.set_duration(200_000)
    assert m.clock() == "1:05 / 3:20"


def test_model_toggles_the_pin():
    m = MiniPlayerModel()
    assert m.on_top is True
    assert m.toggle_on_top() is False
    assert m.toggle_on_top() is True


def test_model_marquee_follows_the_title():
    m = MiniPlayerModel(marquee_width=8)
    m.set_track("The Longest Song Title Ever Recorded", "Someone")
    assert m.title_window() == "The Long"


# --- the widget: mirrors in, gestures out ------------------------------------


def _make_widget(model=None):
    from hearth.minimode import build_mini_widget

    calls = {"play": 0, "next": 0, "prev": 0, "seek": [], "expand": 0,
             "pin": [], "close": 0}
    w = build_mini_widget(
        _palette(),
        model or MiniPlayerModel(),
        on_play_pause=lambda: calls.__setitem__("play", calls["play"] + 1),
        on_next=lambda: calls.__setitem__("next", calls["next"] + 1),
        on_prev=lambda: calls.__setitem__("prev", calls["prev"] + 1),
        on_seek=lambda ms: calls["seek"].append(ms),
        on_expand=lambda: calls.__setitem__("expand", calls["expand"] + 1),
        on_pin=lambda v: calls["pin"].append(v),
        on_close=lambda: calls.__setitem__("close", calls["close"] + 1),
    )
    return w, calls


def test_widget_builds_frameless_and_on_top(qapp):
    w, _ = _make_widget()
    assert w.isWindow()
    assert w.windowFlags() & Qt.WindowType.FramelessWindowHint
    assert w.windowFlags() & Qt.WindowType.WindowStaysOnTopHint
    assert w.windowFlags() & Qt.WindowType.Tool


def test_widget_mirrors_a_track_into_labels(qapp):
    w, _ = _make_widget()
    w.apply_track("Nightdrive", "Neon Fox")
    w.apply_playing(True)
    assert w._title.text() == "Nightdrive"
    assert w._artist.text() == "Neon Fox"
    assert not w._play.icon().isNull()       # pause glyph painted in
    w.apply_playing(False)
    assert not w._play.icon().isNull()       # play glyph painted in


def test_widget_seeks_only_when_duration_is_known(qapp):
    w, calls = _make_widget()
    w.apply_position(0, 100_000)
    w._seek.setValue(500)
    w._seek.sliderReleased.emit()
    assert calls["seek"] == [50_000]         # half of 100 s
    # unknown duration → the grab lands nowhere, honestly
    w2, calls2 = _make_widget()
    w2._seek.setValue(500)
    w2._seek.sliderReleased.emit()
    assert calls2["seek"] == []


def test_widget_transport_buttons_reemit(qapp):
    w, calls = _make_widget()
    w._prev.click()
    w._play.click()
    w._next.click()
    assert (calls["prev"], calls["play"], calls["next"]) == (1, 1, 1)


def test_widget_expand_via_button_and_double_click(qapp):
    from PyQt6.QtTest import QTest

    w, calls = _make_widget()
    w.show()
    w._expand.click()
    QTest.mouseDClick(w, Qt.MouseButton.LeftButton)   # a real double-click event
    assert calls["expand"] == 2


def test_widget_close_calls_home_then_hides(qapp):
    w, calls = _make_widget()
    w.show()
    w._close.click()
    assert calls["close"] == 1
    assert not w.isVisible()


def test_widget_pin_toggles_and_reports(qapp):
    w, calls = _make_widget()
    w._pin.click()
    assert calls["pin"] == [False]
    w._pin.click()
    assert calls["pin"] == [False, True]


def test_widget_marquee_ticker_repaints_a_long_title(qapp):
    model = MiniPlayerModel(marquee_width=8)
    w, _ = _make_widget(model)
    w.apply_track("abcdefghij", "X")
    w._pulse()
    w._pulse()
    assert w._title.text() == "abcdefgh"[:8] or len(w._title.text()) <= 8


def test_widget_positions_the_seek_bar_from_progress(qapp):
    w, _ = _make_widget()
    w.apply_track("Song", "Artist")
    w.apply_position(25_000, 100_000)
    assert w._seek.value() == 250
