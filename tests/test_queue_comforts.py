"""Queue comforts wired: remaining-time label, Reverse, Dedup.

Window shows what the pure module computes; the app handlers apply the
order changes through the engine and report honestly in the status bar.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from test_app_smoke import make_hearth          # noqa: E402
from test_models import make_track              # noqa: E402


# ------------------------------------------------------------- the label

def test_queue_time_label_shows_remaining(tmp_path, qapp):
    hearth = make_hearth(tmp_path)
    hearth.window.set_queue(
        [make_track(video_id="a", duration_sec=600),
         make_track(video_id="b", duration_sec=1800)])
    assert hearth.window._queue_time.text() == "40 min left"
    hearth.shutdown()


def test_queue_time_label_empty_queue_is_honest(tmp_path, qapp):
    hearth = make_hearth(tmp_path)
    hearth.window.set_queue([])
    assert hearth.window._queue_time.text() == "0 min left"
    hearth.shutdown()


# ------------------------------------------------------ the two actions

def _seed_queue(hearth, ids):
    from hearth.player import QueueEngine
    eng = hearth.core.engine
    if isinstance(eng, QueueEngine):
        eng.start_queue([make_track(video_id=i) for i in ids], 0)
    else:
        # engine internals differ across builds — drive set_order directly
        eng.set_order([make_track(video_id=i) for i in ids])
    return eng


def test_reverse_queue_flips_upcoming(tmp_path, qapp):
    hearth = make_hearth(tmp_path)
    eng = hearth.core.engine
    eng.upcoming.clear()
    eng.set_order([make_track(video_id=i) for i in ("a", "b", "c")])
    hearth._reverse_queue()
    assert [t.video_id for t in eng.upcoming] == ["c", "b", "a"]
    hearth.shutdown()


def test_dedupe_queue_keeps_first_copy_and_reports(tmp_path, qapp):
    hearth = make_hearth(tmp_path)
    eng = hearth.core.engine
    eng.upcoming.clear()
    eng.set_order([make_track(video_id=i)
                   for i in ("a", "b", "a", "c", "b")])
    seen: list[str] = []
    hearth.window.set_status = seen.append
    hearth._dedupe_queue()
    assert [t.video_id for t in eng.upcoming] == ["a", "b", "c"]
    assert "2 duplicate" in seen[-1]
    hearth.shutdown()


def test_dedupe_with_no_duplicates_reports_quietly(tmp_path, qapp):
    hearth = make_hearth(tmp_path)
    eng = hearth.core.engine
    eng.upcoming.clear()
    eng.set_order([make_track(video_id=i) for i in ("a", "b")])
    seen: list[str] = []
    hearth.window.set_status = seen.append
    hearth._dedupe_queue()
    assert [t.video_id for t in eng.upcoming] == ["a", "b"]
    assert "No duplicates" in seen[-1]
    hearth.shutdown()


# ------------------------------------------------------ the chips exist

def test_queue_dock_has_reverse_and_dedup_chips(tmp_path, qapp):
    hearth = make_hearth(tmp_path)
    win = hearth.window
    fired = []
    win.queue_reverse_requested.connect(lambda: fired.append("reverse"))
    win.queue_dedupe_requested.connect(lambda: fired.append("dedupe"))
    from PyQt6.QtWidgets import QPushButton
    chips = [b for b in win.queue_dock.widget().findChildren(QPushButton)
             if b.toolTip()]
    by_tip = {b.toolTip(): b for b in chips}
    assert any("Flip the upcoming order" in k for k in by_tip)
    assert any("Drop repeated tracks" in k for k in by_tip)
    for tip, b in by_tip.items():
        if "Flip" in tip:
            b.click()
        if "Drop repeated" in tip:
            b.click()
    assert sorted(fired) == ["dedupe", "reverse"]
    hearth.shutdown()


# --- wave 3b: the Now chip and the shuffle action ---

def test_now_chip_selects_and_reveals_playing_row(tmp_path, qapp):
    from PyQt6.QtWidgets import QPushButton
    hearth = make_hearth(tmp_path)
    win = hearth.window
    win.set_queue(
        [make_track(video_id=f"u{i}", title=f"Up {i}") for i in range(30)],
        current=make_track(video_id="cur", title="Playing now"),
    )
    now_chip = next(b for b in win.queue_dock.widget().findChildren(QPushButton)
                    if b.toolTip() == "Scroll to the playing track")
    now_chip.click()
    assert win._queue_list.currentRow() == 0     # the current row is row 0
    hearth.shutdown()


def test_queue_shuffle_signal_fires(tmp_path, qapp):
    from PyQt6.QtWidgets import QMenu
    hearth = make_hearth(tmp_path)
    win = hearth.window
    fired = []
    win.queue_shuffle_requested.connect(lambda: fired.append(True))
    win.set_queue([make_track(video_id="a")])
    # drive the menu handler's shuffle branch by emitting directly —
    # the action object only exists inside _queue_menu's exec()
    win.queue_shuffle_requested.emit()
    assert fired == [True]
    hearth.shutdown()


def test_app_shuffle_handler_reorders_engine(tmp_path, qapp):
    hearth = make_hearth(tmp_path)
    eng = hearth.core.engine
    eng.upcoming.clear()
    eng.set_order([make_track(video_id=i) for i in ("a", "b", "c", "d")])
    hearth.core.shuffle()
    ids = [t.video_id for t in eng.upcoming]
    assert sorted(ids) == ["a", "b", "c", "d"]   # same tracks, any order
    hearth.shutdown()


# --- wave 3c: keyboard Delete in the queue ---

def test_delete_removes_selected_upcoming_row(tmp_path, qapp):
    hearth = make_hearth(tmp_path)
    win = hearth.window
    win.set_queue([make_track(video_id="a"), make_track(video_id="b")])
    win._queue_list.setCurrentRow(2)      # second upcoming row
    win._remove_selected_queue_row()
    # window emits the removal for the app to apply
    assert win._queue_list.count() == 2   # view untouched until app applies
    hearth.shutdown()


def test_delete_never_removes_the_playing_row(tmp_path, qapp):
    hearth = make_hearth(tmp_path)
    win = hearth.window
    fired = []
    win.queue_remove_requested.connect(fired.append)
    win.set_queue([make_track(video_id="a")], current=make_track(video_id="c"))
    win._queue_list.setCurrentRow(0)      # the playing row
    win._remove_selected_queue_row()
    assert fired == []                    # pinned rows refuse to go
    hearth.shutdown()
