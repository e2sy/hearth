"""Non-focus-stealing desktop toast for "now playing" moments.

The 2020s pass: a translucent glass card that rises into place while
fading in, then whispers away — painted rounded shell, light edge on
top, no native window chrome anywhere in sight.
"""

from __future__ import annotations

from PyQt6.QtCore import QRectF, Qt, QTimer
from PyQt6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath
from PyQt6.QtWidgets import QApplication, QLabel, QVBoxLayout, QWidget

from . import config
from .config import get_palette
from .effects import slide_toast
from .models import Track
from .theme import build_stylesheet
from .utils import mix


class NowPlayingToast(QWidget):
    """A ghost of a notification: appears, whispers the track, fades away."""

    def __init__(self, palette_key: str | None = None):
        super().__init__()
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setFixedSize(config.TOAST_WIDTH, config.TOAST_HEIGHT)
        self._palette = get_palette(palette_key)
        self.setStyleSheet(build_stylesheet(self._palette))

        # room for the painted card inset from the translucent window
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 10)
        self._title = QLabel("🔥 Hearth")
        self._title.setProperty("header", True)
        self._sub = QLabel("")
        self._sub.setProperty("dim", True)
        self._sub.setWordWrap(True)
        layout.addWidget(self._title)
        layout.addWidget(self._sub)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._fade_out)
        self._fade = QTimer(self)
        self._fade.timeout.connect(self._fade_tick)
        self._opacity = 1.0

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt naming
        """The glass card: rounded shell, lit-from-above gradient, bright rim."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        card = QRectF(self.rect().adjusted(4, 4, -4, -4))
        radius = 14.0

        shell = QLinearGradient(0.0, float(card.top()), 0.0,
                                float(card.bottom()))
        shell.setColorAt(0.0, QColor(mix(self._palette.surface_alt,
                                         self._palette.text, 0.05)))
        shell.setColorAt(1.0, QColor(self._palette.surface))
        path = QPainterPath()
        path.addRoundedRect(card, radius, radius)
        painter.fillPath(path, shell)

        rim = QLinearGradient(0.0, float(card.top()), 0.0,
                              float(card.bottom()))
        rim.setColorAt(0.0, QColor(255, 255, 255, 60))
        rim.setColorAt(0.5, QColor(255, 255, 255, 12))
        rim.setColorAt(1.0, QColor(0, 0, 0, 70))
        pen = painter.pen()
        pen.setWidthF(1.2)
        pen.setBrush(rim)
        painter.setPen(pen)
        painter.drawPath(path)
        painter.end()

    def announce(self, track: Track) -> None:
        self._sub.setText(f"▶ {track.display_name}")
        self.reposition()
        self.setWindowOpacity(1.0)
        self._opacity = 1.0
        self.show()
        slide_toast(self, ms=320)   # rise + fade into place
        self._timer.start(config.TOAST_LIFETIME_MS)

    def reposition(self) -> None:
        screen = QApplication.primaryScreen()
        if screen is None:
            return
        geo = screen.availableGeometry()
        self.move(
            geo.right() - self.width() - 18,
            geo.bottom() - self.height() - 18,
        )

    def _fade_out(self) -> None:
        self._fade.start(60)

    def _fade_tick(self) -> None:
        self._opacity -= 0.08
        if self._opacity <= 0.0:
            self._fade.stop()
            self.hide()
            return
        self.setWindowOpacity(max(0.0, self._opacity))
