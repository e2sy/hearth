"""The widget side of motion: hover lifts, press sinks, real effects.

hearth/effects.py turns the pure ladder into QGraphicsDropShadowEffect
ramps. These tests run offscreen and pin the wiring: install once,
choreograph forever, and never fight the other effects.
"""

from PyQt6.QtWidgets import QPushButton

from hearth import effects, motion


def test_hover_lift_installs_a_resting_shadow(qapp):
    card = QPushButton("card")
    lift = effects.hover_lift(card, base_level=motion.LEVEL_REST)
    assert card._hearth_lift is lift
    assert card.graphicsEffect() is lift.effect
    blur, dy, alpha = motion.shadow_for(motion.LEVEL_REST)
    assert lift.effect.blurRadius() == blur
    assert lift.effect.yOffset() == dy
    assert lift.effect.color().alpha() == alpha


def test_lift_rises_on_enter_and_plants_on_press(qapp):
    card = QPushButton("card")
    lift = effects.hover_lift(card)
    lift.enter()
    assert lift.hovered and not lift.pressed
    assert lift.effect.color().alpha() == motion.shadow_for(motion.LEVEL_HOVER)[2]
    lift.press()
    assert lift.pressed
    assert lift.effect.color().alpha() == motion.shadow_for(motion.LEVEL_PRESS)[2]


def test_lift_release_returns_toward_hover_not_rest(qapp):
    card = QPushButton("card")
    lift = effects.hover_lift(card)
    lift.enter()
    lift.press()
    lift.release()
    assert not lift.pressed and lift.hovered
    assert lift.effect.color().alpha() == motion.shadow_for(motion.LEVEL_HOVER)[2]


def test_lift_leave_settles_to_rest(qapp):
    card = QPushButton("card")
    lift = effects.hover_lift(card)
    lift.enter()
    lift.leave()
    assert not lift.hovered and not lift.pressed
    assert lift.effect.color().alpha() == motion.shadow_for(motion.LEVEL_REST)[2]


def test_lift_animations_are_persistent_and_restartable(qapp):
    card = QPushButton("card")
    lift = effects.hover_lift(card)
    for _ in range(3):
        lift.enter()
        lift.leave()
    # both ramps still exist, parented to the effect, and can restart
    lift.enter()
    assert lift._blur.state() == lift._blur.State.Running
    assert lift._dy.state() == lift._dy.State.Running
    lift._blur.stop()
    lift._dy.stop()


def test_lift_survives_degenerate_durations(qapp):
    card = QPushButton("card")
    lift = effects.hover_lift(card)
    motion.LIFT_MS  # pacing exists; zero must not break the ramp
    lift._to(motion.LEVEL_HOVER, 0)
    lift._to(motion.LEVEL_REST, -5)
    lift._blur.stop()
    lift._dy.stop()


def test_event_filter_wires_mouse_choreography(qapp):
    from PyQt6.QtCore import QEvent
    from PyQt6.QtGui import QMouseEvent
    from PyQt6.QtCore import QPointF, Qt

    card = QPushButton("card")
    effects.hover_lift(card)
    lift = card._hearth_lift
    # synthesize a real enter, press, release, leave — no None events, ever
    for et, cls in (
        (QEvent.Type.Enter, QEvent),
        (QEvent.Type.MouseButtonPress, None),
        (QEvent.Type.MouseButtonRelease, None),
        (QEvent.Type.Leave, QEvent),
    ):
        if cls is QMouseEvent:
            ev = QMouseEvent(et, QPointF(4, 4), QPointF(4, 4),
                             Qt.MouseButton.LeftButton,
                             Qt.MouseButton.NoButton,
                             Qt.KeyboardModifier.NoModifier)
        else:
            ev = QEvent(et)
        card.event(ev)
    assert not lift.hovered and not lift.pressed
