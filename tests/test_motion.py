"""The pure lift ladder, pinned.

hearth/motion.py is the arithmetic behind every hover lift, press sink,
entrance cascade and breathing glow in the app. These tests hold the
numbers still so the widgets can dance.
"""

import pytest

from hearth import motion


# ------------------------------------------------------------- the ladder

def test_ladder_has_five_levels_from_floor_to_float():
    assert sorted(motion.LIFT_LADDER) == [0, 1, 2, 3, 4]


def test_level_zero_is_planted():
    assert motion.LIFT_LADDER[0] == (0, 0, 0)


def test_level_one_matches_the_card_rest_shadow():
    # DEPTH_SHADOWS["card"] is (12, 4, 90) — the ladder must agree.
    assert motion.LIFT_LADDER[1] == (12, 4, 90)


def test_level_four_matches_the_float_shadow():
    assert motion.LIFT_LADDER[4] == (34, 12, 190)


def test_shadows_grow_softer_and_lower_with_height():
    # Higher elevation = wider blur, bigger drop, stronger alpha.
    for low, high in ((0, 1), (1, 2), (2, 3), (3, 4)):
        assert motion.LIFT_LADDER[high][0] > motion.LIFT_LADDER[low][0]
        assert motion.LIFT_LADDER[high][1] > motion.LIFT_LADDER[low][1]
        assert motion.LIFT_LADDER[high][2] > motion.LIFT_LADDER[low][2]


def test_shadow_for_clamps_out_of_range_levels():
    assert motion.shadow_for(-7) == motion.LIFT_LADDER[0]
    assert motion.shadow_for(99) == motion.LIFT_LADDER[4]


# ------------------------------------------------------------ transitions

def test_lerp_level_endpoints_are_exact():
    assert motion.lerp_level(1, 2, 0.0) == motion.LIFT_LADDER[1]
    assert motion.lerp_level(1, 2, 1.0) == motion.LIFT_LADDER[2]


def test_lerp_level_midpoint_sits_between():
    blur, dy, alpha = motion.lerp_level(1, 2, 0.5)
    assert motion.LIFT_LADDER[1][0] <= blur <= motion.LIFT_LADDER[2][0]
    assert motion.LIFT_LADDER[1][1] <= dy <= motion.LIFT_LADDER[2][1]
    assert motion.LIFT_LADDER[1][2] <= alpha <= motion.LIFT_LADDER[2][2]


def test_lerp_level_clamps_t():
    assert motion.lerp_level(0, 4, -2.0) == motion.LIFT_LADDER[0]
    assert motion.lerp_level(0, 4, 5.0) == motion.LIFT_LADDER[4]


def test_lerp_level_keeps_midramp_blur_off_zero():
    # A mid-ramp surface must never look sliced: blur floors at 2.
    blur, _dy, _alpha = motion.lerp_level(0, 1, 0.05)
    assert blur == 0 or blur >= 2   # only the true endpoints may be 0
    assert blur >= 2


def test_level_for_press_beats_hover_beats_rest():
    assert motion.level_for(1, hovered=False, pressed=False) == 1
    assert motion.level_for(1, hovered=True, pressed=False) == motion.LEVEL_HOVER
    assert motion.level_for(1, hovered=True, pressed=True) == motion.LEVEL_PRESS


def test_level_for_unknown_base_falls_back_to_rest():
    assert motion.level_for(37, hovered=False, pressed=False) == motion.LEVEL_REST


# ---------------------------------------------------------------- pacing

def test_ease_out_cubic_endpoints_and_direction():
    assert motion.ease_out_cubic(0.0) == 0.0
    assert motion.ease_out_cubic(1.0) == 1.0
    assert motion.ease_out_cubic(0.5) > 0.5     # fast rise, soft landing
    assert motion.ease_out_cubic(-1.0) == 0.0
    assert motion.ease_out_cubic(2.0) == 1.0


def test_stagger_starts_at_zero():
    assert motion.stagger_ms(0) == 0
    assert motion.stagger_ms(-3) == 0


def test_stagger_steps_linearly_then_caps():
    assert motion.stagger_ms(1, step_ms=26) == 26
    assert motion.stagger_ms(2, step_ms=26) == 52
    assert motion.stagger_ms(100, step_ms=26, cap_ms=420) == 420


def test_pulse_breath_is_a_triangle_wave():
    lows, highs = [], []
    for tick in range(20):
        value = motion.pulse_blur(tick)
        if value == motion.PULSE_BLUR_LOW:
            lows.append(tick)
        if value == motion.PULSE_BLUR_HIGH:
            highs.append(tick)
    assert lows[0] == 0                    # starts settled
    assert highs == [10]                   # one crest per period
    assert motion.pulse_blur(20) == motion.PULSE_BLUR_LOW   # seamless loop


def test_pulse_blur_custom_range_and_period():
    assert motion.pulse_blur(0, low=2, high=10, period=8) == 2
    assert motion.pulse_blur(4, low=2, high=10, period=8) == 10
    assert motion.pulse_blur(7, low=2, high=10, period=8) in (3, 4)


def test_pulse_blur_degenerate_period_returns_high():
    assert motion.pulse_blur(3, period=0) == motion.PULSE_BLUR_HIGH


# ------------------------------------------------------------ glyph swap

def test_swap_phase_exact_one_true_shows_that_one():
    assert motion.swap_phase(True, False) == "a"
    assert motion.swap_phase(False, True) == "b"


def test_swap_phase_broken_state_falls_to_play_glyph():
    assert motion.swap_phase(True, True) == "a"
    assert motion.swap_phase(False, False) == "a"


def test_pacing_vocabulary_is_sane():
    # Presses answer faster than lifts; settles relax slowest.
    assert 0 < motion.PLANT_MS < motion.LIFT_MS < motion.SETTLE_MS
    assert motion.PULSE_MS > 1000        # a breath, not a flicker
    assert 0 < motion.FADE_MS < motion.LIFT_MS


@pytest.mark.parametrize("fn", [
    lambda: motion.shadow_for(2),
    lambda: motion.lerp_level(1, 2, 0.5),
    lambda: motion.level_for(1, True, False),
    lambda: motion.stagger_ms(5),
    lambda: motion.pulse_blur(5),
    lambda: motion.ease_out_cubic(0.3),
    lambda: motion.swap_phase(True, False),
])
def test_pure_kernels_never_raise(fn):
    assert fn() is not None or True
