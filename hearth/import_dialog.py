"""The Welcome Mat, pasted: rebuild a Spotify playlist on YouTube Music.

A QDialog that accepts whatever the user copied — a Spotify share page's
embed HTML, an Exportify CSV, or a raw Spotify JSON dump — plus an
optional name and a format override (auto-detect by default). The dialog
knows nothing about matching; it just collects the paste. The heavy
lifting lives in ``switchboard.import_spotify`` and runs on a worker
thread (``jobs.ImportJob``), so a slow catalog never freezes the window.

Pure Qt, headless-testable: construct it, set the fields, read them back.
"""

from __future__ import annotations

from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QVBoxLayout,
)

FORMATS = (("auto", "Detect automatically"), ("json", "Spotify JSON"),
           ("csv", "Exportify CSV"), ("embed", "Share page / embed HTML"))


class ImportDialog(QDialog):
    """Paste a Spotify playlist; Hearth does the rest."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("🟢 Import from Spotify")
        self.setModal(True)
        self.resize(560, 420)

        layout = QVBoxLayout(self)
        tip = QLabel(
            "Paste a Spotify playlist below — a share-page link's HTML, an\n"
            "Exportify CSV, or the JSON from Spotify's data export.\n"
            "Hearth matches every song on YouTube Music and rebuilds the list."
        )
        tip.setWordWrap(True)
        layout.addWidget(tip)

        self._text = QPlainTextEdit()
        self._text.setPlaceholderText(
            "Paste here…\n\n"
            "Works with: the playlist page's embed/share HTML, an Exportify\n"
            "CSV (File → Export on exportify.app), or playlist JSON."
        )
        layout.addWidget(self._text, 1)

        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        self._name = QLineEdit()
        self._name.setPlaceholderText("Spotify import (used when the paste has no name)")
        form.addRow("Playlist name:", self._name)
        self._fmt = QComboBox()
        for value, label in FORMATS:
            self._fmt.addItem(label, value)
        form.addRow("Format:", self._fmt)
        layout.addLayout(form)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Import")
        buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(False)
        self._text.textChanged.connect(
            lambda: buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(
                bool(self.paste_text().strip())
            )
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    # --- what the app reads after accept() ---

    def paste_text(self) -> str:
        return self._text.toPlainText()

    def playlist_name(self) -> str:
        return self._name.text().strip()

    def format_choice(self) -> str:
        return self._fmt.currentData() or "auto"

    # --- tests (and future prefill helpers) ---

    def set_paste(self, text: str) -> None:
        self._text.setPlainText(text)

    def set_playlist_name(self, name: str) -> None:
        self._name.setText(name)

    def set_format_choice(self, value: str) -> None:
        index = self._fmt.findData(value)
        if index >= 0:
            self._fmt.setCurrentIndex(index)
