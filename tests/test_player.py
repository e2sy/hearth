"""Queue engine: history, shuffle, repeat — the pure heart of playback."""

import random

import pytest

from hearth import config
from hearth.models import Track
from hearth.player import PlaybackCore, QueueEngine

from .test_models import make_track


def tracks(n) -> list[Track]:
    return [make_track(video_id=f"t{i}", title=f"Song {i}") for i in range(n)]


def test_start_queue():
    eng = QueueEngine()
    first = eng.start_queue(tracks(3), start=0)
    assert first is not None and first.video_id == "t0"
    assert [t.video_id for t in eng.upcoming] == ["t1", "t2"]


def test_start_queue_invalid_index():
    eng = QueueEngine()
    assert eng.start_queue(tracks(3), start=9) is None
    assert eng.start_queue([], start=0) is None


def test_play_now_moves_current_to_history():
    eng = QueueEngine()
    eng.start_queue(tracks(2))
    extra = make_track(video_id="extra")
    eng.play_now(extra)
    assert eng.current.video_id == "extra"
    assert eng.history[-1].video_id == "t0"


def test_advance_walks_queue_and_history_grows():
    eng = QueueEngine()
    eng.start_queue(tracks(3))
    second = eng.advance()
    assert second.video_id == "t1"
    third = eng.advance()
    assert third.video_id == "t2"
    assert eng.history[-1].video_id == "t1"


def test_advance_empty_returns_none():
    eng = QueueEngine()
    assert eng.advance() is None


def test_repeat_all_wraps_history():
    eng = QueueEngine()
    eng.repeat = config.REPEAT_ALL
    eng.start_queue(tracks(2))
    eng.advance()   # t1
    wrapped = eng.advance()
    assert wrapped is not None and wrapped.video_id == "t0"


def test_repeat_one_sticks():
    eng = QueueEngine()
    eng.repeat = config.REPEAT_ONE
    eng.start_queue(tracks(2))
    again = eng.advance()
    assert again.video_id == "t0"
    assert eng.upcoming[0].video_id == "t1"


def test_go_back_restores_history():
    eng = QueueEngine()
    eng.start_queue(tracks(3))
    eng.advance()
    back = eng.go_back()
    assert back.video_id == "t0"
    assert eng.upcoming[0].video_id == "t1"


def test_go_back_at_start_is_noop():
    eng = QueueEngine()
    eng.start_queue(tracks(2))
    assert eng.go_back().video_id == "t0"


def test_shuffle_preserves_history_and_multiset():
    eng = QueueEngine(rng=random.Random(42))
    eng.start_queue(tracks(8))
    eng.advance()
    history_ids = [t.video_id for t in eng.history]
    eng.shuffle()
    upcoming_ids = [t.video_id for t in eng.upcoming]
    # Shuffling never yanks playback: history untouched, current keeps
    # playing, and the upcoming multiset is exactly the remaining queue.
    assert len(upcoming_ids) == 6
    assert history_ids == [t.video_id for t in eng.history]
    assert eng.current.video_id == "t1"
    assert set(upcoming_ids) == {f"t{i}" for i in range(2, 8)}


def test_peek_next_respects_repeat_one():
    eng = QueueEngine()
    eng.start_queue(tracks(2))
    assert eng.peek_next().video_id == "t1"
    eng.repeat = config.REPEAT_ONE
    assert eng.peek_next().video_id == "t0"


# --- PlaybackCore: signals and settings without touching audio backend ---

@pytest.fixture()
def core(qapp):
    return PlaybackCore()


def test_repeat_cycle_order(core):
    core.set_repeat(config.REPEAT_OFF)
    assert core.cycle_repeat() == config.REPEAT_ALL
    assert core.cycle_repeat() == config.REPEAT_ONE
    assert core.cycle_repeat() == config.REPEAT_OFF


def test_set_repeat_rejects_unknown(core):
    core.set_repeat("banana")
    assert core.engine.repeat == config.REPEAT_OFF


def test_rate_clamped_and_signaled(core):
    seen = []
    core.rate_changed.connect(seen.append)
    core.set_rate(99.0)
    assert seen[-1] == 2.5
    core.set_rate(0.1)
    assert seen[-1] == 0.5


def test_next_rate_cycles(core):
    core.set_rate(1.0)
    assert core.next_rate() == 1.25
    assert core.next_rate() == 1.5
    assert core.next_rate() == 0.75


def test_volume_roundtrip(core):
    core.set_volume(1.7)
    assert core.volume == 1.0
    core.set_volume(-1)
    assert core.volume == 0.0


def test_track_changed_signal(core):
    seen = []
    core.track_changed.connect(seen.append)
    core.play_track(make_track())
    assert len(seen) == 1
    assert core.engine.current.video_id == "dQw4w9WgXcQ"


# --- end-of-media & error recovery (v0.2.0 dropped the v0.1.0 relay,
#     so finished tracks went silent instead of rolling on) ---


def test_end_of_media_rolls_into_next(core):
    seen = []
    core.track_changed.connect(seen.append)
    core.start_queue(tracks(2), start=0)
    core._on_end_of_media()
    assert core.engine.current.video_id == "t1"
    assert seen[-1].video_id == "t1"


