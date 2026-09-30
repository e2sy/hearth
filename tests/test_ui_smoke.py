"""Smoke tests: the real UI builds and repaints headless (offscreen)."""

import pytest
from PyQt6.QtGui import QColor, QPixmap
from PyQt6.QtWidgets import QGraphicsDropShadowEffect, QGraphicsOpacityEffect, QLabel

from hearth.config import PALETTES, get_palette
from hearth.cover import CoverTile, paint_mark, reflected_pixmap, rounded_pixmap
from hearth.effects import add_glow, fade_in
from hearth.panel import EqBars, FloatingPanel, SpringPhysics
from hearth.theme import build_stylesheet
from hearth.toast import NowPlayingToast
from hearth.tray import InstanceGuard, hearth_mark, paint_icon
from hearth.utils import mix

from .test_models import make_track


def test_stylesheet_has_every_token():
    sheet = build_stylesheet(get_palette("hearthlight"))
    assert "#f0a437" in sheet   # accent lands in the compiled CSS
    assert "$" not in sheet     # strict substitution: no token left behind


def test_stylesheet_compiles_for_every_palette():
    # the 2020s layer derives extra tones per palette; none may leak a token
    for key in PALETTES:
        sheet = build_stylesheet(get_palette(key))
        assert "$" not in sheet
        assert "qlineargradient" in sheet   # depth is the point


def test_mix_blends_toward_target():
    assert mix("#000000", "#ffffff", 0.0) == "#000000"
    assert mix("#000000", "#ffffff", 1.0) == "#ffffff"
    assert mix("#000000", "#ffffff", 0.5) == "#808080"


def test_spring_physics_stays_clamped():
    physics = SpringPhysics(bars=4)
    physics.impulse(5.0)
    for _ in range(200):
        values = physics.step(0.05)
        assert all(0.05 <= v <= 1.0 for v in values)


def test_spring_physics_decays():
    physics = SpringPhysics()
    physics.impulse(4.0)
    peak = 0.0
    for _ in range(60):
        peak = max(peak, max(physics.step(0.05)))
    late = max(physics.step(0.05))
    # transients decay: the impulse spike never comes back
    assert peak > late
    for _ in range(120):
        values = physics.step(0.05)
    settled = sum(values)
    # steady state: bars come to rest at their targets
    assert abs(settled - sum(physics.step(0.05))) < 1e-4


def test_panel_builds_and_toggles(qapp):
    panel = FloatingPanel("frost")
    assert not panel.expanded
    panel.setExpanded()
    assert panel.expanded
    panel.setCompact()
    assert not panel.expanded


def test_panel_track_and_state(qapp):
    panel = FloatingPanel("moss")
    panel.set_track(make_track())
    panel.set_playing(True)
    assert panel._btn_play.text() == "⏸"
    panel.set_playing(False)
    assert panel._btn_play.text() == "▶"
    panel.set_track(None)
    assert "nothing playing" in panel._title.text()


def test_panel_results_and_pick_signal(qapp):
    panel = FloatingPanel("slate")
    seen = []
    panel.track_picked.connect(seen.append)
    panel.show_results([make_track(video_id="aaa"), make_track(video_id="bbb")])
    assert len(panel.current_results) == 2
    panel._on_result_clicked(panel._results.item(0))
    assert seen[0].video_id == "aaa"


def test_panel_search_debounce_emits(qapp):
    panel = FloatingPanel("orchid")
    seen = []
    panel.search_submitted.connect(seen.append)
    panel._search.setText("daft punk")
    panel._emit_search()
    assert seen == ["daft punk"]


def test_toast_builds_and_announces(qapp):
    toast = NowPlayingToast("emberfall")
    toast.announce(make_track())
    assert "▶" in toast._sub.text()


def test_paint_icon_returns_icon(qapp):
    icon = paint_icon()
    assert not icon.isNull()


def test_hearth_mark_returns_icon(qapp):
    icon = hearth_mark()
    assert not icon.isNull()


def test_hearth_mark_with_explicit_palette(qapp):
    # Regression: the mark must read colors off a palette *instance*,
    # never off the Palette class (NameError/AttributeError guard).
    icon = hearth_mark(get_palette("frost"))
    assert not icon.isNull()


