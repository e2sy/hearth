"""Ambient mixer, i18n scaffold, last.fm groundwork, packaging manifests
(31-c5c) — the generator is pure deterministic DSP (no Qt needed for
its tests), the channel rides a fake sink so no audio hardware is
required, and everything else is offline by design."""

import hashlib
import json
import struct
from pathlib import Path

import pytest
from PyQt6.QtMultimedia import QAudio, QAudioDevice, QAudioFormat

import hearth
from hearth import ambient as amb
from hearth import config, i18n, scrobble
from hearth.ambient import AmbientChannel, AmbientGenerator, scale_chunk

from .test_app_smoke import make_hearth
from .test_models import make_track

PACKAGING_DIR = Path(hearth.__file__).resolve().parent.parent / "packaging"


# ----------------------------------------------------------------- fake sink

class FakeIO:
    def __init__(self):
        self.chunks: list[bytes] = []

    def write(self, data) -> int:
        self.chunks.append(bytes(data))
        return len(data)


class FakeSink:
    """The AmbientChannel sink protocol: start/stop/error/setVolume."""

    def __init__(self, fail_open: bool = False):
        self.io = FakeIO()
        self.fail_open = fail_open
        self.stopped = False
        self.volumes: list[float] = []

    def start(self):
        return None if self.fail_open else self.io

    def stop(self):
        self.stopped = True

    def error(self):
        return QAudio.Error.OpenError if self.fail_open else QAudio.Error.NoError

    def setVolume(self, v) -> None:  # noqa: N802 - Qt's name
        self.volumes.append(v)


def fake_channel(sink=None, **kwargs) -> tuple[AmbientChannel, list[FakeSink]]:
    """A channel with a fake sink factory; returns (channel, sinks made)."""
    made: list[FakeSink] = []

    def factory(_fmt: QAudioFormat) -> FakeSink:
        s = sink if sink is not None else FakeSink()
        made.append(s)
        return s

    return AmbientChannel(parent=None, sink_factory=factory), made


def samples_of(buf) -> list[int]:
    n = len(buf) // amb.SAMPLE_WIDTH
    return list(struct.unpack_from(f"<{n}h", buf, 0))


# ----------------------------------------------------------------- generator

def test_generator_rejects_unknown_kind_and_lists_kinds():
    with pytest.raises(ValueError):
        AmbientGenerator("blizzard")
    assert set(amb.KINDS) == {"campfire", "cafe", "rain"}


@pytest.mark.parametrize("kind", ["campfire", "cafe", "rain"])
def test_generator_deterministic_given_seed(kind):
    other = "rain" if kind == "campfire" else "campfire"
    a, b = AmbientGenerator(kind, seed=7), AmbientGenerator(kind, seed=7)
    c, d = AmbientGenerator(other, seed=7), AmbientGenerator(kind, seed=99)
    bufs = [bytearray(4096 * amb.SAMPLE_WIDTH) for _ in range(4)]
    for g, buf in zip((a, b, c, d), bufs):
        g.fill(buf, 4096)
        g.fill(buf, 2048)  # a second pull keeps the state machine rolling
    assert bytes(bufs[0]) == bytes(bufs[1])          # same seed = same PCM
    assert bytes(bufs[0]) != bytes(bufs[3])          # different seed differs
    assert bytes(bufs[0]) != bytes(bufs[2])          # kinds sound different


@pytest.mark.parametrize("kind", ["campfire", "rain"])
def test_generator_fill_is_chunk_transparent(kind):
    # fill() writes from the buffer's start; successive chunks land at
    # successive offsets through a memoryview (exactly how the channel
    # could pull them, and proof the DSP state is per-sample).
    one = AmbientGenerator(kind, seed=11)
    many = AmbientGenerator(kind, seed=11)
    big = bytearray(4800 * amb.SAMPLE_WIDTH)
    one.fill(big, 4800)
    small = bytearray(4800 * amb.SAMPLE_WIDTH)
    view = memoryview(small)
    for off in range(0, 4800, 1600):
        assert many.fill(view[off * amb.SAMPLE_WIDTH:], 1600) == 1600
    assert bytes(big) == bytes(small)


