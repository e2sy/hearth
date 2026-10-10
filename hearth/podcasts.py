"""Room 13 — The Broadcast Tower: talk radio for the hearth, still keyless.

A tiny podcast engine on stdlib shoulders only: RSS 2.0 parsing (with
the iTunes namespace extensions everyone actually uses), OPML
import/export for moving subscriptions in one file, and the open
iTunes podcast index for discovery — no keys, no accounts, same
keyless spirit as YT Music and LRCLIB.

Network lives in injected fetchers (the job pool calls them, tests
hand fakes). Parsers never raise: a broken feed is an empty shelf
with a note, per the standing guardrails.
"""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass, field

from .storage import HearthStore

ITUNES_SEARCH_URL = "https://itunes.apple.com/search"
ITUNES_CHARTS_URL = "https://itunes.apple.com/%s/rss/toppodcasts/limit=%d/json"

# Podcast namespaces we understand (iTunes extensions + the RSS core).
_ITUNES_NS = "http://www.itunes.com/dtds/podcast-1.0.dtd"


@dataclass
class Episode:
    """One podcast episode, playable like any Track once resolved."""

    guid: str
    title: str = ""
    enclosure_url: str = ""
    published: str = ""          # human-readable pubDate, as the feed says it
    duration_s: int = 0          # seconds (iTunes duration or ISO-ish parse)
    feed_title: str = ""

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False)

    @classmethod
    def from_json(cls, raw: str) -> "Episode":
        data = json.loads(raw)
        known = set(cls.__dataclass_fields__)
        return cls(**{k: v for k, v in data.items() if k in known})


@dataclass
class PodcastFeed:
    """A parsed RSS feed: the show, its art, and its episodes."""

    title: str = ""
    link: str = ""
    description: str = ""
    image: str = ""
    episodes: list[Episode] = field(default_factory=list)


def parse_feed(xml_text: str) -> PodcastFeed:
    """Parse an RSS 2.0 podcast feed. Broken XML → an empty PodcastFeed.

    Understands the two things a player needs: `<item>` blocks (guid,
    title, enclosure, pubDate, iTunes duration) and the channel-level
    identity (title, link, description, iTunes image).
    """
    feed = PodcastFeed()
    if not xml_text or not xml_text.strip():
        return feed
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return feed
    channel = root.find("channel")
    if channel is None:
        return feed
    feed.title = (channel.findtext("title") or "").strip()
    feed.link = (channel.findtext("link") or "").strip()
    feed.description = (channel.findtext("description") or "").strip()
    image = channel.find(_itunes_key("image"))
    if image is not None and image.get("href"):
        feed.image = image.get("href", "")
    for item in channel.findall("item"):
        guid = (item.findtext("guid") or item.findtext("link") or "").strip()
        if not guid:
            continue
        enclosure = item.find("enclosure")
        episode = Episode(
            guid=guid,
            title=(item.findtext("title") or "").strip(),
            enclosure_url=(enclosure.get("url", "") if enclosure is not None else ""),
            published=(item.findtext("pubDate") or "").strip(),
            duration_s=_parse_duration(item.findtext(_itunes_key("duration")) or ""),
            feed_title=feed.title,
        )
        feed.episodes.append(episode)
    return feed


def parse_opml(xml_text: str) -> list[tuple[str, str]]:
    """OPML → [(xml_url, title)]. One file moves a whole subscription list.

    Understands the common shapes: outlines with type="rss" (and the
    sloppy but popular type="podcast"/no type with an xmlUrl). Broken
    XML returns [] — never raises.
    """
    if not xml_text or not xml_text.strip():
        return []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []
    feeds: list[tuple[str, str]] = []
    seen: set[str] = set()
    for outline in root.iter("outline"):
        url = (outline.get("xmlUrl") or "").strip()
        if not url or url in seen:
            continue
        seen.add(url)
        feeds.append((url, (outline.get("text") or outline.get("title") or "").strip()))
    return feeds


def build_opml(feeds: list[tuple[str, str]]) -> str:
    """[(xml_url, title)] → an OPML document other apps understand."""
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<opml version="2.0">',
        "  <head><title>Hearth podcasts</title></head>",
        "  <body>",
    ]
    for url, title in feeds:
        safe_title = (title or url).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        safe_url = url.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        lines.append(
            f'    <outline type="rss" text="{safe_title}" xmlUrl="{safe_url}"/>'
        )
    lines.extend(["  </body>", "</opml>", ""])
    return "\n".join(lines)


