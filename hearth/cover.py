"""Cover art tiles: painted flame fallback + lazy async album art.

The 3D pass: album art lands in a rounded, beveled frame; the painted
mark gains a glass sheen and an accent bloom behind the flame; the Now
stage mirrors its cover in a floor reflection.
"""

from __future__ import annotations

import logging

from PyQt6.QtCore import Qt, QTimer, QUrl, pyqtSignal
from PyQt6.QtGui import (
    QColor,
    QFont,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPixmap,
    QTransform,
    QRadialGradient,
)
from PyQt6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest
from PyQt6.QtWidgets import QLabel

from .config import Palette

log = logging.getLogger(__name__)

_COVER_TIMEOUT_MS = 8000


def rounded_pixmap(pixmap: QPixmap, radius: int) -> QPixmap:
    """Clip any pixmap into a rounded-corner card (the modern art frame)."""
    if pixmap.isNull():
        return pixmap
    out = QPixmap(pixmap.size())
    out.fill(Qt.GlobalColor.transparent)
    painter = QPainter(out)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    path = QPainterPath()
    path.addRoundedRect(0.0, 0.0, float(out.width()), float(out.height()),
                        radius, radius)
    painter.setClipPath(path)
    painter.drawPixmap(0, 0, pixmap)
    painter.end()
    return out


def reflected_pixmap(pixmap: QPixmap, depth_frac: float = 0.34,
                     strength: int = 70) -> QPixmap:
    """Mirror the cover below itself, fading to nothing — the 3D floor."""
    if pixmap.isNull():
        return pixmap
    h = max(8, int(pixmap.height() * depth_frac))
    flipped = pixmap.transformed(
        QTransform().scale(1.0, -1.0), Qt.TransformationMode.SmoothTransformation
    )
    strip = flipped.copy(0, 0, flipped.width(), min(h * 3, flipped.height())).scaled(
        pixmap.width(), h,
        Qt.AspectRatioMode.IgnoreAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )
    out = QPixmap(pixmap.width(), pixmap.height() + h + 8)
    out.fill(Qt.GlobalColor.transparent)
    painter = QPainter(out)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.drawPixmap(0, 0, pixmap)
    fade = QLinearGradient(0.0, float(pixmap.height() + 8), 0.0,
                           float(out.height()))
    fade.setColorAt(0.0, QColor(255, 255, 255, strength))
    fade.setColorAt(1.0, QColor(255, 255, 255, 0))
    painter.save()
    painter.setOpacity(0.55)
    painter.drawPixmap(0, pixmap.height() + 8, strip)
    painter.restore()
    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationIn)
    painter.fillRect(0, pixmap.height() + 8, out.width(), h + 8, fade)
    painter.end()
    return out


def paint_mark(palette: Palette, side: int = 168, char: str = "🔥") -> QPixmap:
    """The Hearth mark at any size: flame glyph on a glossy 3D shell tile."""
    pixmap = QPixmap(side, side)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    radius = side * 0.14

    # shell: vertical light-to-dark gradient (the "lit from above" pass)
    shell = QLinearGradient(0.0, 0.0, 0.0, float(side))
    shell.setColorAt(0.0, QColor(_lift(palette.surface_alt, 0.06)))
    shell.setColorAt(0.5, QColor(palette.surface_alt))
    shell.setColorAt(1.0, QColor(palette.surface))
    tile = QPainterPath()
    tile.addRoundedRect(0.0, 0.0, float(side), float(side), radius, radius)
    painter.fillPath(tile, shell)

    # glass sheen: soft radial highlight pooled in the upper third
    sheen = QRadialGradient(side * 0.5, side * 0.16, side * 0.62)
    sheen.setColorAt(0.0, QColor(255, 255, 255, 34))
    sheen.setColorAt(1.0, QColor(255, 255, 255, 0))
    painter.fillPath(tile, sheen)

    # bevel: light edge on top, dark edge on the bottom rim
    edge = QLinearGradient(0.0, 0.0, 0.0, float(side))
    edge.setColorAt(0.0, QColor(255, 255, 255, 46))
    edge.setColorAt(0.45, QColor(255, 255, 255, 0))
    edge.setColorAt(1.0, QColor(0, 0, 0, 90))
    pen = painter.pen()
    pen.setWidthF(max(1.0, side * 0.012))
    pen.setBrush(edge)
    painter.setPen(pen)
    painter.drawPath(tile)

    # accent bloom behind the glyph: the flame glowing off the tile
    ar, ag, ab = (int(palette.accent[1:3], 16),
                  int(palette.accent[3:5], 16),
                  int(palette.accent[5:7], 16))
    bloom = QRadialGradient(side * 0.5, side * 0.52, side * 0.42)
    bloom.setColorAt(0.0, QColor(ar, ag, ab, 90))
    bloom.setColorAt(1.0, QColor(ar, ag, ab, 0))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.fillPath(tile, bloom)

    # the glyph itself
    painter.setPen(QColor(palette.accent))
    font = QFont()
    font.setPixelSize(max(12, int(side * 0.62)))
    painter.setFont(font)
    painter.drawText(pixmap.rect(), 0x0084, char)  # AlignCenter
    painter.end()
    return pixmap


