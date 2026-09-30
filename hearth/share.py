"""Playlist share format: encode/decode helpers for export & import.

The file format is intentionally boring JSON so playlists can move
between machines (and between players) without lock-in:

    {"app": "hearth", "version": 1, "name": "roadtrip", "tracks": [...]}

An export file may also hold several playlists as a JSON array of the
same shape — importing accepts either form and skips anything broken.
"""

from __future__ import annotations

import json
from typing import Any

from .models import Track

FORMAT_APP = "hearth"
FORMAT_VERSION = 1


def encode_playlist(name: str, tracks: list[Track]) -> dict[str, Any]:
    """One playlist -> JSON-serializable dict."""
    return {
        "app": FORMAT_APP,
        "version": FORMAT_VERSION,
        "name": name,
        "tracks": [track.to_dict() for track in tracks],
    }


def encode_playlists(items: list[tuple[str, list[Track]]]) -> dict[str, Any]:
    """Several playlists wrapped in an envelope."""
    return {
        "app": FORMAT_APP,
        "version": FORMAT_VERSION,
        "playlists": [encode_playlist(name, tracks) for name, tracks in items],
    }


def decode_playlists(data: Any) -> list[tuple[str, list[Track]]]:
    """Parse any accepted shape into [(name, tracks)]. Never raises.

    Accepted: one playlist dict, an envelope dict, or a list of either.
    Broken entries are skipped; empty names/tracks are dropped.
    """
    candidates: list[Any] = []
    if isinstance(data, dict):
        if isinstance(data.get("playlists"), list):
            candidates = list(data["playlists"])
        else:
            candidates = [data]
    elif isinstance(data, list):
        candidates = data

    out: list[tuple[str, list[Track]]] = []
    seen_names: set[str] = set()
    for entry in candidates:
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("name") or "").strip()
        raw_tracks = entry.get("tracks")
        if not name or not isinstance(raw_tracks, list):
            continue
        tracks: list[Track] = []
        seen_ids: set[str] = set()
        for raw in raw_tracks:
            try:
                track = Track.from_dict(raw) if isinstance(raw, dict) else None
            except Exception:  # noqa: BLE001 - one bad row must not kill an import
                track = None
            if track is None or not track.video_id or not track.title:
                continue
            if track.video_id in seen_ids:
                continue
            seen_ids.add(track.video_id)
            tracks.append(track)
        if not tracks:
            continue
        base, bump = name, 2
        while name in seen_names:
            name = f"{base} ({bump})"
            bump += 1
        seen_names.add(name)
        out.append((name, tracks))
    return out


def decode_playlists_text(text: str) -> list[tuple[str, list[Track]]]:
    """decode_playlists over raw file text ([] on any parse failure)."""
    try:
        return decode_playlists(json.loads(text))
    except Exception:  # noqa: BLE001 - never let a bad file crash the UI
        return []
