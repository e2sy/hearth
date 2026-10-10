"""System tray presence and single-instance guard."""

from __future__ import annotations

import logging

from PyQt6.QtCore import QByteArray, QRect
from PyQt6.QtGui import QAction, QColor, QIcon, QPainter, QPixmap
from PyQt6.QtNetwork import QLocalServer, QLocalSocket
from PyQt6.QtWidgets import QMenu, QSystemTrayIcon

from . import icons
from .config import Palette, get_palette

log = logging.getLogger(__name__)

INSTANCE_KEY = "hearth-single-instance"


def paint_icon(bg: str = "#1d1712", fg: str = "#f0a437") -> QIcon:
    """A tiny painted flame tile — the vector hearth mark, no font needed."""
    pixmap = QPixmap(64, 64)
    pixmap.fill(QColor(bg))
    painter = QPainter(pixmap)
    painter.drawPixmap(QRect(15, 14, 34, 36), icons.pixmap("flame", fg, 34))
    painter.end()
    return QIcon(pixmap)


def hearth_mark(palette: Palette | None = None) -> QIcon:
    """The hearth mark — the vector flame over a warm shell gradient.

    Palette-aware: pass the active palette to tint the tile, or None to
    use the default scheme.
    """
    from PyQt6.QtGui import QColor, QLinearGradient, QPainter

    p = palette if palette is not None else get_palette(None)
    pixmap = QPixmap(64, 64)
    backdrop = QLinearGradient(0.0, 0.0, 0.0, 64.0)
    backdrop.setColorAt(0.0, QColor(p.surface))
    backdrop.setColorAt(1.0, QColor(p.surface_alt))
    painter = QPainter(pixmap)
    painter.fillRect(pixmap.rect(), backdrop)
    painter.drawPixmap(QRect(15, 14, 34, 36), icons.pixmap("flame", p.accent, 34))
    painter.end()
    return QIcon(pixmap)


class InstanceGuard:
    """Single-instance guard via QLocalServer/QLocalSocket (cross-platform)."""

    def __init__(self):
        self.server: QLocalServer | None = None
        socket = QLocalSocket()
        socket.connectToServer(INSTANCE_KEY)
        self.already_running = socket.waitForConnected(300)
        if self.already_running:
            socket.write(QByteArray(b"show\n"))
            socket.flush()
            socket.waitForBytesWritten(300)
            socket.disconnectFromServer()
            return
        QLocalServer.removeServer(INSTANCE_KEY)  # clear stale socket (Linux)
        self.server = QLocalServer()
        self.server.listen(INSTANCE_KEY)

    @property
    def is_primary(self) -> bool:
        return not self.already_running


class HearthTray(QSystemTrayIcon):
    """Tray icon with the full playback menu (plus optional submenus)."""

    def __init__(self, actions: dict[str, QAction] | None = None,
                 menus: list[QMenu] | None = None, parent=None):
        super().__init__(hearth_mark(), parent)
        self.setToolTip("Hearth — keep the fire warm")
        menu = QMenu()
        if actions:
            for act in actions.values():
                menu.addAction(act)
        if menus:
            for sub in menus:
                menu.addMenu(sub)
        if actions or menus:
            menu.addSeparator()
        quit_act = QAction("Quit Hearth", menu)
        quit_act.triggered.connect(parent.quit if parent is not None else self._noop)
        menu.addAction(quit_act)
        self.setContextMenu(menu)

    @staticmethod
    def _noop() -> None:
        pass
