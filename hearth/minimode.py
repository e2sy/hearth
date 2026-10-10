"""The pocket hearth: a floating mini player for the corner of the screen.

Hearth condensed to its smallest honest shape — cover dot, one scrolling
title line, transport, seek — in a frameless, always-on-top window you
can drag anywhere and leave glowing over the spreadsheet.

The split is the house style: a **pure model** (``MiniPlayerModel`` —
marquee math, clock formatting, progress state) that headless tests can
exercise with no Qt anywhere, and a thin ``MiniPlayerWindow`` widget
that only paints what the model says and re-emits the gestures as
signals. The widget never decides anything; the main window stays
authoritative and simply mirrors its playback signals into the model.

Nothing here knows about storage or streaming. If the main window
closes, the pocket window goes with it — a stray ember should never
outlive the fire.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable

# ---------------------------------------------------------------- pure model


def fmt_clock(ms: int | None) -> str:
    """Milliseconds → 'm:ss'. Garbage in → '0:00' — never raises."""
    try:
        total = max(0, int(ms or 0)) // 1000
    except (TypeError, ValueError):
        return "0:00"
    return f"{total // 60}:{total % 60:02d}"


@dataclass
class Marquee:
    """A text ticker: walks a long string through a fixed-width window.

    ``visible`` is the slice to show. When the text fits, it just sits
    there. When it does not, the window advances one character per tick,
    rests a moment at each end (so the seam never strobes), then walks
    back the other way — a ping-pong, not a carousel. Changing the text
    or the width resets the walk; asking for a slice never raises.
    """

    text: str = ""
    width: int = 24
    rest_ticks: int = 6
    offset: int = 0
    direction: int = 1
    _rest: int = field(default=0, repr=False)

    def __post_init__(self) -> None:
        self.width = max(4, int(self.width))
        self.rest_ticks = max(0, int(self.rest_ticks))
        self.set_text(self.text, force=True)

    # --- inputs ---

    def set_text(self, text: str, force: bool = False) -> None:
        text = str(text or "")
        if force or text != self.text:
            self.text = text
            self.reset()

    def set_width(self, width: int) -> None:
        width = max(4, int(width))
        if width != self.width:
            self.width = width
            self.reset()

    def reset(self) -> None:
        self.offset = 0
        self.direction = 1
        self._rest = 0

    # --- outputs ---

    @property
    def fits(self) -> bool:
        return len(self.text) <= self.width

    @property
    def visible(self) -> str:
        """The slice to paint right now. Short text → itself, verbatim."""
        if not self.text:
            return ""
        if self.fits:
            return self.text
        offset = max(0, min(self.offset, len(self.text) - self.width))
        return self.text[offset:offset + self.width]

    # --- the walk ---

    def tick(self) -> None:
        """One pulse: advance, rest at the ends, never run off the page."""
        if self.fits or not self.text:
            return
        limit = len(self.text) - self.width
        if self._rest > 0:
            self._rest -= 1
            return
        nxt = self.offset + self.direction
        if nxt >= limit:                      # hit the right edge → rest, reverse
            self.offset = limit
            self.direction = -1
            self._rest = self.rest_ticks
        elif nxt <= 0:                        # hit the left edge → rest, reverse
            self.offset = 0
            self.direction = 1
            self._rest = self.rest_ticks
        else:
            self.offset = nxt


class MiniPlayerModel:
    """Everything the pocket window paints, and nothing else.

    The main window mirrors its playback signals into this model
    (``set_track`` / ``set_playing`` / ``set_position`` / ``set_duration``);
    the widget reads display state back out and re-emits gestures as
    Qt signals. Pure data — no Qt, no I/O, no raises on junk input.
    """

    def __init__(self, marquee_width: int = 24):
        self.title: str = ""
        self.artist: str = ""
        self.playing: bool = False
        self.position_ms: int = 0
        self.duration_ms: int = 0
        self.on_top: bool = True
        self.marquee = Marquee(width=marquee_width)

    # --- inputs (the main window mirrors into these) ---

    def set_track(self, title: str, artist: str) -> None:
        self.title = str(title or "").strip()
        self.artist = str(artist or "").strip()
        self.marquee.set_text(self.title)
        self.position_ms = 0
        self.duration_ms = 0

    def set_playing(self, playing: bool) -> None:
        self.playing = bool(playing)

    def set_position(self, position_ms: int) -> None:
        try:
            self.position_ms = max(0, int(position_ms or 0))
        except (TypeError, ValueError):
            self.position_ms = 0

    def set_duration(self, duration_ms: int) -> None:
        try:
            self.duration_ms = max(0, int(duration_ms or 0))
        except (TypeError, ValueError):
            self.duration_ms = 0

    def toggle_on_top(self) -> bool:
        """Flip the pin; the new value is the answer."""
        self.on_top = not self.on_top
        return self.on_top

    # --- outputs (the widget paints these) ---

    @property
    def empty(self) -> bool:
        return not self.title

    def title_window(self) -> str:
        """The current marquee slice (a silent hearth shows its name)."""
        return self.marquee.visible or "Hearth"

    def artist_label(self) -> str:
        return self.artist or ("nothing playing" if self.empty else "")

    def progress(self) -> tuple[int, int]:
        """(position_ms, duration_ms) — duration 0 while unknown."""
        return self.position_ms, self.duration_ms

    def clock(self) -> str:
        """'1:23 / 3:45' — honest dashes while the duration is unknown."""
        if self.duration_ms <= 0:
            return f"{fmt_clock(self.position_ms)} / --:--"
        return f"{fmt_clock(self.position_ms)} / {fmt_clock(self.duration_ms)}"

    def progress_fraction(self) -> float:
        """0.0–1.0 for a slim progress line; 0.0 while unknown."""
        if self.duration_ms <= 0:
            return 0.0
        return max(0.0, min(1.0, self.position_ms / self.duration_ms))

    def play_glyph(self) -> str:
        return "⏸" if self.playing else "▶"


# ------------------------------------------------------------------ the room


MINI_WIDTH = 320
MINI_HEIGHT = 104


def build_mini_widget(
    palette,
    model: MiniPlayerModel,
    *,
    on_play_pause: Callable[[], None] | None = None,
    on_next: Callable[[], None] | None = None,
    on_prev: Callable[[], None] | None = None,
    on_seek: Callable[[int], None] | None = None,
    on_expand: Callable[[], None] | None = None,
    on_pin: Callable[[bool], None] | None = None,
    on_close: Callable[[], None] | None = None,
):
    """Build the frameless pocket window. Imported lazily so the pure
    model stays importable without Qt (headless test runs, plugins).

    The widget is all mirrors and gestures: it paints what the model
    says, re-emits button presses through the callbacks above, and
    never talks to the player core itself.
    """
    from PyQt6.QtCore import Qt, QTimer
    from PyQt6.QtWidgets import (
        QHBoxLayout,
        QLabel,
        QPushButton,
        QSlider,
        QVBoxLayout,
        QWidget,
    )

    class MiniPlayerWindow(QWidget):
        """A draggable, always-on-top ember for the screen's corner."""

        def __init__(self):
            super().__init__()
            self._model = model
            self._drag_offset = None
            self.setWindowTitle("Hearth — mini player")
            self.setFixedSize(MINI_WIDTH, MINI_HEIGHT)
            self.setWindowFlags(
                Qt.WindowType.FramelessWindowHint
                | Qt.WindowType.Tool                  # no taskbar entry
                | Qt.WindowType.WindowStaysOnTopHint
            )
            self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
            self.setStyleSheet(
                f"background:{palette.surface};border-radius:12px;"
                f"color:{palette.text};"
            )

            lay = QVBoxLayout(self)
            lay.setContentsMargins(14, 10, 14, 10)
            lay.setSpacing(6)

            # top row: accent dot, marquee title, pin, expand, close
            top = QHBoxLayout()
            top.setSpacing(8)
            self._dot = QLabel("🔥")
            self._dot.setStyleSheet("font-size:15px;border:none;")
            self._title = QLabel(model.title_window())
            self._title.setStyleSheet(
                f"color:{palette.text};font-weight:700;font-size:13px;border:none;"
            )
            top.addWidget(self._dot)
            top.addWidget(self._title, 1)
            self._pin = QPushButton("📌")
            self._pin.setToolTip("Toggle always-on-top")
            self._expand = QPushButton("⤢")
            self._expand.setToolTip("Back to the full hearth (or double-click)")
            self._close = QPushButton("✕")
            for b in (self._pin, self._expand, self._close):
                b.setFixedSize(26, 22)
                b.setCursor(Qt.CursorShape.PointingHandCursor)
                b.setStyleSheet(
                    f"border:none;background:transparent;color:{palette.text_dim};font-size:12px;"
                )
            self._pin.clicked.connect(self._toggle_pin)
            self._expand.clicked.connect(self._expand_now)
            self._close.clicked.connect(self._close_now)
            top.addWidget(self._pin)
            top.addWidget(self._expand)
            top.addWidget(self._close)
            lay.addLayout(top)

            # middle row: artist + clock
            mid = QHBoxLayout()
            self._artist = QLabel(model.artist_label())
            self._artist.setStyleSheet(
                f"color:{palette.text_dim};font-size:11px;border:none;"
            )
            self._clock = QLabel(model.clock())
            self._clock.setStyleSheet(
                f"color:{palette.text_dim};font-size:11px;border:none;"
            )
            mid.addWidget(self._artist, 1)
            mid.addWidget(self._clock)
            lay.addLayout(mid)

            # bottom row: transport + slim seek
            bottom = QHBoxLayout()
            bottom.setSpacing(10)
            self._prev = QPushButton("⏮")
            self._play = QPushButton(model.play_glyph())
            self._next = QPushButton("⏭")
            self._play.setFixedSize(38, 30)
            for b in (self._prev, self._next):
                b.setFixedSize(30, 30)
            for b in (self._prev, self._play, self._next):
                b.setCursor(Qt.CursorShape.PointingHandCursor)
                b.setStyleSheet(
                    f"border:none;border-radius:15px;background:{palette.surface_alt};"
                    f"color:{palette.text};font-size:14px;"
                )
            self._play.setStyleSheet(
                f"border:none;border-radius:19px;background:{palette.accent};"
                f"color:{palette.bg};font-size:15px;font-weight:800;"
            )
            self._seek = QSlider(Qt.Orientation.Horizontal)
            self._seek.setRange(0, 1000)
            self._seek.setValue(0)
            self._seek.setStyleSheet(
                f"QSlider::groove:horizontal{{height:4px;background:{palette.hairline};border-radius:2px;}}"
                f"QSlider::sub-page:horizontal{{background:{palette.accent};border-radius:2px;}}"
                f"QSlider::handle:horizontal{{width:11px;height:11px;margin:-4px 0;"
                f"border-radius:5px;background:{palette.accent_soft};}}"
            )
            self._seek.sliderReleased.connect(self._seek_out)
            bottom.addWidget(self._prev)
            bottom.addWidget(self._play)
            bottom.addWidget(self._next)
            bottom.addWidget(self._seek, 1)
            lay.addLayout(bottom)

            for btn, cb in (
                (self._prev, on_prev),
                (self._play, on_play_pause),
                (self._next, on_next),
            ):
                if cb is not None:
                    btn.clicked.connect(cb)

            # the marquee walk: ~10 Hz is smooth without being busy
            self._ticker = QTimer(self)
            self._ticker.timeout.connect(self._pulse)
            self._ticker.start(100)

        # --- mirrors in (the main window calls these) ---

        def apply_track(self, title: str, artist: str) -> None:
            self._model.set_track(title, artist)
            self._repaint()

        def apply_playing(self, playing: bool) -> None:
            self._model.set_playing(playing)
            self._play.setText(self._model.play_glyph())

        def apply_position(self, position_ms: int, duration_ms: int | None = None) -> None:
            self._model.set_position(position_ms)
            if duration_ms is not None:
                self._model.set_duration(duration_ms)
            self._seek.blockSignals(True)          # programmatic, not a grab
            self._seek.setValue(int(self._model.progress_fraction() * 1000))
            self._seek.blockSignals(False)
            self._clock.setText(self._model.clock())

        # --- gestures out ---

        def _seek_out(self) -> None:
            if on_seek is None:
                return
            duration = self._model.duration_ms
            if duration > 0:
                on_seek(int(self._seek.value() / 1000 * duration))

        def _toggle_pin(self) -> None:
            on_top = self._model.toggle_on_top()
            flags = self.windowFlags()
            if on_top:
                flags |= Qt.WindowType.WindowStaysOnTopHint
            else:
                flags &= ~Qt.WindowType.WindowStaysOnTopHint
            self.setWindowFlags(flags)
            self.show()                            # re-flagging hides it; raise it back
            if on_pin is not None:
                on_pin(on_top)

        def _expand_now(self) -> None:
            if on_expand is not None:
                on_expand()

        def _close_now(self) -> None:
            if on_close is not None:
                on_close()
            self.hide()

        def _pulse(self) -> None:
            self._model.marquee.tick()
            shown = self._model.title_window()
            if shown != self._title.text():
                self._title.setText(shown)

        def _repaint(self) -> None:
            self._title.setText(self._model.title_window())
            self._artist.setText(self._model.artist_label())
            self._clock.setText(self._model.clock())
            self._play.setText(self._model.play_glyph())
            self._seek.blockSignals(True)
            self._seek.setValue(int(self._model.progress_fraction() * 1000))
            self._seek.blockSignals(False)

        # --- drag anywhere on the chrome ---

        def mousePressEvent(self, event) -> None:  # noqa: N802 — Qt naming
            if event.button() == Qt.MouseButton.LeftButton:
                self._drag_offset = (
                    event.globalPosition().toPoint() - self.frameGeometry().topLeft()
                )
            super().mousePressEvent(event)

        def mouseMoveEvent(self, event) -> None:  # noqa: N802 — Qt naming
            if self._drag_offset is not None and event.buttons() & Qt.MouseButton.LeftButton:
                self.move(event.globalPosition().toPoint() - self._drag_offset)
            super().mouseMoveEvent(event)

        def mouseReleaseEvent(self, event) -> None:  # noqa: N802 — Qt naming
            self._drag_offset = None
            super().mouseReleaseEvent(event)

        def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802 — Qt naming
            self._expand_now()
            super().mouseDoubleClickEvent(event)

    return MiniPlayerWindow()
