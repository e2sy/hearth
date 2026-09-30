"""Last.fm scrobble scaffold — opt-in, keyed, deliberately unwired.

An honest groundwork, not a working bridge. Submitting scrobbles needs
user-provided API keys (config.LASTFM_API_KEY / LASTFM_SECRET, empty by
default) and an opt-in flow, so nothing here touches playback and
nothing here reaches the network. What exists:

- the Last.fm eligibility rule (should_scrobble: half the track or
  4 minutes, whichever comes first — pure),
- a capped ScrobbleQueue with a JSON roundtrip (dump/load — pure),
- the "allow this app" token-flow URL and the documented md5 signature
  helper sign(params, secret) (both pure),
- build_scrobble_payload, the final signed track.scrobble parameter
  shape (pure).

TODO(network): POST track.scrobble to https://ws.audioscrobbler.com/2.0/
once accounts are welcome — the roadmap guardrail keeps this scaffold
at the signed-payload boundary until then. Import-and-use ready.
"""

from __future__ import annotations

import hashlib
import time
from collections import deque
from dataclasses import asdict, dataclass

from . import config

AUTH_URL = "https://www.last.fm/api/auth/"
API_URL = "https://ws.audioscrobbler.com/2.0/"   # unused here — see TODO above
SCROBBLE_FRACTION = 0.5      # the 50% rule
SCROBBLE_CAP_SECONDS = 240.0  # …or 4 minutes, whichever comes first
QUEUE_MAX = 200               # a capped deque: scrobbles never pile up forever


def should_scrobble(elapsed_s: float, duration_s: float) -> bool:
    """The Last.fm rule: half the track OR 4 minutes, whichever is first.

    A track with no usable duration can never be scrobbled (we cannot
    judge how much of it was heard), and neither can negative time.
    """
    if duration_s <= 0 or elapsed_s <= 0:
        return False
    threshold = min(duration_s * SCROBBLE_FRACTION, SCROBBLE_CAP_SECONDS)
    return elapsed_s >= threshold


@dataclass
class Scrobble:
    """One scrobble waiting to leave the house."""

    artist: str
    title: str
    album: str = ""
    timestamp: float = 0.0
    duration: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data) -> "Scrobble | None":
        """A Scrobble from a dump()-shaped dict, or None (never raises)."""
        if not isinstance(data, dict):
            return None
        artist = data.get("artist")
        title = data.get("title")
        if not isinstance(artist, str) or not artist:
            return None
        if not isinstance(title, str) or not title:
            return None
        try:
            return cls(
                artist=artist,
                title=title,
                album=str(data.get("album") or ""),
                timestamp=float(data.get("timestamp") or 0.0),
                duration=float(data.get("duration") or 0.0),
            )
        except (TypeError, ValueError):
            return None


def _track_fields(track) -> tuple[str, str, str, float] | None:
    """(artist, title, album, duration) from a Track or Track-shaped dict."""
    if isinstance(track, dict):
        artist = track.get("artist")
        title = track.get("title")
        album = track.get("album") or ""
        duration = track.get("duration_sec", track.get("duration_s", 0))
    else:
        artist = getattr(track, "artist", None)
        title = getattr(track, "title", None)
        album = getattr(track, "album", "") or ""
        duration = getattr(track, "duration_sec", 0)
    if not isinstance(artist, str) or not artist:
        return None
    if not isinstance(title, str) or not title:
        return None
    try:
        duration = float(duration or 0)
    except (TypeError, ValueError):
        duration = 0.0
    return artist, title, str(album or ""), duration


class ScrobbleQueue:
    """A capped queue of scrobbles waiting to be submitted.

    Pure and offline: enqueue accepts hearth Tracks or Track-shaped
    dicts and quietly refuses junk (returns None); dump/load roundtrip
    through plain JSON so a future submitter can persist across
    restarts. The oldest entries fall off the cap.
    """

    def __init__(self, maxlen: int = QUEUE_MAX):
        self._maxlen = max(1, int(maxlen))
        self._items: deque[Scrobble] = deque(maxlen=self._maxlen)

    def __len__(self) -> int:
        return len(self._items)

    def enqueue(self, track, played_at: float | None = None) -> Scrobble | None:
        """Queue one scrobble; returns it, or None for unusable tracks."""
        fields = _track_fields(track)
        if fields is None:
            return None
        artist, title, album, duration = fields
        try:
            ts = time.time() if played_at is None else float(played_at)
        except (TypeError, ValueError):
            ts = time.time()
        scrobble = Scrobble(
            artist=artist,
            title=title,
            album=album,
            timestamp=ts,
            duration=duration,
        )
        self._items.append(scrobble)
        return scrobble

    def dump(self) -> list[dict]:
        """JSON-serializable snapshot (oldest first)."""
        return [s.to_dict() for s in self._items]

    def load(self, data) -> int:
        """Replace the queue from a dump()-shaped payload; returns count."""
        if not isinstance(data, (list, tuple)):
            return 0
        restored = [Scrobble.from_dict(entry) for entry in data]
        restored = [s for s in restored if s is not None][: self._maxlen]
        self._items = deque(restored, maxlen=self._maxlen)
        return len(self._items)


def submit_token_flow(api_key: str | None = None, token: str = "") -> str:
    """The "allow this app" URL the user must open and approve.

    Step one of Last.fm auth: point a browser here, the user grants
    access, Last.fm hands back a token that later becomes a session
    key (which this scaffold deliberately does not fetch yet).
    """
    key = api_key if api_key else getattr(config, "LASTFM_API_KEY", "")
    return f"{AUTH_URL}?api_key={key}&token={token}"


def sign(params: dict, secret: str) -> str:
    """The documented Last.fm api_sig, lowercase md5 hex.

    Algorithm: sort the parameter names alphabetically, concatenate
    key+value pairs with no separators, append the secret, md5 over
    the utf-8 bytes. `api_sig` itself (and `format`) must never be
    fed back in — callers hash the payload before adding the signature.
    """
    joined = "".join(f"{key}{params[key]}" for key in sorted(params))
    return hashlib.md5((joined + secret).encode("utf-8")).hexdigest()


def build_scrobble_payload(
    sk: str,
    artist: str,
    title: str,
    album: str = "",
    ts: float | None = None,
) -> dict:
    """The signed track.scrobble parameter dict (pure — no network).

    api_key/api_sig appear only when the user has configured them; the
    signature is computed over everything except itself, per Last.fm's
    rule. With no keys configured the shape is still honest — just
    unsigned, and the future submitter would refuse to send it.
    """
    payload = {
        "method": "track.scrobble",
        "artist": artist,
        "track": title,
        "album": album,
        "timestamp": int(ts if ts is not None else time.time()),
        "sk": sk,
    }
    api_key = getattr(config, "LASTFM_API_KEY", "")
    if api_key:
        payload["api_key"] = api_key
    secret = getattr(config, "LASTFM_SECRET", "")
    if secret:
        payload["api_sig"] = sign(payload, secret)
    return payload