def test_instance_guard_property(qapp, tmp_path):
    # With single_instance server disabled elsewhere, constructing a guard
    # here must at least be coherent about primary status.
    guard = InstanceGuard()
    assert isinstance(guard.is_primary, bool)
    if guard.server is not None:
        guard.server.close()


# ------------------------------------------------- 2020s depth & motion


def test_paint_mark_is_a_rounded_glossy_tile(qapp):
    mark = paint_mark(get_palette("grove"), 168)
    assert not mark.isNull()
    assert mark.size().width() == 168 and mark.size().height() == 168
    # corners are clipped by the rounded shell (transparent), center is not
    assert QColor(mark.toImage().pixelColor(0, 0)).alpha() == 0
    assert QColor(mark.toImage().pixelColor(84, 84)).alpha() > 0


def test_rounded_pixmap_clips_corners(qapp):
    plain = QPixmap(64, 64)
    plain.fill(QColor("#123456"))
    clipped = rounded_pixmap(plain, 16)
    assert clipped.size() == plain.size()
    assert QColor(clipped.toImage().pixelColor(0, 0)).alpha() == 0
    assert QColor(clipped.toImage().pixelColor(32, 32)).alpha() == 255


def test_reflected_pixmap_adds_fading_floor(qapp):
    art = QPixmap(80, 80)
    art.fill(QColor("#ff8800"))
    mirrored = reflected_pixmap(art, depth_frac=0.3)
    # taller than the source: original + gap + reflection strip
    assert mirrored.height() > art.height()
    assert mirrored.width() == art.width()
    # the reflection fades to nothing at its bottom edge
    bottom = QColor(mirrored.toImage().pixelColor(40, mirrored.height() - 1))
    assert bottom.alpha() < 40


def test_glow_attaches_and_fade_settles(qapp):
    halo = QLabel("halo me")
    effect = add_glow(halo, "#1db954", blur=24)
    assert isinstance(effect, QGraphicsDropShadowEffect)
    assert halo.graphicsEffect() is effect
    # a widget with its own effect keeps it — the fade politely skips
    fade_in(halo, ms=60)
    assert halo.graphicsEffect() is effect
    # a plain widget fades in: effect attached, ramp begins at zero
    plain = QLabel("fade me")
    fade_in(plain, ms=60)
    settled = plain.graphicsEffect()
    assert isinstance(settled, QGraphicsOpacityEffect)
    assert settled.opacity() <= 0.01
    # deterministic finish: force the animation clock to its end. No
    # wall-clock or interpolation probing anywhere — CI runners tick
    # animations erratically (Windows offscreen taught us that twice)
    ramp = settled._hearth_ramp
    ramp.setCurrentTime(ramp.totalDuration())
    assert settled.opacity() == pytest.approx(1.0)
    # restarting on a settled widget is always safe and resets to zero
    fade_in(plain, ms=60)
    assert plain.graphicsEffect().opacity() <= 0.01
    plain.graphicsEffect()._hearth_ramp.setCurrentTime(60)
    assert plain.graphicsEffect().opacity() == pytest.approx(1.0)


def test_cover_tile_frames_art_and_announces(qapp):
    tile = CoverTile(get_palette("grove"), 96)
    seen = []
    tile.art_changed.connect(seen.append)   # constructor swap already happened
    tile.set_mark()   # repaints the mark → art_changed fires
    assert len(seen) == 1
    assert not tile.pixmap().isNull()
    # art lands in a rounded frame: corner transparent, heart opaque
    img = tile.pixmap().toImage()
    assert QColor(img.pixelColor(0, 0)).alpha() == 0
    assert QColor(img.pixelColor(48, 48)).alpha() > 0


def test_now_view_mirrors_cover_in_reflection(qapp):
    from hearth.window import NowView

    view = NowView(get_palette("grove"))
    view.set_track(make_track(thumbnail=""))   # painted mark: synchronous
    shown = view._reflection.pixmap()
    assert shown is not None and not shown.isNull()
    view.set_track(None)
    gone = view._reflection.pixmap()
    assert gone is None or gone.isNull()   # clear stage, clear floor


def test_eqbars_glossy_paint(qapp):
    eq = EqBars(get_palette("orchid"))
    eq.set_active(True)
    eq._physics.step(0.04)   # give the bars something to paint
    grabbed = eq.grab()
    assert not grabbed.isNull()
    eq.set_active(False)
