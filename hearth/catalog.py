"""YouTube Music guest search with retry backoff and link parsing."""

from __future__ import annotations

import logging
import re
import time
from typing import Callable

from .config import DISCOVER_PLAYLIST_LIMIT, RETRY_ATTEMPTS, RETRY_BASE_DELAY
from .models import Album, Artist, Collection, Track

log = logging.getLogger(__name__)

_LINK_PATTERNS = (
    re.compile(r"(?:youtube\.com/watch\?(?:.*&)?v=|youtu\.be/|music\.youtube\.com/watch\?(?:.*&)?v=)([\w-]{11})"),
    re.compile(r"^([\w-]{11})$"),
)


def parse_video_id(query: str) -> str | None:
    """Extract a video id from a YouTube/YT Music URL (or bare id). None if not a link."""
    q = query.strip()
    for pattern in _LINK_PATTERNS:
        m = pattern.search(q)
        if m:
            return m.group(1)
    return None


class Catalog:
    """YT Music guest-API catalogue access. Heavy client import is lazy."""

    SEARCH_FILTERS = {"songs": "songs", "videos": "videos", "albums": "albums"}

    def __init__(self):
        self._client = None
        # Per-leg fetch counters for the diagnostics report (v0.7.1):
        # keys like "search-songs.ok" / "search-songs.fail" /
        # "web-fallback.empty" — which fetch leg served the shelves,
        # counted right where each attempt is judged. Never raises.
        self.counters: dict[str, int] = {}

    def _bump(self, key: str) -> None:
        """Count one fetch outcome; a broken counter never bites."""
        try:
            self.counters[key] = self.counters.get(key, 0) + 1
        except Exception:  # noqa: BLE001 - bookkeeping must stay invisible
            pass

    def _get_client(self, client_factory: Callable | None = None):
        if client_factory is not None:
            return client_factory()
        if self._client is None:
            from ytmusicapi import YTMusic  # lazy: keeps UI startup snappy

            from . import ytm_resilience

            ytm_resilience.apply()  # junk cards must not kill whole shelves
            self._client = YTMusic()
        return self._client

    def _retry(
        self,
        action: Callable,
        label: str,
        attempts: int = RETRY_ATTEMPTS,
        base_delay: float = RETRY_BASE_DELAY,
        sleep: Callable[[float], None] = time.sleep,
        default=None,
    ):
        """Run `action` with exponential backoff. `default` on exhaustion.

        Each attempt is counted under the label's operation name
        ("search-songs(q)" -> "search-songs.ok" / ".fail") so the
        diagnostics page can say which leg served (or starved) a shelf.
        """
        leg = label.split("(", 1)[0].strip() or "fetch"
        for attempt in range(attempts):
            try:
                result = action()
                self._bump(f"{leg}.ok")
                return result
            except Exception as exc:  # noqa: BLE001 - network layer must not crash UI
                if attempt == attempts - 1:
                    log.warning("%s failed after %d attempts: %s", label, attempts, exc)
                    self._bump(f"{leg}.fail")
                    return default
                delay = base_delay * (2 ** attempt)
                log.info("%s retry %d/%d in %.1fs (%s)", label, attempt + 1, attempts, delay, exc)
                sleep(delay)
        self._bump(f"{leg}.fail")
        return default

    def search(
        self,
        query: str,
        limit: int = 20,
        attempts: int = RETRY_ATTEMPTS,
        base_delay: float = RETRY_BASE_DELAY,
        sleep: Callable[[float], None] = time.sleep,
        client_factory: Callable | None = None,
    ) -> list[Track]:
        """Search songs; returns [] on exhausted retries (never raises)."""
        return self.search_songs(
            query, limit=limit, attempts=attempts, base_delay=base_delay,
            sleep=sleep, client_factory=client_factory,
        )

    def scoped_search(
        self,
        query: str,
        scope: str = "songs",
        limit: int = 20,
        attempts: int = RETRY_ATTEMPTS,
        base_delay: float = RETRY_BASE_DELAY,
        sleep: Callable[[float], None] = time.sleep,
        client_factory: Callable | None = None,
    ) -> tuple[str, list]:
        """Search by scope; returns (scope, tracks|albums). Never raises."""
        if scope not in self.SEARCH_FILTERS:
            scope = "songs"
        if scope == "albums":
            return scope, self.search_albums(
                query, limit=limit, attempts=attempts, base_delay=base_delay,
                sleep=sleep, client_factory=client_factory,
            )
        if scope == "videos":
            return scope, self.search_videos(
                query, limit=limit, attempts=attempts, base_delay=base_delay,
                sleep=sleep, client_factory=client_factory,
            )
        return "songs", self.search_songs(
            query, limit=limit, attempts=attempts, base_delay=base_delay,
            sleep=sleep, client_factory=client_factory,
        )

    def search_songs(
        self,
        query: str,
        limit: int = 20,
        attempts: int = RETRY_ATTEMPTS,
        base_delay: float = RETRY_BASE_DELAY,
        sleep: Callable[[float], None] = time.sleep,
        client_factory: Callable | None = None,
    ) -> list[Track]:
        raw = self._retry(
            lambda: self._get_client(client_factory).search(
                query, filter="songs", limit=limit
            ),
            f"search-songs({query!r})", attempts, base_delay, sleep, default=[],
        )
        return self._map_results(raw or [])

    def search_videos(
        self,
        query: str,
        limit: int = 20,
        attempts: int = RETRY_ATTEMPTS,
        base_delay: float = RETRY_BASE_DELAY,
        sleep: Callable[[float], None] = time.sleep,
        client_factory: Callable | None = None,
    ) -> list[Track]:
        raw = self._retry(
            lambda: self._get_client(client_factory).search(
                query, filter="videos", limit=limit
            ),
            f"search-videos({query!r})", attempts, base_delay, sleep, default=[],
        )
        return self._map_results(raw or [])

    def search_everywhere(
        self,
        query: str,
        limit: int = 20,
        attempts: int = RETRY_ATTEMPTS,
        base_delay: float = RETRY_BASE_DELAY,
        sleep: Callable[[float], None] = time.sleep,
        client_factory: Callable | None = None,
        fallback: Callable[[str, int], list[Track]] | None = None,
    ) -> list[Track]:
        """Songs, then videos, then a web fallback. Never raises.

        The guest catalogue misses rare live cuts, B-sides and regional
        uploads — the fallback leg (`fallback(query, limit)`) catches
        those. None skips the web leg (unit tests stay offline).
        """
        for scope in ("songs", "videos"):
            raw = self._retry(
                lambda: self._get_client(client_factory).search(
                    query, filter=scope, limit=limit
                ),
                f"search-everywhere-{scope}({query!r})", attempts, base_delay,
                sleep, default=[],
            )
            mapped = self._map_results(raw or [])
            if mapped:
                return mapped
            self._bump(f"search-everywhere-{scope}.empty")
        if fallback is None:
            return []
        try:
            served = list(fallback(query, limit))
        except Exception as exc:  # noqa: BLE001 - the fallback must not crash either
            log.warning("search_everywhere fallback failed for %r: %s", query, exc)
            self._bump("web-fallback.fail")
            return []
        self._bump("web-fallback.ok" if served else "web-fallback.empty")
        return served

    def search_albums(
        self,
        query: str,
        limit: int = 20,
        attempts: int = RETRY_ATTEMPTS,
        base_delay: float = RETRY_BASE_DELAY,
        sleep: Callable[[float], None] = time.sleep,
        client_factory: Callable | None = None,
    ) -> list[Album]:
        raw = self._retry(
            lambda: self._get_client(client_factory).search(
                query, filter="albums", limit=limit
            ),
            f"search-albums({query!r})", attempts, base_delay, sleep, default=[],
        )
        return self._map_albums(raw or [])

    def album(
        self,
        browse_id: str,
        attempts: int = RETRY_ATTEMPTS,
        base_delay: float = RETRY_BASE_DELAY,
        sleep: Callable[[float], None] = time.sleep,
        client_factory: Callable | None = None,
    ) -> tuple[Album, list[Track]] | None:
        """Album page: (Album, [Track]); None on failure (never raises)."""
        data = self._retry(
            lambda: self._get_client(client_factory).get_album(browseId=browse_id),
            f"album({browse_id})", attempts, base_delay, sleep,
        )
        data = data or {}
        if not data.get("title"):
            return None
        album = Album(
            browse_id=browse_id,
            title=data.get("title", "Unknown album"),
            artist=self._artist_names(data),
            year=data.get("year") or "",
            thumbnail=(data.get("thumbnails") or [{}])[-1].get("url", ""),
        )
        return album, self._map_results(data.get("tracks") or [])

    def song_details(
        self,
        video_id: str,
        attempts: int = RETRY_ATTEMPTS,
        base_delay: float = RETRY_BASE_DELAY,
        sleep: Callable[[float], None] = time.sleep,
        client_factory: Callable | None = None,
    ) -> Track | None:
        """Fetch metadata for a single video id (e.g. from a pasted link)."""
        for attempt in range(attempts):
            try:
                info = self._get_client(client_factory).get_song(video_id)
                video = (info or {}).get("videoDetails", {})
                if not video.get("videoId"):
                    return None
                return self._map_song(video)
            except Exception as exc:  # noqa: BLE001
                if attempt == attempts - 1:
                    log.warning("song_details(%s) failed: %s", video_id, exc)
                    return None
                sleep(base_delay * (2 ** attempt))
        return None

    # --- artist pages: every artist gets a stage ---

    def search_artists(
        self,
        query: str,
        limit: int = 10,
        attempts: int = RETRY_ATTEMPTS,
        base_delay: float = RETRY_BASE_DELAY,
        sleep: Callable[[float], None] = time.sleep,
        client_factory: Callable | None = None,
    ) -> list[Artist]:
        """Find artists by name (shallow pages: id + name + face). [] on failure."""
        raw = self._retry(
            lambda: self._get_client(client_factory).search(
                query, filter="artists", limit=limit
            ),
            f"search-artists({query!r})", attempts, base_delay, sleep, default=[],
        )
        artists: list[Artist] = []
        for item in raw or []:
            channel_id = item.get("browseId") or ""
            if not channel_id:
                continue
            name = item.get("artist") or ""
            if isinstance(name, dict):
                name = name.get("name", "")
            artists.append(
                Artist(
                    channel_id=channel_id,
                    name=str(name).strip() or "Unknown artist",
                    thumbnail=(item.get("thumbnails") or [{}])[-1].get("url", ""),
                )
            )
        return artists

    def artist(
        self,
        channel_id: str,
        attempts: int = RETRY_ATTEMPTS,
        base_delay: float = RETRY_BASE_DELAY,
        sleep: Callable[[float], None] = time.sleep,
        client_factory: Callable | None = None,
    ) -> Artist | None:
        """Full artist page: identity, top tracks, albums, singles, related.
        None on failure (never raises)."""
        data = self._retry(
            lambda: self._get_client(client_factory).get_artist(channelId=channel_id),
            f"artist({channel_id})", attempts, base_delay, sleep,
        )
        data = data or {}
        name = (data.get("name") or "").strip()
        if not name:
            return None
        related: list[Artist] = []
        for item in ((data.get("related") or {}).get("results") or []):
            cid = item.get("browseId") or ""
            if not cid:
                continue
            related.append(
                Artist(
                    channel_id=cid,
                    name=item.get("title") or "Unknown artist",
                    thumbnail=(item.get("thumbnails") or [{}])[-1].get("url", ""),
                )
            )
        return Artist(
            channel_id=channel_id,
            name=name,
            description=(data.get("description") or "").strip(),
            subscribers=str(data.get("subscribers") or ""),
            thumbnail=(data.get("thumbnails") or [{}])[-1].get("url", ""),
            top_tracks=self._map_results((data.get("songs") or {}).get("results") or []),
            albums=self._map_albums((data.get("albums") or {}).get("results") or []),
            singles=self._map_albums((data.get("singles") or {}).get("results") or []),
            related=related,
        )

    def lyrics(
        self,
        video_id: str,
        attempts: int = RETRY_ATTEMPTS,
        base_delay: float = RETRY_BASE_DELAY,
        sleep: Callable[[float], None] = time.sleep,
        client_factory: Callable | None = None,
    ) -> str | None:
        """Lyrics text for a track. None when unavailable (never raises)."""
        for attempt in range(attempts):
            try:
                data = self._get_client(client_factory).get_lyrics(video_id)
                text = (data or {}).get("lyrics") or ""
                return text.strip() or None
            except Exception as exc:  # noqa: BLE001 - network layer must not crash UI
                if attempt == attempts - 1:
                    log.info("lyrics(%s) unavailable: %s", video_id, exc)
                    return None
                sleep(base_delay * (2 ** attempt))
        return None

    def radio(
        self,
        video_id: str,
        limit: int = 25,
        attempts: int = RETRY_ATTEMPTS,
        base_delay: float = RETRY_BASE_DELAY,
        sleep: Callable[[float], None] = time.sleep,
        client_factory: Callable | None = None,
    ) -> list[Track]:
        """Endless-radio seed: tracks related to `video_id`. [] on failure."""
        for attempt in range(attempts):
            try:
                data = self._get_client(client_factory).get_watch_playlist(
                    videoId=video_id, radio=True, limit=limit
                )
                return self._map_results((data or {}).get("tracks") or [])
            except Exception as exc:  # noqa: BLE001
                if attempt == attempts - 1:
                    log.warning("radio(%s) failed after %d attempts: %s",
                                video_id, attempts, exc)
                    return []
                sleep(base_delay * (2 ** attempt))
        return []

    # --- discover: the whole world's music ---

    def mood_categories(
        self,
        attempts: int = RETRY_ATTEMPTS,
        base_delay: float = RETRY_BASE_DELAY,
        sleep: Callable[[float], None] = time.sleep,
        client_factory: Callable | None = None,
    ) -> list[tuple[str, list[dict]]]:
        """Mood & genre sections: [(section_title, [{title, params}])]. [] on failure."""
        data = self._retry(
            lambda: self._get_client(client_factory).get_mood_categories(),
            "mood-categories", attempts, base_delay, sleep, default={},
        )
        return [
            (title, list(sections))
            for title, sections in (data or {}).items()
            if isinstance(sections, list)
        ]

    def mood_playlists(
        self,
        params: str,
        attempts: int = RETRY_ATTEMPTS,
        base_delay: float = RETRY_BASE_DELAY,
        sleep: Callable[[float], None] = time.sleep,
        client_factory: Callable | None = None,
    ) -> list[Collection]:
        """Curated playlists for one mood/genre param. [] on failure."""
        raw = self._retry(
            lambda: self._get_client(client_factory).get_mood_playlists(params=params),
            f"mood-playlists({params!r})", attempts, base_delay, sleep, default=[],
        )
        return self._map_collections(raw or [])

    def charts(
        self,
        attempts: int = RETRY_ATTEMPTS,
        base_delay: float = RETRY_BASE_DELAY,
        sleep: Callable[[float], None] = time.sleep,
        client_factory: Callable | None = None,
    ) -> list[Collection]:
        """Global chart playlists (daily / weekly / top-100). [] on failure."""
        data = self._retry(
            lambda: self._get_client(client_factory).get_charts(),
            "charts", attempts, base_delay, sleep, default={},
        )
        return self._map_collections((data or {}).get("videos") or [])

    def explore_shelves(
        self,
        attempts: int = RETRY_ATTEMPTS,
        base_delay: float = RETRY_BASE_DELAY,
        sleep: Callable[[float], None] = time.sleep,
        client_factory: Callable | None = None,
    ) -> tuple[list[Album], list[Track], list[Track]]:
        """Explore page: (new release albums, trending tracks, new videos)."""
        data = self._retry(
            lambda: self._get_client(client_factory).get_explore(),
            "explore", attempts, base_delay, sleep, default={},
        )
        data = data or {}
        albums = self._map_albums(data.get("new_releases") or [])
        trending = self._map_results((data.get("trending") or {}).get("items") or [])
        videos = self._map_results(data.get("new_videos") or [])
        return albums, trending, videos

    def playlist(
        self,
        playlist_id: str,
        limit: int = DISCOVER_PLAYLIST_LIMIT,
        attempts: int = RETRY_ATTEMPTS,
        base_delay: float = RETRY_BASE_DELAY,
        sleep: Callable[[float], None] = time.sleep,
        client_factory: Callable | None = None,
    ) -> tuple[str, list[Track]] | None:
        """Full track list of a curated playlist. None on failure (never raises)."""
        data = self._retry(
            lambda: self._get_client(client_factory).get_playlist(
                playlistId=playlist_id, limit=limit
            ),
            f"playlist({playlist_id})", attempts, base_delay, sleep,
        )
        data = data or {}
        if not data.get("title"):
            return None
        return str(data["title"]), self._map_results(data.get("tracks") or [])

    @classmethod
    def _map_collections(cls, results: list[dict]) -> list[Collection]:
        collections: list[Collection] = []
        for item in results:
            pid = item.get("playlistId") or item.get("browseId") or ""
            if not pid:
                continue
            collections.append(
                Collection(
                    playlist_id=pid,
                    title=item.get("title", "Unknown playlist"),
                    subtitle=item.get("subtitle") or item.get("description") or "",
                    thumbnail=(item.get("thumbnails") or [{}])[-1].get("url", ""),
                )
            )
        return collections

    @staticmethod
    def _artist_names(item: dict) -> str:
        """Best-effort artist line across result shapes (song/video/album)."""
        listed = item.get("artists") or []
        if isinstance(listed, list) and listed:
            names = ", ".join(a.get("name", "") for a in listed if isinstance(a, dict))
            if names.strip(", "):
                return names.strip(", ")
        single = item.get("artist") or item.get("owner")
        if isinstance(single, dict) and single.get("name"):
            return single["name"]
        if isinstance(single, str) and single.strip():
            return single.strip()
        author = item.get("author")
        if isinstance(author, str) and author.strip():
            return author.strip()
        return "Unknown artist"

    @staticmethod
    def _first_artist_id(item: dict) -> str:
        """Best-effort channel id (UC…) for the primary artist of a result."""
        listed = item.get("artists") or []
        if isinstance(listed, list):
            for entry in listed:
                if isinstance(entry, dict) and entry.get("id"):
                    return str(entry["id"])
        owner = item.get("owner")
        if isinstance(owner, dict) and owner.get("id"):
            return str(owner["id"])
        return ""

    @classmethod
    def _map_results(cls, results: list[dict]) -> list[Track]:
        tracks: list[Track] = []
        for item in results:
            if not item.get("videoId"):
                continue
            seconds = _duration_to_sec(item.get("duration_seconds")) or _duration_to_sec(item.get("lengthSeconds"))
            tracks.append(
                Track(
                    video_id=item["videoId"],
                    title=item.get("title", "Unknown"),
                    artist=cls._artist_names(item),
                    duration=item.get("duration") or _seconds_to_clock(seconds),
                    duration_sec=seconds,
                    thumbnail=(item.get("thumbnails") or [{}])[-1].get("url", ""),
                    playlist_id=item.get("album", {}).get("id", "") if isinstance(item.get("album"), dict) else "",
                    artist_id=cls._first_artist_id(item),
                )
            )
        return tracks

    @classmethod
    def _map_albums(cls, results: list[dict]) -> list[Album]:
        albums: list[Album] = []
        for item in results:
            browse_id = item.get("browseId") or item.get("playlistId") or ""
            if not browse_id:
                continue
            albums.append(
                Album(
                    browse_id=browse_id,
                    title=item.get("title", "Unknown album"),
                    artist=cls._artist_names(item),
                    artist_id=cls._first_artist_id(item),
                    year=item.get("year") or "",
                    thumbnail=(item.get("thumbnails") or [{}])[-1].get("url", ""),
                )
            )
        return albums

    @staticmethod
    def _map_song(video: dict) -> Track:
        return Track(
            video_id=video["videoId"],
            title=video.get("title", "Unknown"),
            artist=video.get("author", "Unknown artist"),
            duration_sec=int(video.get("lengthSeconds") or 0),
            duration=_seconds_to_clock(int(video.get("lengthSeconds") or 0)),
            thumbnail=(video.get("thumbnail", {}).get("thumbnails") or [{}])[-1].get("url", ""),
        )


