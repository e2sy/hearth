"""Synced lyrics: LRC parsing, position lookup, and the LRCLIB client.

The catalog's plain lyrics say what is sung; this module says *when*.
LRCLIB (https://lrclib.net) is a free, keyless lyrics database that
returns timestamped LRC — every line gets its moment, so Hearth can
glow the current line along with the fire.
"""

from __future__ import annotations

import bisect
import json
import logging
import re
import urllib.parse
import urllib.request
from dataclasses import dataclass

from . import config

log = logging.getLogger(__name__)

_STAMP = re.compile(r"\[(\d{1,3}):(\d{1,2})(?:[.:](\d{1,3}))?\]")
_META_TAG = re.compile(r"^\[[a-z]+:")          # [ar:…] [ti:…] [offset:…] …


@dataclass(frozen=True)
class LrcLine:
    """One sung line and the moment it begins (ms from track start)."""

    time_ms: int
    text: str


def _stamp_ms(minutes: str, seconds: str, fraction: str | None) -> int:
    """'[03:45]' / '[03:45.12]' / '[03:45.123]' / '[03:45.1]' → milliseconds."""
    frac = (fraction or "").ljust(3, "0")[:3]
    hundredths = int(frac or 0)
    return (int(minutes) * 60 + int(seconds)) * 1000 + hundredths


def parse_lrc(raw: str) -> list[LrcLine]:
    """Parse LRC text into time-sorted lines. Garbage in → [] out (never raises).

    Handles multiple stamps per line ('[00:12.00][01:40.50] chorus'),
    a global '[offset:+/-ms]' shift, and skips metadata headers.
    """
    if not raw or not raw.strip():
        return []
    try:
        offset_ms = 0
        lines: list[LrcLine] = []
        for line in raw.splitlines():
            line = line.strip()
            if not line:
                continue
            if _META_TAG.match(line) and "offset" in line:
                digits = re.sub(r"[^\d+-]", "", line)
                try:
                    offset_ms = int(digits)
                except ValueError:
                    offset_ms = 0
                continue
            stamps = _STAMP.findall(line)
            if not stamps:
                continue  # metadata header or stray text — not singable
            text = _STAMP.sub("", line).strip().strip("]")
            for minutes, seconds, fraction in stamps:
                lines.append(
                    LrcLine(time_ms=_stamp_ms(minutes, seconds, fraction) - offset_ms,
                            text=text)
                )
        lines.sort(key=lambda item: item.time_ms)
        return lines
    except Exception as exc:  # noqa: BLE001 - lyrics must never crash the player
        log.info("lrc parse failed: %s", exc)
        return []


class SyncedLyrics:
    """A parsed LRC timeline: which line burns at a given moment."""

    def __init__(self, lines: list[LrcLine]):
        self.lines = sorted(lines, key=lambda item: item.time_ms)
        self._starts = [item.time_ms for item in self.lines]

    def __len__(self) -> int:
        return len(self.lines)

    @property
    def empty(self) -> bool:
        return not self.lines

    def line_at(self, position_ms: int) -> int:
        """Index of the active line; -1 before the first line starts."""
        return bisect.bisect_right(self._starts, position_ms) - 1


def _http_get_json(url: str, timeout: int) -> dict | list | None:
    """GET a JSON document with a polite User-Agent. None on any failure."""
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": f"{config.APP_NAME}/{config.VERSION} (+{config.REPO_URL})",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8", errors="replace"))
    except Exception as exc:  # noqa: BLE001 - network layer must not crash UI
        log.info("lrclib request failed for %s: %s", url, exc)
        return None


def _query_url(endpoint: str, **params: str) -> str:
    base = config.LRCLIB_URL.rstrip("/")
    return f"{base}/{endpoint}?{urllib.parse.urlencode(params)}"


def _primary_artist(artist: str) -> str:
    """'A, B & C' → 'A' — LRCLIB indexes tracks under the lead artist."""
    return artist.split(",")[0].strip()


def _pick_best(results: list, duration_sec: int | None) -> dict | None:
    """Closest-duration result that actually carries lyrics, else None."""
    if not isinstance(results, list):
        return None
    with_lyrics = [r for r in results if isinstance(r, dict)
                   and (r.get("syncedLyrics") or r.get("plainLyrics"))]
    if not with_lyrics:
        return None
    if duration_sec:
        with_lyrics.sort(
            key=lambda r: abs(int(r.get("duration") or 0) - int(duration_sec))
        )
    return with_lyrics[0]


def fetch_lyrics(
    artist: str,
    title: str,
    duration_sec: int | None = None,
    album: str = "",
    timeout: int | None = None,
) -> tuple[str | None, str | None]:
    """Ask LRCLIB for a track's lyrics.

    Returns ``(plain_text, lrc_text)`` — either side may be None. Exact
    match first, then a fuzzy search; the closest-duration candidate wins
    so covers and remixes do not hand us the wrong song's words. Never raises.
    """
    artist = (artist or "").strip()
    title = (title or "").strip()
    if not artist or not title:
        return None, None
    timeout = timeout or config.LRCLIB_TIMEOUT

    params: dict[str, str] = {"artist_name": artist, "track_name": title}
    if album:
        params["album_name"] = album
    if duration_sec:
        params["duration"] = str(int(duration_sec))

    payload = _http_get_json(_query_url("get", **params), timeout)
    if isinstance(payload, dict) and (payload.get("syncedLyrics") or payload.get("plainLyrics")):
        return (payload.get("plainLyrics") or None,
                payload.get("syncedLyrics") or None)

    # Fuzzy leg: /get misses renamed releases; search + duration distance saves them.
    payload = _http_get_json(
        _query_url("search", q=f"{artist} {title}"), timeout
    )
    best = _pick_best(payload if isinstance(payload, list) else [], duration_sec)
    if best is not None:
        return (best.get("plainLyrics") or None, best.get("syncedLyrics") or None)

    # Last try without the featured-lineup noise: 'A feat. B' or 'A, B'.
    lead = _primary_artist(artist)
    if lead and lead != artist:
        payload = _http_get_json(
            _query_url("get", artist_name=lead, track_name=title),
            timeout,
        )
        if isinstance(payload, dict) and (payload.get("syncedLyrics") or payload.get("plainLyrics")):
            return (payload.get("plainLyrics") or None,
                    payload.get("syncedLyrics") or None)
    return None, None
