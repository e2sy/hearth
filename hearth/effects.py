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
)
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QGraphicsDropShadowEffect,
    QGraphicsOpacityEffect,
    QWidget,
)

from . import motion


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
    lift = Lift(effect, base_level=base_level, color=color)
    widget.installEventFilter(_LiftFilter(lift))
    widget._hearth_lift = lift
    return lift


def slide_toast(widget: QWidget, ms: int = 320) -> None:
    """Toast entrance: rise from below the final resting point while fading in."""
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
    "Lift", "hover_lift",
]
