"""v0.6.1 wave: synced lyrics — LRC parsing, sync engine, LRCLIB client, job."""

import json
import urllib.error

import pytest

from hearth import lyrics as lyrics_engine
from hearth.jobs import LyricsJob
from hearth.lyrics import LrcLine, SyncedLyrics, fetch_lyrics, parse_lrc

from .test_models import make_track


# ----------------------------------------------------------------- parsing

def test_parse_lrc_basic_and_sorting():
    raw = "[00:30.00]later line\n[00:10.00]early line\n"
    lines = parse_lrc(raw)
    assert [line.time_ms for line in lines] == [10_000, 30_000]
    assert [line.text for line in lines] == ["early line", "later line"]


def test_parse_lrc_multiple_stamps_one_line():
    lines = parse_lrc("[00:12.00][01:40.50]chorus")
    assert [(line.time_ms, line.text) for line in lines] == [
        (12_000, "chorus"), (100_500, "chorus")
    ]


def test_parse_lrc_fraction_variants():
    lines = parse_lrc("[00:01.5]a\n[00:02.25]b\n[00:03.123]c")
    assert [line.time_ms for line in lines] == [1_500, 2_250, 3_123]


def test_parse_lrc_offset_shifts_every_line():
    lines = parse_lrc("[offset:+500]\n[00:02.00]late\n[00:01.00]early")
    assert [line.time_ms for line in lines] == [500, 1_500]
    back = parse_lrc("[offset:-250]\n[00:02.00]line")
    assert back[0].time_ms == 2_250


def test_parse_lrc_skips_metadata_and_stray_text():
    lines = parse_lrc(
        "[ar:Someone]\n[ti:A song]\n[by:encoder]\n[00:05.00]real line\nstray words"
    )
    assert len(lines) == 1
    assert lines[0].text == "real line"


@pytest.mark.parametrize("raw", ["", "   ", "[ar:x]", "not lrc at all", "[00:xx]bad"])
def test_parse_lrc_garbage_in_empty_out(raw):
    assert parse_lrc(raw) == []


def test_synced_line_at_boundaries():
    sync = SyncedLyrics([
        LrcLine(5_000, "two"), LrcLine(1_000, "one"), LrcLine(9_000, "three")
    ])
    assert sync.line_at(0) == -1          # before the first line
    assert sync.line_at(999) == -1
    assert sync.line_at(1_000) == 0       # exact start owns the moment
    assert sync.line_at(8_999) == 1
    assert sync.line_at(90_000) == 2      # long past the end keeps the last


# ----------------------------------------------------------------- lrclib client

class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload if isinstance(payload, bytes) else json.dumps(payload).encode()

    def read(self):
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def _install_urlopen(monkeypatch, responder):
    """Swap urllib.request.urlopen for `responder(url)`. Returns the call log."""
    calls: list[str] = []

    def fake_urlopen(request, timeout=None):
        url = request.full_url if hasattr(request, "full_url") else str(request)
        calls.append(url)
        return responder(url)

    monkeypatch.setattr(lyrics_engine.urllib.request, "urlopen", fake_urlopen)
    return calls


def test_fetch_exact_hit_returns_plain_and_lrc(monkeypatch):
    payload = {"plainLyrics": "just words", "syncedLyrics": "[00:01.00]timed words"}
    calls = _install_urlopen(
        monkeypatch, lambda url: _FakeResponse(payload)
    )
    plain, lrc = fetch_lyrics("Artist", "Song", duration_sec=180)
    assert plain == "just words"
    assert lrc == "[00:01.00]timed words"
    assert len(calls) == 1 and "/get?" in calls[0]


def test_fetch_falls_back_to_search_and_picks_closest(monkeypatch):
    def responder(url):
        if "/get?" in url:
            raise urllib.error.HTTPError(url, 404, "nope", None, None)
        return _FakeResponse([
            {"duration": 999, "syncedLyrics": "", "plainLyrics": "far too long"},
            {"duration": 181, "syncedLyrics": "[00:01.00]close", "plainLyrics": "close"},
        ])

    _install_urlopen(monkeypatch, responder)
    plain, lrc = fetch_lyrics("Artist", "Song", duration_sec=180)
    assert lrc == "[00:01.00]close"
    assert plain == "close"


