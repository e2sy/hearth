"""Diagnostics report: one honest page about the fire's health.

`gather_report()` folds the app's identity, the look, the database
shape, the catalogue-resilience counters and (when reachable) the tail
of hearth.log into a single human-readable string. Pure and never
raises — a diagnostics page that crashes would be a poor apology.
"""

from __future__ import annotations

import platform
import sys
from pathlib import Path

from . import config

LOG_TAIL_LINES = 40
LOG_FILE_NAME = "hearth.log"

_DB_TABLES = ("favorites", "history", "playlists")


def _row_count(store, table: str):
    """Row count of one table, or '?' when the store won't tell."""
    try:
        db = getattr(store, "_db", None)
        if db is None:
            return "?"
        (count,) = db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
        return int(count)
    except Exception:  # noqa: BLE001 - a locked/corrupt table is still a fact
        return "?"


def _identity_lines() -> list[str]:
    lines = [
        f"🔥 {config.APP_NAME} diagnostics",
        f"version:   {config.VERSION}",
        f"platform:  {platform.platform()}",
        f"python:    {sys.version.split()[0]}",
    ]
    try:
        lines.append(f"repo:      {config.REPO_URL}")
    except Exception:  # noqa: BLE001
        pass
    return lines


def _look_lines() -> list[str]:
    try:
        from . import theme   # lazy: keeps this module importable anywhere

        style = "?"
        try:
            style = str(theme.active_style())
        except Exception:  # noqa: BLE001
            pass
        return [
            f"look:      palette={config.DEFAULT_PALETTE} "
            f"packs={len(config.PALETTES)} style={style}"
        ]
    except Exception:  # noqa: BLE001
        return ["look:      (theme unavailable)"]


def _store_lines(store) -> list[str]:
    try:
        db_path = getattr(store, "db_path", "?")
    except Exception:  # noqa: BLE001
        db_path = "?"
    lines = [f"database:  {db_path}"]
    for table in _DB_TABLES:
        lines.append(f"  {table:<12}{_row_count(store, table):>8} rows")
    return lines


def _resilience_lines(resilience) -> list[str]:
    """Which fetch legs served the shelves — whatever the caller knows.

    `resilience` may be the ytm_resilience module, a plain dict of leg
    counters, or anything else; the report only ever probes politely.
    """
    if resilience is None:
        return ["catalogue: (no resilience info)"]
    try:
        if isinstance(resilience, dict):
            if not resilience:
                return ["catalogue: (no counters recorded)"]
            lines = ["catalogue fetch legs (resilience counters):"]
            for key in sorted(resilience):
                lines.append(f"  {key}: {resilience[key]}")
            return lines
        lines: list[str] = ["catalogue resilience:"]
        applied = getattr(resilience, "_APPLIED", None)
        if applied is not None:
            state = "applied ✓" if applied else "off"
            lines.append(f"  junk-card tolerance: {state}")
        counters = getattr(resilience, "counters", None)
        if isinstance(counters, dict) and counters:
            for key in sorted(counters):
                lines.append(f"  {key}: {counters[key]}")
        if len(lines) == 1:
            lines.append("  (no counters exposed)")
        return lines
    except Exception as exc:  # noqa: BLE001
        return [f"catalogue: (resilience probe failed: {exc})"]


def _log_tail_lines(store) -> list[str]:
    """The last few log lines, when hearth.log lives beside the database."""
    try:
        db_path = Path(str(getattr(store, "db_path", "")))
        log_path = db_path.parent / LOG_FILE_NAME
        if not log_path.is_file():
            return []
        text = log_path.read_text(encoding="utf-8", errors="replace")
        tail = [line for line in text.splitlines() if line.strip()][-LOG_TAIL_LINES:]
        if not tail:
            return []
        lines = [f"log tail (last {len(tail)} lines of {LOG_FILE_NAME}):"]
        lines.extend(f"  | {line}" for line in tail)
        return lines
    except Exception:  # noqa: BLE001 - no log, no problem
        return []


def _fetch_leg_lines(counters) -> list[str]:
    """Per-leg fetch counters (v0.7.1): which leg served, starved, failed.

    `counters` is the Catalog's flat dict ("search-songs.ok" -> 12, ...).
    Anything missing, wrong-shaped, or empty degrades to a polite
    nothing — counters are the last thing allowed to ruin a report.
    """
    try:
        if not isinstance(counters, dict) or not counters:
            return []
        lines = ["fetch legs (this session):"]
        for key in sorted(counters):
            lines.append(f"  {key}: {counters[key]}")
        return lines
    except Exception:  # noqa: BLE001 - bookkeeping must stay invisible
        return []


def gather_report(store, resilience=None, fetch_counters=None) -> str:
    """The full health page as one multi-line string. Never raises."""
    sections: list[list[str]] = []
    try:
        sections.append(_identity_lines())
    except Exception as exc:  # noqa: BLE001
        sections.append([f"(identity unavailable: {exc})"])
    try:
        sections.append(_look_lines())
    except Exception as exc:  # noqa: BLE001
        sections.append([f"(look unavailable: {exc})"])
    try:
        sections.append(_store_lines(store))
    except Exception as exc:  # noqa: BLE001
        sections.append([f"(database unavailable: {exc})"])
    try:
        sections.append(_resilience_lines(resilience))
    except Exception as exc:  # noqa: BLE001
        sections.append([f"(resilience unavailable: {exc})"])
    try:
        sections.append(_fetch_leg_lines(fetch_counters))
    except Exception as exc:  # noqa: BLE001
        sections.append([f"(fetch legs unavailable: {exc})"])
    try:
        sections.append(_log_tail_lines(store))
    except Exception as exc:  # noqa: BLE001
        sections.append([f"(log tail unavailable: {exc})"])

    lines: list[str] = []
    for section in sections:
        if section:
            lines.extend(section)
            lines.append("")
    lines.append("keep the fire warm 🔥")
    return "\n".join(lines)
