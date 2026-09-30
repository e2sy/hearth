"""Hotkey binding helpers and conflict detection."""

from __future__ import annotations

from .config import DEFAULT_HOTKEYS, RESERVED_CHORDS


def find_hotkey_conflicts(chords: dict[str, str]) -> list[str]:
    """Return human-readable problems with a chord map.

    Detects (1) two actions bound to the same chord, and (2) bindings
    that shadow well-known system shortcuts (RESERVED_CHORDS).
    """
    problems: list[str] = []
    seen: dict[str, str] = {}
    for action, chord in chords.items():
        c = (chord or "").strip()
        if not c:
            problems.append(f"action '{action}' has an empty chord")
            continue
        if c.lower() in seen:
            problems.append(f"'{c}' is bound to both '{seen[c.lower()]}' and '{action}'")
        else:
            seen[c.lower()] = action
    lowered_reserved = {r.lower(): r for r in RESERVED_CHORDS}
    for action, chord in chords.items():
        c = (chord or "").strip()
        if c.lower() in lowered_reserved:
            problems.append(f"'{c}' ({action}) shadows a system shortcut")
    return problems


def effective_chords(overrides: dict[str, str] | None = None) -> dict[str, str]:
    """Merge user overrides on top of the defaults (invalid entries ignored)."""
    merged = dict(DEFAULT_HOTKEYS)
    for action, chord in (overrides or {}).items():
        if action in merged and (chord or "").strip():
            merged[action] = chord.strip()
    return merged
