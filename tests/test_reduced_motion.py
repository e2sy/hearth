"""The reduced-motion kill-switch: everything holds still, nothing breaks.

config.MOTION_ENABLED = False must silence every choreography helper —
surfaces keep their resting shadows, toasts appear without slides, and
no helper raises. These tests flip the flag and demand stillness.
"""

import pytest

from PyQt6.QtWidgets import QPushButton

from hearth import config, effects, motion


@pytest.fixture()
def frozen_motion(monkeypatch):
    monkeypatch.setattr(config, "MOTION_ENABLED", False)


def test_hover_lift_returns_none_but_keeps_the_rest_shadow(qapp, frozen_motion):
    card = QPushButton("card")
    assert effects.hover_lift(card) is None
    assert card._hearth_lift is None
    blur, dy, alpha = motion.shadow_for(motion.LEVEL_REST)
    assert card.graphicsEffect().blurRadius() == blur
    assert card.graphicsEffect().color().alpha() == alpha


def test_start_pulse_is_a_noop_when_frozen(qapp, frozen_motion):
    row = QPushButton("row")
    effects.start_pulse(row, "#ff0000")
    assert row._hearth_pulse is None or getattr(row, "_hearth_pulse", None) is None


def test_slide_toast_is_a_noop_when_frozen(qapp, frozen_motion):
    w = QPushButton("toast")
    effects.slide_toast(w)      # must neither raise nor animate
    assert not hasattr(w, "_hearth_slide_group")


def test_ladder_math_is_untouched_by_the_flag(frozen_motion):
    # pure arithmetic never freezes — the widgets just choose stillness
    assert motion.shadow_for(2) == (22, 7, 132)


def test_motion_on_restores_the_choreography(qapp, monkeypatch):
    monkeypatch.setattr(config, "MOTION_ENABLED", True)
    card = QPushButton("card")
    assert effects.hover_lift(card) is not None
