"""SQLite favorites & playback history — zero external bloat."""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import time
from datetime import datetime
from pathlib import Path

from .config import (
    HISTORY_PAGE_SIZE,
    ON_REPEAT_DECAY_DAYS,
    ON_REPEAT_LIMIT,
    STATS_TOP_LIMIT,
)
from .models import Track, format_duration, parse_duration

_SCHEMA = """
CREATE TABLE IF NOT EXISTS favorites (
    video_id   TEXT PRIMARY KEY,
    payload    TEXT NOT NULL,
    created_at REAL NOT NULL DEFAULT (unixepoch('now'))
);
CREATE TABLE IF NOT EXISTS history (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    video_id   TEXT NOT NULL,
    payload    TEXT NOT NULL,
    played_at  REAL NOT NULL DEFAULT (unixepoch('now'))
);
CREATE INDEX IF NOT EXISTS idx_history_played ON history (played_at DESC);
CREATE TABLE IF NOT EXISTS playlists (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT NOT NULL,
    created_at REAL NOT NULL DEFAULT (unixepoch('now'))
);
CREATE TABLE IF NOT EXISTS playlist_tracks (
    playlist_id INTEGER NOT NULL REFERENCES playlists(id) ON DELETE CASCADE,
    position    INTEGER NOT NULL,
    video_id    TEXT NOT NULL,
    payload     TEXT NOT NULL,
    PRIMARY KEY (playlist_id, position)
);
CREATE TABLE IF NOT EXISTS queue_snapshot (
    id          INTEGER PRIMARY KEY CHECK (id = 1),
    video_ids   TEXT NOT NULL,
    idx         INTEGER NOT NULL DEFAULT 0,
    position_ms INTEGER NOT NULL DEFAULT 0,
    updated_at  REAL NOT NULL DEFAULT (unixepoch('now'))
);
CREATE TABLE IF NOT EXISTS track_prefs (
    video_id TEXT NOT NULL,
    key      TEXT NOT NULL,
    value    REAL NOT NULL,
    PRIMARY KEY (video_id, key)
);
CREATE TABLE IF NOT EXISTS local_tracks (
    video_id   TEXT PRIMARY KEY,
    path       TEXT NOT NULL UNIQUE,
    title      TEXT NOT NULL,
    artist     TEXT NOT NULL DEFAULT '',
    album      TEXT NOT NULL DEFAULT '',
    duration_s REAL NOT NULL DEFAULT 0,
    added_at   REAL NOT NULL DEFAULT (unixepoch('now'))
);
"""

# Bare URLs in an .m3u carry the video id in a v= query parameter.
_VIDEO_ID_RE = re.compile(r"[?&]v=([A-Za-z0-9_-]+)")


