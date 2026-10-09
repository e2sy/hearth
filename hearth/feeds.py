"""Room 10 — The Ember Feed: the hearth knows what you'll love next.

Local-first personalization: everything here is computed from the
SQLite play log you already own. No accounts, no clouds, no keys —
the only network touch is an injected fetcher the caller controls
(release-radar sweeps, radio refills), and every function degrades to
an honest empty list when the local signal is thin.

- weekly_ember_feed(): the Friday mix — heavy rotation cooling off,
  deep cuts from your own history, fresh blood from your rotation
  artists' quieter corners.
- daylist(): the day has a sound. An hour-of-day model over history.
- sweep_artist(): release radar — one followed artist, one fetch,
  only the genuinely new come back.
- queue_suggestions(): radio-shaped suggestions for a drying queue,
  marked as suggestions and never repeating what's already queued.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from . import config
from .models import Track
from .storage import HearthStore

# Local-midnight-anchored day buckets: the daylist's four rooms.
DAY_BUCKETS = (
    ("morning", 5, 12),    # 05:00–11:59
    ("afternoon", 12, 17), # 12:00–16:59
    ("evening", 17, 22),   # 17:00–21:59
    ("night", 22, 24),     # 22:00–04:59 (wraps)
    ("night", 0, 5),
)


def day_bucket(hour: int) -> str:
    """0–23 → 'morning' | 'afternoon' | 'evening' | 'night'."""
    hour = int(hour) % 24
    for name, start, end in DAY_BUCKETS:
        if start <= hour < end:
            return name
    return "night"


@dataclass
class DaylistMix:
    """A time-of-day mix: which room of the day it serves, and its tracks."""

    bucket: str
    tracks: list[Track] = field(default_factory=list)

    @property
    def display_name(self) -> str:
        return f"{self.bucket} daylist"


def daylist(
    store: HearthStore,
    now: float | None = None,
    limit: int = config.DAYLIST_SIZE,
) -> DaylistMix:
    """The daylist: tracks you love *at this hour*, from history alone.

    Pure SQL over existing rows — hour-of-day weighting with a recency
    nudge (newest payload wins per video id). A cold library falls back
    to the On Repeat decay list, so the shelf is never embarrassed.
    Deterministic against a fixed store.
    """
    stamp = time.time() if now is None else float(now)
    bucket = day_bucket(_local_hour(stamp))
    start, end = _bucket_hours(bucket)
    rows = store._db.execute(
        "SELECT video_id, payload, played_at FROM history ORDER BY id DESC"
    ).fetchall()
    bucket_plays: dict[str, int] = {}
    recency: dict[str, float] = {}
    newest: dict[str, str] = {}
    for video_id, payload, played_at in rows:
        if video_id not in newest:
            newest[video_id] = payload
        hour = _local_hour(float(played_at))
        in_bucket = (start <= hour < end) if start < end else (hour >= start or hour < end)
        if in_bucket:
            bucket_plays[video_id] = bucket_plays.get(video_id, 0) + 1
        recency[video_id] = max(recency.get(video_id, 0.0), float(played_at))
    ranked: list[tuple[Track, int]] = []
    for video_id, plays in bucket_plays.items():
        try:
            track = Track.from_json(newest[video_id])
        except (TypeError, ValueError):
            continue
        ranked.append((track, plays))
    ranked.sort(key=lambda pair: (-pair[1], -recency[pair[0].video_id],
                                  str(pair[0].title).lower()))
    tracks = [track for track, _plays in ranked[: max(int(limit), 0)]]
    if not tracks:
        tracks = store.on_repeat(limit=max(int(limit), 0))
    return DaylistMix(bucket=bucket, tracks=tracks)


def weekly_ember_feed(
    store: HearthStore,
    now: float | None = None,
    limit: int = config.EMBER_FEED_SIZE,
) -> list[Track]:
    """The weekly mix: cooling rotation, deep cuts, rotation-artist B-sides.

    The blend, in order of the feed's promise:
    1. **Cooling rotation** — tracks with many raw plays whose decayed
       score has slid down the table (you loved them, lately less).
    2. **Deep cuts** — pinned favorites you barely spin (rare gems).
    3. **Rotation B-sides** — other tracks by your heavy-rotation
       artists, pulled from your own history payloads (offline kindred).

    Deduped by video_id, never contains what you played *today*, and
    deterministic against a fixed store. A cold library degrades to the
    On Repeat list — an empty shelf is the last resort of last resorts.
    """
    limit = max(int(limit), 0)
    if limit == 0:
        return []
    stamp = time.time() if now is None else float(now)
    lt = time.localtime(stamp)
    midnight = time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, 0, 0, 0, 0, 0, -1))

    scores = store.on_repeat_scores(limit=max(limit * 3, 60))
    plays_by_id: dict[str, int] = {}
    play_rows = store._db.execute(
        "SELECT video_id, COUNT(*) AS plays, MAX(played_at) AS last_play "
        "FROM history GROUP BY video_id"
    ).fetchall()
    for video_id, plays, last_play in play_rows:
        plays_by_id[str(video_id)] = int(plays)
        if float(last_play) >= midnight:
            plays_by_id[str(video_id)] = -1  # played today — the feed skips it

    picked: list[Track] = []
    seen: set[str] = set()

    def _take(track: Track) -> bool:
        if track.video_id in seen or plays_by_id.get(track.video_id, 0) < 0:
            return False
        seen.add(track.video_id)
        picked.append(track)
        return True

    # 1) cooling rotation: ranked by raw plays among the *lower half* of
    #    the decay table — hot once, sliding now.
    if scores:
        cut = max(1, len(scores) // 2)
        cooling = sorted(
            scores[cut:],
            key=lambda pair: (-plays_by_id.get(pair[0].video_id, 0),
                              str(pair[0].title).lower()),
        )
        cooling_quota = max(1, int(limit * config.EMBER_FEED_COOLING_SHARE))
        for track, _score in cooling:
            if len(picked) >= cooling_quota:
                break
            _take(track)

    # 2) deep cuts: pinned but barely spun.
    for track in store.smart_rare_gems(limit=limit):
        if len(picked) >= limit:
            break
        _take(track)

    # 3) rotation B-sides: other history tracks by your top rotation artists.
    rotation_artists = {
        track.artist.strip().lower() for track, _score in scores[:8]
        if track.artist.strip()
    }
    if rotation_artists and len(picked) < limit:
        rows = store._db.execute(
            "SELECT payload FROM history GROUP BY video_id "
            "ORDER BY MAX(played_at) DESC LIMIT 400"
        ).fetchall()
        for (payload,) in rows:
            if len(picked) >= limit:
                break
            try:
                track = Track.from_json(payload)
            except (TypeError, ValueError):
                continue
            if track.artist.strip().lower() in rotation_artists:
                _take(track)

    # 4) whatever is still short: the decay list itself, top first.
    for track, _score in scores:
        if len(picked) >= limit:
            break
        _take(track)

    return picked[:limit]


def sweep_artist(
    store: HearthStore,
    artist_id: str,
    fetch_releases,
    now: float | None = None,
) -> list[Track]:
    """Release radar for one followed artist — returns only what's new.

    `fetch_releases(artist_id)` must return ``list[Track]`` (network
    lives in the caller, tests hand a fake). New video ids are marked
    seen with their payload so the shelf reads offline later. A fetch
    failure (caller returns []) is an honest no-op, never an error.
    """
    releases = fetch_releases(artist_id) or []
    if not isinstance(releases, list):
        return []
    releases = [t for t in releases if isinstance(t, Track) and t.video_id]
    new_ids = store.radar_sweep_seen(artist_id, releases, now=now)
    out: list[Track] = []
    for track in releases:
        if track.video_id in new_ids and all(t.video_id != track.video_id for t in out):
            out.append(track)
    return out


def queue_suggestions(
    queue_ids: list[str],
    radio_fetch,
    seed_id: str = "",
    n: int = config.QUEUE_AUTOCOMPLETE_N,
) -> list[Track]:
    """Marked suggestions for a drying queue — never repeats the queued.

    `radio_fetch(video_id)` returns ``list[Track]`` (the same radio call
    autoplay uses). Suggestions are ordered, deduped against the queue
    and each other, and capped at `n`. A radio failure is an empty
    suggestion list — the queue stays exactly as the user left it.
    """
    n = max(int(n), 0)
    if n == 0:
        return []
    seed = str(seed_id or (queue_ids[-1] if queue_ids else ""))
    if not seed:
        return []
    try:
        candidates = radio_fetch(seed) or []
    except Exception:  # noqa: BLE001 — network layer must not crash UI
        return []
    queued = {str(v) for v in queue_ids}
    out: list[Track] = []
    for track in candidates:
        if not isinstance(track, Track) or not track.video_id:
            continue
        if track.video_id in queued or track.video_id in {t.video_id for t in out}:
            continue
        out.append(track)
        if len(out) >= n:
            break
    return out


def _local_hour(stamp: float) -> int:
    """Local hour-of-day (0–23) for an epoch stamp."""
    return time.localtime(stamp).tm_hour


def _bucket_hours(bucket: str) -> tuple[int, int]:
    """The (start, end) window of a day bucket (night wraps)."""
    for name, start, end in DAY_BUCKETS:
        if name == bucket:
            return (start, end)
    return (22, 24)
