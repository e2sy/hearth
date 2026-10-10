"""The Welcome Mat: move your Spotify playlists onto the hearth.

Parse-only and match-only — no Spotify login, no keys, no crawler.
Three honest inputs, all pasted or dropped in by the user:

- a Spotify JSON export (a bare list of track objects, or
  ``{"tracks": [...]}`` / ``{"items": [...]}`` — every shape the
  export tools emit),
- an Exportify-style CSV (``Track Name`` / ``Artist Name(s)`` columns,
  case-tolerant),
- the HTML of an ``open.spotify.com/embed/playlist/...`` page (its
  embedded ``trackList`` JSON).

Each parsed song is cleaned of video-noise ("(Official Music Video)",
"feat. …"), handed to an *injected* search callable (the same YTM
search the app already owns), and matched tracks dedupe by video id.
Misses come back listed in the report, not hidden. The store gets a
real playlist; the report says exactly what landed and what didn't.
"""

from __future__ import annotations

import csv
import io
import json
import logging
import re
from dataclasses import dataclass, field
from typing import Callable, Iterable

from . import config
from .models import Track
from .storage import HearthStore

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class SongRef:
    """One parsed song, before it goes looking for its YT Music twin."""

    title: str
    artist: str = ""
    album: str = ""
    duration_sec: int | None = None


@dataclass
class ImportReport:
    """The honest receipt: what landed, what duplicated, what didn't."""

    playlist_id: int
    name: str
    total: int = 0
    added: int = 0
    duplicates: int = 0
    skipped: list[str] = field(default_factory=list)
    tracks: list[Track] = field(default_factory=list)

    @property
    def summary(self) -> str:
        base = f"{self.added}/{self.total} matched into '{self.name}'"
        if self.duplicates:
            base += f" · {self.duplicates} duplicate(s) collapsed"
        if self.skipped:
            base += f" · {len(self.skipped)} unmatched"
        return base


# ------------------------------------------------------------------ parsing

_TITLE_KEYS = ("title", "trackName", "name", "track")
_ARTIST_KEYS = ("artist", "artistName", "albumArtist")
_ARTISTS_KEYS = ("artists", "artistNames")
_ALBUM_KEYS = ("album", "albumName", "album_name")
_DUR_MS_KEYS = ("duration_ms", "durationMs", "duration")
_DUR_S_KEYS = ("duration_sec", "durationSeconds")


def _first_str(payload: dict, keys: Iterable[str]) -> str:
    """First present, non-empty string value among candidate keys."""
    for key in keys:
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _artist_of(payload: dict) -> str:
    """One primary artist string out of the many export shapes."""
    solo = _first_str(payload, _ARTIST_KEYS)
    if solo:
        return solo
    for key in _ARTISTS_KEYS:
        group = payload.get(key)
        if isinstance(group, list):
            names = [
                (item.get("name") if isinstance(item, dict) else item)
                for item in group
                if (isinstance(item, dict) and item.get("name")) or isinstance(item, str)
            ]
            if names:
                return str(names[0]).strip()
        elif isinstance(group, str) and group.strip():
            return group.strip()
    return ""


def _duration_of(payload: dict) -> int | None:
    for key in _DUR_MS_KEYS:
        value = payload.get(key)
        if isinstance(value, (int, float)) and value > 0:
            return int(round(value / 1000.0))
    for key in _DUR_S_KEYS:
        value = payload.get(key)
        if isinstance(value, (int, float)) and value > 0:
            return int(value)
    return None


def _ref_of(payload: dict) -> SongRef | None:
    title = _first_str(payload, _TITLE_KEYS)
    if not title:
        return None
    return SongRef(
        title=title,
        artist=_artist_of(payload),
        album=_first_str(payload, _ALBUM_KEYS),
        duration_sec=_duration_of(payload),
    )


def parse_spotify_json(text: str) -> list[SongRef]:
    """Parse a Spotify JSON export. Garbage in → [] out (never raises)."""
    try:
        payload = json.loads(text)
    except Exception as exc:  # noqa: BLE001 - user paste must never crash
        log.info("spotify json parse failed: %s", exc)
        return []
    if isinstance(payload, dict):
        payload = (payload.get("tracks") or payload.get("items")
                   or payload.get("songs") or [])
    if not isinstance(payload, list):
        return []
    refs: list[SongRef] = []
    for item in payload:
        if isinstance(item, dict):
            ref = _ref_of(item)
            if ref is not None:
                refs.append(ref)
    return refs


def parse_exportify_csv(text: str) -> list[SongRef]:
    """Parse an Exportify-style CSV with case-tolerant column names."""
    try:
        reader = csv.DictReader(io.StringIO(text))
        if not reader.fieldnames:
            return []
        lowered = {
            (name or "").strip().lower(): (name or "").strip()
            for name in reader.fieldnames
        }

        def col(row: dict, *candidates: str) -> str:
            for cand in candidates:
                name = lowered.get(cand)
                if name and (row.get(name) or "").strip():
                    return row[name].strip()
            return ""

        refs: list[SongRef] = []
        for row in reader:
            title = col(row, "track name", "title", "name", "song")
            if not title:
                continue
            duration_sec: int | None = None
            ms = col(row, "duration (ms)", "duration_ms", "durationms")
            if ms.isdigit() and int(ms) > 0:
                duration_sec = int(round(int(ms) / 1000.0))
            refs.append(SongRef(
                title=title,
                artist=col(row, "artist name(s)", "artist name", "artist", "artists"),
                album=col(row, "album name", "album"),
                duration_sec=duration_sec,
            ))
        return refs
    except Exception as exc:  # noqa: BLE001
        log.info("spotify csv parse failed: %s", exc)
        return []


