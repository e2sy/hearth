"""The big stage: sidebar, home shelves, search, library, player bar.

Layout conventions follow the familiar three-pane desktop music player:
navigation on the left, content cards up top, transport controls pinned
to the bottom. Everything here is original Hearth code painted from the
active Palette — no assets, no third-party marks.
"""

from __future__ import annotations

import json
import math
import random
import time
from dataclasses import replace
from datetime import date, datetime
from pathlib import Path

from PyQt6.QtCore import QRectF, QSize, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QImage,
    QKeySequence,
    QLinearGradient,
    QPainter,
    QPixmap,
    QShortcut,
)
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QColorDialog,
    QComboBox,
    QDialog,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSlider,
    QStackedLayout,
    QStackedWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from . import config, share, world
from .config import Palette, get_palette
from .cover import CoverTile, reflected_pixmap
from .effects import (
    add_glow,
    add_shadow,
    fade_in,
    set_glow_color,
)
from .lyrics import LrcLine, SyncedLyrics
from .models import Album, Artist, Track
from .rewind import build_rewind_story
from .storage import HearthStore
from .theme import (
    STYLES,
    build_stylesheet,
    export_palette,
    lyrics_font,
    register_custom_palette,
)
from .utils import clock


# ----------------------------------------------------------------- rows

class TrackRow(QWidget):
    """One search/playlist/queue row: index, mini cover, title·artist, time."""

    def __init__(self, palette: Palette, track: Track, index: int = 0,
                 removable: bool = False):
        super().__init__()
        self.track = track
        self.setMinimumHeight(config.ROW_HEIGHT)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 4, 10, 4)
        lay.setSpacing(10)

        self._pos = QLabel(f"{index}" if index else "▶")
        self._pos.setProperty("dim", True)
        self._pos.setFixedWidth(26)
        self._pos.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._cover = CoverTile(palette, 38)
        if track.thumbnail:
            self._cover.set_track_cover(track.thumbnail)

        text = QVBoxLayout()
        text.setSpacing(1)
        self._title = QLabel(track.title)
        self._title.setProperty("header", True)
        self._artist = QLabel(track.artist)
        self._artist.setProperty("dim", True)
        text.addWidget(self._title)
        text.addWidget(self._artist)

        self._time = QLabel(track.duration or clock(track.duration_sec * 1000))
        self._time.setProperty("dim", True)
        self._time.setFixedWidth(52)
        self._time.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        lay.addWidget(self._pos)
        lay.addWidget(self._cover)
        lay.addLayout(text, 1)
        lay.addWidget(self._time)

    def set_index(self, index: int) -> None:
        self._pos.setText(str(index))


class Shelf(QWidget):
    """A titled horizontal strip of track cards ('Made for you' vibes)."""

    card_picked = pyqtSignal(object, list)      # Track, shelf context

    def header_button(self, text: str, tooltip: str = "") -> QPushButton:
        """A small chip button beside the shelf title (one-shot rituals).

        The title row is rebuilt into a header strip so a caller can drop
        an action (the ✨ Glow Mix button) exactly where its shelf lives.
        The button carries no behavior — connect its `clicked` yourself.
        """
        btn = QPushButton(text)
        btn.setProperty("chip", True)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setToolTip(tooltip)
        lay = self.layout()
        lay.removeWidget(self._title)
        row = QHBoxLayout()
        row.addWidget(self._title)
        row.addStretch(1)
        row.addWidget(btn)
        lay.insertLayout(0, row)
        return btn

    def __init__(self, palette: Palette, title: str):
        super().__init__()
        self._palette = palette
        self._tracks: list[Track] = []
        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 6, 4, 10)
        lay.setSpacing(8)
        self._title = QLabel(title)
        self._title.setProperty("shelf", True)
        self._strip_area = QScrollArea()
        self._strip_area.setWidgetResizable(True)
        self._strip_area.setFixedHeight(config.COVER_TILE + 96)
        self._strip_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._strip_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._strip = QWidget()
        self._strip_lay = QHBoxLayout(self._strip)
        self._strip_lay.setContentsMargins(2, 2, 2, 2)
        self._strip_lay.setSpacing(10)
        self._strip_lay.setAlignment(Qt.AlignmentFlag.AlignLeft)
        self._strip_area.setWidget(self._strip)
        self._empty = QLabel("Nothing here yet — play something cozy.")
        self._empty.setProperty("dim", True)
        lay.addWidget(self._title)
        lay.addWidget(self._strip_area)
        lay.addWidget(self._empty)
        self.set_tracks([])

    def set_tracks(self, tracks: list[Track]) -> None:
        self._tracks = list(tracks)
        while self._strip_lay.count():
            item = self._strip_lay.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        for index, track in enumerate(self._tracks):
            card = self._make_card(track, index)
            self._strip_lay.addWidget(card)
        has = bool(self._tracks)
        self._strip_area.setVisible(has)
        self._empty.setVisible(not has)

    def _make_card(self, track: Track, index: int) -> QPushButton:
        card = QPushButton()
        card.setProperty("card", True)
        card.setCursor(Qt.CursorShape.PointingHandCursor)
        card.setFixedSize(config.COVER_TILE, config.COVER_TILE + 74)
        inner = QVBoxLayout(card)
        inner.setContentsMargins(12, 12, 12, 12)
        inner.setSpacing(6)
        tile = CoverTile(self._palette, config.COVER_TILE - 24)
        tile.set_track_cover(track.thumbnail)
        title = QLabel(track.title)
        title.setWordWrap(True)
        title.setMaximumHeight(34)
        artist = QLabel(track.artist)
        artist.setProperty("dim", True)
        inner.addWidget(tile)
        inner.addWidget(title, 1)
        inner.addWidget(artist)
        card.clicked.connect(lambda _=False, t=track, i=index: self.card_picked.emit(t, list(self._tracks)))
        return card


# ----------------------------------------------------------------- views

class HomeView(QWidget):
    """Scrolling shelves: quick picks, on repeat, pinned favorites, recent."""

    glow_mix_requested = pyqtSignal()   # ✨ the one-tap ritual button

    def __init__(self, palette: Palette):
        super().__init__()
        self._palette = palette
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        area = QScrollArea()
        area.setWidgetResizable(True)
        body = QWidget()
        self._body_lay = QVBoxLayout(body)
        self._body_lay.setContentsMargins(24, 18, 24, 18)
        self._body_lay.setSpacing(14)
        area.setWidget(body)
        outer.addWidget(area)
        self._shelves: dict[str, Shelf] = {}
        for name in (
            "Quick picks", "Top tracks", "On Repeat", "Pinned favorites",
            "Recently played", "Most played", "Recently loved", "Rare gems",
            "🔌 Plugins",
        ):
            self._shelves[name] = Shelf(palette, name)
            self._body_lay.addWidget(self._shelves[name])
            self._shelves[name].setVisible(False)
        self._hero = QLabel("Good fire to sit by. What are we playing?")
        self._hero.setProperty("hero", True)
        self._body_lay.insertWidget(0, self._hero)
        # the one-tap ritual lives where the rotation it grows from lives
        self._glow_button = self._shelves["On Repeat"].header_button(
            "✨ Glow Mix", "Your rotation blended with kindred artists' fire")
        self._glow_button.clicked.connect(
            lambda _=False: self.glow_mix_requested.emit())

    def shelf(self, name: str) -> Shelf:
        return self._shelves[name]

    def set_shelf(self, name: str, tracks: list[Track]) -> None:
        self._shelves[name].set_tracks(list(tracks))
        self._shelves[name].setVisible(bool(tracks))

    def apply_palette(self, palette: Palette) -> None:
        self._palette = palette


class TrackListView(QWidget):
    """A searchable list of rows with double-click-to-play and a context menu."""

    track_activated = pyqtSignal(object, list)   # Track, full list context
    menu_requested = pyqtSignal(object, object)  # Track, QMenu (caller fills)

    def __init__(self, palette: Palette):
        super().__init__()
        self._palette = palette
        self._tracks: list[Track] = []
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 18, 24, 12)
        lay.setSpacing(10)
        self._head = QLabel("")
        self._head.setProperty("hero", True)
        self._count = QLabel("")
        self._count.setProperty("dim", True)
        self._list = QListWidget()
        self._list.setProperty("rows", True)
        self._list.setSpacing(2)
        self._list.itemDoubleClicked.connect(self._on_double)
        self._list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._list.customContextMenuRequested.connect(self._on_menu)
        lay.addWidget(self._head)
        lay.addWidget(self._count)
        lay.addWidget(self._list, 1)

    def set_header(self, title: str) -> None:
        self._head.setText(title)

    def set_visible_rows(self, rows: int) -> None:
        """Cap the list to `rows` visible rows (embeds inside scroll pages)."""
        rows = max(1, min(int(rows), 12))
        self._list.setFixedHeight(rows * (config.ROW_HEIGHT + 8) + 14)

    def set_tracks(self, tracks: list[Track]) -> None:
        self._tracks = list(tracks)
        self._list.clear()
        for index, track in enumerate(self._tracks, start=1):
            item = QListWidgetItem()
            item.setSizeHint(TrackRow(self._palette, track).sizeHint())
            row = TrackRow(self._palette, track, index)
            item.setData(Qt.ItemDataRole.UserRole, track)
            self._list.addItem(item)
            self._list.setItemWidget(item, row)
        shown = len(self._tracks)
        self._count.setText(
            f"{shown} tracks" if shown != 1 else "1 track"
        )

    @property
    def current_tracks(self) -> list[Track]:
        return list(self._tracks)

    def _on_double(self, item: QListWidgetItem) -> None:
        track = item.data(Qt.ItemDataRole.UserRole)
        if track is not None:
            self.track_activated.emit(track, list(self._tracks))

    def _on_menu(self, pos) -> None:
        item = self._list.itemAt(pos)
        if item is None:
            return
        track = item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(track, Track):
            return
        menu = QMenu(self)
        self.menu_requested.emit(track, menu)
        menu.exec(self._list.viewport().mapToGlobal(pos))


class SearchView(TrackListView):
    """The search page: query box, scope chips, and the result rows."""

    search_submitted = pyqtSignal(str)
    search_scoped = pyqtSignal(str, str)      # query, scope ("songs"/"videos"/"albums")
    album_opened = pyqtSignal(object)         # Album (double-click an album result)

    SCOPES = (("songs", "♪ Songs"), ("videos", "▶ Videos"), ("albums", "💿 Albums"))

    def __init__(self, palette: Palette):
        super().__init__(palette)
        self._head.setText("Search")
        self.set_tracks([])
        self._scope = "songs"
        self._box = QLineEdit()
        self._box.setPlaceholderText("What do you want to play?  (or paste a link)")
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(config.SEARCH_DEBOUNCE_MS)
        self._debounce.timeout.connect(self._emit_search)
        self._box.textEdited.connect(lambda _: self._debounce.start())
        self._box.returnPressed.connect(self._emit_search)
        self.layout().insertWidget(0, self._box)

        chips = QHBoxLayout()
        chips.setSpacing(6)
        self._chips: dict[str, QPushButton] = {}
        for scope, label in self.SCOPES:
            chip = QPushButton(label)
            chip.setProperty("chip", True)
            chip.setCheckable(True)
            chip.setCursor(Qt.CursorShape.PointingHandCursor)
            chip.setChecked(scope == self._scope)
            chip.clicked.connect(lambda _=False, s=scope: self.set_scope(s))
            self._chips[scope] = chip
            chips.addWidget(chip)
        chips.addStretch(1)
        self.layout().insertLayout(1, chips)
        self._count.hide()

    # --- scope ---

    def set_scope(self, scope: str) -> None:
        if scope not in self._chips:
            return
        changed = scope != self._scope
        self._scope = scope
        for name, chip in self._chips.items():
            chip.setChecked(name == scope)
        if changed and self.query():
            self.search_scoped.emit(self.query(), scope)

    def scope(self) -> str:
        return self._scope

    # --- results ---

    def set_albums(self, albums: list[Album]) -> None:
        """Show album cards instead of track rows (albums scope)."""
        self._tracks = []
        self._list.clear()
        for album in albums:
            label = album.title if not album.year else f"{album.title}  ·  {album.year}"
            item = QListWidgetItem(f"💿  {label}\n      {album.artist or 'Unknown artist'}")
            item.setSizeHint(QSize(0, config.ROW_HEIGHT + 24))
            item.setData(Qt.ItemDataRole.UserRole, album)
            self._list.addItem(item)

    def _emit_search(self) -> None:
        query = self._box.text().strip()
        if not query:
            return
        if self._scope == "songs":
            self.search_submitted.emit(query)
        else:
            self.search_scoped.emit(query, self._scope)

    def set_query(self, text: str) -> None:
        self._box.setText(text)

    def query(self) -> str:
        return self._box.text().strip()

    def _on_double(self, item: QListWidgetItem) -> None:
        data = item.data(Qt.ItemDataRole.UserRole)
        if isinstance(data, Album):
            self.album_opened.emit(data)
            return
        if data is not None:
            self.track_activated.emit(data, list(self._tracks))


class LibraryView(QWidget):
    """Your stuff: pinned favorites, recent history, and playlist cards."""

    playlist_opened = pyqtSignal(int)            # playlist id
    track_activated = pyqtSignal(object, list)
    menu_requested = pyqtSignal(object, object)
    create_playlist_requested = pyqtSignal()
    import_requested = pyqtSignal()              # 📥 import playlists (JSON / M3U)

    def __init__(self, palette: Palette):
        super().__init__()
        self._palette = palette
        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 18, 24, 12)
        outer.setSpacing(14)

        head = QHBoxLayout()
        hero = QLabel("Your Library")
        hero.setProperty("hero", True)
        new_btn = QPushButton("＋ New playlist")
        new_btn.setProperty("accent", True)
        new_btn.clicked.connect(self.create_playlist_requested.emit)
        import_btn = QPushButton("📥 Import…")
        import_btn.setProperty("chip", True)
        import_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        import_btn.setToolTip("Import playlists from JSON or M3U files")
        import_btn.clicked.connect(lambda _=False: self.import_requested.emit())
        self._import_btn = import_btn
        head.addWidget(hero)
        head.addStretch(1)
        head.addWidget(import_btn)
        head.addWidget(new_btn)
        outer.addLayout(head)

        self._fav_shelf = Shelf(palette, "Pinned favorites")
        self._recent = TrackListView(palette)
        self._recent.set_header("Recently played")
        self._recent.setMinimumHeight(240)
        self._recent.track_activated.connect(self.track_activated)
        self._recent.menu_requested.connect(self.menu_requested)
        outer.addWidget(self._fav_shelf)
        outer.addWidget(QLabel("Recently played"))
        outer.addWidget(self._recent, 1)

    def set_favorites(self, tracks: list[Track]) -> None:
        self._fav_shelf.set_tracks(list(tracks))

    def set_recent(self, tracks: list[Track]) -> None:
        self._recent.set_tracks(list(tracks)[:8])


class LocalView(TrackListView):
    """Your own files: the scanned local library plus its folder controls.

    Deliberately thin — the buttons only raise signals, the app does the
    scanning (on a worker pool) and pushes the tracks back in.
    """

    add_folder_requested = pyqtSignal()
    rescan_requested = pyqtSignal()

    def __init__(self, palette: Palette):
        super().__init__(palette)
        self._head.setText("📁 Local songs")
        tools = QHBoxLayout()
        tools.setSpacing(6)
        add_btn = QPushButton("📂 Add folder…")
        add_btn.setProperty("chip", True)
        add_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        add_btn.clicked.connect(self.add_folder_requested.emit)
        rescan_btn = QPushButton("🔄 Rescan")
        rescan_btn.setProperty("chip", True)
        rescan_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        rescan_btn.clicked.connect(self.rescan_requested.emit)
        tools.addWidget(add_btn)
        tools.addWidget(rescan_btn)
        tools.addStretch(1)
        lay = self.layout()
        lay.insertLayout(1, tools)     # below the header, above the count
        self._empty = QLabel("no local songs yet — point hearth at a folder")
        self._empty.setProperty("dim", True)
        self._empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.insertWidget(lay.indexOf(self._list), self._empty)
        self._empty.hide()

    def set_tracks(self, tracks: list[Track]) -> None:
        super().set_tracks(tracks)
        has = bool(tracks)
        self._empty.setVisible(not has)
        self._list.setVisible(has)


