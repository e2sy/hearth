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
]
