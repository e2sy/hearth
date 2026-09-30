"""Audio core: pure queue engine + lazy QMediaPlayer backend."""

from __future__ import annotations

import logging
import math
import random
from collections import deque
from typing import Callable

from PyQt6.QtCore import QObject, QTimer, pyqtSignal

from . import config
from .models import Track

log = logging.getLogger(__name__)

_WAITING_STATUSES: frozenset | None = None

# Distance sentinel for smart shuffle: an artist never seen this queue
# waits "forever", so first passes keep the queued order intact.
_UNSEEN_DISTANCE = 1 << 30


def _waiting_statuses() -> frozenset:
    """Qt media statuses that mean 'working on it'.

    Resolved lazily so headless/CI never touches QtMultimedia until a
    real backend exists. No module, no grace — callers fall back to
    judging streams by position alone.
    """
    global _WAITING_STATUSES
    if _WAITING_STATUSES is None:
        try:
            from PyQt6.QtMultimedia import QMediaPlayer

            _WAITING_STATUSES = frozenset({
                QMediaPlayer.MediaStatus.LoadingMedia,
                QMediaPlayer.MediaStatus.BufferingMedia,
                QMediaPlayer.MediaStatus.StalledMedia,
            })
        except Exception:  # noqa: BLE001 - no multimedia module: no grace
            _WAITING_STATUSES = frozenset()
    return _WAITING_STATUSES


# --- crossfade groundwork (v1.0.0): equal-power ramp + twin handles ---


def fade_pair(progress: float, seconds: int) -> tuple[float, float]:
    """Equal-power crossfade pair at `progress` in (current, next) factors.

    Equal-power (cos/sin) keeps the *perceived* loudness flat across the
    seam — a linear pair dips roughly 3 dB at the midpoint because two
    half-volume sources don't add up to one full one. Endpoints are
    exact: progress 0 → (1, 0), progress 1 → (0, 1), the midpoint sits
    at ≈ (0.707, 0.707). `progress` is clamped to [0, 1]. `seconds` <= 0
    means "no fade at all": unity for the current track, silence for
    the next, whatever the progress.
    """
    if seconds <= 0:
        return 1.0, 0.0
    p = max(0.0, min(1.0, float(progress)))
    if p <= 0.0:
        return 1.0, 0.0        # exact endpoints: no float dust at the seams
    if p >= 1.0:
        return 0.0, 1.0
    angle = p * math.pi / 2
    return math.cos(angle), math.sin(angle)


class MediaHandle:
    """The sliver of a media player a crossfade twin needs.

    The CrossfadeController drives handles through exactly these six
    members — start/stop/set_volume/position_ms/duration_ms/error_count
    — and nothing else. PlaybackCore may use the setup extras (load,
    set_rate) while priming a shadow. Production uses QtMediaHandle (a
    QMediaPlayer + QAudioOutput pair); tests inject fakes.
    """

    errors: int = 0   # backend errors observed on this handle

    def load(self, url: str) -> None:
        """Set the source WITHOUT playing (prime time)."""

    def start(self, position_ms: int = 0) -> None:
        """Begin playback, optionally from a position."""

    def stop(self) -> None:
        """Halt playback."""

    def set_volume(self, factor: float) -> None:
        """Absolute output volume, clamped 0..1."""

    def set_rate(self, rate: float) -> None:
        """Playback speed (shadow setup only; not driven by the controller)."""

    @property
    def position_ms(self) -> int:
        return 0

    @property
    def duration_ms(self) -> int:
        return 0

    @property
    def error_count(self) -> int:
        return self.errors


class QtMediaHandle(MediaHandle):
    """A real QMediaPlayer + QAudioOutput pair behind a MediaHandle."""

    def __init__(self, parent: QObject | None = None):
        from PyQt6.QtMultimedia import QAudioOutput, QMediaPlayer

        # Both Qt objects are parented to the core when one is given, so
        # a promoted (or dropped) handle's wrapper can be garbage-collected
        # without ever dangling the live audio output underneath it.
        self.audio = QAudioOutput(parent)
        self.player = QMediaPlayer(parent)
        self.player.setAudioOutput(self.audio)
        self.errors = 0
        self.player.errorOccurred.connect(self._note_error)

    def _note_error(self, _err, _err_str: str) -> None:
        self.errors += 1

    def load(self, url: str) -> None:
        from PyQt6.QtCore import QUrl

        self.player.setSource(QUrl(url))

    def start(self, position_ms: int = 0) -> None:
        self.player.play()
        if position_ms:
            self.player.setPosition(int(position_ms))

    def stop(self) -> None:
        self.player.stop()

    def set_volume(self, factor: float) -> None:
        self.audio.setVolume(max(0.0, min(1.0, float(factor))))

    def set_rate(self, rate: float) -> None:
        self.player.setPlaybackRate(float(rate))

    @property
    def position_ms(self) -> int:
        try:
            return int(self.player.position())
        except RuntimeError:
            return 0

    @property
    def duration_ms(self) -> int:
        try:
            return int(self.player.duration())
        except RuntimeError:
            return 0

    @property
    def error_count(self) -> int:
        return self.errors


class _LiveBackendHandle(MediaHandle):
    """Adapts the PlaybackCore's live backend into a MediaHandle.

    The controller's ramp-out leg only needs volume (the outgoing track
    is already finished when an EndOfMedia crossfade starts); position
    reads through for completeness. The adapter is evergreen — it always
    targets whatever backend the core currently fronts, so it stays
    valid across promotions.
    """

    def __init__(self, core: "PlaybackCore"):
        self._core = core

    def start(self, position_ms: int = 0) -> None:
        return   # the core drives its own backend

    def stop(self) -> None:
        return

    def set_volume(self, factor: float) -> None:
        out = self._core._audio_out
        if out is not None:
            try:
                out.setVolume(max(0.0, min(1.0, float(factor))))
            except (RuntimeError, AttributeError):
                pass

    @property
    def position_ms(self) -> int:
        return self._core.position_ms

    @property
    def duration_ms(self) -> int:
        return 0   # not used by the EndOfMedia-engage design