class DiscoverView(QWidget):
    """The whole world's music: charts, new releases, trending, moods & genres.

    The view stays deliberately dumb — every click just asks the app for
    data via a signal, and the app pushes content back in through
    set_sections / set_collections / set_track_list.
    """

    category_selected = pyqtSignal(str)        # mood/genre params
    collection_opened = pyqtSignal(object)     # Collection | Album card clicked
    charts_requested = pyqtSignal()
    explore_requested = pyqtSignal(str)        # "new_releases" | "trending" | "new_videos"
    track_activated = pyqtSignal(object, list)
    menu_requested = pyqtSignal(object, object)

    MAX_GRID_CARDS = 60

    def __init__(self, palette: Palette):
        super().__init__()
        self._palette = palette
        self._sections: list[tuple[str, list[dict]]] = []
        self._mode = ""          # which chip is lit ("section" or an explore mode)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 18, 24, 12)
        outer.setSpacing(10)

        head = QHBoxLayout()
        hero = QLabel("🌍 Discover")
        hero.setProperty("hero", True)
        self._status = QLabel("every mood, genre and corner of the world's music")
        self._status.setProperty("dim", True)
        head.addWidget(hero)
        head.addStretch(1)
        head.addWidget(self._status)
        outer.addLayout(head)

        chips = QHBoxLayout()
        chips.setSpacing(6)
        self._chips: dict[str, QPushButton] = {}
        for key, label in (
            ("charts", "🔥 Charts"),
            ("new_releases", "✨ New releases"),
            ("trending", "🎶 Trending"),
            ("new_videos", "🎬 New videos"),
        ):
            chip = QPushButton(label)
            chip.setProperty("chip", True)
            chip.setCheckable(True)
            chip.setCursor(Qt.CursorShape.PointingHandCursor)
            chip.clicked.connect(lambda _=False, k=key: self._chip_clicked(k))
            self._chips[key] = chip
            chips.addWidget(chip)
        self._chip_sep = QLabel("·")
        self._chip_sep.setProperty("dim", True)
        chips.addWidget(self._chip_sep)
        chips.addStretch(1)
        self._chips_row = chips          # direct handle — section chips insert here
        outer.addLayout(chips)

        self._body = QStackedWidget()
        outer.addWidget(self._body, 1)

        # page 0 — grid: subcategory list + collection cards
        grid_page = QWidget()
        grid_lay = QHBoxLayout(grid_page)
        grid_lay.setContentsMargins(0, 0, 0, 0)
        grid_lay.setSpacing(12)
        self._cat_list = QListWidget()
        self._cat_list.setProperty("sidebar", True)
        self._cat_list.setFixedWidth(200)
        self._cat_list.itemClicked.connect(self._category_clicked)
        grid_lay.addWidget(self._cat_list)
        self._grid_area = QScrollArea()
        self._grid_area.setWidgetResizable(True)
        self._grid_area.setFrameShape(QScrollArea.Shape.NoFrame)
        self._grid_host = QWidget()
        self._grid_lay = QGridLayout(self._grid_host)
        self._grid_lay.setContentsMargins(0, 0, 8, 0)
        self._grid_lay.setSpacing(10)
        self._grid_lay.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self._grid_area.setWidget(self._grid_host)
        grid_lay.addWidget(self._grid_area, 1)
        self._body.addWidget(grid_page)

        # page 1 — straight track list (trending / new videos)
        self._track_page = TrackListView(palette)
        self._track_page.track_activated.connect(self.track_activated)
        self._track_page.menu_requested.connect(self.menu_requested)
        self._body.addWidget(self._track_page)

    # --- chips / navigation ---

    def _chip_clicked(self, key: str) -> None:
        if key == "charts":
            self._light_chip("charts")
            self.charts_requested.emit()
        elif key in ("new_releases", "trending", "new_videos"):
            self._light_chip(key)
            self.explore_requested.emit(key)

    def _light_chip(self, key: str) -> None:
        self._mode = key
        for name, chip in self._chips.items():
            chip.setChecked(name == key)

    def set_sections(self, sections: list[tuple[str, list[dict]]]) -> None:
        """(Re)build the mood/genre section chips and open the first one."""
        self._sections = list(sections)
        # drop stale section chips (everything after the built-in four)
        for name in [k for k in self._chips if k not in
                     ("charts", "new_releases", "trending", "new_videos")]:
            chip = self._chips.pop(name)
            chip.deleteLater()
        for index, (title, _subs) in enumerate(self._sections):
            chip = QPushButton(title)
            chip.setProperty("chip", True)
            chip.setCheckable(True)
            chip.setCursor(Qt.CursorShape.PointingHandCursor)
            key = f"section-{index}"
            chip.clicked.connect(
                lambda _=False, i=index, k=key: self._section_chip(i, k)
            )
            self._chips[key] = chip
            self._chips_row.insertWidget(
                self._chips_row.indexOf(self._chip_sep) + 1 + index, chip
            )
        if self._sections:
            self._section_chip(0, "section-0")

    def _section_chip(self, index: int, key: str) -> None:
        self._light_chip(key)
        self.show_section(index)

    def show_section(self, index: int) -> None:
        """Fill the subcategory list for a section and select the first one."""
        if not (0 <= index < len(self._sections)):
            return
        _title, submenus = self._sections[index]
        self._cat_list.clear()
        for sub in submenus:
            item = QListWidgetItem(sub.get("title", "?"))
            item.setData(Qt.ItemDataRole.UserRole, sub.get("params", ""))
            self._cat_list.addItem(item)
        self._mode = "section"
        self._body.setCurrentIndex(0)
        self._cat_list.setVisible(bool(submenus))
        if self._cat_list.count():
            self._cat_list.setCurrentRow(0)
            self.category_selected.emit(submenus[0].get("params", ""))

    def _category_clicked(self, item: QListWidgetItem) -> None:
        params = item.data(Qt.ItemDataRole.UserRole)
        if params:
            self.category_selected.emit(str(params))

    # --- content in ---

    def set_collections(self, items: list) -> None:
        """Grid of Collection / Album cards."""
        self._cat_list.setVisible(self._mode == "section")
        self._body.setCurrentIndex(0)
        while self._grid_lay.count():
            item = self._grid_lay.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        for index, thing in enumerate(items[: self.MAX_GRID_CARDS]):
            self._grid_lay.addWidget(
                self._make_card(thing), index // 4, index % 4
            )
        overflow = len(items) - self.MAX_GRID_CARDS
        if overflow > 0:
            note = QLabel(f"… and {overflow} more — pick a subcategory to narrow it down")
            note.setProperty("dim", True)
            rows = (self.MAX_GRID_CARDS + 3) // 4
            self._grid_lay.addWidget(note, rows, 0, 1, 4)

    def _make_card(self, thing) -> QPushButton:
        card = QPushButton()
        card.setProperty("card", True)
        card.setCursor(Qt.CursorShape.PointingHandCursor)
        card.setFixedSize(config.DISCOVER_CARD_SIZE, config.DISCOVER_CARD_SIZE + 64)
        inner = QVBoxLayout(card)
        inner.setContentsMargins(10, 10, 10, 10)
        inner.setSpacing(4)
        tile = CoverTile(self._palette, config.DISCOVER_CARD_SIZE - 20)
        thumbnail = getattr(thing, "thumbnail", "")
        if thumbnail:
            tile.set_track_cover(thumbnail)
        title = QLabel(thing.title)
        title.setWordWrap(True)
        title.setMaximumHeight(30)
        subtitle = getattr(thing, "subtitle", "") or getattr(thing, "artist", "")
        sub = QLabel(str(subtitle or ""))
        sub.setProperty("dim", True)
        inner.addWidget(tile)
        inner.addWidget(title, 1)
        inner.addWidget(sub)
        card.clicked.connect(lambda _=False, t=thing: self.collection_opened.emit(t))
        return card

    def set_track_list(self, title: str, tracks: list[Track]) -> None:
        """Straight playable list (trending / new videos)."""
        self._mode = ""
        self._body.setCurrentIndex(1)
        self._track_page.set_header(title)
        self._track_page.set_tracks(list(tracks))

    def set_status(self, text: str) -> None:
        self._status.setText(text)


class RemotePlaylistView(TrackListView):
    """A curated Discover playlist opened as a page: play all / shuffle / queue all."""

    play_all_requested = pyqtSignal(list, int)
    shuffle_requested_sig = pyqtSignal(list)
    enqueue_all_requested = pyqtSignal(list)

    def __init__(self, palette: Palette):
        super().__init__(palette)
        actions = QHBoxLayout()
        play = QPushButton("▶ Play all")
        play.setProperty("accent", True)
        play.clicked.connect(lambda: self.play_all_requested.emit(list(self._tracks), 0))
        shuffle = QPushButton("🔀 Shuffle")
        shuffle.clicked.connect(lambda: self.shuffle_requested_sig.emit(list(self._tracks)))
        enqueue = QPushButton("➕ Queue all")
        enqueue.setToolTip("Append every track to the up-next queue")
        enqueue.clicked.connect(lambda: self.enqueue_all_requested.emit(list(self._tracks)))
        for b in (play, shuffle, enqueue):
            actions.addWidget(b)
        actions.addStretch(1)
        self.layout().insertLayout(2, actions)


