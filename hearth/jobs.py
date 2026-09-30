"""QRunnable workers on isolated thread pools (search vs load never queue together)."""

from __future__ import annotations

import logging
from typing import Callable

from PyQt6.QtCore import QObject, QRunnable, pyqtSignal

from .catalog import Catalog
from .models import Track
from .stream import resolve_stream_url

log = logging.getLogger(__name__)


class _SignalCarrier(QObject):
    finished = pyqtSignal(object)   # list[Track] or (url, loudness)
    failed = pyqtSignal(str)

    def emit_safe(self, signal, payload) -> None:
        """Emit defensively: the recipient may have closed before we finished."""
        try:
            signal.emit(payload)
        except RuntimeError:
            log.debug("signal carrier gone — recipient closed before job finished")


class SearchJob(QRunnable):
    """Runs on the background pool — heavy catalogue queries (songs)."""

    def __init__(self, catalog: Catalog, query: str, limit: int = 20):
        super().__init__()
        self.setAutoDelete(False)  # lifetime managed by Hearth._jobs, not the pool
        self.signals = _SignalCarrier()
        self.catalog = catalog
        self.query = query
        self.limit = limit

    def run(self) -> None:  # noqa: D102 - QRunnable entry
        from .catalog import parse_video_id

        video_id = parse_video_id(self.query)
        if video_id:
            track = self.catalog.song_details(video_id)
            self.signals.emit_safe(self.signals.finished, [track] if track else [])
        else:
            self.signals.emit_safe(self.signals.finished,
                                   self.catalog.search(self.query, limit=self.limit))


class ScopedSearchJob(QRunnable):
    """Search with a scope tag; emits (scope, tracks|albums)."""

    def __init__(self, catalog: Catalog, query: str, scope: str = "songs",
                 limit: int = 20):
        super().__init__()
        self.setAutoDelete(False)
        self.signals = _SignalCarrier()
        self.catalog = catalog
        self.query = query
        self.scope = scope
        self.limit = limit

    def run(self) -> None:  # noqa: D102
        from .catalog import parse_video_id

        video_id = parse_video_id(self.query)
        if video_id:
            track = self.catalog.song_details(video_id)
            self.signals.emit_safe(self.signals.finished,
                                   ("songs", [track] if track else []))
        else:
            self.signals.emit_safe(
                self.signals.finished,
                self.catalog.scoped_search(self.query, scope=self.scope,
                                           limit=self.limit),
            )


class AlbumJob(QRunnable):
    """Opens an album page; emits (Album, [Track])."""

    def __init__(self, catalog: Catalog, browse_id: str):
        super().__init__()
        self.setAutoDelete(False)
        self.signals = _SignalCarrier()
        self.catalog = catalog
        self.browse_id = browse_id

    def run(self) -> None:  # noqa: D102
        payload = self.catalog.album(self.browse_id)
        if payload is not None:
            self.signals.emit_safe(self.signals.finished, payload)
        else:
            self.signals.emit_safe(self.signals.failed, self.browse_id)


class DiscoverJob(QRunnable):
    """One generic fetcher for every Discover page; emits (kind, payload).

    kind            payload
    ------------    -------------------------------------------------
    moods           list[(section_title, [{title, params}])]
    mood_playlists  list[Collection]
    charts          list[Collection]
    explore         (list[Album], list[Track], list[Track])
    playlist        (title, list[Track]) — or failed for a dead id
    """

    KINDS = ("moods", "mood_playlists", "charts", "explore", "playlist")

    def __init__(self, catalog: Catalog, kind: str, arg=None):
        super().__init__()
        self.setAutoDelete(False)
        self.signals = _SignalCarrier()
        self.catalog = catalog
        self.kind = kind
        self.arg = arg

    def run(self) -> None:  # noqa: D102
        if self.kind == "moods":
            payload = self.catalog.mood_categories()
        elif self.kind == "mood_playlists":
            payload = self.catalog.mood_playlists(self.arg)
        elif self.kind == "charts":
            payload = self.catalog.charts()
        elif self.kind == "explore":
            payload = self.catalog.explore_shelves()
        elif self.kind == "playlist":
            payload = self.catalog.playlist(self.arg)
            if payload is None:
                self.signals.emit_safe(self.signals.failed, self.arg)
                return
        else:
            log.warning("DiscoverJob got unknown kind %r", self.kind)
            return
        self.signals.emit_safe(self.signals.finished, (self.kind, payload))


