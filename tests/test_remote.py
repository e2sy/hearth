"""The phone remote: token-gated stdlib HTTP server, headless-tested."""

import json
import time
import urllib.request

import pytest

from hearth.remote import (
    COMMANDS,
    RemoteServer,
    lan_address,
    make_token,
)


class FakeController:
    def __init__(self):
        self.calls: list[tuple] = []
        self.volume = 0.8

    def status(self) -> dict:
        return {
            "playing": False,
            "title": "Ember Song",
            "artist": "Pyre & Co",
            "video_id": "abc123",
            "volume": self.volume,
            "position_ms": 12000,
            "upcoming": 4,
        }

    def cmd(self, name: str, volume: float | None = None) -> None:
        self.calls.append((name, volume))
        if name == "vol" and volume is not None:
            self.volume = volume


@pytest.fixture()
def server():
    ctrl = FakeController()
    srv = RemoteServer(ctrl, host="127.0.0.1", port=0, token="cafebabe")
    srv.start()
    time.sleep(0.05)
    yield srv, ctrl
    srv.stop()


def get(path: str) -> tuple[int, dict | str]:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{path}", timeout=3) as resp:
            body = resp.read().decode("utf-8")
            code = resp.status
    except urllib.error.HTTPError as err:
        body = err.read().decode("utf-8")
        code = err.code
    try:
        return code, json.loads(body)
    except (json.JSONDecodeError, ValueError):
        return code, body


# --- the link is the key ---


def test_root_serves_locked_page(server):
    srv, _ctrl = server
    code, body = get(f"{srv.port}/")
    assert code == 200
    assert "locked" in body.lower()


def test_bad_token_is_forbidden_everywhere(server):
    srv, _ctrl = server
    for path in (f"{srv.port}/remote?k=WRONG",
                 f"{srv.port}/api/status?k=WRONG",
                 f"{srv.port}/api/cmd?k=WRONG&name=next"):
        code, body = get(path)
        assert code == 403
        assert body["ok"] is False


def test_missing_token_is_forbidden(server):
    srv, _ctrl = server
    code, body = get(f"{srv.port}/api/status")
    assert code == 403


def test_control_page_needs_the_key(server):
    srv, _ctrl = server
    code, body = get(f"{srv.port}/remote?k=cafebabe")
    assert code == 200
    assert "Hearth remote" in body


# --- status & commands ---


def test_status_reports_controller_state(server):
    srv, _ctrl = server
    code, body = get(f"{srv.port}/api/status?k=cafebabe")
    assert code == 200
    assert body["title"] == "Ember Song"
    assert body["upcoming"] == 4
    assert body["volume"] == 0.8


def test_next_and_prev_dispatch(server):
    srv, ctrl = server
    code, body = get(f"{srv.port}/api/cmd?k=cafebabe&name=next")
    assert code == 200 and body["ok"] is True
    assert ("next", None) in ctrl.calls
    get(f"{srv.port}/api/cmd?k=cafebabe&name=prev")
    assert ("prev", None) in ctrl.calls


def test_toggle_dispatch(server):
    srv, ctrl = server
    get(f"{srv.port}/api/cmd?k=cafebabe&name=toggle")
    assert ("toggle", None) in ctrl.calls


def test_volume_is_clamped(server):
    srv, ctrl = server
    get(f"{srv.port}/api/cmd?k=cafebabe&name=vol&volume=1.7")
    sent = [v for name, v in ctrl.calls if name == "vol"][0]
    assert sent == 1.0
    get(f"{srv.port}/api/cmd?k=cafebabe&name=vol&volume=-3")
    sent = [v for name, v in ctrl.calls if name == "vol"][-1]
    assert sent == 0.0


def test_unknown_command_is_400(server):
    srv, _ctrl = server
    code, body = get(f"{srv.port}/api/cmd?k=cafebabe&name=launch")
    assert code == 400
    assert body["ok"] is False


def test_unknown_path_is_404(server):
    srv, _ctrl = server
    code, _body = get(f"{srv.port}/nope?k=cafebabe")
    assert code == 404


def test_cmd_answers_with_fresh_status(server):
    srv, ctrl = server
    code, body = get(f"{srv.port}/api/cmd?k=cafebabe&name=vol&volume=0.3")
    assert code == 200
    assert body["status"]["volume"] == 0.3


# --- lifecycle & helpers ---


def test_make_token_is_url_safe_and_unique():
    tokens = {make_token() for _ in range(20)}
    assert len(tokens) == 20
    assert all(t and "/" not in t and "+" not in t for t in tokens)


def test_lan_address_is_an_ip():
    addr = lan_address()
    assert addr.count(".") == 3


def test_server_url_contains_key_and_port(server):
    srv, _ctrl = server
    url = srv.url(host="192.168.1.9")
    assert url.startswith("http://192.168.1.9:")
    assert f":{srv.port}/remote?k=cafebabe" in url


def test_commands_enum_matches_page_and_tests():
    assert set(COMMANDS) == {"toggle", "play", "pause", "next", "prev", "vol"}