class WorldView(QWidget):
    """The World Explorer: a curated dial of every kind of music on Earth.

    Genre stations across nine regions — tap one and the app tunes a
    station (search-everywhere backed, so the dial never comes back
    static). A filter narrows the dial; the dice tunes a surprise.
    All data is local (hearth.world), so the page paints instantly,
    network or no network.
    """

    station_requested = pyqtSignal(object)     # world.Genre

    def __init__(self, palette: Palette):
        super().__init__()
        self._palette = palette

        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 18, 24, 12)
        outer.setSpacing(10)

        head = QHBoxLayout()
        hero = QLabel("🗺️ World Explorer")
        hero.setProperty("hero", True)
        self._status = QLabel(
            f"{len(world.genres())} stations — every continent, every era"
        )
        self._status.setProperty("dim", True)
        head.addWidget(hero)
        head.addStretch(1)
        head.addWidget(self._status)
        surprise = QPushButton("🎲 Surprise me")
        surprise.setToolTip("Tune a random genre from anywhere on Earth")
        surprise.clicked.connect(self._surprise)
        head.addWidget(surprise)
        outer.addLayout(head)

        self._filter = QLineEdit()
        self._filter.setPlaceholderText(
            "Filter the dial — try 'Africa', 'metal', 'bhangra'…"
        )
        self._filter.setClearButtonEnabled(True)
        self._filter.textChanged.connect(self._apply_filter)
        outer.addWidget(self._filter)

        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setFrameShape(QScrollArea.Shape.NoFrame)
        host = QWidget()
        host_lay = QVBoxLayout(host)
        host_lay.setContentsMargins(0, 4, 8, 12)
        host_lay.setSpacing(12)
        area.setWidget(host)
        outer.addWidget(area, 1)

        # (region caption, [chip, ...]) — kept for the filter to sweep
        self._sections: list[tuple[QLabel, list[QPushButton]]] = []
        for region, items in world.genres_by_region():
            cap = QLabel(region.upper())
            cap.setProperty("dim", True)
            host_lay.addWidget(cap)
            grid_host = QWidget()
            grid = QGridLayout(grid_host)
            grid.setContentsMargins(0, 0, 0, 0)
            grid.setSpacing(6)
            grid.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
            host_lay.addWidget(grid_host)
            chips: list[QPushButton] = []
            for index, g in enumerate(items):
                chip = QPushButton(f"{g.emoji} {g.label}")
                chip.setProperty("chip", True)
                chip.setCursor(Qt.CursorShape.PointingHandCursor)
                chip.setToolTip(f"{g.blurb}\n(region: {g.region})")
                chip.setProperty("genre", g)
                chip.clicked.connect(
                    lambda _=False, gg=g: self.station_requested.emit(gg)
                )
                grid.addWidget(chip, index // 4, index % 4)
                chips.append(chip)
            self._sections.append((cap, chips))

    # --- filter / dice ---

    def _apply_filter(self, text: str) -> None:
        needle = text.strip()
        visible = 0
        for cap, chips in self._sections:
            any_visible = False
            for chip in chips:
                g = chip.property("genre")
                show = (not needle) or world.match(g, needle)
                chip.setVisible(show)
                any_visible = any_visible or show
                visible += 1 if show else 0
            cap.setVisible(any_visible)
        total = len(world.genres())
        if not needle:
            self._status.setText(f"{total} stations — every continent, every era")
        else:
            self._status.setText(
                f"{visible} of {total} stations match “{needle}”"
            )

    def _surprise(self) -> None:
        self.station_requested.emit(world.random_genre())

    def set_status(self, text: str) -> None:
        self._status.setText(text)


class PlaylistView(TrackListView):
    """One playlist: header actions + its rows."""

    play_all_requested = pyqtSignal(list, int)
    shuffle_requested_sig = pyqtSignal(list)
    rename_requested = pyqtSignal(int)
    delete_requested = pyqtSignal(int)

    def __init__(self, palette: Palette, playlist_id: int, name: str):
        super().__init__(palette)
        self.playlist_id = playlist_id
        self._playlist_name = name
        self.set_header(f"📁 {name}")

        actions = QHBoxLayout()
        play = QPushButton("▶ Play all")
        play.setProperty("accent", True)
        play.clicked.connect(lambda: self.play_all_requested.emit(list(self._tracks), 0))
        shuffle = QPushButton("🔀 Shuffle")
        shuffle.clicked.connect(lambda: self.shuffle_requested_sig.emit(list(self._tracks)))
        rename = QPushButton("Rename")
        rename.clicked.connect(lambda: self.rename_requested.emit(self.playlist_id))
        delete = QPushButton("Delete")
        delete.clicked.connect(lambda: self.delete_requested.emit(self.playlist_id))
        for b in (play, shuffle, rename, delete):
            actions.addWidget(b)
        actions.addStretch(1)
        self.layout().insertLayout(2, actions)


class AlbumView(TrackListView):
    """One album's track list with Play all / Shuffle actions."""

    play_all_requested = pyqtSignal(list, int)
    shuffle_requested_sig = pyqtSignal(list)

    def __init__(self, palette: Palette):
        super().__init__(palette)
        actions = QHBoxLayout()
        play = QPushButton("▶ Play all")
        play.setProperty("accent", True)
        play.clicked.connect(lambda: self.play_all_requested.emit(list(self._tracks), 0))
        shuffle = QPushButton("🔀 Shuffle")
        shuffle.clicked.connect(lambda: self.shuffle_requested_sig.emit(list(self._tracks)))
        for b in (play, shuffle):
            actions.addWidget(b)
        actions.addStretch(1)
        self.layout().insertLayout(2, actions)


class ArtistView(QWidget):
    """One artist's stage: face, story, top tracks, releases, kindred acts."""

    play_all_requested = pyqtSignal(list, int)
    shuffle_requested_sig = pyqtSignal(list)
    track_activated = pyqtSignal(object, list)     # Track, context — top tracks
    album_opened = pyqtSignal(object)      # Album — drill into a release
    artist_opened = pyqtSignal(object)     # Artist — a related act's page
    menu_requested = pyqtSignal(object, object)   # Track, QMenu (top tracks)

    def __init__(self, palette: Palette):
        super().__init__()
        self._palette = palette
        self._artist: Artist | None = None

        area = QScrollArea()
        area.setWidgetResizable(True)
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(24, 18, 24, 12)
        lay.setSpacing(10)

        # --- face + identity ---
        head = QHBoxLayout()
        head.setSpacing(16)
        self._avatar = CoverTile(palette, config.ARTIST_AVATAR)
        ident = QVBoxLayout()
        ident.setSpacing(4)
        self._name = QLabel("Artist")
        self._name.setProperty("hero", True)
        self._name.setWordWrap(True)
        self._meta = QLabel("")
        self._meta.setProperty("dim", True)
        self._meta.setWordWrap(True)
        ident.addWidget(self._name)
        ident.addWidget(self._meta)
        ident.addStretch(1)
        head.addWidget(self._avatar)
        head.addLayout(ident, 1)
        lay.addLayout(head)

        # --- actions ---
        actions = QHBoxLayout()
        play = QPushButton("▶ Play top tracks")
        play.setProperty("accent", True)
        play.clicked.connect(
            lambda: self.play_all_requested.emit(list(self._top_tracks()), 0)
        )
        shuffle = QPushButton("🔀 Shuffle")
        shuffle.clicked.connect(
            lambda: self.shuffle_requested_sig.emit(list(self._top_tracks()))
        )
        for b in (play, shuffle):
            actions.addWidget(b)
        actions.addStretch(1)
        lay.addLayout(actions)

        # --- top tracks (embedded list, capped height) ---
        self._top = TrackListView(palette)
        self._top.set_header("Top tracks")
        self._top.track_activated.connect(self.track_activated.emit)
        self._top.menu_requested.connect(self.menu_requested.emit)
        lay.addWidget(self._top)

        # --- albums & singles ---
        self._albums_cap = QLabel("Albums")
        self._albums_cap.setProperty("shelf", True)
        self._albums_grid = QGridLayout()
        self._albums_grid.setSpacing(10)
        lay.addWidget(self._albums_cap)
        lay.addLayout(self._albums_grid)
        self._singles_cap = QLabel("Singles")
        self._singles_cap.setProperty("shelf", True)
        self._singles_grid = QGridLayout()
        self._singles_grid.setSpacing(10)
        lay.addWidget(self._singles_cap)
        lay.addLayout(self._singles_grid)

        # --- related artists ---
        self._related_cap = QLabel("Fans also like")
        self._related_cap.setProperty("shelf", True)
        self._related_row = QHBoxLayout()
        self._related_row.setSpacing(6)
        lay.addWidget(self._related_cap)
        lay.addLayout(self._related_row)
        lay.addStretch(1)

        area.setWidget(page)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(area)

        self._empty_sections()

    def _empty_sections(self) -> None:
        self._albums_cap.setVisible(False)
        self._albums_grid.setEnabled(False)
        self._singles_cap.setVisible(False)
        self._related_cap.setVisible(False)

    def _top_tracks(self) -> list[Track]:
        return self._top.current_tracks if hasattr(self, "_top") else []

    # --- content in ---

    def set_artist(self, artist: Artist) -> None:
        self._artist = artist
        if artist.thumbnail:
            self._avatar.set_track_cover(artist.thumbnail)
        else:
            self._avatar.set_mark()
        self._name.setText(artist.name)
        self._meta.setText(artist.meta_line)
        self._top.set_tracks(list(artist.top_tracks))
        self._top.set_visible_rows(
            len(artist.top_tracks) or 1
        )
        self._fill_grid(self._albums_grid, artist.albums, self._albums_cap)
        self._fill_grid(self._singles_grid, artist.singles, self._singles_cap)
        self._fill_related(artist.related)

    def _fill_grid(self, grid: QGridLayout, albums: list[Album],
                   caption: QLabel) -> None:
        """One grid of release cards; the section hides itself when empty."""
        while grid.count():
            item = grid.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        for index, album in enumerate(albums):
            card = self._release_card(album)
            grid.addWidget(card, index // 4, index % 4)
        caption.setVisible(bool(albums))
        grid.setEnabled(bool(albums))

    def _release_card(self, album: Album) -> QPushButton:
        card = QPushButton()
        card.setProperty("card", True)
        card.setCursor(Qt.CursorShape.PointingHandCursor)
        card.setFixedSize(config.ARTIST_CARD_SIZE, config.ARTIST_CARD_SIZE + 58)
        inner = QVBoxLayout(card)
        inner.setContentsMargins(10, 10, 10, 10)
        inner.setSpacing(4)
        tile = CoverTile(self._palette, config.ARTIST_CARD_SIZE - 20)
        if album.thumbnail:
            tile.set_track_cover(album.thumbnail)
        title = QLabel(album.title)
        title.setWordWrap(True)
        title.setMaximumHeight(30)
        sub = QLabel(album.year or album.artist or "")
        sub.setProperty("dim", True)
        inner.addWidget(tile)
        inner.addWidget(title, 1)
        inner.addWidget(sub)
        card.clicked.connect(lambda _=False, a=album: self.album_opened.emit(a))
        return card

    def _fill_related(self, related: list[Artist]) -> None:
        while self._related_row.count():
            item = self._related_row.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        for act in related:
            chip = QPushButton(f"🎤 {act.name}")
            chip.setProperty("chip", True)
            chip.setCursor(Qt.CursorShape.PointingHandCursor)
            chip.clicked.connect(
                lambda _=False, a=act: self.artist_opened.emit(a)
            )
            self._related_row.addWidget(chip)
        self._related_row.addStretch(1)
        self._related_cap.setVisible(bool(related))

    def apply_palette(self, palette: Palette) -> None:
        self._palette = palette
        self._top.apply_palette(palette)

    @property
    def current_artist(self) -> Artist | None:
        return self._artist


# ----------------------------------------------------------------- now playing

class LyricsSheet(QWidget):
    """The lyrics pane: plain text, or LRC lines that glow with the song.

    In synced mode the active line is lit in the palette accent and kept
    centered; clicking any line seeks the player to that moment.
    """

    line_clicked = pyqtSignal(int)   # ms — click a lyric line to seek there

    def __init__(self, palette: Palette):
        super().__init__()
        self._palette = palette
        self._sync: SyncedLyrics | None = None
        self._active = -2                       # -2 = nothing highlighted yet
        self._lyric_font = lyrics_font(config.LYRICS_DEFAULT_SIZE_KEY)

        pages = QStackedLayout(self)
        pages.setContentsMargins(0, 0, 0, 0)
        self._plain = QPlainTextEdit()
        self._plain.setProperty("lyrics", True)
        self._plain.setReadOnly(True)
        self._plain.setPlaceholderText(
            "Lyrics show up here once something is playing."
        )
        self._sheet = QListWidget()
        self._sheet.setProperty("lyrics", True)
        self._sheet.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self._sheet.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._sheet.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._sheet.itemClicked.connect(self._on_clicked)
        pages.addWidget(self._plain)
        pages.addWidget(self._sheet)
        self._pages = pages

    # --- content in ---

    def show_message(self, text: str) -> None:
        """Plain-text state (loading notices, empty results)."""
        self._sync = None
        self._active = -2
        self._pages.setCurrentWidget(self._plain)
        self._plain.setPlainText(text)

    def set_plain(self, text: str | None) -> None:
        self._sync = None
        self._active = -2
        self._pages.setCurrentWidget(self._plain)
        self._plain.setPlainText(text or "No lyrics available for this track.")

    def set_synced(self, lines: list[LrcLine]) -> None:
        if not lines:
            self.set_plain(None)
            return
        self._sync = SyncedLyrics(lines)
        self._active = -2
        self._sheet.clear()
        dim = QColor(self._palette.text_dim)
        for line in self._sync.lines:
            item = QListWidgetItem(line.text or "♪")
            item.setTextAlignment(
                Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter
            )
            item.setData(Qt.ItemDataRole.UserRole, line.time_ms)
            item.setToolTip(clock(line.time_ms))
            item.setForeground(dim)
            item.setFont(self._lyric_font)
            self._sheet.addItem(item)
        self._pages.setCurrentWidget(self._sheet)

    # --- position in / interaction out ---

    def set_position(self, position_ms: int) -> None:
        """Light the line that owns this moment (no-op in plain mode)."""
        if self._sync is None or self._sync.empty:
            return
        index = self._sync.line_at(position_ms)
        if index == self._active:
            return
        self._activate(index)

    def _activate(self, index: int) -> None:
        if 0 <= self._active < self._sheet.count():
            prev = self._sheet.item(self._active)
            prev.setFont(self._lyric_font)
            prev.setForeground(QColor(self._palette.text_dim))
        self._active = index
        if 0 <= index < self._sheet.count():
            item = self._sheet.item(index)
            font = QFont(self._lyric_font)
            font.setBold(True)
            font.setPixelSize(self._lyric_font.pixelSize() + 2)
            item.setFont(font)
            item.setForeground(QColor(self._palette.accent))
            self._sheet.scrollToItem(
                item, QAbstractItemView.ScrollHint.PositionAtCenter
            )

    def _on_clicked(self, item: QListWidgetItem) -> None:
        ms = item.data(Qt.ItemDataRole.UserRole)
        if isinstance(ms, int):
            self.line_clicked.emit(ms)

    def apply_lyrics_font(self, font: QFont) -> None:
        """Apply the lyrics settings typeface to every line, live."""
        self._lyric_font = QFont(font)
        if self._sync is None:
            return
        for index in range(self._sheet.count()):
            item = self._sheet.item(index)
            if index == self._active:
                active = QFont(self._lyric_font)
                active.setBold(True)
                active.setPixelSize(self._lyric_font.pixelSize() + 2)
                item.setFont(active)
            else:
                item.setFont(self._lyric_font)

    def apply_palette(self, palette: Palette) -> None:
        self._palette = palette
        if self._sync is None:
            return
        active_color = QColor(self._palette.accent)
        dim = QColor(self._palette.text_dim)
        for index in range(self._sheet.count()):
            item = self._sheet.item(index)
            if index == self._active:
                item.setForeground(active_color)
            else:
                item.setForeground(dim)


class NowView(QWidget):
    """The Now Playing stage: big cover, identity, and the lyrics sheet."""

    pin_toggled = pyqtSignal()
    radio_requested = pyqtSignal()
    lyrics_seek_requested = pyqtSignal(int)   # ms — click a lyric line, go there
    lyrics_font_changed = pyqtSignal(str, str)  # size key (S/M/L), family
    crossfade_changed = pyqtSignal(int)         # seconds (0 = off)

    def __init__(self, palette: Palette):
        super().__init__()
        self._palette = palette
        self._track: Track | None = None
        self._video_id: str = ""

        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 18, 24, 12)
        outer.setSpacing(12)

        head = QHBoxLayout()
        hero = QLabel("Now Playing")
        hero.setProperty("hero", True)
        head.addWidget(hero)
        head.addStretch(1)
        self._btn_radio = QPushButton("📻 Start radio")
        self._btn_radio.clicked.connect(self.radio_requested.emit)
        head.addWidget(self._btn_radio)
        outer.addLayout(head)

        body = QHBoxLayout()
        body.setSpacing(24)

        left = QVBoxLayout()
        left.setSpacing(10)
        self._cover = CoverTile(palette, config.NOW_COVER)
        self._cover_glow = add_glow(self._cover, palette.accent, blur=54,
                                    alpha=120)
        self._reflection = QLabel()
        self._reflection.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        self._reflection.setFixedHeight(round(config.NOW_COVER * 0.4))
        self._cover.art_changed.connect(self._set_reflection)
        ident = QHBoxLayout()
        ident.setSpacing(8)
        text = QVBoxLayout()
        text.setSpacing(2)
        self._title = QLabel("Nothing playing")
        self._title.setProperty("header", True)
        self._title.setWordWrap(True)
        self._artist = QLabel("pick something from the shelves")
        self._artist.setProperty("dim", True)
        self._artist.setWordWrap(True)
        text.addWidget(self._title)
        text.addWidget(self._artist)
        self._pin = QPushButton("♡")
        self._pin.setProperty("flat", True)
        self._pin.setFixedWidth(34)
        self._pin.setToolTip("Pin to favorites")
        self._pin.clicked.connect(self.pin_toggled.emit)
        ident.addLayout(text, 1)
        ident.addWidget(self._pin)
        left.addWidget(self._cover, 0, Qt.AlignmentFlag.AlignHCenter)
        left.addWidget(self._reflection)
        left.addLayout(ident)
        left.addStretch(1)

        right = QVBoxLayout()
        right.setSpacing(6)
        cap_row = QHBoxLayout()
        cap_row.setSpacing(6)
        cap = QLabel("LYRICS")
        cap.setProperty("dim", True)
        self._lyrics = LyricsSheet(palette)
        self._lyrics.line_clicked.connect(self.lyrics_seek_requested.emit)
        cap_row.addWidget(cap)
        cap_row.addStretch(1)
        # --- lyrics settings row: family + S/M/L size presets (v0.8.0) ---
        self._size_key = config.LYRICS_DEFAULT_SIZE_KEY
        self._family_box = QComboBox()
        self._family_box.addItems(config.LYRICS_FONT_FAMILIES)
        self._family_box.setToolTip("Lyrics font")
        self._family_box.activated.connect(
            lambda _i: self._emit_lyrics_font()
        )
        cap_row.addWidget(self._family_box)
        self._size_chips: dict[str, QPushButton] = {}
        for key in config.LYRICS_SIZE_PRESETS:
            chip = QPushButton(key)
            chip.setProperty("chip", True)
            chip.setCheckable(True)
            chip.setFixedWidth(34)
            chip.setCursor(Qt.CursorShape.PointingHandCursor)
            chip.setToolTip(f"Lyrics size {key} — "
                            f"{config.LYRICS_SIZE_PRESETS[key]}px")
            chip.clicked.connect(lambda _=False, k=key: self.set_lyrics_size(k))
            self._size_chips[key] = chip
            cap_row.addWidget(chip)
        self._sync_size_chips()
        right.addLayout(cap_row)
        # --- crossfade row (v1.0.0 groundwork, opt-in via config flag) ---
        # Built only when CROSSFADE_ENABLED: with the flag off (default)
        # the slider never exists and nothing else in the view changes.
        self._xf_slider = None
        self._xf_label = None
        if config.CROSSFADE_ENABLED:
            xf_row = QHBoxLayout()
            xf_row.setSpacing(8)
            xf_cap = QLabel("Crossfade")
            xf_cap.setProperty("dim", True)
            self._xf_label = QLabel("off")
            self._xf_label.setProperty("dim", True)
            self._xf_label.setFixedWidth(28)
            self._xf_slider = QSlider(Qt.Orientation.Horizontal)
            self._xf_slider.setRange(0, max(0, config.CROSSFADE_MAX_MS // 1000))
            self._xf_slider.setValue(config.CROSSFADE_DEFAULT_SECONDS)
            self._xf_slider.setToolTip("Blend the end of one song into the next")
            self._xf_slider.valueChanged.connect(self._on_crossfade_moved)
            xf_row.addWidget(xf_cap)
            xf_row.addWidget(self._xf_slider, 1)
            xf_row.addWidget(self._xf_label)
            right.addLayout(xf_row)
        right.addWidget(self._lyrics, 1)

        body.addLayout(left, 1)
        body.addLayout(right, 1)
        outer.addLayout(body, 1)

    # --- state in ---

    def _set_reflection(self, pixmap) -> None:
        """Mirror the current cover in a fading floor reflection."""
        base = self._cover.pixmap()
        if base is None or base.isNull():
            self._reflection.clear()
            return
        self._reflection.setPixmap(reflected_pixmap(base, depth_frac=0.3))

    def set_track(self, track: Track | None) -> None:
        self._track = track
        if track is None:
            self._video_id = ""
            self._title.setText("Nothing playing")
            self._artist.setText("pick something from the shelves")
            self._pin.setText("♡")
            self._cover.set_mark()
            self._lyrics.show_message("")
            self._reflection.clear()
            return
        self._video_id = track.video_id
        self._title.setText(track.title)
        self._artist.setText(track.artist)
        if track.thumbnail:
            self._cover.set_track_cover(track.thumbnail)
        else:
            self._cover.set_mark()

    def set_lyrics(self, video_id: str, text: str | None,
                   lines: list[LrcLine] | None = None) -> None:
        """Late-arriving lyrics; drop them if the track moved on meanwhile."""
        if video_id != self._video_id:
            return
        if lines:
            self._lyrics.set_synced(lines)
        else:
            self._lyrics.set_plain(text)

    def set_lyrics_loading(self) -> None:
        self._lyrics.show_message("Loading lyrics…")

    def set_position(self, position_ms: int) -> None:
        """Keep the glowing lyric line in step with the song."""
        self._lyrics.set_position(position_ms)

    def set_pinned(self, pinned: bool) -> None:
        self._pin.setText("♥" if pinned else "♡")

    def apply_palette(self, palette: Palette) -> None:
        self._palette = palette
        self._cover.apply_palette(palette)
        self._lyrics.apply_palette(palette)
        set_glow_color(self._cover_glow, palette.accent, alpha=120)

    @property
    def current_track(self) -> Track | None:
        return self._track

    def cover_pixmap(self):
        """The current cover art (theater mode reuses it as its giant copy)."""
        return self._cover.pixmap()

    # --- lyrics settings row (v0.8.0) ---

    def set_lyrics_size(self, key: str) -> None:
        """Pick an S/M/L preset and apply it (emits lyrics_font_changed)."""
        if key not in self._size_chips:
            return
        self._size_key = key
        self._sync_size_chips()
        self._emit_lyrics_font()

    def set_lyrics_settings(self, size_key: str, family: str) -> None:
        """Restore persisted settings silently (no signal — app already knows)."""
        if size_key in self._size_chips:
            self._size_key = size_key
        self._sync_size_chips()
        if family and self._family_box.findText(family) >= 0:
            self._family_box.setCurrentText(family)
        self.apply_lyrics_font(lyrics_font(self._size_key,
                                           self._family_box.currentText()))

    def apply_lyrics_font(self, font: QFont) -> None:
        self._lyrics.apply_lyrics_font(font)

    @property
    def lyrics_size_key(self) -> str:
        return self._size_key

    def _sync_size_chips(self) -> None:
        for key, chip in self._size_chips.items():
            chip.setChecked(key == self._size_key)

    # --- crossfade row (v1.0.0 groundwork) ---

    def _on_crossfade_moved(self, value: int) -> None:
        self._sync_crossfade_label(value)
        self.crossfade_changed.emit(int(value))

    def _sync_crossfade_label(self, value: int) -> None:
        if self._xf_label is not None:
            self._xf_label.setText(f"{int(value)}s" if value else "off")

    def set_crossfade(self, seconds: int) -> None:
        """Restore the persisted length silently (the app already knows)."""
        if self._xf_slider is None:
            return
        try:
            seconds = int(seconds)
        except (TypeError, ValueError):
            seconds = 0
        seconds = max(0, min(self._xf_slider.maximum(), seconds))
        self._xf_slider.blockSignals(True)
        self._xf_slider.setValue(seconds)
        self._xf_slider.blockSignals(False)
        self._sync_crossfade_label(seconds)

    @property
    def crossfade_seconds(self) -> int:
        return 0 if self._xf_slider is None else int(self._xf_slider.value())

    def _emit_lyrics_font(self) -> None:
        """Apply locally, then tell the app (it persists + spreads the rest)."""
        family = self._family_box.currentText()
        self._lyrics.apply_lyrics_font(lyrics_font(self._size_key, family))
        self.lyrics_font_changed.emit(self._size_key, family)


class TheaterView(QWidget):
    """Full-screen Now Playing: the giant, glowing end of the stage.

    A pure VIEW over the state the main window already holds — the same
    track, the same lyric tick, zero playback logic. Esc or the ✕ walks
    you back to the regular room.
    """

    exit_requested = pyqtSignal()

    def __init__(self, palette: Palette):
        super().__init__()
        self._palette = palette
        self._track: Track | None = None
        self._video_id: str = ""
        self._sync: SyncedLyrics | None = None
        self._active = -2
        self._lyric_font = lyrics_font(config.LYRICS_DEFAULT_SIZE_KEY)
        self.setStyleSheet(build_stylesheet(palette))

        outer = QVBoxLayout(self)
        outer.setContentsMargins(48, 32, 48, 36)
        outer.setSpacing(18)

        top = QHBoxLayout()
        mark = QLabel(f"🔥 {config.APP_NAME} theater")
        mark.setProperty("kicker", True)
        top.addWidget(mark)
        top.addStretch(1)
        self._close = QPushButton("✕  Exit (Esc)")
        self._close.setProperty("flat", True)
        self._close.setCursor(Qt.CursorShape.PointingHandCursor)
        self._close.clicked.connect(self.exit_requested.emit)
        top.addWidget(self._close)
        outer.addLayout(top)

        self._cover = CoverTile(palette, config.THEATER_COVER)
        self._cover_glow = add_glow(self._cover, palette.accent, blur=90,
                                    alpha=130)
        outer.addWidget(self._cover, 0, Qt.AlignmentFlag.AlignHCenter)

        self._title = QLabel("Nothing playing")
        self._title.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        self._title.setWordWrap(True)
        self._title.setStyleSheet("font-size: 34px; font-weight: 800;")
        self._artist = QLabel("press Esc to step back into the room")
        self._artist.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        self._artist.setProperty("dim", True)
        outer.addWidget(self._title)
        outer.addWidget(self._artist)

        self._now = QLabel("♪")
        self._now.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter)
        self._now.setWordWrap(True)
        self._now_glow = add_glow(self._now, palette.accent, blur=40, alpha=150)
        self._next = QLabel("")
        self._next.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        self._next.setWordWrap(True)
        self._next.setProperty("dim", True)
        outer.addWidget(self._now, 1)
        outer.addWidget(self._next)
        self.apply_lyrics_font(self._lyric_font)

    # --- state in (mirrors the main window's Now Playing) ---

    def set_track(self, track: Track | None) -> None:
        self._track = track
        if track is None:
            self._video_id = ""
            self._sync = None
            self._active = -2
            self._title.setText("Nothing playing")
            self._artist.setText("press Esc to step back into the room")
            self._cover.set_mark()
            self._now.setText("♪")
            self._next.setText("")
            return
        if track.video_id != self._video_id:
            # a genuinely new song clears the timeline; re-settling the same
            # one (theater re-entry) keeps already-arrived lyrics
            self._sync = None
            self._active = -2
        self._video_id = track.video_id
        self._title.setText(track.title)
        self._artist.setText(track.artist)
        if track.thumbnail:
            self._cover.set_track_cover(track.thumbnail)
        else:
            self._cover.set_mark()

    def set_cover_pixmap(self, pixmap) -> None:
        """Adopt the Now Playing cover instantly (no re-download)."""
        if pixmap is not None and not pixmap.isNull():
            self._cover.setPixmap(pixmap)

    def set_lyrics(self, video_id: str, text: str | None,
                   lines: list[LrcLine] | None = None) -> None:
        """Late-arriving lyrics; drop them if the track moved on meanwhile."""
        if video_id != self._video_id:
            return
        if lines:
            self._sync = SyncedLyrics(lines)
        else:
            self._sync = None
        self._active = -2

    def set_position(self, position_ms: int) -> None:
        """Keep the giant line in step with the song (cheap: two labels)."""
        if self._sync is None or self._sync.empty:
            return
        index = self._sync.line_at(position_ms)
        if index == self._active:
            return
        self._active = index
        if 0 <= index < len(self._sync.lines):
            line = self._sync.lines[index]
            self._now.setText(line.text or "♪")
            if index + 1 < len(self._sync.lines):
                self._next.setText(self._sync.lines[index + 1].text)
            else:
                self._next.setText("")
        else:
            self._now.setText("♪")
            self._next.setText("")

    def apply_lyrics_font(self, font: QFont) -> None:
        """Scale the giant line from the shared lyrics settings."""
        self._lyric_font = QFont(font)
        px = max(18, font.pixelSize())
        giant = QFont(font)
        giant.setPixelSize(round(px * 1.6))
        giant.setBold(True)
        self._now.setFont(giant)
        preview = QFont(font)
        preview.setPixelSize(px)
        preview.setBold(False)
        self._next.setFont(preview)
        # inline styles so the 13px app rule never shrinks the stage type
        self._now.setStyleSheet(
            f"color: {self._palette.accent}; background: transparent;"
            f"font-size: {round(px * 1.6)}px; font-weight: 800;"
        )
        self._next.setStyleSheet(
            f"color: {self._palette.text_dim}; background: transparent;"
            f"font-size: {px}px;"
        )

    def apply_palette(self, palette: Palette) -> None:
        self._palette = palette
        self.setStyleSheet(build_stylesheet(palette))
        self._cover.apply_palette(palette)
        set_glow_color(self._cover_glow, palette.accent, alpha=130)
        set_glow_color(self._now_glow, palette.accent, alpha=150)
        self.apply_lyrics_font(self._lyric_font)
        self.update()

    # --- exit ---

    def keyPressEvent(self, event) -> None:  # noqa: N802 - Qt naming
        if event.key() == Qt.Key.Key_Escape:
            self.exit_requested.emit()
            event.accept()
            return
        super().keyPressEvent(event)

    @property
    def current_track(self) -> Track | None:
        return self._track


# ----------------------------------------------------------------- stats

MONTH_NAMES = ("Jan", "Feb", "Mar", "Apr", "May", "Jun",
               "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def group_months(days: list[tuple[str, int]], months: int = 12,
                 today: str | None = None) -> list[tuple[str, int]]:
    """history_days() → the last `months` (YYYY-MM, plays) buckets, oldest first.

    Pure and storage-free: the day rows are grouped client-side, months
    the store never touched come back as quiet zeros, and `today`
    (YYYY-MM-DD) is injectable so tests can pin the window.
    """
    try:
        end = date.fromisoformat(str(today)) if today else date.today()
    except (TypeError, ValueError):
        end = date.today()
    count = max(1, min(int(months), 36))
    totals: dict[str, int] = {}
    for key, plays in (days or []):
        key = str(key)
        if len(key) < 7:
            continue
        try:
            totals[key[:7]] = totals.get(key[:7], 0) + int(plays)
        except (TypeError, ValueError):
            continue
    buckets: list[tuple[str, int]] = []
    year, month = end.year, end.month
    for _ in range(count):
        key = f"{year:04d}-{month:02d}"
        buckets.append((key, totals.get(key, 0)))
        month -= 1
        if month == 0:
            year, month = year - 1, 12
    buckets.reverse()
    return buckets


class MonthBars(QWidget):
    """Twelve little accent bars: plays per month, painted, no chart lib.

    One widget, one paintEvent — the bar heights are derived straight
    from the (label, count) buckets each pass; months the fire never
    touched simply don't grow a bar.
    """

    def __init__(self, palette: Palette):
        super().__init__()
        self._palette = palette
        self._months: list[tuple[str, int]] = []
        self.setMinimumHeight(110)

    def set_months(self, months: list[tuple[str, int]]) -> None:
        self._months = list(months)[-12:]
        self.update()

    def apply_palette(self, palette: Palette) -> None:
        self._palette = palette
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt naming
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect().adjusted(4, 4, -4, -18))
        peak = max((count for _key, count in self._months), default=0)
        grad = QLinearGradient(0.0, rect.top(), 0.0, rect.bottom())
        grad.setColorAt(0.0, QColor(self._palette.accent_soft))
        grad.setColorAt(1.0, QColor(self._palette.accent))
        painter.setBrush(QBrush(grad))
        pen = painter.pen()
        pen.setColor(QColor(self._palette.text_dim))
        n = max(1, len(self._months))
        slot = rect.width() / n
        bar_w = max(2.0, slot - 6.0)
        for index, (key, count) in enumerate(self._months):
            if count <= 0 or peak <= 0:
                continue
            height = max(2.0, rect.height() * count / peak)
            bar = QRectF(rect.left() + index * slot + 3.0,
                         rect.bottom() - height, bar_w, height)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(bar, 2.4, 2.4)
            painter.setPen(pen)
            painter.drawText(
                QRectF(rect.left() + index * slot, rect.bottom() + 2.0,
                       slot, 14.0),
                Qt.AlignmentFlag.AlignHCenter, _month_label(key),
            )
        painter.end()


def _month_label(key: str) -> str:
    """'2024-03' → 'Mar' (garbage tolerantly becomes '?')."""
    try:
        month = int(str(key)[5:7])
    except (TypeError, ValueError):
        return "?"
    return MONTH_NAMES[month - 1] if 1 <= month <= 12 else "?"


class StatsView(QWidget):
    """📊 Your year at the hearth: plays, minutes, artists, months.

    A pure view over HearthStore's stats — every visit calls refresh(),
    which reads stats_summary() + history_days() and repaints. Nothing
    here touches the network, and an empty history gets a cozy
    invitation instead of a chart of zeroes.
    """

    track_activated = pyqtSignal(object, list)   # Track, context — top tracks

    def __init__(self, palette: Palette, store: HearthStore | None = None):
        super().__init__()
        self._palette = palette
        self.store = store
        self._empty_state = True

        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 18, 24, 12)
        outer.setSpacing(12)

        head = QHBoxLayout()
        hero = QLabel("📊 Your year at the hearth")
        hero.setProperty("hero", True)
        self._status = QLabel("every play remembered, nothing forgotten")
        self._status.setProperty("dim", True)
        head.addWidget(hero)
        head.addStretch(1)
        head.addWidget(self._status)
        rewind_btn = QPushButton("🎁 Rewind story")
        rewind_btn.setProperty("flat", True)
        rewind_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        rewind_btn.setToolTip("Your year at the hearth, told in a few scenes")
        rewind_btn.clicked.connect(self._show_rewind)
        head.addWidget(rewind_btn)
        outer.addLayout(head)

        # page 0: the dashboard · page 1: the no-plays invitation
        self._pages = QStackedWidget()
        outer.addWidget(self._pages, 1)
        self._pages.addWidget(self._build_content())
        self._pages.addWidget(self._build_empty_page())
        self._pages.setCurrentIndex(1)

    # --- the rewind story (v0.7.1) ---

    def _show_rewind(self) -> None:
        """🎁 Rewind: the year told in a few honest scenes over the stats."""
        if self.store is None:
            return
        stats = self.store.stats_summary(top=8)
        scenes = build_rewind_story(
            stats,
            self.store.history_days(),
            stats.get("top_tracks") or [],
            stats.get("top_artists") or [],
        )
        dlg = QDialog(self)
        dlg.setWindowTitle("🎁 Rewind — your year at the hearth")
        lay = QVBoxLayout(dlg)
        lay.setContentsMargins(24, 20, 24, 14)
        lay.setSpacing(10)
        for scene in scenes:
            label = QLabel(scene)
            label.setWordWrap(True)
            label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            lay.addWidget(label)
        # share row (v0.7.1): the story leaves the machine only when you say so
        share_row = QHBoxLayout()
        copy_btn = QPushButton("📋 Copy")
        copy_btn.setProperty("flat", True)
        copy_btn.setToolTip("Copy the story as text — paste it anywhere")
        copy_btn.clicked.connect(
            lambda: QApplication.clipboard().setText("\n".join(scenes))
        )
        png_btn = QPushButton("🖼 Save PNG")
        png_btn.setProperty("flat", True)
        png_btn.setToolTip("Save the story as a shareable card")

        def _save_card() -> None:
            path, _filter = QFileDialog.getSaveFileName(
                dlg, "Save Rewind card", "hearth-rewind.png", "PNG image (*.png)")
            if not path:
                return
            from .card import render_card

            ok = render_card(scenes, path, self._palette.key)
            lbl = QLabel("Card saved ❤" if ok else "Could not save the card")
            lbl.setProperty("dim", True)
            lay.addWidget(lbl)

        png_btn.clicked.connect(_save_card)
        share_row.addWidget(copy_btn)
        share_row.addWidget(png_btn)
        share_row.addStretch(1)
        lay.addLayout(share_row)
        close = QPushButton("Back to the fire")
        close.clicked.connect(dlg.accept)
        lay.addWidget(close)
        dlg.exec()

    # --- construction bits ---

    def _build_content(self) -> QWidget:
        content = QWidget()
        body = QVBoxLayout(content)
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(12)

        tiles = QHBoxLayout()
        tiles.setSpacing(10)
        self._tiles: dict[str, QLabel] = {}
        for key, caption in (("plays", "plays"),
                             ("minutes", "minutes listened"),
                             ("uniques", "unique tracks"),
                             ("days", "days listened")):
            tile = QVBoxLayout()
            tile.setSpacing(1)
            value = QLabel("0")
            value.setStyleSheet("font-size: 26px; font-weight: 800;")
            cap = QLabel(caption)
            cap.setProperty("dim", True)
            tile.addWidget(value)
            tile.addWidget(cap)
            tile.addStretch(1)
            tiles.addLayout(tile, 1)
            self._tiles[key] = value
        body.addLayout(tiles)

        self._first_lit = QLabel("")
        self._first_lit.setProperty("dim", True)
        body.addWidget(self._first_lit)

        middle = QHBoxLayout()
        middle.setSpacing(18)
        artists_col = QVBoxLayout()
        artists_cap = QLabel("Top artists")
        artists_cap.setProperty("shelf", True)
        artists_col.addWidget(artists_cap)
        self._artist_lay = QVBoxLayout()
        self._artist_lay.setSpacing(4)
        artists_col.addLayout(self._artist_lay)
        artists_col.addStretch(1)
        middle.addLayout(artists_col, 1)
        chart_col = QVBoxLayout()
        chart_cap = QLabel("Plays by month")
        chart_cap.setProperty("shelf", True)
        chart_col.addWidget(chart_cap)
        self._months_chart = MonthBars(self._palette)
        chart_col.addWidget(self._months_chart, 1)
        middle.addLayout(chart_col, 1)
        body.addLayout(middle, 1)

        self._top = TrackListView(self._palette)
        self._top.set_header("Top tracks")
        self._top.set_visible_rows(5)
        self._top.track_activated.connect(self.track_activated.emit)
        body.addWidget(self._top)
        return content

    def _build_empty_page(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.addStretch(1)
        self._empty = QLabel("no plays yet — light the fire")
        self._empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty.setStyleSheet("font-size: 22px;")
        lay.addWidget(self._empty)
        hint = QLabel("play something and your year will gather here")
        hint.setProperty("dim", True)
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(hint)
        lay.addStretch(1)
        return page

    # --- data in ---

    def refresh(self) -> None:
        """Re-read the store and repaint every number (cheap: one page)."""
        if self.store is None:
            self._empty_state = True
            self._pages.setCurrentIndex(1)
            return
        try:
            summary = self.store.stats_summary(top=config.STATS_TOP_LIMIT)
            days = self.store.history_days()
        except Exception:  # noqa: BLE001 - a grumpy store shows the invitation
            self._empty_state = True
            self._pages.setCurrentIndex(1)
            return
        total = int(summary.get("total_plays") or 0)
        self._empty_state = total == 0
        self._pages.setCurrentIndex(1 if total == 0 else 0)
        if total == 0:
            return
        self._tiles["plays"].setText(str(total))
        self._tiles["minutes"].setText(str(int(summary.get("est_minutes") or 0)))
        self._tiles["uniques"].setText(str(int(summary.get("unique_tracks") or 0)))
        self._tiles["days"].setText(str(int(summary.get("days_listened") or 0)))
        first = str(summary.get("first_play") or "")
        self._first_lit.setText(
            f"🕯️ First lit {first[:10]}" if first else "")
        self._set_artists(list(summary.get("top_artists") or []))
        self._top.set_tracks(list(summary.get("top_tracks") or []))
        self._months_chart.set_months(group_months(days))

    def _set_artists(self, rows: list[tuple[str, int]]) -> None:
        """The top-artists list: name on the left, play count on the right."""
        while self._artist_lay.count():
            item = self._artist_lay.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        for artist, plays in rows[: config.STATS_TOP_LIMIT]:
            holder = QWidget()
            row = QHBoxLayout(holder)
            row.setContentsMargins(0, 0, 0, 0)
            name = QLabel(str(artist) or "Unknown artist")
            count = QLabel("1 play" if plays == 1 else f"{plays} plays")
            count.setProperty("dim", True)
            row.addWidget(name, 1)
            row.addWidget(count)
            self._artist_lay.addWidget(holder)
        if not rows:
            note = QLabel("no artists yet")
            note.setProperty("dim", True)
            self._artist_lay.addWidget(note)

    def apply_palette(self, palette: Palette) -> None:
        self._palette = palette
        self._months_chart.apply_palette(palette)

    @property
    def empty_state(self) -> bool:
        """True when the last refresh found no plays at all."""
        return self._empty_state


def day_label(day: str) -> str:
    """'2026-02-16' → 'Feb 16' (readable chips; odd days render raw)."""
    try:
        return datetime.strptime(str(day), "%Y-%m-%d").strftime("%b %d")
    except (TypeError, ValueError):
        return str(day)


class HistoryView(TrackListView):
    """🕘 Every play, day by day: jump chips, a paged "All", double-click-to-play.

    A pure view over HearthStore's history — refresh() re-reads
    history_days() and repaints the chip row; picking a day lists
    history_on(day); "All" pages through history_slice() with a
    Show-more button. Zero new storage methods, zero network.
    """

    def __init__(self, palette: Palette, store: HearthStore | None = None,
                 page_size: int | None = None):
        super().__init__(palette)
        self.store = store
        self._page_size = max(1, int(page_size or config.HISTORY_PAGE_SIZE))
        self._page = 0
        self._all: list[Track] = []      # accumulated rows of the current listing
        self._has_more = False
        self._day: str | None = None     # None = All
        self._head.setText("🕘 History")

        self._chips_area = QScrollArea()
        self._chips_area.setWidgetResizable(True)
        self._chips_area.setFixedHeight(44)
        self._chips_area.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._chips_area.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._chips_bar = QWidget()
        self._chips_lay = QHBoxLayout(self._chips_bar)
        self._chips_lay.setContentsMargins(2, 2, 2, 2)
        self._chips_lay.setSpacing(6)
        self._chips_lay.setAlignment(Qt.AlignmentFlag.AlignLeft)
        self._chips_area.setWidget(self._chips_bar)

        self._more_btn = QPushButton("Show more")
        self._more_btn.setProperty("chip", True)
        self._more_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._more_btn.clicked.connect(self._show_more)
        self._more_btn.hide()

        self._empty = QLabel("nothing played yet — light the fire")
        self._empty.setProperty("dim", True)
        self._empty.setAlignment(Qt.AlignmentFlag.AlignCenter)

        row = QHBoxLayout()
        row.addWidget(self._chips_area, 1)
        row.addWidget(self._more_btn)
        lay = self.layout()
        lay.insertLayout(1, row)                       # below the header
        lay.insertWidget(lay.indexOf(self._list), self._empty)
        self._chips: dict[str | None, QPushButton] = {}
        self._empty.hide()

    # --- data in ---

    def refresh(self) -> None:
        """Re-read the store: rebuild chips + repaint the current listing."""
        days: list[tuple[str, int]] = []
        if self.store is not None:
            try:
                days = list(self.store.history_days())
            except Exception:   # noqa: BLE001 - a grumpy store shows an empty page
                days = []
        has_any = bool(days)
        self._empty.setVisible(not has_any)
        self._list.setVisible(has_any)
        self._chips_area.setVisible(has_any)
        self._build_chips(days[: config.HISTORY_CHIP_DAYS])
        self._load_current()

    def _build_chips(self, days: list[tuple[str, int]]) -> None:
        """The chip row: 'All' first, then the newest listening days."""
        self._chips = {}
        while self._chips_lay.count():
            item = self._chips_lay.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        all_chip = self._make_chip("All")
        all_chip.clicked.connect(lambda _=False: self._select_day(None))
        self._chips[None] = all_chip
        self._chips_lay.addWidget(all_chip)
        for day, count in days:
            chip = self._make_chip(day_label(day), tooltip=f"{count} plays")
            chip.clicked.connect(lambda _=False, d=day: self._select_day(d))
            self._chips[day] = chip
            self._chips_lay.addWidget(chip)
        self._chips_lay.addStretch(1)
        self._sync_chips()

    def _make_chip(self, label: str, tooltip: str = "") -> QPushButton:
        chip = QPushButton(label)
        chip.setProperty("chip", True)
        chip.setCheckable(True)
        chip.setCursor(Qt.CursorShape.PointingHandCursor)
        if tooltip:
            chip.setToolTip(tooltip)
        return chip

    def _sync_chips(self) -> None:
        for key, chip in self._chips.items():
            chip.setChecked(key == self._day)

    def _select_day(self, day: str | None) -> None:
        """A chip was clicked (None = All): reload the listing under it."""
        self._day = day
        self._sync_chips()
        self._load_current()

    def _load_current(self) -> None:
        if self.store is None:
            self._all = []
            self._has_more = False
            self._more_btn.hide()
            self.set_tracks([])
            return
        try:
            if self._day is None:
                self._page = 0
                tracks, self._has_more = self.store.history_slice(
                    0, self._page_size)
                self._all = list(tracks)
            else:
                self._all = list(self.store.history_on(
                    self._day, limit=self._page_size))
                self._has_more = False
        except Exception:   # noqa: BLE001 - a grumpy store beats a crash
            self._all = []
            self._has_more = False
        self._more_btn.setVisible(self._has_more)
        self.set_tracks(self._all)

    def _show_more(self) -> None:
        """Append the next 'All' page (day views stay single-page)."""
        if self._day is not None or self.store is None or not self._has_more:
            return
        self._page += 1
        try:
            tracks, has_more = self.store.history_slice(
                self._page, self._page_size)
        except Exception:   # noqa: BLE001 - paging stops politely
            self._has_more = False
            self._more_btn.hide()
            return
        self._all.extend(tracks)
        self._has_more = has_more
        self._more_btn.setVisible(has_more)
        self.set_tracks(self._all)


# ----------------------------------------------------------------- visualizer

class VisualizerModel:
    """Pure headless model behind the player-bar mini-visualizer.

    No Qt, no clock: the widget feeds `tick(dt)` every frame and paints
    whatever comes back. Bars ease toward smooth pseudo-random targets
    while playing (each bar drifts on its own phase), settle into a low
    resting wave when paused, and fall to a flat baseline when stopped.
    Every amplitude stays in [0, 1] and moves at most MAX_STEP_PER_SEC
    * dt per tick, so nothing on screen ever jumps or flickers. A seed
    makes the whole dance reproducible in tests.
    """

    MAX_STEP_PER_SEC = 2.2   # easing cap: a full swing takes ~0.45 s

    STATES = ("playing", "paused", "stopped")

    def __init__(self, bars: int | None = None, seed: int | None = None):
        self._n = max(1, int(bars or config.VISUALIZER_BARS))
        self._rng = random.Random(seed)
        self._state = "stopped"
        self._t = 0.0
        self._amps = [0.0] * self._n
        self._phase = [self._rng.uniform(0.0, 2.0 * math.pi)
                       for _ in range(self._n)]
        self._drift = [self._rng.uniform(0.6, 2.4)
                       for _ in range(self._n)]

    @property
    def bars(self) -> int:
        return self._n

    @property
    def state(self) -> str:
        return self._state

    @property
    def amplitudes(self) -> list[float]:
        """The live heights (read-only view — paint straight from it)."""
        return self._amps

    def set_state(self, state: str) -> None:
        """'playing' | 'paused' | 'stopped' (anything else is ignored)."""
        if state in self.STATES:
            self._state = state

    def tick(self, dt: float) -> list[float]:
        """Advance one frame; returns a fresh list of heights in [0, 1]."""
        dt = min(max(float(dt), 0.0), 0.25)   # tab-switch spikes stay tame
        self._t += dt
        cap = self.MAX_STEP_PER_SEC * dt
        for i in range(self._n):
            self._phase[i] = (self._phase[i] + self._drift[i] * dt) % (2.0 * math.pi)
            target = self._target(i)
            delta = target - self._amps[i]
            if delta > cap:
                delta = cap
            elif delta < -cap:
                delta = -cap
            self._amps[i] += delta
        return list(self._amps)

    def _target(self, i: int) -> float:
        """Where bar `i` wants to be this frame, per the current state."""
        if self._state == "playing":
            return 0.32 + 0.53 * (0.5 + 0.5 * math.sin(self._phase[i]))
        if self._state == "paused":
            wave = 0.5 + 0.5 * math.sin(self._t * 1.1 + self._phase[i] * 0.35)
            return 0.05 + 0.07 * wave   # the fire idles low, never out
        return 0.0


class MiniVisualizer(QWidget):
    """The player-bar equalizer: rounded accent bars breathing with the song.

    One widget, one paintEvent, one timer. Geometry and the accent
    gradient are cached on resize/palette changes, and each frame only
    re-heights the cached rects in place — nothing is allocated per
    frame. The actual motion lives in the pure VisualizerModel.
    """

    def __init__(self, palette: Palette, bars: int | None = None,
                 model: VisualizerModel | None = None, parent=None):
        super().__init__(parent)
        self._palette = palette
        self._model = model or VisualizerModel(bars=bars)
        self._bars: list[QRectF] = []      # full-height templates, re-heighted per frame
        self._floor = 0.0                  # bottom y for every bar
        self._full_h = 0.0
        self._brush = QBrush()
        self.setFixedSize(124, 40)
        self._timer = QTimer(self)
        self._timer.setInterval(config.VISUALIZER_TICK_MS)
        self._timer.timeout.connect(self._on_tick)
        self._last = 0.0
        self._rebuild()

    # --- state in ---

    def set_state(self, state: str) -> None:
        """'playing' | 'paused' | 'stopped' — forwarded to the model."""
        self._model.set_state(state)

    def apply_palette(self, palette: Palette) -> None:
        self._palette = palette
        self._rebuild()
        self.update()

    # --- lifecycle ---

    def showEvent(self, event) -> None:  # noqa: N802 - Qt naming
        self._last = 0.0
        self._timer.start()
        super().showEvent(event)

    def hideEvent(self, event) -> None:  # noqa: N802 - Qt naming
        self._timer.stop()
        super().hideEvent(event)

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt naming
        self._rebuild()
        super().resizeEvent(event)

    # --- frame loop ---

    def _on_tick(self) -> None:
        now = time.monotonic()
        dt = (now - self._last) if self._last else config.VISUALIZER_TICK_MS / 1000.0
        self._last = now
        self._model.tick(dt)
        self.update()

    # --- painting ---

    def _rebuild(self) -> None:
        """Re-derive bar templates + the accent gradient (resize/palette)."""
        w, h = self.width(), self.height()
        count = self._model.bars
        gap = 3.0
        bar_w = max(1.0, (w - gap * (count - 1)) / count)
        self._floor = float(h) - 2.0
        self._full_h = self._floor - 2.0
        self._bars = [
            QRectF(i * (bar_w + gap), 2.0, bar_w, self._full_h)
            for i in range(count)
        ]
        grad = QLinearGradient(0.0, 0.0, 0.0, float(h))
        grad.setColorAt(0.0, QColor(self._palette.accent_soft))
        grad.setColorAt(1.0, QColor(self._palette.accent))
        self._brush = QBrush(grad)

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt naming
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(self._brush)
        full = self._full_h
        for rect, amp in zip(self._bars, self._model.amplitudes):
            rect.setHeight(max(2.0, full * amp))   # in place: no per-frame allocations
            rect.moveBottom(self._floor)
            painter.drawRoundedRect(rect, 1.6, 1.6)
        painter.end()


# ----------------------------------------------------------------- player bar

class PlayerBar(QWidget):
    """Bottom transport: cover, pin, controls, seek, queue toggle, volume."""

    play_pause_requested = pyqtSignal()
    next_requested = pyqtSignal()
    prev_requested = pyqtSignal()
    shuffle_requested = pyqtSignal()
    repeat_requested = pyqtSignal()
    volume_changed = pyqtSignal(float)
    seek_requested = pyqtSignal(int)
    pin_toggled = pyqtSignal()
    queue_toggled = pyqtSignal()
    radio_requested = pyqtSignal()
    rate_cycled = pyqtSignal()
    sleep_requested = pyqtSignal(int)      # minutes; 0 = off
    lyrics_toggled = pyqtSignal()

    def __init__(self, palette: Palette):
        super().__init__()
        self._palette = palette
        self._track: Track | None = None
        self._pinned = False
        self.setFixedHeight(config.PLAYERBAR_HEIGHT)
        self.setProperty("playerbar", True)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(16, 10, 16, 10)
        lay.setSpacing(10)   # was 12 — the mini-visualizer needs a snug row

        # left: cover + identity + pin
        self._cover = CoverTile(palette, 56)
        add_shadow(self._cover, blur=18, dy=3, alpha=150)
        self._title = QLabel("Nothing playing")
        self._title.setProperty("header", True)
        self._artist = QLabel("pick something from the shelves")
        self._artist.setProperty("dim", True)
        ident = QVBoxLayout()
        ident.setSpacing(2)
        ident.addWidget(self._title)
        ident.addWidget(self._artist)
        self._pin = QPushButton("♡")
        self._pin.setProperty("flat", True)
        self._pin.setFixedWidth(34)
        self._pin.setToolTip("Pin to favorites")
        self._pin.clicked.connect(self.pin_toggled.emit)

        # center: transport + seek
        self._btn_shuffle = QPushButton("🔀")
        self._btn_prev = QPushButton("⏮")
        self._btn_play = QPushButton("▶")
        self._btn_play.setProperty("accent", True)
        self._play_glow = add_glow(self._btn_play, palette.accent, blur=28,
                                   alpha=95)
        self._btn_next = QPushButton("⏭")
        self._btn_repeat = QPushButton("🔁")
        self._btn_shuffle.setProperty("flat", True)
        self._btn_repeat.setProperty("flat", True)
        self._btn_prev.setProperty("flat", True)
        self._btn_next.setProperty("flat", True)
        for b in (self._btn_shuffle, self._btn_prev, self._btn_play,
                  self._btn_next, self._btn_repeat):
            b.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_play.setFixedSize(44, 36)
        self._btn_shuffle.clicked.connect(self.shuffle_requested.emit)
        self._btn_prev.clicked.connect(self.prev_requested.emit)
        self._btn_play.clicked.connect(self.play_pause_requested.emit)
        self._btn_next.clicked.connect(self.next_requested.emit)
        self._btn_repeat.clicked.connect(self.repeat_requested.emit)

        self._elapsed = QLabel("0:00")
        self._elapsed.setProperty("dim", True)
        self._total = QLabel("0:00")
        self._total.setProperty("dim", True)
        self._seek = QSlider(Qt.Orientation.Horizontal)
        self._seek.setRange(0, 0)
        self._seek.sliderReleased.connect(
            lambda: self.seek_requested.emit(self._seek.value())
        )
        center = QVBoxLayout()
        center.setSpacing(4)
        ctrl = QHBoxLayout()
        ctrl.addStretch(1)
        for b in (self._btn_shuffle, self._btn_prev, self._btn_play,
                  self._btn_next, self._btn_repeat):
            ctrl.addWidget(b)
        ctrl.addStretch(1)
        seek_row = QHBoxLayout()
        seek_row.setSpacing(8)
        seek_row.addWidget(self._elapsed)
        seek_row.addWidget(self._seek, 1)
        seek_row.addWidget(self._total)
        center.addLayout(ctrl)
        center.addLayout(seek_row)

        # right: lyrics · radio · speed · sleep · queue · volume
        self._btn_lyrics = QPushButton("♪")
        self._btn_lyrics.setProperty("flat", True)
        self._btn_lyrics.setToolTip("Now playing & lyrics")
        self._btn_lyrics.clicked.connect(self.lyrics_toggled.emit)
        self._btn_radio = QPushButton("📻")
        self._btn_radio.setProperty("flat", True)
        self._btn_radio.setToolTip("Start radio from this track")
        self._btn_radio.clicked.connect(self.radio_requested.emit)
        self._btn_speed = QPushButton("1x")
        self._btn_speed.setProperty("flat", True)
        self._btn_speed.setFixedWidth(44)
        self._btn_speed.setToolTip("Playback speed")
        self._btn_speed.clicked.connect(self.rate_cycled.emit)
        self._btn_sleep = QPushButton("⏾")
        self._btn_sleep.setProperty("flat", True)
        self._btn_sleep.setToolTip("Sleep timer")
        self._sleep_menu = QMenu(self)
        for label, minutes in (("Off", 0), ("15 minutes", 15),
                               ("30 minutes", 30), ("45 minutes", 45),
                               ("60 minutes", 60)):
            act = self._sleep_menu.addAction(label)
            act.triggered.connect(
                lambda _checked=False, m=minutes: self.sleep_requested.emit(m)
            )
        self._btn_sleep.setMenu(self._sleep_menu)
        self._btn_queue = QPushButton("☰ Queue")
        self._btn_queue.setProperty("flat", True)
        self._btn_queue.clicked.connect(self.queue_toggled.emit)
        self._volume = QSlider(Qt.Orientation.Horizontal)
        self._volume.setRange(0, 100)
        self._volume.setValue(80)
        self._volume.setFixedWidth(110)
        self._volume.valueChanged.connect(lambda v: self.volume_changed.emit(v / 100.0))

        self.visualizer = MiniVisualizer(palette)
        lay.addWidget(self._cover)
        lay.addLayout(ident, 1)
        lay.addWidget(self._pin)
        lay.addLayout(center, 3)
        lay.addWidget(self.visualizer)
        lay.addWidget(self._btn_lyrics)
        lay.addWidget(self._btn_radio)
        lay.addWidget(self._btn_speed)
        lay.addWidget(self._btn_sleep)
        lay.addWidget(self._btn_queue)
        lay.addWidget(self._volume)

    # --- state in ---

    def set_track(self, track: Track | None) -> None:
        self._track = track
        if track is None:
            self._title.setText("Nothing playing")
            self._artist.setText("pick something from the shelves")
            self._pin.setText("♡")
            self._cover.set_mark()
            return
        self._title.setText(track.title)
        self._artist.setText(track.artist)
        self._pin.setText("♥" if self._pinned else "♡")
        if track.thumbnail:
            self._cover.set_track_cover(track.thumbnail)
        else:
            self._cover.set_mark()

    def set_pinned(self, pinned: bool) -> None:
        self._pinned = pinned
        self._pin.setText("♥" if pinned else "♡")

    def set_playing(self, playing: bool) -> None:
        self._btn_play.setText("⏸" if playing else "▶")

    def set_visualizer_state(self, state: str) -> None:
        """Feed the mini-visualizer: 'playing' | 'paused' | 'stopped'."""
        self.visualizer.set_state(state)

    def set_status(self, text: str) -> None:
        self._artist.setText(text) if self._track is None else None

    def set_position(self, position_ms: int) -> None:
        self._elapsed.setText(clock(position_ms))
        if not self._seek.isSliderDown():
            self._seek.setValue(position_ms)

    def set_duration(self, duration_ms: int) -> None:
        self._total.setText(clock(duration_ms))
        self._seek.setRange(0, max(0, duration_ms))

    def set_volume(self, value: float) -> None:
        self._volume.blockSignals(True)
        self._volume.setValue(int(value * 100))
        self._volume.blockSignals(False)

    def set_speed_label(self, rate: float) -> None:
        label = f"{rate:g}x"
        self._btn_speed.setText(label)
        self._btn_speed.setToolTip(f"Playback speed ({label})")

    def set_sleep_label(self, minutes: int | None) -> None:
        self._btn_sleep.setText(f"⏾ {minutes}" if minutes else "⏾")

    def apply_palette(self, palette: Palette) -> None:
        self._palette = palette
        set_glow_color(self._play_glow, palette.accent, alpha=95)
        self.visualizer.apply_palette(palette)

    @property
    def current_track(self) -> Track | None:
        return self._track


# ----------------------------------------------------------------- main window

class AccentPickerDialog(QDialog):
    """Tweak the current palette's accent/accent_soft, live.

    A modest dialog: two pickers, a live swatch, and "save as pack" —
    which writes the tweaked colors out as a portable JSON pack instead
    of ever overwriting a built-in palette.
    """

    palette_changed = pyqtSignal(object)   # Palette — the live trial
    pack_saved = pyqtSignal(str)           # effective key of the saved pack

    FIELDS = ("accent", "accent_soft")

    def __init__(self, palette: Palette, parent=None):
        super().__init__(parent)
        self.setWindowTitle("🎨 Accent colors")
        self.setMinimumWidth(340)
        self._base = palette
        self._palette = palette
        self.saved = False

        lay = QVBoxLayout(self)
        lay.setSpacing(10)

        self._preview = QLabel()
        self._preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._preview.setFixedHeight(72)
        lay.addWidget(self._preview)

        picks = QHBoxLayout()
        picks.setSpacing(8)
        self._swatches: dict[str, QLabel] = {}
        for field in self.FIELDS:
            btn = QPushButton(f"🎨 Pick {field}…")
            btn.clicked.connect(lambda _=False, f=field: self._pick(f))
            picks.addWidget(btn)
        lay.addLayout(picks)

        self._swatch_row = QHBoxLayout()
        for field in self.FIELDS:
            swatch = QLabel(field)
            swatch.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._swatches[field] = swatch
            self._swatch_row.addWidget(swatch, 1)
        lay.addLayout(self._swatch_row)

        row = QHBoxLayout()
        row.setSpacing(8)
        save = QPushButton("💾 Save as pack…")
        save.setProperty("accent", True)
        save.clicked.connect(self._save_pack)
        reset = QPushButton("Reset")
        reset.clicked.connect(self._reset)
        row.addWidget(save, 1)
        row.addWidget(reset)
        close = QPushButton("Close")
        close.clicked.connect(self.reject)
        row.addWidget(close)
        lay.addLayout(row)
        self._refresh()

    # --- internals ---

    def _pick(self, field: str) -> None:
        color = QColorDialog.getColor(
            QColor(getattr(self._palette, field)), self, f"Pick {field}"
        )
        if not color.isValid():
            return
        self._palette = replace(self._palette, **{field: color.name()})
        self._refresh()
        self.palette_changed.emit(self._palette)

    def _reset(self) -> None:
        self._palette = self._base
        self._refresh()
        self.palette_changed.emit(self._palette)

    def _save_pack(self) -> None:
        key = register_custom_palette(self._palette)
        if key is None:   # a trial of a valid palette always validates
            return
        path, _filter = QFileDialog.getSaveFileName(
            self, "Save palette pack",
            f"{key}.hearthpalette.json",
            "Hearth palette pack (*.json);;All files (*)",
        )
        if not path:
            return
        if export_palette(key, path):
            self.saved = True
            self.pack_saved.emit(key)
            self.accept()

    def _refresh(self) -> None:
        p = self._palette
        self._preview.setText("Aa  ♪  keep the fire warm")
        self._preview.setStyleSheet(
            f"background: {p.bg}; color: {p.text}; border: 1px solid {p.hairline};"
            f"border-radius: 10px; font-size: 17px; font-weight: 700;"
        )
        for field in self.FIELDS:
            swatch = self._swatches.get(field)
            if swatch is not None:
                swatch.setStyleSheet(
                    f"background: {getattr(p, field)}; color: {p.bg};"
                    f"border-radius: 8px; font-weight: 700; padding: 6px;"
                )



class StylePickerDialog(QDialog):
    """The style closet: try whole visual languages + your own wallpaper.

    Everything is a live trial — clicking a style card (or dragging the
    wallpaper slider) re-skins the running app through signals; only OK
    commits. Cancel lets the app restore whatever the room looked like
    before the closet opened.
    """

    style_trial = pyqtSignal(str)            # key — preview a style live
    style_chosen = pyqtSignal(str)           # key — committed on OK
    background_picked = pyqtSignal(str)      # image file the user picked
    background_cleared = pyqtSignal()
    wallpaper_alpha_changed = pyqtSignal(int)

    def __init__(self, style_key: str, alpha: int, has_wallpaper: bool,
                 parent=None):
        super().__init__(parent)
        self.setWindowTitle("🪞 Style closet")
        self.setMinimumWidth(380)
        self.saved = False
        self._current = style_key

        lay = QVBoxLayout(self)
        lay.setSpacing(8)

        head = QLabel("STYLE")
        head.setProperty("kicker", True)
        lay.addWidget(head)

        self._cards: dict[str, QPushButton] = {}
        for key, pack in STYLES.items():
            card = QPushButton(f"{pack.label}  —  {pack.blurb}")
            card.setCheckable(True)
            card.setCursor(Qt.CursorShape.PointingHandCursor)
            card.setChecked(key == style_key)
            card.clicked.connect(lambda _=False, k=key: self._trial(k))
            self._cards[key] = card
            lay.addWidget(card)

        lay.addSpacing(6)
        bg_head = QLabel("BACKGROUND")
        bg_head.setProperty("kicker", True)
        lay.addWidget(bg_head)

        self._upload_btn = QPushButton("🖼 Upload background…")
        self._upload_btn.clicked.connect(self._pick_image)
        lay.addWidget(self._upload_btn)

        self._remove_btn = QPushButton("🚫 Remove background")
        self._remove_btn.clicked.connect(self.background_cleared.emit)
        self._remove_btn.setEnabled(has_wallpaper)
        lay.addWidget(self._remove_btn)

        alpha_row = QHBoxLayout()
        alpha_cap = QLabel("See-through")
        alpha_cap.setProperty("dim", True)
        self._alpha = QSlider(Qt.Orientation.Horizontal)
        self._alpha.setRange(config.WALLPAPER_ALPHA_MIN, config.WALLPAPER_ALPHA_MAX)
        self._alpha.setValue(alpha)
        self._alpha.valueChanged.connect(self.wallpaper_alpha_changed.emit)
        alpha_row.addWidget(alpha_cap)
        alpha_row.addWidget(self._alpha, 1)
        lay.addLayout(alpha_row)

        row = QHBoxLayout()
        ok = QPushButton("Wear it")
        ok.setProperty("accent", True)
        ok.clicked.connect(self._commit)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        row.addWidget(ok, 1)
        row.addWidget(cancel)
        lay.addLayout(row)

    # --- internals ---

    def _trial(self, key: str) -> None:
        self._current = key
        for k, card in self._cards.items():
            card.setChecked(k == key)
        self.style_trial.emit(key)

    def _commit(self) -> None:
        self.saved = True
        self.style_chosen.emit(self._current)
        self.accept()

    def _pick_image(self) -> None:
        path, _filter = QFileDialog.getOpenFileName(
            self, "Choose a background image", "",
            "Images (*.png *.jpg *.jpeg *.webp *.bmp *.gif);;All files (*)",
        )
        if path:
            self.background_picked.emit(path)


class DiagnosticsDialog(QDialog):
    """🩺 The health page: the diagnostics report, read-only, copyable.

    A modest modeless dialog — the report arrives as a ready-made
    string from hearth.diagnostics, this shell just paints it in a
    monospace pane and hands the listener a clipboard button.
    """

    def __init__(self, report: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("🩺 Hearth diagnostics")
        self.setMinimumSize(560, 460)
        lay = QVBoxLayout(self)
        self._text = QPlainTextEdit()
        self._text.setReadOnly(True)
        self._text.setPlainText(report)
        mono = QFont("Consolas")
        mono.setStyleHint(QFont.StyleHint.Monospace)
        mono.setPointSize(10)
        self._text.setFont(mono)
        lay.addWidget(self._text, 1)
        row = QHBoxLayout()
        row.addStretch(1)
        copy_btn = QPushButton("📋 Copy")
        copy_btn.setProperty("accent", True)
        copy_btn.setToolTip("Copy the whole report to the clipboard")
        copy_btn.clicked.connect(self._copy)
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        row.addWidget(copy_btn)
        row.addWidget(close_btn)
        lay.addLayout(row)

    def _copy(self) -> None:
        QApplication.clipboard().setText(self._text.toPlainText())


class MainWindow(QMainWindow):
    """Hearth, grown up: navigation, shelves, lists, and a real transport."""

    search_submitted = pyqtSignal(str)
    search_scoped = pyqtSignal(str, str)          # query, scope
    album_opened = pyqtSignal(object)             # Album — open its page
    artist_opened = pyqtSignal(object)            # Track | Artist | Album — artist page
    track_picked = pyqtSignal(object)             # single card pick
    playlist_picked = pyqtSignal(list, int)       # play list from index
    play_next_requested = pyqtSignal(object)      # insert at queue head
    enqueue_requested = pyqtSignal(object)        # append to queue
    pin_toggled = pyqtSignal(object)              # Track
    queue_remove_requested = pyqtSignal(int)
    queue_reorder_requested = pyqtSignal(list)    # new upcoming order
    queue_jump_requested = pyqtSignal(int)        # upcoming index to play now
    queue_clear_requested = pyqtSignal()
    radio_requested = pyqtSignal(object)          # Track | None (None = current)
    rate_cycled = pyqtSignal()
    sleep_requested = pyqtSignal(int)             # minutes; 0 = off
    mute_toggled = pyqtSignal()
    home_refresh_requested = pyqtSignal()
    library_refresh_requested = pyqtSignal()
    discover_refresh_requested = pyqtSignal()
    discover_category_selected = pyqtSignal(str)     # mood/genre params
    discover_collection_opened = pyqtSignal(object)  # Collection | Album
    discover_charts_requested = pyqtSignal()
    discover_explore_requested = pyqtSignal(str)     # new_releases|trending|new_videos
    discover_enqueue_all_requested = pyqtSignal(list)  # queue a whole curated list
    world_station_requested = pyqtSignal(object)     # world.Genre — tune a station
    style_closet_requested = pyqtSignal()            # open the style closet
    local_add_folder_requested = pyqtSignal()        # 📂 pick a folder to scan
    local_rescan_requested = pyqtSignal()            # 🔄 rescan remembered roots
    glow_mix_requested = pyqtSignal()                # ✨ one-tap Glow Mix ritual
    remote_requested = pyqtSignal()                  # 📱 open the phone remote
    play_pause_requested = pyqtSignal()
    next_requested = pyqtSignal()
    prev_requested = pyqtSignal()
    shuffle_requested = pyqtSignal()
    repeat_requested = pyqtSignal()
    volume_changed = pyqtSignal(float)
    seek_requested = pyqtSignal(int)

    VIEWS = ("home", "discover", "world", "search", "library", "local",
             "now", "stats", "history")

    def __init__(self, palette_key: str | None = None,
                 store: HearthStore | None = None):
        super().__init__()
        self._palette = get_palette(palette_key)
        self.store = store
        self.setWindowTitle(f"🔥 {config.APP_NAME} — {config.APP_TAGLINE}")
        self.resize(config.WINDOW_WIDTH, config.WINDOW_HEIGHT)

        self.home_view = HomeView(self._palette)
        self.discover_view = DiscoverView(self._palette)
        self.world_view = WorldView(self._palette)
        self.search_view = SearchView(self._palette)
        self.library_view = LibraryView(self._palette)
        self.local_view = LocalView(self._palette)     # scanned local files
        self.now_view = NowView(self._palette)
        self.album_view = AlbumView(self._palette)
        self.remote_playlist_view = RemotePlaylistView(self._palette)
        self.artist_view = ArtistView(self._palette)
        self.theater_view = TheaterView(self._palette)   # full-screen stage
        self.stats_view = StatsView(self._palette, store=store)  # memory page
        self.history_view = HistoryView(self._palette, store=store)  # 🕘 day jumps

        self.stack = QStackedWidget()
        for view in (self.home_view, self.discover_view, self.world_view,
                     self.search_view, self.library_view, self.local_view,
                     self.now_view, self.stats_view, self.history_view,
                     self.album_view, self.remote_playlist_view,
                     self.artist_view):
            self.stack.addWidget(view)

        self.player_bar = PlayerBar(self._palette)
        self._build_queue_dock()

        central = QWidget()
        outer = QVBoxLayout(central)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        body.addWidget(self._build_sidebar())
        body.addWidget(self.stack, 1)
        outer.addLayout(body, 1)
        outer.addWidget(self.player_bar)
        self.setCentralWidget(central)

        # wallpaper engine: a translucent skin poured over a user image.
        # the label lives under every sibling but above the QSS canvas.
        self._wallpaper: QPixmap | None = None
        self._wallpaper_path: str | None = None
        self._bg_label = QLabel(self)
        self._bg_label.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._bg_label.hide()

        self.setStyleSheet(build_stylesheet(self._palette))
        self._wire_internal()
        self._install_shortcuts()
        self.theater_view.exit_requested.connect(self.toggle_theater)
        self.show_view("home")

    # --- construction bits ---

    def _build_sidebar(self) -> QWidget:
        side = QWidget()
        side.setProperty("sidebar", True)
        side.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        side.setFixedWidth(config.SIDEBAR_WIDTH)
        lay = QVBoxLayout(side)
        lay.setContentsMargins(14, 18, 14, 14)
        lay.setSpacing(6)
        wordmark = QLabel("🔥 Hearth")
        wordmark.setProperty("hero", True)
        lay.addWidget(wordmark)
        tagline = QLabel(config.APP_TAGLINE)
        tagline.setProperty("kicker", True)
        lay.addWidget(tagline)
        lay.addSpacing(10)

        self._nav: dict[str, QPushButton] = {}
        for key, label in (("home", "🏠 Home"), ("discover", "🧭 Discover"),
                           ("world", "🗺️ World"), ("search", "🔍 Search"),
                           ("library", "📚 Your Library"),
                           ("local", "📁 Local"),
                           ("now", "🎧 Now Playing"),
                           ("stats", "📊 Stats"),
                           ("history", "🕘 History")):
            btn = QPushButton(label)
            btn.setProperty("nav", True)
            btn.setCheckable(True)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda _=False, k=key: self.show_view(k))
            self._nav[key] = btn
            lay.addWidget(btn)

        # Theater is an action, not a stack page: full-screen over everything.
        if config.THEATER_ENABLED:
            theater_btn = QPushButton("🎭 Theater")
            theater_btn.setProperty("nav", True)
            theater_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            theater_btn.clicked.connect(lambda _=False: self.toggle_theater())
            lay.addWidget(theater_btn)

        head = QHBoxLayout()
        cap = QLabel("PLAYLISTS")
        cap.setProperty("dim", True)
        add = QPushButton("＋")
        add.setProperty("flat", True)
        add.setFixedWidth(30)
        add.setCursor(Qt.CursorShape.PointingHandCursor)
        add.clicked.connect(self._new_playlist_dialog)
        imp = QPushButton("⬆")
        imp.setProperty("flat", True)
        imp.setFixedWidth(30)
        imp.setToolTip("Import playlists (JSON)")
        imp.clicked.connect(self._import_playlists)
        head.addWidget(cap)
        head.addStretch(1)
        closet_btn = QPushButton("🪞")
        closet_btn.setProperty("flat", True)
        closet_btn.setFixedWidth(30)
        closet_btn.setToolTip("Style closet — glass looks, wallpapers")
        closet_btn.clicked.connect(self.style_closet_requested.emit)
        head.addWidget(closet_btn)
        accent_btn = QPushButton("🎨")
        accent_btn.setProperty("flat", True)
        accent_btn.setFixedWidth(30)
        accent_btn.setToolTip("Accent colors (live preview)")
        accent_btn.clicked.connect(self._open_accent_picker)
        head.addWidget(accent_btn)
        remote_btn = QPushButton("📱")
        remote_btn.setProperty("flat", True)
        remote_btn.setFixedWidth(30)
        remote_btn.setToolTip("Phone remote — control Hearth from any browser")
        remote_btn.clicked.connect(lambda _=False: self.remote_requested.emit())
        head.addWidget(remote_btn)
        head.addWidget(imp)
        head.addWidget(add)
        lay.addSpacing(12)
        lay.addLayout(head)

        self._playlist_list = QListWidget()
        self._playlist_list.setProperty("sidebar", True)
        self._playlist_list.itemDoubleClicked.connect(self._open_playlist_item)
        self._playlist_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._playlist_list.customContextMenuRequested.connect(self._playlist_menu)
        lay.addWidget(self._playlist_list, 1)
        return side

    def _build_queue_dock(self) -> None:
        from PyQt6.QtWidgets import QDockWidget

        self.queue_dock = QDockWidget("Up next", self)
        self.queue_dock.setAllowedAreas(
            Qt.DockWidgetArea.RightDockWidgetArea | Qt.DockWidgetArea.LeftDockWidgetArea
        )
        body = QWidget()
        body_lay = QVBoxLayout(body)
        body_lay.setContentsMargins(0, 0, 0, 0)
        body_lay.setSpacing(2)
        tools = QHBoxLayout()
        tools.addStretch(1)
        clear_btn = QPushButton("Clear")
        clear_btn.setProperty("flat", True)
        clear_btn.setToolTip("Remove every upcoming track")
        clear_btn.clicked.connect(self.queue_clear_requested.emit)
        tools.addWidget(clear_btn)
        body_lay.addLayout(tools)
        self._queue_list = QListWidget()
        self._queue_list.setProperty("rows", True)
        self._queue_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._queue_list.customContextMenuRequested.connect(self._queue_menu)
        # drag & drop reordering (current row is pinned, the rest move freely)
        self._queue_list.setDragDropMode(
            QAbstractItemView.DragDropMode.InternalMove
        )
        self._queue_list.setDefaultDropAction(Qt.DropAction.MoveAction)
        self._queue_list.model().rowsMoved.connect(self._on_queue_rows_moved)
        self._queue_list.itemDoubleClicked.connect(
            lambda item: self._queue_jump_from_row(self._queue_list.row(item))
        )
        body_lay.addWidget(self._queue_list, 1)
        self.queue_dock.setWidget(body)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.queue_dock)
        self.queue_dock.hide()
        self.resizeDocks([self.queue_dock], [config.QUEUE_WIDTH], Qt.Orientation.Horizontal)

    def _wire_internal(self) -> None:
        for shelf_name in ("Quick picks", "Top tracks", "Pinned favorites",
                           "Recently played", "Most played", "Recently loved",
                           "Rare gems", "🔌 Plugins"):
            self.home_view.shelf(shelf_name).card_picked.connect(
                lambda t, ctx: self.playlist_picked.emit(list(ctx), list(ctx).index(t))
            )
        self.search_view.search_submitted.connect(self.search_submitted.emit)
        self.search_view.search_scoped.connect(self.search_scoped.emit)
        self.search_view.album_opened.connect(self.album_opened.emit)
        self.search_view.track_activated.connect(
            lambda t, ctx: self.playlist_picked.emit(list(ctx), list(ctx).index(t))
        )
        self.album_view.track_activated.connect(
            lambda t, ctx: self.playlist_picked.emit(list(ctx), list(ctx).index(t))
        )
        self.album_view.play_all_requested.connect(self.playlist_picked.emit)
        self.album_view.shuffle_requested_sig.connect(
            lambda tracks: self.playlist_picked.emit(list(tracks), 0)
        )
        self.album_view.menu_requested.connect(self._track_menu)
        d = self.discover_view
        d.category_selected.connect(self.discover_category_selected.emit)
        d.collection_opened.connect(self.discover_collection_opened.emit)
        d.charts_requested.connect(self.discover_charts_requested.emit)
        d.explore_requested.connect(self.discover_explore_requested.emit)
        self.world_view.station_requested.connect(self.world_station_requested.emit)
        d.track_activated.connect(
            lambda t, ctx: self.playlist_picked.emit(list(ctx), list(ctx).index(t))
        )
        d.menu_requested.connect(self._track_menu)
        self.remote_playlist_view.track_activated.connect(
            lambda t, ctx: self.playlist_picked.emit(list(ctx), list(ctx).index(t))
        )
        self.remote_playlist_view.play_all_requested.connect(self.playlist_picked.emit)
        self.remote_playlist_view.shuffle_requested_sig.connect(
            lambda tracks: self.playlist_picked.emit(list(tracks), 0)
        )
        self.remote_playlist_view.menu_requested.connect(self._track_menu)
        self.remote_playlist_view.enqueue_all_requested.connect(
            self.discover_enqueue_all_requested.emit
        )
        self.library_view.track_activated.connect(
            lambda t, ctx: self.playlist_picked.emit(list(ctx), list(ctx).index(t))
        )
        self.library_view.playlist_opened.connect(self.open_playlist)
        self.library_view.create_playlist_requested.connect(self._new_playlist_dialog)
        self.local_view.track_activated.connect(
            lambda t, ctx: self.playlist_picked.emit(list(ctx), list(ctx).index(t))
        )
        self.local_view.menu_requested.connect(self._track_menu)
        self.stats_view.track_activated.connect(
            lambda t, ctx: self.playlist_picked.emit(list(ctx), list(ctx).index(t))
        )
        self.history_view.track_activated.connect(
            lambda t, ctx: self.playlist_picked.emit(list(ctx), list(ctx).index(t))
        )
        self.history_view.menu_requested.connect(self._track_menu)
        # drive-by fix (31-c5b gap): the Local view's buttons speak view-local
        # signal names — relay them onto the MainWindow signals the app hears
        self.local_view.add_folder_requested.connect(
            self.local_add_folder_requested.emit)
        self.local_view.rescan_requested.connect(
            self.local_rescan_requested.emit)
        self.home_view.glow_mix_requested.connect(self.glow_mix_requested.emit)
        self.library_view.import_requested.connect(self._import_files_dialog)
        for view in (self.search_view, self.library_view._recent):
            view.menu_requested.connect(self._track_menu)
        self.player_bar.play_pause_requested.connect(self.play_pause_requested.emit)
        self.player_bar.next_requested.connect(self.next_requested.emit)
        self.player_bar.prev_requested.connect(self.prev_requested.emit)
        self.player_bar.shuffle_requested.connect(self.shuffle_requested.emit)
        self.player_bar.repeat_requested.connect(self.repeat_requested.emit)
        self.player_bar.volume_changed.connect(self.volume_changed.emit)
        self.player_bar.seek_requested.connect(self.seek_requested.emit)
        self.player_bar.pin_toggled.connect(self._on_pin_clicked)
        self.player_bar.queue_toggled.connect(self.toggle_queue)
        self.player_bar.lyrics_toggled.connect(lambda: self.show_view("now"))
        self.player_bar.radio_requested.connect(
            lambda: self.radio_requested.emit(None)
        )
        self.player_bar.rate_cycled.connect(self.rate_cycled.emit)
        self.player_bar.sleep_requested.connect(self.sleep_requested.emit)
        self.now_view.pin_toggled.connect(self._on_pin_clicked)
        self.now_view.radio_requested.connect(
            lambda: self.radio_requested.emit(None)
        )
        self.now_view.lyrics_seek_requested.connect(self.seek_requested.emit)
        av = self.artist_view
        av.track_activated.connect(
            lambda t, ctx: self.playlist_picked.emit(list(ctx), list(ctx).index(t))
        )
        av.play_all_requested.connect(self.playlist_picked.emit)
        av.shuffle_requested_sig.connect(
            lambda tracks: self.playlist_picked.emit(list(tracks), 0)
        )
        av.menu_requested.connect(self._track_menu)
        av.album_opened.connect(self.album_opened.emit)
        av.artist_opened.connect(self.artist_opened.emit)

    # --- navigation ---

    def show_view(self, name: str) -> None:
        if name not in self.VIEWS:
            return
        index = self.VIEWS.index(name)
        self.stack.setCurrentIndex(index)
        current = self.stack.currentWidget()
        if current is not None:
            fade_in(current, ms=200)   # the stage crossfades in
        for key, btn in self._nav.items():
            btn.setChecked(key == name)
        if name == "home":
            self.home_refresh_requested.emit()
        elif name == "library":
            self.library_refresh_requested.emit()
        elif name == "discover":
            self.discover_refresh_requested.emit()
        elif name == "search":
            self.search_view._box.setFocus()
        elif name == "stats":
            self.stats_view.refresh()
        elif name == "history":
            self.history_view.refresh()

    def focus_search(self) -> None:
        self.show_view("search")

    # --- home / library data ---

    def set_home_shelf(self, name: str, tracks: list[Track]) -> None:
        self.home_view.set_shelf(name, tracks)

    def set_top_tracks(self, tracks: list[Track]) -> None:
        self.home_view.set_shelf("Top tracks", list(tracks))

    def show_album_results(self, albums: list[Album]) -> None:
        self.search_view.set_albums(list(albums))

    def open_album(self, album: Album, tracks: list[Track]) -> None:
        self.album_view.set_header(f"💿 {album.title}")
        self.album_view.set_tracks(list(tracks))
        self.stack.setCurrentWidget(self.album_view)
        for key, btn in self._nav.items():
            btn.setChecked(key == "search")   # albums arrive from Search

    def open_artist(self, artist: Artist) -> None:
        """An artist's stage: face, top tracks, releases, kindred acts."""
        self.artist_view.set_artist(artist)
        self.stack.setCurrentWidget(self.artist_view)

    def open_remote_playlist(self, title: str, tracks: list[Track]) -> None:
        """A curated Discover playlist, opened as a full page."""
        self.remote_playlist_view.set_header(f"🎧 {title}")
        self.remote_playlist_view.set_tracks(list(tracks))
        self.stack.setCurrentWidget(self.remote_playlist_view)
        for key, btn in self._nav.items():
            btn.setChecked(key == "discover")   # arrived from Discover

    # --- keyboard shortcuts (text-field safe) ---

    def _install_shortcuts(self) -> None:
        """Window keys: guarded so typing in the search box never triggers them."""
        entry_widgets = (QLineEdit, QTextEdit, QPlainTextEdit)

        def typing() -> bool:
            return isinstance(QApplication.focusWidget(), entry_widgets)

        def bind(chord: str, handler) -> None:
            shortcut = QShortcut(QKeySequence(chord), self)
            shortcut.activated.connect(
                lambda: None if typing() else handler()
            )

        bind("Space", self.play_pause_requested.emit)
        bind("M", self.mute_toggled.emit)
        bind("S", self.shuffle_requested.emit)
        bind("R", self.repeat_requested.emit)
        bind("N", lambda: self.show_view("now"))
        bind("Q", self.toggle_queue)
        bind("/", self.focus_search)

        def seek_by(step_ms: int) -> None:
            self.seek_requested.emit(
                max(0, self.player_bar._seek.value() + step_ms)
            )

        def volume_by(step: int) -> None:
            value = self.player_bar._volume.value() + step
            self.volume_changed.emit(max(0, min(100, value)) / 100.0)

        bind("Right", lambda: seek_by(config.SEEK_STEP_MS))
        bind("Left", lambda: seek_by(-config.SEEK_STEP_MS))
        bind("Up", lambda: volume_by(int(config.VOLUME_STEP * 100)))
        bind("Down", lambda: volume_by(-int(config.VOLUME_STEP * 100)))

    def set_favorites(self, tracks: list[Track]) -> None:
        self.library_view.set_favorites(tracks)
        self.home_view.set_shelf("Pinned favorites", tracks)

    def set_recent(self, tracks: list[Track]) -> None:
        self.library_view.set_recent(tracks)
        self.home_view.set_shelf("Recently played", tracks)

    def set_on_repeat(self, tracks: list[Track]) -> None:
        self.home_view.set_shelf("On Repeat", tracks)

    def set_smart_shelves(
        self,
        most_played: list[Track],
        recently_loved: list[Track],
        rare_gems: list[Track],
    ) -> None:
        """The three auto-refreshing smart shelves (v0.7.1)."""
        self.home_view.set_shelf("Most played", list(most_played))
        self.home_view.set_shelf("Recently loved", list(recently_loved))
        self.home_view.set_shelf("Rare gems", list(rare_gems))

    def set_local_tracks(self, tracks: list[Track]) -> None:
        self.local_view.set_tracks(list(tracks))

    # --- playlists ---

    def refresh_playlists(self) -> None:
        self._playlist_list.clear()
        if self.store is None:
            return
        for pid, name, count in self.store.playlists():
            item = QListWidgetItem(f"♪ {name}  ·  {count}")
            item.setData(Qt.ItemDataRole.UserRole, pid)
            self._playlist_list.addItem(item)

    def _new_playlist_dialog(self) -> None:
        name, ok = QInputDialog.getText(self, "New playlist", "Playlist name:")
        if not ok or not name.strip():
            return
        if self.store is not None:
            self.store.create_playlist(name)
        self.refresh_playlists()

    def _open_playlist_item(self, item: QListWidgetItem) -> None:
        pid = item.data(Qt.ItemDataRole.UserRole)
        if pid is not None:
            self.open_playlist(int(pid))

    def open_playlist(self, playlist_id: int) -> None:
        if self.store is None:
            return
        name = self.store.playlist_name(playlist_id)
        if name is None:
            return
        existing = self.findChild(PlaylistView, f"playlist-{playlist_id}")
        if existing is None:
            view = PlaylistView(self._palette, playlist_id, name)
            view.setObjectName(f"playlist-{playlist_id}")
            view.track_activated.connect(
                lambda t, ctx: self.playlist_picked.emit(list(ctx), list(ctx).index(t))
            )
            view.play_all_requested.connect(self.playlist_picked.emit)
            view.shuffle_requested_sig.connect(
                lambda tracks: self.playlist_picked.emit(list(tracks), 0)
            )
            view.rename_requested.connect(self._rename_playlist)
            view.delete_requested.connect(self._delete_playlist)
            view.menu_requested.connect(self._playlist_track_menu)
            self.stack.addWidget(view)
        existing = self.findChild(PlaylistView, f"playlist-{playlist_id}")
        assert existing is not None
        existing.set_header(f"📁 {self.store.playlist_name(playlist_id) or name}")
        existing.set_tracks(self.store.playlist_tracks(playlist_id))
        self.stack.setCurrentWidget(existing)

    def _rename_playlist(self, playlist_id: int) -> None:
        if self.store is None:
            return
        current = self.store.playlist_name(playlist_id) or ""
        name, ok = QInputDialog.getText(self, "Rename playlist", "New name:", text=current)
        if not ok or not name.strip():
            return
        self.store.rename_playlist(playlist_id, name)
        self.refresh_playlists()
        self.open_playlist(playlist_id)

    def _delete_playlist(self, playlist_id: int) -> None:
        if self.store is None:
            return
        confirm, ok = QInputDialog.getText(
            self, "Delete playlist", "Type DELETE to confirm:"
        )
        if not ok or confirm.strip().upper() != "DELETE":
            return
        self.store.delete_playlist(playlist_id)
        view = self.findChild(PlaylistView, f"playlist-{playlist_id}")
        if view is not None:
            self.stack.removeWidget(view)
            view.deleteLater()
        self.refresh_playlists()
        self.show_view("library")

    # --- context menus ---

    def _track_menu(self, track: Track, menu: QMenu) -> None:
        play_next = menu.addAction("▶ Play next")
        enqueue = menu.addAction("➕ Add to queue")
        radio = menu.addAction("📻 Start radio")
        artist_page = menu.addAction("🎤 Artist page")
        copy_link = menu.addAction("🔗 Copy YouTube link")
        menu.addSeparator()
        pinned = self.store.is_pinned(track.video_id) if self.store else False
        pin = menu.addAction("♥ Unpin" if pinned else "♡ Pin to favorites")
        menu.addSeparator()
        playlists_menu = menu.addMenu("📌 Add to playlist")
        if self.store is not None:
            for pid, name, _count in self.store.playlists():
                playlists_menu.addAction(name).setData(pid)
            playlists_menu.addSeparator()
            new_act = playlists_menu.addAction("＋ New playlist…")
            new_act.setData(-1)

        def _add_to(playlist_id: int) -> None:
            if playlist_id == -1:
                name, ok = QInputDialog.getText(self, "New playlist", "Playlist name:")
                if not ok or not name.strip() or self.store is None:
                    return
                playlist_id = self.store.create_playlist(name)
                self.refresh_playlists()
            if self.store is not None and self.store.add_to_playlist(playlist_id, track):
                self.refresh_playlists()

        play_next.triggered.connect(lambda: self.play_next_requested.emit(track))
        enqueue.triggered.connect(lambda: self.enqueue_requested.emit(track))
        radio.triggered.connect(lambda: self.radio_requested.emit(track))
        artist_page.triggered.connect(lambda: self.artist_opened.emit(track))
        copy_link.triggered.connect(
            lambda: QApplication.clipboard().setText(
                f"https://www.youtube.com/watch?v={track.video_id}"
            )
        )
        pin.triggered.connect(lambda: self.pin_toggled.emit(track))
        playlists_menu.triggered.connect(
            lambda act: _add_to(int(act.data()) if act.data() is not None else -1)
        )

    def _playlist_track_menu(self, track: Track, menu: QMenu) -> None:
        view = self.sender()
        if isinstance(view, PlaylistView):
            remove = menu.addAction("✕ Remove from this playlist")
            remove.triggered.connect(
                lambda: (self.store.remove_from_playlist(view.playlist_id, track.video_id),
                         self.open_playlist(view.playlist_id),
                         self.refresh_playlists())
            )
            menu.addSeparator()

    def _playlist_menu(self, pos) -> None:
        item = self._playlist_list.itemAt(pos)
        if item is None:
            return
        menu = self._build_playlist_menu(int(item.data(Qt.ItemDataRole.UserRole)))
        menu.exec(self._playlist_list.viewport().mapToGlobal(pos))

    def _build_playlist_menu(self, playlist_id: int) -> QMenu:
        """The sidebar playlist row's menu, built standalone (so the actions
        and their wiring stay testable without a blocking exec)."""
        menu = QMenu(self)
        open_act = menu.addAction("Open")
        export_share = menu.addAction("⬆ Export…")              # hearth share format
        export_all = menu.addAction("📤 Export all (JSON)…")    # every playlist
        export_m3u = menu.addAction("📤 Export M3U…")           # this playlist
        rename_act = menu.addAction("Rename")
        delete_act = menu.addAction("Delete")
        open_act.triggered.connect(lambda: self.open_playlist(playlist_id))
        export_share.triggered.connect(
            lambda: self._export_playlist(playlist_id))
        export_all.triggered.connect(
            lambda: self._export_all_playlists(playlist_id))
        export_m3u.triggered.connect(
            lambda: self._export_playlist_m3u(playlist_id))
        rename_act.triggered.connect(lambda: self._rename_playlist(playlist_id))
        delete_act.triggered.connect(lambda: self._delete_playlist(playlist_id))
        return menu

    # --- playlist share (export / import) ---

    def _export_playlist(self, playlist_id: int) -> None:
        if self.store is None:
            return
        name = self.store.playlist_name(playlist_id)
        if name is None:
            return
        tracks = self.store.playlist_tracks(playlist_id)
        path, _filter = QFileDialog.getSaveFileName(
            self, "Export playlist",
            f"{name}{config.PLAYLIST_SUFFIX}",
            "Hearth playlist (*.json);;All files (*)",
        )
        if not path:
            return
        payload = json.dumps(share.encode_playlist(name, tracks), ensure_ascii=False, indent=2)
        try:
            Path(path).write_text(payload, encoding="utf-8")
        except OSError:
            self.set_status(f"Could not write {path}")
            return
        self.set_status(f"Exported {len(tracks)} tracks → {path}")

    def _import_playlists(self) -> None:
        if self.store is None:
            return
        path, _filter = QFileDialog.getOpenFileName(
            self, "Import playlists", "",
            "Hearth playlist (*.json);;All files (*)",
        )
        if not path:
            return
        try:
            text = Path(path).read_text(encoding="utf-8")
        except OSError:
            self.set_status(f"Could not read {path}")
            return
        imported = share.decode_playlists_text(text)
        if not imported:
            self.set_status("No playlists found in that file")
            return
        for name, tracks in imported:
            pid = self.store.create_playlist(name)
            for track in tracks:
                self.store.add_to_playlist(pid, track)
        self.refresh_playlists()
        self.set_status(f"Imported {len(imported)} playlist(s) from {path}")

    # --- playlist export / import (storage-backed: JSON for everything, M3U per list) ---

    def _export_all_playlists(self, _playlist_id: int = 0) -> None:
        """📤 Every playlist as one portable JSON (asks where first)."""
        if self.store is None:
            return
        path, _filter = QFileDialog.getSaveFileName(
            self, "Export all playlists (JSON)",
            "hearth-playlists.json",
            "JSON (*.json);;All files (*)",
        )
        if not path:
            return
        self._export_all_playlists_to(path)

    def _export_all_playlists_to(self, path: str) -> bool:
        """Write the all-playlists JSON to `path` (tests call this directly)."""
        if self.store is None:
            return False
        try:
            ok = bool(self.store.export_playlists(path))
        except Exception:   # noqa: BLE001 - storage is safe, but belt & braces
            ok = False
        if ok:
            self.set_status(
                f"📤 Exported {len(self.store.playlists())} playlist(s) → {path}")
        else:
            self.set_status(f"Could not write {path}")
        return ok

    def _export_playlist_m3u(self, playlist_id: int) -> None:
        """📤 One playlist as a standard M3U (asks where first)."""
        if self.store is None:
            return
        name = self.store.playlist_name(playlist_id) or "playlist"
        path, _filter = QFileDialog.getSaveFileName(
            self, "Export playlist as M3U",
            f"{name}.m3u",
            "M3U playlist (*.m3u *.m3u8);;All files (*)",
        )
        if not path:
            return
        self._export_playlist_m3u_to(playlist_id, path)

    def _export_playlist_m3u_to(self, playlist_id: int, path: str) -> bool:
        """Write one playlist's M3U to `path` (tests call this directly)."""
        if self.store is None:
            return False
        try:
            ok = bool(self.store.export_m3u(playlist_id, path))
        except Exception:   # noqa: BLE001 - never raise out of a menu handler
            ok = False
        if ok:
            self.set_status(f"📤 Exported M3U → {path}")
        else:
            self.set_status("Could not export that playlist as M3U")
        return ok

    def _import_files_dialog(self) -> None:
        """📥 Pick a .json / .m3u file and hand it to the importer."""
        if self.store is None:
            return
        path, _filter = QFileDialog.getOpenFileName(
            self, "Import playlists", "",
            "Playlists (*.json *.m3u *.m3u8);;All files (*)",
        )
        if not path:
            return
        self._import_playlist_file(path)

    def _import_playlist_file(self, path: str) -> str:
        """Import by extension: JSON playlists / M3U (file stem names it).

        Returns the status note (tests drive this directly, bypassing the
        dialog). Bad files produce a note, never a crash, and the sidebar
        playlist list always refreshes.
        """
        if self.store is None:
            return "no library to import into"
        suffix = Path(path).suffix.lower()
        try:
            if suffix == ".json":
                imported = self.store.import_playlists(path)
                note = (
                    f"📥 Imported {imported} playlist(s) from {Path(path).name}"
                    if imported
                    else "No playlists in that file — is it a hearth export?"
                )
            elif suffix in (".m3u", ".m3u8"):
                added = self.store.import_m3u(path, Path(path).stem)
                note = (
                    f"📥 Imported {added} tracks into “{Path(path).stem}”"
                    if added
                    else "No playable entries in that M3U"
                )
            else:
                note = "Unsupported playlist file — use .json or .m3u"
        except Exception:   # noqa: BLE001 - a hostile file must stay boring
            note = "That file could not be imported"
        self.refresh_playlists()
        self.set_status(note)
        return note

    def _queue_menu(self, pos) -> None:
        item = self._queue_list.itemAt(pos)
        if item is None:
            return
        row = self._queue_list.row(item)
        kind = item.data(Qt.ItemDataRole.UserRole + 1)
        menu = QMenu(self)
        play_now = None
        move_up = None
        move_down = None
        if kind == "upcoming":
            play_now = menu.addAction("▶ Play now")
            move_up = menu.addAction("↑ Move up")
            move_down = menu.addAction("↓ Move down")
            menu.addSeparator()
            remove = menu.addAction("✕ Remove from queue")
        else:
            remove = menu.addAction("✕ Remove from queue")
            remove.setEnabled(False)   # the playing row isn't in `upcoming`
        chosen = menu.exec(self._queue_list.viewport().mapToGlobal(pos))
        if chosen is None:
            return
        if chosen is play_now:
            self.queue_jump_requested.emit(row - 1)   # upcoming index
        elif chosen is move_up:
            self._queue_swap(row - 1, row - 2)
        elif chosen is move_down:
            self._queue_swap(row - 1, row)
        elif chosen is remove and kind == "upcoming":
            self.queue_remove_requested.emit(row - 1)

    def _queue_jump_from_row(self, row: int) -> None:
        item = self._queue_list.item(row) if row >= 0 else None
        if item is None or item.data(Qt.ItemDataRole.UserRole + 1) != "upcoming":
            return
        self.queue_jump_requested.emit(row - 1)

    def _queue_swap(self, i: int, j: int) -> None:
        """Swap upcoming positions via the reorder signal (engine owns truth)."""
        item_i = self._queue_list.item(i + 1)
        item_j = self._queue_list.item(j + 1)
        if item_i is None or item_j is None:
            return
        order = []
        for row in range(1, self._queue_list.count()):
            track = self._queue_list.item(row).data(Qt.ItemDataRole.UserRole)
            if track is not None:
                order.append(track)
        if 0 <= i < len(order) and 0 <= j < len(order):
            order[i], order[j] = order[j], order[i]
            self.queue_reorder_requested.emit(order)

    # --- queue dock ---

    def toggle_queue(self) -> None:
        self.queue_dock.setVisible(not self.queue_dock.isVisible())

    def set_queue(self, upcoming: list[Track], current: Track | None = None) -> None:
        self._queue_list.clear()
        if current is not None:
            row = TrackRow(self._palette, current, 0)
            row._title.setText(f"▶ {current.title}")
            item = QListWidgetItem()
            item.setSizeHint(row.sizeHint())
            item.setData(Qt.ItemDataRole.UserRole, current)
            item.setData(Qt.ItemDataRole.UserRole + 1, "current")
            # the playing row is pinned — only upcoming tracks reorder
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsDragEnabled)
            self._queue_list.addItem(item)
            self._queue_list.setItemWidget(item, row)
        for index, track in enumerate(upcoming, start=1):
            item = QListWidgetItem()
            item.setSizeHint(TrackRow(self._palette, track, index).sizeHint())
            item.setData(Qt.ItemDataRole.UserRole, track)
            item.setData(Qt.ItemDataRole.UserRole + 1, "upcoming")
            self._queue_list.addItem(item)
            self._queue_list.setItemWidget(
                item, TrackRow(self._palette, track, index)
            )

    def _on_queue_rows_moved(self, *_args) -> None:
        """Drag & drop finished: read back the new upcoming order."""
        reordered: list[Track] = []
        for row in range(self._queue_list.count()):
            item = self._queue_list.item(row)
            if item.data(Qt.ItemDataRole.UserRole + 1) == "upcoming":
                track = item.data(Qt.ItemDataRole.UserRole)
                if track is not None:
                    reordered.append(track)
        if reordered:
            self.queue_reorder_requested.emit(reordered)

    # --- pin ---

    def _on_pin_clicked(self) -> None:
        track = self.player_bar.current_track
        if track is not None:
            self.pin_toggled.emit(track)

    # --- panel-compatible state API ---

    def set_track(self, track: Track | None) -> None:
        self.player_bar.set_track(track)
        self.now_view.set_track(track)
        self.theater_view.set_track(track)
        if track is None:
            self.setWindowTitle(f"🔥 {config.APP_NAME} — {config.APP_TAGLINE}")
        else:
            self.setWindowTitle(f"▶ {track.display_name} — 🔥 {config.APP_NAME}")

    def set_pinned(self, pinned: bool) -> None:
        self.player_bar.set_pinned(pinned)
        self.now_view.set_pinned(pinned)

    def set_playing(self, playing: bool) -> None:
        self.player_bar.set_playing(playing)

    def set_status(self, text: str) -> None:
        self.player_bar.set_status(text)

    def set_duration(self, duration_ms: int) -> None:
        self.player_bar.set_duration(duration_ms)

    def set_position(self, position_ms: int) -> None:
        self.player_bar.set_position(position_ms)
        self.now_view.set_position(position_ms)
        if self.theater_view.isVisible():
            self.theater_view.set_position(position_ms)

    def set_lyrics(self, video_id: str, text: str | None,
                   lines: list[LrcLine] | None = None) -> None:
        """Lyrics land in the Now Playing sheet and the theater at once."""
        self.now_view.set_lyrics(video_id, text, lines)
        self.theater_view.set_lyrics(video_id, text, lines)

    def set_lyrics_font(self, font: QFont, size_key: str, family: str) -> None:
        """Apply + remember the lyrics settings across every lyric surface."""
        self.now_view.set_lyrics_settings(size_key, family)
        self.theater_view.apply_lyrics_font(font)

    def set_crossfade(self, seconds: int) -> None:
        """Restore the persisted crossfade length on the Now Playing row."""
        self.now_view.set_crossfade(seconds)

    def set_volume(self, value: float) -> None:
        self.player_bar.set_volume(value)

    def show_search_results(self, tracks: list[Track]) -> None:
        self.search_view.set_tracks(list(tracks))

    def apply_palette(self, palette: Palette) -> None:
        self._palette = palette
        self.now_view.apply_palette(palette)
        self.player_bar.apply_palette(palette)
        self.theater_view.apply_palette(palette)
        self.stats_view.apply_palette(palette)
        self.setStyleSheet(build_stylesheet(palette))

    # --- wallpaper engine (v0.8.0 style closet) ---

    @property
    def wallpaper_path(self) -> str | None:
        return self._wallpaper_path

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt naming
        """Keep the wallpaper covering the stage as the window breathes."""
        super().resizeEvent(event)
        if self._wallpaper is not None:
            self._fit_wallpaper()

    def set_background_image(self, path: str | None) -> bool:
        """Pour a wallpaper under the UI. False when the image won't load."""
        if not path:
            self._wallpaper = None
            self._wallpaper_path = None
            self._bg_label.hide()
            return True
        img = QImage(path)
        if img.isNull():
            return False
        self._wallpaper_path = str(path)
        self._wallpaper = QPixmap.fromImage(img)
        self._fit_wallpaper()
        self._bg_label.lower()
        self._bg_label.show()
        return True

    def _fit_wallpaper(self) -> None:
        """Cover-crop the original image to the current window rect."""
        if self._wallpaper is None or self._wallpaper.isNull():
            return
        size = self.size()
        if size.width() < 1 or size.height() < 1:
            return
        scaled = self._wallpaper.scaled(
            size,
            Qt.AspectRatioMode.KeepAspectRatioByExpanding,
            Qt.TransformationMode.SmoothTransformation,
        )
        x = max(0, (scaled.width() - size.width()) // 2)
        y = max(0, (scaled.height() - size.height()) // 2)
        self._bg_label.setGeometry(0, 0, size.width(), size.height())
        self._bg_label.setPixmap(
            scaled.copy(x, y, size.width(), size.height()))

    # --- theater mode (v0.8.0) ---

    def toggle_theater(self) -> None:
        """Flip the full-screen Now Playing stage (gated on config)."""
        if not config.THEATER_ENABLED:
            return
        if self.theater_view.isVisible():
            self.theater_view.hide()
            self.show()
            return
        self.theater_view.set_track(self.now_view.current_track)
        self.theater_view.set_cover_pixmap(self.now_view.cover_pixmap())
        self.theater_view.showFullScreen()

    # --- accent picker (v0.8.0) ---

    def _open_accent_picker(self) -> None:
        """Live-tweak the current palette's accents; save as a pack."""
        base = self._palette
        dlg = AccentPickerDialog(base, self)
        dlg.palette_changed.connect(self.apply_palette)
        dlg.pack_saved.connect(
            lambda key: self.set_status(f"Palette pack saved: {key}")
        )

        def _restore_unsaved() -> None:
            if not dlg.saved:
                self.apply_palette(base)

        dlg.finished.connect(_restore_unsaved)
        dlg.exec()

    def summon(self) -> None:
        self.show()
        self.setWindowState(self.windowState() & ~Qt.WindowState.WindowMinimized)
        self.raise_()
        self.activateWindow()
