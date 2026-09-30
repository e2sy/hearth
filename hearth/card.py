"""The Rewind card: your year at the hearth, painted into one shareable PNG.

The Rewind story already tells itself inside the app (rewind.py — pure
words, no Qt). This module is the share button's engine: the same
scenes, laid out on a palette-colored card sized for a phone wallpaper,
saved as a PNG. The painter is deliberately the only resident — rewind.py
keeps its "pure data → pure words" promise untouched.

Never raises: a missing Qt, a full disk, or a jailed path all come back
as a quiet False, because an export button that crashes would be a poor
apology. Offscreen-safe (CI paints into a QImage, no screen involved).
"""

from __future__ import annotations

from . import config

CARD_WIDTH = 640
CARD_HEIGHT = 800
CARD_MARGIN = 48
CARD_LINE_GAP = 14
MAX_SCENES = 8   # the card stays a card, not a ledger (rewind.MAX_SCENES twins it)


def render_card(scenes, path, palette_key: str | None = None,
                width: int = CARD_WIDTH, height: int = CARD_HEIGHT) -> bool:
    """Paint `scenes` onto a PNG card. True only when a file landed."""
    try:
        lines = [str(scene).strip() for scene in (scenes or [])[:MAX_SCENES]]
        lines = [line for line in lines if line]
        if not lines:
            return False
        from PyQt6.QtCore import QRect, Qt
        from PyQt6.QtGui import QColor, QFont, QImage, QPainter
        from .config import get_palette

        pal = get_palette(palette_key)
        img = QImage(int(width), int(height), QImage.Format.Format_ARGB32_Premultiplied)
        img.fill(QColor(pal.bg))
        painter = QPainter(img)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
            # the warm glow behind everything — a hearth breathes light
            painter.save()
            glow = QColor(pal.accent)
            glow.setAlpha(26)
            painter.setBrush(glow)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(QRect(int(width * -0.1), int(height * -0.12),
                                      int(width * 1.2), int(width * 1.2)))
            painter.restore()
            # headline
            painter.setPen(QColor(pal.text))
            title_font = QFont()
            title_font.setPixelSize(40)
            title_font.setBold(True)
            painter.setFont(title_font)
            painter.drawText(QRect(CARD_MARGIN, CARD_MARGIN,
                                   width - 2 * CARD_MARGIN, 120),
                             Qt.TextFlag.TextWordWrap, "Your year at the hearth")
            # accent underline
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(pal.accent))
            painter.drawRoundedRect(QRect(CARD_MARGIN, CARD_MARGIN + 92, 132, 6), 3, 3)
            # the scenes — each wrapped honestly, dim headers glow-soft
            body_font = QFont()
            body_font.setPixelSize(23)
            painter.setFont(body_font)
            y = CARD_MARGIN + 140
            bottom = height - CARD_MARGIN - 40
            for line in lines:
                metrics = painter.fontMetrics()
                rect = metrics.boundingRect(
                    QRect(0, 0, width - 2 * CARD_MARGIN, 1000),
                    Qt.TextFlag.TextWordWrap, line)
                if y + rect.height() > bottom:
                    break   # the card ends before the story is embarrassed
                if line.startswith(("🔥", "🌱", "🧭", "🕯", "📅", "🎯")):
                    painter.setPen(QColor(pal.accent_soft))
                else:
                    painter.setPen(QColor(pal.text))
                painter.drawText(QRect(CARD_MARGIN, y,
                                       width - 2 * CARD_MARGIN, rect.height() + 6),
                                 Qt.TextFlag.TextWordWrap, line)
                y += rect.height() + CARD_LINE_GAP
            # sign-off
            small = QFont()
            small.setPixelSize(17)
            painter.setFont(small)
            painter.setPen(QColor(pal.text_dim))
            painter.drawText(QRect(CARD_MARGIN, height - CARD_MARGIN,
                                   width - 2 * CARD_MARGIN, 30),
                             Qt.TextFlag.TextSingleLine,
                             f"Hearth {config.VERSION} — keep the fire warm")
        finally:
            painter.end()
        return bool(img.save(str(path), "PNG"))
    except Exception:  # noqa: BLE001 - a failed card is a False, never a crash
        return False
