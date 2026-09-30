"""v0.8.0 controls: Ctrl+K palette, mini-visualizer, smart shuffle,
wake-up alarm, per-track speed memory — headless, offscreen, no network,
no sleeps (the alarm clock is injected)."""

import pytest
from PyQt6.QtCore import QEvent, Qt
from PyQt6.QtGui import QKeyEvent, QShortcut

from hearth import config
from hearth.app import AlarmController
from hearth.command_palette import (
    CommandAction,
    CommandPalette,
    fuzzy_score,
    rank_actions,
)
from hearth.player import QueueEngine
from hearth.window import MiniVisualizer, VisualizerModel

from .test_app_smoke import make_hearth
from .test_models import make_track


def queue_of(pairs) -> list:
    """Tracks from (video_id, artist) pairs — the smart-shuffle fuel."""
    return [make_track(video_id=vid, artist=artist) for vid, artist in pairs]


def press(dlg: CommandPalette, key: Qt.Key) -> None:
    """Send a key through the search box's event filter."""
    ev = QKeyEvent(QEvent.Type.KeyPress, key, Qt.KeyboardModifier.NoModifier)
    dlg.eventFilter(dlg._search, ev)


# ----------------------------------------------------------------- palette: ranking

def test_fuzzy_rank_prefix_beats_word_start_beats_subsequence():
    actions = [
        CommandAction("Apply theme"),      # 'pl' contiguous, mid-word
        CommandAction("Some playlist"),    # 'pl' at a word boundary
        CommandAction("Play / Pause"),     # 'pl' right at the start
    ]
    ranked = rank_actions(actions, "pl")
    labels = [actions[i].label for _score, i in ranked]
    assert labels == ["Play / Pause", "Some playlist", "Apply theme"]


def test_fuzzy_keywords_rank_below_label_and_no_match_hides():
    quit_act = CommandAction("Quit Hearth", None, "exit close goodbye")
    assert fuzzy_score("exit", "Quit Hearth") == -1     # label itself has no hit
    acts = [quit_act, CommandAction("Exit fullscreen")]
    labels = [acts[i].label for _score, i in rank_actions(acts, "exit")]
    assert labels == ["Exit fullscreen", "Quit Hearth"]  # label prefix outranks keyword
    assert rank_actions(acts, "banana") == []            # no match → hidden


def test_empty_query_lists_everything_in_registration_order():
    acts = [CommandAction(f"Action {n}") for n in range(4)]
    ranked = rank_actions(acts, "")
    assert [i for _score, i in ranked] == [0, 1, 2, 3]
    assert all(score == 0 for score, _i in ranked)


# ----------------------------------------------------------------- palette: dialog

def test_palette_filter_enter_runs_and_closes(qapp):
    dlg = CommandPalette("grove")
    runs = []
    dlg.set_actions([
        CommandAction("Play / Pause", lambda: runs.append("play")),
        CommandAction("Shuffle queue", lambda: runs.append("shuf")),
    ])
    dlg._search.setText("shuf")
    assert dlg._list.count() == 1
    press(dlg, Qt.Key.Key_Return)
    assert runs == ["shuf"]
    assert not dlg.isVisible()


def test_palette_arrows_navigate_wrap_and_double_click_runs(qapp):
    dlg = CommandPalette(None)
    runs = []
    dlg.set_actions([
        CommandAction(f"Action {n}", lambda n=n: runs.append(n))
        for n in range(3)
    ])
    assert dlg._list.currentRow() == 0
    press(dlg, Qt.Key.Key_Down)
    assert dlg._list.currentRow() == 1
    press(dlg, Qt.Key.Key_Up)
    press(dlg, Qt.Key.Key_Up)               # wraps to the bottom
    assert dlg._list.currentRow() == 2
    dlg._list.itemDoubleClicked.emit(dlg._list.item(2))
    assert runs == [2]
    assert not dlg.isVisible()


