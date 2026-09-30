"""Folder scanner for the local library — filename forensics, honest limits.

Walks each music folder, pulls Artist/Title out of filenames, and hands
the results back as upsert-ready dicts. `parse_track_name` is pure and
heavily tested; the walk honors a file cap and a soft timeout so a huge
or slow disk can never stall the app.

There is deliberately NO duration probing: reading real durations would
mean loading every file through QMediaPlayer (seconds per file) — not
cheap, so unknown durations stay 0 and render as an honest "—".

`LocalScanJob` runs the whole walk on a QThreadPool worker (never the
UI thread) and never touches the store — the app upserts on the main
thread in one transaction.
"""

from __future__ import annotations

import logging
import os
import re
import time
from pathlib import Path

from PyQt6.QtCore import QRunnable

from . import config
from .jobs import _SignalCarrier

log = logging.getLogger(__name__)

# A leading track number: "07. ", "3 - ", "12_" before the real name.
_TRACK_NO_RE = re.compile(r"^\d{1,3}\s*[-._]?\s+")


def parse_track_name(path: str | Path) -> tuple[str, str]:
    """(artist, title) from a filename — PURE, no disk access.

    Patterns tried in order on the de-suffixed, underscore-spaced stem:

    ========================  ==========================
    ``07. Artist - Title``    ``("Artist", "Title")``
    ``Artist - Title``        ``("Artist", "Title")``
    ``07 Title``              ``("", "Title")``
    ``Title``                 ``("", "Title")``
    ========================  ==========================

    Underscores become spaces; letter case is preserved exactly as the
    file spells it. Only the spaced " - " separator splits artist from
    title — "Don't-Stop" stays whole. A song named "1979" behind a dash
    survives: at most three leading digits are treated as a track number.
    """
    stem = Path(path).stem.replace("_", " ").strip()
    stripped = _TRACK_NO_RE.sub("", stem, count=1).strip() or stem
    if " - " in stripped:
        artist, _sep, title = stripped.partition(" - ")
        return artist.strip(), title.strip()
    return "", stripped


def collect_local_tracks(
    roots: list[str | Path],
    cap: int | None = None,
    timeout_s: float | None = None,
) -> tuple[list[dict], dict]:
    """Walk `roots` and parse every audio file into upsert-ready dicts.

    Returns ``(entries, stats)`` where stats is::

        {"scanned": audio files accepted,
         "skipped": files ignored (non-audio),
         "truncated": whether the cap or the soft timeout cut the walk}

    `cap` bounds the number of audio files (default ``config.LOCAL_SCAN_CAP``)
    and `timeout_s` is a soft wall-clock budget for the walk. Entries are
    deduped by path, so overlapping roots cannot double-count a file.
    """
    cap = config.LOCAL_SCAN_CAP if cap is None else max(0, int(cap))
    timeout_s = (
        config.LOCAL_SCAN_TIMEOUT_S if timeout_s is None else float(timeout_s)
    )
    deadline = time.monotonic() + max(0.0, timeout_s)
    suffixes = tuple(s.lower() for s in config.LOCAL_AUDIO_SUFFIXES)

    entries: list[dict] = []
    seen: set[str] = set()
    scanned = 0
    skipped = 0
    truncated = False

    for root in roots:
        root_path = Path(root)
        if not root_path.is_dir():
            continue
        for dirpath, dirnames, filenames in os.walk(root_path):
            dirnames.sort()
            filenames.sort()
            for name in filenames:
                if not name.lower().endswith(suffixes):
                    skipped += 1
                    continue
                if scanned >= cap:
                    truncated = True
                    break
                path = str(Path(dirpath) / name)
                if path in seen:
                    continue
                seen.add(path)
                artist, title = parse_track_name(path)
                entries.append({
                    "path": path,
                    "title": title,
                    "artist": artist,
                    "album": "",
                    "duration_s": 0.0,     # honest: probed durations cost seconds/file
                })
                scanned += 1
            if truncated:
                break
            if time.monotonic() > deadline:
                truncated = True
                break
        if truncated:
            break
    return entries, {"scanned": scanned, "skipped": skipped, "truncated": truncated}


class LocalScanJob(QRunnable):
    """Walks + parses music folders on a pool thread; never touches the store.

    Emits ``(entries, stats)`` on finished — the app turns entries into
    upserts on the main thread. Catastrophic trouble (a vanished root
    mid-walk, a permission storm) lands on failed as a short message.
    """

    def __init__(self, roots: list[str | Path],
                 cap: int | None = None, timeout_s: float | None = None):
        super().__init__()
        self.setAutoDelete(False)   # lifetime managed by Hearth._launch
        self.signals = _SignalCarrier()
        self.roots = [str(r) for r in roots]
        self.cap = cap
        self.timeout_s = timeout_s

    def run(self) -> None:   # noqa: D102 - QRunnable entry
        try:
            payload = collect_local_tracks(self.roots, self.cap, self.timeout_s)
        except Exception as exc:   # noqa: BLE001 - a worker must not crash the pool
            log.info("local scan failed: %s", exc, exc_info=True)
            self.signals.emit_safe(self.signals.failed, str(exc))
            return
        self.signals.emit_safe(self.signals.finished, payload)
