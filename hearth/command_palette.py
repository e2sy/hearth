"""Ctrl+K: every hearth action, one fuzzy search away.

A small frameless dialog floating over the main window: type to filter,
↑/↓ to walk the list, Enter to run, Esc to slip away. Actions are plain
(label, callable) pairs registered by the app layer — the palette knows
nothing about playback, views, or themes, so it stays tiny and testable.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Callable

from PyQt6.QtCore import QEvent, Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QDialog,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
    QWidget,
)

from . import config
from .config import Palette, get_palette
from .effects import add_shadow
from .utils import mix

log = logging.getLogger(__name__)

# Ranking tiers (higher wins): a match at the very start of the label
# beats a match at a word boundary beats a scattered subsequence beats
# a keyword-only hit. Ties keep registration order.
_PREFIX_SCORE = 300
_WORD_START_SCORE = 200
_SUBSEQUENCE_SCORE = 100
_KEYWORD_SCORE = 50


@dataclass(frozen=True)
class CommandAction:
    """One entry in the palette: a label, its callback, optional fuel."""

    label: str
    callback: Callable[[], None] | None = None
    keywords: str = ""   # extra search text that never shows in the list


def _is_subsequence(needle: str, hay: str) -> bool:
    """True when every char of `needle` appears in `hay`, in order."""
    remaining = iter(hay)
    return all(ch in remaining for ch in needle)


def fuzzy_score(query: str, text: str) -> int:
    """Rank `text` against `query`: prefix > word-start > subsequence.

    Case-insensitive. Returns a tier score, or -1 when the text doesn't
    match at all (hidden from the list). An empty query matches
    everything with score 0 — the whole menu, in registration order.
    """
    q = " ".join((query or "").lower().split())
    t = (text or "").lower()
    if not q:
        return 0
    if t.startswith(q):
        return _PREFIX_SCORE
    if not _is_subsequence(q, t):
        return -1
    # Contiguous somewhere after the start: word-start beats mid-word.
    i = t.find(q)
    while i > 0:
        before = t[i - 1]
        if not (before.isalnum() and q[0].isalnum()):
            return _WORD_START_SCORE
        i = t.find(q, i + 1)
    return _SUBSEQUENCE_SCORE


def _action_score(query: str, action: CommandAction) -> int:
    """Best of the label and the (capped) keyword match."""
    label = fuzzy_score(query, action.label)
    if action.keywords:
        kw = fuzzy_score(query, action.keywords)
        if kw >= 0:
            return max(label, min(kw, _KEYWORD_SCORE))
    return label


def rank_actions(
    actions: list[CommandAction], query: str
) -> list[tuple[int, int]]:
    """Visible (score, action-index) pairs, best first, stable on ties."""
    scored: list[tuple[int, int]] = []
    for index, action in enumerate(actions):
        score = _action_score(query, action)
        if score >= 0:
            scored.append((score, index))
    scored.sort(key=lambda pair: (-pair[0], pair[1]))
    return scored


class CommandPalette(QDialog):
    """Fuzzy launcher over the main window (Ctrl+K).

    Never raises on an empty action list: it just shows nothing, and
    every key on it becomes a harmless no-op.
    """

    action_run = pyqtSignal(str)   # label of the action actually run

    def __init__(self, palette: Palette | str | None = None, parent=None):
        super().__init__(parent)
        self._palette = get_palette(palette)
        self._actions: list[CommandAction] = []
        self._rows: list[int] = []   # action index per visible list row
        self.setWindowTitle("Command palette")
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setModal(True)
        self.setFixedWidth(430)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 10, 10, 10)
        lay.setSpacing(8)
        self._search = QLineEdit()
        self._search.setPlaceholderText("Type a command…")
        self._search.setClearButtonEnabled(True)
        self._search.textChanged.connect(lambda _t: self._refilter())
        self._search.installEventFilter(self)
        lay.addWidget(self._search)
        self._list = QListWidget()
        self._list.itemDoubleClicked.connect(
            lambda item: self.run_index(self._list.row(item))
        )
        lay.addWidget(self._list, 1)
        self._apply_style()

    # --- actions ---

    def set_actions(self, actions: list[CommandAction]) -> None:
        """Replace the whole menu (an empty list is perfectly fine)."""
        self._actions = list(actions or [])
        self._refilter()

    def register(self, action: CommandAction) -> None:
        """Add one more action to the end of the menu."""
        self._actions.append(action)
        self._refilter()

    @property
    def actions(self) -> list[CommandAction]:
        return list(self._actions)

    # --- lifecycle ---

    def popup(self) -> None:
        """Open fresh: clear the query, show all, centered over the window."""
        self._search.clear()
        self._refilter()
        host = self.parentWidget()
        if host is not None:
            geo = host.window().geometry()
            self.adjustSize()
            self.move(
                geo.center().x() - self.width() // 2,
                geo.top() + geo.height() // 5,
            )
        self.show()
        self.raise_()
        self.activateWindow()
        self._search.setFocus()

    # --- running ---

    def run_current(self) -> None:
        """Run whatever the highlight is on (no highlight → nothing)."""
        self.run_index(self._list.currentRow())

    def run_index(self, row: int) -> None:
        """Run the action at list `row`, then close (out of range → no-op)."""
        if not (0 <= row < len(self._rows)):
            return
        action = self._actions[self._rows[row]]
        self.close()
        self.action_run.emit(action.label)
        if action.callback is not None:
            try:
                action.callback()
            except Exception:  # noqa: BLE001 - a sick action never sinks the room
                log.warning("palette action %r failed", action.label, exc_info=True)

    # --- internals ---

    def _refilter(self) -> None:
        """Rebuild the visible rows from the query, best match on top."""
        self._rows = [index for _s, index in rank_actions(self._actions,
                                                           self._search.text())]
        self._list.clear()
        for index in self._rows:
            self._list.addItem(QListWidgetItem(self._actions[index].label))
        if self._rows:
            self._list.setCurrentRow(0)

    def _move(self, step: int) -> None:
        """Walk the highlight up/down, wrapping at the ends."""
        count = self._list.count()
        if not count:
            return
        row = self._list.currentRow() + step
        self._list.setCurrentRow(row % count)

    def eventFilter(self, obj, event) -> bool:  # noqa: N802 - Qt naming
        """Keys typed in the search box steer the palette."""
        if obj is self._search and event.type() == QEvent.Type.KeyPress:
            key = event.key()
            if key in (Qt.Key.Key_Down, Qt.Key.Key_Up):
                self._move(1 if key == Qt.Key.Key_Down else -1)
                return True
            if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                self.run_current()
                return True
            if key == Qt.Key.Key_Escape:
                self.close()
                return True
        return super().eventFilter(obj, event)

    def apply_palette(self, palette: Palette) -> None:
        """Re-tint when the room changes palette."""
        self._palette = palette
        self._apply_style()

    def _apply_style(self) -> None:
        p = self._palette
        # the relief shell: lit rounded glass, light top lip, ground shadow
        face_hi = mix(p.surface, p.text, 0.05)
        face_deep = mix(p.surface, "#000000", 0.16)
        lip_hi = mix(p.hairline, p.text, 0.16)
        lip_lo = mix(p.surface, "#000000", 0.30)
        channel_top = mix(p.bg, "#000000", 0.30)
        self.setStyleSheet(
            f"QDialog{{background: qlineargradient(x1:0, y1:0, x2:0, y2:1,"
            f" stop:0 {face_hi}, stop:0.1 {p.surface}, stop:1 {face_deep});"
            f"border: 1px solid {lip_lo}; border-top-color: {lip_hi};"
            f"border-radius: {config.DEPTH_RADIUS}px;}}"
            f"QLineEdit{{background: qlineargradient(x1:0, y1:0, x2:0, y2:1,"
            f" stop:0 {channel_top}, stop:0.3 {p.surface_alt},"
            f" stop:1 {p.surface_alt}); color: {p.text};"
            f"border: 1px solid {lip_lo}; border-bottom-color: {lip_hi};"
            f"border-radius: 8px;"
            f"padding: 8px; font-size: 15px;"
            f"selection-background-color: {p.selection};}}"
            f"QLineEdit:focus{{border: 1px solid {p.accent};}}"
            f"QListWidget{{background: transparent; color: {p.text};"
            f"border: none; font-size: 14px; outline: none;}}"
            f"QListWidget::item{{padding: 7px 8px; border-radius: 6px;}}"
            f"QListWidget::item:selected{{background: {p.selection};"
            f"color: {p.text};}}"
        )
        blur, dy, alpha = config.DEPTH_SHADOWS["float"]
        add_shadow(self, blur=blur, dy=dy, alpha=alpha)


def palette_over(parent: QWidget, palette: Palette | str | None = None,
                 actions: list[CommandAction] | None = None) -> CommandPalette:
    """Convenience builder: a ready palette dialog owned by `parent`."""
    dlg = CommandPalette(palette, parent=parent)
    if actions:
        dlg.set_actions(actions)
    return dlg
