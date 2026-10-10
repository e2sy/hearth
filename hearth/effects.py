"""Depth & motion: drop shadows, accent glows, and view transitions.

The 2020s toolkit behind the modern look — everything is plain Qt
graphics effects and property animations, so it works headless and on
every platform without new dependencies.

Lifetime rules (learned the hard way): every animation is created once,
parented to its own effect, and parked on the widget it serves. Nothing
is ever deleted from inside a `finished` signal — restarting a persistent
animation is always safe, even at teardown time. A widget that already
carries a non-opacity effect (the cover's glow, say) politely skips the
fade instead of getting its effect replaced.
"""

from __future__ import annotations

from PyQt6.QtCore import (
    QEasingCurve,
    QEvent,
    QObject,
    QParallelAnimationGroup,
    QPoint,
    QPropertyAnimation,
    QTimer,
)
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QGraphicsDropShadowEffect,
    QGraphicsOpacityEffect,
    QWidget,
)

from . import config, motion


def add_shadow(widget: QWidget, color: str = "#000000", blur: int = 26,
               dy: int = 8, alpha: int = 160) -> QGraphicsDropShadowEffect:
    """Anchor a widget above the canvas with a soft ground shadow."""
    effect = QGraphicsDropShadowEffect(widget)
    c = QColor(color)
    c.setAlpha(max(0, min(255, alpha)))
    effect.setColor(c)
    effect.setBlurRadius(blur)
    effect.setOffset(0, dy)
    widget.setGraphicsEffect(effect)
    return effect


def add_glow(widget: QWidget, color: str, blur: int = 34,
             alpha: int = 110) -> QGraphicsDropShadowEffect:
    """Halo an element (play button, big cover) in its accent color."""
    effect = QGraphicsDropShadowEffect(widget)
    c = QColor(color)
    c.setAlpha(max(0, min(255, alpha)))
    effect.setColor(c)
    effect.setBlurRadius(blur)
    effect.setOffset(0, 0)
    widget.setGraphicsEffect(effect)
    return effect


def set_glow_color(effect: QGraphicsDropShadowEffect, color: str,
                   alpha: int = 110) -> None:
    """Recolor an existing glow (used on palette swaps)."""
    c = QColor(color)
    c.setAlpha(max(0, min(255, alpha)))
    effect.setColor(c)


def _ensure_opacity_effect(widget: QWidget) -> QGraphicsOpacityEffect | None:
    """The widget's (possibly existing) opacity effect, or None if it
    already carries a different effect we must not replace."""
    current = widget.graphicsEffect()
    if isinstance(current, QGraphicsOpacityEffect):
        return current
    if current is not None:
        return None   # another effect lives here; fades yield to it
    effect = QGraphicsOpacityEffect(widget)
    widget.setGraphicsEffect(effect)
    return effect


def _ramp(effect: QGraphicsOpacityEffect, ms: int) -> QPropertyAnimation:
    """A persistent, restartable opacity ramp owned by `effect`."""
    anim = getattr(effect, "_hearth_ramp", None)
    if anim is None:
        anim = QPropertyAnimation(effect, b"opacity", effect)
        effect._hearth_ramp = anim
    anim.stop()
    anim.setDuration(ms)
    anim.setStartValue(0.0)
    anim.setEndValue(1.0)
    anim.setEasingCurve(QEasingCurve.Type.OutCubic)
    return anim


def fade_in(widget: QWidget, ms: int = 220) -> None:
    """One-shot opacity ramp; safe to call on every view switch."""
    effect = _ensure_opacity_effect(widget)
    if effect is None:
        return
    effect.setOpacity(0.0)
    _ramp(effect, ms).start()


class Lift:
    """Hover choreography for one widget, along the pure lift ladder.

    Owns two persistent, restartable ramps (blur and y-offset) parked on
    the widget's shadow effect — same lifetime rules as every animation
    here: created once, parented to the effect, always safe to restart.
    Color (alpha) jumps to the target level's value at ramp start; the
    blur and offset do the visible easing.
    """

    def __init__(self, effect: QGraphicsDropShadowEffect,
                 base_level: int = motion.LEVEL_REST,
                 color: str = "#000000"):
        self.effect = effect
        self.base = base_level
        self.color = color
        self.hovered = False
        self.pressed = False
        self._blur = QPropertyAnimation(effect, b"blurRadius", effect)
        self._dy = QPropertyAnimation(effect, b"yOffset", effect)
        self._tint = QPropertyAnimation(effect, b"color", effect)
        for anim in (self._blur, self._dy):
            anim.setEasingCurve(QEasingCurve.Type.OutCubic)

    def _to(self, level: int, ms: int) -> None:
        blur, dy, alpha = motion.shadow_for(level)
        c = QColor(self.color)
        c.setAlpha(max(0, min(255, alpha)))
        self.effect.setColor(c)
        for anim, end in (
            (self._blur, float(blur)),
            (self._dy, float(dy)),
        ):
            anim.stop()
            anim.setDuration(max(1, ms))
            anim.setStartValue(float(self.effect.blurRadius())
                               if anim is self._blur
                               else float(self.effect.yOffset()))
            anim.setEndValue(end)
            anim.start()

    def _level(self) -> int:
        return motion.level_for(self.base, self.hovered, self.pressed)

    def enter(self) -> None:
        self.hovered = True
        self._to(self._level(), motion.LIFT_MS)

    def leave(self) -> None:
        self.hovered = False
        self.pressed = False
        self._to(self._level(), motion.SETTLE_MS)

    def press(self) -> None:
        self.pressed = True
        self._to(self._level(), motion.PLANT_MS)

    def release(self) -> None:
        self.pressed = False
        self._to(self._level(), motion.LIFT_MS)

    def ground(self, ms: int = motion.FADE_MS) -> None:
        """Entrance: the ground shadow grows in from nothing.

        Used for staggered cascades — a card doesn't pop, it lands. The
        blur and alpha ramp from zero to the resting level while the
        surface itself is simply there. Safe to call repeatedly.
        """
        blur, _dy, alpha = motion.shadow_for(self.base)
        c0 = QColor(self.color)
        c0.setAlpha(0)
        c1 = QColor(self.color)
        c1.setAlpha(max(0, min(255, alpha)))
        self.effect.setColor(c0)
        self._tint.stop()
        self._tint.setDuration(max(1, ms))
        self._tint.setStartValue(c0)
        self._tint.setEndValue(c1)
        self._tint.start()
        self._blur.stop()
        self._blur.setDuration(max(1, ms))
        self._blur.setStartValue(0.0)
        self._blur.setEndValue(float(blur))
        self._blur.start()