def test_palette_escape_closes_and_popup_resets(qapp):
    dlg = CommandPalette("frost")
    dlg.set_actions([CommandAction("Play / Pause")])
    dlg.popup()
    assert dlg.isVisible()
    dlg._search.setText("pla")
    assert dlg._list.count() == 1
    press(dlg, Qt.Key.Key_Escape)
    assert not dlg.isVisible()
    dlg.popup()                             # a fresh open starts clean
    assert dlg._search.text() == ""
    assert dlg._list.count() == 1


def test_palette_empty_and_failing_actions_never_raise(qapp):
    dlg = CommandPalette(None)
    dlg.set_actions([])
    dlg._search.setText("anything")
    assert dlg._list.count() == 0
    press(dlg, Qt.Key.Key_Down)
    press(dlg, Qt.Key.Key_Return)           # nothing highlighted: harmless
    dlg.run_current()
    dlg.run_index(99)
    dlg._move(1)
    assert dlg.actions == []

    def boom():
        raise RuntimeError("sick action")

    dlg.set_actions([CommandAction("Boom", boom)])
    dlg._search.setText("boom")
    press(dlg, Qt.Key.Key_Return)           # runs, swallows the error, closes
    assert not dlg.isVisible()


# ----------------------------------------------------------------- palette: app wiring

def test_app_registers_expected_palette_actions(tmp_path, qapp):
    hearth = make_hearth(tmp_path)
    labels = [a.label for a in hearth.command_palette.actions]
    assert "Play / Pause" in labels
    assert "Shuffle queue" in labels
    assert "Cycle repeat" in labels
    assert "Mute / Unmute" in labels
    assert "Toggle favorite" in labels
    assert "Quit Hearth" in labels
    assert "Go to Now Playing" in labels
    assert f"Theme: {config.PALETTES['frost'].label}" in labels
    assert "Speed 0.75x" in labels          # one action per PLAYBACK_RATES entry
    assert len(labels) == 7 + len(hearth.window.VIEWS) \
        + len(config.PALETTES) + len(config.PLAYBACK_RATES) + 1
    hearth.shutdown()


def test_app_theme_and_favorite_actions_work(tmp_path, qapp):
    hearth = make_hearth(tmp_path)
    theme_action = next(a for a in hearth.command_palette.actions
                        if a.label == "Theme: Frost")
    theme_action.callback()
    assert hearth.panel._palette is config.PALETTES["frost"]
    assert hearth.window._palette is config.PALETTES["frost"]
    assert hearth.command_palette._palette is config.PALETTES["frost"]
    assert hearth.settings.value("theme") == "frost"

    fav_action = next(a for a in hearth.command_palette.actions
                      if a.label == "Toggle favorite")
    hearth.core.play_track(make_track(video_id="fav1"))
    fav_action.callback()
    assert hearth.store.is_pinned("fav1")
    fav_action.callback()
    assert not hearth.store.is_pinned("fav1")
    hearth.shutdown()


def test_app_speed_action_sets_rate_and_saves_pref(tmp_path, qapp):
    hearth = make_hearth(tmp_path)
    hearth.core.play_track(make_track(video_id="spd1"))
    action = next(a for a in hearth.command_palette.actions
                  if a.label == "Speed 1.5x")
    action.callback()
    assert hearth.core.rate == 1.5
    assert hearth.store.track_pref("spd1", "rate") == 1.5
    hearth.shutdown()


def test_ctrl_k_shortcut_installed_and_opens_palette(tmp_path, qapp):
    hearth = make_hearth(tmp_path)
    chords = [s.key().toString() for s in hearth.window.findChildren(QShortcut)]
    assert "Ctrl+K" in chords
    hearth._open_command_palette()
    assert hearth.command_palette.isVisible()
    assert hearth.command_palette._search.text() == ""
    hearth.command_palette.close()
    hearth.shutdown()


# ----------------------------------------------------------------- visualizer model

def test_visualizer_playing_bounds_and_unknown_state_ignored():
    model = VisualizerModel(bars=8, seed=7)
    model.set_state("vibing")               # unknown states are ignored
    assert model.state == "stopped"
    model.set_state("playing")
    vals = []
    for _ in range(300):
        vals = model.tick(0.06)
        assert len(vals) == 8
        assert all(0.0 <= v <= 1.0 for v in vals)
    assert all(v > 0.2 for v in vals)       # actually dancing, not idling


