"""v0.9.0 Room 13 — the Broadcast Tower: RSS, OPML, discovery."""

import json

from hearth.podcasts import (
    Episode,
    build_opml,
    charts_url,
    lookup_feed_url,
    parse_feed,
    parse_opml,
    refresh_feed,
    search_podcasts,
    top_podcasts,
)
from hearth.storage import HearthStore

RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd" version="2.0">
  <channel>
    <title>Fireside Chats</title>
    <link>https://example.com/show</link>
    <description>Warm talk by the fire.</description>
    <itunes:image href="https://example.com/art.jpg"/>
    <item>
      <title>Episode 1: Kindling</title>
      <guid>ep-1</guid>
      <pubDate>Mon, 05 Oct 2026 10:00:00 GMT</pubDate>
      <enclosure url="https://example.com/ep1.mp3" type="audio/mpeg" length="1"/>
      <itunes:duration>27:43</itunes:duration>
    </item>
    <item>
      <title>Episode 2: Embers</title>
      <guid>ep-2</guid>
      <enclosure url="https://example.com/ep2.mp3" type="audio/mpeg" length="1"/>
      <itunes:duration>3600</itunes:duration>
    </item>
    <item>
      <title>No guid, no entry</title>
      <enclosure url="https://example.com/ep3.mp3" type="audio/mpeg" length="1"/>
    </item>
  </channel>
</rss>
"""

OPML = """<?xml version="1.0" encoding="UTF-8"?>
<opml version="2.0">
  <body>
    <outline text="News">
      <outline type="rss" text="Fireside Chats" xmlUrl="https://example.com/feed.rss"/>
      <outline type="rss" text="Night Radio" xmlUrl="https://example.com/night.rss"/>
    </outline>
  </body>
