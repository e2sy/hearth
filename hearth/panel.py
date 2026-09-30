"""The floating surface: a slim ribbon that blooms into the full player."""

from __future__ import annotations

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QLinearGradient, QMouseEvent, QPainter, QPainterPath
from PyQt6.QtWidgets import (
    QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QPushButton, QSlider, QVBoxLayout, QWidget,
)

from . import config
from .config import Palette, get_palette
from .models import Track
from .theme import build_stylesheet
from .utils import mix


class SpringPhysics:
    """4-bar spring-damper simulation for the equalizer (pure, testable)."""

    def __init__(self, bars: int = 4, k: float = 26.0, damping: float = 5.2):
        self.bars = bars
        self.k = k
        self.damping = damping
        self.pos = [0.0] * bars
        self.vel = [0.0] * bars

    def impulse(self, strength: float = 1.0) -> None:
        for i in range(self.bars):
            jitter = 0.7 + ((i * 37) % 10) / 10.0 * 0.6
            self.vel[i] += strength * jitter

    def step(self, dt: float) -> list[float]:
        """Advance the simulation; values stay clamped to [0, 1]."""
        for i in range(self.bars):
            target = 0.18 + 0.5 * ((i * 53) % 7) / 7.0
            acc = (target - self.pos[i]) * self.k - self.vel[i] * self.damping
            self.vel[i] += acc * dt
            self.pos[i] += self.vel[i] * dt
            self.pos[i] = max(0.05, min(1.0, self.pos[i]))
        return list(self.pos)


class EqBars(QWidget):
    """The hand-painted visual signature of Hearth."""

    def __init__(self, palette: Palette, parent: QWidget | None = None):
        super().__init__(parent)
        self._palette = palette
        self._physics = SpringPhysics()
        self.setFixedSize(46, 30)
        self._timer = QTimer(self)
        self._timer.setInterval(40)
        self._timer.timeout.connect(self._tick)

    def set_palette(self, palette: Palette) -> None:
        self._palette = palette
        self.update()

    def set_active(self, active: bool) -> None:
        if active and not self._timer.isActive():
            self._physics.impulse(1.0)
            self._timer.start()
        elif not active:
            self._timer.stop()
            self._physics.pos = [0.12] * self._physics.bars
            self.update()

    def _tick(self) -> None:
        self._physics.step(0.04)
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt naming
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        width = self.width() / self._physics.bars
        for i, value in enumerate(self._physics.pos):
            h = max(3, int(value * self.height()))
            x = int(i * width + width * 0.22)
            bw = width * 0.56
            r = bw / 2.0
            hot = self._palette.accent if i % 2 == 0 else self._palette.accent_soft

            # halo: the bar glowing onto the surface behind it
            halo = QColor(hot)
            halo.setAlpha(56)
            glow = QPainterPath()
            glow.addRoundedRect(x - 2.5, self.height() - h - 2.5,
                                bw + 5.0, h + 5.0, r + 2.5, r + 2.5)
            painter.fillPath(glow, halo)

            # glossy bar: bright cap fading toward a deep base
            bar = QLinearGradient(0.0, float(self.height() - h), 0.0,
                                  float(self.height()))
            bar.setColorAt(0.0, QColor(hot))
            bar.setColorAt(1.0, QColor(mix(hot, "#000000", 0.35)))
            path = QPainterPath()
            path.addRoundedRect(x, self.height() - h, bw, h, r, r)
            painter.fillPath(path, bar)
        painter.end()