def _duration_to_sec(seconds) -> int:
    try:
        return int(seconds or 0)
    except (TypeError, ValueError):
        return 0


def _seconds_to_clock(seconds: int) -> str:
    minutes, secs = divmod(seconds, 60)
    return f"{minutes}:{secs:02d}"


def web_search_tracks(query: str, limit: int = 20) -> list[Track]:
    """Last-resort web search via yt-dlp's YouTube index. Never raises.

    This is the 'each and every music' insurance: if the YT Music guest
    catalogue has never heard of a track, the world's biggest video
    index probably has. The search runs flat (ids + titles only) — the
    heavy per-video resolution already happens later, in LoadJob, so
    this leg stays fast and dodges YouTube's metadata bot-checks.
    """
    try:
        import yt_dlp  # lazy: only paid for when the catalogue comes up empty

        ydl = yt_dlp.YoutubeDL({
            "quiet": True,
            "no_warnings": True,
            "noplaylist": True,
            "default_search": "ytsearch",
            "extract_flat": True,   # ids/titles only — LoadJob resolves later
        })
        info = ydl.extract_info(f"ytsearch{int(limit)}:{query}", download=False)
    except Exception as exc:  # noqa: BLE001 - network layer must not crash UI
        log.warning("web search failed for %r: %s", query, exc)
        return []
    tracks: list[Track] = []
    for entry in (info or {}).get("entries") or []:
        if not isinstance(entry, dict) or not entry.get("id"):
            continue
        seconds = _duration_to_sec(entry.get("duration"))
        thumbs = entry.get("thumbnails") or []
        channel_id = str(entry.get("channel_id") or "")
        tracks.append(
            Track(
                video_id=str(entry["id"]),
                title=entry.get("title") or "Unknown",
                artist=entry.get("uploader") or entry.get("channel") or "Unknown artist",
                duration=_seconds_to_clock(seconds),
                duration_sec=seconds,
                thumbnail=(
                    thumbs[-1].get("url", "")
                    if thumbs else entry.get("thumbnail") or ""
                ),
                artist_id=channel_id if channel_id.startswith("UC") else "",
            )
        )
    return tracks