</opml>
"""


def make_store(tmp_path) -> HearthStore:
    return HearthStore(tmp_path / "hearth.db")


# --- feed parsing ---


def test_parse_feed_channel_and_items():
    feed = parse_feed(RSS)
    assert feed.title == "Fireside Chats"
    assert feed.image == "https://example.com/art.jpg"
    assert [e.guid for e in feed.episodes] == ["ep-1", "ep-2"]  # guidless skipped


def test_parse_feed_durations_both_shapes():
    feed = parse_feed(RSS)
    assert feed.episodes[0].duration_s == 27 * 60 + 43
    assert feed.episodes[1].duration_s == 3600


def test_parse_feed_enclosure_and_title():
    feed = parse_feed(RSS)
    assert feed.episodes[0].enclosure_url == "https://example.com/ep1.mp3"
    assert feed.episodes[0].feed_title == "Fireside Chats"


def test_parse_feed_broken_xml_never_raises():
    for garbage in ("", "not xml at all", "<rss><channel>", RSS[:20]):
        feed = parse_feed(garbage)
        assert feed.title == "" and feed.episodes == []


def test_episode_json_roundtrip():
    episode = Episode(guid="g", title="T", enclosure_url="u", duration_s=9)
    clone = Episode.from_json(episode.to_json())
    assert clone == episode


# --- OPML ---


def test_parse_opml_extracts_feeds():
    feeds = parse_opml(OPML)
    assert ("https://example.com/feed.rss", "Fireside Chats") in feeds
    assert len(feeds) == 2


def test_opml_roundtrip():
    feeds = [("https://example.com/a.rss", "Show A"), ("https://example.com/b.rss", "B & C")]
    parsed = parse_opml(build_opml(feeds))
    assert sorted(parsed) == sorted(feeds)


def test_parse_opml_broken_never_raises():
    assert parse_opml("") == []
    assert parse_opml("<opml><body>") == []


# --- store-backed subscriptions ---


def test_subscribe_refresh_position_memory(tmp_path):
    store = make_store(tmp_path)
    feed_id = store.podcast_subscribe("https://example.com/feed.rss", "Fireside")
    added = refresh_feed(store, feed_id, RSS, now=1000.0)
    assert added == 2

    # Halfway through episode 1, then a refresh lands: place is kept.
    store.podcast_set_position(feed_id, "ep-1", 831.0)
    store.podcast_mark_played(feed_id, "ep-2")
    added_again = refresh_feed(store, feed_id, RSS, now=2000.0)
    assert added_again == 0
    state = store.podcast_episode_state(feed_id, "ep-1")
    assert state == (831.0, False)
    assert store.podcast_episode_state(feed_id, "ep-2") == (0.0, True)


def test_subscribe_is_idempotent_on_url(tmp_path):
    store = make_store(tmp_path)
    first = store.podcast_subscribe("https://x.rss", "One")
    second = store.podcast_subscribe("https://x.rss", "One Renamed")
    assert first == second
    assert len(store.podcast_feeds()) == 1
    assert store.podcast_feeds()[0]["title"] == "One Renamed"


def test_unsubscribe_cascades_episodes(tmp_path):
    store = make_store(tmp_path)
    feed_id = store.podcast_subscribe("https://x.rss")
    refresh_feed(store, feed_id, RSS)
    assert store.podcast_unsubscribe(feed_id) is True
    assert store.podcast_feeds() == []


def test_feed_listing_counts_episodes(tmp_path):
    store = make_store(tmp_path)
    feed_id = store.podcast_subscribe("https://x.rss", "Show")
    refresh_feed(store, feed_id, RSS)
    listing = store.podcast_feeds()
    assert listing == [{"id": feed_id, "url": "https://x.rss", "title": "Show", "episodes": 2}]


def test_corrupt_episode_payload_skipped(tmp_path):
    store = make_store(tmp_path)
    feed_id = store.podcast_subscribe("https://x.rss")
    store.podcast_upsert_episodes(feed_id, [
        {"guid": "good", "payload": Episode(guid="good", title="Fine").to_json()},
        {"guid": "bad", "payload": "{not json"},
        {"guid": "", "payload": "no guid"},
    ])
    episodes = store.podcast_episodes(feed_id)
    assert [e["guid"] for e in episodes] == ["good"]


# --- discovery (open iTunes index, injected fetch) ---


def test_search_podcasts_maps_results():
    def fake_fetch(url):
        return json.dumps({"results": [{
            "collectionName": "Fireside Chats", "artistName": "Ember",
            "feedUrl": "https://example.com/feed.rss",
            "artworkUrl100": "https://example.com/art.jpg",
            "primaryGenreName": "Comedy",
        }]})
    results = search_podcasts("fireside", fake_fetch)
    assert results[0]["name"] == "Fireside Chats"
    assert results[0]["feed_url"] == "https://example.com/feed.rss"


def test_search_podcasts_failure_is_empty():
    def boom(url):
        raise RuntimeError("offline")
    assert search_podcasts("anything", boom) == []
    assert search_podcasts("", lambda url: "{}") == []


def test_top_podcasts_carries_itunes_id():
    def fake_fetch(url):
        return json.dumps({"feed": {"entry": [{
            "id": {"label": "x", "attributes": {"im:id": "12345"}},
            "title": {"label": "The Daily Ember"},
            "im:artist": {"label": "Ember Media"},
            "im:image": [{"label": "small"}, {"label": "big"}],
        }]}})
    results = top_podcasts(fake_fetch, country="in", limit=10)
    assert results[0]["itunes_id"] == "12345"
    assert results[0]["art"] == "big"


def test_lookup_feed_url_resolves():
    def fake_fetch(url):
        assert "id=12345" in url
        return json.dumps({"results": [{"feedUrl": "https://example.com/feed.rss"}]})
    assert lookup_feed_url(fake_fetch, "12345") == "https://example.com/feed.rss"
    assert lookup_feed_url(lambda url: "{}", "1") == ""
    assert lookup_feed_url(lambda url: (_ for _ in ()).throw(OSError()), "1") == ""


def test_charts_url_shape():
    assert charts_url("in", 25) == "https://itunes.apple.com/in/rss/toppodcasts/limit=25/json"