class FloatingPanel(QWidget):
    """Ribbon (compact) ⇄ panel (expanded) — frameless, always on top."""

    search_submitted = pyqtSignal(str)
    track_picked = pyqtSignal(object)
    play_pause_requested = pyqtSignal()
    next_requested = pyqtSignal()
    prev_requested = pyqtSignal()
    shuffle_requested = pyqtSignal()
    repeat_requested = pyqtSignal()
    volume_changed = pyqtSignal(float)
    seek_requested = pyqtSignal(int)
    expand_toggled = pyqtSignal(bool)

    def __init__(self, palette_key: str | None = None):
        super().__init__()
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self._palette = get_palette(palette_key)
        self._expanded = False
        self._tracks: list[Track] = []
        self._drag_offset = None
        self._build_ui()
        self.apply_palette(self._palette)
        self.setCompact()

    # --- UI construction ---

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        # Compact ribbon
        self._ribbon = QWidget()
        self._ribbon.setProperty("ribbon", True)
        rib = QHBoxLayout(self._ribbon)
        rib.setContentsMargins(14, 10, 14, 10)
        rib.setSpacing(8)
        self._flame = QLabel("🔥")
        self._flame.setStyleSheet("font-size: 18px; background: transparent;")
        self._title = QLabel("Hearth — nothing playing yet")
        self._title.setProperty("dim", True)
        self._btn_prev = QPushButton("⏮")
        self._btn_play = QPushButton("▶")
        self._btn_play.setProperty("accent", True)
        self._btn_next = QPushButton("⏭")
        for b in (self._btn_prev, self._btn_next):
            b.setProperty("flat", True)
            b.setFixedWidth(34)
        self._btn_play.setFixedWidth(40)
        for b in (self._btn_prev, self._btn_play, self._btn_next):
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(
                self.play_pause_requested.emit if b is self._btn_play
                else (self.next_requested.emit if b is self._btn_next else self.prev_requested.emit)
            )
        rib.addWidget(self._flame)
        rib.addWidget(self._title, 1)
        rib.addWidget(self._btn_prev)
        rib.addWidget(self._btn_play)
        rib.addWidget(self._btn_next)

        # Expanded panel
        self._body = QWidget()
        self._body.setProperty("glass", True)
        body = QVBoxLayout(self._body)
        body.setContentsMargins(14, 14, 14, 14)
        body.setSpacing(10)

        self._search = QLineEdit()
        self._search.setPlaceholderText("Search YT Music or paste a link…")
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(config.SEARCH_DEBOUNCE_MS)
        self._debounce.timeout.connect(self._emit_search)
        self._search.textEdited.connect(lambda _: self._debounce.start())
        self._search.returnPressed.connect(self._emit_search)

        self._results = QListWidget()
        self._results.itemDoubleClicked.connect(self._on_result_clicked)

        self._status = QLabel("")
        self._status.setProperty("dim", True)

        self._eq = EqBars(self._palette)

        self._volume = QSlider(Qt.Orientation.Horizontal)
        self._volume.setRange(0, 100)
        self._volume.setValue(80)
        self._volume.valueChanged.connect(lambda v: self.volume_changed.emit(v / 100.0))

        self._seek = QSlider(Qt.Orientation.Horizontal)
        self._seek.setRange(0, 0)
        self._seek.sliderReleased.connect(
            lambda: self.seek_requested.emit(self._seek.value())
        )

        ctrl = QHBoxLayout()
        self._btn_shuffle = QPushButton("🔀")
        self._btn_repeat = QPushButton("🔁")
        self._btn_expand = QPushButton("▾")
        for b, sig in (
            (self._btn_shuffle, self.shuffle_requested),
            (self._btn_repeat, self.repeat_requested),
        ):
            b.setProperty("flat", True)
            b.clicked.connect(sig.emit)
        self._btn_expand.setProperty("flat", True)
        self._btn_expand.clicked.connect(self.toggleExpand)
        ctrl.addWidget(self._btn_shuffle)
        ctrl.addWidget(self._btn_repeat)
        ctrl.addStretch(1)
        ctrl.addWidget(self._eq)
        ctrl.addStretch(1)
        ctrl.addWidget(self._btn_expand)

        body.addWidget(self._search)
        body.addWidget(self._results, 1)
        body.addWidget(self._status)
        body.addWidget(self._seek)
        ctrl.insertWidget(2, self._volume, 1)  # volume sits between shuffle/repeat and stretch
        body.addLayout(ctrl)

        root.addWidget(self._ribbon)
        root.addWidget(self._body)
        self._body.setVisible(False)

    # --- layout modes ---

    def setCompact(self) -> None:  # noqa: N802 - mirrors Qt style
        self._expanded = False
        self._body.setVisible(False)
        self._ribbon.setVisible(True)
        self.setFixedSize(config.RIBBON_WIDTH, config.RIBBON_HEIGHT)
        self.expand_toggled.emit(False)

    def setExpanded(self) -> None:  # noqa: N802
        self._expanded = True
        self._ribbon.setVisible(True)
        self._body.setVisible(True)
        self.setFixedSize(config.PANEL_WIDTH, config.PANEL_HEIGHT)
        self._search.setFocus()
        self.expand_toggled.emit(True)

    def toggleExpand(self) -> None:
        self.setExpanded() if not self._expanded else self.setCompact()

    @property
    def expanded(self) -> bool:
        return self._expanded

    # --- ribbon drag ---

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self._drag_offset is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_offset)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        self._drag_offset = None
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        self.toggleExpand()
        super().mouseDoubleClickEvent(event)

    # --- state updates ---

    def apply_palette(self, palette: Palette) -> None:
        self._palette = palette
        self.setStyleSheet(build_stylesheet(palette))
        self._eq.set_palette(palette)

    def set_track(self, track: Track | None) -> None:
        if track is None:
            self._title.setText("Hearth — nothing playing yet")
            self._title.setProperty("dim", True)
        else:
            self._title.setText(track.display_name)
            self._title.setProperty("dim", False)
        self._title.style().unpolish(self._title)
        self._title.style().polish(self._title)

    def set_playing(self, playing: bool) -> None:
        self._btn_play.setText("⏸" if playing else "▶")
        self._eq.set_active(playing)

    def set_status(self, text: str) -> None:
        self._status.setText(text)

    def set_position(self, position_ms: int) -> None:
        if not self._seek.isSliderDown():
            self._seek.setValue(position_ms)

    def set_duration(self, duration_ms: int) -> None:
        self._seek.setRange(0, max(0, duration_ms))

    def set_volume(self, value: float) -> None:
        self._volume.blockSignals(True)
        self._volume.setValue(int(value * 100))
        self._volume.blockSignals(False)

    # --- search / results ---

    def _emit_search(self) -> None:
        query = self._search.text().strip()
        if query:
            self.search_submitted.emit(query)

    def show_results(self, tracks: list[Track]) -> None:
        self._tracks = list(tracks)
        self._results.clear()
        for track in self._tracks:
            item = QListWidgetItem(f"♪ {track.title}  ·  {track.artist}")
            item.setData(Qt.ItemDataRole.UserRole, track)
            self._results.addItem(item)
        self._status.setText(f"{len(self._tracks)} results" if self._tracks else "No results")

    def _on_result_clicked(self, item: QListWidgetItem) -> None:
        track = item.data(Qt.ItemDataRole.UserRole)
        if track is not None:
            self.track_picked.emit(track)

    @property
    def current_results(self) -> list[Track]:
        return list(self._tracks)