class HearthStore:
    """Persistent local library (favorites) and listening history."""

    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(self.db_path))
        self._db.execute("PRAGMA foreign_keys = ON")
        self._db.executescript(_SCHEMA)
        self._db.commit()

    def close(self) -> None:
        self._db.close()

    # --- favorites ---

    def pin(self, track: Track) -> None:
        self._db.execute(
            "INSERT OR REPLACE INTO favorites (video_id, payload) VALUES (?, ?)",
            (track.video_id, track.to_json()),
        )
        self._db.commit()

    def unpin(self, video_id: str) -> None:
        self._db.execute("DELETE FROM favorites WHERE video_id = ?", (video_id,))
        self._db.commit()

    def is_pinned(self, video_id: str) -> bool:
        row = self._db.execute(
            "SELECT 1 FROM favorites WHERE video_id = ?", (video_id,)
        ).fetchone()
        return row is not None

    def favorites(self) -> list[Track]:
        rows = self._db.execute(
            "SELECT payload FROM favorites ORDER BY created_at DESC, rowid DESC"
        ).fetchall()
        return [Track.from_json(payload) for (payload,) in rows]

    # --- history ---

    def log_play(self, track: Track, played_at: float | None = None) -> None:
        """Record a play; `played_at` backfills an older moment (tests, imports)."""
        if played_at is None:
            self._db.execute(
                "INSERT INTO history (video_id, payload) VALUES (?, ?)",
                (track.video_id, track.to_json()),
            )
        else:
            self._db.execute(
                "INSERT INTO history (video_id, payload, played_at) VALUES (?, ?, ?)",
                (track.video_id, track.to_json(), float(played_at)),
            )
        self._db.commit()

    def history(self, limit: int = 100) -> list[Track]:
        rows = self._db.execute(
            "SELECT payload FROM history ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [Track.from_json(payload) for (payload,) in rows]

    def top_tracks(self, limit: int = 10) -> list[Track]:
        """Most-played tracks; ties broken by most-recent play."""
        rows = self._db.execute(
            "SELECT payload FROM history GROUP BY video_id "
            "ORDER BY COUNT(*) DESC, MAX(played_at) DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [Track.from_json(payload) for (payload,) in rows]

    # --- smart shelves (v0.7.1): auto-refreshing playlists with no upkeep ---

    def smart_most_played(self, limit: int = 25) -> list[Track]:
        """The all-time rotation: most-played first, newest payload wins.

        Same grouping contract as top_tracks() but sized for a shelf and
        guarded against corrupt rows — a broken payload is skipped, never
        allowed to blank the shelf.
        """
        rows = self._db.execute(
            "SELECT payload FROM history GROUP BY video_id "
            "ORDER BY COUNT(*) DESC, MAX(played_at) DESC LIMIT ?",
            (max(int(limit), 0),),
        ).fetchall()
        tracks: list[Track] = []
        for (payload,) in rows:
            try:
                tracks.append(Track.from_json(payload))
            except (TypeError, ValueError):
                continue
        return tracks

    def smart_recently_loved(self, limit: int = 25, days: int = 30) -> list[Track]:
        """Favorites pinned within the last `days` days, newest pin first.

        The "what did I add to my heart lately" shelf — reads the
        favorites table's own created_at, so unfavorite/refavorite
        cycles honestly refresh a track's place here.
        """
        cutoff = time.time() - max(int(days), 0) * 86400.0
        rows = self._db.execute(
            "SELECT payload FROM favorites WHERE created_at >= ? "
            "ORDER BY created_at DESC, rowid DESC LIMIT ?",
            (cutoff, max(int(limit), 0)),
        ).fetchall()
        tracks: list[Track] = []
        for (payload,) in rows:
            try:
                tracks.append(Track.from_json(payload))
            except (TypeError, ValueError):
                continue
        return tracks

    def smart_rare_gems(self, limit: int = 25, max_plays: int = 2) -> list[Track]:
        """Favorites you barely spin — pinned, but played ≤ `max_plays` times.

        The quiet corner of the library: tracks you loved enough to pin
        but never gave room to grow. Unplayed favorites count as 0 plays
        and surface first among ties (newest pin wins).
        """
        rows = self._db.execute(
            "SELECT f.payload FROM favorites f LEFT JOIN "
            "(SELECT video_id, COUNT(*) AS plays FROM history GROUP BY video_id) h "
            "ON h.video_id = f.video_id "
            "WHERE COALESCE(h.plays, 0) <= ? "
            "ORDER BY f.created_at DESC, f.rowid DESC LIMIT ?",
            (max(int(max_plays), 0), max(int(limit), 0)),
        ).fetchall()
        tracks: list[Track] = []
        for (payload,) in rows:
            try:
                tracks.append(Track.from_json(payload))
            except (TypeError, ValueError):
                continue
        return tracks

    def prune_history(self, keep: int = 500) -> int:
        """Delete history beyond the newest `keep` rows. Returns rows removed."""
        cur = self._db.execute(
            "DELETE FROM history WHERE id NOT IN "
            "(SELECT id FROM history ORDER BY id DESC LIMIT ?)",
            (keep,),
        )
        self._db.commit()
        return cur.rowcount

    # --- memory & rituals (v0.7.0) ---

    def on_repeat(
        self, limit: int = ON_REPEAT_LIMIT, decay_days: float = ON_REPEAT_DECAY_DAYS
    ) -> list[Track]:
        """The decayed most-played list: last week beats last year.

        Every play scores `0.5 ** (age_days / decay_days)` — a track played
        all week outranks one you binged last spring. Deduped by video_id
        (newest payload wins); ties break by total plays, then title.
        """
        scores = self.on_repeat_scores(limit=limit, decay_days=decay_days)
        return [track for track, _score in scores]

    def on_repeat_scores(
        self, limit: int = ON_REPEAT_LIMIT, decay_days: float = ON_REPEAT_DECAY_DAYS
    ) -> list[tuple[Track, float]]:
        """(track, score) pairs behind on_repeat() — the math, exposed."""
        decay = decay_days if decay_days > 0 else 1.0
        now = time.time()
        rows = self._db.execute(
            "SELECT video_id, payload, played_at FROM history ORDER BY id DESC"
        ).fetchall()
        scores: dict[str, float] = {}
        plays: dict[str, int] = {}
        newest: dict[str, str] = {}
        for video_id, payload, played_at in rows:
            if video_id not in newest:
                newest[video_id] = payload
            age_days = max(0.0, (now - float(played_at)) / 86400.0)
            scores[video_id] = scores.get(video_id, 0.0) + 0.5 ** (age_days / decay)
            plays[video_id] = plays.get(video_id, 0) + 1
        ranked: list[tuple[Track, float]] = []
        for video_id, score in scores.items():
            try:
                track = Track.from_json(newest[video_id])
            except (TypeError, ValueError):
                continue  # corrupt row — not worth dying over
            ranked.append((track, score))
        ranked.sort(
            key=lambda pair: (-pair[1], -plays[pair[0].video_id], str(pair[0].title).lower())
        )
        return ranked[: max(int(limit), 0)]

    def history_page(
        self, days: int | None = None, limit: int = 2000
    ) -> list[tuple[str, list[Track]]]:
        """History grouped by calendar day, newest first — the day-jump page.

        Returns [(day_iso, [Track]), …]; within a day, newest plays come
        first. `days` bounds how far back the page reaches.
        """
        query = "SELECT payload, played_at FROM history"
        params: list = []
        if days is not None and days > 0:
            query += " WHERE played_at >= ?"
            params.append(time.time() - days * 86400.0)
        query += " ORDER BY id DESC LIMIT ?"
        params.append(max(1, int(limit)))
        rows = self._db.execute(query, tuple(params)).fetchall()
        groups: list[tuple[str, list[Track]]] = []
        index: dict[str, int] = {}
        for payload, played_at in rows:
            try:
                track = Track.from_json(payload)
            except (TypeError, ValueError):
                continue
            day = time.strftime("%Y-%m-%d", time.localtime(float(played_at)))
            if day not in index:
                index[day] = len(groups)
                groups.append((day, []))
            groups[index[day]][1].append(track)
        return groups

    def listening_stats(self) -> dict:
        """A quick shape of your listening: plays, uniques, top artist, days."""
        rows = self._db.execute("SELECT payload, played_at FROM history").fetchall()
        uniques: set[str] = set()
        artists: dict[str, int] = {}
        days: set[str] = set()
        for payload, played_at in rows:
            try:
                track = Track.from_json(payload)
            except (TypeError, ValueError):
                continue
            uniques.add(track.video_id)
            if track.artist:
                artists[track.artist] = artists.get(track.artist, 0) + 1
            days.add(time.strftime("%Y-%m-%d", time.localtime(float(played_at))))
        top_artist = max(artists, key=lambda a: (artists[a], a)) if artists else ""
        return {
            "total_plays": len(rows),
            "unique_tracks": len(uniques),
            "top_artist": top_artist,
            "top_artist_plays": artists.get(top_artist, 0),
            "days_listened": len(days),
        }

    # --- memory: day jumps, stats, queue, prefs (v0.7.0 storage core) ---

    def history_days(self) -> list[tuple[str, int]]:
        """Distinct listening days (YYYY-MM-DD) with play counts, newest first."""
        rows = self._db.execute(
            "SELECT date(played_at, 'unixepoch', 'localtime') AS day, COUNT(*) "
            "FROM history GROUP BY day ORDER BY day DESC"
        ).fetchall()
        return [(str(day), int(count)) for day, count in rows]

    def history_on(self, day: str, limit: int = HISTORY_PAGE_SIZE) -> list[Track]:
        """Plays from one calendar day, newest first — the day-jump view."""
        rows = self._db.execute(
            "SELECT payload FROM history "
            "WHERE date(played_at, 'unixepoch', 'localtime') = ? "
            "ORDER BY id DESC LIMIT ?",
            (day, limit),
        ).fetchall()
        return [Track.from_json(payload) for (payload,) in rows]

    def history_slice(
        self, page: int = 0, page_size: int = HISTORY_PAGE_SIZE
    ) -> tuple[list[Track], bool]:
        """One flat slice of history, newest first, plus whether more remain.

        (Named `history_slice` because history_page() already groups by day.)
        """
        size = max(page_size, 0)
        offset = max(page, 0) * size
        rows = self._db.execute(
            "SELECT payload FROM history ORDER BY id DESC LIMIT ? OFFSET ?",
            (size + 1, offset),
        ).fetchall()
        has_more = len(rows) > size
        return [Track.from_json(payload) for (payload,) in rows[:size]], has_more

    def stats_summary(self, top: int = STATS_TOP_LIMIT) -> dict:
        """Everything the memory dashboard needs, degraded gracefully when thin."""
        (total_plays,) = self._db.execute("SELECT COUNT(*) FROM history").fetchone()
        (unique_tracks,) = self._db.execute(
            "SELECT COUNT(DISTINCT video_id) FROM history"
        ).fetchone()
        (days_listened,) = self._db.execute(
            "SELECT COUNT(DISTINCT date(played_at, 'unixepoch', 'localtime')) FROM history"
        ).fetchone()
        row = self._db.execute("SELECT MIN(played_at) FROM history").fetchone()
        first_play = (
            datetime.fromtimestamp(float(row[0])).isoformat(timespec="seconds")
            if row and row[0] is not None
            else None
        )
        artist_counts: dict[str, int] = {}
        total_seconds = 0.0
        per_track = self._db.execute(
            "SELECT payload, COUNT(*) FROM history GROUP BY video_id"
        ).fetchall()
        for payload, plays in per_track:
            try:
                data = json.loads(payload)
            except ValueError:
                continue
            if not isinstance(data, dict):
                continue
            artist = str(data.get("artist") or "").strip()
            if artist:
                artist_counts[artist] = artist_counts.get(artist, 0) + plays
            seconds = data.get("duration_sec") or 0
            if not isinstance(seconds, (int, float)) or seconds <= 0:
                seconds = parse_duration(str(data.get("duration") or ""))
            total_seconds += max(0.0, float(seconds)) * plays
        top_artists = sorted(artist_counts.items(), key=lambda item: (-item[1], item[0]))
        return {
            "total_plays": int(total_plays),
            "unique_tracks": int(unique_tracks),
            "est_minutes": int(total_seconds // 60),
            "days_listened": int(days_listened),
            "first_play": first_play,
            "top_tracks": self.top_tracks(max(top, 0)),
            "top_artists": top_artists[: max(top, 0)],
        }

    def save_queue(self, video_ids: list[str], index: int, position_ms: int) -> None:
        """Idempotent single-row snapshot — cheap enough to call on every tick."""
        self._db.execute(
            "INSERT OR REPLACE INTO queue_snapshot (id, video_ids, idx, position_ms) "
            "VALUES (1, ?, ?, ?)",
            (json.dumps(list(video_ids)), int(index), int(position_ms)),
        )
        self._db.commit()

    def load_queue(self) -> tuple[list[str], int, int] | None:
        """The saved queue, or None when nothing worth restoring is kept."""
        row = self._db.execute(
            "SELECT video_ids, idx, position_ms FROM queue_snapshot WHERE id = 1"
        ).fetchone()
        if row is None:
            return None
        try:
            video_ids = json.loads(row[0])
        except ValueError:
            return None
        if not isinstance(video_ids, list):
            return None
        return [str(v) for v in video_ids], int(row[1]), int(row[2])

    def clear_queue(self) -> None:
        self._db.execute("DELETE FROM queue_snapshot")
        self._db.commit()

    def set_track_pref(self, video_id: str, key: str, value: float) -> None:
        """Remember a per-track dial (speed, volume) — upsert, never complains."""
        self._db.execute(
            "INSERT OR REPLACE INTO track_prefs (video_id, key, value) VALUES (?, ?, ?)",
            (video_id, key, float(value)),
        )
        self._db.commit()

    def track_pref(
        self, video_id: str, key: str, default: float | None = None
    ) -> float | None:
        row = self._db.execute(
            "SELECT value FROM track_prefs WHERE video_id = ? AND key = ?",
            (video_id, key),
        ).fetchone()
        return float(row[0]) if row else default

    def track_prefs_all(self, video_id: str) -> dict[str, float]:
        rows = self._db.execute(
            "SELECT key, value FROM track_prefs WHERE video_id = ?", (video_id,)
        ).fetchall()
        return {key: float(value) for key, value in rows}

    # --- local library (v0.7.0): your own files by the fire ---

    @staticmethod
    def local_video_id(path: str | Path) -> str:
        """Stable id for a file on disk: 'local-' + a short path hash.

        Same path in, same id out — re-scans update instead of duplicating.
        """
        digest = hashlib.sha1(str(path).encode("utf-8", "replace")).hexdigest()
        return f"local-{digest[:16]}"

    @staticmethod
    def _local_track(video_id: str, path: str, title: str, artist: str,
                     album: str, duration_s: float) -> Track:
        """A local_tracks row as a Track (unknown duration renders as '—')."""
        seconds = max(0, int(float(duration_s or 0)))
        return Track(
            video_id=video_id,
            title=title,
            artist=artist,
            duration=format_duration(seconds) if seconds else "—",
            duration_sec=seconds,
        )

    def upsert_local_track(
        self,
        path: str | Path,
        title: str,
        artist: str = "",
        album: str = "",
        duration_s: float = 0.0,
    ) -> Track:
        """Insert or refresh one local file; returns it as a Track.

        The path is the identity: a re-scan of the same file updates
        title/artist/album/duration and keeps its video_id + added_at.
        """
        clean_path = str(path)
        video_id = self.local_video_id(clean_path)
        self._db.execute(
            "INSERT INTO local_tracks (video_id, path, title, artist, album, duration_s) "
            "VALUES (?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(path) DO UPDATE SET title = excluded.title, "
            "artist = excluded.artist, album = excluded.album, "
            "duration_s = excluded.duration_s",
            (video_id, clean_path, str(title), str(artist), str(album),
             max(0.0, float(duration_s))),
        )
        self._db.commit()
        return self._local_track(video_id, clean_path, str(title), str(artist),
                                 str(album), float(duration_s))

    def upsert_local_tracks(self, entries: list[dict]) -> tuple[int, int]:
        """Batch upsert for the scanner — one transaction, ``(added, updated)``.

        Entries are ``{path, title, artist?, album?, duration_s?}`` dicts;
        malformed ones and within-batch duplicate paths are skipped.
        `added` counts paths that were not in the library before.
        """
        clean: list[tuple] = []
        seen_paths: set[str] = set()
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            path = str(entry.get("path") or "").strip()
            title = str(entry.get("title") or "").strip()
            if not path or not title or path in seen_paths:
                continue
            seen_paths.add(path)
            clean.append((
                self.local_video_id(path), path, title,
                str(entry.get("artist") or ""),
                str(entry.get("album") or ""),
                max(0.0, float(entry.get("duration_s") or 0.0)),
            ))
        if not clean:
            return 0, 0
        known = {
            str(row[0]) for row in self._db.execute(
                "SELECT path FROM local_tracks"
            ).fetchall()
        }
        self._db.executemany(
            "INSERT INTO local_tracks (video_id, path, title, artist, album, duration_s) "
            "VALUES (?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(path) DO UPDATE SET title = excluded.title, "
            "artist = excluded.artist, album = excluded.album, "
            "duration_s = excluded.duration_s",
            clean,
        )
        self._db.commit()
        added = sum(1 for row in clean if row[1] not in known)
        return added, len(clean) - added

    def local_tracks(self) -> list[Track]:
        """Every local song, artist → album → title order (stable, library-like)."""
        rows = self._db.execute(
            "SELECT video_id, path, title, artist, album, duration_s "
            "FROM local_tracks "
            "ORDER BY artist COLLATE NOCASE, album COLLATE NOCASE, "
            "title COLLATE NOCASE"
        ).fetchall()
        return [self._local_track(*row) for row in rows]

    def local_track_path(self, video_id: str) -> str | None:
        """The file behind a 'local-…' video id (the playback resolve)."""
        row = self._db.execute(
            "SELECT path FROM local_tracks WHERE video_id = ?", (video_id,)
        ).fetchone()
        return str(row[0]) if row else None

    def remove_local_track(self, path: str | Path) -> bool:
        """Drop one local file from the library. True when it was there."""
        cur = self._db.execute(
            "DELETE FROM local_tracks WHERE path = ?", (str(path),)
        )
        self._db.commit()
        return cur.rowcount > 0

    def local_track_count(self) -> int:
        (count,) = self._db.execute(
            "SELECT COUNT(*) FROM local_tracks"
        ).fetchone()
        return int(count)

    # --- playlists ---

    def create_playlist(self, name: str) -> int:
        cur = self._db.execute(
            "INSERT INTO playlists (name) VALUES (?)", (name.strip(),)
        )
        self._db.commit()
        return int(cur.lastrowid)

    def rename_playlist(self, playlist_id: int, name: str) -> None:
        self._db.execute(
            "UPDATE playlists SET name = ? WHERE id = ?", (name.strip(), playlist_id)
        )
        self._db.commit()

    def delete_playlist(self, playlist_id: int) -> None:
        self._db.execute(
            "DELETE FROM playlist_tracks WHERE playlist_id = ?", (playlist_id,)
        )
        self._db.execute("DELETE FROM playlists WHERE id = ?", (playlist_id,))
        self._db.commit()

    def playlists(self) -> list[tuple[int, str, int]]:
        """[(id, name, track_count)] oldest first — stable sidebar order."""
        rows = self._db.execute(
            "SELECT p.id, p.name, COUNT(t.position) FROM playlists p "
            "LEFT JOIN playlist_tracks t ON t.playlist_id = p.id "
            "GROUP BY p.id ORDER BY p.id"
        ).fetchall()
        return [(int(pid), name, int(count)) for pid, name, count in rows]

    def playlist_name(self, playlist_id: int) -> str | None:
        row = self._db.execute(
            "SELECT name FROM playlists WHERE id = ?", (playlist_id,)
        ).fetchone()
        return row[0] if row else None

    def add_to_playlist(self, playlist_id: int, track: Track) -> bool:
        """Append a track (skips duplicates). True when inserted."""
        row = self._db.execute(
            "SELECT 1 FROM playlist_tracks WHERE playlist_id = ? AND video_id = ?",
            (playlist_id, track.video_id),
        ).fetchone()
        if row is not None:
            return False
        nxt = self._db.execute(
            "SELECT COALESCE(MAX(position), 0) + 1 FROM playlist_tracks "
            "WHERE playlist_id = ?",
            (playlist_id,),
        ).fetchone()[0]
        self._db.execute(
            "INSERT INTO playlist_tracks (playlist_id, position, video_id, payload) "
            "VALUES (?, ?, ?, ?)",
            (playlist_id, int(nxt), track.video_id, track.to_json()),
        )
        self._db.commit()
        return True

    def remove_from_playlist(self, playlist_id: int, video_id: str) -> int:
        """Drop every occurrence of a track, then compact positions."""
        cur = self._db.execute(
            "DELETE FROM playlist_tracks WHERE playlist_id = ? AND video_id = ?",
            (playlist_id, video_id),
        )
        rows = self._db.execute(
            "SELECT position FROM playlist_tracks WHERE playlist_id = ? "
            "ORDER BY position",
            (playlist_id,),
        ).fetchall()
        for new_pos, (old_pos,) in enumerate(rows, start=1):
            if old_pos != new_pos:
                self._db.execute(
                    "UPDATE playlist_tracks SET position = ? "
                    "WHERE playlist_id = ? AND position = ?",
                    (new_pos, playlist_id, old_pos),
                )
        self._db.commit()
        return cur.rowcount

    def playlist_tracks(self, playlist_id: int) -> list[Track]:
        rows = self._db.execute(
            "SELECT payload FROM playlist_tracks WHERE playlist_id = ? "
            "ORDER BY position",
            (playlist_id,),
        ).fetchall()
        return [Track.from_json(payload) for (payload,) in rows]

    # --- library backup (portable JSON, favorites + playlists) ---

    EXPORT_FORMAT = "hearth-library"

    def export_library(self) -> dict:
        """Everything user-created as one portable dict."""
        return {
            "format": self.EXPORT_FORMAT,
            "version": 1,
            "favorites": [t.to_dict() for t in self.favorites()],
            "playlists": [
                {
                    "name": name,
                    "tracks": [t.to_dict() for t in self.playlist_tracks(pid)],
                }
                for pid, name, _count in self.playlists()
            ],
        }

    def import_library(self, data: dict, merge: bool = False) -> tuple[int, int]:
        """Restore an export_library() dict. Returns (playlists, tracks) added.

        merge=False wipes the current library first; merge=True skips entries
        that already exist. Corrupt entries are skipped individually — a
        partial file restores as much as it can.
        """
        if not isinstance(data, dict) or data.get("format") != self.EXPORT_FORMAT:
            raise ValueError("not a hearth library export")
        if not merge:
            for pid, _name, _count in self.playlists():
                self.delete_playlist(pid)
            for track in self.favorites():
                self.unpin(track.video_id)

        playlists_added = 0
        tracks_added = 0
        for entry in data.get("favorites") or []:
            track = self._track_from(entry)
            if track is None or self.is_pinned(track.video_id):
                continue
            self.pin(track)
            tracks_added += 1
        for entry in data.get("playlists") or []:
            if not isinstance(entry, dict):
                continue
            name = str(entry.get("name") or "").strip()
            if not name:
                continue
            pid = self._playlist_for_import(name, merge=merge)
            if pid is None:
                playlists_added += 1
                pid = self.create_playlist(name)
            for track_data in entry.get("tracks") or []:
                track = self._track_from(track_data)
                if track is not None and self.add_to_playlist(pid, track):
                    tracks_added += 1
        return playlists_added, tracks_added

    # --- playlist files: import / export (never-raises) ---

    def export_playlists(self, path: str | Path) -> bool:
        """Playlists only, same shapes as export_library(). False on write failure."""
        data = self.export_library()
        data.pop("favorites", None)
        try:
            Path(path).write_text(
                json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except OSError:
            return False
        return True

    def import_playlists(self, path: str | Path, merge: bool = True) -> int:
        """Import playlists from an export_playlists()/export_library() file.

        merge=True folds tracks into same-named playlists; merge=False always
        creates new ones. Returns how many playlists were imported, 0 on any
        failure. Corrupt entries are skipped individually.
        """
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return 0
        if not isinstance(data, dict) or not isinstance(data.get("playlists"), list):
            return 0
        imported = 0
        for entry in data["playlists"]:
            if not isinstance(entry, dict):
                continue
            name = str(entry.get("name") or "").strip()
            if not name:
                continue
            pid = self._playlist_for_import(name, merge=merge)
            if pid is None:
                pid = self.create_playlist(name)
            for track_data in entry.get("tracks") or []:
                track = self._track_from(track_data)
                if track is not None:
                    self.add_to_playlist(pid, track)
            imported += 1
        return imported

    def export_m3u(self, playlist_id: int, path: str | Path) -> bool:
        """Standard #EXTM3U with YouTube Music URLs. False on any failure."""
        if self.playlist_name(playlist_id) is None:
            return False
        lines = ["#EXTM3U"]
        for t in self.playlist_tracks(playlist_id):
            seconds = t.duration_sec or parse_duration(t.duration)
            lines.append(f"#EXTINF:{seconds},{t.artist} - {t.title}")
            lines.append(f"https://music.youtube.com/watch?v={t.video_id}")
        try:
            Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")
        except OSError:
            return False
        return True

    def import_m3u(self, path: str | Path, name: str) -> int:
        """Import an .m3u file as a new playlist. Returns tracks added.

        #EXTINF labels are read as 'Artist - Title'; entries without one fall
        back to the video id as the title. 0 on any failure.
        """
        try:
            text = Path(path).read_text(encoding="utf-8")
        except (OSError, ValueError):
            return 0
        name = name.strip()
        if not name:
            return 0
        pid = self.create_playlist(name)
        added = 0
        seconds = 0
        label = ""
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            if line.startswith("#EXTINF:"):
                raw, _sep, label = line[len("#EXTINF:"):].partition(",")
                try:
                    seconds = int(float(raw))
                except (ValueError, OverflowError):
                    seconds = 0
                continue
            if line.startswith("#"):
                continue
            match = _VIDEO_ID_RE.search(line)
            if match is None:
                continue
            artist, sep, title = label.partition(" - ")
            if not sep:
                artist, title = "", label
            track = Track(
                video_id=match.group(1),
                title=title.strip() or match.group(1),
                artist=artist.strip(),
                duration_sec=max(0, seconds),
            )
            if self.add_to_playlist(pid, track):
                added += 1
            seconds = 0
            label = ""
        return added

    def _playlist_for_import(self, name: str, merge: bool) -> int | None:
        """merge=True reuses a same-named playlist; None = create a new one."""
        if not merge:
            return None
        for pid, existing, _count in self.playlists():
            if existing == name:
                return pid
        return None

    def _track_from(self, data) -> Track | None:
        if not isinstance(data, dict):
            return None
        try:
            track = Track.from_dict(data)
        except (TypeError, ValueError):
            return None
        if not track.video_id or not track.title:
            return None
        return track
