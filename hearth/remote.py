"""The phone remote: drive Hearth from any browser on the same Wi-Fi.

stdlib-only — a ThreadingHTTPServer in a daemon thread, zero new
dependencies. The design has one security idea: **the link is the key**.
Every useful route (the control page included) carries a per-session
token baked into the URL, so a stranger scanning the LAN only ever sees
a locked page. No pairing UI, no accounts, nothing stored.

The server never touches Qt. It talks to a duck-typed *controller* the
app injects (`status()` plus `cmd(name, volume=None)`), so the whole
thing runs headless in tests — the same pattern as the ambient mixer's
pure generator and the scrobble queue.

Routes (all GET, browser-friendly):

- ``/``                  → locked page; tells the visitor to use the link
- ``/remote?k=KEY``      → the control page (HTML reads KEY from its URL)
- ``/api/status?k=KEY``  → JSON snapshot of the player
- ``/api/cmd?k=KEY&name=toggle|play|pause|next|prev|vol[&volume=0.42]``
                         → apply a command, answer with the fresh status

Bad or missing keys get 403 JSON; unknown commands get 400. Everything
degrades honestly — a controller that raises gets a 500 with ``ok:false``
instead of a hung socket.
"""

from __future__ import annotations

import json
import re
import secrets
import socket
import threading
import time
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable
from urllib.parse import parse_qs, urlparse

from . import config

COMMANDS = ("toggle", "play", "pause", "next", "prev", "vol")

_LOCKED_PAGE = """<!doctype html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Hearth — locked</title>
<style>body{font-family:system-ui;background:#14100e;color:#f4e9dd;display:grid;place-items:center;height:100vh;margin:0}
div{text-align:center}h1{font-size:22px}p{opacity:.7;font-size:14px}</style></head>
<body><div><h1>🔥 This hearth is locked</h1>
<p>Open the phone-remote link shown in the Hearth app — the link is the key.</p></div></body></html>
"""

_REMOTE_PAGE = """<!doctype html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Hearth remote</title>
<style>
body{font-family:system-ui;background:#14100e;color:#f4e9dd;margin:0;display:flex;flex-direction:column;align-items:center;justify-content:center;min-height:100vh}
h1{font-size:18px;opacity:.85}.card{background:#1e1713;border-radius:14px;padding:18px;margin:8px;width:min(88vw,420px);box-shadow:0 6px 24px rgba(0,0,0,.5)}
#title{font-weight:700;font-size:17px}#artist{opacity:.65;font-size:14px;margin-top:2px}
.row{display:flex;gap:10px;margin-top:14px}button{flex:1;padding:14px 0;font-size:17px;border:0;border-radius:10px;background:#ff7a18;color:#14100e;font-weight:800;cursor:pointer}
button.sec{background:#33261d;color:#f4e9dd}input[type=range]{width:100%;accent-color:#ff7a18}
#pos{opacity:.55;font-size:12px;margin-top:8px}
</style></head>
<body><h1>🔥 Hearth remote</h1>
<div class="card"><div id="title">—</div><div id="artist"></div><div id="pos"></div>
<div class="row"><button class="sec" onclick="cmd('prev')">⏮</button>
<button onclick="cmd('toggle')">⏯</button>
<button class="sec" onclick="cmd('next')">⏭</button></div></div>
<div class="card"><input id="vol" type="range" min="0" max="100" value="80" oninput="vol(this.value)"></div>
<div class="card"><button class="sec" style="width:100%" onclick="suggestSong()">➕ Suggest a song for the host</button></div>
<script>
const k = new URLSearchParams(location.search).get('k') || '';
async function paint(s){document.getElementById('title').textContent=s.title||'Nothing playing';
document.getElementById('artist').textContent=s.artist||'';
document.getElementById('pos').textContent=(s.playing?'▶ playing · ':'⏸ paused · ')+(s.upcoming||0)+' queued · volume '+Math.round((s.volume||0)*100)+'%';
const v=document.getElementById('vol');if(document.activeElement!==v)v.value=Math.round((s.volume||0)*100);}
async function refresh(){try{const r=await fetch('/api/status?k='+encodeURIComponent(k));paint(await r.json());}catch(e){}}
async function cmd(name){try{const r=await fetch('/api/cmd?k='+encodeURIComponent(k)+'&name='+name);paint((await r.json()).status||{});}catch(e){}}
async function vol(v){try{await fetch('/api/cmd?k='+encodeURIComponent(k)+'&name=vol&volume='+(v/100));}catch(e){}}
async function suggestSong(){const t=prompt('Paste a YouTube link (or just the video id):');if(!t)return;
try{const r=await fetch('/api/suggest?k='+encodeURIComponent(k)+'&video='+encodeURIComponent(t));const j=await r.json();
alert(j.ok?(j.accepted?'🔥 Suggested — the host will see it.':'Already suggested — the host has it.'):'Nope: '+(j.error||'not possible'));}catch(e){}}
refresh();setInterval(refresh,4000);
</script></body></html>
"""


