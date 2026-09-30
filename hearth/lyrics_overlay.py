"""The desktop lyric strip: the song's words, floating over everything.

A tiny frameless window that hugs the bottom of the screen and glows
the current synced line while whispering the next one. Drag it anywhere
with a left-click; the "♪" keeps its seat warm when lyrics are missing.
Opt-in by nature — nothing shows unless the wiring decides to show it.
"""

from __future__ import annotations

from PyQt6.QtCore import QPoint, QRectF, Qt
from PyQt6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import QApplication, QLabel, QVBoxLayout, QWidget

from . import config
from .config import Palette, get_palette
from .effects import add_glow, set_glow_color
from .theme import build_stylesheet, lyrics_font

OVERLAY_WIDTH = 620
OVERLAY_HEIGHT = 148
BG_ALPHA = 205          # window shell opacity (the "semi-transparent bg")
MARGIN = 16             # painted card inset inside the translucent window


class LyricsOverlay(QWidget):
    """A draggable, always-on-top strip showing the current lyric line."""

    def __init__(self, palette_key: str | None = None):
        super().__init__()
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setFixedSize(OVERLAY_WIDTH, OVERLAY_HEIGHT)
        self._palette = get_palette(palette_key)
        self.setStyleSheet(build_stylesheet(self._palette))
        self._drag_offset: QPoint | None = None

        lay = QVBoxLayout(self)
        lay.setContentsMargins(MARGIN + 6, 10, MARGIN + 6, 12)
        lay.setSpacing(2)
        self._now = QLabel("♪")
        self._now.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter)
        self._now.setWordWrap(True)
        self._glow = add_glow(self._now, self._palette.accent, blur=26, alpha=170)
        self._next = QLabel("")
        self._next.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter)
        self._next.setWordWrap(True)
        lay.addWidget(self._now, 1)
        lay.addWidget(self._next)
        self.apply_font(lyrics_font(config.LYRICS_DEFAULT_SIZE_KEY))
        self.set_palette(self._palette)

    # --- content in (never raises on missing lyrics) ---

    def show_line(self, text: str, next_text: str = "") -> None:
        """Light the current line; the next one dims underneath."""
        self._now.setText(str(text or "").strip() or "♪")
        self._next.setText(str(next_text or "").strip())

    def clear(self) -> None:
        """No lyrics for this track — the note keeps the strip company."""
        self.show_line("♪")

    # --- look ---

    def set_palette(self, palette: Palette) -> None:
        """Re-tint the strip (bg shell, accent glow, dim preview)."""
        self._palette = palette
        self.setStyleSheet(build_stylesheet(palette))
        self._style_labels()
        set_glow_color(self._glow, palette.accent, alpha=170)
        self.update()

    def apply_font(self, font: QFont) -> None:
        """Apply the lyrics settings: size on the line, smaller on the preview."""
        self._font = QFont(font)
        now = QFont(font)
        self._now.setFont(now)
        preview = QFont(font)
        preview.setPixelSize(max(10, round(self._font.pixelSize() * 0.55)))
        preview.setBold(False)
        self._next.setFont(preview)
        self._style_labels()

    def _style_labels(self) -> None:
        """Inline styles win over the global 13px rule — size + color live here."""
        px = max(12, self._font.pixelSize())
        self._now.setStyleSheet(
            f"color: {self._palette.accent}; background: transparent;"
            f"font-size: {px}px; font-weight: 700;"
        )
        self._next.setStyleSheet(
            f"color: {self._palette.text_dim}; background: transparent;"
            f"font-size: {max(10, round(px * 0.55))}px;"
        )

    def toggle(self) -> bool:
        """Show/hide the strip. True afterwards means 'on screen'."""
        if self.isVisible():
            self.hide()
            return False
        self.reposition()
        self.clear()
        self.show()
        return True

    def reposition(self) -> None:
        """Dock to the bottom-center of the screen, out of the tray's way."""
        screen = QApplication.primaryScreen()
        if screen is None:
            return
        geo = screen.availableGeometry()
        self.move(
            geo.center().x() - self.width() // 2,
            geo.bottom() - self.height() - 56,
        )

    # --- painting: the translucent rounded shell ---

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt naming
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        card = QRectF(float(MARGIN), float(MARGIN // 2),
                      float(self.width() - MARGIN * 2),
                      float(self.height() - MARGIN))
        radius = 16.0
        shell = QColor(self._palette.bg)
        shell.setAlpha(BG_ALPHA)
        path = QPainterPath()
        path.addRoundedRect(card, radius, radius)
        painter.fillPath(path, shell)
        rim = QLinearGradient(0.0, card.top(), 0.0, card.bottom())
        rim.setColorAt(0.0, QColor(255, 255, 255, 42))
        rim.setColorAt(1.0, QColor(0, 0, 0, 60))
        pen = QPen()
        pen.setWidthF(1.1)
        pen.setBrush(rim)
        painter.setPen(pen)
        painter.drawPath(path)
        painter.end()

    # --- drag: left-click anywhere moves the strip ---

    def mousePressEvent(self, event) -> None:  # noqa: N802 - Qt naming
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_offset = (
                event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            )
            event.accept()

    def mouseMoveEvent(self, event) -> None:  # noqa: N802 - Qt naming
        if self._drag_offset is not None and (
            event.buttons() & Qt.MouseButton.LeftButton
        ):
            self.move(event.globalPosition().toPoint() - self._drag_offset)
            event.accept()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802 - Qt naming
        self._drag_offset = None