_TRACKLIST = re.compile(r'"trackList"\s*:\s*(\[.*?\])\s*[,}]', re.DOTALL)


def parse_embed_html(text: str) -> list[SongRef]:
    """Pull the trackList out of an open.spotify.com/embed page."""
    try:
        match = _TRACKLIST.search(text)
        if not match:
            return []
        items = json.loads(match.group(1))
        if not isinstance(items, list):
            return []
        refs: list[SongRef] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            title = (item.get("title") or "").strip()
            if not title:
                continue
            # subtitle is "Lead Artist, Second Artist" — the lead carries the match
            artists = (item.get("subtitle") or "").split(",")
            refs.append(SongRef(
                title=title,
                artist=artists[0].strip() if artists else "",
            ))
        return refs
    except Exception as exc:  # noqa: BLE001
        log.info("spotify embed parse failed: %s", exc)
        return []


def parse_source(text: str, fmt: str = "auto") -> list[SongRef]:
    """Auto-detect the paste's shape (json | csv | html) and parse it."""
    text = (text or "").strip()
    if not text:
        return []
    if fmt == "auto":
        if text[0] in "{[":
            fmt = "json"
        elif text[0] == "<":
            fmt = "html"
        else:
            fmt = "csv"
    parsers = {
        "json": parse_spotify_json,
        "csv": parse_exportify_csv,
        "html": parse_embed_html,
    }
    parser = parsers.get(fmt)
    return parser(text) if parser else []


# ------------------------------------------------------------------ matching

_VIDEO_NOISE = re.compile(
    r"\((?:\s*(?:official\s+)?(?:music\s+)?(?:video|audio|lyric(?:s)?\s*video|"
    r"visualizer|hd|hq|4k)\s*)\)|"
    r"\[(?:\s*(?:official\s+)?(?:music\s+)?(?:video|audio|lyric(?:s)?)\s*)\]|"
    r"【[^】]*】",
    re.IGNORECASE,
)
_FEAT_TAIL = re.compile(r"\s*(?:feat\.?|ft\.?|featuring|with)\s+.*$", re.IGNORECASE)


def clean_title(title: str) -> str:
    """'(Official Music Video)' and 'feat. X' and friends → gone."""
    cleaned = _VIDEO_NOISE.sub(" ", title or "")
    cleaned = _FEAT_TAIL.sub(" ", cleaned)
    return re.sub(r"\s{2,}", " ", cleaned).strip(" -–—|")


def clean_query(ref: SongRef) -> str:
    """The best single search string for one parsed song.

    Multi-artist rows ("A, B & C") search under the lead only —
    LRCLIB and YTM both index tracks under the primary artist.
    """
    title = clean_title(ref.title)
    artist = clean_title(ref.artist).split(",")[0].strip()
    return f"{artist} {title}".strip() if artist else title


def _as_track(result: Track | list | None) -> Track | None:
    if isinstance(result, Track):
        return result
    if isinstance(result, list):
        return result[0] if result and isinstance(result[0], Track) else None
    return None


def match_songs(
    refs: list[SongRef],
    search: Callable[[str], Track | list[Track] | None],
) -> tuple[list[Track], list[str], int]:
    """Match every ref against the injected search.

    Returns ``(tracks, skipped_queries, duplicate_count)``. Two queries
    per ref — full cleaned string first, bare title as the fallback —
    and the same YT Music video never lands twice.
    """
    tracks: list[Track] = []
    skipped: list[str] = []
    seen: set[str] = set()
    duplicates = 0
    for ref in refs:
        track: Track | None = None
        for query in dict.fromkeys(q for q in (clean_query(ref), clean_title(ref.title)) if q):
            try:
                track = _as_track(search(query))
            except Exception as exc:  # noqa: BLE001 - search layer may hiccup
                log.info("import search failed for %r: %s", query, exc)
                track = None
            if track is not None:
                break
        if track is None:
            label = f"{ref.artist} — {ref.title}" if ref.artist else ref.title
            skipped.append(label)
            continue
        if track.video_id in seen:
            duplicates += 1
            continue
        seen.add(track.video_id)
        tracks.append(track)
    return tracks, skipped, duplicates


# ------------------------------------------------------------------ import

def import_spotify(
    store: HearthStore,
    text: str,
    search: Callable[[str], Track | list[Track] | None],
    name: str | None = None,
    fmt: str = "auto",
) -> ImportReport:
    """Parse → match → create the playlist. Never raises on bad paste.

    ``search`` is the app's own YTM search, injected so tests (and the
    caller's job pool) stay in control of the network.
    """
    playlist_name = (name or "").strip() or "Spotify import"
    refs = parse_source(text, fmt=fmt)[: config.IMPORT_MAX_TRACKS]
    report = ImportReport(
        playlist_id=0, name=playlist_name, total=len(refs),
    )
    if not refs:
        return report
    tracks, skipped, duplicates = match_songs(refs, search)
    report.skipped = skipped
    report.duplicates = duplicates
    report.tracks = tracks
    if not tracks:
        return report
    report.playlist_id = store.create_playlist(playlist_name)
    for track in tracks:
        if store.add_to_playlist(report.playlist_id, track):
            report.added += 1
    return report