def _lift(color: str, t: float) -> str:
    """Nudge a #rrggbb toward white by t (0–1)."""
    r, g, b = int(color[1:3], 16), int(color[3:5], 16), int(color[5:7], 16)
    return (f"#{round(r + (255 - r) * t):02x}"
            f"{round(g + (255 - g) * t):02x}"
            f"{round(b + (255 - b) * t):02x}")


class CoverTile(QLabel):
    """A square cover: painted mark first, album art once it downloads."""

    art_changed = pyqtSignal(QPixmap)   # fires whenever the visible art swaps

    def __init__(self, palette: Palette, side: int = 168, parent=None):
        super().__init__(parent)
        self._palette = palette
        self._side = side
        self._nam: QNetworkAccessManager | None = None
        self._reply: QNetworkReply | None = None
        self._timeout = QTimer(self)
        self._timeout.setSingleShot(True)
        self._timeout.timeout.connect(self._abort)
        self.setFixedSize(side, side)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setProperty("tile", True)
        self.set_mark()

    # --- content ---

    def set_mark(self) -> None:
        self._set_pixmap(paint_mark(self._palette, self._side))

    def set_track_cover(self, url: str) -> None:
        if not url:
            self.set_mark()
            return
        if self._nam is None:
            self._nam = QNetworkAccessManager(self)
        if self._reply is not None:
            self._reply.abort()
        request = QNetworkRequest(QUrl(url))
        request.setTransferTimeout(_COVER_TIMEOUT_MS)
        self._reply = self._nam.get(request)
        self._reply.finished.connect(self._on_cover)
        self._timeout.start(_COVER_TIMEOUT_MS)

    # --- internals ---

    def _set_pixmap(self, pixmap: QPixmap) -> None:
        scaled = pixmap.scaled(
            self._side, self._side,
            Qt.AspectRatioMode.KeepAspectRatioByExpanding,
            Qt.TransformationMode.SmoothTransformation,
        )
        frame = rounded_pixmap(scaled, max(8, round(self._side * 0.14)))
        self.setPixmap(frame)
        self.art_changed.emit(frame)

    def _abort(self) -> None:
        if self._reply is not None:
            self._reply.abort()

    def _on_cover(self) -> None:
        self._timeout.stop()
        reply, self._reply = self._reply, None
        if reply is None:
            return
        try:
            if reply.error() != QNetworkReply.NetworkError.NoError:
                return  # keep the painted mark; offline is a first-class state
            data = reply.readAll()
            art = QPixmap()
            if not art.loadFromData(bytes(data)):
                return
            self._set_pixmap(art)
        finally:
            reply.deleteLater()

    def apply_palette(self, palette: Palette) -> None:
        self._palette = palette
        if self.pixmap() is None:
            self.set_mark()