class WorldJob(QRunnable):
    """Tunes one world-genre station; emits (label, tracks).

    Runs Catalog.search_everywhere — songs, then videos, then the
    yt-dlp web fallback — so a genre dial never comes back static just
    because the guest catalogue is shy.
    """

    def __init__(self, catalog: Catalog, query: str, label: str,
                 limit: int | None = None,
                 fallback: Callable | None = None):
        super().__init__()
        self.setAutoDelete(False)
        self.signals = _SignalCarrier()
        self.catalog = catalog
        self.query = query
        self.label = label
        self.limit = limit
        self.fallback = fallback

    def run(self) -> None:  # noqa: D102
        from . import config
        from .catalog import web_search_tracks

        tracks = self.catalog.search_everywhere(
            self.query,
            limit=self.limit or config.WORLD_STATION_LIMIT,
            fallback=self.fallback if self.fallback is not None else web_search_tracks,
        )
        self.signals.emit_safe(self.signals.finished, (self.label, tracks))


class LoadJob(QRunnable):
    """Runs on the dedicated playback pool — stream resolution never waits on anything."""

    def __init__(self, track: Track):
        super().__init__()
        self.setAutoDelete(False)  # lifetime managed by Hearth._jobs, not the pool
        self.signals = _SignalCarrier()
        self.track = track

    def run(self) -> None:  # noqa: D102
        url, loudness = resolve_stream_url(
            f"https://www.youtube.com/watch?v={self.track.video_id}"
        )
        if url:
            self.signals.emit_safe(self.signals.finished, (url, loudness, self.track))
        else:
            self.signals.emit_safe(self.signals.failed, self.track.title)


class LyricsJob(QRunnable):
    """Fetches lyrics for the current track off the main thread.

    Synced (LRC) first via LRCLIB — every line gets its moment — then
    plain text from LRCLIB, and the YT Music catalogue as the last leg.
    Emits ``(video_id, plain_text, lines)`` where `lines` is a parsed
    LRC timeline or None when only plain text was found.
    """

    def __init__(self, catalog: Catalog, track: Track):
        super().__init__()
        self.setAutoDelete(False)
        self.signals = _SignalCarrier()
        self.catalog = catalog
        self.track = track

    def run(self) -> None:  # noqa: D102
        from . import lyrics as lyrics_engine

        plain: str | None = None
        lines = None
        try:
            plain_lrclib, lrc = lyrics_engine.fetch_lyrics(
                self.track.artist,
                self.track.title,
                duration_sec=self.track.duration_sec or None,
            )
            if lrc:
                parsed = lyrics_engine.parse_lrc(lrc)
                if parsed:
                    lines = parsed
            plain = plain_lrclib
        except Exception as exc:  # noqa: BLE001 - lyrics must never break playback
            log.info("synced lyrics fetch failed for %s: %s", self.track.video_id, exc)
        if plain is None and lines is None:
            plain = self.catalog.lyrics(self.track.video_id)
        self.signals.emit_safe(
            self.signals.finished, (self.track.video_id, plain, lines)
        )


class ArtistJob(QRunnable):
    """Opens an artist page; emits an Artist (or failed(channel_id))."""

    def __init__(self, catalog: Catalog, channel_id: str):
        super().__init__()
        self.setAutoDelete(False)
        self.signals = _SignalCarrier()
        self.catalog = catalog
        self.channel_id = channel_id

    def run(self) -> None:  # noqa: D102
        artist = self.catalog.artist(self.channel_id)
        if artist is not None:
            self.signals.emit_safe(self.signals.finished, artist)
        else:
            self.signals.emit_safe(self.signals.failed, self.channel_id)


class ArtistLookupJob(QRunnable):
    """Finds an artist by name when no channel id is known; emits list[Artist].

    The yt-dlp web leg and some catalogue results carry a name but no
    UC… id — this is the door-opener for those.
    """

    def __init__(self, catalog: Catalog, name: str, limit: int = 5):
        super().__init__()
        self.setAutoDelete(False)
        self.signals = _SignalCarrier()
        self.catalog = catalog
        self.name = name
        self.limit = limit

    def run(self) -> None:  # noqa: D102
        artists = self.catalog.search_artists(self.name, limit=self.limit)
        if artists:
            self.signals.emit_safe(self.signals.finished, artists)
        else:
            self.signals.emit_safe(self.signals.failed, self.name)


class RadioJob(QRunnable):
    """Seeds an endless-radio queue from one track off the main thread."""

    def __init__(self, catalog: Catalog, video_id: str, limit: int = 25):
        super().__init__()
        self.setAutoDelete(False)
        self.signals = _SignalCarrier()
        self.catalog = catalog
        self.video_id = video_id
        self.limit = limit

    def run(self) -> None:  # noqa: D102
        from . import config

        tracks = self.catalog.radio(self.video_id, limit=self.limit or config.RADIO_LIMIT)
        self.signals.emit_safe(self.signals.finished, (self.video_id, tracks))