def test_end_of_media_repeat_one_sticks(core):
    seen = []
    core.track_changed.connect(seen.append)
    core.set_repeat(config.REPEAT_ONE)
    core.start_queue(tracks(2), start=0)
    core._on_end_of_media()
    assert core.engine.current.video_id == "t0"
    assert seen[-1].video_id == "t0"
    assert core.engine.upcoming[0].video_id == "t1"


def test_end_of_media_repeat_all_wraps(core):
    core.set_repeat(config.REPEAT_ALL)
    core.start_queue(tracks(2), start=0)
    core._on_end_of_media()   # t0 -> t1
    core._on_end_of_media()   # queue dry, repeat-all wraps -> t0
    assert core.engine.current.video_id == "t0"


def test_end_of_media_queue_finished_stops(core):
    seen = []
    core.state_changed.connect(seen.append)
    core.set_autoplay(False)
    core.start_queue(tracks(1), start=0)
    core._on_end_of_media()
    assert core.engine.current is None
    assert seen[-1] is False


def test_end_of_media_autoplay_asks_for_radio_refill(core):
    dried = []
    core.queue_dry.connect(dried.append)
    core.set_autoplay(True)
    core.start_queue(tracks(1), start=0)
    core._on_end_of_media()
    assert dried and dried[0].video_id == "t0"


def test_player_error_skips_to_next_track(core):
    core.start_queue(tracks(2), start=0)
    core._on_error(0, "stream died")
    assert core.engine.current.video_id == "t1"


def test_player_error_duplicate_ignored_until_audio_plays(core):
    core.start_queue(tracks(3), start=0)
    core._on_error(0, "boom")         # skip t0 -> t1
    core._on_error(0, "boom again")   # duplicate before any audio: ignored
    assert core.engine.current.video_id == "t1"
    core._note_playing(True)          # t1 actually starts
    core._on_error(0, "boom")         # now a fresh failure may skip again
    assert core.engine.current.video_id == "t2"


def test_error_streak_gives_up(core):
    core.start_queue(tracks(9), start=0)
    for _ in range(core.MAX_ERROR_SKIPS + 1):
        core._note_playing(True)      # each track starts...
        core._on_error(0, "dead")     # ...then dies mid-play
    assert core.engine.current.video_id == f"t{core.MAX_ERROR_SKIPS}"


# --- mid-song rejoin (v0.6.3): a stream that dies while audibly playing
#     gets a fresh URL and rejoins where it stopped, instead of a skip ---


def test_mid_song_error_rejoins_same_track(core):
    lost = []
    core.stream_lost.connect(lambda t, ms: lost.append((t.video_id, ms)))
    core.start_queue(tracks(2), start=0)
    core._note_playing(True)
    core._last_pos_ms = 154_000            # 2:34 into the song — audibly underway
    core._on_error(0, "CDN 403")
    assert lost == [("t0", 154_000)]       # same song, resume position kept
    assert core.engine.current.video_id == "t0"


def test_error_at_position_zero_still_skips(core):
    # Nothing played yet: there is no song to rejoin, skip as before.
    core.start_queue(tracks(2), start=0)
    core._on_error(0, "bad url")
    assert core.engine.current.video_id == "t1"


def test_rejoin_budget_exhausts_then_skips(core):
    lost = []
    core.stream_lost.connect(lambda t, ms: lost.append(t.video_id))
    core.start_queue(tracks(3), start=0)
    core._note_playing(True)
    core._last_pos_ms = 10_000
    for _ in range(config.STREAM_MAX_RECOVERIES):
        core._on_error(0, "dies")          # three honest rejoin tries...
        core._note_playing(True)           # ...each one landing before the next death
    assert len(lost) == config.STREAM_MAX_RECOVERIES
    core._note_playing(True)
    core._on_error(0, "dies")              # budget gone -> skip fallback
    assert core.engine.current.video_id == "t1"


def test_healthy_playback_renews_rejoin_budget(core):
    core.start_queue(tracks(1), start=0)
    core._note_playing(True)
    core._last_pos_ms = 10_000
    core._stream_anchor_ms = 0
    core._on_error(0, "dies")              # rejoin #1
    assert core._retries == 1
    core._note_playing(True)               # the rejoin lands: audio flows again
    core._last_pos_ms = 45_000             # 45s of healthy playback past the anchor
    core._on_error(0, "dies again")        # budget renewed -> fresh rejoin
    assert core._retries == 1


def test_stall_watchdog_rejoins_frozen_stream(core):
    lost = []
    core.stream_lost.connect(lambda t, ms: lost.append((t.video_id, ms)))
    core.start_queue(tracks(1), start=0)

    class Frozen:
        def position(self):
            return 90_000

    core._player = Frozen()
    core._note_playing(True)
    core._last_pos_ms = 90_000
    for _ in range(config.STALL_POLLS):
        core._emit_position()
    assert lost == [("t0", 90_000)]