class CrossfadeController:
    """Pure crossfade state machine over two injectable media handles.

    IDLE → PRIMED (next track resolved + loaded on a shadow) →
    CROSSFADING (both rolling, volumes ramped) → DONE (promoted).

    It never touches QMediaPlayer: it drives two `MediaHandle` twins.
    Production wires `on_promote` to PlaybackCore's promotion (swap the
    shadow in as the primary, then advance the queue exactly once);
    tests inject recording fakes. Timings come from an injectable tick
    interval, so no real timers are needed to test the ramp.
    """

    IDLE = "idle"
    PRIMED = "primed"
    CROSSFADING = "crossfading"
    DONE = "done"

    def __init__(self, seconds: int = 0,
                 tick_ms: int = 100,
                 on_promote: Callable[[], None] | None = None):
        self.seconds = max(0, int(seconds))
        self.tick_ms = max(1, int(tick_ms))
        self.on_promote = on_promote   # fired exactly once, at ramp end
        self.state: str = self.IDLE
        self.current: MediaHandle | None = None   # live primary (ramp-out leg)
        self.shadow: MediaHandle | None = None    # primed next track
        self.primed_track: object | None = None   # Track the shadow carries
        self.base_volume: float = 0.8   # the core's master volume, kept synced
        self.progress: float = 0.0
        self._steps = 0
        self._ticked = 0
        self._promoted = False

    def adopt(self, current: MediaHandle | None = None) -> None:
        """(Re)arm for a new round: drop any primed/crossfading state.

        Any shadow still holding the floor is stopped. Promotion hands
        the shadow off to the core itself, so by the time the next
        adopt() runs the reference is already clear and nothing live
        gets stopped by accident.
        """
        if self.shadow is not None:
            try:
                self.shadow.stop()
            except (RuntimeError, AttributeError):
                pass
        self.shadow = None
        self.primed_track = None
        self.state = self.IDLE
        self.progress = 0.0
        self._ticked = 0
        self._promoted = False
        if current is not None:
            self.current = current

    def prime(self, shadow: MediaHandle, track) -> bool:
        """A resolved next track is loaded on the shadow. IDLE → PRIMED."""
        if self.state != self.IDLE or shadow is None or track is None:
            return False
        self.shadow = shadow
        self.primed_track = track
        self.state = self.PRIMED
        self._promoted = False
        self._ticked = 0
        self.progress = 0.0
        return True

    def end_of_media(self) -> bool:
        """The current track finished naturally.

        True = the crossfade took over (the caller must NOT advance the
        queue — the promotion does that, exactly once). False = fall
        back to the legacy path. Any doubt returns False: missing or
        errored shadow, crossfade off. A relay landing mid-ramp or post-
        promotion is absorbed (True, no new ramp) — THE double-advance
        guard.
        """
        if self.seconds <= 0:
            return False
        if self.state in (self.CROSSFADING, self.DONE):
            return True   # duplicate relay: already fading/faded
        if self.state != self.PRIMED or self.shadow is None or self.current is None:
            return False
        if self.shadow.error_count > 0:
            return False   # the primed stream already hiccuped — legacy path
        self.state = self.CROSSFADING
        self._steps = max(1, int(round(self.seconds * 1000 / self.tick_ms)))
        self._ticked = 0
        self.progress = 0.0
        self.shadow.set_volume(0.0)
        self.shadow.start(0)
        return True

    def tick(self) -> bool:
        """One ramp step; applies the fade pair. True when the fade ended."""
        if self.state != self.CROSSFADING:
            return False
        self._ticked += 1
        progress = min(1.0, self._ticked / self._steps)
        self.progress = progress
        cur_f, nxt_f = fade_pair(progress, self.seconds)
        if self.current is not None:
            self.current.set_volume(self.base_volume * cur_f)
        if self.shadow is not None:
            self.shadow.set_volume(self.base_volume * nxt_f)
        if progress >= 1.0 and not self._promoted:
            self._promoted = True   # exactly once, however many ticks land
            self.state = self.DONE
            if self.on_promote is not None:
                self.on_promote()
            return True
        return False

    def set_seconds(self, seconds: int) -> None:
        self.seconds = max(0, int(seconds))


