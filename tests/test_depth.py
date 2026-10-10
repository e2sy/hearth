"""v0.9.1 depth system: the tokens, the relief stylesheet, and real shadows.

docs/UI-DEPTH.md is the frame; these tests pin the dials. Pure string
math where possible, offscreen effect-slot checks for the floaters.
"""

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QGraphicsDropShadowEffect

from hearth import config, theme
from hearth.config import get_palette

GROVE = get_palette("grove")


# ----------------------------------------------------------------- tokens

def test_depth_tokens_shape():
    assert config.DEPTH_RADIUS >= 8                 # floaters get real corners
    assert set(config.DEPTH_SHADOWS) == {"card", "bar", "float"}
    for blur, dy, alpha in config.DEPTH_SHADOWS.values():
        assert blur > 0 and dy > 0
        assert 0 < alpha <= 255
    # floaters hover higher than cards: wider, softer shadows
    assert config.DEPTH_SHADOWS["float"][0] > config.DEPTH_SHADOWS["card"][0]
    assert config.DEPTH_SHADOWS["bar"][0] > config.DEPTH_SHADOWS["card"][0]


# ----------------------------------------------------------------- the language

def test_spotlight_canvas():
    css = theme.build_stylesheet(GROVE)
    assert "qradialgradient(cx: 0.5, cy: 0.04" in css
    glow = theme._mix(GROVE.bg, GROVE.accent, 0.07)
    assert glow in css                              # the warm spot at the top


def test_carved_surfaces_have_lips():
    css = theme.build_stylesheet(GROVE)
    edge_hi = theme._mix(GROVE.hairline, GROVE.text, 0.14)
    shadow_edge = theme._mix(GROVE.surface, "#000000", 0.32)
    assert f"border-top-color: {edge_hi}" in css          # light catches the top
    assert f"border-bottom-color: {shadow_edge}" in css   # shade pools beneath


def test_glossy_accent_ramp():
    css = theme.build_stylesheet(GROVE)
    acc_hi = theme._mix(GROVE.accent, "#ffffff", 0.22)
    acc_deep = theme._mix(GROVE.accent, "#000000", 0.28)
    assert f"stop: 0 {acc_hi}" in css
    assert f"stop: 1 {acc_deep}" in css
    # pressed sinks: the ramp flips
    assert f"stop: 0 {acc_deep}, stop: 1 {GROVE.accent}" in css


def test_inset_channels_and_glossy_handle():
    css = theme.build_stylesheet(GROVE)
    inset_top = theme._mix(GROVE.bg, "#000000", 0.30)
    assert f"stop: 0 {inset_top}" in css            # fields and grooves sink in
    assert "QSlider::handle:horizontal" in css
    assert "qradialgradient(cx: 0.35, cy: 0.3" in css     # the glossy sphere


def test_playerbar_floats_with_depth_radius():
    css = theme.build_stylesheet(GROVE)
    assert 'QWidget[playerbar="true"]' in css
    assert f"border-radius: {config.DEPTH_RADIUS}px" in css


def test_glass_mode_frosts_the_depth_tones():
    theme.set_style("glass")
    try:
        css = theme.build_stylesheet(GROVE)
        surf_a = theme.STYLES["glass"].panel_alpha
        r, g, b = (int(GROVE.surface[i:i + 2], 16) for i in (1, 3, 5))
        assert f"rgba({r}, {g}, {b}, {surf_a}%)" in css     # panes stay translucent
        # the spotlight follows the canvas into the glass (100% without wallpaper)
        glow = theme._mix(GROVE.bg, GROVE.accent, 0.07)
        gr, gg, gb = (int(glow[i:i + 2], 16) for i in (1, 3, 5))
        assert f"rgba({gr}, {gg}, {gb}, 100%)" in css
    finally:
        theme.set_style(None)   # the frost melts: never leak into other tests


# ----------------------------------------------------------------- floaters

def test_player_bar_carries_a_real_shadow(qapp):
    from hearth.window import MainWindow

    win = MainWindow("grove")
    effect = win.player_bar.graphicsEffect()
    assert isinstance(effect, QGraphicsDropShadowEffect)
    assert effect.blurRadius() == config.DEPTH_SHADOWS["bar"][0]
    win.close()


def test_home_shelf_cards_hover(qapp):
    from hearth.window import Shelf

    from .test_models import make_track

    shelf = Shelf(GROVE, "test shelf")
    shelf.set_tracks([make_track(), make_track(video_id="x2", title="Two")])
    card = shelf._strip_lay.itemAt(0).widget()
    assert isinstance(card.graphicsEffect(), QGraphicsDropShadowEffect)
    assert card.graphicsEffect().blurRadius() == config.DEPTH_SHADOWS["card"][0]
    shelf.deleteLater()


def test_frameless_floaters_carry_shadows(qapp):
    from hearth.command_palette import CommandPalette
    from hearth.minimode import MiniPlayerModel, build_mini_widget
    from hearth.panel import FloatingPanel

    panel = FloatingPanel("grove")
    assert isinstance(panel.graphicsEffect(), QGraphicsDropShadowEffect)
    panel.close()
    panel.deleteLater()

    pal = CommandPalette("grove")
    assert isinstance(pal.graphicsEffect(), QGraphicsDropShadowEffect)
    assert pal.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
    pal.deleteLater()

    mini = build_mini_widget(GROVE, MiniPlayerModel())
    assert isinstance(mini.graphicsEffect(), QGraphicsDropShadowEffect)
    assert mini.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
    mini.close()
    mini.deleteLater()


# --- wave 3: focus rims and the pressed handle ---

def test_focus_rims_exist_for_lists_and_buttons():
    css = theme.build_stylesheet(GROVE)
    assert "QListWidget:focus" in css
    assert "QPushButton:focus" in css
    assert "$accent_soft" not in css        # tokens must all be resolved


def test_slider_handle_has_a_pressed_face():
    css = theme.build_stylesheet(GROVE)
    assert "QSlider::handle:horizontal:pressed" in css
    assert "QSlider::sub-page:horizontal:active" in css
