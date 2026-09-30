"""The Rewind story: your listening year, told in a few honest scenes.

Pure data → pure words. `build_rewind_story` consumes the same shapes
`HearthStore.stats_summary()`, `history_days()` and `top_tracks()` already
produce and returns a list of scene strings — no Qt, no I/O, no network,
so it is fully unit-testable and safe to call from any thread.

The StatsView dialog just paints whatever scenes come back. Degradation
is graceful by design: a thin or empty history still yields a cozy honest
line ("the hearth is unlit") instead of a chart of zeroes or a crash.
Every scene is self-contained, so the caller can show as few or as many
as fit the screen.
"""

from __future__ import annotations

import calendar
from datetime import datetime, timedelta
from typing import Any, Iterable

MAX_SCENES = 8          # the story stays a story, not a ledger
STREAK_MIN = 2          # a "streak" of one day is just a Tuesday
EMPTY_STORY = [
    "🕯️ The hearth is unlit — press play, and this page becomes your year.",
]


def _fmt_day(day: str) -> str:
    """'2026-03-07' -> 'March 7, 2026'; odd input comes back unchanged."""
    try:
        year, month, mday = (int(part) for part in day.split("-"))
        return f"{calendar.month_name[month]} {mday}, {year}"
    except (ValueError, AttributeError, IndexError, TypeError):
        return str(day)


def _fmt_month(month: str) -> str:
    """'2026-03' -> 'March 2026'; odd input comes back unchanged."""
    try:
        year, month_num = (int(part) for part in month.split("-"))
        return f"{calendar.month_name[month_num]} {year}"
    except (ValueError, AttributeError, IndexError, TypeError):
        return str(month)


def peak_day(days: Iterable[tuple[str, int]]) -> tuple[str, int] | None:
    """The single loudest day: ('2026-03-07', 42). None when nothing played."""
    best: tuple[str, int] | None = None
    for day, count in days or []:
        try:
            count = int(count)
        except (TypeError, ValueError):
            continue
        if best is None or count > best[1]:
            best = (str(day), count)
    return best


def longest_streak(days: Iterable[tuple[str, int]], minimum: int = STREAK_MIN) -> int:
    """Longest run of consecutive lit days, from plain date strings."""
    parsed: set[datetime] = set()
    for day, _count in days or []:
        try:
            parsed.add(datetime.strptime(str(day), "%Y-%m-%d"))
        except ValueError:
            continue
    best = 0
    while parsed:
        current = min(parsed)
        streak = 1
        while True:
            nxt = current + timedelta(days=1)
            if nxt not in parsed:
                break
            parsed.discard(nxt)
            current = nxt
            streak += 1
        parsed.discard(current)
        best = max(best, streak)
    return best if best >= max(int(minimum), 1) else 0


def busiest_month(days: Iterable[tuple[str, int]]) -> tuple[str, int] | None:
    """The month with the most plays: ('2026-03', 412). None when thin."""
    months: dict[str, int] = {}
    for day, count in days or []:
        try:
            count = int(count)
        except (TypeError, ValueError):
            continue
        key = str(day)[:7]
        if len(key) == 7:
            months[key] = months.get(key, 0) + count
    if not months:
        return None
    key = sorted(months.items(), key=lambda item: (-item[1], item[0]))[0][0]
    return (key, months[key])


def build_rewind_story(
    stats: dict[str, Any],
    days: Iterable[tuple[str, int]],
    top_tracks: list,
    top_artists: list[tuple[str, int]],
) -> list[str]:
    """Weave stats + history into a short stack of scene lines.

    `stats` is the dict from HearthStore.stats_summary(); `days` the
    (date, plays) pairs from history_days(); `top_tracks`/`top_artists`
    the ranked lists the dashboard already shows. Returns at most
    MAX_SCENES lines; an empty history returns EMPTY_STORY untouched.
    """
    stats = stats or {}
    plays = int(stats.get("total_plays") or 0)
    if plays <= 0:
        return list(EMPTY_STORY)

    minutes = int(stats.get("est_minutes") or 0)
    days_listened = int(stats.get("days_listened") or 0)
    uniques = int(stats.get("unique_tracks") or 0)
    day_items = list(days or [])
    track_items = list(top_tracks or [])
    artist_items = list(top_artists or [])

    scenes: list[str] = [
        f"🔥 {plays:,} plays · {minutes:,} minutes · {days_listened} days by the fire"
    ]

    first_play = stats.get("first_play")
    if first_play:
        try:
            begun = datetime.fromisoformat(str(first_play))
            scenes.append(f"🌱 It all began on {begun.strftime('%B %d, %Y')}")
        except ValueError:
            pass

    if uniques:
        scenes.append(f"🧭 {uniques:,} different tracks crossed the hearth")

    if artist_items:
        name, count = artist_items[0][0], artist_items[0][1]
        if name:
            scenes.append(f"🎤 {name} owned your year — {count:,} plays")

    if track_items:
        track = track_items[0]
        title = getattr(track, "title", "") or "an untitled flame"
        artist = getattr(track, "artist", "") or "an unknown voice"
        scenes.append(f"🎵 “{title}” — {artist} — was the song you kept returning to")

    peak = peak_day(day_items)
    if peak and peak[1] > 0:
        scenes.append(f"🎈 {_fmt_day(peak[0])} burned brightest — {peak[1]} plays in one day")

    streak = longest_streak(day_items)
    if streak:
        scenes.append(f"🌌 A {streak}-day streak — the fire never went out")

    month = busiest_month(day_items)
    if month and month[1] > 0:
        scenes.append(f"🗓️ {_fmt_month(month[0])} was your loudest month — {month[1]:,} plays")

    return scenes[:MAX_SCENES]