def test_fetch_lead_artist_third_leg(monkeypatch):
    def responder(url):
        if "/get?" in url and "A%2C+B" in url:
            # exact leg with the full lineup ('Artist A, B'): not found
            raise urllib.error.HTTPError(url, 404, "nope", None, None)
        if "/search?" in url:
            return _FakeResponse([])           # fuzzy leg comes up empty
        return _FakeResponse({"plainLyrics": "lead words", "syncedLyrics": ""})

    _install_urlopen(monkeypatch, responder)
    plain, lrc = fetch_lyrics("Artist A, B", "Song")
    assert plain == "lead words"


def test_fetch_nothing_anywhere(monkeypatch):
    def responder(url):
        raise urllib.error.HTTPError(url, 404, "nope", None, None)

    _install_urlopen(monkeypatch, responder)
    assert fetch_lyrics("Artist", "Song") == (None, None)


def test_fetch_garbage_json_is_swallowed(monkeypatch):
    _install_urlopen(monkeypatch, lambda url: _FakeResponse(b"not json at all"))
    assert fetch_lyrics("Artist", "Song") == (None, None)


def test_fetch_skips_network_without_names(monkeypatch):
    calls = _install_urlopen(monkeypatch, lambda url: _FakeResponse({}))
    assert fetch_lyrics("", "Song") == (None, None)
    assert fetch_lyrics("Artist", "  ") == (None, None)
    assert calls == []


# ----------------------------------------------------------------- the job

class StubCatalog:
    """Just the lyrics leg — LyricsJob only needs it as last resort."""

    def __init__(self, catalog_text=None):
        self.catalog_text = catalog_text
        self.asked: list[str] = []

    def lyrics(self, video_id):
        self.asked.append(video_id)
        return self.catalog_text


def _run_job(catalog, track, monkeypatch, fetch_result):
    received: list = []
    monkeypatch.setattr(
        lyrics_engine, "fetch_lyrics", lambda *a, **k: fetch_result
    )
    job = LyricsJob(catalog, track)
    job.signals.finished.connect(received.append)
    job.run()
    return received[0]


def test_lyrics_job_prefers_synced_lines(monkeypatch):
    lrc = "[00:01.00]hello\n[00:03.00]again"
    catalog = StubCatalog(catalog_text="yt words")
    video_id, plain, lines = _run_job(
        catalog, make_track(video_id="abc12345678"), monkeypatch, (None, lrc)
    )
    assert video_id == "abc12345678"
    assert plain is None
    assert [line.text for line in lines] == ["hello", "again"]
    assert catalog.asked == []            # catalog leg never needed


def test_lyrics_job_plain_only(monkeypatch):
    catalog = StubCatalog(catalog_text="yt words")
    video_id, plain, lines = _run_job(
        catalog, make_track(video_id="def12345678"), monkeypatch, ("lrclib words", None)
    )
    assert plain == "lrclib words"
    assert lines is None
    assert catalog.asked == []


def test_lyrics_job_falls_back_to_catalog(monkeypatch):
    catalog = StubCatalog(catalog_text="yt words")
    video_id, plain, lines = _run_job(
        catalog, make_track(video_id="ghi12345678"), monkeypatch, (None, None)
    )
    assert plain == "yt words"
    assert lines is None
    assert catalog.asked == ["ghi12345678"]


def test_lyrics_job_survives_fetch_explosion(monkeypatch):
    def boom(*args, **kwargs):
        raise ConnectionError("network gone")

    catalog = StubCatalog(catalog_text="yt words")
    monkeypatch.setattr(lyrics_engine, "fetch_lyrics", boom)
    received: list = []
    job = LyricsJob(catalog, make_track(video_id="jkl12345678"))
    job.signals.finished.connect(received.append)
    job.run()
    assert received[0] == ("jkl12345678", "yt words", None)