@pytest.mark.parametrize("kind", ["campfire", "rain"])
def test_generator_fill_respects_buffer_geometry(kind):
    gen = AmbientGenerator(kind, seed=3)
    tiny = bytearray(10 * amb.SAMPLE_WIDTH)
    assert gen.fill(tiny, 1000) == 10          # clamped to capacity, no raise
    assert gen.fill(tiny, 0) == 0
    assert gen.fill(tiny, -5) == 0
    odd = bytearray(1)                          # half a frame: nothing fits
    assert gen.fill(odd, 4) == 0 and bytes(odd) == b"\x00"
    empty = bytearray(4 * amb.SAMPLE_WIDTH)
    assert gen.fill(empty, 4) == 4
    assert any(v != 0 for v in samples_of(empty))   # real audio was written


@pytest.mark.parametrize("kind", ["campfire", "rain"])
def test_generator_output_is_valid_int16_mono(kind):
    gen = AmbientGenerator(kind, seed=42)
    seconds = 2
    buf = bytearray(amb.SAMPLE_RATE * seconds * amb.SAMPLE_WIDTH)
    assert gen.fill(buf, amb.SAMPLE_RATE * seconds) == amb.SAMPLE_RATE * seconds
    samples = samples_of(buf)
    assert all(-32768 <= v <= 32767 for v in samples)
    assert any(v != 0 for v in samples)              # audible, not silence
    assert any(v > 0 for v in samples) and any(v < 0 for v in samples)
    assert gen.frames_written == amb.SAMPLE_RATE * seconds


def test_scale_chunk_clamps_and_scales_in_place():
    buf = bytearray(struct.pack("<4h", 1000, -2000, 32000, -32000))
    scale_chunk(buf, 0.0)
    assert samples_of(buf) == [0, 0, 0, 0]
    buf = bytearray(struct.pack("<2h", 1000, -2000))
    scale_chunk(buf, 0.5)
    assert samples_of(buf) == [500, -1000]
    scale_chunk(buf, 1.0)
    scale_chunk(buf, 5.0)            # ≥1 is a no-op, never boosts
    assert samples_of(buf) == [500, -1000]
    scale_chunk(buf, -3.0)           # negative clamps to silence
    assert samples_of(buf) == [0, 0]


# ----------------------------------------------------------------- the channel

def test_channel_without_device_is_silent_noop(monkeypatch):
    monkeypatch.setattr(amb, "_default_output", lambda: QAudioDevice())
    ch = AmbientChannel()
    assert ch.start("campfire") is False
    assert ch.active is False and ch.kind is None
    assert not ch._timer.isActive()


def test_channel_without_multimedia_module_never_raises(monkeypatch):
    monkeypatch.setattr(amb, "_default_output", lambda: None)
    ch = AmbientChannel()
    assert ch.start("rain") is False and ch.active is False


def test_channel_fake_lifecycle_level_and_tick():
    ch, made = fake_channel()
    assert ch.level == config.AMBIENT_DEFAULT_LEVEL
    assert ch.start("campfire", seed=5) is True
    assert len(made) == 1 and ch.active and ch.kind == "campfire"
    ch._timer.setInterval(100)                       # 2205 frames per tick
    ch._tick()
    ch._tick()
    chunks = made[0].io.chunks
    assert len(chunks) == 2 and len(chunks[0]) == 2205 * amb.SAMPLE_WIDTH
    # level dial is real: samples scaled in place, not boosted
    loud = AmbientGenerator("campfire", seed=5)
    reference = bytearray(2205 * amb.SAMPLE_WIDTH)
    loud.fill(reference, 2205)
    scaled = samples_of(chunks[0])
    unscaled = samples_of(reference)
    assert max(abs(s) for s in scaled) <= max(abs(u) for u in unscaled)
    ch.stop()
    assert made[0].stopped and not ch.active and ch.kind is None
    assert not ch._timer.isActive()
    ch.stop()                                        # idempotent, no raise


def test_channel_start_asserts_the_ambient_format():
    fmts: list[QAudioFormat] = []
    ch = AmbientChannel(sink_factory=fmts.append)
    ch.start("rain", seed=1)
    assert len(fmts) == 1
    fmt = fmts[0]
    assert fmt.sampleRate() == amb.SAMPLE_RATE
    assert fmt.channelCount() == amb.CHANNELS
    assert fmt.sampleFormat() == QAudioFormat.SampleFormat.Int16


