"""Regression test for the QGraphicsDropShadowEffect deleted crash.

The v0.7.4 Windows binary crashed with:
    RuntimeError: wrapped C/C++ object of type
    QGraphicsDropShadowEffect has been deleted

Reproduction:
1. Create a card widget with ``hover_lift`` (a shadow effect parented
   to the widget, plus a Lift wrapper holding a Python ref to that
   effect).
2. Delete the widget (Qt destroys the C++ effect since it's parented
   to the widget).
3. Fire ``leave()`` on the still-alive Lift wrapper — before the fix
   this raised RuntimeError because the wrapper tried to call
   ``self.effect.setColor(...)`` on a deleted C++ object.

After the fix, every Lift/Pulse/breathe method that touches the
effect bails out cleanly via :func:`hearth.effects._alive`.
"""

import pytest

from PyQt6.QtWidgets import QLabel, QWidget

from hearth.effects import Lift, _alive, hover_lift, start_pulse


def test_lift_leave_survives_deleted_effect(qapp):
    """The crash site: a Lift wrapper outlives its effect's C++ object."""
    w = QLabel("ghost card")
    lift = hover_lift(w, base_level=1)
    assert lift is not None  # MOTION_ENABLED is True in tests

    # Simulate the widget being deleted during a view rebuild — the
    # C++ QGraphicsDropShadowEffect dies with its parent, but the
    # Python Lift wrapper still holds a reference.
    del w
    # Force Qt to flush deletion — when the C++ object is gone, our
    # _alive helper must say so before we touch it.
    qapp.processEvents()

    # The exact crash path from the user's screenshot: a Leave event
    # fires on the deleted widget, Lift.leave() runs Lift._to(), and
    # _to() touches self.effect. Must not raise.
    lift.leave()
    lift.enter()
    lift.press()
    lift.release()
    lift.ground(ms=10)
    # Repeated calls still don't raise — the wrapper is permanently
    # in the "host gone" state and that's fine.
    lift.leave()
    assert _alive(lift.effect) is False


def test_lift_to_directly_with_deleted_effect(qapp):
    """Direct call to Lift._to() on a deleted effect must bail quietly."""
    w = QLabel("card")
    lift = hover_lift(w, base_level=0)
    del w
    qapp.processEvents()
    # Direct call — covers the ground() path too.
    lift._to(level=2, ms=100)
    lift.ground(ms=10)


def test_pulse_tick_survives_deleted_effect(qapp):
    """The other crash site: a Pulse timer ticks after its widget dies."""
    w = QLabel("now playing row")
    start_pulse(w, color="#ff7a18")
    pulse = w._hearth_pulse
    assert pulse is not None

    # Delete the widget — the C++ effect dies but the _Pulse object
    # still has a self._effect Python ref and its QTimer is still
    # running (parented to the effect, but the timer keeps firing
    # until we stop it).
    del w
    qapp.processEvents()

    # The next tick used to raise RuntimeError. Now it bails cleanly
    # without touching the dead timer (the timer is parented to the
    # dead effect, so it's also dead — _on_tick must not touch it).
    pulse._on_tick()
    pulse.stop()  # also must not raise on a dead timer
    assert _alive(pulse._timer) is False


def test_set_glow_color_survives_deleted_effect(qapp):
    """A palette swap on a deleted glow must not raise."""
    from hearth.effects import add_glow, set_glow_color

    w = QLabel("glow")
    eff = add_glow(w, color="#ff7a18")
    del w
    qapp.processEvents()
    # Recoloring a deleted effect must be a no-op, not an exception.
    set_glow_color(eff, color="#3fb950", alpha=120)


def test_alive_helper_distinguishes_live_and_dead(qapp):
    """The _alive helper correctly reports the lifetime state."""
    w = QLabel("x")
    eff = w.graphicsEffect()
    # No effect installed yet — _alive on a None is undefined; we don't
    # call it on None in the codebase. Install one via hover_lift.
    lift = hover_lift(w, base_level=0)
    assert lift is not None
    assert _alive(lift.effect) is True

    del w
    qapp.processEvents()
    assert _alive(lift.effect) is False
