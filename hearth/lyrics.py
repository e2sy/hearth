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
from typing import Callable

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


# ----------------------------------------------------------------- Room 6.4
# Lyrics-line search: paste a line you half-remember, get the song back.
# Two legs — the offline cache the player already owns (works with the
# network unplugged), and a keyless LRCLIB sweep for lines nobody has
# played yet. Both legs score honestly and never raise.


@dataclass(frozen=True)
class LyricHit:
    """One matched line, where it was found, and how well it matched."""

    line: str
    score: float
    source: str            # "cache" | "lrclib"
    artist: str = ""
    title: str = ""
    video_id: str = ""     # cache hits know their video; LRCLIB hits don't


_PUNCT = re.compile(r"[^\w\s]", re.UNICODE)


def normalize_line(text: str) -> str:
    """Lowercase, punctuation-free, single-spaced — the comparison shape."""
    return re.sub(r"\s{2,}", " ", _PUNCT.sub(" ", (text or "").lower())).strip()


def score_line(query: str, line: str) -> float:
    """How well a remembered line matches a sung line, in 0.0–1.0.

    Exact normalized match tops out at 1.0; a contained phrase scores
    by how much of the line the query accounts for; a full-word match
    in order beats a scrambled one; stray shared words get a small
    share. 0.0 when nothing overlaps.
    """
    query = normalize_line(query)
    line = normalize_line(line)
    if not query or not line:
        return 0.0
    if query == line:
        return 1.0
    if query in line:
        return 0.9 + 0.1 * min(1.0, len(query) / max(1, len(line)))
    q_tokens = query.split()
    l_tokens = line.split()
    if not q_tokens:
        return 0.0
    overlap = sum(1 for tok in set(q_tokens) if tok in l_tokens)
    if overlap == len(set(q_tokens)):
        # every word present — in order beats shuffled
        pos = 0
        in_order = True
        for tok in q_tokens:
            try:
                found = l_tokens.index(tok, pos)
            except ValueError:
                in_order = False
                break
            pos = found + 1
        return 0.8 if in_order else 0.72
    return round(0.6 * overlap / len(set(q_tokens)), 4)


def _best_line_in_text(query: str, lines: list[str]) -> tuple[str, float]:
    """The highest-scoring line in a lyric sheet (ties → earliest)."""
    best_line, best_score = "", 0.0
    for line in lines:
        line = line.strip()
        if not line:
            continue
        score = score_line(query, line)
        if score > best_score:
            best_line, best_score = line, score
    return best_line, best_score


def _text_lines(plain: str, synced: str) -> list[str]:
    """Singable lines from a payload.

    LRC stamps are stripped when the text really is LRC; stampless
    plain text (a cache entry, or a payload that only shipped plain)
    falls back to raw lines instead of vanishing through the parser.
    """
    source = (synced or "").strip() or (plain or "").strip()
    if not source:
        return []
    if synced and synced.strip():
        lines = [line.text for line in parse_lrc(synced)]
        if lines:
            return lines
    return source.splitlines()


def search_cache_entries(
    entries: list[tuple[str, str, str, str]],
    query: str,
    limit: int | None = None,
) -> list[LyricHit]:
    """Score cached entries against a remembered line. Pure and offline.

    ``entries`` are ``(video_id, artist, title, lyric_text)`` tuples —
    exactly what ``HearthStore.lyric_entries()`` produces — so callers
    can hand-fold any source. Zero-score hits are dropped; ties sort by
    artist, then title.
    """
    limit = limit or config.LYRIC_SEARCH_LIMIT
    hits: list[LyricHit] = []
    for video_id, artist, title, text in entries:
        line, score = _best_line_in_text(query, _text_lines("", text))
        if score <= 0.0:
            continue
        hits.append(LyricHit(
            line=line, score=score, source="cache",
            artist=artist, title=title, video_id=video_id,
        ))
    hits.sort(key=lambda h: (-h.score, h.artist.lower(), h.title.lower()))
    return hits[: max(1, int(limit))]


def search_cache(store, query: str, limit: int | None = None) -> list[LyricHit]:
    """The offline leg: search the player's own lyrics cache."""
    try:
        entries = store.lyric_entries()
    except Exception as exc:  # noqa: BLE001 - a broken cache is an empty shelf
        log.info("lyric cache read failed: %s", exc)
        return []
    return search_cache_entries(entries, query, limit=limit)


def search_online(
    query: str,
    limit: int | None = None,
    timeout: int | None = None,
) -> list[LyricHit]:
    """The LRCLIB leg: keyless sweep for the remembered line. Never raises."""
    query = (query or "").strip()
    if not query:
        return []
    limit = limit or config.LYRIC_SEARCH_LIMIT
    timeout = timeout or config.LRCLIB_TIMEOUT
    payload = _http_get_json(_query_url("search", q=query), timeout)
    if not isinstance(payload, list):
        return []
    hits: list[LyricHit] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        line, score = _best_line_in_text(
            query, _text_lines(item.get("plainLyrics") or "",
                                item.get("syncedLyrics") or "")
        )
        if score <= 0.0:
            continue
        hits.append(LyricHit(
            line=line, score=score, source="lrclib",
            artist=(item.get("artistName") or "").strip(),
            title=(item.get("trackName") or "").strip(),
        ))
    hits.sort(key=lambda h: (-h.score, h.artist.lower(), h.title.lower()))
    return hits[: max(1, int(limit))]


def resolve_lyric_hits(
    hits: list[LyricHit],
    search: Callable[[str], "Track | list | None"],
    limit: int | None = None,
) -> list:
    """Lyric hits → playable tracks, deduped, in match-quality order.

    The bridge from "I remember the line" to "play it now". Cache hits
    already know their video, so they become tracks directly; LRCLIB
    hits only know artist + title, so each earns one catalog search.
    A search that raises or returns junk costs its hit nothing — the
    rest of the list keeps flowing. Never raises.
    """
    from .models import Track  # leaf module — safe here, avoids import cycles

    limit = limit or config.LYRIC_SEARCH_LIMIT
    tracks: list[Track] = []
    seen: set[str] = set()
    for hit in hits:
        if len(tracks) >= max(1, int(limit)):
            break
        if hit.source == "cache" and hit.video_id:
            if hit.video_id in seen:
                continue
            seen.add(hit.video_id)
            tracks.append(Track(
                video_id=hit.video_id,
                title=hit.title or "Unknown title",
                artist=hit.artist or "",
            ))
            continue
        query = " ".join(part for part in (hit.artist, hit.title) if part).strip()
        if not query:
            continue
        try:
            result = search(query)
        except Exception as exc:  # noqa: BLE001 - the catalog may hiccup
            log.info("lyric resolve search failed for %r: %s", query, exc)
            continue
        found: Track | None = None
        if isinstance(result, Track):
            found = result
        elif isinstance(result, list):
            found = next(
                (t for t in result if isinstance(t, Track) and t.video_id),
                None,
            )
        if found is None or not found.video_id or found.video_id in seen:
            continue
        seen.add(found.video_id)
        tracks.append(found)
    return tracks
