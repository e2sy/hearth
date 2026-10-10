"""The party hat's front door: guest suggestions waiting for the host.

A small non-modal review surface over the remote's ``SuggestionInbox``.
Each guest paste becomes one row — song, artist, who-asked metadata —
and the host accepts (straight into the queue) or skips (out of the
box). The dialog never touches playback itself; it only emits
``accept_requested`` and lets the app decide, the same way every other
Hearth view stays honest about its role.

Pure Qt, headless-testable: feed it a real inbox, click the buttons.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class PartyInboxDialog(QDialog):
    """Guest suggestions waiting for the host's nod."""

    accept_requested = pyqtSignal(object)   # the suggestion dict
    empty = pyqtSignal()                    # nothing left — the app may close us

    def __init__(self, inbox, parent=None):
        super().__init__(parent)
        self._inbox = inbox
        self.setWindowTitle("Party suggestions")
        self.setModal(False)
        self.resize(460, 300)

        layout = QVBoxLayout(self)
        self._head = QLabel("Guest suggestions for tonight's fire")
        self._head.setProperty("hero", True)
        layout.addWidget(self._head)
        self._rows_host = QVBoxLayout()
        self._rows_host.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(self._rows_host)
        layout.addStretch(1)
        self.refresh()

    # --- rendering ---

    def refresh(self) -> None:
        """Rebuild the rows from the inbox's pending snapshot."""
        while self._rows_host.count():
            item = self._rows_host.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        pending = self._inbox.pending()
        for entry in pending:
            self._rows_host.addWidget(self._row(entry))
        self._head.setText(
            f"{len(pending)} guest suggestion(s) waiting" if pending
            else "The inbox is empty — the party made their picks"
        )
        if not pending:
            self.empty.emit()

    def _row(self, entry: dict) -> QWidget:
        row = QWidget()
        inner = QHBoxLayout(row)
        inner.setContentsMargins(0, 4, 0, 4)
        label = QLabel(
            f"🎵 {entry.get('title') or entry.get('video_id')}"
            + (f" — {entry['artist']}" if entry.get("artist") else "")
        )
        label.setProperty("rowTitle", True)
        inner.addWidget(label, 1)
        accept = QPushButton("➕ Queue")
        accept.setToolTip("Add this guest pick to the queue now")
        accept.clicked.connect(lambda _=False: self._accept(entry, row))
        inner.addWidget(accept)
        skip = QPushButton("Skip")
        skip.clicked.connect(lambda _=False: self._skip(entry, row))
        inner.addWidget(skip)
        return row

    # --- actions (each row decision immediately leaves the inbox) ---

    def _accept(self, entry: dict, row: QWidget) -> None:
        self.accept_requested.emit(entry)
        self._consume(entry, row)

    def _skip(self, entry: dict, row: QWidget) -> None:
        self._consume(entry, row)

    def _consume(self, entry: dict, row: QWidget) -> None:
        """Remove one suggestion from the inbox (oldest matching duplicate)."""
        video_id = str(entry.get("video_id") or "")
        remaining = [
            item for item in self._inbox.pending()
            if item.get("video_id") != video_id
        ]
        self._inbox.drain()                  # empty the box…
        for item in reversed(remaining):     # …then put back what stays
            self._inbox.push(item)
        row.deleteLater()
        self.refresh()

    # --- politeness ---

    def keyPressEvent(self, event):  # noqa: N802 - Qt naming
        if event.key() == Qt.Key.Key_Escape:
            self.close()
            return
        super().keyPressEvent(event)