def test_visualizer_per_tick_delta_capped():
    model = VisualizerModel(bars=6, seed=3)
    model.set_state("playing")
    dt = 0.06
    cap = VisualizerModel.MAX_STEP_PER_SEC * dt + 1e-9
    prev = model.tick(dt)
    for _ in range(50):
        vals = model.tick(dt)
        assert all(abs(b - a) <= cap for a, b in zip(prev, vals))
        prev = vals
    vals = model.tick(10.0)                 # a giant frame clamps to 0.25 s
    cap_wide = VisualizerModel.MAX_STEP_PER_SEC * 0.25 + 1e-9
    assert all(abs(b - a) <= cap_wide for a, b in zip(prev, vals))
    assert all(0.0 <= v <= 1.0 for v in vals)
    assert model.tick(-5.0) == vals         # negative dt: time stands still


def test_visualizer_paused_and_stopped_settle():
    model = VisualizerModel(bars=8, seed=11)
    model.set_state("playing")
    for _ in range(60):
        model.tick(0.06)
    model.set_state("paused")
    vals = []
    for _ in range(80):
        vals = model.tick(0.06)
    assert all(0.0 <= v <= 0.2 for v in vals)     # low resting wave
    model.set_state("stopped")
    for _ in range(40):
        vals = model.tick(0.06)
    assert all(v <= 1e-6 for v in vals)           # flat baseline


def test_visualizer_seed_determinism():
    def dance(seed: int):
        model = VisualizerModel(bars=10, seed=seed)
        model.set_state("playing")
        return [model.tick(0.06) for _ in range(40)]

    assert dance(42) == dance(42)
    assert dance(42) != dance(43)


# ----------------------------------------------------------------- visualizer widget

def test_mini_visualizer_widget_paints_and_timer_lifecycle(qapp):
    viz = MiniVisualizer(config.PALETTES["orchid"], bars=12,
                         model=VisualizerModel(bars=12, seed=5))
    assert not viz._timer.isActive()
    viz.show()
    assert viz._timer.isActive()
    viz.set_state("playing")
    viz._on_tick()                          # drive one frame by hand
    assert not viz.grab().isNull()          # forces a real paintEvent offscreen
    viz.hide()
    assert not viz._timer.isActive()


def test_player_bar_visualizer_tracks_playback_state(tmp_path, qapp):
    hearth = make_hearth(tmp_path)
    viz = hearth.window.player_bar.visualizer
    assert viz._model.state == "stopped"
    hearth.core.play_track(make_track())
    assert viz._model.state == "paused"     # track loaded, no audio yet
    hearth.core._note_playing(True)         # the backend's real state path
    assert viz._model.state == "playing"
    hearth.core._note_playing(False)
    assert viz._model.state == "paused"
    hearth.shutdown()


# ----------------------------------------------------------------- smart shuffle

def test_smart_shuffle_spreads_artists():
    eng = QueueEngine()
    eng.start_queue(queue_of([
        ("a1", "A"), ("a2", "A"), ("a3", "A"),
        ("b1", "B"), ("b2", "B"), ("c1", "C"),
    ]), start=0)
    eng.shuffle_upcoming_smart()
    artists = [t.artist for t in eng.upcoming]
    assert sorted(t.video_id for t in eng.upcoming) == \
        ["a2", "a3", "b1", "b2", "c1"]      # same multiset of upcoming ids
    for prev, cur in zip(artists, artists[1:]):
        assert prev != cur                  # no two neighbors share an artist
    assert artists[0] != "A"                # the now-playing artist rests first


def test_smart_shuffle_same_artist_ties_keep_queue_order():
    eng = QueueEngine()
    eng.start_queue(queue_of([("s1", "Solo"), ("s2", "Solo"), ("s3", "Solo")]), 0)
    eng.shuffle_upcoming_smart()
    # All candidates tie: the least-recently-queued wins, order preserved.
    assert [t.video_id for t in eng.upcoming] == ["s2", "s3"]


