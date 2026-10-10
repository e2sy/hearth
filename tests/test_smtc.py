"""v0.8.0 Room 8.3 — the SMTC shim: pure mappers + fake-bus service tests."""

from hearth.models import Track
from hearth.smtc import (
    SMTC_AVAILABLE,
    SmtcService,
    button_command,
    metadata_map,
    playback_status,
    timeline_map,
)

from .test_models import make_track


# --- playback status ---


def test_playback_status_tri_state():
    assert playback_status(True) == "PLAYING"
    assert playback_status(False) == "PAUSED"
    assert playback_status(None) == "STOPPED"


# --- button mapping ---


def test_button_command_maps_to_hearth_verbs():
    assert button_command("playpause") == "toggle"
    assert button_command("next") == "next"
    assert button_command("previous") == "prev"
    assert button_command("stop") == "pause"
    assert button_command("play") == "play"
    assert button_command("pause") == "pause"


def test_button_command_ignores_unknown():
    assert button_command("channel_up") is None
    assert button_command("") is None
    assert button_command("PREVIOUS") == "prev"       # case-tolerant


# --- metadata map ---


def test_metadata_map_plain_types():
    meta = metadata_map(make_track())
    assert meta["video_id"] == "dQw4w9WgXcQ"
    assert meta["title"] == "Never Gonna Give You Up"
    assert meta["artist"] == "Rick Astley"
    assert meta["url"] == "https://music.youtube.com/watch?v=dQw4w9WgXcQ"
    assert meta["duration_ms"] == 213000
    assert meta["thumbnail"].startswith("https://")


def test_metadata_map_empty_track_is_empty_dict():
    assert metadata_map(None) == {}
    meta = metadata_map(make_track(thumbnail=""))
    assert "thumbnail" not in meta              # no art → no art key


def test_metadata_map_derives_duration_from_string():
    meta = metadata_map(make_track(duration_sec=0, duration="3:33"))
    assert meta["duration_ms"] == 213000


# --- timeline map ---


def test_timeline_map_clamps_and_orders():
    t = timeline_map(-5, 1000, True)
    assert t == {"position_ms": 0, "end_ms": 1000, "status": "PLAYING"}
    # a position past the end still gets a sane window
    t = timeline_map(5000, 1000, False)
    assert t["end_ms"] == 5000 and t["status"] == "PAUSED"
    assert timeline_map(None, None, None)["status"] == "STOPPED"


# --- the service with a fake bus ---


class FakeBridge:
    def __init__(self):
        self.snapshots: list[tuple[dict, dict]] = []
        self.explode = False

    def __call__(self, metadata: dict, timeline: dict) -> None:
        if self.explode:
            raise RuntimeError("lockscreen lied")
        self.snapshots.append((metadata, timeline))


def _service(bridge, *, track=None, playing=True, position=10_000, duration=213_000):
    return SmtcService(
        bridge=bridge,
        get_track=lambda: track,
        is_playing=lambda: playing,
        get_position_ms=lambda: position,
        get_duration_ms=lambda: duration,
    )


def test_service_start_needs_a_bridge():
    assert SmtcService().start() is (True if SMTC_AVAILABLE else False)
    assert _service(FakeBridge(), track=make_track()).start() is True


def test_service_pushes_snapshot():
    bridge = FakeBridge()
    svc = _service(bridge, track=make_track())
    svc.start()
    assert svc.update() is True
    metadata, timeline = bridge.snapshots[0]
    assert metadata["title"] == "Never Gonna Give You Up"
    assert timeline["position_ms"] == 10_000
    assert timeline["status"] == "PLAYING"


def test_service_without_start_or_track_is_honest():
    bridge = FakeBridge()
    svc = _service(bridge, track=make_track())
    assert svc.update() is False            # not started
    svc.start()
    assert _service(FakeBridge(), track=None).update() is False
    assert bridge.snapshots == []


def test_service_survives_exploding_bridge():
    bridge = FakeBridge()
    bridge.explode = True
    svc = _service(bridge, track=make_track())
    svc.start()
    assert svc.update() is False            # absorbed, never raised


def test_service_getter_hiccups_degrade_fields():
    def boom():
        raise RuntimeError("nope")

    bridge = FakeBridge()
    svc = SmtcService(
        bridge=bridge,
        get_track=lambda: make_track(),
        is_playing=boom,
        get_position_ms=boom,
        get_duration_ms=boom,
    )
    svc.start()
    assert svc.update() is True
    _meta, timeline = bridge.snapshots[0]
    assert timeline["status"] == "STOPPED"
    assert timeline["position_ms"] == 0
    assert timeline["end_ms"] == 213000     # duration fell back to metadata


def test_service_handle_button():
    svc = SmtcService()
    assert svc.handle_button("playpause") == "toggle"
    assert svc.handle_button("mystery") is None
