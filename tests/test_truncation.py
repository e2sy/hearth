"""Premature EndOfMedia = stream truncation, not a natural finish.

YouTube throttling truncates googlevideo streams today; QMediaPlayer
then reports EndOfMedia while the song is barely halfway through.
The old core treated that as a natural finish and rolled on (or fell
silent) — the classic 'song stops in the middle' complaint. These
tests pin the healing behavior: rejoin with a fresh URL, bounded by
the existing rejoin budget.
"""

import pytest

from hearth import config
from hearth.models import Track
from hearth.player import PlaybackCore

from .test_models import make_track


def tracks(n, **overrides) -> list[Track]:
    return [
        make_track(video_id=f"t{i}", title=f"Song {i}", **overrides)
        for i in range(n)
    ]


@pytest.fixture
def core(qapp):
    return PlaybackCore()


def _simulate_audible_playback(core: PlaybackCore, pos_ms: int) -> None:
    """Convince the core a stream is genuinely playing at `pos_ms`."""
    core._note_playing(True)       # audio flowed: _stream_played, _recover_armed
    core._last_pos_ms = pos_ms
    core._stream_anchor_ms = 0


def test_premature_end_of_media_rejoins_instead_of_advancing(core):
    lost = []
    core.stream_lost.connect(lambda t, ms: lost.append((t.video_id, ms)))
    core.start_queue(tracks(2), start=0)          # duration_sec=213 each
    _simulate_audible_playback(core, 50_000)      # died 50s into a 213s track
    core._on_end_of_media()
    # the queue did NOT move — the same song is being healed in place
    assert core.engine.current.video_id == "t0"
    assert lost == [("t0", 50_000)]


def test_natural_end_of_media_still_advances(core):
    seen = []
    core.track_changed.connect(seen.append)
    core.start_queue(tracks(2), start=0)
    _simulate_audible_playback(core, int(213 * 1000 * config.STREAM_TRUNCATION_RATIO) + 500)
    core._on_end_of_media()
    assert core.engine.current.video_id == "t1"
    assert seen[-1].video_id == "t1"


def test_premature_end_without_audio_never_rejoins(core):
    """A restored session sitting at its resume point emits no audio —
    an EndOfMedia from a stream that never played must stay a normal end."""
    seen = []
    core.track_changed.connect(seen.append)
    core.start_queue(tracks(2), start=0)
    core._last_pos_ms = 50_000        # position observed, but no audio yet
    core._stream_played = False
    core._on_end_of_media()
    assert core.engine.current.video_id == "t1"   # honest advance, no healing
    assert seen[-1].video_id == "t1"


def test_premature_end_budget_exhausted_skips_forward(core):
    seen = []
    core.track_changed.connect(seen.append)
    core.start_queue(tracks(2), start=0)
    _simulate_audible_playback(core, 10_000)   # inside the 30s renewal window
    core._recovered_id = "t0"          # budget belongs to this track
    core._retries = config.STREAM_MAX_RECOVERIES   # …and it is spent
    core._on_end_of_media()
    assert core.engine.current.video_id == "t1"
    assert seen[-1].video_id == "t1"


def test_premature_end_unknown_duration_advances(core):
    """duration_sec=0 (live radio, unknown metadata) can never be judged."""
    seen = []
    core.track_changed.connect(seen.append)
    core.start_queue(tracks(2, duration_sec=0), start=0)
    _simulate_audible_playback(core, 30_000)
    core._on_end_of_media()
    assert core.engine.current.video_id == "t1"


def test_healthy_playback_renews_truncation_budget(core):
    """30s of real playback resets the rejoin budget (same rule as errors)."""
    lost = []
    core.stream_lost.connect(lambda t, ms: lost.append((t.video_id, ms)))
    core.start_queue(tracks(1), start=0)
    _simulate_audible_playback(core, 10_000)
    core._recovered_id = "t0"
    core._retries = config.STREAM_MAX_RECOVERIES   # budget spent
    core._last_pos_ms = 10_000 + config.STREAM_RECOVERY_RESET_MS + 1
    core._on_end_of_media()
    # the budget renewed, so the truncation earned a fresh rejoin anyway
    assert lost and lost[0][0] == "t0"
