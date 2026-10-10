"""v0.8.0 Room 8.2 groundwork — party suggestions: inbox + /api/suggest."""

import json
import time
import urllib.parse
import urllib.request

from hearth.remote import (
    RemoteServer,
    SuggestionInbox,
    parse_video_id,
)


class FakeController:
    """No suggest hook — the route must answer 'party mode not enabled'."""

    def status(self) -> dict:
        return {"playing": False, "title": "x", "artist": "", "volume": 0.5,
                "position_ms": 0, "upcoming": 0}

    def cmd(self, name, volume=None):
        pass


class PartyController(FakeController):
    """The host's side: a real inbox behind the suggest hook."""

    def __init__(self):
        self.inbox = SuggestionInbox(max_items=5)

    def suggest(self, item: dict) -> bool:
        return self.inbox.push(item)

    def pending_suggestions(self) -> int:
        return len(self.inbox)


def request(path: str) -> tuple[int, dict | str]:
    url = f"http://127.0.0.1:{path}" if not path.startswith("http") else path
    try:
        with urllib.request.urlopen(url, timeout=3) as resp:
            body, code = resp.read().decode("utf-8"), resp.status
    except urllib.error.HTTPError as err:
        body, code = err.read().decode("utf-8"), err.code
    try:
        return code, json.loads(body)
    except (json.JSONDecodeError, ValueError):
        return code, body


# --- parse_video_id ---


def test_parse_video_id_shapes():
    assert parse_video_id("dQw4w9WgXcQ") == "dQw4w9WgXcQ"
    assert parse_video_id("  https://youtu.be/dQw4w9WgXcQ?t=1m ") == "dQw4w9WgXcQ"
    assert parse_video_id("https://www.youtube.com/watch?app=x&v=dQw4w9WgXcQ") == "dQw4w9WgXcQ"
    assert parse_video_id("https://music.youtube.com/watch?v=dQw4w9WgXcQ&si=z") == "dQw4w9WgXcQ"
    assert parse_video_id("https://www.youtube.com/shorts/dQw4w9WgXcQ") == "dQw4w9WgXcQ"
    assert parse_video_id('"dQw4w9WgXcQ"') == "dQw4w9WgXcQ"


def test_parse_video_id_rejects_junk():
    assert parse_video_id("") == ""
    assert parse_video_id("too short") == ""
    assert parse_video_id("https://example.com/nothing") == ""
    assert parse_video_id(None) == "" if False else parse_video_id("") == ""


# --- SuggestionInbox ---


def test_inbox_push_and_pending_order():
    box = SuggestionInbox(max_items=3)
    assert box.push({"video_id": "aaaaaaaaaaa", "title": "One"}) is True
    assert box.push({"video_id": "bbbbbbbbbbb", "title": "Two"}) is True
    assert [i["video_id"] for i in box.pending()] == ["aaaaaaaaaaa", "bbbbbbbbbbb"]
    assert len(box) == 2


def test_inbox_dedupes_by_video_id_and_bumps():
    box = SuggestionInbox()
    box.push({"video_id": "aaaaaaaaaaa", "title": "One"})
    assert box.push({"video_id": "aaaaaaaaaaa", "title": "One again"}) is False
    pending = box.pending()
    assert len(pending) == 1
    assert pending[0]["title"] == "One again"


def test_inbox_accepts_url_paste():
    box = SuggestionInbox()
    assert box.push({"video_id": "https://youtu.be/dQw4w9WgXcQ"}) is True
    assert box.pending()[0]["video_id"] == "dQw4w9WgXcQ"


def test_inbox_rejects_junk():
    box = SuggestionInbox()
    assert box.push({"video_id": ""}) is False
    assert box.push({}) is False
    assert box.push({"video_id": "nope"}) is False


def test_inbox_bounded_drops_oldest():
    box = SuggestionInbox(max_items=2)
    for i, vid in enumerate(["aaaaaaaaaaa", "bbbbbbbbbbb", "ccccccccccc"]):
        box.push({"video_id": vid, "title": f"T{i}"})
    assert [i["video_id"] for i in box.pending()] == ["bbbbbbbbbbb", "ccccccccccc"]


def test_inbox_drain_clears():
    box = SuggestionInbox()
    box.push({"video_id": "aaaaaaaaaaa"})
    items = box.drain()
    assert len(items) == 1 and len(box) == 0
    assert box.drain() == []


def test_inbox_entry_fields_are_sanitized():
    box = SuggestionInbox()
    box.push({"video_id": "aaaaaaaaaaa",
              "title": "x" * 500, "artist": "y" * 300,
              "duration_sec": 99}, now=123.0)
    entry = box.pending()[0]
    assert len(entry["title"]) == 200
    assert len(entry["artist"]) == 120
    assert entry["duration_sec"] == 99
    assert entry["at"] == 123.0


# --- the HTTP route ---


def test_suggest_route_requires_party_enabled():
    srv = RemoteServer(FakeController(), host="127.0.0.1", port=0, token="cafebabe")
    srv.start()
    time.sleep(0.05)
    try:
        qs = urllib.parse.urlencode({"k": "cafebabe", "video": "dQw4w9WgXcQ"})
        code, body = request(f"{srv.port}/api/suggest?{qs}")
        assert code == 400
        assert "party mode" in body["error"]
    finally:
        srv.stop()


def test_suggest_route_accepts_and_dedupes():
    ctrl = PartyController()
    srv = RemoteServer(ctrl, host="127.0.0.1", port=0, token="cafebabe")
    srv.start()
    time.sleep(0.05)
    try:
        qs = urllib.parse.urlencode({
            "k": "cafebabe", "video": "https://youtu.be/dQw4w9WgXcQ",
            "title": "Party Song", "artist": "DJ Ember", "dur": "200",
        })
        code, body = request(f"{srv.port}/api/suggest?{qs}")
        assert code == 200 and body["ok"] is True and body["accepted"] is True
        assert body["pending"] == 1
        # same song again → accepted False, still one entry
        code, body = request(f"{srv.port}/api/suggest?{qs}")
        assert body["accepted"] is False and body["pending"] == 1
        entry = ctrl.inbox.pending()[0]
        assert entry["video_id"] == "dQw4w9WgXcQ"
        assert entry["title"] == "Party Song"
        assert entry["duration_sec"] == 200
    finally:
        srv.stop()


def test_suggest_route_rejects_bad_key_and_bad_video():
    ctrl = PartyController()
    srv = RemoteServer(ctrl, host="127.0.0.1", port=0, token="cafebabe")
    srv.start()
    time.sleep(0.05)
    try:
        code, body = request(f"{srv.port}/api/suggest?k=wrong&video=dQw4w9WgXcQ")
        assert code == 403
        qs = urllib.parse.urlencode({"k": "cafebabe", "video": "garbage"})
        code, body = request(f"{srv.port}/api/suggest?{qs}")
        assert code == 400
        assert len(ctrl.inbox) == 0
    finally:
        srv.stop()


def test_suggest_route_bad_duration_is_tolerated():
    ctrl = PartyController()
    srv = RemoteServer(ctrl, host="127.0.0.1", port=0, token="cafebabe")
    srv.start()
    time.sleep(0.05)
    try:
        qs = urllib.parse.urlencode({"k": "cafebabe", "video": "dQw4w9WgXcQ", "dur": "abc"})
        code, body = request(f"{srv.port}/api/suggest?{qs}")
        assert code == 200 and body["accepted"] is True
        assert ctrl.inbox.pending()[0]["duration_sec"] is None
    finally:
        srv.stop()
