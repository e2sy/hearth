"""Room 15 — The Wise Fire: prompt playlists without pretending.

Type "rainy midnight study" and the hearth assembles a playlist. The
trick is honest: mood words map to YouTube Music's own mood/search
queries (keyless, no LLM in the loop), candidates come from an
injected search function, and the result is an ordinary editable
playlist. An optional local model can sharpen the mapping later —
the zero-network fallback path always exists.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from . import config
from .models import Track

# Mood words → YTM search queries. Lowercase keys; matching is substring
# based so "rainy"/"raining" catch "rain". Order matters only for display.
MOOD_WORDS: dict[str, tuple[str, ...]] = {
    "rain": ("rainy day mood", "rain soundscape songs"),
    "storm": ("stormy mood music",),
    "night": ("late night mood", "midnight songs"),
    "midnight": ("midnight mood playlist",),
    "morning": ("morning mood", "sunrise songs"),
    "sad": ("sad songs mood", "melancholy mix"),
    "cry": ("songs to cry to",),
    "heartbreak": ("heartbreak songs",),
    "happy": ("happy mood playlist", "feel good songs"),
    "chill": ("chill mood playlist", "laid back mix"),
    "lofi": ("lofi beats",),
    "study": ("study focus playlist", "deep focus instrumental"),
    "focus": ("deep focus playlist",),
    "work": ("work focus mix",),
    "gym": ("workout energy playlist", "gym motivation"),
    "run": ("running energy mix",),
    "energy": ("high energy playlist",),
    "party": ("party hits", "dance floor mix"),
    "dance": ("dance playlist",),
    "romantic": ("romantic mood playlist",),
    "love": ("love songs mix",),
    "sleep": ("sleep playlist", "calm sleep sounds"),
    "calm": ("calm mood playlist",),
    "peace": ("peaceful instrumental",),
    "drive": ("driving songs", "night drive mix"),
    "road": ("road trip playlist",),
    "cozy": ("cozy mood playlist",),
    "warm": ("warm acoustic mix",),
    "coffee": ("coffee shop vibes",),
    "hindi": ("hindi mood songs",),
    "punjabi": ("punjabi hits",),
    "tamil": ("tamil mood songs",),
    "spanish": ("spanish mood playlist",),
    "instrumental": ("instrumental playlist",),
    "acoustic": ("acoustic sessions",),
    "jazz": ("jazz mood playlist",),
    "classical": ("classical focus mix",),
    "rock": ("rock essentials",),
    "punk": ("punk energy mix",),
    "metal": ("metal essentials",),
    "hip hop": ("hip hop essentials",),
    "rap": ("rap essentials",),
    "electronic": ("electronic mood mix",),
    "synth": ("synthwave playlist",),
    "ambient": ("ambient playlist",),
    "folk": ("folk favorites",),
    "country": ("country road playlist",),
}

# Word → word so "rainy night study" can split across moods cleanly.
_STOP_WORDS = frozenset({
    "a", "an", "and", "for", "me", "my", "music", "playlist", "songs",
    "song", "some", "the", "to", "vibes", "with", "please", "give",
    "something", "play", "mood", "mix", "kind", "of", "like", "listen",
})


@dataclass
class PromptPlan:
    """What a prompt means: mood tags, search queries, and the echo back."""

    text: str
    tags: list[str] = field(default_factory=list)
    queries: list[str] = field(default_factory=list)

    @property
    def display_name(self) -> str:
        """A shelf-worthy name assembled from what matched."""
        if self.tags:
            return " ".join(tag.capitalize() for tag in self.tags[:3]) + " mix"
        return f'"{self.text}" mix'


def interpret(text: str, max_queries: int = config.PROMPT_QUERY_LIMIT) -> PromptPlan:
    """Map a natural-language prompt onto keyless YTM search queries.

    Substring mood matching (so "rainy" catches "rain"), stop words
    ignored, and the raw prompt itself is always the last-resort query
    so *something* is always searchable. Never raises.
    """
    text = str(text or "").strip()
    plan = PromptPlan(text=text)
    if not text:
        return plan
    lowered = text.lower()
    tags: list[str] = []
    for word, queries in MOOD_WORDS.items():
        if word in lowered:
            tags.append(word)
    # Longest tags first so "hip hop" wins over the "hop"-less world.
    tags.sort(key=len, reverse=True)
    plan.tags = tags
    queries: list[str] = []
    for tag in tags:
        for query in MOOD_WORDS[tag]:
            if query not in queries:
                queries.append(query)
    # Unmatched plain words become one extra keyword query ("late homework" → "late homework songs").
    plain = [w for w in lowered.split() if w not in _STOP_WORDS and not any(w in tag for tag in tags)]
    if plain and len(plain) <= 4 and len(queries) < max_queries:
        keyword_query = " ".join(plain)
        if keyword_query not in queries:
            queries.append(keyword_query)
    plan.queries = queries[: max(int(max_queries), 1)] or [text]
    return plan


def assemble(
    plan: PromptPlan,
    search_fn,
    per_query: int = config.PROMPT_TRACKS_PER_QUERY,
    limit: int = config.GLOW_MIX_SIZE,
) -> list[Track]:
    """Run a plan's queries through `search_fn(query)` and blend the results.

    Round-robin across queries so every mood gets a seat, deduped by
    video id, capped at `limit`. A search failure skips its query —
    one dead mood never blanks the playlist.
    """
    limit = max(int(limit), 0)
    if limit == 0 or not plan.queries:
        return []
    buckets: list[list[Track]] = []
    for query in plan.queries:
        try:
            results = search_fn(query) or []
        except Exception:  # noqa: BLE001 — network layer must not crash UI
            results = []
        bucket: list[Track] = []
        for track in results[: max(int(per_query), 0)]:
            if isinstance(track, Track) and track.video_id:
                bucket.append(track)
        buckets.append(bucket)
    picked: list[Track] = []
    seen: set[str] = set()
    cursor = 0
    while len(picked) < limit:
        advanced = False
        for bucket in buckets:
            if cursor < len(bucket):
                advanced = True
                track = bucket[cursor]
                if track.video_id not in seen:
                    seen.add(track.video_id)
                    picked.append(track)
                    if len(picked) >= limit:
                        break
        if not advanced:
            break
        cursor += 1
    return picked
