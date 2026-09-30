"""v0.8.0 stage: desktop lyrics overlay, theater mode, palette packs,
lyrics settings — headless and offscreen, no network, no sleeps."""

import json

import pytest
from PyQt6.QtCore import QEvent, QPointF, Qt
from PyQt6.QtGui import QColor, QKeyEvent, QMouseEvent
from PyQt6.QtWidgets import QPushButton

from hearth import config, theme
from hearth.config import get_palette
from hearth.lyrics import LrcLine, SyncedLyrics
from hearth.lyrics_overlay import LyricsOverlay
from hearth.window import AccentPickerDialog, MainWindow, TheaterView

from .test_app_smoke import make_hearth
from .test_models import make_track

LINES = [LrcLine(0, "first line"), LrcLine(60_000, "second line"),
         LrcLine(120_000, "third line")]


@pytest.fixture(autouse=True)
def _clean_palettes():
    """Palette-pack tests mutate config.PALETTES — always restore it."""
    saved = dict(config.PALETTES)
    yield
    config.PALETTES.clear()
    config.PALETTES.update(saved)


# ----------------------------------------------------------------- overlay

def test_overlay_empty_state_and_lines(qapp):
    ov = LyricsOverlay("frost")
    assert ov._now.text() == "♪"          # missing lyrics keep the strip warm
    ov.show_line("first line", "second line")
    assert ov._now.text() == "first line"
    assert ov._next.text() == "second line"
    ov.show_line("")                       # blank line never blanks the strip
    assert ov._now.text() == "♪"
    ov.clear()
    assert ov._now.text() == "♪"
    assert ov._next.text() == ""


def test_overlay_flags_and_toggle(qapp):
    ov = LyricsOverlay(None)
    flags = ov.windowFlags()
    assert Qt.WindowType.FramelessWindowHint & flags
    assert Qt.WindowType.WindowStaysOnTopHint & flags
    assert Qt.WindowType.Tool & flags
    assert ov.toggle() is True and ov.isVisible()
    assert ov.toggle() is False and not ov.isVisible()


def test_overlay_set_palette_recolors(qapp):
    ov = LyricsOverlay("grove")
    orchid = get_palette("orchid")
    ov.set_palette(orchid)
    assert ov._palette is orchid
    assert f"color: {orchid.accent}" in ov._now.styleSheet()
    assert f"color: {orchid.text_dim}" in ov._next.styleSheet()


