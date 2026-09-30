"""Application lifecycle: wiring, persistence, hotkeys, logging."""

from __future__ import annotations

import json
import logging
import random
import sys
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path

from PyQt6.QtCore import (
    QObject,
    QRunnable,
    QSettings,
    QStandardPaths,
    Qt,
    QTimer,
    QThreadPool,
    QtMsgType,
    pyqtSignal,
)
from PyQt6.QtGui import QAction, QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QApplication,
    QFileDialog,
    QMenu,
    QMessageBox,
    QSystemTrayIcon,
)

from . import config, plugins, theme, world, ytm_resilience
from .ambient import AmbientChannel
from .catalog import Catalog
from .command_palette import CommandAction, CommandPalette
from .diagnostics import gather_report
from .discord_presence import (
    AVAILABLE as DISCORD_AVAILABLE,
    DiscordPresence,
    Throttle,
)
from .hotkeys import effective_chords
from .jobs import (
    AlbumJob,
    ArtistJob,
    ArtistLookupJob,
    DiscoverJob,
    LoadJob,
    LyricsJob,
    RadioJob,
    ScopedSearchJob,
    SearchJob,
    WorldJob,
    _SignalCarrier,
)
from .local_scan import LocalScanJob
from .lyrics import SyncedLyrics
from .lyrics_overlay import LyricsOverlay
from .models import Album, Artist, Collection, Track
from .mpris import MPRIS_AVAILABLE, MprisService
from .panel import FloatingPanel
from .player import PlaybackCore
from .remote import RemoteServer
from .storage import HearthStore
from .theme import lyrics_font
from .toast import NowPlayingToast
from .tray import HearthTray, InstanceGuard
from .update_whisper import UpdateWhisper
from .window import DiagnosticsDialog, MainWindow, StylePickerDialog

log = logging.getLogger(__name__)

# Module-level registry of in-flight QRunnables. Python must keep each job
# wrapper (and its signal carrier) alive until the pool thread finishes
# run() — an instance-level ref dies with the Hearth object, but a worker
# thread can outlive it and would emit into a deleted carrier.
_INFLIGHT: set = set()

# Tray labels for the ambient soundscapes (kind -> display name).
AMBIENT_KIND_LABELS = {
    "campfire": "🏕 Campfire",
    "cafe": "☕ Café",
    "rain": "🌧 Rain",
}


def data_dir() -> Path:
    """Per-OS app data directory (Linux: ~/.local/share/Hearth)."""
    base = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppDataLocation)
    path = Path(base)
    path.mkdir(parents=True, exist_ok=True)
    return path


