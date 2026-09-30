"""The ambient mixer: procedural campfire, café & rain, mixed under the music.

Zero assets, zero dependencies. Every sound is synthesized sample-by-
sample with struct/math/random into 16-bit mono PCM at 22050 Hz and fed
to its own QAudioSink — the music's player path is never touched, the
ambience simply burns quieter underneath it.

Two layers live here:

- AmbientGenerator: pure, deterministic, Qt-free DSP. Campfire is a
  brown-noise bed (leaky integrator) with random crackle pops
  (Poisson-ish arrivals, sharp attack, exponential decay, snapped by a
  one-pole high-pass). Rain is a filtered noise bed (one-pole low-pass
  whose cutoff wanders), occasional droplet plinks, and a distant
  rumble — a heavy low-pass plus a slow LFO breathing on the gain.
  Café is a murmur bed (brown noise softened by a wandering low-pass),
  a babble layer (low-passed white noise behind three slow, coprime
  swells that never quite loop), and occasional cup clinks — tiny
  decaying sines that sometimes get a saucer answer a beat later.
- AmbientChannel: the thin Qt wrapper — a QAudioSink in push mode fed
  by a QTimer, with its own level dial (0..1). Audio-device absence is
  a silent no-op: `start` returns False so the caller can post a status
  note instead (offscreen CI has no speakers, and that is fine).

Only one soundscape plays at a time; starting a new one releases the
old sink completely. `fill` is chunk-transparent — all DSP state is
per-sample, so pulling one big chunk or many small ones sounds the same.
"""

from __future__ import annotations

import math
import random
import struct

from PyQt6.QtCore import QTimer

from . import config

SAMPLE_RATE = 22050   # small + light: a bed of sound needs no fidelity
CHANNELS = 1          # mono — ambience, not a stage
SAMPLE_WIDTH = 2      # bytes per frame: 16-bit little-endian
KINDS = ("campfire", "cafe", "rain")

# --- campfire: brown-noise bed (leaky integrator) ---
_CAMP_BROWN_INC = 0.02     # integrator input gain
_CAMP_BROWN_LEAK = 0.9998  # per-sample leak (long memory = deep rumble)
_CAMP_BROWN_LEVEL = 0.55   # bed loudness after the integrator
# --- campfire: crackle pops ---
_CAMP_POP_RATE = 9.0       # expected pops per second (Poisson-ish)
_CAMP_POP_DECAY = 0.9975   # per-sample exponential decay of a pop
_CAMP_POP_HP = 0.90        # one-pole high-pass: the "snap" of the snap
_CAMP_POP_LEVEL = 1.5

# --- rain: filtered noise bed with a wandering cutoff ---
_RAIN_ALPHA_BASE = 0.12    # one-pole low-pass coefficient (bed tone)
_RAIN_ALPHA_WANDER = 0.08  # how far the cutoff breathes either way
_RAIN_WANDER_HZ = 0.07     # cutoff wander rate
_RAIN_BED_LEVEL = 2.2
# --- rain: droplet plinks (tiny decaying sines) ---
_RAIN_DROP_RATE = 2.5      # expected droplets per second
_RAIN_DROP_DECAY = 0.9982
_RAIN_DROP_LEVEL = 0.55
# --- rain: distant rumble (heavy low-pass + slow gain LFO) ---
_RAIN_RUMBLE_ALPHA = 0.004
_RAIN_RUMBLE_LEVEL = 2.5
_RAIN_LFO_HZ = 0.13        # the room "breathes" every ~8 seconds
_RAIN_LFO_DEPTH = 0.15     # gain swings 0.85 ± 0.15

# --- café: murmur bed (brown noise softened by a wandering low-pass) ---
_CAFE_MURMUR_INC = 0.05     # integrator input gain (gentler than campfire)
_CAFE_MURMUR_LEAK = 0.9995  # per-sample leak (shorter memory = closer room)
_CAFE_MURMUR_ALPHA = 0.10   # one-pole low-pass on the brown bed
_CAFE_MURMUR_WANDER = 0.04  # how far the low-pass breathes either way
_CAFE_MURMUR_LEVEL = 1.6
# --- café: voice babble (low-passed white behind three slow swells) ---
_CAFE_BABBLE_ALPHA = 0.22   # low-pass tone: softer than the murmur bed
_CAFE_BABBLE_LEVEL = 0.9
_CAFE_SWELL_HZ_A = 0.051    # three coprime-ish swells: the room never loops
_CAFE_SWELL_HZ_B = 0.083
_CAFE_SWELL_HZ_C = 0.127
# --- café: cup clinks (tiny decaying sines, sometimes a saucer answer) ---
_CAFE_CLINK_RATE = 0.9      # expected clinks per second (a slow morning)
_CAFE_CLINK_DECAY = 0.9955
_CAFE_CLINK_LEVEL = 0.35
_CAFE_CLINK_ECHO_CHANCE = 0.3
# --- café: the room breathes (slow gain LFO, like every real room) ---
_CAFE_BREATH_HZ = 0.09
_CAFE_BREATH_DEPTH = 0.12   # gain swings 0.9 ± 0.12