class QueueEngine:
    """Pure queue logic: history, upcoming, shuffle, repeat. Fully testable."""

    def __init__(self, rng: random.Random | None = None):
        self._rng = rng or random.Random()
        self.history: list[Track] = []
        self.upcoming: list[Track] = []
        self.current: Track | None = None
        self.repeat: str = config.REPEAT_OFF
        # video ids played this session (smart shuffle never replays them)
        self._recent_ids: deque[str] = deque(maxlen=config.SMART_SHUFFLE_RECENT_IDS)

    def clear(self) -> None:
        self.history.clear()
        self.upcoming.clear()
        self.current = None
        self._recent_ids.clear()

    def start_queue(self, tracks: list[Track], start: int = 0) -> Track | None:
        """Replace the queue and start at index `start`."""
        if not tracks or not (0 <= start < len(tracks)):
            return None
        self.clear()
        self.current = tracks[start]
        self.upcoming = list(tracks[start + 1:])
        self._remember(self.current)
        return self.current

    def play_now(self, track: Track) -> Track:
        """Play immediately; the previous track goes to history."""
        if self.current is not None:
            self.history.append(self.current)
        self.current = track
        self._remember(track)
        return track

    def enqueue(self, track: Track) -> None:
        self.upcoming.append(track)

    def peek_next(self) -> Track | None:
        if self.repeat == config.REPEAT_ONE:
            return self.current
        return self.upcoming[0] if self.upcoming else None

    def advance(self) -> Track | None:
        """Move to the next track honoring repeat modes. None = queue done."""
        if self.repeat == config.REPEAT_ONE and self.current is not None:
            return self.current
        if self.current is not None:
            self.history.append(self.current)
        if not self.upcoming:
            if self.repeat == config.REPEAT_ALL and self.history:
                # Restart the queue in play order (oldest first), so the
                # first thing you heard is the first thing you hear again.
                self.upcoming = list(self.history)
                self.history = []
            else:
                self.current = None
                return None
        self.current = self.upcoming.pop(0)
        self._remember(self.current)
        return self.current

    def go_back(self) -> Track | None:
        if not self.history:
            return self.current
        if self.current is not None:
            self.upcoming.insert(0, self.current)
        self.current = self.history.pop()
        self._remember(self.current)
        return self.current

    def _remember(self, track: Track) -> None:
        """Note a track as 'played this session' (bounded deque)."""
        self._recent_ids.append(track.video_id)

    def shuffle(self) -> None:
        """Non-destructively shuffle the upcoming tracks (history untouched)."""
        self._rng.shuffle(self.upcoming)

    def shuffle_upcoming_smart(self, weights: dict[str, float] | None = None) -> None:
        """Reorder upcoming so consecutive tracks rarely share an artist.

        Greedy pass: at each step pick the candidate whose artist has
        been waiting longest (max distance since that artist last
        appeared — the current track counts as position 0). When every
        remaining candidate shares the artist, the least-recent one
        (queued longest ago) wins. Tracks already played this session
        never come back. History untouched, same multiset of ids minus
        those session replays — the non-destructive contract of
        shuffle(), just with taste.

        `weights` (video_id -> 0..1, from decayed play counts) lets
        favorites surface a little more often: a seen candidate's
        waiting distance is stretched by up to
        SMART_SHUFFLE_WEIGHT_GAIN before comparing, so a hot track wins
        its starved-but-cold sibling a touch earlier. The stretch only
        applies to artists already seen this queue — the just-played
        artist can never buy its way into an immediate encore, and
        unseen candidates keep their strict first-in-first-out grace.
        Equal weights reorder exactly like no weights at all.
        """
        if not self.upcoming:
            return
        pool = [t for t in self.upcoming if t.video_id not in self._recent_ids]
        if not pool:
            return   # everything upcoming was just played — leave it be
        gain = config.SMART_SHUFFLE_WEIGHT_GAIN

        def _boost(distance: int, track: Track) -> float:
            if distance >= _UNSEEN_DISTANCE:
                return float(distance)   # unseen artists keep queue order
            w = 0.0
            if weights:
                try:
                    w = min(max(float(weights.get(track.video_id, 0.0)), 0.0), 1.0)
                except (TypeError, ValueError):
                    w = 0.0
            return distance * (1.0 + gain * w)

        last_seen: dict[str, int] = {}
        if self.current is not None:
            last_seen[self.current.artist] = -1   # the now-playing artist just played
        picked: list[Track] = []
        while pool:
            best_i, best_d = 0, -1.0
            for i, track in enumerate(pool):
                artist = track.artist
                if artist in last_seen:
                    distance = len(picked) - last_seen[artist]
                else:
                    distance = _UNSEEN_DISTANCE
                score = _boost(distance, track)
                if score > best_d:
                    best_i, best_d = i, score   # strict >: ties keep the earliest
            chosen = pool.pop(best_i)
            last_seen[chosen.artist] = len(picked)
            picked.append(chosen)
        self.upcoming = picked

    def set_order(self, upcoming: list[Track]) -> None:
        """Replace the upcoming order exactly as given (drag & drop result)."""
        self.upcoming = list(upcoming)


