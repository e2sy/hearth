"""The Sound Forge bench: EQ math, karaoke cut, preamp, persistence."""

import math

import pytest

from hearth import sound_shape
from hearth.sound_shape import (
    BAND_FREQUENCIES,
    MAX_GAIN_DB,
    MAX_PREAMP_DB,
    MIN_GAIN_DB,
    MIN_PREAMP_DB,
    PRESETS,
    SoundState,
    clamp_gain,
    clamp_preamp,
    db_to_linear,
    effective_volume,
    linear_to_db,
    mute_center,
    sound_summary,
)
from hearth.storage import HearthStore


# --- the band table -------------------------------------------------------


def test_band_table_is_the_classic_ten():
    assert len(BAND_FREQUENCIES) == 10
    assert BAND_FREQUENCIES == tuple(sorted(BAND_FREQUENCIES))   # ascending
    assert BAND_FREQUENCIES[0] == 31 and BAND_FREQUENCIES[-1] == 16000


def test_every_preset_shapes_the_full_table():
    for name, gains in PRESETS.items():
        assert len(gains) == 10, name
        for g in gains:
            assert MIN_GAIN_DB <= g <= MAX_GAIN_DB, name


# --- clamps and conversions ------------------------------------------------


def test_clamp_gain_pulls_drift_inside_the_rails():
    assert clamp_gain(-99) == MIN_GAIN_DB
    assert clamp_gain(99) == MAX_GAIN_DB
    assert clamp_gain(3.5) == 3.5
    assert clamp_gain("junk") == 0.0
    assert clamp_gain(float("nan")) == 0.0


def test_clamp_preamp_uses_its_own_rails():
    assert clamp_preamp(-99) == MIN_PREAMP_DB
    assert clamp_preamp(99) == MAX_PREAMP_DB
    assert clamp_preamp("junk") == 0.0


def test_db_linear_roundtrip():
    assert db_to_linear(0.0) == pytest.approx(1.0)
    assert db_to_linear(-6.0) == pytest.approx(0.5012, rel=1e-3)
    assert linear_to_db(db_to_linear(3.0)) == pytest.approx(3.0, rel=1e-6)
    assert linear_to_db(0.0) == MIN_PREAMP_DB     # silence reads as the floor


def test_effective_volume_attenuates_a_hot_master():
    # -6 dB preamp on 0.8 volume ≈ 0.4 — the "tame loud masters" case
    assert effective_volume(0.8, -6.0) == pytest.approx(0.401, rel=0.02)
    assert effective_volume(0.8, 0.0) == pytest.approx(0.8)


def test_effective_volume_never_exits_0_1_and_never_raises():
    assert effective_volume(1.0, 12.0) == 1.0        # ceiling stops the lift
    assert effective_volume(0.5, -12.0) >= 0.0
    assert effective_volume("junk", None) <= 1.0     # junk base → default 0.8
    assert effective_volume(0.8, "junk") == pytest.approx(0.8)  # junk preamp → 0 dB


# --- the SoundState bundle --------------------------------------------------


def test_state_defaults_are_flat_and_normalized():
    state = SoundState().normalized()
    assert len(state.gains) == 10
    assert all(g == 0.0 for g in state.gains)
    assert state.preamp_db == 0.0
    assert state.karaoke is False


def test_state_preset_switch_loads_the_curve():
    state = SoundState()
    assert state.apply_preset("Bass Boost") is True
    assert state.gains[0] > 0                      # the low end lifts
    assert state.apply_preset("no such preset") is False
    assert state.gains[0] > 0                      # a failed load changes nothing


def test_state_roundtrips_through_its_dict():
    state = SoundState(gains=(3, -2, 0, 1, 0, 0, 0, 0, 0, 2),
                       preamp_db=-3.0, karaoke=True, karaoke_strength=0.7)
    clone = SoundState.from_dict(state.to_dict())
    assert clone == state.normalized()


def test_state_from_dict_junk_lands_on_defaults():
    for junk in (None, "nope", 42, {"gains": "junk"}, {"preamp_db": "oops"}):
        state = SoundState.from_dict(junk)
        assert len(state.gains) == 10
        assert state.preamp_db == 0.0


def test_state_normalization_clamps_hostile_rows():
    state = SoundState(gains=(99, -99, 0, 0, 0, 0, 0, 0, 0, 0),
                       preamp_db=55, karaoke_strength=7)
    clean = state.normalized()
    assert clean.gains[0] == MAX_GAIN_DB
    assert clean.gains[1] == MIN_GAIN_DB
    assert clean.preamp_db == MAX_PREAMP_DB
    assert clean.karaoke_strength == 1.0


def test_summary_speaks_plainly():
    flat = sound_summary(SoundState())
    assert "Flat" in flat and "karaoke" not in flat
    state = SoundState()
    state.apply_preset("Vocal")
    state.preamp_db = -3
    state.karaoke = True
    text = sound_summary(state)
    assert "preamp -3 dB" in text and "karaoke on" in text


# --- the karaoke cut (real mid/side math) -----------------------------------


def test_karaoke_kills_a_dead_center_vocal():
    # L == R: the classic studio-center vocal → silence at full strength
    out = mute_center([0.5, 0.5], strength=1.0)
    assert out == [0.0, 0.0]


def test_karaoke_spares_hard_side_content():
    # L == -R: pure side (panned wide) — mid is zero, nothing is removed
    frame = [0.5, -0.5]
    assert mute_center(frame, strength=1.0) == pytest.approx(frame)


def test_karaoke_strength_zero_is_a_noop_and_blends_between():
    frame = [0.6, 0.2]
    assert mute_center(frame, strength=0.0) == pytest.approx(frame)
    mid = (0.6 + 0.2) / 2
    out = mute_center(frame, strength=0.5)
    assert out[0] == pytest.approx(0.6 - mid * 0.5)
    assert out[1] == pytest.approx(0.2 - mid * 0.5)


def test_karaoke_runs_a_whole_song_without_inventing_clip():
    frames = [0.9 * ((-1) ** i) * (1 - i % 3) for i in range(1000)]
    out = mute_center(frames, strength=0.85)
    assert len(out) == len(frames)
    assert all(-1.0 <= v <= 1.0 for v in out)


def test_karaoke_survives_odd_length_and_garbage():
    out = mute_center([0.4, 0.4, 0.123], strength=1.0)   # orphan passes through
    assert out[2] == 0.123
    assert mute_center([], strength=1.0) == []
    out = mute_center([float("nan"), 0.2], strength=1.0)
    assert math.isnan(out[0])        # garbage in passes through, never crashes
    assert out[1] == 0.2


# --- persistence ------------------------------------------------------------


def test_sound_settings_roundtrip(tmp_path):
    store = HearthStore(tmp_path / "hearth.db")
    assert store.sound_settings() == {}          # nothing saved yet
    state = SoundState()
    state.apply_preset("Rock")
    state.preamp_db = -2.5
    store.save_sound_settings(state.to_dict())
    loaded = SoundState.from_dict(store.sound_settings())
    assert loaded.gains == state.gains
    assert loaded.preamp_db == -2.5


def test_sound_settings_second_save_replaces_the_first(tmp_path):
    store = HearthStore(tmp_path / "hearth.db")
    store.save_sound_settings({"preamp_db": -1})
    store.save_sound_settings({"preamp_db": -4, "karaoke": True})
    data = store.sound_settings()
    assert data["preamp_db"] == -4 and data["karaoke"] is True