def test_channel_switching_kinds_releases_the_old_sink():
    ch, made = fake_channel()
    assert ch.start("campfire", seed=2) is True
    assert ch.start("rain", seed=2) is True
    assert len(made) == 2 and made[0].stopped        # old sink fully released
    assert made[1].stopped is False                  # new one is playing
    assert ch.kind == "rain"


def test_channel_start_failures_are_quiet():
    ch, made = fake_channel(sink=FakeSink(fail_open=True))
    assert ch.start("campfire") is False
    assert ch.active is False and not ch._timer.isActive()
    ch2, _made = fake_channel(sink=FakeSink(fail_open=True))
    assert ch2.start("rain") is False and ch2.active is False
    ch3, _ = fake_channel()
    assert ch3.start("thunderstorm") is False        # unknown kind: quiet False
    assert ch3.active is False and ch3.kind is None


def test_channel_set_level_clamps_and_ignores_junk():
    ch, _made = fake_channel()
    ch.set_level(2.0)
    assert ch.level == 1.0
    ch.set_level(-1.0)
    assert ch.level == 0.0
    ch.set_level("junk")                             # never raises
    assert ch.level == 0.0
    ch.set_level(0.7)
    assert ch.level == 0.7


def test_channel_level_zero_mutes_the_bed():
    ch, made = fake_channel()
    ch.set_level(0.0)
    ch.start("campfire", seed=9)
    ch._tick()
    assert made[0].io.chunks and samples_of(made[0].io.chunks[0]) == [
        0
    ] * (len(made[0].io.chunks[0]) // amb.SAMPLE_WIDTH)


# ----------------------------------------------------------------- app wiring

def test_app_ambient_unavailable_notes_and_never_raises(tmp_path, qapp, monkeypatch):
    monkeypatch.setattr(amb, "_default_output", lambda: QAudioDevice())
    hearth = make_hearth(tmp_path)
    notes: list[str] = []
    hearth.surface.set_status = notes.append
    assert hearth.ambient is not None and hearth.ambient.active is False
    hearth._set_ambient("campfire", 0.5)             # no device: silent no-op
    assert notes == ["Ambient unavailable — no audio device"]
    hearth._set_ambient(None, 0.0)
    assert notes[-1] == "Ambient: off"
    hearth.shutdown()


def test_app_ambient_switch_levels_and_off(tmp_path, qapp):
    hearth = make_hearth(tmp_path)
    notes: list[str] = []
    hearth.surface.set_status = notes.append
    ch, made = fake_channel()
    hearth.ambient = ch                              # inject the fake hardware
    hearth._set_ambient("campfire", 0.35)
    assert ch.kind == "campfire" and ch.level == 0.35
    assert notes[-1] == "Ambient: 🏕 Campfire at 35%"
    hearth._set_ambient("rain", 0.5)                 # switching stops the old
    assert ch.kind == "rain" and len(made) == 2 and made[0].stopped
    assert notes[-1] == "Ambient: 🌧 Rain at 50%"
    hearth._set_ambient("rain", 0.7)                 # same kind: level only
    assert ch.kind == "rain" and ch.level == 0.7 and len(made) == 2
    hearth._set_ambient(None, 0.0)
    assert ch.active is False and made[1].stopped
    assert notes[-1] == "Ambient: off"
    hearth.shutdown()


def test_app_shutdown_releases_the_ambient_sink(tmp_path, qapp):
    hearth = make_hearth(tmp_path)
    sink = FakeSink()
    hearth.ambient._sink = sink
    hearth.ambient._io = sink.io
    hearth.ambient._gen = AmbientGenerator("rain", seed=1)
    hearth.ambient._timer.start()
    hearth.shutdown()
    assert sink.stopped and hearth.ambient.active is False


def test_tray_labels_honour_i18n_lang(monkeypatch):
    from hearth.app import _i18n_label

    monkeypatch.setattr(config, "I18N_LANG", "en")
    assert _i18n_label("play_pause", "Play / Pause") == "Play / Pause"
    monkeypatch.setattr(config, "I18N_LANG", "es")
    assert _i18n_label("play", "Play / Pause") == "Reproducir"
    assert _i18n_label("next", "Next") == "Siguiente"
    monkeypatch.setattr(config, "I18N_LANG", "hi")
    assert _i18n_label("previous", "Previous") == "पिछला"
    assert _i18n_label("show_hearth", "Show Hearth") == "Show Hearth"  # fallback


# ----------------------------------------------------------------- i18n

def test_i18n_available_langs_includes_en_hi_es():
    langs = i18n.available_langs()
    assert isinstance(langs, tuple)
    assert {"en", "hi", "es"} <= set(langs)
    assert list(langs) == sorted(langs)


def test_i18n_english_covers_the_core_keys():
    en = i18n.STRINGS["en"]
    assert len(en) >= 40
    for key in ("play", "pause", "next", "previous", "shuffle", "repeat",
                "queue", "favorites", "playlists", "settings", "themes",
                "crossfade", "ambient", "alarm", "stats", "history", "local",
                "plugins", "lyrics", "theater", "on", "off"):
        assert isinstance(en[key], str) and en[key]


def test_i18n_partials_are_honest():
    en, hi, es = (i18n.STRINGS[c] for c in ("en", "hi", "es"))
    for partial in (hi, es):
        assert 10 <= len(partial) <= 20
        assert set(partial) <= set(en)               # no orphan keys
    assert set(hi) | set(es) != set(en)              # genuinely partial


def test_i18n_known_translations_are_correct():
    assert i18n.tr("play", "es") == "Reproducir"
    assert i18n.tr("pause", "es") == "Pausar"
    assert i18n.tr("mute", "es") == "Silenciar"
    assert i18n.tr("play", "hi") == "चलाएँ"
    assert i18n.tr("next", "hi") == "अगला"
    assert i18n.tr("off", "hi") == "बंद"


def test_i18n_fallback_chain_and_never_raises():
    en_crossfade = i18n.STRINGS["en"]["crossfade"]
    assert "crossfade" not in i18n.STRINGS["hi"]
    assert i18n.tr("crossfade", "hi") == en_crossfade    # code -> en
    assert i18n.tr("play", "zz") == "Play"               # unknown code -> en
    assert i18n.tr("no_such_key", "es") == "no_such_key"  # unknown key -> key
    assert i18n.tr("no_such_key", "zz") == "no_such_key"  # total miss -> key


def test_i18n_default_lang_reads_config(monkeypatch):
    assert i18n.DEFAULT_LANG == config.I18N_LANG == "en"
    monkeypatch.setattr(config, "I18N_LANG", "es")
    assert i18n.tr("play") == "Reproducir"           # resolved at call time


# ----------------------------------------------------------------- last.fm

@pytest.mark.parametrize(
    ("elapsed", "duration", "expected"),
    [
        (200, 400, True),    # exactly 50% of a 400s track (half < cap)
        (199, 400, False),   # one second shy of half
        (240, 600, True),    # the 4-minute cap on a long track
        (239, 600, False),   # cap not reached, half (300s) not reached
        (300, 600, True),    # long past the cap: already eligible
        (30, 60, True),      # short track: half arrives before the cap
        (29, 60, False),
        (10, 20, True),      # tiny track, threshold = 1s
        (0, 60, False),      # nothing heard
        (100, 0, False),     # no duration: never
        (100, -5, False),    # nonsense duration: never
        (-1, 60, False),     # nonsense elapsed: never
    ],
)
def test_should_scrobble_matrix(elapsed, duration, expected):
    assert scrobble.should_scrobble(elapsed, duration) is expected


def test_sign_matches_the_hand_computed_vector():
    params = {
        "method": "track.scrobble",
        "artist": "Nirvana",
        "api_key": "abcdef123",
        "track": "Smells Like Teen Spirit",
    }
    # hand-computed: sort by key, concatenate key+value, append the secret
    # ("api_keyabcdef123" + "artistNirvana" + "methodtrack.scrobble"
    #  + "trackSmells Like Teen Spirit" + "SECRETSHH"), then md5.
    assert scrobble.sign(params, "SECRETSHH") == "bd3913ed8649021c133ff930f191dc37"
    assert scrobble.sign(params, "SECRETSHH") == hashlib.md5(
        b"api_keyabcdef123artistNirvanamethodtrack.scrobble"
        b"trackSmells Like Teen SpiritSECRETSHH"
    ).hexdigest()


def test_sign_sorts_keys_and_handles_empty_params():
    assert scrobble.sign({"b": "2", "a": "1"}, "s") == hashlib.md5(b"a1b2s").hexdigest()
    assert scrobble.sign({}, "shhh") == hashlib.md5(b"shhh").hexdigest()


def test_payload_shape_with_default_config():
    assert config.LASTFM_API_KEY == "" and config.LASTFM_SECRET == ""
    payload = scrobble.build_scrobble_payload("SK123", "A", "T", "Al", ts=1700000000.9)
    assert payload["method"] == "track.scrobble"
    assert payload["artist"] == "A" and payload["track"] == "T"
    assert payload["album"] == "Al"
    assert payload["timestamp"] == 1700000000          # int, not float
    assert payload["sk"] == "SK123"
    assert "api_key" not in payload and "api_sig" not in payload


def test_payload_signs_itself_when_keys_exist(monkeypatch):
    monkeypatch.setattr(config, "LASTFM_API_KEY", "KEY")
    monkeypatch.setattr(config, "LASTFM_SECRET", "SEC")
    payload = scrobble.build_scrobble_payload("SK", "A", "T", album="", ts=1.0)
    assert payload["api_key"] == "KEY"
    unsigned = {k: v for k, v in payload.items() if k != "api_sig"}
    assert payload["api_sig"] == scrobble.sign(unsigned, "SEC")


def test_token_flow_url_builder(monkeypatch):
    assert scrobble.submit_token_flow("KEY", "TOK") == \
        "https://www.last.fm/api/auth/?api_key=KEY&token=TOK"
    monkeypatch.setattr(config, "LASTFM_API_KEY", "CFGKEY")
    assert scrobble.submit_token_flow(token="TOK2") == \
        "https://www.last.fm/api/auth/?api_key=CFGKEY&token=TOK2"


def test_queue_roundtrip_through_json():
    q = scrobble.ScrobbleQueue()
    q.enqueue(make_track(), played_at=1234.5)
    q.enqueue({"artist": "Embrace", "title": "Ashes", "album": "Songs",
               "duration_sec": 281})
    payload = json.loads(json.dumps(q.dump()))
    restored = scrobble.ScrobbleQueue()
    assert restored.load(payload) == 2
    assert restored.dump() == q.dump()
    first = restored.dump()[0]
    assert first["artist"] == "Rick Astley" and first["timestamp"] == 1234.5


def test_queue_capped_and_junk_is_refused():
    q = scrobble.ScrobbleQueue(maxlen=2)
    assert q.enqueue(make_track(video_id="1")) is not None
    assert q.enqueue(make_track(video_id="2")) is not None
    assert q.enqueue(make_track(video_id="3")) is not None  # evicts the oldest
    assert len(q) == 2
    assert [s["timestamp"] for s in q.dump()] == sorted(
        s["timestamp"] for s in q.dump())             # oldest first, cap held
    assert q.enqueue(None) is None and q.enqueue(42) is None
    assert q.enqueue({"title": "no artist"}) is None and len(q) == 2
    assert q.load("not a list") == 0
    assert q.load([{"nope": 1}, {"artist": "A", "title": "T"}]) == 1
    assert q.dump()[0]["title"] == "T"


def test_scrobble_config_flags_stay_asleep():
    assert config.LASTFM_ENABLED is False
    assert config.LASTFM_API_KEY == "" and config.LASTFM_SECRET == ""


# ----------------------------------------------------------------- packaging

def test_packaging_manifests_exist_and_carry_required_keys():
    pkgbuild = (PACKAGING_DIR / "PKGBUILD").read_text(encoding="utf-8")
    yml = (PACKAGING_DIR / "com.qtjg.hearth.yml").read_text(encoding="utf-8")
    rb = (PACKAGING_DIR / "hearth.rb").read_text(encoding="utf-8")
    readme = (PACKAGING_DIR / "README.md").read_text(encoding="utf-8")
    assert "pkgname=hearth-music" in pkgbuild
    assert "python-pyqt6" in pkgbuild and "python-installer" in pkgbuild
    assert "archive/refs/tags/v${pkgver}.tar.gz" in pkgbuild
    assert "SKIP" in pkgbuild and "python -m installer" in pkgbuild
    assert "PackageIdentifier: qtjg.hearth" in yml
    assert "Installers:" in yml and "Silent" in yml
    assert 'cask "hearth"' in rb and "github_releases" in rb
    assert "homepage" in rb and "https://github.com/qtjg/hearth" in rb
    for text in (pkgbuild, yml, rb, readme):
        assert len(text) > 150                          # non-trivial, not stubs
    for name in ("PKGBUILD", "com.qtjg.hearth.yml", "hearth.rb"):
        assert name in readme                           # README explains each