def search_podcasts(term: str, fetch, limit: int = 20) -> list[dict]:
    """Discovery via the open iTunes index: [{name, artist, feedUrl, art}].

    `fetch(url)` returns raw bytes/text (requests on the job pool, a
    fake in tests). Any failure is an honest [] — discovery is a
    convenience, never a dependency.
    """
    term = str(term or "").strip()
    if not term:
        return []
    url = f"{ITUNES_SEARCH_URL}?media=podcast&limit={max(1, int(limit))}&term={term}"
    try:
        raw = fetch(url)
        data = json.loads(raw)
    except Exception:  # noqa: BLE001 — network layer must not crash UI
        return []
    results = data.get("results") if isinstance(data, dict) else None
    out: list[dict] = []
    for entry in results or []:
        if not isinstance(entry, dict) or not entry.get("feedUrl"):
            continue
        out.append({
            "name": str(entry.get("collectionName") or ""),
            "artist": str(entry.get("artistName") or ""),
            "feed_url": str(entry.get("feedUrl") or ""),
            "art": str(entry.get("artworkUrl100") or ""),
            "genre": str(entry.get("primaryGenreName") or ""),
        })
    return out


def charts_url(country: str = "us", limit: int = 50) -> str:
    """The open charts endpoint for a country's top podcasts."""
    return ITUNES_CHARTS_URL % (str(country or "us").strip() or "us", max(1, int(limit)))


def top_podcasts(fetch, country: str = "us", limit: int = 20) -> list[dict]:
    """The discovery shelf: today's top podcasts from the open charts.

    Chart entries carry an iTunes id rather than a direct RSS url, so
    each result includes ``itunes_id`` — resolve it to a real feed with
    lookup_feed_url() when the user taps subscribe. Same failure law as
    search_podcasts: any hiccup is an honest [].
    """
    try:
        raw = fetch(charts_url(country, max(limit, 1)))
        data = json.loads(raw)
    except Exception:  # noqa: BLE001 — network layer must not crash UI
        return []
    entries = data.get("feed", {}).get("entry", []) if isinstance(data, dict) else []
    if isinstance(entries, dict):  # a single-entry chart comes back as a dict
        entries = [entries]
    out: list[dict] = []
    for entry in entries or []:
        if not isinstance(entry, dict):
            continue
        entry_id = entry.get("id") or {}
        itunes_id = str((entry_id.get("attributes") or {}).get("im:id") or "")
        title = str((entry.get("title") or {}).get("label") or "")
        artist = str((entry.get("im:artist") or {}).get("label") or "")
        images = entry.get("im:image") or []
        art = str(images[-1].get("label") or "") if images else ""
        if not title:
            continue
        out.append({
            "name": title,
            "artist": artist,
            "feed_url": "",       # charts don't carry it; resolve via itunes_id
            "itunes_id": itunes_id,
            "art": art,
            "genre": "",
        })
    return out


def lookup_feed_url(fetch, itunes_id: str) -> str:
    """Resolve an iTunes podcast id to its RSS feed url ('' on any failure)."""
    itunes_id = str(itunes_id or "").strip()
    if not itunes_id:
        return ""
    url = f"https://itunes.apple.com/lookup?id={itunes_id}&entity=podcast"
    try:
        raw = fetch(url)
        data = json.loads(raw)
    except Exception:  # noqa: BLE001 — network layer must not crash UI
        return ""
    results = data.get("results") if isinstance(data, dict) else None
    for entry in results or []:
        if isinstance(entry, dict) and entry.get("feedUrl"):
            return str(entry["feedUrl"])
    return ""


def refresh_feed(store: HearthStore, feed_id: int, xml_text: str,
                 now: float | None = None) -> int:
    """Parse one feed's XML and upsert its episodes. Returns new count.

    The refresh loop's core: subscribe → fetch → refresh. Known guids
    keep their position/played state; only genuinely new episodes land.
    """
    feed = parse_feed(xml_text)
    if not feed.episodes:
        return 0
    entries = [{"guid": e.guid, "payload": e.to_json()} for e in feed.episodes]
    return store.podcast_upsert_episodes(feed_id, entries, now=now)


def _itunes_key(name: str) -> str:
    """'{itunes-namespace}name' — ElementTree's expanded-name form."""
    return f"{{{_ITUNES_NS}}}{name}"


def _parse_duration(text: str) -> int:
    """'27:43' → 1663; '1:02:03' → 3723; '3600' → 3600; garbage → 0.

    iTunes durations arrive either seconds or H:MM:SS / MM:SS.
    """
    text = str(text or "").strip()
    if not text:
        return 0
    if text.isdigit():
        return int(text)
    parts = text.split(":")
    if not all(p.isdigit() for p in parts):
        return 0
    total = 0
    for part in parts:
        total = total * 60 + int(part)
    return total