def make_token() -> str:
    """A short, URL-safe session key — the link is the permission."""
    return secrets.token_hex(4)


_VIDEO_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")
_VIDEO_ID_IN_URL = re.compile(r"(?:[?&]v=|youtu\.be/|/shorts/|/embed/)([A-Za-z0-9_-]{11})")


def parse_video_id(text: str) -> str:
    """A raw id, a youtu.be link, a watch?v= link — the id inside, or ''.

    Guests paste whatever their phone copied; every reasonable shape
    lands on the same 11-character id.
    """
    text = (text or "").strip().strip('"<>')
    if _VIDEO_ID.match(text):
        return text
    match = _VIDEO_ID_IN_URL.search(text)
    return match.group(1) if match else ""


class SuggestionInbox:
    """The party hat: guest suggestions waiting for the host's nod.

    Bounded (config.PARTY_INBOX_MAX), deduped by video id (a repeat
    bumps the entry instead of stacking), and purely passive — the
    host's app drains it whenever the UI gets around to it. Host
    playback stays authoritative; nothing here touches the queue.
    """

    def __init__(self, max_items: int | None = None):
        self._max = int(max_items or config.PARTY_INBOX_MAX)
        self._items: deque[dict] = deque()

    def push(self, item: dict, *, now: float | None = None) -> bool:
        """Add a suggestion; True = new, False = duplicate or junk."""
        video_id = parse_video_id(str(item.get("video_id") or ""))
        if not video_id:
            return False
        entry = {
            "video_id": video_id,
            "title": str(item.get("title") or "").strip()[:200] or video_id,
            "artist": str(item.get("artist") or "").strip()[:120],
            "duration_sec": item.get("duration_sec"),
            "at": float(now if now is not None else time.time()),
        }
        for existing in self._items:               # a repeat bumps, not stacks
            if existing["video_id"] == video_id:
                self._items.remove(existing)
                self._items.append(entry)
                return False
        self._items.append(entry)
        while len(self._items) > self._max:
            self._items.popleft()
        return True

    def pending(self) -> list[dict]:
        """Oldest-first snapshot; the inbox keeps its contents."""
        return list(self._items)

    def drain(self) -> list[dict]:
        """Hand over everything and clear — the host just reviewed it."""
        items = list(self._items)
        self._items.clear()
        return items

    def __len__(self) -> int:
        return len(self._items)