def setup_logging(directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(
        directory / "hearth.log",
        maxBytes=config.LOG_MAX_BYTES,
        backupCount=config.LOG_BACKUPS,
        encoding="utf-8",
    )
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    handler.setFormatter(fmt)
    logging.basicConfig(level=logging.INFO, handlers=[handler])
    _install_qt_log_bridge()


def _qt_message(mode, context, message) -> None:  # noqa: ANN001 - Qt's signature
    """One Qt message, routed into Python's logging instead of stderr.

    Qt prints straight to the process stderr — one failed stream open
    used to paint the terminal with endless 'Could not open media'
    lines (v0.6.3). The bridge lands every Qt message in hearth.log
    instead: the playback firehose at DEBUG, everything else at its
    natural severity. Defensive throughout — this runs for every Qt
    message, on any thread, possibly during interpreter teardown.
    """
    try:
        raw = getattr(context, "category", b"") or b""
        category = (
            raw.decode("utf-8", "replace")
            if isinstance(raw, (bytes, bytearray)) else str(raw)
        )
        text = (
            message.decode("utf-8", "replace")
            if isinstance(message, (bytes, bytearray)) else str(message)
        )
        logger = logging.getLogger(f"qt.{category}" if category else "qt")
        if category.startswith("qt.multimedia"):
            level = logging.DEBUG   # per-attempt backend chatter: file-only, quiet
        else:
            level = {
                QtMsgType.QtDebugMsg: logging.DEBUG,
                QtMsgType.QtInfoMsg: logging.INFO,
                QtMsgType.QtWarningMsg: logging.WARNING,
                QtMsgType.QtCriticalMsg: logging.ERROR,
                QtMsgType.QtFatalMsg: logging.CRITICAL,
            }.get(mode, logging.WARNING)
        logger.log(level, "%s", text)
    except Exception:  # noqa: BLE001 - a dying log must never take the app down
        pass


def _install_qt_log_bridge() -> None:
    """Replace Qt's default stderr printer with `_qt_message` (best effort)."""
    try:
        from PyQt6.QtCore import qInstallMessageHandler

        qInstallMessageHandler(_qt_message)
    except Exception:  # noqa: BLE001 - no PyQt6 here: keep the default behavior
        pass


class _PluginShelfJob(QRunnable):
    """Calls registered plugin shelf sources off the UI thread.

    A source may do anything (that is the plugin's business) — which is
    exactly why it runs here and not on the main thread. Its Track-shaped
    dicts are coerced defensively: junk entries are dropped, not fatal.
    """

    def __init__(self, sources: dict):
        super().__init__()
        self.setAutoDelete(False)
        self.signals = _SignalCarrier()
        self.sources = dict(sources)

    def run(self) -> None:
        results: list[tuple[str, list[Track]]] = []
        failures: list[tuple[str, str]] = []
        for name, fn in self.sources.items():
            try:
                raw = fn() or []
            except Exception as exc:   # noqa: BLE001 - the plugin boundary
                failures.append((name, str(exc)))
                continue
            tracks = [t for t in (_coerce_track(e) for e in raw) if t]
            results.append((name, tracks))
        self.signals.emit_safe(self.signals.finished, (results, failures))


def _coerce_track(entry) -> Track | None:
    """A Track, or a Track-shaped dict, or None (garbage in, nothing out)."""
    if isinstance(entry, Track):
        return entry if entry.video_id and entry.title else None
    if not isinstance(entry, dict):
        return None
    try:
        track = Track.from_dict(entry)
    except (TypeError, ValueError):
        return None
    return track if track.video_id and track.title else None


class GlowMixJob(QRunnable):
    """Harvests kindred tracks for the Glow Mix on the job pool.

    For each seed (the top track of a top rotation artist) it rides the
    same Start Radio plumbing RadioJob uses — ``catalog.radio(video_id)``
    — which returns real playable tracks from kindred artists. Seeds
    that fail are quietly skipped; the app falls back to the rotation
    alone when the whole harvest comes up empty.
    """

    def __init__(self, catalog: Catalog, seeds: list[Track],
                 rotation: list[Track]):
        super().__init__()
        self.setAutoDelete(False)
        self.signals = _SignalCarrier()
        self.catalog = catalog
        self.seeds = list(seeds)
        self.rotation = list(rotation)

    def run(self) -> None:  # noqa: D102 - QRunnable entry
        kindred: list[Track] = []
        for seed in self.seeds:
            try:
                kindred.extend(
                    self.catalog.radio(seed.video_id, limit=config.RADIO_LIMIT))
            except Exception:  # noqa: BLE001 - a bad seed costs nothing
                continue
        self.signals.emit_safe(self.signals.finished,
                               (list(self.rotation), kindred))


def glow_seeds(rotation: list[Track], limit: int) -> list[Track]:
    """One seed per distinct artist from the top of the rotation (pure).

    The blend wants breadth, not more of the same act — so the first
    track of every distinct artist becomes a seed, rotation order kept.
    Artist-less tracks still seed (their video_id stand in) so a
    rotation of one-off uploads can blend too.
    """
    seeds: list[Track] = []
    seen_artists: set[str] = set()
    seen_ids: set[str] = set()
    for track in rotation:
        if track.video_id in seen_ids:
            continue
        artist = (getattr(track, "artist", "") or "").strip().lower()
        key = artist or f"id:{track.video_id}"
        if key in seen_artists:
            continue
        seen_artists.add(key)
        seen_ids.add(track.video_id)
        seeds.append(track)
        if len(seeds) >= max(1, int(limit)):
            break
    return seeds


def blend_glow(rotation: list[Track], kindred: list[Track],
               size: int) -> list[Track]:
    """The Glow Mix blend — pure, deterministic, deduped by video_id.

    ~60% rotation (config.GLOW_MIX_ROTATION_SHARE), the rest kindred
    tracks, capped at `size`; rotation wins duplicates. A thin kindred
    harvest is topped up from the rest of the rotation, so the mix is
    never shorter than the music we already know.
    """
    size = max(0, int(size))
    if size == 0:
        return []
    rot: list[Track] = []
    seen: set[str] = set()
    for track in rotation:
        if track.video_id in seen:
            continue
        seen.add(track.video_id)
        rot.append(track)
    kin: list[Track] = []
    for track in kindred:
        if track.video_id in seen:
            continue
        seen.add(track.video_id)
        kin.append(track)
    n_rot = min(len(rot), round(size * config.GLOW_MIX_ROTATION_SHARE))
    mix = rot[:n_rot]
    mix.extend(kin[: size - len(mix)])
    if len(mix) < size:   # kindred ran dry — let the rotation fill the rest
        mix.extend(rot[n_rot: n_rot + (size - len(mix))])
    return mix[:size]


def _i18n_label(key: str, fallback: str) -> str:
    """A tray label through the i18n scaffold (guarded — never fatal).

    The scaffold is opt-in by config.I18N_LANG: while it stays "en",
    the hand-written literals win (same words, zero lookups). When a
    key is missing from every table, the readable fallback wins too —
    the tray never shows a raw msg_key. Any surprise in the lookup
    path costs a label, never the tray.
    """
    try:
        lang = getattr(config, "I18N_LANG", "en")
        if lang and lang != "en":
            from .i18n import tr

            translated = tr(key, lang)
            return fallback if translated == key else translated
    except Exception:  # noqa: BLE001 - a label must never kill the tray
        pass
    return fallback


class AlarmController(QObject):
    """Wake-up alarm: a one-shot deadline that fades the fire back up.

    Pure and headless-testable: the only time source is an injectable
    clock (ms). The app wires `fired` to the fade-in and polls `poll()`
    from a cheap timer; tests drive the clock by hand. Scheduling again
    replaces the pending alarm; there is exactly one at a time and
    nothing is ever persisted.
    """

    fired = pyqtSignal()

    def __init__(self, clock=None, parent=None):
        super().__init__(parent)
        self._now = clock or (lambda: int(time.monotonic() * 1000))
        self._deadline: int | None = None

    @property
    def armed(self) -> bool:
        return self._deadline is not None

    def schedule(self, minutes: float) -> int:
        """Arm (or re-arm) the alarm; returns the deadline in clock ms."""
        minutes = max(0.0, float(minutes))
        self._deadline = self._now() + int(minutes * 60_000)
        return self._deadline

    def cancel(self) -> None:
        """Disarm silently (no fire, no fuss)."""
        self._deadline = None

    def remaining_ms(self) -> int:
        """Ms until the fire; 0 once disarmed (or already due)."""
        if self._deadline is None:
            return 0
        return max(0, self._deadline - self._now())

    def poll(self) -> bool:
        """Fire if due (one-shot: disarmed first, then the signal). True on fire."""
        if self._deadline is None or self._now() < self._deadline:
            return False
        self._deadline = None
        self.fired.emit()
        return True


class Hearth:
    """Owns every component; one instance per process."""

    def __init__(
        self,
        argv: list[str] | None = None,
        settings_path: str | None = None,
        data_directory: Path | None = None,
        single_instance: bool = True,
        enable_streaming: bool = True,
        ui_mode: str | None = None,
    ):
        # Qt allows exactly one QApplication per process — reuse it if the
        # host already created one (tests, embeddings, launcher wrappers).
        self.qapp = QApplication.instance() or QApplication(
            argv if argv is not None else ["hearth"]
        )
        self.qapp.setApplicationName(config.APP_NAME)
        self.qapp.setOrganizationName(config.ORG_NAME)
        self.qapp.setQuitOnLastWindowClosed(False)
        self._enable_streaming = enable_streaming
        flags = " ".join(argv or [])
        if ui_mode is not None:
            self.ui_mode = ui_mode
        elif "--ribbon" in flags:
            self.ui_mode = "ribbon"
        else:
            self.ui_mode = "window"

        self._dir = data_directory or data_dir()
        setup_logging(self._dir)
        self.settings = (
            QSettings(settings_path, QSettings.Format.IniFormat)
            if settings_path else QSettings(config.ORG_NAME, config.APP_NAME)
        )
        self.store = HearthStore(self._dir / "hearth.db")
        self._snapshot_path = self._dir / "session.json"
        self.catalog = Catalog()
        # video_id -> (plain_text | None, LrcLine list | None)
        self._lyrics_cache: dict[str, tuple[str | None, list | None]] = {}
        # Discover caches: sections fetched once, playlists per category,
        # explore shelves reused across its three chips.
        self._discover_moods: list | None = None
        self._mood_playlists_cache: dict[str, list[Collection]] = {}
        self._explore_cache: tuple | None = None
        # World Explorer: rotates the genre search seeds so the same dial
        # spins up a different station each visit.
        self._world_spin = 0
        # In-flight jobs are tracked in the module-level _INFLIGHT registry
        # so they survive even if this Hearth object is torn down early.

        self.guard = InstanceGuard() if single_instance else None
        if self.guard is not None and not self.guard.is_primary:
            log.info("Hearth already running — forwarded 'show' and exiting")
            self.store.close()
            return

        palette_key = self.settings.value("theme", config.DEFAULT_PALETTE)

        # Core + UI (panel stays built for ribbon mode; window is the default)
        self.core = PlaybackCore(self.qapp)
        self.panel = FloatingPanel(palette_key)
        self.toast = NowPlayingToast(palette_key)
        self.overlay = LyricsOverlay(palette_key)
        # desktop lyrics state: the synced engine for the current track and
        # the last line index we pushed (so each tick stays a cheap no-op)
        self._lyrics_engine: SyncedLyrics | None = None
        self._overlay_index = -2
        self._overlay_on = bool(config.LYRICS_OVERLAY_ENABLED)
        # the style closet: active look lives in theme module state; this
        # slot remembers the wallpaper see-through dial for persistence
        self._wallpaper_alpha = config.WALLPAPER_ALPHA_DEFAULT
        self.window = MainWindow(palette_key, store=self.store)
        self.command_palette = CommandPalette(palette_key, parent=self.window)
        # the phone remote: created lazily on first 📱, one session per run
        self._remote: RemoteServer | None = None
        # wake-up alarm: one-shot, tray-scheduled, fades the room back in
        self.alarm = AlarmController(parent=self.qapp)
        self.alarm.fired.connect(self._fire_alarm)
        self._alarm_poll = QTimer(self.qapp)
        self._alarm_poll.setInterval(1000)
        self._alarm_poll.timeout.connect(self.alarm.poll)
        self._alarm_fade: QTimer | None = None
        self._alarm_target = 0.8
        self._alarm_step = 0
        # ambient mixer: a second, quieter fire beside the music — its
        # own sink, its own level, the player path untouched
        self.ambient = AmbientChannel(parent=self.qapp)
        self.tray: HearthTray | None = None
        # plugin shelf sources: name -> callable returning Track-shaped dicts
        # (resolved on the job pool; the home "🔌 Plugins" shelf renders them)
        self._plugin_shelves: dict[str, object] = {}
        # the update whisper: opt-in, first look ≥60s after boot, and
        # while UPDATE_CHECK_ENABLED is False it doesn't even schedule
        self._update_tag = ""
        self.whisper = UpdateWhisper(self.settings, parent=self.qapp)
        self.whisper.whisper.connect(self._on_update_whisper)
        self.whisper.schedule(self.qapp)
        # MPRIS2: the desk's media keys ride the same core the tray does
        # (a silent no-op everywhere the guarded dbus import failed)
        self.mpris = MprisService()
        if config.MPRIS_ENABLED and MPRIS_AVAILABLE:
            self.mpris.connect(self.core, summon=self._summon,
                               quit=self.qapp.quit)
            self.mpris.start()

        # Discord Rich Presence: opt-in, guarded, silent everywhere pypresence
        # is absent — and it never touches the audio path. It only wakes up
        # when the user flips the tray switch (which itself is gated on
        # config.DISCORD_RPC_ENABLED, off in tests/CI).
        self.presence = DiscordPresence(backoff_s=config.DISCORD_RPC_BACKOFF_S)
        self._presence_throttle = Throttle(config.DISCORD_RPC_THROTTLE_S)
        self._presence_duration_ms = 0

        # plugins: quiet, time-boxed, before settings so a plugin palette
        # pack exists by the time pickers and restores go looking for it
        self._load_plugins()

        self._restore_settings()
        self._wire_panel()
        self._wire_window()
        self._wire_core()
        self._install_hotkeys()
        self._install_palette_hotkey()
        self._register_palette_actions()
        self._build_tray()
        self._restore_session()
        if self.ui_mode == "window":
            self.panel.hide()
        else:
            self.window.hide()

    # --- wiring ---

    def _wire_panel(self) -> None:
        p = self.panel
        p.search_submitted.connect(self._run_search)
        p.track_picked.connect(self._pick_track)
        p.play_pause_requested.connect(self.core.toggle)
        p.next_requested.connect(self.core.next)
        p.prev_requested.connect(self.core.previous)
        p.shuffle_requested.connect(self._shuffle)
        p.repeat_requested.connect(self._cycle_repeat)
        p.volume_changed.connect(self._on_user_volume)
        p.seek_requested.connect(self.core.seek)

    def _wire_window(self) -> None:
        w = self.window
        w.search_submitted.connect(self._run_search)
        w.search_scoped.connect(self._run_scoped_search)
        w.album_opened.connect(self._open_album)
        w.playlist_picked.connect(self._play_list)
        w.play_next_requested.connect(self._play_next)
        w.enqueue_requested.connect(self._enqueue)
        w.pin_toggled.connect(self._toggle_pin)
        w.queue_remove_requested.connect(self._remove_from_queue)
        w.queue_reorder_requested.connect(self._reorder_queue)
        w.queue_jump_requested.connect(self._jump_to_queue_index)
        w.queue_clear_requested.connect(self._clear_queue)
        w.mute_toggled.connect(self._toggle_mute)
        w.radio_requested.connect(self._start_radio)
        w.artist_opened.connect(self._open_artist)
        w.rate_cycled.connect(self._cycle_rate)
        w.sleep_requested.connect(self._set_sleep)
        w.home_refresh_requested.connect(self._refresh_home)
        w.library_refresh_requested.connect(self._refresh_library)
        w.discover_refresh_requested.connect(self._open_discover)
        w.discover_category_selected.connect(self._discover_category)
        w.discover_collection_opened.connect(self._discover_collection)
        w.discover_charts_requested.connect(self._discover_charts)
        w.discover_explore_requested.connect(self._discover_explore)
        w.discover_enqueue_all_requested.connect(self._enqueue_all)
        w.world_station_requested.connect(self._start_world_station)
        w.style_closet_requested.connect(self._open_style_closet)
        w.local_add_folder_requested.connect(self._local_add_folder)
        w.local_rescan_requested.connect(self._local_rescan)
        w.glow_mix_requested.connect(self._glow_mix)
        w.remote_requested.connect(self._open_remote)
        w.play_pause_requested.connect(self.core.toggle)
        w.next_requested.connect(self.core.next)
        w.prev_requested.connect(self.core.previous)
        w.shuffle_requested.connect(self._shuffle)
        w.repeat_requested.connect(self._cycle_repeat)
        w.volume_changed.connect(self._on_user_volume)
        w.seek_requested.connect(self.core.seek)
        w.now_view.lyrics_font_changed.connect(self._on_lyrics_font_changed)
        w.refresh_playlists()

    def _wire_core(self) -> None:
        self.core.track_changed.connect(self._on_track_changed)
        self.core.state_changed.connect(self.panel.set_playing)
        self.core.state_changed.connect(self.window.set_playing)
        self.core.position_changed.connect(self.panel.set_position)
        self.core.position_changed.connect(self.window.set_position)
        self.core.duration_changed.connect(self.panel.set_duration)
        self.core.duration_changed.connect(self.window.set_duration)
        self.core.status.connect(self.panel.set_status)
        self.core.queue_changed.connect(self._on_queue_changed)
        self.core.queue_changed.connect(self._save_session_snapshot)
        self.core.repeat_changed.connect(lambda m: self._persist())
        self.core.rate_changed.connect(lambda r: self._persist())
        self.core.queue_dry.connect(self._on_queue_dry)
        self.core.stream_lost.connect(self._on_stream_lost)
        self.core.position_changed.connect(self._push_overlay_line)
        self.core.rate_changed.connect(
            lambda r: self.window.player_bar.set_speed_label(r)
        )
        # per-track speed memory: every rate change sticks to the song
        self.core.rate_changed.connect(self._on_rate_changed)
        self.core.state_changed.connect(
            lambda _playing: self._update_visualizer_state()
        )
        # crossfade groundwork: the core decides when, the app resolves
        # (its handler keeps test mode off the network, like _on_stream_lost)
        self.core.preresolve_requested.connect(self._on_preresolve)
        self.window.now_view.crossfade_changed.connect(self._on_crossfade_changed)

    def _build_tray(self) -> None:
        if not QSystemTrayIcon.isSystemTrayAvailable():
            log.info("No system tray on this desktop — skipping tray icon")
            return
        actions = {
            "play": self._make_action(_i18n_label("play_pause", "Play / Pause"), self.core.toggle),
            "next": self._make_action(_i18n_label("next", "Next"), self.core.next),
            "prev": self._make_action(_i18n_label("previous", "Previous"), self.core.previous),
            "show": self._make_action("Show Hearth", self._summon),
            "diag": self._make_action("🩺 Diagnostics", self._show_diagnostics),
        }
        if config.UPDATE_CHECK_ENABLED:
            actions["update"] = self._make_action(
                "🕯️ Newer hearth — don't whisper again", self._dismiss_update_whisper
            )
        if config.DISCORD_RPC_ENABLED:
            # the flag gates the action's existence; importability gates its
            # use (a grayed row beats a toggle that can never connect)
            discord_act = self._make_action(
                "🎮 Discord Rich Presence", self._on_discord_action)
            discord_act.setCheckable(True)
            discord_act.setEnabled(DISCORD_AVAILABLE)
            actions["discord"] = discord_act
        lyrics_act = self._make_action("🪧 Desktop lyrics", self._toggle_overlay)
        lyrics_act.setCheckable(True)
        lyrics_act.setChecked(self._overlay_on)
        actions["lyrics"] = lyrics_act
        sleep_menu = QMenu("⏾ Sleep timer")
        for label, minutes in (("Off", 0), ("15 minutes", 15),
                               ("30 minutes", 30), ("45 minutes", 45), ("60 minutes", 60)):
            act = QAction(label, sleep_menu)
            act.triggered.connect(
                lambda _checked, m=minutes: self.core.set_sleep_timer(m or None)
            )
            sleep_menu.addAction(act)
        alarm_menu = QMenu("⏰ Wake-up")
        for label, minutes in (("Off / cancel", 0), ("15 minutes", 15),
                               ("30 minutes", 30), ("45 minutes", 45), ("60 minutes", 60)):
            act = QAction(label, alarm_menu)
            act.triggered.connect(
                lambda _checked, m=minutes: self._arm_alarm(m)
            )
            alarm_menu.addAction(act)
        # ambient: one soundscape at a time, each with its own level dial
        ambient_menu = QMenu("🌫️ Ambient")
        ambient_menu.addAction(
            self._make_action("Off", lambda: self._set_ambient(None, 0.0))
        )
        for kind_label, kind in (("🏕 Campfire", "campfire"), ("☕ Café", "cafe"),
                                 ("🌧 Rain", "rain")):
            sub = QMenu(kind_label, ambient_menu)
            for frac in config.AMBIENT_LEVELS:
                act = QAction(f"{int(round(frac * 100))}%", sub)
                act.triggered.connect(
                    lambda _checked, k=kind, f=frac: self._set_ambient(k, f)
                )
                sub.addAction(act)
            ambient_menu.addMenu(sub)
        self.tray = HearthTray(actions, menus=[sleep_menu, alarm_menu, ambient_menu], parent=self.qapp)
        self.tray.activated.connect(self._on_tray_activated)
        self.tray.show()

    def _make_action(self, text: str, callback) -> QAction:
        act = QAction(text)
        act.triggered.connect(callback)
        return act

    def _install_hotkeys(self) -> None:
        saved = self.settings.value("hotkeys", {}) or {}
        surface = self.window if self.ui_mode == "window" else self.panel
        for action, chord in effective_chords(saved).items():
            shortcut = QShortcut(QKeySequence(chord), surface)
            shortcut.activated.connect({
                "play_pause": self.core.toggle,
                "next_track": self.core.next,
                "prev_track": self.core.previous,
                "toggle_panel": self._toggle_surface,
                "focus_search": self._focus_search,
            }[action])

    def _install_palette_hotkey(self) -> None:
        """Ctrl+K pops the command palette (never a reserved system chord)."""
        chord = "Ctrl+K"
        if chord.lower() in {r.lower() for r in config.RESERVED_CHORDS}:
            return
        surface = self.window if self.ui_mode == "window" else self.panel
        shortcut = QShortcut(QKeySequence(chord), surface)
        shortcut.activated.connect(self._open_command_palette)

    # --- actions ---

    @property
    def surface(self):
        """The active UI surface (main window by default, ribbon legacy)."""
        return self.window if self.ui_mode == "window" else self.panel

    def _run_search(self, query: str) -> None:
        self.window.search_view.set_header("Search")  # a manual search replaces station pages
        self.surface.set_status("Searching…")
        job = SearchJob(self.catalog, query)
        job.signals.finished.connect(self._show_search_results)
        job.signals.failed.connect(lambda msg: self.surface.set_status(f"Search failed: {msg}"))
        self._launch(job)

    def _run_scoped_search(self, query: str, scope: str) -> None:
        """Songs / Videos / Albums scopes from the search-page chips."""
        if scope == "songs":
            self._run_search(query)
            return
        self.surface.set_status(f"Searching {scope}…")
        job = ScopedSearchJob(self.catalog, query, scope=scope)
        job.signals.finished.connect(self._show_scoped_results)
        job.signals.failed.connect(lambda msg: self.surface.set_status(f"Search failed: {msg}"))
        self._launch(job)

    def _show_scoped_results(self, payload) -> None:
        scope, results = payload
        if scope == "albums":
            self.window.show_album_results(results)
            self.surface.set_status(f"{len(results)} albums" if results else "No albums found")
            return
        self._show_search_results(results)

    def _open_album(self, album) -> None:
        """Album drill-down: fetch the full track list, then open its page."""
        self.surface.set_status(f"Opening {album.title}…")
        job = AlbumJob(self.catalog, album.browse_id)
        job.signals.finished.connect(self._on_album_ready)
        job.signals.failed.connect(
            lambda bid: self.surface.set_status("Could not open that album")
        )
        self._launch(job)

    def _on_album_ready(self, payload) -> None:
        album, tracks = payload
        self.window.open_album(album, tracks)
        self.surface.set_status(f"{album.title} — {len(tracks)} tracks")

    def _open_artist(self, target) -> None:
        """Artist page drill-down from a track, an album, or an artist chip."""
        channel_id = ""
        name = ""
        if isinstance(target, Artist):
            channel_id, name = target.channel_id, target.name
        elif isinstance(target, Album):
            channel_id, name = target.artist_id, target.artist
        elif isinstance(target, Track):
            channel_id, name = target.artist_id, target.artist
        if channel_id:
            self.surface.set_status(f"Opening {name or 'artist'}…")
            job = ArtistJob(self.catalog, channel_id)
            job.signals.finished.connect(self._on_artist_ready)
            job.signals.failed.connect(
                lambda _cid, n=name: self._open_artist_by_name(n)
            )
            self._launch(job)
        elif name:
            self._open_artist_by_name(name)

    def _open_artist_by_name(self, name: str) -> None:
        """No channel id anywhere — find the artist by name first."""
        if not name or name == "Unknown artist":
            self.surface.set_status("No artist to open here")
            return
        self.surface.set_status(f"Finding {name}…")
        job = ArtistLookupJob(self.catalog, name)
        job.signals.finished.connect(self._on_artist_lookup_ready)
        job.signals.failed.connect(
            lambda n: self.surface.set_status(f"Could not find {n}")
        )
        self._launch(job)

    def _on_artist_lookup_ready(self, artists: list) -> None:
        if not artists:
            self.surface.set_status("Could not find that artist")
            return
        match = artists[0]
        self.surface.set_status(f"Opening {match.name}…")
        job = ArtistJob(self.catalog, match.channel_id)
        job.signals.finished.connect(self._on_artist_ready)
        job.signals.failed.connect(
            lambda _cid: self.surface.set_status("Could not open that artist")
        )
        self._launch(job)

    def _on_artist_ready(self, artist) -> None:
        self.window.open_artist(artist)
        top = len(artist.top_tracks)
        extras = artist.albums or artist.singles
        tail = f" · {len(extras)} releases" if extras else ""
        self.surface.set_status(f"{artist.name} — {top} top tracks{tail}")

    def _show_search_results(self, tracks: list[Track]) -> None:
        self.window.show_search_results(tracks)
        self.panel.show_results(tracks)
        if self.ui_mode == "window":
            self.window.show_view("search")
            self.surface.set_status(f"{len(tracks)} results" if tracks else "No results")

    def _play_list(self, tracks: list[Track], start: int = 0) -> None:
        if not tracks:
            return
        start = max(0, min(int(start), len(tracks) - 1))
        self.core.start_queue(list(tracks), start)

    def _pick_track(self, track: Track) -> None:
        self.core.play_track(track)

    def _play_next(self, track: Track) -> None:
        self.core.engine.upcoming.insert(0, track)
        self.core.queue_changed.emit()

    def _enqueue(self, track: Track) -> None:
        self.core.enqueue(track)

    def _remove_from_queue(self, index: int) -> None:
        upcoming = self.core.engine.upcoming
        if 0 <= index < len(upcoming):
            upcoming.pop(index)
            self.core.queue_changed.emit()

    def _reorder_queue(self, upcoming: list[Track]) -> None:
        """Apply the drag & drop order from the queue dock."""
        self.core.engine.set_order(list(upcoming))
        self.core.queue_changed.emit()

    def _jump_to_queue_index(self, index: int) -> None:
        """Double-click / 'Play now' in the queue: promote that track."""
        upcoming = self.core.engine.upcoming
        if not (0 <= index < len(upcoming)):
            return
        track = upcoming.pop(index)
        self.core.play_track(track)

    def _clear_queue(self) -> None:
        self.core.engine.upcoming.clear()
        self.core.queue_changed.emit()
        self.surface.set_status("Queue cleared")

    _pre_mute_volume: float | None = None

    def _toggle_mute(self) -> None:
        if self.core.volume > 0.0:
            self._pre_mute_volume = self.core.volume
            self.core.set_volume(0.0)
            self.window.set_volume(0.0)
            self.surface.set_status("Muted")
        else:
            restore = self._pre_mute_volume or 0.8
            self.core.set_volume(restore)
            self.window.set_volume(restore)
            self.surface.set_status("Unmuted")

    def _toggle_pin(self, track: Track) -> None:
        if self.store.is_pinned(track.video_id):
            self.store.unpin(track.video_id)
            self.surface.set_status(f"Unpinned: {track.title}")
        else:
            self.store.pin(track)
            self.surface.set_status(f"Pinned: {track.title}")
        self.window.set_pinned(self.store.is_pinned(track.video_id))
        self._refresh_library()

    def _refresh_home(self) -> None:
        self.window.set_recent(self.store.history(12))
        self.window.set_favorites(self.store.favorites()[:12])
        self.window.set_top_tracks(self.store.top_tracks(config.TOP_TRACKS_LIMIT))
        self.window.set_on_repeat(
            self.store.on_repeat(
                config.ON_REPEAT_SHELF_LIMIT, config.ON_REPEAT_HALF_LIFE_DAYS
            )
        )
        self.window.set_smart_shelves(
            self.store.smart_most_played(12),
            self.store.smart_recently_loved(12),
            self.store.smart_rare_gems(12),
        )
        self._refresh_plugin_shelf()   # plugin shelf sources, off the UI thread
        if not self._enable_streaming:
            return  # unit tests: no network shelves
        for query in config.QUICK_PICKS:
            job = SearchJob(self.catalog, query, limit=8)
            job.signals.finished.connect(
                lambda tracks, q=query: self.window.set_home_shelf(
                    "Quick picks", tracks
                ) if tracks else None
            )
            self._launch(job)

    def _refresh_library(self) -> None:
        self.window.set_favorites(self.store.favorites()[:12])
        self.window.set_recent(self.store.history(12))
        self.window.set_local_tracks(self.store.local_tracks())
        self.window.refresh_playlists()

    # --- discover: the whole world's music ---

    def _open_discover(self) -> None:
        """Discover tab opened: serve cached sections or fetch them once."""
        if self._discover_moods is not None:
            self.window.discover_view.set_sections(self._discover_moods)
            return
        if not self._enable_streaming:
            return  # unit tests: no network shelves
        self.window.discover_view.set_status("Loading the world's music…")
        job = DiscoverJob(self.catalog, "moods")
        job.signals.finished.connect(self._on_discover_moods)
        job.signals.failed.connect(
            lambda: self.surface.set_status("Discover could not load — try again")
        )
        self._launch(job)

    def _on_discover_moods(self, payload) -> None:
        _kind, sections = payload
        self._discover_moods = list(sections)
        self.window.discover_view.set_sections(self._discover_moods)

    def _discover_category(self, params: str) -> None:
        """A mood/genre subcategory was picked — serve cache or fetch playlists."""
        if not params:
            return
        cached = self._mood_playlists_cache.get(params)
        if cached is not None:
            self.window.discover_view.set_collections(list(cached))
            self.surface.set_status(f"{len(cached)} playlists")
            return
        if not self._enable_streaming:
            return
        self.window.discover_view.set_status("Loading playlists…")
        job = DiscoverJob(self.catalog, "mood_playlists", params)
        job.signals.finished.connect(
            lambda payload, p=params: self._on_mood_playlists(p, payload[1])
        )
        job.signals.failed.connect(
            lambda: self.surface.set_status("Could not load that category")
        )
        self._launch(job)

    def _on_mood_playlists(self, params: str, collections: list[Collection]) -> None:
        self._mood_playlists_cache[params] = list(collections)
        self.window.discover_view.set_collections(list(collections))
        self.surface.set_status(
            f"{len(collections)} playlists" if collections else "Nothing here yet"
        )

    def _discover_charts(self) -> None:
        if not self._enable_streaming:
            return
        self.window.discover_view.set_status("Loading charts…")
        job = DiscoverJob(self.catalog, "charts")
        job.signals.finished.connect(
            lambda payload: self._on_charts(payload[1])
        )
        job.signals.failed.connect(
            lambda: self.surface.set_status("Charts unavailable right now")
        )
        self._launch(job)

    def _on_charts(self, collections: list[Collection]) -> None:
        self.window.discover_view.set_collections(list(collections))
        self.surface.set_status(
            f"{len(collections)} chart playlists" if collections else "No charts found"
        )

    def _discover_explore(self, mode: str) -> None:
        """new_releases / trending / new_videos — one fetch serves all three."""
        if mode not in ("new_releases", "trending", "new_videos"):
            return
        if self._explore_cache is not None:
            self._route_explore(mode)
            return
        if not self._enable_streaming:
            return
        self.window.discover_view.set_status("Loading explore…")
        job = DiscoverJob(self.catalog, "explore")
        job.signals.finished.connect(
            lambda payload, m=mode: self._on_explore(m, payload[1])
        )
        job.signals.failed.connect(
            lambda: self.surface.set_status("Explore unavailable right now")
        )
        self._launch(job)

    def _on_explore(self, mode: str, payload) -> None:
        self._explore_cache = payload      # (albums, trending, new_videos)
        self._route_explore(mode)

    def _route_explore(self, mode: str) -> None:
        albums, trending, videos = self._explore_cache
        view = self.window.discover_view
        if mode == "new_releases":
            view.set_collections(list(albums))
            self.surface.set_status(f"{len(albums)} new releases")
        elif mode == "trending":
            view.set_track_list("🔥 Trending now", list(trending))
            self.surface.set_status(f"{len(trending)} trending tracks")
        else:
            view.set_track_list("🎬 New music videos", list(videos))
            self.surface.set_status(f"{len(videos)} new videos")

    def _discover_collection(self, item) -> None:
        """A Discover card was clicked: albums drill down, playlists open."""
        if isinstance(item, Album):
            self._open_album(item)
            return
        if not isinstance(item, Collection):
            return
        if not self._enable_streaming:
            self.surface.set_status(f"Playlist: {item.title} (test mode)")
            return
        self.surface.set_status(f"Opening {item.title}…")
        job = DiscoverJob(self.catalog, "playlist", item.playlist_id)
        job.signals.finished.connect(self._on_collection_page)
        job.signals.failed.connect(
            lambda pid: self.surface.set_status("Could not open that playlist")
        )
        self._launch(job)

    def _on_collection_page(self, payload) -> None:
        _kind, (title, tracks) = payload
        self.window.open_remote_playlist(title, tracks)
        self.surface.set_status(f"{title} — {len(tracks)} tracks")

    def _enqueue_all(self, tracks: list[Track]) -> None:
        if not tracks:
            return
        self.core.engine.upcoming.extend(list(tracks))
        self.core.queue_changed.emit()
        self.surface.set_status(f"Queued {len(tracks)} tracks")

    # --- world explorer: the curated dial ---

    def _start_world_station(self, genre) -> None:
        """A World Explorer chip (or the dice) was clicked: tune that dial."""
        if not self._enable_streaming:
            self.surface.set_status(f"🗺️ {genre.label} station (test mode)")
            return
        self._world_spin += 1
        query = world.station_query(genre, spin=self._world_spin)
        self.window.world_view.set_status(
            f"Tuning {genre.emoji} {genre.label} — “{query}”"
        )
        self.surface.set_status(f"🗺️ Tuning into {genre.label}…")
        job = WorldJob(self.catalog, query, genre.label)
        job.signals.finished.connect(self._on_world_ready)
        job.signals.failed.connect(
            lambda label: self.surface.set_status(f"🗺️ {label}: could not tune in")
        )
        self._launch(job)

    def _on_world_ready(self, payload) -> None:
        """Station fetched: show it as a playable list and start spinning."""
        label, tracks = payload
        if not tracks:
            self.surface.set_status(
                f"🗺️ {label}: static on this frequency — roll the dice"
            )
            return
        self.window.show_search_results(list(tracks))
        self.window.search_view.set_header(f"🗺️ {label} — world station")
        self.window.show_view("search")
        self.surface.set_status(f"{label}: {len(tracks)} tracks queued")
        self.core.start_queue(list(tracks), 0)

    def _on_queue_changed(self) -> None:
        self.window.set_queue(
            list(self.core.engine.upcoming), self.core.engine.current
        )

    def _on_stream_lost(self, track: Track, resume_ms: int) -> None:
        """The player died mid-song: re-resolve a fresh URL and rejoin it."""
        if not self._enable_streaming:
            return  # test mode: keep the playback pool out of unit tests
        local_url = self._local_file_url(track)
        if local_url is not None:
            # a local file never needs re-resolving — just rejoin it
            self.core.set_stream(track, local_url, resume_ms=resume_ms)
            return
        job = LoadJob(track)
        job.signals.finished.connect(
            lambda payload: self.core.set_stream(
                payload[2], payload[0], payload[1], resume_ms=resume_ms
            )
        )
        job.signals.failed.connect(
            lambda title: self.surface.set_status(f"Could not rejoin: {title}")
        )
        self._launch(job)

    def _on_preresolve(self, track: Track) -> None:
        """Crossfade groundwork: resolve the NEXT stream while this one plays.

        Runs on the same playback pool as every LoadJob. A failure lands
        nowhere at all — the core drops the pre-resolve and the normal
        EndOfMedia path resolves fresh, exactly as it always has.
        """
        if not self._enable_streaming:
            return  # test mode: keep the playback pool out of unit tests
        if track is None:
            return
        local_url = self._local_file_url(track)
        if local_url is not None:
            self.core.prime_shadow(track, local_url)
            return
        job = LoadJob(track)
        job.signals.finished.connect(
            lambda payload: self.core.prime_shadow(payload[2], payload[0],
                                                   payload[1])
        )
        self._launch(job)

    def _on_crossfade_changed(self, seconds: int) -> None:
        """The Now Playing slider moved: apply live + remember it."""
        self.core.set_crossfade(int(seconds))
        self.settings.setValue("crossfade", self.core.crossfade_seconds)
        if seconds:
            self.surface.set_status(f"Crossfade: {int(seconds)}s")
        else:
            self.surface.set_status("Crossfade off")

    def _on_track_changed(self, track: Track | None) -> None:
        self.panel.set_track(track)
        self.window.set_track(track)
        self._update_visualizer_state()
        self.window.set_pinned(
            self.store.is_pinned(track.video_id) if track is not None else False
        )
        if track is not None:
            self.store.log_play(track)
            self._restore_track_rate(track)   # this song's remembered speed
            self._restore_track_volume(track)  # this song's remembered nudge
        self._persist()
        # desktop lyrics: a new song means a fresh, empty strip
        self._lyrics_engine = None
        self._overlay_index = -2
        self.overlay.clear()
        if track is None:
            return
        self.toast.announce(track)
        if not self._enable_streaming:
            return  # test mode: keep the playback pool out of unit tests
        self._fetch_lyrics(track)
        local_url = self._local_file_url(track)
        if local_url is not None:
            # your own file: skip the network resolve entirely — QMediaPlayer
            # opens a file:// URL directly (the smallest possible branch;
            # set_stream itself is untouched)
            self.core.set_stream(track, local_url)
            return
        job = LoadJob(track)
        job.signals.finished.connect(
            lambda payload: self.core.set_stream(payload[2], payload[0], payload[1])
        )
        job.signals.failed.connect(
            lambda title: self.surface.set_status(f"Could not resolve: {title}")
        )
        self._launch(job)

    def _launch(self, job) -> None:
        """Start a QRunnable, keeping it referenced until it completes.

        The module-level registry keeps the wrapper (and its signal
        carrier) alive even if the Hearth object itself is torn down
        while a worker thread is still inside run().
        """
        _INFLIGHT.add(job)
        job.signals.finished.connect(lambda *_: _INFLIGHT.discard(job))
        job.signals.failed.connect(lambda *_: _INFLIGHT.discard(job))
        QThreadPool.globalInstance().start(job)

    def _cycle_repeat(self) -> None:
        mode = self.core.cycle_repeat()
        self.panel.set_status(f"Repeat: {mode}")

    def _cycle_rate(self) -> None:
        rate = self.core.next_rate()
        self.surface.set_status(f"Speed {rate:g}x")

    # --- shuffle / smart shuffle (v0.8.0 controls) ---

    def _shuffle(self) -> None:
        """The shuffle button + S key: artist-spread when SMART_SHUFFLE is on.

        Either way the contract is the one shuffle() always had —
        upcoming only, history untouched, exactly one queue_changed —
        so nothing downstream can tell the difference.
        """
        if config.SMART_SHUFFLE:
            self.core.shuffle_smart(self._shuffle_weights())
            self.surface.set_status("Smart shuffle — artists spread, favorites surface")
        else:
            self.core.shuffle()

    def _shuffle_weights(self) -> dict[str, float]:
        """Decayed play counts, max-normalized to 0..1, for the smart shuffle.

        The On Repeat engine already knows which tracks are hot right now;
        feeding its scores into the shuffle is what turns "artists spread
        out" into "favorites surface a little more often". Never raises:
        a tired database means an unweighted shuffle, same as always.
        """
        try:
            pairs = self.store.on_repeat_scores(
                limit=config.SMART_SHUFFLE_WEIGHTS_LIMIT
            )
        except Exception:  # noqa: BLE001 - weights are a garnish, not a meal
            return {}
        if not pairs:
            return {}
        top = max(score for _track, score in pairs)
        if top <= 0.0:
            return {}
        return {track.video_id: score / top for track, score in pairs}

    # --- per-track speed memory (v0.8.0 controls) ---

    def _on_rate_changed(self, rate: float) -> None:
        """Playback speed moved: stick it to the current track (no debounce)."""
        track = self.core.engine.current
        if track is None:
            return   # a rate with no song belongs to nobody
        self.store.set_track_pref(track.video_id, "rate", float(rate))

    def _restore_track_rate(self, track: Track) -> None:
        """A track starts: put its remembered speed back (default 1.0)."""
        saved = self.store.track_pref(track.video_id, "rate", 1.0)
        rate = saved if saved in config.PLAYBACK_RATES else 1.0
        if abs(rate - self.core.rate) > 1e-9:
            self.core.set_rate(rate)

    # --- per-track volume nudges (v0.7.1) ---

    def _on_user_volume(self, volume: float) -> None:
        """The user moved a volume dial: apply it + stick it to this track.

        Quiet podcast episodes get a nudge up, loud remasters a nudge
        down — and the nudge comes back with the track. Programmatic
        volume changes (mute, the alarm fade, restore-on-launch) call
        core.set_volume directly and never land here, so they stay
        anonymous and write no prefs.
        """
        self.core.set_volume(volume)
        track = self.core.engine.current
        if track is None:
            return   # a dial with no song belongs to nobody
        try:
            self.store.set_track_pref(track.video_id, "vol", float(volume))
        except Exception:  # noqa: BLE001 - a pref write must not touch playback
            pass

    def _restore_track_volume(self, track: Track) -> None:
        """A track starts: put its remembered volume nudge back (if any)."""
        saved = self.store.track_pref(track.video_id, "vol", None)
        if saved is None:
            return   # no nudge on record: the dial stays where the user left it
        self.core.set_volume(saved)
        self.panel.set_volume(saved)
        self.window.set_volume(saved)

    # --- mini-visualizer state (v0.8.0 controls) ---

    def _update_visualizer_state(self) -> None:
        """Translate playback state into the player-bar equalizer's mood."""
        if self.core.engine.current is None:
            state = "stopped"
        elif self.core.is_playing:
            state = "playing"
        else:
            state = "paused"
        self.window.player_bar.set_visualizer_state(state)

    # --- command palette (v0.8.0 controls) ---

    def _register_palette_actions(self) -> None:
        """Fill the palette with every action the room answers to."""
        self.command_palette.set_actions(self._palette_actions())

    def _palette_actions(self) -> list[CommandAction]:
        """The whole menu: transport, views, themes, favorite, speed, quit."""
        acts = [
            CommandAction("Play / Pause", self.core.toggle, "resume transport"),
            CommandAction("Next track", self.core.next, "skip forward"),
            CommandAction("Previous track", self.core.previous, "back"),
            CommandAction("Shuffle queue", self._shuffle, "random mix smart"),
            CommandAction("Cycle repeat", self._cycle_repeat, "loop all one off"),
            CommandAction("Mute / Unmute", self._toggle_mute, "silence volume"),
            CommandAction("Toggle favorite", self._palette_toggle_favorite,
                          "pin heart like"),
        ]
        view_labels = {
            "home": "Go to Home",
            "discover": "Go to Discover",
            "world": "Go to World Explorer",
            "search": "Go to Search",
            "library": "Go to Your Library",
            "local": "Go to Local songs",
            "now": "Go to Now Playing",
            "stats": "Go to Stats",
            "history": "Go to History",
        }
        for key in self.window.VIEWS:
            label = view_labels.get(key, f"Go to {key}")
            acts.append(CommandAction(label,
                                      lambda k=key: self.window.show_view(k)))
        for key, pal in config.PALETTES.items():
            acts.append(CommandAction(f"Theme: {pal.label}",
                                      lambda k=key: self._apply_palette_key(k),
                                      f"palette color {key}"))
        for rate in config.PLAYBACK_RATES:
            acts.append(CommandAction(f"Speed {rate:g}x",
                                      lambda r=rate: self.core.set_rate(r),
                                      "playback tempo"))
        acts.append(CommandAction("Quit Hearth", self.qapp.quit, "exit close"))
        return acts

    def _open_command_palette(self) -> None:
        """Ctrl+K: fresh menu (theme packs may have grown), centered search."""
        self._register_palette_actions()
        self.command_palette.popup()

    def _apply_palette_key(self, key: str) -> None:
        """Switch the whole room to a built-in palette and remember it."""
        pal = config.PALETTES.get(key)
        if pal is None:
            return
        self.panel.apply_palette(pal)   # _restyle reads the panel's palette
        self._restyle()
        self.settings.setValue("theme", key)
        self.surface.set_status(f"Theme: {pal.label}")

    def _palette_toggle_favorite(self) -> None:
        """Palette action: pin/unpin whatever is playing right now."""
        track = self.core.engine.current
        if track is not None:
            self._toggle_pin(track)

    # --- plugins (v0.7.0): palette packs + shelf sources, trusted installs ---

    def _plugin_services(self) -> dict:
        """The tiny surface a plugin entry is handed.

        ``register_palette(dict)`` wraps theme.register_custom_palette:
        the dict is rebuilt into a Palette and rejected when it does not
        validate, so a half-baked plugin cannot poison the room's colors
        (built-in keys are never overwritten — theme suffixes collisions).

        ``register_shelf_source(name, fn)`` remembers a home-shelf source;
        hearth calls ``fn`` on a worker thread and renders the Track-shaped
        dicts it returns on the "🔌 Plugins" shelf.
        """
        def register_palette(data):
            pal = theme._palette_from_dict(data)
            if pal is None:
                log.info("plugin palette rejected: not a complete palette dict")
                return None
            return theme.register_custom_palette(pal)

        def register_shelf_source(name, fn):
            if not isinstance(name, str) or not name.strip() or not callable(fn):
                log.info("plugin shelf source rejected (need a name + callable)")
                return False
            self._plugin_shelves[name.strip()] = fn
            return True

        return {
            "register_palette": register_palette,
            "register_shelf_source": register_shelf_source,
        }

    def _load_plugins(self) -> None:
        """Boot-time plugin load: quiet, time-boxed, never delays startup.

        Discovery does no network I/O; the whole thing is wrapped so even
        a spectacularly broken plugins folder cannot slow the fire down
        (the deadline caps misbehaving imports, the except caps everything
        else).
        """
        try:
            warnings: list[str] = []
            deadline = time.monotonic() + config.PLUGIN_BOOT_TIMEOUT_S
            results = plugins.load_all(
                self._dir / config.PLUGINS_DIR_NAME,
                self._plugin_services(),
                deadline=deadline,
                warnings=warnings,
            )
            for note in warnings:
                log.info("plugin: %s", note)
            for info, result in results:
                if isinstance(result, Exception):
                    log.info("plugin %s failed to load: %s", info.name, result)
            loaded = [info.name for info, result in results
                      if not isinstance(result, Exception)]
            if loaded:
                log.info("plugins loaded: %s", ", ".join(loaded))
        except Exception:   # noqa: BLE001 - plugins must never delay the fire
            log.info("plugin load skipped", exc_info=True)

    def _refresh_plugin_shelf(self) -> None:
        """Resolve every plugin shelf source on the pool — never the UI thread."""
        if not self._plugin_shelves:
            return
        job = _PluginShelfJob(self._plugin_shelves)
        job.signals.finished.connect(self._on_plugin_shelf)
        self._launch(job)

    def _on_plugin_shelf(self, payload) -> None:
        """Shelf sources landed: one merged shelf; failures speak up."""
        results, failures = payload
        tracks: list[Track] = []
        for _name, source_tracks in results:
            tracks.extend(source_tracks)
        self.window.set_home_shelf(plugins.SHELF_NAME, tracks)
        for name, error in failures:
            self.surface.set_status(f"🔌 {name}: shelf source failed ({error})")

    # --- local library (v0.7.0): scan your own folders ---

    def _local_roots(self) -> list[str]:
        """Remembered scan roots (one per line in the settings)."""
        raw = str(self.settings.value("local/roots", "") or "")
        return [line for line in (l.strip() for l in raw.splitlines()) if line]

    def _save_local_roots(self, roots: list[str]) -> None:
        self.settings.setValue("local/roots", "\n".join(roots))

    def _local_add_folder(self) -> None:
        """📂 Pick a folder, remember it, scan it (dialog only in real UI)."""
        root = QFileDialog.getExistingDirectory(
            self.window, "Add a music folder"
        )
        if not root:
            return
        roots = self._local_roots()
        if root not in roots:
            roots.append(root)
            self._save_local_roots(roots)
        self._scan_local_roots()

    def _local_rescan(self) -> None:
        """🔄 Re-walk every remembered folder (or ask for one first)."""
        if not self._local_roots():
            self._local_add_folder()
            return
        self._scan_local_roots()

    def _scan_local_roots(self) -> None:
        """Kick a scan job: the walk runs on the pool, the upsert stays here."""
        self.surface.set_status("Scanning local folders…")
        job = LocalScanJob(self._local_roots())
        job.signals.finished.connect(self._on_local_scan)
        job.signals.failed.connect(
            lambda msg: self.surface.set_status(f"Local scan failed: {msg}")
        )
        self._launch(job)

    def _on_local_scan(self, payload) -> None:
        """Scan results: one batched upsert, then refresh the view."""
        entries, stats = payload
        added, updated = self.store.upsert_local_tracks(entries)
        self.window.set_local_tracks(self.store.local_tracks())
        tail = " · list capped" if stats.get("truncated") else ""
        self.surface.set_status(
            f"📁 Local: {added} added · {updated} updated · "
            f"{stats.get('scanned', 0)} scanned{tail}"
        )

    def _local_file_url(self, track: Track | None) -> str | None:
        """A file:// URL for a local-library track, or None.

        Local tracks carry video_id ``local-<path hash>``; the real path
        lives in the store. A file that has vanished on disk returns None
        with a status note instead of pretending anything is playable.
        """
        if track is None or not track.video_id.startswith("local-"):
            return None
        try:
            path = self.store.local_track_path(track.video_id)
        except Exception:   # noqa: BLE001 - store trouble must not break playback
            return None
        if not path:
            return None
        if not Path(path).is_file():
            self.surface.set_status(f"Local file is gone: {Path(path).name}")
            return None
        from PyQt6.QtCore import QUrl

        return QUrl.fromLocalFile(path).toString()

    # --- the phone remote (v0.7.1) ---

    def _remote_controller(self) -> object:
        """A duck-typed controller for RemoteServer — Qt-free, headless-safe.

        Reads only live state from the playback core; every command maps
        onto the same core calls the window buttons use, so nothing here
        can bypass the immune system or the queue engine.
        """
        core = self.core

        class Bridge:
            def status(self_inner) -> dict:
                track = core.engine.current
                return {
                    "playing": bool(core.is_playing),
                    "title": getattr(track, "title", None),
                    "artist": getattr(track, "artist", None),
                    "video_id": getattr(track, "video_id", None),
                    "volume": round(float(core.volume), 3),
                    "position_ms": int(core.position_ms),
                    "upcoming": len(core.engine.upcoming),
                }

            def cmd(self_inner, name: str, volume: float | None = None) -> None:
                if name == "toggle":
                    core.toggle()
                elif name == "play":
                    if not core.is_playing:
                        core.toggle()
                elif name == "pause":
                    if core.is_playing:
                        core.toggle()
                elif name == "next":
                    core.next()
                elif name == "prev":
                    core.previous()
                elif name == "vol" and volume is not None:
                    core.set_volume(max(0.0, min(1.0, float(volume))))

        return Bridge()

    def _open_remote(self) -> None:
        """📱 Start (or reuse) the remote session and show the shareable link.

        The link is the key: anyone holding it can drive playback, so the
        dialog says so plainly. The server is LAN-bound but token-gated;
        one session lives per app run and is shut down with the app.
        """
        if self._remote is None:
            self._remote = RemoteServer(self._remote_controller())
            self._remote.start()
        QMessageBox.information(
            self.window,
            "📱 Phone remote",
            "Open this link in your phone's browser (same Wi-Fi):\n\n"
            f"{self._remote.url()}\n\n"
            "The link is the key — anyone who has it can control playback.",
        )

    def _glow_mix(self) -> None:
        """✨ One tap in the On Repeat shelf: your rotation plus kindred fire."""
        self._start_glow_mix()

    def _start_glow_mix(self, store=None, fetch_kindred=None) -> None:
        """Gather the rotation, fetch kindred tracks, blend, play.

        Headless-testable seam: tests may pass a `store` (a fake
        HearthStore) and a synchronous `fetch_kindred(seeds) ->
        list[Track]` instead of the job pool. Never dead-ends — an
        empty rotation gets a gentle note, and a failed/empty fetch
        falls back to playing the rotation as-is.
        """
        store = self.store if store is None else store
        try:
            rotation = list(store.on_repeat(config.GLOW_MIX_SIZE))
        except Exception:   # noqa: BLE001 - a grumpy store still plays something
            rotation = []
        if not rotation:
            self.surface.set_status(
                "Nothing on repeat yet — play a few songs, then light the Glow Mix")
            return
        if fetch_kindred is None:
            if not self._enable_streaming:
                self._play_glow(rotation, kindred=False)   # test mode: no network
                return
            self.surface.set_status("mixing your Glow Mix…")
            job = GlowMixJob(
                self.catalog,
                glow_seeds(rotation, config.GLOW_MIX_ARTISTS),
                rotation,
            )
            job.signals.finished.connect(self._on_glow_ready)
            self._launch(job)
            return
        self.surface.set_status("mixing your Glow Mix…")
        try:
            kindred = list(
                fetch_kindred(glow_seeds(rotation, config.GLOW_MIX_ARTISTS)))
        except Exception:   # noqa: BLE001 - fetch trouble falls back, never dead-ends
            kindred = []
        self._on_glow_ready((rotation, kindred))

    def _on_glow_ready(self, payload) -> None:
        """The kindred harvest landed (rotation, kindred): blend and light it."""
        rotation, kindred = payload
        mix = blend_glow(list(rotation), list(kindred), config.GLOW_MIX_SIZE)
        self._play_glow(mix, kindred=bool(kindred))

    def _play_glow(self, tracks: list[Track], kindred: bool = True) -> None:
        """Shuffle the blend into the queue — the ritual's final flourish."""
        mix = list(tracks)
        if not mix:
            self.surface.set_status("Glow Mix came up empty — play more music first")
            return
        random.shuffle(mix)
        if kindred:
            self.surface.set_status(
                f"✨ Glow Mix: {len(mix)} tracks — your rotation plus kindred fire")
        else:
            self.surface.set_status("✨ Glow Mix: your rotation, straight up")
        self._play_list(mix)

    # --- wake-up alarm (v0.8.0 controls) ---

    def _arm_alarm(self, minutes: int) -> None:
        """Tray schedule: N minutes from now (a new schedule replaces)."""
        if minutes:
            self.alarm.schedule(minutes)
            self._alarm_poll.start()
            self.surface.set_status(f"⏰ Wake-up in {minutes} min")
        else:
            self.alarm.cancel()
            self._alarm_poll.stop()
            self.surface.set_status("Wake-up alarm off")

    def _fire_alarm(self) -> None:
        """The alarm went off: start the music, swell the volume back up.

        Reverse of the sleep timer's fade — silence to the pre-alarm
        level over config.ALARM_FADE_MS, one-shot, nothing persisted.
        """
        self._alarm_poll.stop()
        self._alarm_target = self.core.volume
        self._alarm_step = 0
        self.core.set_volume(0.0)
        if not self.core.is_playing:
            self.core.toggle()   # resume / first-queued behavior, as ever
        self.surface.set_status("⏰ Rise and shine — the fire is lit")
        if self._alarm_fade is None:
            self._alarm_fade = QTimer(self.qapp)
            self._alarm_fade.setInterval(
                max(1, config.ALARM_FADE_MS // config.ALARM_FADE_STEPS))
            self._alarm_fade.timeout.connect(self._alarm_fade_tick)
        self._alarm_fade.start()

    def _alarm_fade_tick(self) -> None:
        """One rung up the volume ladder; the last rung restores exactly."""
        self._alarm_step += 1
        if self._alarm_step >= config.ALARM_FADE_STEPS:
            if self._alarm_fade is not None:
                self._alarm_fade.stop()
            self.core.set_volume(self._alarm_target)
            self._persist()
            return
        self.core.set_volume(
            self._alarm_target * self._alarm_step / config.ALARM_FADE_STEPS)

    # --- ambient mixer (v0.7.0) ---

    def _set_ambient(self, kind: str | None, level: float) -> None:
        """One soundscape at a time; level-only tweaks keep it playing.

        Never raises: on a machine with no audio device (or a dead
        sink) the start is a silent no-op and the status note says so.
        """
        if kind is None:
            self.ambient.stop()
            self.surface.set_status("Ambient: off")
            return
        try:
            level = max(0.0, min(1.0, float(level)))
        except (TypeError, ValueError):
            level = config.AMBIENT_DEFAULT_LEVEL
        label = f"{int(round(level * 100))}%"
        if self.ambient.active and self.ambient.kind == kind:
            self.ambient.set_level(level)
        else:
            if not self.ambient.start(kind):
                self.surface.set_status("Ambient unavailable — no audio device")
                return
            self.ambient.set_level(level)
        name = AMBIENT_KIND_LABELS.get(kind, kind)
        self.surface.set_status(f"Ambient: {name} at {label}")

    def _set_sleep(self, minutes: int) -> None:
        self.core.set_sleep_timer(minutes or None)
        self.window.player_bar.set_sleep_label(minutes or None)

    # --- radio / autoplay ---

    def _start_radio(self, track: Track | None = None) -> None:
        seed = track or self.core.engine.current
        if seed is None:
            self.surface.set_status("Play something first, then start radio")
            return
        if not self._enable_streaming:
            self.surface.set_status(f"Radio from: {seed.title} (test mode)")
            return
        self.surface.set_status(f"Starting radio from {seed.title}…")
        job = RadioJob(self.catalog, seed.video_id)
        job.signals.finished.connect(self._on_radio_ready)
        job.signals.failed.connect(
            lambda title: self.surface.set_status(f"Radio failed: {title}")
        )
        self._launch(job)

    def _on_radio_ready(self, payload) -> None:
        seed_id, tracks = payload
        fresh: list[Track] = []
        seen = {seed_id}
        for track in tracks:
            if track.video_id in seen:
                continue
            seen.add(track.video_id)
            fresh.append(track)
        if not fresh:
            self.surface.set_status("Radio came back empty — try another seed")
            return
        seed = self.core.engine.current
        if seed is not None and seed.video_id == seed_id:
            queue = [seed, *fresh]
        else:
            queue = fresh
        self.core.start_queue(queue, 0)
        self.surface.set_status(f"Radio: {len(queue)} tracks queued")

    def _on_queue_dry(self, track: Track) -> None:
        """Autoplay: the queue ran out — extend it with a radio seed."""
        if not self._enable_streaming:
            return  # unit tests: keep the playback pool out
        if track is None:
            return
        job = RadioJob(self.catalog, track.video_id)
        job.signals.finished.connect(self._on_autoplay_ready)
        job.signals.failed.connect(
            lambda title: self.surface.set_status(f"Radio failed: {title}")
        )
        self._launch(job)

    def _on_autoplay_ready(self, payload) -> None:
        seed_id, tracks = payload
        engine = self.core.engine
        current = engine.current
        moved_on = current is not None and current.video_id != seed_id
        if moved_on:
            return  # the listener picked something else while we were fetching
        seen = {seed_id} | {t.video_id for t in engine.upcoming} | {
            t.video_id for t in engine.history
        }
        fresh = [t for t in tracks if t.video_id not in seen]
        if not fresh:
            self.core.stop()
            self.core.status.emit("Radio: nothing new found")
            return
        engine.upcoming.extend(fresh)
        self.core.queue_changed.emit()
        self.core.next()  # keep the music going without a hiccup

    # --- lyrics ---

    def _fetch_lyrics(self, track: Track) -> None:
        cached = self._lyrics_cache.get(track.video_id)
        if cached is not None:
            plain, lines = cached
            self.window.set_lyrics(track.video_id, plain, lines)
            self._set_overlay_engine(track.video_id, lines)
            return
        if len(self._lyrics_cache) > 200:
            self._lyrics_cache.clear()
        self.window.now_view.set_lyrics_loading()
        job = LyricsJob(self.catalog, track)
        job.signals.finished.connect(self._on_lyrics_ready)
        self._launch(job)

    def _on_lyrics_ready(self, payload) -> None:
        video_id, plain, lines = payload
        self._lyrics_cache[video_id] = (plain, lines)
        self.window.set_lyrics(video_id, plain, lines)
        self._set_overlay_engine(video_id, lines)

    # --- desktop lyrics overlay (v0.8.0) ---

    def _set_overlay_engine(self, video_id: str, lines) -> None:
        """Feed the overlay's timeline, but only for the track still playing."""
        current = self.core.engine.current
        if lines and current is not None and current.video_id == video_id:
            self._lyrics_engine = SyncedLyrics(list(lines))

    def _toggle_overlay(self) -> None:
        """Tray toggle for the desktop lyric strip (never raises)."""
        self._overlay_on = not self._overlay_on
        self.overlay.toggle()

    def _on_lyrics_font_changed(self, size_key: str, family: str) -> None:
        """The Now Playing row changed the lyrics type: persist + spread it."""
        self.settings.setValue("lyrics/size", size_key)
        self.settings.setValue("lyrics/family", family)
        font = lyrics_font(size_key, family)
        self.window.theater_view.apply_lyrics_font(font)
        self.overlay.apply_font(font)

    def _push_overlay_line(self, position_ms: int) -> None:
        """Position tick → the strip, only when enabled, visible and synced."""
        if not self._overlay_on or not self.overlay.isVisible():
            return
        engine = self._lyrics_engine
        if engine is None or engine.empty:
            return
        index = engine.line_at(position_ms)
        if index == self._overlay_index:
            return
        self._overlay_index = index
        if 0 <= index < len(engine.lines):
            next_text = ""
            if index + 1 < len(engine.lines):
                next_text = engine.lines[index + 1].text
            self.overlay.show_line(engine.lines[index].text, next_text)
        else:
            self.overlay.clear()

    def _summon(self) -> None:
        if self.ui_mode == "window":
            self.window.summon()
            return
        self.panel.show()
        self.panel.raise_()
        self.panel.activateWindow()

    def _toggle_surface(self) -> None:
        if self.ui_mode == "window":
            self.window.setVisible(not self.window.isVisible())
        else:
            self.panel.toggleExpand()

    def _focus_search(self) -> None:
        if self.ui_mode == "window":
            self._summon()
            self.window.focus_search()
            return
        self._summon()
        if not self.panel.expanded:
            self.panel.setExpanded()
        self.panel._search.setFocus()

    def _on_tray_activated(self, reason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self.surface.setVisible(not self.surface.isVisible())

    # --- services: MPRIS / update whisper / diagnostics (v0.7.0 reach) ---

    def _on_update_whisper(self, message: str, url: str, tag: str) -> None:
        """A newer hearth was announced: one status line, never a modal."""
        self._update_tag = tag
        text = f"{message}  ·  {url}" if url else message
        self.surface.set_status(text)

    def _dismiss_update_whisper(self) -> None:
        """The tray's 'don't whisper again' for the tag we announced."""
        tag = self._update_tag
        if not tag:
            self.surface.set_status("No update whisper to silence")
            return
        self.whisper.dismiss(tag)
        self.surface.set_status(f"Update whisper silenced for {tag}")

    def _show_diagnostics(self) -> None:
        """🩺 Open the health page (modeless — never blocks the room)."""
        report = gather_report(self.store, resilience=ytm_resilience,
                               fetch_counters=getattr(self.catalog, "counters", None))
        dlg = DiagnosticsDialog(report, self.window)
        self._diag_dlg = dlg
        dlg.show()

    # --- Discord Rich Presence (v0.7.0 reach, opt-in, guarded) ---

    def _on_discord_action(self, checked: bool = False) -> None:
        """The tray toggle flipped: connect or disconnect the bridge."""
        self._set_discord_presence(bool(checked))

    def _set_discord_presence(self, on: bool) -> None:
        """Wire (or unwind) the presence signals. Never raises.

        The config flag gates everything; an empty DISCORD_CLIENT_ID
        means there is nothing to connect to — a status note says so,
        no signals are hooked and no connection is attempted.
        """
        if not config.DISCORD_RPC_ENABLED:
            return
        if not on:
            self._disconnect_presence()
            self.surface.set_status("🎮 Discord presence off")
            return
        client_id = str(getattr(config, "DISCORD_CLIENT_ID", "") or "").strip()
        if not client_id:
            self.surface.set_status(
                "🎮 Discord presence: set DISCORD_CLIENT_ID in hearth/config.py first")
            return
        if not self.presence.start(client_id):
            self.surface.set_status(
                "🎮 Discord presence unavailable — is Discord running?")
            return
        self._presence_duration_ms = 0
        self.core.track_changed.connect(self._on_presence_track)
        self.core.position_changed.connect(self._on_presence_position)
        self.core.duration_changed.connect(self._on_presence_duration)
        track = self.core.engine.current
        if track is not None:
            self._on_presence_track(track)
        self.surface.set_status("🎮 Discord presence on")

    def _disconnect_presence(self) -> None:
        """Unhook every presence signal and drop the IPC (idempotent)."""
        for signal, slot in (
            (self.core.track_changed, self._on_presence_track),
            (self.core.position_changed, self._on_presence_position),
            (self.core.duration_changed, self._on_presence_duration),
        ):
            try:
                signal.disconnect(slot)
            except TypeError:
                pass   # not connected — nothing to unwind
        self.presence.clear()
        self.presence.stop()

    def _on_presence_track(self, track: Track | None) -> None:
        """Track changes push immediately (and re-arm the position throttle)."""
        if track is None:
            self.presence.clear()   # between tracks / stopped: wipe the profile
            return
        self._presence_throttle.stamp()   # the track-change push owns this window
        self._push_presence(track)

    def _on_presence_position(self, position_ms: int) -> None:
        """Position ticks are throttled: at most one push per window."""
        if not self._presence_throttle.allow():
            return
        self._push_presence(self.core.engine.current)

    def _on_presence_duration(self, duration_ms: int) -> None:
        self._presence_duration_ms = max(0, int(duration_ms))

    def _push_presence(self, track: Track | None) -> None:
        """One presence push: core timestamps + a 'Listen along' button."""
        if track is None:
            return
        duration_ms = self._presence_duration_ms or int(track.duration_sec) * 1000
        self.presence.update_track(
            track,
            elapsed_s=max(0, int(self.core.position_ms)) / 1000.0,
            duration_s=max(0, int(duration_ms)) / 1000.0,
            youtube_url=f"https://www.youtube.com/watch?v={track.video_id}",
        )

    # --- persistence ---

    def _restore_settings(self) -> None:
        self.core.set_volume(float(self.settings.value("volume", 0.8)))
        self.panel.set_volume(self.core.volume)
        rate = float(self.settings.value("rate", 1.0))
        self.core.set_rate(rate)
        self.window.player_bar.set_speed_label(self.core.rate)
        repeat = str(self.settings.value("repeat", config.REPEAT_OFF))
        if repeat in config.REPEAT_MODES:
            self.core.set_repeat(repeat)
        autoplay = self.settings.value("autoplay", config.AUTOPLAY_DEFAULT)
        self.core.set_autoplay(
            autoplay in (True, "true", "True", "1", 1)
            if isinstance(autoplay, (str, int)) else bool(autoplay)
        )
        # crossfade length (whole seconds; 0 = off)
        crossfade = self._int_setting("crossfade", config.CROSSFADE_DEFAULT_SECONDS)
        self.core.set_crossfade(crossfade)
        self.window.set_crossfade(self.core.crossfade_seconds)
        # lyrics settings: size preset + family for every lyric surface
        size_key = str(self.settings.value("lyrics/size",
                                           config.LYRICS_DEFAULT_SIZE_KEY))
        family = str(self.settings.value("lyrics/family", ""))
        self.window.set_lyrics_font(lyrics_font(size_key, family),
                                    size_key, family)
        self.overlay.apply_font(lyrics_font(size_key, family))
        # the style closet: glass look + wallpaper survive restarts
        self._wallpaper_alpha = self._int_setting(
            "ui/wallpaper_alpha", config.WALLPAPER_ALPHA_DEFAULT)
        theme.set_style(str(self.settings.value("ui/style",
                                                config.STYLE_DEFAULT)))
        bg_path = str(self.settings.value("ui/background", "") or "")
        if bg_path and Path(bg_path).is_file():
            theme.set_wallpaper_alpha(self._wallpaper_alpha)
            if not self.window.set_background_image(bg_path):
                self.settings.remove("ui/background")
                theme.set_wallpaper_alpha(None)
        self._restyle()

    def _int_setting(self, key: str, default: int) -> int:
        """QSettings INI values come back as str — coerce, never raise."""
        try:
            return int(self.settings.value(key, default))
        except (TypeError, ValueError):
            return default

    def _restore_session(self) -> None:
        pos = self.settings.value("geometry/pos")
        if pos is not None:
            self.panel.move(pos)
        size = self.settings.value("window/size")
        if size is not None:
            self.window.resize(size)
        win_pos = self.settings.value("window/pos")
        if win_pos is not None:
            self.window.move(win_pos)
        favorites = self.store.favorites()
        if favorites:
            self.surface.set_status(f"{len(favorites)} favorites pinned")
        self._refresh_home()
        self._refresh_library()
        data = self._load_session_snapshot()
        if data is not None:
            self._apply_session_snapshot(data)

    def _persist(self) -> None:
        self.settings.setValue("volume", self.core.volume)
        self.settings.setValue("rate", self.core.rate)
        self.settings.setValue("repeat", self.core.engine.repeat)
        self.settings.setValue("autoplay", self.core.autoplay)
        self.settings.setValue("crossfade", self.core.crossfade_seconds)
        self.settings.setValue("theme", self.panel._palette.key)
        self.settings.setValue("ui/style", theme.active_style())
        self.settings.setValue("ui/wallpaper_alpha", self._wallpaper_alpha)
        self.settings.setValue("geometry/pos", self.panel.pos())
        self.settings.setValue("window/size", self.window.size())
        self.settings.setValue("window/pos", self.window.pos())
        self._save_session_snapshot()

    # --- the style closet (v0.8.0): glass looks + custom wallpapers ---

    def _restyle(self) -> None:
        """Re-pour every surface with the current palette + style policy."""
        pal = self.panel._palette
        self.window.apply_palette(pal)
        self.panel.apply_palette(pal)
        self.toast.setStyleSheet(theme.build_stylesheet(pal))
        self.overlay.set_palette(pal)
        self.command_palette.apply_palette(pal)

    def _open_style_closet(self) -> None:
        """Live-preview style packs and wallpapers; cancel puts it back."""
        base_style = theme.active_style()
        base_alpha = self._wallpaper_alpha
        dlg = StylePickerDialog(
            base_style, base_alpha,
            self.window.wallpaper_path is not None, self.window)
        dlg.style_trial.connect(self._trial_style)
        dlg.style_chosen.connect(self._commit_style)
        dlg.background_picked.connect(self._set_background_from_file)
        dlg.background_cleared.connect(self._clear_background)
        dlg.wallpaper_alpha_changed.connect(self._set_wallpaper_alpha)

        def _restore_unsaved() -> None:
            if not dlg.saved:
                self._apply_style_policy(
                    base_style,
                    base_alpha if self.window.wallpaper_path else None)

        dlg.finished.connect(_restore_unsaved)
        dlg.exec()

    def _apply_style_policy(self, key: str, alpha: int | None) -> None:
        """Set the module-wide look and re-pour every surface."""
        theme.set_style(key)
        theme.set_wallpaper_alpha(alpha)
        self._restyle()

    def _trial_style(self, key: str) -> None:
        self._apply_style_policy(key,
                                 self._wallpaper_alpha
                                 if self.window.wallpaper_path else None)

    def _commit_style(self, key: str) -> None:
        self._apply_style_policy(key,
                                 self._wallpaper_alpha
                                 if self.window.wallpaper_path else None)
        self.settings.setValue("ui/style", key)
        self.window.set_status(
            f"Style: {theme.STYLES[key].label}")

    def _set_wallpaper_alpha(self, value: int) -> None:
        self._wallpaper_alpha = int(value)
        self.settings.setValue("ui/wallpaper_alpha", self._wallpaper_alpha)
        theme.set_wallpaper_alpha(
            self._wallpaper_alpha if self.window.wallpaper_path else None)
        self._restyle()

    def _set_background_from_file(self, path: str) -> None:
        """Import the picked image into the store and wear it (never raises)."""
        stored = theme.import_wallpaper(path, self._dir / "backgrounds")
        if stored is None:
            self.window.set_status("Couldn't load that image — try a PNG or JPG")
            return
        if not self.window.set_background_image(stored):
            self.window.set_status("Couldn't load that image — try a PNG or JPG")
            return
        theme.set_wallpaper_alpha(self._wallpaper_alpha)
        self.settings.setValue("ui/background", stored)
        self._restyle()
        self.window.set_status("Background set ✨")

    def _clear_background(self) -> None:
        self.window.set_background_image(None)
        self.settings.remove("ui/background")
        theme.set_wallpaper_alpha(None)
        self._restyle()
        self.window.set_status("Background removed")

    # --- session snapshot: the queue survives a restart (v0.7.0) ---

    def _session_snapshot(self) -> dict:
        """The current queue + transport state as one portable dict."""
        engine = self.core.engine
        return {
            "format": "hearth-session",
            "version": 1,
            "current": engine.current.to_dict() if engine.current else None,
            "history": [
                t.to_dict() for t in engine.history[-config.SESSION_MAX_HISTORY:]
            ],
            "upcoming": [
                t.to_dict() for t in engine.upcoming[: config.SESSION_MAX_UPCOMING]
            ],
            "position_ms": self.core.session_position_ms if engine.current else 0,
            "volume": self.core.volume,
            "rate": self.core.rate,
            "repeat": engine.repeat,
        }

    def _save_session_snapshot(self, *_args) -> None:
        """Write the snapshot (never raises — a dead snapshot is no tragedy)."""
        try:
            payload = json.dumps(self._session_snapshot(), ensure_ascii=False)
            self._snapshot_path.write_text(payload, encoding="utf-8")
        except (OSError, TypeError, ValueError):
            log.debug("session snapshot skipped", exc_info=True)

    def _load_session_snapshot(self) -> dict | None:
        try:
            data = json.loads(self._snapshot_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if not isinstance(data, dict) or data.get("format") != "hearth-session":
            return None
        return data

    def _apply_session_snapshot(self, data: dict) -> bool:
        """Rebuild queue + display from a snapshot. True when restored."""

        def _track(entry) -> Track | None:
            if not isinstance(entry, dict):
                return None
            try:
                track = Track.from_dict(entry)
            except (TypeError, ValueError):
                return None
            return track if track.video_id and track.title else None

        current = _track(data.get("current"))
        history = [t for t in (_track(e) for e in data.get("history") or []) if t]
        upcoming = [t for t in (_track(e) for e in data.get("upcoming") or []) if t]
        if current is None and not upcoming:
            return False
        rate = data.get("rate")
        if isinstance(rate, (int, float)) and rate > 0:
            # before restore_queue: no current track yet, so the rate
            # change is not mistaken for a per-track speed preference
            self.core.set_rate(float(rate))
        self.core.restore_queue(
            current, history, upcoming,
            resume_ms=int(data.get("position_ms") or 0),
        )
        volume = data.get("volume")
        if isinstance(volume, (int, float)):
            self.core.set_volume(float(volume))
        repeat = data.get("repeat")
        if repeat in config.REPEAT_MODES:
            self.core.set_repeat(repeat)
        if current is not None:
            self.panel.set_track(current)
            self.window.set_track(current)
            self.window.set_pinned(self.store.is_pinned(current.video_id))
            self.surface.set_status("Session restored — press play to continue")
        self._on_queue_changed()
        return True

    def shutdown(self) -> None:
        # Let in-flight jobs land while their recipients are still alive.
        QThreadPool.globalInstance().waitForDone(5000)
        if self._remote is not None:
            self._remote.stop()   # the phone remote burns out with the app
        self.ambient.stop()   # release the ambience sink fully on the way out
        self.mpris.stop()
        self.presence.stop()  # and let Discord forget the hearth until next time
        self._persist()
        self.store.close()

    # --- run ---

    def run(self) -> int:
        if self.guard is not None and not self.guard.is_primary:
            return 0
        if self.ui_mode == "window":
            self.window.show()
        else:
            self.panel.show()
        code = self.qapp.exec()
        self.shutdown()
        return code


def main() -> int:
    hearth = Hearth(single_instance="--no-single-instance" not in sys.argv)
    return hearth.run()