class PlaybackCore(QObject):
    """Wires QueueEngine to Qt Multimedia.

    Stream resolution happens OUTSIDE this class (LoadJob on a dedicated
    pool) so audio decoding never queues behind heavy work. Once a URL is
    resolved, call set_stream() to load and play.
    """

    MAX_ERROR_SKIPS = 3   # mid-play deaths in a row before we give up

    track_changed = pyqtSignal(object)          # Track | None
    state_changed = pyqtSignal(bool)            # playing
    position_changed = pyqtSignal(int)          # ms
    duration_changed = pyqtSignal(int)          # ms
    queue_changed = pyqtSignal()
    repeat_changed = pyqtSignal(str)
    rate_changed = pyqtSignal(float)
    queue_dry = pyqtSignal(object)                # last track before the queue ran dry
    stream_lost = pyqtSignal(object, int)         # (track, resume_ms) — mid-song death
    status = pyqtSignal(str)
    preresolve_requested = pyqtSignal(object)     # Track — resolve the next stream while this one plays

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self.engine = QueueEngine()
        self.autoplay: bool = config.AUTOPLAY_DEFAULT
        self._volume = 0.8
        self._rate = 1.0
        self._player = None
        self._audio_out = None
        self._sleep_timer: QTimer | None = None
        self._fade_timer: QTimer | None = None
        self._fade_step = 0
        self._pre_fade_volume = self._volume

        # --- stream self-healing state (see config STREAM_*) ---
        self._playing = False            # mirrors the backend, minus the Qt enum
        self._last_pos_ms = 0            # last position we actually observed
        self._stream_anchor_ms = 0       # position this stream was joined at
        self._stall_polls = 0            # consecutive polls with a frozen position
        self._retries = 0                # rejoin attempts spent on the current track
        self._recovered_id: str | None = None   # which track the budget belongs to
        self._end_of_media = None        # Qt enum, resolved with the backend
        self._error_streak = 0
        self._recover_armed = True   # one error-skip per track that actually played
        self._stream_played = False  # THIS stream demonstrably produced audio

        # --- restored-session state (queue persistence, v0.7.0) ---
        self._resume_pending: Track | None = None   # waiting for the first play
        self._resume_ms = 0                         # where the song was left
        self._armed_resume_ms = 0                   # consumed by the next set_stream

        self._poll = QTimer(self)
        self._poll.setInterval(config.SEEK_POLL_MS)
        self._poll.timeout.connect(self._emit_position)

        # --- crossfade (v1.0.0 groundwork; opt-in via config.CROSSFADE_ENABLED) ---
        # With the flag off (the default) `_xf` stays None and every
        # crossfade hook below is a one-line early return: zero behavior
        # change. The controller exists at construction; the shadow
        # PLAYER is built lazily, only when a pre-resolve lands.
        self._crossfade_seconds = 0
        self._xf: CrossfadeController | None = (
            CrossfadeController(0, tick_ms=config.CROSSFADE_TICK_MS,
                                on_promote=self._xf_promote)
            if config.CROSSFADE_ENABLED else None
        )
        self._xf_timer: QTimer | None = None
        self._xf_promoted_id: str | None = None   # absorbs the app's resolve echo
        self._xf_preresolved: tuple[str, str] | None = None   # (current, next) asked for
        self._xf_primed_loudness: float | None = None
        self._xf_promoting = False   # re-entrancy brake around the promotion
        self._xf_promoted_handle: MediaHandle | None = None   # keeps the promoted wrapper alive
        # Tests swap this for a fake factory; production builds Qt twins.
        self.shadow_factory: Callable[[], MediaHandle] | None = None
        if self._xf is not None:
            self._xf.adopt(_LiveBackendHandle(self))
            # queue_changed can be emitted from outside the core (the app
            # reorders/clears the engine directly) — self-connection keeps
            # the pre-resolve re-armed no matter who moved the queue.
            self.queue_changed.connect(self._xf_maybe_preresolve)

    # --- backend (lazy so headless/CI never touches multimedia) ---

    def _ensure_backend(self) -> bool:
        if self._player is not None:
            return True
        try:
            from PyQt6.QtMultimedia import QAudioOutput, QMediaPlayer

            self._audio_out = QAudioOutput()
            self._audio_out.setVolume(self._volume)
            self._player = QMediaPlayer(self)
            self._player.setAudioOutput(self._audio_out)
            self._connect_backend()
            return True
        except Exception as exc:  # noqa: BLE001
            log.warning("audio backend unavailable: %s", exc)
            self.status.emit("Audio backend unavailable")
            return False

    def _backend_signal_slots(self) -> tuple:
        """The backend → core slot wiring, shared by connect/disconnect."""
        return (
            ("playbackStateChanged", self._on_playback_state),
            ("mediaStatusChanged", self._on_media_status),
            ("errorOccurred", self._on_error),
            ("durationChanged", self.duration_changed.emit),
        )

    def _connect_backend(self) -> None:
        """Wire the current backend's signals into the core slots.

        Duck-typed on purpose: promotion re-runs this against whatever
        object now fronts `self._player` (a real QMediaPlayer, or a test
        fake that happens to expose Qt-style signals).
        """
        player = self._player
        if player is None:
            return
        for name, slot in self._backend_signal_slots():
            signal = getattr(player, name, None)
            if signal is not None:
                try:
                    signal.connect(slot)
                except (TypeError, RuntimeError):
                    pass

    def _disconnect_backend(self) -> None:
        """Cut every backend → core signal (promotion tears the old primary down)."""
        player = self._player
        if player is None:
            return
        for name, slot in self._backend_signal_slots():
            signal = getattr(player, name, None)
            if signal is not None:
                try:
                    signal.disconnect(slot)
                except (TypeError, RuntimeError):
                    pass

    # --- playback ---

    def play_track(self, track: Track) -> None:
        """Mark a track current; the app resolves its stream, then calls set_stream()."""
        self._error_streak = 0   # user-driven movement: fresh faith in the backend
        self._resume_pending = None
        self._resume_ms = 0
        self._xf_promoted_id = None   # user movement: any pending echo is void
        self._xf_cancel_user()
        self.engine.play_now(track)
        self.track_changed.emit(track)
        self.queue_changed.emit()

    def start_queue(self, tracks: list[Track], start: int = 0) -> None:
        self._error_streak = 0
        self._resume_pending = None
        self._resume_ms = 0
        self._xf_promoted_id = None   # user movement: any pending echo is void
        self._xf_cancel_user()
        first = self.engine.start_queue(tracks, start)
        self.queue_changed.emit()
        if first is not None:
            self.track_changed.emit(first)

    def enqueue(self, track: Track) -> None:
        self.engine.enqueue(track)
        self.queue_changed.emit()

    def restore_queue(
        self,
        current: Track | None,
        history: list[Track] | None = None,
        upcoming: list[Track] | None = None,
        resume_ms: int = 0,
    ) -> None:
        """Rebuild the last session's queue without making a sound.

        The queue comes back exactly as it was left. No track_changed is
        emitted, so nothing resolves, nothing plays — pressing play
        resumes the current track at `resume_ms` instead of starting cold.
        """
        self.engine.clear()
        self.engine.history = list(history or [])
        self.engine.current = current
        self.engine.upcoming = list(upcoming or [])
        self._resume_pending = current
        self._resume_ms = max(0, int(resume_ms))
        self.queue_changed.emit()

    def toggle(self) -> None:
        if self._resume_pending is not None:
            # A restored session waiting for its first play: resolve the
            # stream and let set_stream() rejoin at the saved position.
            track = self._resume_pending
            self._armed_resume_ms = self._resume_ms
            self._resume_pending = None
            self._resume_ms = 0
            self.track_changed.emit(track)
            return
        # Pausing or resuming mid-crossfade ends the fade honestly: the
        # primed/rolling shadow is stopped, the old primary keeps the room.
        self._xf_cancel_user()
        if not self._ensure_backend():
            return
        from PyQt6.QtMultimedia import QMediaPlayer

        state = self._player.playbackState()
        if state == QMediaPlayer.PlaybackState.PlayingState:
            self._player.pause()
        else:
            self._player.play()

    def next(self) -> None:
        last = self.engine.current
        track = self.engine.advance()
        self.queue_changed.emit()
        if track is None:
            if self.autoplay and last is not None:
                # Spotify-style autoplay: the queue ran dry, ask for a radio
                # refill around the last track instead of stopping cold.
                self.status.emit("Queue empty — extending radio…")
                self.queue_dry.emit(last)
                return
            self.stop()
            self.status.emit("Queue finished")
            return
        self.track_changed.emit(track)

    def previous(self) -> None:
        self._error_streak = 0
        self._xf_promoted_id = None   # user movement: any pending echo is void
        self._xf_cancel_user()
        track = self.engine.go_back()
        self.queue_changed.emit()
        if track is not None:
            self.track_changed.emit(track)

    def stop(self) -> None:
        self._xf_cancel_user()
        if self._player is not None:
            self._player.stop()
        self._poll.stop()
        self._playing = False
        self.state_changed.emit(False)

    def shuffle(self) -> None:
        self.engine.shuffle()
        self.queue_changed.emit()

    def shuffle_smart(self, weights: dict[str, float] | None = None) -> None:
        """Opt-in smart shuffle: spread artists through the upcoming queue.

        Same contract as shuffle() — upcoming only, history untouched,
        one queue_changed — so nothing in the stream/error paths cares.
        `weights` (video_id -> 0..1) let favorites surface a little
        more often; None keeps the pure artist-spread order.
        """
        self.engine.shuffle_upcoming_smart(weights)
        self.queue_changed.emit()

    def set_repeat(self, mode: str) -> None:
        if mode not in config.REPEAT_MODES:
            return
        self.engine.repeat = mode
        self.repeat_changed.emit(mode)

    def set_autoplay(self, enabled: bool) -> None:
        self.autoplay = bool(enabled)

    def cycle_repeat(self) -> str:
        order = list(config.REPEAT_MODES)
        nxt = order[(order.index(self.engine.repeat) + 1) % len(order)]
        self.set_repeat(nxt)
        return nxt

    def next_rate(self) -> float:
        rates = list(config.PLAYBACK_RATES)
        idx = rates.index(self._rate) if self._rate in rates else rates.index(1.0)
        self.set_rate(rates[(idx + 1) % len(rates)])
        return self._rate

    def set_rate(self, rate: float) -> None:
        rate = max(0.5, min(2.5, float(rate)))
        self._rate = rate
        if self._player is not None:
            self._player.setPlaybackRate(rate)
        self.rate_changed.emit(rate)

    # --- crossfade + gapless pre-resolve (v1.0.0 groundwork) ---

    @property
    def crossfade_seconds(self) -> int:
        """Crossfade length in whole seconds; 0 = off."""
        return self._crossfade_seconds

    def set_crossfade(self, seconds: int) -> None:
        """Set the crossfade length (whole seconds, 0 = off).

        Clamped to 0..CROSSFADE_MAX_MS//1000. Live: switching off drops
        a primed shadow (nothing would ever use it); a ramp already in
        flight is left to finish so the promotion lands cleanly.
        """
        limit = max(0, int(config.CROSSFADE_MAX_MS) // 1000)
        try:
            seconds = int(seconds)
        except (TypeError, ValueError):
            seconds = 0
        seconds = max(0, min(limit, seconds))
        self._crossfade_seconds = seconds
        if self._xf is not None:
            self._xf.set_seconds(seconds)
            if (seconds <= 0
                    and self._xf.state == CrossfadeController.PRIMED):
                self._xf.adopt(self._xf.current)   # drop the useless shadow

    def _make_shadow(self) -> MediaHandle | None:
        """Build a second player. Tests inject `shadow_factory` fakes."""
        factory = self.shadow_factory
        if factory is not None:
            return factory()
        try:
            return QtMediaHandle(self)
        except Exception as exc:  # noqa: BLE001 - no backend, no crossfade
            log.warning("crossfade shadow unavailable: %s", exc)
            return None

    def _xf_maybe_preresolve(self) -> None:
        """Ask the app layer to resolve the next stream while this one plays.

        One request per (current, next) pair — cached; a queue change
        re-arms automatically via the self-connected queue_changed.
        Failures are silent by contract: the app drops them and the
        normal EndOfMedia path resolves fresh as always.
        """
        ctl = self._xf
        if ctl is None or ctl.seconds <= 0:
            return
        if ctl.state != CrossfadeController.IDLE:
            return   # already primed (or fading) — nothing to pre-resolve
        current = self.engine.current
        nxt = self.engine.peek_next()
        if current is None or nxt is None or not self._playing:
            return
        pair = (current.video_id, nxt.video_id)
        if pair == self._xf_preresolved:
            return   # asked for exactly this one already
        self._xf_preresolved = pair
        self.preresolve_requested.emit(nxt)

    def prime_shadow(self, track: Track, url: str,
                     loudness_db: float | None = None) -> None:
        """A pre-resolve landed: load the next track onto the shadow player.

        Called by the app layer when the preresolve_requested job came
        back. Stale results — queue moved on, already primed, crossfade
        off — are dropped silently; the normal EndOfMedia path always
        works. The shadow is built lazily HERE, so with the flag on but
        nothing queued, no second player ever exists.
        """
        ctl = self._xf
        if ctl is None or not url:
            return
        if ctl.seconds <= 0 or ctl.state != CrossfadeController.IDLE:
            return
        nxt = self.engine.peek_next()
        if nxt is None or nxt.video_id != track.video_id:
            return   # the queue moved on while we were resolving
        handle = self._make_shadow()
        if handle is None:
            return
        try:
            handle.load(url)
        except Exception as exc:  # noqa: BLE001 - a dead pre-resolve is silent
            log.debug("shadow load failed for %s: %s", track.video_id, exc)
            return
        handle.set_rate(self._rate)
        handle.set_volume(0.0)
        self._xf_primed_loudness = loudness_db
        if not ctl.prime(handle, track):   # lost a race: give the handle back
            handle.stop()

    def _xf_cancel_user(self) -> None:
        """User-driven movement ends crossfade business immediately.

        Crossfade only ever engages on the NATURAL EndOfMedia path; a
        skip, a queue jump or a pause while a shadow exists must not let
        the primed track start playing out from under the user.
        """
        ctl = self._xf
        if ctl is None:
            return
        self._xf_stop_timer()
        if ctl.state in (CrossfadeController.PRIMED, CrossfadeController.CROSSFADING):
            ctl.adopt(ctl.current)   # stop + drop the shadow

    def _xf_stop_timer(self) -> None:
        if self._xf_timer is not None:
            self._xf_timer.stop()

    def _xf_start_timer(self) -> None:
        if self._xf is None:
            return
        if self._xf_timer is None:
            self._xf_timer = QTimer(self)
            self._xf_timer.setInterval(self._xf.tick_ms)
            self._xf_timer.timeout.connect(self._xf_tick)
        self._xf_timer.start()

    def _xf_tick(self) -> None:
        """One ramp step (the existing fade-timer pattern, per-handle)."""
        if self._xf is None:
            self._xf_stop_timer()
            return
        if self._xf.tick():    # finished — on_promote already ran inside
            self._xf_stop_timer()

    def _xf_engage(self) -> bool:
        """Natural EndOfMedia + a healthy primed shadow → start the ramp.

        Returns True when the crossfade took over (the caller must NOT
        advance the queue — the promotion does that, exactly once). Any
        doubt returns False and the legacy next() path runs exactly as
        v0.6.3 left it. NEVER engages on errors, rejoin, skip, or manual
        movement — those all pass through _xf_cancel_user or never reach
        _on_end_of_media at all.
        """
        ctl = self._xf
        if ctl is None or ctl.seconds <= 0:
            return False
        if ctl.state in (CrossfadeController.CROSSFADING,
                         CrossfadeController.DONE):
            # A second EndOfMedia relay while the ramp is running (or
            # just finished): absorbed. The promotion advances the queue
            # exactly once — this return is THE double-advance guard.
            return True
        if ctl.state != CrossfadeController.PRIMED:
            return False
        if ctl.shadow is None or ctl.shadow.error_count > 0:
            ctl.adopt(ctl.current)   # a sick shadow is no better than none
            return False
        track = ctl.primed_track
        nxt = self.engine.peek_next()
        if track is None or nxt is None or nxt.video_id != track.video_id:
            ctl.adopt(ctl.current)   # the queue moved on since priming
            return False
        if not ctl.end_of_media():
            return False
        self._xf_start_timer()
        return True

    def _xf_promote(self) -> None:
        """Ramp finished: the shadow becomes THE primary — exactly once.

        The promotion rebuilds the exact backend wiring _ensure_backend()
        creates, then resets the stream-healing ledger for the new stream
        (fresh rejoin budget, proof-of-audio gate, stall counters), so
        the v0.6.3 machinery — stall watchdog, mid-song rejoin, bounded
        error skips — watches the NEW primary from a clean slate. Then it
        advances the queue ONCE: this call IS the EndOfMedia relay for
        the crossed-over track. The app's resolve echo of that advance
        is absorbed by the _xf_promoted_id guard in set_stream(), so the
        freshly promoted stream is never reloaded mid-air.
        """
        ctl = self._xf
        shadow, track = (ctl.shadow, ctl.primed_track) if ctl else (None, None)
        if shadow is None or track is None or self._xf_promoting:
            return
        self._xf_promoting = True
        try:
            # 1) cut the old primary's signals, then silence and stop it.
            #    setAudioOutput(None) first so the retired QAudioOutput can
            #    be released without leaving the old player a dangling view.
            self._disconnect_backend()
            old_player = self._player
            if old_player is not None:
                try:
                    old_player.setAudioOutput(None)
                except (RuntimeError, AttributeError, TypeError):
                    pass
                try:
                    old_player.stop()
                except (RuntimeError, AttributeError):
                    pass
            # 2) adopt the shadow as the backend: a QtMediaHandle hands
            #    over its inner QMediaPlayer/QAudioOutput pair; any other
            #    MediaHandle (test fakes) stands in as the backend
            #    directly — the core duck-types self._player either way.
            self._player = getattr(shadow, "player", shadow)
            audio = getattr(shadow, "audio", None)
            if audio is not None:
                self._audio_out = audio
            self._xf_promoted_handle = shadow   # own the wrapper: it holds the audio
            self._connect_backend()
            # 3) clean healing ledger for the new stream — the same reset
            #    set_stream() performs, so nothing carries over.
            self._recovered_id = track.video_id
            self._retries = 0
            self._stream_played = False
            self._stream_anchor_ms = 0
            self._stall_polls = 0
            self._last_pos_ms = 0
            self._playing = True   # the shadow is audibly rolling
            self._poll.start()
            self.state_changed.emit(True)
            self.apply_normalization(self._xf_primed_loudness)
            duration = max(0, int(shadow.duration_ms))
            if duration:
                self.duration_changed.emit(duration)
            # 4) exactly ONE queue advance — the promotion is the relay.
            self.next()
            self._xf_promoted_id = track.video_id   # absorb the resolve echo
            # 5) hand the controller a fresh round (shadow reference is
            #    consumed — the promoted handle now lives as the backend).
            ctl.shadow = None
            ctl.primed_track = None
            ctl.state = CrossfadeController.IDLE
            ctl.progress = 0.0
            ctl.current = _LiveBackendHandle(self)
            self._xf_maybe_preresolve()
        finally:
            self._xf_promoting = False

    # --- volume / seek ---

    def set_volume(self, value: float) -> None:
        self._volume = max(0.0, min(1.0, float(value)))
        if self._audio_out is not None:
            self._audio_out.setVolume(self._volume)
        if self._xf is not None:
            self._xf.base_volume = self._volume   # keep the ramp scaled to master

    @property
    def volume(self) -> float:
        return self._volume

    @property
    def rate(self) -> float:
        return self._rate

    @property
    def is_playing(self) -> bool:
        """True while the backend reports audio flowing (no Qt enums)."""
        return self._playing

    @property
    def position_ms(self) -> int:
        """Best-known position: the live backend if present, else observed."""
        if self._player is not None:
            try:
                return int(self._player.position())
            except (RuntimeError, AttributeError):
                pass
        return self._last_pos_ms

    @property
    def session_position_ms(self) -> int:
        """Where a restored session would resume; the live position otherwise."""
        if self._resume_pending is not None:
            return self._resume_ms
        return self.position_ms

    def _effective_resume(self, resume_ms: int) -> int:
        """Explicit resume wins; else a restored-session resume, once."""
        explicit = max(0, int(resume_ms))
        if explicit:
            return explicit
        armed, self._armed_resume_ms = self._armed_resume_ms, 0
        return max(0, int(armed))

    def seek(self, position_ms: int) -> None:
        if self._player is not None:
            self._player.setPosition(int(position_ms))

    def apply_normalization(self, loudness_db: float | None) -> float:
        """Scale audio output by the track's loudness gain (returns gain dB)."""
        from .stream import normalization_gain

        gain = normalization_gain(loudness_db)
        if self._audio_out is not None and gain != 0.0:
            self._audio_out.setVolume(self._volume * (10 ** (gain / 20)))
        return gain

    # --- sleep timer with gentle fade ---

    def set_sleep_timer(self, minutes: int | None) -> None:
        if self._sleep_timer is not None:
            self._sleep_timer.stop()
            self._sleep_timer = None
        if self._fade_timer is not None:
            self._fade_timer.stop()
            self._fade_timer = None
            self.set_volume(self._pre_fade_volume)
        if not minutes:
            self.status.emit("Sleep timer cancelled")
            return
        self._sleep_timer = QTimer(self)
        self._sleep_timer.setSingleShot(True)
        self._sleep_timer.timeout.connect(self._begin_fade)
        self._sleep_timer.start(int(minutes) * 60_000)
        self.status.emit(f"Sleeping in {minutes} min")

    def _begin_fade(self) -> None:
        self._pre_fade_volume = self._volume
        self._fade_step = 0
        self._fade_timer = QTimer(self)
        self._fade_timer.setInterval(max(1, config.FADE_INTERVAL_MS // config.FADE_STEPS))
        self._fade_timer.timeout.connect(self._fade_tick)
        self._fade_timer.start()

    def _fade_tick(self) -> None:
        self._fade_step += 1
        if self._fade_step >= config.FADE_STEPS:
            if self._fade_timer is not None:
                self._fade_timer.stop()
                self._fade_timer = None
            self.stop()
            self.set_volume(self._pre_fade_volume)
            self.status.emit("Sleep timer: paused")
            return
        factor = 1.0 - (self._fade_step / config.FADE_STEPS)
        self.set_volume(self._pre_fade_volume * factor)

    # --- internals ---

    def set_stream(
        self,
        track: Track,
        url: str,
        loudness_db: float | None = None,
        resume_ms: int = 0,
    ) -> None:
        """Load a resolved stream URL and start playing (LoadJob callback).

        `resume_ms` rejoins a track that died mid-song: the position it
        stopped at, minus a small backstep so a truncating stream can't
        tip us straight back into end-of-media.
        """
        if not self._ensure_backend():
            return
        if self.engine.current is not None and self.engine.current.video_id != track.video_id:
            return  # user moved on while we were resolving
        if (self._xf_promoted_id == track.video_id
                and self.engine.current is not None
                and self.engine.current.video_id == track.video_id):
            # A crossfade promotion already started this very track on
            # the new primary; this is the app's resolve echo of that
            # advance. Refresh gain + rate, but never touch the source —
            # reloading it would restart the song mid-fade.
            self._xf_promoted_id = None
            self.apply_normalization(loudness_db)
            self._player.setPlaybackRate(self._rate)
            return
        if self._recovered_id != track.video_id:
            self._recovered_id = track.video_id
            self._retries = 0  # a fresh track gets a fresh budget
        self.apply_normalization(loudness_db)
        from PyQt6.QtCore import QUrl

        rejoin_ms = self._effective_resume(resume_ms)
        rejoin = max(0, rejoin_ms - config.STREAM_RESUME_BACKSTEP_MS) if rejoin_ms else 0
        self._player.setSource(QUrl(url))
        self._player.setPlaybackRate(self._rate)
        self._player.play()
        if rejoin:
            self._player.setPosition(rejoin)
        self._poll.start()
        self._playing = True  # the backend signal confirms or corrects
        self._stream_played = False  # nothing proven until audio flows
        self._last_pos_ms = rejoin
        self._stream_anchor_ms = rejoin
        self._stall_polls = 0
        self.state_changed.emit(True)
        self._xf_rearm()
        self._xf_maybe_preresolve()

    def _try_rejoin(self, track: Track, reason: str) -> bool:
        """Ask for a freshly resolved URL and rejoin this very song.

        Budget-guarded (config STREAM_*): the budget renews once the
        stream has played healthily for a while, so one flaky minute
        can't strand the session — but a truly dead track falls through
        to the error-skip path after a few honest tries.
        """
        if self._last_pos_ms - self._stream_anchor_ms >= config.STREAM_RECOVERY_RESET_MS:
            self._retries = 0   # it genuinely played — this is a new mishap
        if self._recovered_id != track.video_id:
            self._recovered_id = track.video_id
            self._retries = 0
        if self._retries >= config.STREAM_MAX_RECOVERIES:
            return False
        self._retries += 1
        self.status.emit(f"Stream {reason} — picking it back up…")
        self.stream_lost.emit(track, int(self._last_pos_ms))
        return True

    def _on_playback_state(self, state) -> None:
        from PyQt6.QtMultimedia import QMediaPlayer

        self._note_playing(state == QMediaPlayer.PlaybackState.PlayingState)

    def _note_playing(self, playing: bool) -> None:
        self._playing = playing
        if playing:
            self._recover_armed = True   # audio actually flowed — re-arm the skip guard
            self._stream_played = True   # and this stream is genuinely underway
        self.state_changed.emit(playing)

    def _on_media_status(self, status) -> None:
        from PyQt6.QtMultimedia import QMediaPlayer

        if status != QMediaPlayer.MediaStatus.EndOfMedia:
            return
        self._on_end_of_media()

    def _on_end_of_media(self) -> None:
        """Track finished naturally — roll straight into the next one.

        The v0.2.0 rewrite of the audio core dropped the v0.1.0
        EndOfMedia relay: tracks ended and playback went silent instead
        of advancing. This restores it (repeat modes and autoplay are
        already handled by next() and the queue_dry -> radio refill
        chain in the app layer).

        With crossfade armed and a healthy primed shadow, the fade takes
        over instead: the queue advance moves to the END of the ramp
        (the promotion), exactly once.
        """
        log.debug("track finished — rolling into the next one")
        self._error_streak = 0   # a natural finish proves the pipeline is healthy
        if self._xf_engage():
            return
        self.next()

    def _xf_rearm(self) -> None:
        """A fresh stream just took the primary: settle crossfade state.

        A primed shadow that is STILL the queue's next track survives
        (the pre-resolve stays valid); anything else — stale prime,
        ramp-in-flight — is cancelled so the new track starts clean.
        """
        ctl = self._xf
        if ctl is None:
            return
        self._xf_stop_timer()
        if ctl.state == CrossfadeController.IDLE:
            return
        nxt = self.engine.peek_next()
        if (ctl.state == CrossfadeController.PRIMED
                and ctl.primed_track is not None
                and nxt is not None
                and nxt.video_id == ctl.primed_track.video_id):
            return   # still the right next track — keep the primed shadow
        ctl.adopt(ctl.current)

    def _on_error(self, err, err_str: str) -> None:
        log.warning("player error: %s", err_str)
        ctl = self._xf
        if ctl is not None and ctl.state == CrossfadeController.CROSSFADING:
            # An error from the outgoing stream mid-ramp (it is already
            # finished by definition — there is nothing to heal): absorb
            # it. The promotion moments later rebuilds the whole healing
            # machinery around the new primary.
            return
        self._playing = False   # the backend just said otherwise; believe it
        self.state_changed.emit(False)
        current = self.engine.current
        if current is None:
            self.status.emit(f"Playback error: {err_str}")
            return
        # A mid-song death on a stream that audibly played: rejoin it
        # where it stopped. A stream that NEVER opened (dead URL, CDN
        # 403) has no song to rejoin — position alone can't vouch for
        # it (a restored session sits at its resume position before the
        # first byte arrives), and re-feeding the same dead URL is
        # exactly the 'Could not open media' spam storm of v0.6.3.
        if self._stream_played and self._last_pos_ms > 0 and self._try_rejoin(current, "dropped"):
            return
        self._skip_or_stop(current)

    def _skip_or_stop(self, current: Track | None) -> None:
        """One stream proved dead past all healing: skip it once, or stop.

        The shared end of every failure path — backend error, watchdog
        stall, refused rejoin — so a sick pipeline always ends in the
        same bounded, honest way: at most MAX_ERROR_SKIPS single-shot
        skips (each one re-armed by real audio), then a clean stop.
        """
        if current is None:
            self.stop()
            return
        if not self._recover_armed or self._error_streak >= self.MAX_ERROR_SKIPS:
            self.stop()
            self.status.emit("Playback stopped — too many errors in a row")
            return
        self._recover_armed = False
        self._error_streak += 1
        log.warning("recovering from dead stream — skipping %s", current.title)
        self.status.emit("Skipping past the bad stream…")
        self.next()

    def _emit_position(self) -> None:
        if self._player is None:
            return
        ctl = self._xf
        if ctl is not None and ctl.state == CrossfadeController.CROSSFADING:
            # Mid-fade the outgoing stream is finished by definition, so
            # the stall watchdog has nothing to heal — stand it down and
            # report the position of the track that is actually audible.
            try:
                pos = (ctl.shadow.position_ms
                       if ctl.shadow is not None else self._player.position())
            except (RuntimeError, AttributeError):
                pos = 0
            self.position_changed.emit(int(pos))
            return
        pos = self._player.position()
        if self._playing and pos == self._last_pos_ms:
            # "Playing" but going nowhere — and the backend never said
            # otherwise (a media that never opened sits in StoppedState
            # and emits nothing, so _playing stays stale-True forever).
            # Two sicknesses: a stream that played and froze wants a
            # rejoin; one that never opened at all wants a bounded skip
            # — re-feeding it was the other half of the v0.6.3 storm.
            if not self._forgiving_status():
                self._stall_polls += 1
                if self._stall_polls >= config.STALL_POLLS:
                    self._stall_polls = 0
                    current = self.engine.current
                    healed = (
                        self._stream_played
                        and current is not None
                        and self._try_rejoin(current, "stalled")
                    )
                    if not healed:
                        self._playing = False
                        self._skip_or_stop(current)
            # else: loading/buffering — alive, just shy; give it air
        else:
            self._stall_polls = 0
            if pos > 0:
                self._stream_played = True   # audio demonstrably flowing
            self._last_pos_ms = pos
        self.position_changed.emit(pos)

    def _forgiving_status(self) -> bool:
        """True while the backend is merely loading/buffering.

        Judged by position alone, a slow open looks exactly like a dead
        stream — this grace keeps slow networks off the stall-skip
        path. Detached/fake backends (no mediaStatus) get no grace and
        are judged by position, as before.
        """
        try:
            return self._player.mediaStatus() in _waiting_statuses()
        except (RuntimeError, AttributeError):
            return False
