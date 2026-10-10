"""The font-scale accessibility dial, pinned."""

from hearth.config import (
    FONT_SCALE_MAX,
    FONT_SCALE_MIN,
    clamp_font_scale,
    font_scale_step,
)


def test_clamp_passes_sane_values_through():
    assert clamp_font_scale(1.0) == 1.0
    assert clamp_font_scale(1.15) == 1.15
    assert clamp_font_scale("1.2") == 1.2     # settings files store strings


def test_clamp_junk_falls_back_to_one():
    assert clamp_font_scale(None) == 1.0
    assert clamp_font_scale("abc") == 1.0
    assert clamp_font_scale("") == 1.0
    assert clamp_font_scale([1]) == 1.0


def test_clamp_bounds_extremes():
    assert clamp_font_scale(99) == FONT_SCALE_MAX
    assert clamp_font_scale(-3) == FONT_SCALE_MIN
    assert clamp_font_scale(0.5) == FONT_SCALE_MIN


def test_step_moves_up_and_down():
    assert font_scale_step(1.0, 1) > 1.0
    assert font_scale_step(1.0, -1) < 1.0


def test_step_clamps_at_both_ends():
    assert font_scale_step(FONT_SCALE_MAX, 1) == FONT_SCALE_MAX
    assert font_scale_step(FONT_SCALE_MIN, -1) == FONT_SCALE_MIN


def test_step_survives_junk_current():
    # a junk stored scale coerces to 1.0, then steps normally
    assert font_scale_step("junk", 1) == font_scale_step(1.0, 1)


def test_full_walk_never_leaves_range():
    value = 1.0
    for _ in range(20):
        value = font_scale_step(value, 1)
        assert FONT_SCALE_MIN <= value <= FONT_SCALE_MAX
    for _ in range(20):
        value = font_scale_step(value, -1)
        assert FONT_SCALE_MIN <= value <= FONT_SCALE_MAX