class _LiftFilter(QObject):
    """Funnel enter/leave/press/release into a Lift. Never consumes."""

    def __init__(self, lift: Lift):
        super().__init__(lift.effect)
        self._lift = lift

    def eventFilter(self, obj, event) -> bool:  # noqa: N802 - Qt naming
        et = event.type()
        if et == QEvent.Type.Enter:
            self._lift.enter()
        elif et == QEvent.Type.Leave:
            self._lift.leave()
        elif et == QEvent.Type.MouseButtonPress:
            self._lift.press()
        elif et == QEvent.Type.MouseButtonRelease:
            self._lift.release()
        return False


def hover_lift(widget: QWidget, base_level: int = motion.LEVEL_REST,
               color: str = "#000000") -> Lift:
    """Give a widget its hover life: rise on enter, sink on press,
    settle on leave — along the pure lift ladder (hearth/motion.py).

    Installs its own ground shadow at the resting level (a widget can
    carry only one graphics effect, so this *is* the shadow). The Lift
    is parked at `widget._hearth_lift` and the filter is parented to
    the effect, so everything dies with the widget.
    """
    blur, dy, alpha = motion.shadow_for(base_level)
    effect = add_shadow(widget, color=color, blur=blur, dy=dy,
                        alpha=alpha)
    if not config.MOTION_ENABLED:
        # reduced motion: the surface keeps its resting shadow and its
        # dignity — no filter, no choreography
        widget._hearth_lift = None
        return None
    lift = Lift(effect, base_level=base_level, color=color)
    widget.installEventFilter(_LiftFilter(lift))
    widget._hearth_lift = lift
    return lift


def start_pulse(widget: QWidget, color: str,
                period_ms: int = motion.PULSE_MS,
                ticks: int = 20) -> None:
    """Give a widget a breathing accent glow (the now-playing heart).

    A tick timer walks motion.pulse_blur's triangle wave into the glow
    effect's blur radius. The pulse is parked at `widget._hearth_pulse`;
    a widget already pulsing is left alone (start is idempotent).
    """
    if getattr(widget, "_hearth_pulse", None) is not None:
        return
    if not config.MOTION_ENABLED:
        return                     # no breathing under reduced motion
    effect = add_glow(widget, color, blur=motion.PULSE_BLUR_LOW, alpha=100)
    widget._hearth_pulse = _Pulse(widget, effect, period_ms, ticks)


def stop_pulse(widget: QWidget) -> None:
    """End a widget's breathing glow and take the effect slot back."""
    pulse = getattr(widget, "_hearth_pulse", None)
    if pulse is None:
        return
    pulse.stop()
    widget._hearth_pulse = None


class _Pulse(QObject):
    """Timer-driven breath behind start_pulse (parented to its effect)."""

    def __init__(self, widget: QWidget,
                 effect: QGraphicsDropShadowEffect,
                 period_ms: int, ticks: int):
        super().__init__(effect)
        self._effect = effect
        self._tick_n = 0
        self._timer = QTimer(self)
        self._timer.setInterval(max(1, int(period_ms) // max(1, int(ticks))))
        self._timer.timeout.connect(self._on_tick)
        self._timer.start()

    def _on_tick(self) -> None:
        self._tick_n += 1
        self._effect.setBlurRadius(
            motion.pulse_blur(self._tick_n,
                              low=motion.PULSE_BLUR_LOW,
                              high=motion.PULSE_BLUR_HIGH))

    def stop(self) -> None:
        self._timer.stop()


def slide_toast(widget: QWidget, ms: int = 320) -> None:
    """Toast entrance: rise from below the final resting point while fading in."""
    if not config.MOTION_ENABLED:
        return                     # a reduced-motion toast just appears
    effect = _ensure_opacity_effect(widget)
    if effect is None:
        return
    group = getattr(widget, "_hearth_slide_group", None)
    if group is None:
        fade = QPropertyAnimation(effect, b"opacity", effect)
        rise = QPropertyAnimation(widget, b"pos")
        group = QParallelAnimationGroup(effect)
        group.addAnimation(fade)
        group.addAnimation(rise)
        widget._hearth_slide_group = group
    end = widget.geometry().topLeft()
    start = QPoint(end.x(), end.y() + 18)
    group.stop()
    effect.setOpacity(0.0)
    fade_anim = group.animationAt(0)
    fade_anim.setDuration(ms)
    fade_anim.setStartValue(0.0)
    fade_anim.setEndValue(1.0)
    fade_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
    rise_anim = group.animationAt(1)
    rise_anim.setDuration(ms)
    rise_anim.setStartValue(start)
    rise_anim.setEndValue(end)
    rise_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
    group.start()


__all__ = [
    "add_shadow", "add_glow", "set_glow_color", "fade_in", "slide_toast",
    "Lift", "hover_lift", "start_pulse", "stop_pulse",
]