def test_overlay_drag_moves_window(qapp):
    ov = LyricsOverlay(None)
    start = ov.pos()
    press = QMouseEvent(QEvent.Type.MouseButtonPress, QPointF(10, 10),
                        QPointF(10, 10), Qt.MouseButton.LeftButton,
                        Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    ov.mousePressEvent(press)
    move = QMouseEvent(QEvent.Type.MouseMove, QPointF(10, 10),
                       QPointF(10 + 30, 10 + 20), Qt.MouseButton.LeftButton,
                       Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    ov.mouseMoveEvent(move)
    assert ov.pos().x() == start.x() + 30
    assert ov.pos().y() == start.y() + 20
    release = QMouseEvent(QEvent.Type.MouseButtonRelease, QPointF(10, 10),
                          QPointF(40, 30), Qt.MouseButton.LeftButton,
                          Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier)
    ov.mouseReleaseEvent(release)
    move2 = QMouseEvent(QEvent.Type.MouseMove, QPointF(10, 10),
                        QPointF(90, 90), Qt.MouseButton.LeftButton,
                        Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    ov.mouseMoveEvent(move2)
    assert ov.pos().x() == start.x() + 30   # released: no more dragging


# ----------------------------------------------------------------- palette packs

def test_palette_export_import_roundtrip_new_key(tmp_path, qapp):
    path = tmp_path / "pack.json"
    assert theme.export_palette("moss", path) is True
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["key"] = "moss_night"
    payload["label"] = "Moss Night"
    payload["accent"] = "#112233"
    path.write_text(json.dumps(payload), encoding="utf-8")
    key = theme.import_palette(path)
    assert key == "moss_night"
    assert config.PALETTES["moss_night"].accent == "#112233"
    assert config.PALETTES["moss"].accent != "#112233"   # built-in untouched


def test_palette_import_collision_suffixes_builtin(tmp_path, qapp):
    path = tmp_path / "groveish.json"
    payload = theme.palette_to_dict(config.PALETTES["grove"])
    payload["accent"] = "#abcdef"
    path.write_text(json.dumps(payload), encoding="utf-8")
    first = theme.import_palette(path)
    assert first == "grove-2"                # built-in key never overwritten
    assert config.PALETTES["grove"].label == "Grove"
    assert config.PALETTES["grove"].accent != "#abcdef"
    assert config.PALETTES["grove-2"].accent == "#abcdef"
    second = theme.import_palette(path)      # dedupe: another bump, not a clash
    assert second == "grove-3"


def test_palette_import_garbage_returns_none(tmp_path, qapp):
    bad = tmp_path / "bad.json"
    bad.write_text("{not json at all", encoding="utf-8")
    assert theme.import_palette(bad) is None
    assert theme.import_palette(tmp_path / "missing.json") is None
    empty = tmp_path / "empty.json"
    empty.write_text("[]", encoding="utf-8")           # not a dict
    assert theme.import_palette(empty) is None


def test_palette_import_rejects_invalid_colors(tmp_path, qapp):
    path = tmp_path / "invalid.json"
    payload = theme.palette_to_dict(config.PALETTES["slate"])
    payload["accent"] = "red"                 # fails validate_palette
    path.write_text(json.dumps(payload), encoding="utf-8")
    assert theme.import_palette(path) is None
    assert "accent" not in config.PALETTES    # nothing partial merged


def test_palette_export_unknown_key_false(tmp_path, qapp):
    assert theme.export_palette("no-such-palette", tmp_path / "x.json") is False
    assert not (tmp_path / "x.json").exists()


# ----------------------------------------------------------------- lyrics font

def test_lyrics_font_presets_and_fallback(qapp):
    for key, px in (("S", 20), ("M", 28), ("L", 40)):
        assert theme.lyrics_font(key, "").pixelSize() == px
    fallback = theme.lyrics_font("XL", "")   # unknown key → default preset
    assert fallback.pixelSize() == config.LYRICS_SIZE_PRESETS[
        config.LYRICS_DEFAULT_SIZE_KEY
    ]


def test_lyrics_font_family_applied(qapp):
    font = theme.lyrics_font("L", "Georgia")
    assert font.pixelSize() == 40
    assert font.family() == "Georgia"


# ----------------------------------------------------------------- theater

def test_theater_view_tracks_song_and_lyrics(qapp):
    view = TheaterView(get_palette("grove"))
    track = make_track(video_id="th1", thumbnail="")
    view.set_track(track)
    assert view.current_track is track
    assert view._title.text() == track.title
    view.set_lyrics("th1", None, LINES)
    view.set_position(65_000)
    assert view._now.text() == "second line"
    assert view._next.text() == "third line"
    view.set_lyrics("th1", None, [LrcLine(30_000, "late line")])
    view.set_position(500)                    # before the first stamp → ♪
    assert view._now.text() == "♪"
    view.set_position(30_000)
    assert view._now.text() == "late line"
    view.set_lyrics("stale-id", "old words")  # wrong track: ignored
    assert view._sync is not None


def test_theater_exit_via_esc_and_button(qapp):
    view = TheaterView(get_palette("grove"))
    exits = []
    view.exit_requested.connect(lambda: exits.append(1))
    view.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Escape,
                                 Qt.KeyboardModifier.NoModifier))
    view._close.click()
    assert len(exits) == 2


def test_main_window_theater_toggle(tmp_path, qapp):
    hearth = make_hearth(tmp_path)
    window = hearth.window
    track = make_track(video_id="mv1", thumbnail="")
    window.set_track(track)
    window.set_lyrics("mv1", None, LINES)
    assert not window.theater_view.isVisible()
    window.toggle_theater()
    assert window.theater_view.isVisible()
    window.set_position(65_000)               # tick reaches the theater too
    assert window.theater_view._now.text() == "second line"
    window.toggle_theater()
    assert not window.theater_view.isVisible()
    hearth.shutdown()


def test_theater_disabled_gates_entry(monkeypatch, qapp):
    monkeypatch.setattr(config, "THEATER_ENABLED", False)
    window = MainWindow(None, store=None)
    assert "theater" not in getattr(window, "_nav", {})
    assert not any(btn.text() == "🎭 Theater"
                   for btn in window.findChildren(QPushButton))
    window.toggle_theater()
    assert not window.theater_view.isVisible()


# ----------------------------------------------------------------- accent picker

def test_accent_picker_live_trial_and_save_pack(monkeypatch, tmp_path, qapp):
    monkeypatch.setattr(
        "hearth.window.QFileDialog.getSaveFileName",
        lambda *a, **k: (str(tmp_path / "pack.json"), ""),
    )
    trials = []
    dlg = AccentPickerDialog(get_palette("grove"))
    dlg.palette_changed.connect(lambda p: trials.append(p))
    monkeypatch.setattr(
        "hearth.window.QColorDialog.getColor",
        lambda *a, **k: QColor("#3366cc"),
    )
    dlg._pick("accent")
    assert len(trials) == 1
    assert trials[0].accent == "#3366cc"
    saved_keys = []
    dlg.pack_saved.connect(saved_keys.append)
    dlg._save_pack()
    assert dlg.saved is True
    assert len(saved_keys) == 1
    key = saved_keys[0]
    assert key not in config.BUILTIN_PALETTE_KEYS
    assert config.PALETTES[key].accent == "#3366cc"
    pack_path = tmp_path / "pack.json"
    assert json.loads(pack_path.read_text(encoding="utf-8"))["accent"] == "#3366cc"
    # reset returns to the untouched base palette
    dlg._reset()
    assert dlg._palette is get_palette("grove")


# ----------------------------------------------------------------- settings

def test_lyrics_settings_roundtrip_persist(tmp_path, qapp):
    hearth = make_hearth(tmp_path)
    hearth.window.now_view.lyrics_font_changed.emit("L", "Georgia")
    assert hearth.settings.value("lyrics/size") == "L"
    assert hearth.settings.value("lyrics/family") == "Georgia"
    hearth.shutdown()

    reopened = make_hearth(tmp_path)
    now = reopened.window.now_view
    assert now.lyrics_size_key == "L"
    assert now._lyrics._lyric_font.pixelSize() == 40
    assert now._lyrics._lyric_font.family() == "Georgia"
    assert reopened.overlay._font.pixelSize() == 40
    assert "font-size: 40px" in reopened.overlay._now.styleSheet()
    assert reopened.settings.value("lyrics/size") == "L"
    reopened.shutdown()


def test_lyrics_size_chip_updates_sheet_live(qapp):
    window = MainWindow(None, store=None)
    window.now_view.set_track(make_track(video_id="chip1", thumbnail=""))
    window.now_view.set_lyrics("chip1", None, list(LINES))
    window.now_view.set_lyrics_size("L")
    assert window.now_view.lyrics_size_key == "L"
    first = window.now_view._lyrics._sheet.item(0)
    assert first.font().pixelSize() == 40
    window.now_view.set_lyrics_size("S")
    first = window.now_view._lyrics._sheet.item(0)
    assert first.font().pixelSize() == 20


# ----------------------------------------------------------------- app wiring

def test_app_overlay_toggle_and_line_push(tmp_path, qapp):
    hearth = make_hearth(tmp_path)
    assert hearth._overlay_on is False        # config default: opt-in
    hearth._toggle_overlay()
    assert hearth._overlay_on is True and hearth.overlay.isVisible()
    hearth._lyrics_engine = SyncedLyrics(list(LINES))
    hearth._push_overlay_line(1_000)
    assert hearth.overlay._now.text() == "first line"
    assert hearth.overlay._next.text() == "second line"
    hearth._push_overlay_line(61_000)
    assert hearth.overlay._now.text() == "second line"
    assert hearth.overlay._next.text() == "third line"
    hearth._lyrics_engine = SyncedLyrics([LrcLine(5_000, "late line")])
    hearth._overlay_index = -2
    hearth._push_overlay_line(1_000)          # before the first stamp → ♪
    assert hearth.overlay._now.text() == "♪"
    hearth._toggle_overlay()
    assert not hearth.overlay.isVisible()
    hearth._push_overlay_line(62_000)         # hidden: harmless no-op
    hearth.shutdown()


def test_app_overlay_ignores_stale_lyrics_and_disabled_default(tmp_path, qapp):
    hearth = make_hearth(tmp_path)
    track = make_track(video_id="lyr1", thumbnail="")
    hearth.core.play_track(track)
    hearth._on_lyrics_ready(("lyr1", None, list(LINES)))
    assert hearth._lyrics_engine is not None  # current track: engine armed
    hearth._on_lyrics_ready(("other-track", None, list(LINES)))
    # stale payload must not replace the current engine's first line
    assert hearth._lyrics_engine.lines[0].text == "first line"
    hearth.core.play_track(make_track(video_id="next1", thumbnail=""))
    assert hearth._lyrics_engine is None      # a new song resets the strip
    assert hearth.overlay._now.text() == "♪"
    hearth.shutdown()
