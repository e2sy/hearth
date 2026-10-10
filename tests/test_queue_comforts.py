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