def test_smart_shuffle_empty_single_and_all_recent_are_safe():
    eng = QueueEngine()
    eng.shuffle_upcoming_smart()            # empty queue: no-op
    assert eng.upcoming == []
    eng.start_queue(queue_of([("x1", "X"), ("x2", "X")]), 0)
    eng.shuffle_upcoming_smart()            # single upcoming: stays put
    assert [t.video_id for t in eng.upcoming] == ["x2"]
    eng2 = QueueEngine()
    eng2.start_queue(queue_of([("y1", "Y"), ("y2", "Y")]), 0)
    eng2.advance()
    eng2.go_back()                          # upcoming = [y2], but y2 just played
    eng2.shuffle_upcoming_smart()           # nothing eligible: left alone
    assert [t.video_id for t in eng2.upcoming] == ["y2"]


def test_smart_shuffle_never_replays_recent_ids():
    eng = QueueEngine()
    eng.start_queue(queue_of([
        ("p1", "P"), ("q1", "Q"), ("q2", "Q"), ("r1", "R"),
    ]), 0)
    eng.advance()                           # q1 played…
    eng.go_back()                           # …and dropped back into upcoming
    assert "q1" in {t.video_id for t in eng.upcoming}
    history_ids = [t.video_id for t in eng.history]
    current = eng.current
    eng.shuffle_upcoming_smart()
    assert {t.video_id for t in eng.upcoming}.isdisjoint(eng._recent_ids)
    assert eng.current is current           # playback untouched
    assert [t.video_id for t in eng.history] == history_ids


def test_smart_shuffle_preserves_history_and_multiset():
    eng = QueueEngine()
    eng.start_queue(queue_of([
        ("a1", "A"), ("b1", "B"), ("a2", "A"), ("c1", "C"),
        ("b2", "B"), ("a3", "A"), ("d1", "D"), ("c2", "C"),
    ]), 0)
    eng.advance()
    history_ids = [t.video_id for t in eng.history]
    current = eng.current
    eng.shuffle_upcoming_smart()
    assert [t.video_id for t in eng.history] == history_ids
    assert eng.current is current
    assert sorted(t.video_id for t in eng.upcoming) == \
        ["a2", "a3", "b2", "c1", "c2", "d1"]


def test_shuffle_button_routes_smart_or_plain_by_config(tmp_path, qapp, monkeypatch):
    hearth = make_hearth(tmp_path)
    calls = []
    hearth.core.shuffle = lambda: calls.append("plain")
    hearth.core.shuffle_smart = lambda *a: calls.append("smart")
    monkeypatch.setattr(config, "SMART_SHUFFLE", True)
    hearth.window.shuffle_requested.emit()   # button + hotkey S funnel through here
    monkeypatch.setattr(config, "SMART_SHUFFLE", False)
    hearth.window.shuffle_requested.emit()
    assert calls == ["smart", "plain"]
    hearth.shutdown()


# ----------------------------------------------------------------- wake-up alarm

def test_alarm_schedule_remaining_math():
    now = [1_000_000]
    alarm = AlarmController(clock=lambda: now[0])
    assert alarm.schedule(2) == now[0] + 120_000
    assert alarm.armed
    assert alarm.remaining_ms() == 120_000
    now[0] += 30_000
    assert alarm.remaining_ms() == 90_000


def test_alarm_replacement_and_cancel():
    now = [0]
    alarm = AlarmController(clock=lambda: now[0])
    alarm.schedule(60)
    alarm.schedule(1)                       # a new schedule replaces the old
    assert 0 < alarm.remaining_ms() <= 60_000
    alarm.cancel()
    assert not alarm.armed
    assert alarm.remaining_ms() == 0
    assert alarm.poll() is False            # a cancelled alarm never fires


