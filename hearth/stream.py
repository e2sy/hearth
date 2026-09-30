"""yt-dlp audio stream resolution with cross-platform format fallback.

The Qt Multimedia FFmpeg backend plays opus/m4a/aac equally well on
Linux, Windows, and macOS — so we simply prefer the highest-bitrate
audio-only HTTPS stream instead of special-casing any one OS.
"""

from __future__ import annotations

import logging
from typing import Callable

log = logging.getLogger(__name__)

_AUDIO_CODECS = ("opus", "mp4a", "aac", "mp3", "vorbis", "flac")


def pick_audio_stream(formats: list[dict]) -> dict | None:
    """Choose the best audio-only stream from yt-dlp format dicts.

    Preference: progressive HTTPS over HLS (QMediaPlayer is far more
    reliable on single-shot URLs than on m3u8 segment playlists), then
    higher bitrate, then higher sample rate as tie-break.
    """
    candidates = [
        f for f in formats
        if f.get("url")
        and f.get("acodec") not in (None, "none")
        and f.get("vcodec") in (None, "none")
    ]
    if not candidates:
        candidates = [f for f in formats if f.get("url") and f.get("acodec") not in (None, "none")]
    if not candidates:
        return None

    def bitrate(f: dict) -> float:
        return float(f.get("abr") or f.get("tbr") or 0)

    def is_progressive(f: dict) -> int:
        return 1 if f.get("protocol") in ("https", None) else 0

    candidates.sort(key=lambda f: (is_progressive(f), bitrate(f), float(f.get("asr") or 0)), reverse=True)
    return candidates[0]


def normalization_gain(loudness_db: float | None, target_db: float = -16.0,
                       max_gain_db: float = 6.0, min_gain_db: float = -6.0) -> float:
    """Gain (dB) that nudges a track's loudness toward the target, clamped."""
    if loudness_db is None:
        return 0.0
    return max(min_gain_db, min(max_gain_db, target_db - float(loudness_db)))


def resolve_stream_url(
    video_url: str,
    ydl_factory: Callable[[], object] | None = None,
) -> tuple[str | None, float | None]:
    """Resolve a direct audio URL for `video_url`.

    Returns (url, loudness_db). loudness may be None. Never raises.
    """
    try:
        if ydl_factory is not None:
            ydl = ydl_factory()
            info = ydl.extract_info(video_url, download=False)
        else:
            import yt_dlp  # lazy

            ydl = yt_dlp.YoutubeDL({
                "format": "bestaudio",
                "quiet": True,
                "no_warnings": True,
                "noplaylist": True,
                "default_search": "ytsearch",
            })
            info = ydl.extract_info(video_url, download=False)
    except Exception as exc:  # noqa: BLE001 - network layer must not crash UI
        log.warning("stream resolve failed for %s: %s", video_url, exc)
        return None, None

    if not info:
        return None, None

    formats = info.get("formats") or []
    best = pick_audio_stream(formats)
    url = (best or {}).get("url") or info.get("url")
    loudness = info.get("loudness")
    return url, (float(loudness) if loudness is not None else None)
