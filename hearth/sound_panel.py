"""The Sound Forge bench, in the room: sliders the host can actually grab.

A small dialog over the pure engine in ``sound_shape`` — ten band
sliders, the preset drawer, the preamp dial, and the karaoke cut. Every
move rebuilds a ``SoundState`` and emits ``state_changed``; the app
persists it and applies what the backend can honor today (the preamp —
it rides the master volume for real). Nothing here knows about storage
or playback; it is knobs and honest labels, headless-testable.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QSlider,
    QVBoxLayout,
)

from . import sound_shape
from .sound_shape import (
    BAND_LABELS,
    MAX_GAIN_DB,
    MAX_PREAMP_DB,
    MIN_GAIN_DB,
    MIN_PREAMP_DB,
    SoundState,
)


class _BandSlider(QSlider):
    """One EQ band: integer steps over the dB range, 0 dB has a notch."""

    def __init__(self):
        super().__init__(Qt.Orientation.Horizontal)
        lo, hi = int(MIN_GAIN_DB), int(MAX_GAIN_DB)
        self.setRange(lo, hi)
        self.setValue(0)


class SoundForgeDialog(QDialog):
    """Ten bands, one preamp, one karaoke cut — the bench with knobs on."""

    state_changed = pyqtSignal(object)   # SoundState (normalized)

    def __init__(self, parent=None, state: SoundState | None = None):
        super().__init__(parent)
        self.setWindowTitle("Sound Forge")
        self.setModal(False)
        self.resize(520, 380)
        self._loading = False               # programmatic updates stay quiet

        layout = QVBoxLayout(self)
        top = QHBoxLayout()
        top.addWidget(QLabel("Preset:"))
        self._preset = QComboBox()
        self._preset.addItem("Custom", "")
        for name in SoundState.preset_names():
            self._preset.addItem(name, name)
        self._preset.currentIndexChanged.connect(self._on_preset)
        top.addWidget(self._preset, 1)
        layout.addLayout(top)

        bands_row = QHBoxLayout()
        self._band_sliders: list[_BandSlider] = []
        for label in BAND_LABELS:
            column = QVBoxLayout()
            slider = _BandSlider()
            slider.valueChanged.connect(self._on_any_change)
            column.addWidget(slider, 1)
            caption = QLabel(label)
            caption.setAlignment(Qt.AlignmentFlag.AlignHCenter)
            column.addWidget(caption)
            holder = QVBoxLayout()
            holder.addLayout(column)
            holder.setContentsMargins(2, 0, 2, 0)
            bands_row.addLayout(holder)
            self._band_sliders.append(slider)
        layout.addLayout(bands_row, 1)

        preamp_row = QHBoxLayout()
        preamp_row.addWidget(QLabel("Preamp:"))
        self._preamp = QSlider(Qt.Orientation.Horizontal)
        self._preamp.setRange(int(MIN_PREAMP_DB), int(MAX_PREAMP_DB))
        self._preamp.setValue(0)
        self._preamp.valueChanged.connect(self._on_any_change)
        preamp_row.addWidget(self._preamp, 1)
        self._preamp_label = QLabel("0 dB")
        preamp_row.addWidget(self._preamp_label)
        layout.addLayout(preamp_row)

        karaoke_row = QHBoxLayout()
        self._karaoke = QCheckBox("Karaoke (mute the singer, keep the band)")
        self._karaoke.toggled.connect(self._on_any_change)
        karaoke_row.addWidget(self._karaoke)
        self._karaoke_strength = QSlider(Qt.Orientation.Horizontal)
        self._karaoke_strength.setRange(0, 100)
        self._karaoke_strength.setValue(
            int(sound_shape.DEFAULT_KARAOKE_STRENGTH * 100)
        )
        self._karaoke_strength.valueChanged.connect(self._on_any_change)
        karaoke_row.addWidget(self._karaoke_strength, 1)
        layout.addLayout(karaoke_row)

        self._summary = QLabel("")
        layout.addWidget(self._summary)

        self.set_state(state or SoundState())

    # --- populate / read ---

    def set_state(self, state: SoundState) -> None:
        """Load a state into the knobs without re-emitting it."""
        state = state.normalized()
        self._loading = True
        try:
            for slider, gain in zip(self._band_sliders, state.gains):
                slider.setValue(int(round(gain)))
            self._preamp.setValue(int(round(state.preamp_db)))
            self._karaoke.setChecked(state.karaoke)
            self._karaoke_strength.setValue(
                int(round(state.karaoke_strength * 100))
            )
            self._sync_preset_box(state)
        finally:
            self._loading = False
        self._paint_summary()

    def current_state(self) -> SoundState:
        return SoundState(
            gains=tuple(float(s.value()) for s in self._band_sliders),
            preamp_db=float(self._preamp.value()),
            karaoke=self._karaoke.isChecked(),
            karaoke_strength=self._karaoke_strength.value() / 100.0,
        ).normalized()

    # --- reactions ---

    def _on_preset(self, index: int) -> None:
        if self._loading:
            return
        name = self._preset.itemData(index) or ""
        state = self.current_state()
        if state.apply_preset(name):
            self._loading = True
            try:
                for slider, gain in zip(self._band_sliders, state.gains):
                    slider.setValue(int(round(gain)))
            finally:
                self._loading = False
            self._paint_summary()

    def _on_any_change(self, _value: int = 0) -> None:
        if self._loading:
            return
        state = self.current_state()
        self._sync_preset_box(state)
        self._paint_summary()
        self.state_changed.emit(state)

    def _sync_preset_box(self, state: SoundState) -> None:
        """When the curve matches a preset, name it; otherwise Custom."""
        match = ""
        for name, gains in sound_shape.PRESETS.items():
            if all(abs(g - p) < 0.5 for g, p in zip(state.gains, gains)):
                match = name
                break
        index = self._preset.findData(match)
        if index >= 0 and self._preset.currentIndex() != index:
            self._loading = True
            self._preset.setCurrentIndex(index)
            self._loading = False

    def _paint_summary(self) -> None:
        state = self.current_state()
        self._preamp_label.setText(f"{state.preamp_db:+.0f} dB")
        self._summary.setText(sound_shape.sound_summary(state))
        self._summary.setToolTip(
            "Preamp rides the master volume today; the band curve and the "
            "karaoke cut engage fully when the v1.0 shaped pipeline lands."
        )