def test_alarm_fires_once_exactly_at_deadline():
    now = [50_000]
    alarm = AlarmController(clock=lambda: now[0])
    fired = []
    alarm.fired.connect(lambda: fired.append(1))
    alarm.schedule(1)                       # deadline: 110_000
    now[0] = 109_999
    assert alarm.poll() is False
    assert fired == []
    now[0] = 110_000
    assert alarm.poll() is True             # fired the moment the deadline passed
    assert fired == [1]
    assert not alarm.armed
    assert alarm.poll() is False            # one-shot
    assert fired == [1]


def test_app_alarm_fades_volume_and_consumes_resume(tmp_path, qapp):
    hearth = make_hearth(tmp_path)
    hearth.core.set_volume(0.8)
    hearth.core.restore_queue(make_track(video_id="wake1"), resume_ms=4_000)
    hearth._fire_alarm()
    assert hearth.core.volume == 0.0                # dipped for the swell
    assert hearth.core._resume_pending is None      # toggle reused the resume path
    assert hearth.core.engine.current.video_id == "wake1"
    for _ in range(config.ALARM_FADE_STEPS):
        hearth._alarm_fade_tick()
    assert abs(hearth.core.volume - 0.8) < 1e-9     # back to the pre-alarm level
    assert not hearth._alarm_fade.isActive()
    hearth.shutdown()


def test_app_alarm_schedule_then_fire_then_cancel(tmp_path, qapp):
    hearth = make_hearth(tmp_path)
    hearth.core.restore_queue(make_track(video_id="wake2"), resume_ms=0)
    hearth._arm_alarm(15)
    assert hearth.alarm.armed
    assert hearth._alarm_poll.isActive()
    hearth.alarm._now = lambda: hearth.alarm._deadline + 1   # jump the clock
    assert hearth.alarm.poll() is True              # fired → the fade began
    assert hearth.core.volume == 0.0
    hearth._arm_alarm(0)                            # the "Off / cancel" row
    assert not hearth.alarm.armed
    assert not hearth._alarm_poll.isActive()
    hearth.shutdown()


# ----------------------------------------------------------------- per-track speed memory

def test_rate_change_saves_track_pref(tmp_path, qapp):
    hearth = make_hearth(tmp_path)
    hearth.core.set_rate(1.5)               # no current track: nobody to remember
    assert hearth.store.track_prefs_all("rate1") == {}
    hearth.core.play_track(make_track(video_id="rate1"))
    hearth.core.set_rate(1.25)
    assert hearth.store.track_pref("rate1", "rate") == 1.25
    hearth.core.set_rate(1.0)
    assert hearth.store.track_pref("rate1", "rate") == 1.0
    hearth.shutdown()


def test_track_start_restores_saved_rate(tmp_path, qapp):
    hearth = make_hearth(tmp_path)
    hearth.store.set_track_pref("slow1", "rate", 0.75)
    hearth.core.play_track(make_track(video_id="slow1"))
    assert hearth.core.rate == 0.75
    hearth.shutdown()


def test_rate_pref_out_of_range_falls_back_to_1(tmp_path, qapp):
    hearth = make_hearth(tmp_path)
    hearth.store.set_track_pref("fast1", "rate", 3.0)
    hearth.store.set_track_pref("odd1", "rate", 0.9)   # not a PLAYBACK_RATES preset
    hearth.core.play_track(make_track(video_id="fast1"))
    assert hearth.core.rate == 1.0
    hearth.core.play_track(make_track(video_id="odd1"))
    assert hearth.core.rate == 1.0
    hearth.core.play_track(make_track(video_id="fresh1"))   # no pref at all
    assert hearth.core.rate == 1.0
    hearth.shutdown()


def test_session_rate_restore_does_not_pollute_track_prefs(tmp_path, qapp):
    hearth = make_hearth(tmp_path)
    hearth._apply_session_snapshot({
        "format": "hearth-session",
        "version": 1,
        "current": make_track(video_id="snap1").to_dict(),
        "history": [],
        "upcoming": [],
        "position_ms": 1_000,
        "volume": 0.5,
        "rate": 1.25,
        "repeat": "off",
    })
    assert hearth.core.rate == 1.25
    assert hearth.store.track_prefs_all("snap1") == {}   # a snapshot is not a choice
    hearth.shutdown()