def test_advancing_position_never_stalls(core):
    lost = []
    core.stream_lost.connect(lambda t, ms: lost.append(t.video_id))
    core.start_queue(tracks(1), start=0)

    class Ticking:
        def __init__(self):
            self.n = 0

        def position(self):
            self.n += 500
            return self.n

    core._player = Ticking()
    core._note_playing(True)
    for _ in range(config.STALL_POLLS * 2):
        core._emit_position()
    assert not lost


# --- the v0.6.3 spam storm: a stream that never opened (dead URL /
#     CDN 403) was re-fed to the backend forever — position alone
#     can't vouch for "the song was underway", and a refused rejoin
#     left the player a frozen zombie. Fixed by gating every heal on
#     audio that demonstrably flowed, and giving every failure a
#     bounded, honest ending (skip once, then stop). ---


def test_resume_position_without_playback_never_rejoins(core):
    # A restored session sits at its resume position before the first
    # byte arrives. If the stream then fails to open, that position is
    # NOT proof of playback: skip the track, never re-feed the URL.
    lost = []
    core.stream_lost.connect(lambda t, ms: lost.append(t.video_id))
    core.start_queue(tracks(3), start=0)
    core._last_pos_ms = 118_800            # resume point of a restored session
    core._on_error(0, "Could not open media. FFmpeg error 403")
    assert not lost                        # no rejoin spam
    assert core.engine.current.video_id == "t1"


def test_never_opened_stream_is_skipped_by_watchdog(core):
    # set_stream() accepted a dead URL: the backend stays Stopped, emits
    # nothing, and _playing sits stale-True. The watchdog must end the
    # silence with a skip — not re-feed the URL, not freeze forever.
    lost = []
    core.stream_lost.connect(lambda t, ms: lost.append(t.video_id))
    core.start_queue(tracks(2), start=0)

    class NeverOpens:
        def position(self):
            return 0

    core._player = NeverOpens()
    core._playing = True                   # stale from set_stream
    core._last_pos_ms = 0
    for _ in range(config.STALL_POLLS):
        core._emit_position()
    assert not lost                        # nothing played -> nothing to rejoin
    assert core.engine.current.video_id == "t1"
    assert not core._playing


def test_watchdog_rejoin_refused_then_skips(core):
    # A played stream freezes, but the rejoin budget is gone: the old
    # code ignored the refusal and zombie-ed forever. Now: skip.
    core.start_queue(tracks(2), start=0)

    class Frozen:
        def position(self):
            return 90_000

    core._player = Frozen()
    core._note_playing(True)
    core._last_pos_ms = 90_000
    core._stream_anchor_ms = 90_000        # no healthy-playback renewal
    core._retries = config.STREAM_MAX_RECOVERIES   # budget already spent
    core._recovered_id = "t0"
    for _ in range(config.STALL_POLLS):
        core._emit_position()
    assert core.engine.current.video_id == "t1"


def test_buffering_media_gets_stall_grace(core):
    # A slow open (LoadingMedia/BufferingMedia) is alive, just shy:
    # frozen position alone must not trip the watchdog into a skip.
    lost = []
    core.stream_lost.connect(lambda t, ms: lost.append(t.video_id))
    core.start_queue(tracks(2), start=0)

    class Buffering:
        def position(self):
            return 0

        def mediaStatus(self):
            from PyQt6.QtMultimedia import QMediaPlayer

            return QMediaPlayer.MediaStatus.BufferingMedia

    core._player = Buffering()
    core._playing = True
    core._last_pos_ms = 0
    for _ in range(config.STALL_POLLS * 3):
        core._emit_position()
    assert not lost
    assert core.engine.current.video_id == "t0"   # still waiting, untouched


def test_position_progress_marks_stream_played(core):
    core.start_queue(tracks(1), start=0)
    assert not core._stream_played

    class SlowStart:
        """Frozen at zero first (still opening), then audio flows."""

        def __init__(self):
            self.n = 0

        def position(self):
            self.n += 500
            return min(0, self.n - 500) if self.n <= 500 else self.n

    core._player = SlowStart()
    core._playing = True
    core._emit_position()                  # frozen at 0, "playing": stall counting
    assert not core._stream_played         # no audio yet — no proof
    core._emit_position()                  # 500ms: position moved
    assert core._stream_played             # audio demonstrably flowing


def test_set_stream_resets_played_proof(core):
    # A fresh set_stream forgets the old stream's good name: the next
    # URL must earn its rejoin rights with its own audio.
    core.start_queue(tracks(1), start=0)
    core._stream_played = True
    core._recovered_id = None

    class Mutable:
        def setSource(self, url):
            pass

        def setPlaybackRate(self, rate):
            pass

        def play(self):
            pass

        def setPosition(self, ms):
            pass

    core._player = Mutable()
    core.set_stream(tracks(1)[0], "https://example.com/a.mp3")
    assert not core._stream_played


def test_stop_resets_playing_and_poll(core):
    core.start_queue(tracks(1), start=0)
    core._playing = True
    core._poll.start()
    core.stop()
    assert not core._playing
    assert not core._poll.isActive()
