"""Queue comforts — pure arithmetic for the up-next list.

Everything the queue panel shows besides the rows themselves: how long
the road ahead runs, a clean reverse, and a de-duper that keeps the
first copy. No Qt — the window hands these plain lists and paints what
comes back.
"""

from __future__ import annotations


def remaining_seconds(durations_sec: list[float | int | None]) -> int:
    """Total seconds in a list of track durations.

    Unknown durations (None or junk) count as zero — the label says what
    it knows, never a guess dressed up as a fact. Negative values are
    clamped; time does not run backwards.
    """
    total = 0
    for d in durations_sec or []:
        try:
            total += max(0, int(d))
        except (TypeError, ValueError):
            continue
    return total


def fmt_remaining(total_sec: int) -> str:
    """A human label for the road ahead: '42 min left', '1 h 12 min left'.

    Zero stays honest ('0 min left') — an empty queue is a fact, not a
    blank. Hours and minutes never mix with seconds; nobody needs '3 min
    42 sec left' on a shelf label.
    """
    total = max(0, int(total_sec))
    minutes = total // 60
    hours, mins = divmod(minutes, 60)
    if hours:
        return f"{hours} h {mins} min left"
    return f"{mins} min left"


def remaining_label(durations_sec: list[float | int | None]) -> str:
    """One call: durations in, queue label out."""
    return fmt_remaining(remaining_seconds(durations_sec))


def reverse_upcoming(items: list) -> list:
    """A reversed copy — the queue panel re-renders from what returns."""
    return list(reversed(items))


def dedupe(items: list, key=lambda x: x) -> list:
    """First copy of each key wins; later twins silently drop out.

    Order is otherwise untouched, so 'remove duplicates' never shuffles
    someone's careful line-up. Keys may be unhashable — identity is
    checked with an == scan, fine at queue sizes.
    """
    seen: list = []
    out: list = []
    for item in items:
        k = key(item)
        if any(k == s for s in seen):
            continue
        seen.append(k)
        out.append(item)
    return out


__all__ = [
    "remaining_seconds", "fmt_remaining", "remaining_label",
    "reverse_upcoming", "dedupe",
]
