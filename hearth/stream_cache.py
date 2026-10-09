"""Room 12 — The Pantry: yesterday's warmth for tomorrow's cold start.

A disk LRU cache of resolved audio streams. Replayed tracks start
instantly and survive short network drops; the next queue entries can
pre-warm the Pantry while the current song plays.

Honest scope (per the roadmap row): this is a *replay shelf*, not a
download store. Nothing here ever fetches on its own initiative — the
caller decides what goes in. File mtimes are the recency order, so a
hit touches and an eviction drops the coldest shelf first.

Every path is never-raises: a broken root, a full disk, or a vanished
file degrade to a miss, never an exception on the audio path.
"""

from __future__ import annotations

import os
from pathlib import Path

from . import config

DEFAULT_MAX_BYTES = config.STREAM_CACHE_MAX_MB * 1024 * 1024


class StreamCache:
    """A size-capped, mtime-ordered disk cache keyed by video id."""

    def __init__(self, root: str | Path, max_bytes: int = DEFAULT_MAX_BYTES):
        self.root = Path(root)
        self.max_bytes = max(1, int(max_bytes))

    # --- reads ---

    def path_for(self, video_id: str) -> Path | None:
        """The cached file for a video id, or None on a miss.

        A hit also refreshes the file's mtime (an LRU touch) — playing
        a track is the strongest signal it should survive eviction.
        """
        path = self._slot(video_id)
        if path is None or not path.is_file():
            return None
        try:
            os.utime(path, None)
        except OSError:
            pass  # the touch is an optimization, never a requirement
        return path

    def has(self, video_id: str) -> bool:
        path = self._slot(video_id)
        return path is not None and path.is_file()

    def size(self) -> int:
        """Total cached bytes (best effort — unreadable files count as 0)."""
        total = 0
        for path in self._files():
            try:
                total += path.stat().st_size
            except OSError:
                continue
        return total

    def item_count(self) -> int:
        return len(self._files())

    # --- writes ---

    def store(self, video_id: str, data: bytes) -> Path | None:
        """Cache one stream's bytes; returns the path, or None on failure.

        Overwrites any previous entry for the id, then trims the Pantry
        back under its cap (this entry survives its own trim).
        """
        path = self._slot(video_id)
        if path is None or not data:
            return None
        try:
            self.root.mkdir(parents=True, exist_ok=True)
            path.write_bytes(bytes(data))
        except OSError:
            return None
        self.trim(keep=video_id)
        return path

    def trim(self, keep: str = "") -> int:
        """Evict coldest files until under cap. Returns files removed.

        `keep` protects one id (the entry just written, or the track
        currently playing) from its own eviction round.
        """
        entries: list[tuple[float, Path, int]] = []
        for path in self._files():
            try:
                stat = path.stat()
            except OSError:
                continue
            entries.append((stat.st_mtime, path, stat.st_size))
        entries.sort()  # coldest (oldest mtime) first — an LRU, not an MRU
        total = sum(size for _m, _p, size in entries)
        removed = 0
        for _mtime, path, size in entries:
            if total <= self.max_bytes:
                break
            if path.stem == keep:
                continue
            try:
                path.unlink()
            except OSError:
                continue
            total -= size
            removed += 1
        return removed

    def clear(self) -> int:
        """The broom: drop every cached file. Returns files removed.

        Safe to call while playing — the player holds its own open
        handle/URL, and a mid-play clear costs nothing but a miss later.
        """
        removed = 0
        for path in self._files():
            try:
                path.unlink()
                removed += 1
            except OSError:
                continue
        return removed

    # --- internals ---

    def _slot(self, video_id: str) -> Path | None:
        """The one file slot for an id; None for ids that can't be safe names."""
        video_id = str(video_id or "").strip()
        if not video_id or "/" in video_id or "\\" in video_id or video_id in (".", ".."):
            return None
        return self.root / f"{video_id}.audio"

    def _files(self) -> list[Path]:
        try:
            return [p for p in self.root.glob("*.audio") if p.is_file()]
        except OSError:
            return []
