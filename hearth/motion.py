"""The pure lift ladder — motion arithmetic with no Qt.

The depth frame (docs/UI-DEPTH.md) says height = light + shadow. This
module is the arithmetic behind that promise: given a resting elevation
it knows the hovered and pressed elevations, the shadow tuples that sell
them, and the pacing (stagger, durations) that makes movement feel like
weight instead of wobble.

Pure data in, pure data out — `hearth/effects.py` turns these numbers
into QGraphicsDropShadowEffect calls. Nothing here may import Qt: the
pure side must stay headless-testable like every other hearth engine.
"""

from __future__ import annotations

# The elevation ladder. Level 0 rests flat on the floor; higher levels
# float closer to the light (wider, softer, lower shadows). Levels 1-4
# deliberately match the vocabulary the depth system already uses:
# card at rest, card rising, player bar, frameless floater.
LIFT_LADDER: dict[int, tuple[int, int, int]] = {
    0: (0, 0, 0),        # planted — pressed buttons sit down here
    1: (12, 4, 90),      # a card at rest (DEPTH_SHADOWS["card"])
    2: (22, 7, 132),     # a card rising toward the light
    3: (30, 10, 170),    # the player bar's hover (DEPTH_SHADOWS["bar"])
    4: (34, 12, 190),    # floaters (DEPTH_SHADOWS["float"])
}

# Choreography levels for a resting card: it rests at 1, rises to 2 on
# hover, and plants back to 0 while pressed (pushed into the floor).
LEVEL_REST = 1
LEVEL_HOVER = 2
LEVEL_PRESS = 0


def shadow_for(level: int) -> tuple[int, int, int]:
    """The shadow tuple (blur, dy, alpha) for a ladder level.

    Out-of-range levels clamp to the nearest end — motion helpers may
    overshoot during animated ramps and must never raise.
    """
    if level <= min(LIFT_LADDER):
        return LIFT_LADDER[min(LIFT_LADDER)]
    if level >= max(LIFT_LADDER):
        return LIFT_LADDER[max(LIFT_LADDER)]
    return LIFT_LADDER[int(level)]


def lerp_level(a: int, b: int, t: float) -> tuple[int, int, int]:
    """A shadow tuple between two ladder levels at progress `t` (0..1).

    `t` is clamped; ints come back (shadows take whole pixels) with a
    small floor on blur so a mid-ramp surface never looks sliced.
    """
    t = max(0.0, min(1.0, float(t)))
    sa, sb = shadow_for(a), shadow_for(b)
    blur, dy, alpha = (
        round(sa[i] + (sb[i] - sa[i]) * t) for i in range(3)
    )
    if blur and blur < 2:
        blur = 2
    return (blur, dy, alpha)


def level_for(base: int, hovered: bool, pressed: bool) -> int:
    """Which ladder level a surface should show right now.

    Pressed wins over hovered (you can press without leaving), and both
    win over the resting base. Unknown bases fall back to the rest level
    so a misconfigured widget still behaves.
    """
    if pressed:
        return LEVEL_PRESS
    if hovered:
        return LEVEL_HOVER
    if base in LIFT_LADDER:
        return base
    return LEVEL_REST


def ease_out_cubic(t: float) -> float:
    """The one easing the house uses for lifts (fast rise, soft landing)."""
    t = max(0.0, min(1.0, float(t)))
    return 1.0 - (1.0 - t) ** 3


def stagger_ms(index: int, step_ms: int = 26, cap_ms: int = 420) -> int:
    """Entrance delay for the `index`-th card in a cascade.

    Each card waits one step more than the last, but a long shelf must
    not make its tail wait forever — everything past the cap lands
    together. Negative or zero indexes start immediately.
    """
    if index <= 0:
        return 0
    return min(int(index) * int(step_ms), int(cap_ms))


# Pacing vocabulary (ms). One place to tune the whole room's tempo.
LIFT_MS = 160      # rest → hover rise
PLANT_MS = 120     # hover → press sink (quicker: you asked for it)
SETTLE_MS = 220    # hover → rest settle (slower: nothing asked for it)
FADE_MS = 150      # glyph crossfades
PULSE_MS = 1600    # one full breath of the now-playing glow

# The breathing glow: blur radius oscillates between these while a row
# is the one burning. Subtle on purpose — depth is quiet (principle 3).
PULSE_BLUR_LOW = 8
PULSE_BLUR_HIGH = 20


def pulse_blur(tick: int, low: int = PULSE_BLUR_LOW,
               high: int = PULSE_BLUR_HIGH,
               period: int = 20) -> int:
    """The glow blur for tick `tick` of a breathing pulse.

    A triangle wave over `period` ticks: out to `high` at the midpoint,
    back down to `low` at the seam. Pure and deterministic so tests can
    pin the breath exactly.
    """
    if period <= 0:
        return high
    span = max(0, int(high) - int(low))
    phase = int(tick) % int(period)
    half = period / 2.0
    frac = 1.0 - abs((phase - half) / half)
    return int(low) + round(span * max(0.0, min(1.0, frac)))


def swap_phase(icon_a: bool, icon_b: bool) -> str:
    """Which glyph a crossfading toggle should show.

    Tiny pure kernel behind the play/pause crossfade: exactly one icon
    is ever true. Both or neither is a caller bug — the safer glyph wins
    (play, i.e. 'a') so a broken state can never blink at the user.
    """
    if icon_a == icon_b:
        return "a"
    return "a" if icon_a else "b"


__all__ = [
    "LIFT_LADDER", "LEVEL_REST", "LEVEL_HOVER", "LEVEL_PRESS",
    "shadow_for", "lerp_level", "level_for", "ease_out_cubic",
    "stagger_ms", "LIFT_MS", "PLANT_MS", "SETTLE_MS", "FADE_MS",
    "PULSE_MS", "PULSE_BLUR_LOW", "PULSE_BLUR_HIGH", "pulse_blur",
    "swap_phase",
]
