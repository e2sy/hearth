"""The Sound Forge bench: EQ bands, karaoke vocal-cut, and preamp math.

Room 5.1 groundwork, cut to fit the Qt Multimedia backend. QMediaPlayer
gives Hearth no insert point in its audio path, so this module ships the
*brains* of the forge as pure math — the band table, the presets, the
mid/side karaoke filter, the preamp curve — while the plumbing splits in
two:

- **Real today**: preamp attenuation. ``effective_volume`` folds the
  preamp into the master volume the player already applies, so the
  bench tames loud masters the moment it lands.
- **Engaged when the shaped pipeline lands (v1.0)**: the ten band
  gains and the karaoke cut, consumed directly by the PCM filter that
  a push-mode audio core will run. The math is finished and tested;
  only the tap is missing.

Pure module — no Qt, no network. Every function clamps and never raises
on junk input, so a drifted settings row can't hurt playback.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field

log = logging.getLogger(__name__)

# The classic ten-band graphic EQ, in Hz. ascending on purpose — the
# panel lays sliders left (bass) to right (air) straight from this.
BAND_FREQUENCIES: tuple[int, ...] = (
    31, 62, 125, 250, 500, 1000, 2000, 4000, 8000, 16000,
)
BAND_LABELS: tuple[str, ...] = (
    "31", "62", "125", "250", "500", "1k", "2k", "4k", "8k", "16k",
)

MIN_GAIN_DB = -12.0
MAX_GAIN_DB = 12.0
MIN_PREAMP_DB = -12.0
MAX_PREAMP_DB = 6.0

# karaoke: 0.0 = untouched stereo, 1.0 = full center cut
DEFAULT_KARAOKE_STRENGTH = 0.85

PRESETS: dict[str, tuple[float, ...]] = {
    #          31    62   125   250   500    1k    2k    4k    8k   16k
    "Flat":         (0, 0, 0, 0, 0, 0, 0, 0, 0, 0),
    "Bass Boost":   (6, 5.5, 4, 2, 0, 0, 0, 0, 0, 0),
    "Vocal":        (-2, -1.5, 0, 2, 4, 4.5, 3, 1.5, 0, -1),
    "Rock":         (5, 4, 2, -1, -2, 0, 2, 4, 5, 5),
    "Electronic":   (6, 5, 1, 0, -2, 1, 1, 3, 5, 6),
    "Acoustic":     (4, 3, 1, 1.5, 2, 2.5, 2, 1, 2, 3),
    "Sleep":        (-4, -3, -2, -1, 0, -1, -2, -3, -4, -6),
    "Late Night":   (-3, -2, 0, 1, 2, 2, 1, 0, -1, -2),
}


def clamp_gain(db: float) -> float:
    """Any drift → the nearest legal band gain."""
    try:
        value = float(db)
    except (TypeError, ValueError):
        return 0.0
    if math.isnan(value) or math.isinf(value):
        return 0.0
    return max(MIN_GAIN_DB, min(MAX_GAIN_DB, value))


def clamp_preamp(db: float) -> float:
    """Any drift → the nearest legal preamp."""
    try:
        value = float(db)
    except (TypeError, ValueError):
        return 0.0
    if math.isnan(value) or math.isinf(value):
        return 0.0
    return max(MIN_PREAMP_DB, min(MAX_PREAMP_DB, value))


def db_to_linear(db: float) -> float:
    """Decibels → amplitude ratio. 0 dB is unity, -6 dB is half-ish."""
    return 10.0 ** (float(db) / 20.0)


def linear_to_db(linear: float) -> float:
    """Amplitude ratio → decibels; silence reads as the floor, not -inf."""
    linear = abs(float(linear))
    if linear <= 0.0:
        return MIN_PREAMP_DB
    return max(MIN_PREAMP_DB, min(MAX_PREAMP_DB, 20.0 * math.log10(linear)))


def effective_volume(base_volume: float, preamp_db: float) -> float:
    """The one hook that is real today: fold preamp into master volume.

    A negative preamp attenuates a hot master (the common need — taming
    normalized-loud tracks); a positive one lifts quiet sources until
    the output ceiling of 1.0 stops it. Never raises, always 0..1.
    """
    try:
        base = max(0.0, min(1.0, float(base_volume)))
    except (TypeError, ValueError):
        base = 0.8
    scaled = base * db_to_linear(clamp_preamp(preamp_db))
    return max(0.0, min(1.0, scaled))


def mute_center(samples: list[float], strength: float = 1.0) -> list[float]:
    """The karaoke cut: remove what headphones hear in the middle.

    Real mid/side math on interleaved stereo floats (L, R, L, R, …):
    the center channel is ``mid = (L+R)/2``, and vocals from a studio
    mix live almost exactly there. Each side loses ``mid * strength``:

    - dead-center content (L == R) fades to silence at strength 1.0
    - hard side content (L == -R) has no mid and survives untouched
    - strength 0.0 is a no-op, 0.85 (the default) keeps instruments
      while dimming the singer

    A stray orphan sample at the end of an odd-length buffer is passed
    through untouched. Never raises on junk numbers.
    """
    cut = max(0.0, min(1.0, float(strength)))
    if cut <= 0.0 or not samples:
        return list(samples)
    out: list[float] = []
    pairs = len(samples) // 2
    for i in range(pairs):
        left, right = samples[2 * i], samples[2 * i + 1]
        if not _finite(left) or not _finite(right):
            out.append(left)
            out.append(right)
            continue
        mid = (left + right) / 2.0
        out.append(_limit(left - mid * cut))
        out.append(_limit(right - mid * cut))
    if len(samples) % 2:
        out.append(samples[-1])
    return out


def _finite(value: float) -> bool:
    return isinstance(value, (int, float)) and math.isfinite(value)


def _limit(value: float) -> float:
    """Keep the math honest: a filter must never manufacture clipping."""
    return max(-1.0, min(1.0, value))


@dataclass
class SoundState:
    """Everything the forge bench remembers, in one clampable bundle."""

    gains: tuple[float, ...] = field(
        default_factory=lambda: tuple([0.0] * len(BAND_FREQUENCIES))
    )
    preamp_db: float = 0.0
    karaoke: bool = False
    karaoke_strength: float = DEFAULT_KARAOKE_STRENGTH

    def normalized(self) -> "SoundState":
        """A copy with every number legal — settings drift cannot pass."""
        gains = tuple(clamp_gain(g) for g in self._padded_gains())
        strength = self.karaoke_strength
        try:
            strength = max(0.0, min(1.0, float(strength)))
        except (TypeError, ValueError):
            strength = DEFAULT_KARAOKE_STRENGTH
        if not _finite(strength):
            strength = DEFAULT_KARAOKE_STRENGTH
        return SoundState(
            gains=gains,
            preamp_db=clamp_preamp(self.preamp_db),
            karaoke=bool(self.karaoke),
            karaoke_strength=strength,
        )

    def _padded_gains(self) -> list[float]:
        gains = list(self.gains or [])
        if len(gains) < len(BAND_FREQUENCIES):
            gains += [0.0] * (len(BAND_FREQUENCIES) - len(gains))
        return gains[: len(BAND_FREQUENCIES)]

    def apply_preset(self, name: str) -> bool:
        """Load a preset by name; True when one actually matched."""
        preset = PRESETS.get((name or "").strip())
        if preset is None:
            return False
        self.gains = tuple(clamp_gain(g) for g in preset)
        return True

    @classmethod
    def preset_names(cls) -> tuple[str, ...]:
        return tuple(PRESETS)

    def to_dict(self) -> dict:
        state = self.normalized()
        return {
            "gains": [round(g, 2) for g in state.gains],
            "preamp_db": round(state.preamp_db, 2),
            "karaoke": state.karaoke,
            "karaoke_strength": round(state.karaoke_strength, 3),
        }

    @classmethod
    def from_dict(cls, data: dict | None) -> "SoundState":
        """Junk in → defaults out. Never raises."""
        if not isinstance(data, dict):
            return cls()
        gains = data.get("gains")
        if not isinstance(gains, (list, tuple)):
            gains = ()
        try:
            preamp = float(data.get("preamp_db") or 0.0)
        except (TypeError, ValueError):
            preamp = 0.0
        try:
            strength = float(data.get("karaoke_strength", DEFAULT_KARAOKE_STRENGTH))
        except (TypeError, ValueError):
            strength = DEFAULT_KARAOKE_STRENGTH
        return cls(
            gains=tuple(gains),
            preamp_db=preamp,
            karaoke=bool(data.get("karaoke", False)),
            karaoke_strength=strength,
        ).normalized()


def sound_summary(state: SoundState) -> str:
    """One honest line for the status bar, e.g. 'EQ: Vocal · preamp -3 dB'."""
    state = state.normalized()
    parts: list[str] = []
    if any(abs(g) > 0.05 for g in state.gains):
        best = max(PRESETS, key=lambda name: _preset_closeness(state.gains, name))
        label = best if _preset_closeness(state.gains, best) > 0.995 else "Custom"
        parts.append(f"EQ: {label}")
    else:
        parts.append("EQ: Flat")
    if abs(state.preamp_db) > 0.05:
        parts.append(f"preamp {state.preamp_db:+.0f} dB")
    if state.karaoke:
        parts.append("karaoke on")
    return " · ".join(parts)


def _preset_closeness(gains: tuple[float, ...], name: str) -> float:
    """1.0 when the curve matches a preset exactly; decays with distance."""
    preset = PRESETS.get(name) or ()
    if not preset:
        return 0.0
    drift = sum(abs(g - p) for g, p in zip(gains, preset))
    return 1.0 / (1.0 + drift / 10.0)


__all__ = [
    "BAND_FREQUENCIES",
    "BAND_LABELS",
    "DEFAULT_KARAOKE_STRENGTH",
    "MAX_GAIN_DB",
    "MAX_PREAMP_DB",
    "MIN_GAIN_DB",
    "MIN_PREAMP_DB",
    "PRESETS",
    "SoundState",
    "clamp_gain",
    "clamp_preamp",
    "db_to_linear",
    "effective_volume",
    "linear_to_db",
    "mute_center",
    "sound_summary",
]
