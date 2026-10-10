"""Room 10 follow-up — the Enhance sprinkle: playlists that grow themselves.

Spotify's "Enhance" in hearth terms: take any playlist, ask the app's
own radio for a few more tracks like the ones already burning, and lay
them in. The service is pure except for the injected ``suggester``
(the same YTM radio fetch the queue autocomplete uses), and it stays
explainable — every pick carries the seed track it grew from, the
playlist's own tracks are never suggested back, and a shy result is an
honest short list instead of padding.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Callable

from . import config
from .models import Track
from .storage import HearthStore

log = logging.getLogger(__name__)

# suggester: (seed_track, how_many) -> candidate tracks (never-required to fill)
Suggester = Callable[[Track, int], list[Track]]


@dataclass(frozen=True)
class EnhancePick:
    """One sprinkled track, plus the seed and the honest reason why."""

    track: Track
    seed: Track
    reason: str

    @property
    def label(self) -> str:
        return f"{self.track.display_name} · {self.reason}"


def pick_seed(tracks: list[Track]) -> Track | None:
    """The playlist's gravitational center: most frequent artist.

    Ties and empties resolve to the earliest track in playlist order,
    so the pick is deterministic against a fixed playlist.
    """
    counts: dict[str, int] = {}
    first_by_artist: dict[str, Track] = {}
    for track in tracks:
        artist = (track.artist or "").strip().lower()
        if not artist:
            continue
        counts[artist] = counts.get(artist, 0) + 1
        first_by_artist.setdefault(artist, track)
    if not counts:
        return tracks[0] if tracks else None
    best = max(counts.values())
    for artist, count in counts.items():          # dict order = first-seen order
        if count == best:
            return first_by_artist[artist]
    return None


def enhance(
    tracks: list[Track],
    suggester: Suggester,
    n: int | None = None,
    exclude: list[Track] | None = None,
) -> list[EnhancePick]:
    """Sprinkle up to ``n`` radio-shaped picks into a track list.

    Seeds are tried in playlist order (frequency irrelevant beyond the
    pick_seed headline); every suggestion already in the playlist, in
    ``exclude``, or already picked is skipped. A suggester that raises
    or returns junk costs its seed nothing — the sprinkle just skips on.
    """
    want = config.ENHANCE_SIZE if n is None else int(n)
    if want <= 0 or not tracks:
        return []
    existing: set[str] = {t.video_id for t in tracks}
    existing |= {t.video_id for t in (exclude or []) if isinstance(t, Track)}
    picks: list[EnhancePick] = []
    for seed in tracks:
        if len(picks) >= want:
            break
        try:
            candidates = suggester(seed, want - len(picks)) or []
        except Exception as exc:  # noqa: BLE001 - radio hiccups skip quietly
            log.info("enhance suggester failed for %s: %s", seed.video_id, exc)
            continue
        for candidate in candidates:
            if len(picks) >= want:
                break
            if not isinstance(candidate, Track) or not candidate.video_id:
                continue
            if candidate.video_id in existing:
                continue
            existing.add(candidate.video_id)
            picks.append(EnhancePick(
                track=candidate,
                seed=seed,
                reason=f"radio from {seed.display_name}",
            ))
    return picks


def enhance_into_playlist(
    store: HearthStore,
    playlist_id: int,
    suggester: Suggester,
    n: int | None = None,
) -> tuple[list[Track], list[EnhancePick]]:
    """Enhance a stored playlist in place.

    Returns ``(added_tracks, picks)`` — the tracks that actually landed
    (duplicates inside the store are skipped by the storage layer) and
    the full sprinkle list for showing the user what grew where.
    """
    tracks = store.playlist_tracks(playlist_id)
    picks = enhance(tracks, suggester, n=n)
    added: list[Track] = []
    for pick in picks:
        if store.add_to_playlist(playlist_id, pick.track):
            added.append(pick.track)
    return added, picks