def lan_address() -> str:
    """Best-effort LAN IP for the shareable URL; 127.0.0.1 when unsure."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("10.255.255.255", 1))   # no packets actually sent
        return str(sock.getsockname()[0])
    except OSError:
        return "127.0.0.1"
    finally:
        sock.close()


def _make_handler(
    controller: Any,
    token: str,
    logger: Callable[[str], None] | None = None,
) -> type[BaseHTTPRequestHandler]:
    """Build a handler class bound to one controller + session key."""

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt: str, *args: Any) -> None:  # silence stdlib
            if logger is not None:
                logger(fmt % args)

        # --- helpers ---

        def _authorized(self, qs: dict[str, list[str]]) -> bool:
            got = (qs.get("k") or [""])[0]
            return secrets.compare_digest(str(got), token)

        def _send_json(self, code: int, payload: dict[str, Any]) -> None:
            body = json.dumps(payload).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _send_html(self, code: int, html: str) -> None:
            body = html.encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        # --- routing ---

        def do_GET(self) -> None:  # noqa: N802 — stdlib naming
            try:
                url = urlparse(self.path)
                qs = parse_qs(url.query)
                if url.path in ("/", "/index.html"):
                    self._send_html(200, _LOCKED_PAGE)
                    return
                if url.path == "/remote":
                    if not self._authorized(qs):
                        self._send_json(403, {"ok": False, "error": "forbidden"})
                        return
                    self._send_html(200, _REMOTE_PAGE)
                    return
                if url.path in ("/api/status", "/api/cmd"):
                    if not self._authorized(qs):
                        self._send_json(403, {"ok": False, "error": "forbidden"})
                        return
                    if url.path == "/api/status":
                        self._send_json(200, controller.status())
                        return
                    name = (qs.get("name") or [""])[0].strip().lower()
                    if name not in COMMANDS:
                        self._send_json(
                            400, {"ok": False, "error": f"unknown command: {name!r}"}
                        )
                        return
                    volume: float | None = None
                    if name == "vol":
                        try:
                            volume = max(0.0, min(1.0, float((qs.get("volume") or [""])[0])))
                        except ValueError:
                            self._send_json(400, {"ok": False, "error": "bad volume"})
                            return
                    controller.cmd(name, volume=volume)
                    self._send_json(200, {"ok": True, "status": controller.status()})
                    return
                if url.path == "/api/suggest":
                    if not self._authorized(qs):
                        self._send_json(403, {"ok": False, "error": "forbidden"})
                        return
                    suggest_hook = getattr(controller, "suggest", None)
                    if not callable(suggest_hook):
                        self._send_json(400, {
                            "ok": False,
                            "error": "party mode is not enabled on this hearth",
                        })
                        return
                    video_id = parse_video_id((qs.get("video") or [""])[0])
                    if not video_id:
                        self._send_json(400, {"ok": False, "error": "no video id in paste"})
                        return
                    duration_sec: int | None = None
                    try:
                        duration_sec = int((qs.get("dur") or [""])[0])
                        if not 0 <= duration_sec <= 86400:
                            duration_sec = None
                    except ValueError:
                        duration_sec = None
                    item = {
                        "video_id": video_id,
                        "title": (qs.get("title") or [""])[0],
                        "artist": (qs.get("artist") or [""])[0],
                        "duration_sec": duration_sec,
                    }
                    accepted = bool(suggest_hook(item))
                    pending_hook = getattr(controller, "pending_suggestions", None)
                    pending = pending_hook() if callable(pending_hook) else None
                    payload: dict[str, Any] = {"ok": True, "accepted": accepted}
                    if isinstance(pending, int):
                        payload["pending"] = pending
                    self._send_json(200, payload)
                    return
                self._send_json(404, {"ok": False, "error": "not found"})
            except (BrokenPipeError, ConnectionResetError):
                pass          # the phone wandered off — nothing to answer
            except Exception as exc:   # honest 500 instead of a hung socket
                try:
                    self._send_json(500, {"ok": False, "error": str(exc)})
                except Exception:
                    pass

    return Handler


class RemoteServer:
    """One session of the phone remote: start, share the URL, stop."""

    def __init__(
        self,
        controller: Any,
        host: str = "0.0.0.0",
        port: int = 0,
        token: str | None = None,
        logger: Callable[[str], None] | None = None,
    ):
        self._controller = controller
        self._host = host
        self._token = token or make_token()
        self._logger = logger
        self._httpd = ThreadingHTTPServer(
            (host, int(port)), _make_handler(controller, self._token, logger)
        )
        self._thread: threading.Thread | None = None

    # --- lifecycle ---

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._thread = threading.Thread(
            target=self._httpd.serve_forever, daemon=True, name="hearth-remote"
        )
        self._thread.start()

    def stop(self) -> None:
        try:
            self._httpd.shutdown()
            self._httpd.server_close()
        except OSError:
            pass

    # --- introspection ---

    @property
    def port(self) -> int:
        return int(self._httpd.server_address[1])

    @property
    def token(self) -> str:
        return self._token

    def url(self, host: str | None = None) -> str:
        """The shareable link — the page and the permission in one string."""
        return f"http://{host or lan_address()}:{self.port}/remote?k={self._token}"