class AmbientGenerator:
    """A deterministic procedural soundscape (22050 Hz / 16-bit / mono).

    Pure Python — no Qt, no numpy, no assets. Given the same seed, two
    generators produce identical PCM forever; given no seed, the
    soundscape is unique each time. Unknown kinds raise ValueError at
    construction (the only way in which this class is allowed to be
    noisy — every later failure is the caller's geometry, clamped).
    """

    def __init__(self, kind: str, seed: int | None = None):
        if kind not in KINDS:
            raise ValueError(f"unknown ambient kind: {kind!r} (have {KINDS})")
        self.kind = kind
        self._rng = random.Random(seed)
        self._pos = 0                                   # absolute sample clock
        self._lfo_phase = self._rng.uniform(0.0, 2.0 * math.pi)
        if kind == "campfire":
            self._brown = 0.0     # leaky-integrator state
            self._pop_env = 0.0   # envelope of the crackle in flight
            self._hp = 0.0        # one-pole high-pass memory
            self._hp_prev_in = 0.0
            self._next_sample = self._campfire_sample
        elif kind == "cafe":
            self._brown = 0.0        # murmur integrator state
            self._bed = 0.0          # wandering low-pass over the murmur
            self._babble = 0.0       # low-passed white (the voices)
            self._clink_env = 0.0    # cup clink in flight (0 = none)
            self._clink_freq = 0.0
            self._clink_phase = 0.0
            self._clink_echo = False  # a saucer answer is pending
            self._next_sample = self._cafe_sample
        else:
            self._bed = 0.0       # wandering low-pass state
            self._rumble = 0.0    # heavy low-pass state (distant thunder)
            self._drop_env = 0.0  # droplet plink in flight (0 = none)
            self._drop_freq = 0.0
            self._drop_phase = 0.0
            self._next_sample = self._rain_sample

    @property
    def frames_written(self) -> int:
        return self._pos

    def fill(self, buf: memoryview | bytearray, frames: int) -> int:
        """Write `frames` mono 16-bit samples into buf (little-endian).

        Returns the frames actually written — never more than the
        buffer holds (len(buf) // 2), and never raises on odd geometry.
        Chunk-transparent: 3 x fill(1600) equals one fill(4800).
        """
        if frames < 0:
            frames = 0
        frames = min(frames, len(buf) // SAMPLE_WIDTH)
        for i in range(frames):
            s = self._next_sample()
            struct.pack_into("<h", buf, i * SAMPLE_WIDTH, int(s * 32767.0))
        return frames

    # --- per-sample DSP (state lives only in these floats + the rng) ---

    def _campfire_sample(self) -> float:
        self._pos += 1
        rng = self._rng
        # brown-noise bed: a leaky integrator over white noise
        self._brown = (self._brown * _CAMP_BROWN_LEAK
                       + _CAMP_BROWN_INC * rng.uniform(-1.0, 1.0))
        # crackle pops: Poisson-ish arrivals, sharp attack, exp decay
        if rng.random() < _CAMP_POP_RATE / SAMPLE_RATE:
            self._pop_env = rng.uniform(0.5, 1.0)
        else:
            self._pop_env *= _CAMP_POP_DECAY
        burst = self._pop_env * rng.uniform(-1.0, 1.0)
        # bandpass-ish shaping: one-pole high-pass makes the crackle snap
        hp = _CAMP_POP_HP * (self._hp + burst - self._hp_prev_in)
        self._hp = hp
        self._hp_prev_in = burst
        s = self._brown * _CAMP_BROWN_LEVEL + hp * _CAMP_POP_LEVEL
        return 1.0 if s > 1.0 else (-1.0 if s < -1.0 else s)

    def _cafe_sample(self) -> float:
        self._pos += 1
        rng = self._rng
        white = rng.uniform(-1.0, 1.0)
        t = self._pos / SAMPLE_RATE
        # murmur bed: brown noise softened by a low-pass whose cutoff
        # wanders with the second swell — the room never sits still
        self._brown = (self._brown * _CAFE_MURMUR_LEAK
                       + _CAFE_MURMUR_INC * rng.uniform(-1.0, 1.0))
        alpha = _CAFE_MURMUR_ALPHA + _CAFE_MURMUR_WANDER * math.sin(
            2.0 * math.pi * _CAFE_SWELL_HZ_B * t + self._lfo_phase)
        self._bed += alpha * (self._brown - self._bed)
        # voice babble: low-passed white noise behind three slow swells —
        # conversations you can't quite make out, rising and falling
        self._babble += _CAFE_BABBLE_ALPHA * (white - self._babble)
        swell = (1.0
                 + math.sin(2.0 * math.pi * _CAFE_SWELL_HZ_A * t
                            + self._lfo_phase)
                 + math.sin(2.0 * math.pi * _CAFE_SWELL_HZ_B * t * 1.7 + 1.3)
                 + math.sin(2.0 * math.pi * _CAFE_SWELL_HZ_C * t + 2.6)) / 4.0
        babble = self._babble * max(0.15, swell)
        # cup clinks: occasional tiny sines; some get a saucer answer a
        # beat later at a slightly different pitch (same envelope trick
        # as the rain plinks, but rarer, lower level, and conversational)
        if self._clink_env <= 0.0:
            if rng.random() < _CAFE_CLINK_RATE / SAMPLE_RATE:
                self._clink_env = rng.uniform(0.5, 1.0)
                self._clink_freq = rng.uniform(1400.0, 3200.0)
                self._clink_phase = 0.0
                self._clink_echo = (rng.random() < _CAFE_CLINK_ECHO_CHANCE)
        else:
            self._clink_phase += 2.0 * math.pi * self._clink_freq / SAMPLE_RATE
            self._clink_env *= _CAFE_CLINK_DECAY
            if self._clink_env < 0.01:
                if self._clink_echo:
                    self._clink_echo = False       # the saucer answers
                    self._clink_env = 0.6
                    self._clink_freq *= rng.uniform(0.9, 1.1)
                else:
                    self._clink_env = 0.0
        clink = (self._clink_env * math.sin(self._clink_phase)
                 if self._clink_env > 0.0 else 0.0)
        # the room breathes: one slow LFO on the overall gain
        gain = 0.9 + _CAFE_BREATH_DEPTH * math.sin(
            2.0 * math.pi * _CAFE_BREATH_HZ * t + self._lfo_phase)
        s = ((self._bed * _CAFE_MURMUR_LEVEL
              + babble * _CAFE_BABBLE_LEVEL
              + clink * _CAFE_CLINK_LEVEL) * gain)
        return 1.0 if s > 1.0 else (-1.0 if s < -1.0 else s)

    def _rain_sample(self) -> float:
        self._pos += 1
        rng = self._rng
        white = rng.uniform(-1.0, 1.0)
        t = self._pos / SAMPLE_RATE
        # noise bed: one-pole low-pass whose cutoff wanders slowly
        alpha = _RAIN_ALPHA_BASE + _RAIN_ALPHA_WANDER * math.sin(
            2.0 * math.pi * _RAIN_WANDER_HZ * t + self._lfo_phase)
        self._bed += alpha * (white - self._bed)
        # distant rumble: the same white through a much heavier low-pass
        self._rumble += _RAIN_RUMBLE_ALPHA * (white - self._rumble)
        # droplet plinks: occasional tiny decaying sines
        if self._drop_env <= 0.0:
            if rng.random() < _RAIN_DROP_RATE / SAMPLE_RATE:
                self._drop_env = rng.uniform(0.6, 1.0)
                self._drop_freq = rng.uniform(1800.0, 5200.0)
                self._drop_phase = 0.0
        else:
            self._drop_phase += 2.0 * math.pi * self._drop_freq / SAMPLE_RATE
            self._drop_env *= _RAIN_DROP_DECAY
            if self._drop_env < 0.01:
                self._drop_env = 0.0
        drop = (self._drop_env * math.sin(self._drop_phase)
                if self._drop_env > 0.0 else 0.0)
        # the distant rumble LFO: a slow breath on the overall gain
        gain = 0.85 + _RAIN_LFO_DEPTH * math.sin(
            2.0 * math.pi * _RAIN_LFO_HZ * t + self._lfo_phase)
        s = (self._bed * gain * _RAIN_BED_LEVEL
             + self._rumble * _RAIN_RUMBLE_LEVEL
             + drop * _RAIN_DROP_LEVEL)
        return 1.0 if s > 1.0 else (-1.0 if s < -1.0 else s)


def scale_chunk(buf: memoryview | bytearray, level: float) -> None:
    """Scale a 16-bit mono chunk in place by `level` (clamped to 0..1).

    The channel's loudness lives here rather than in QAudioSink volume
    so the dial is exact regardless of backend quirks.
    """
    if level >= 1.0:
        return
    if level < 0.0:
        level = 0.0
    for i in range(len(buf) // SAMPLE_WIDTH):
        v, = struct.unpack_from("<h", buf, i * SAMPLE_WIDTH)
        struct.pack_into("<h", buf, i * SAMPLE_WIDTH, int(v * level))


def _audio_format():
    """The QAudioFormat the sink is opened with (lazy QtMultimedia import)."""
    from PyQt6.QtMultimedia import QAudioFormat

    fmt = QAudioFormat()
    fmt.setSampleRate(SAMPLE_RATE)
    fmt.setChannelCount(CHANNELS)
    fmt.setSampleFormat(QAudioFormat.SampleFormat.Int16)
    return fmt


def _default_output():
    """The default audio output device, or None when Qt cannot offer one."""
    try:
        from PyQt6.QtMultimedia import QMediaDevices

        return QMediaDevices.defaultAudioOutput()
    except Exception:  # noqa: BLE001 - no multimedia module: no audio
        return None


class AmbientChannel:
    """One QAudioSink dedicated to ambience — independent of the music.

    Push mode: a QTimer generates ~100 ms PCM chunks and writes them
    into the sink's internal QIODevice. `start` never raises: without
    an audio device (offscreen CI) it is a silent no-op returning False
    so the caller can post a status note instead. `stop` fully releases
    the device — no timer, no sink, no dangling QIODevice.

    Tests: pass `sink_factory(fmt) -> sink-like`. The fake protocol is
    start() -> QIODevice-like | None, stop(), error() -> QAudio.Error,
    setVolume(). A non-sink or a failed open is a quiet False, never an
    exception.
    """

    def __init__(self, parent=None, sink_factory=None):
        self._sink_factory = sink_factory
        self._sink = None
        self._io = None
        self._gen: AmbientGenerator | None = None
        self._level = float(config.AMBIENT_DEFAULT_LEVEL)
        self._timer = QTimer(parent) if parent is not None else QTimer()
        self._timer.setInterval(config.AMBIENT_TICK_MS)
        self._timer.timeout.connect(self._tick)

    @property
    def active(self) -> bool:
        return self._sink is not None

    @property
    def kind(self) -> str | None:
        return self._gen.kind if self._gen is not None else None

    @property
    def level(self) -> float:
        return self._level

    def start(self, kind: str, seed: int | None = None) -> bool:
        """Begin a soundscape. True only when audio actually opened."""
        self.stop()  # switching kinds releases the old soundscape first
        try:
            gen = AmbientGenerator(kind, seed)
        except ValueError:
            return False
        try:
            sink = self._make_sink()
        except Exception:  # noqa: BLE001 - no backend: stay a silent no-op
            sink = None
        if sink is None:
            return False
        io = sink.start()
        if io is None or sink.error() != _no_error():
            try:
                sink.stop()
            except Exception:  # noqa: BLE001 - a dying sink is quiet
                pass
            return False
        self._gen = gen
        self._sink = sink
        self._io = io
        self._timer.start()
        return True

    def stop(self) -> None:
        """Release everything: timer off, sink stopped, refs dropped."""
        self._timer.stop()
        sink, self._sink = self._sink, None
        self._io = None
        self._gen = None
        if sink is not None:
            try:
                sink.stop()
            except Exception:  # noqa: BLE001 - a dying sink must not sting
                pass

    def set_level(self, level: float) -> None:
        """Dial the ambience (0..1, clamped). Junk input is ignored."""
        try:
            level = float(level)
        except (TypeError, ValueError):
            return
        self._level = 1.0 if level > 1.0 else (0.0 if level < 0.0 else level)

    # --- internals ---

    def _make_sink(self):
        """A fresh sink (or None when no device / the factory declines)."""
        if self._sink_factory is not None:
            return self._sink_factory(_audio_format())
        from PyQt6.QtMultimedia import QAudioSink

        device = _default_output()
        if device is None or device.isNull():
            return None
        return QAudioSink(device, _audio_format())

    def _tick(self) -> None:
        """One pull cadence: generate, scale by level, write."""
        if self._sink is None or self._io is None or self._gen is None:
            self._timer.stop()
            return
        frames = SAMPLE_RATE * self._timer.interval() // 1000
        buf = bytearray(frames * SAMPLE_WIDTH)
        self._gen.fill(buf, frames)
        scale_chunk(buf, self._level)
        try:
            self._io.write(bytes(buf))
        except Exception:  # noqa: BLE001 - device vanished mid-stream: stop quietly
            self.stop()


def _no_error():
    """QAudio.Error.NoError, resolved lazily like the rest of the sink."""
    from PyQt6.QtMultimedia import QAudio

    return QAudio.Error.NoError
