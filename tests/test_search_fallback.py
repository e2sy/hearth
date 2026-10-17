"""Search that never dies: catalogue miss -> yt-dlp web fallback.

The main search box used to consult ONLY the YT Music guest catalogue;
a bot-checked or starved leg ended the search as a silent zero and the
page looked broken. These tests pin the new contract: SearchJob falls
through search_everywhere (songs -> videos -> web index), and a pasted
link the catalogue cannot name is still fetched straight from yt-dlp.
"""

from types import SimpleNamespace

from hearth.catalog import web_track_for_id
from hearth.jobs import SearchJob
from hearth.models import Track

from .test_models import make_track


class EverywhereCatalog:
    """Fake with the one method the new SearchJob path uses."""

    def __init__(self, result):
        self._result = result
        self.calls: list[tuple] = []

    def search_everywhere(self, query, limit=20, fallback=None, **_kw):
        self.calls.append((query, limit, fallback is not None))
        return self._result


class DetailsOnlyCatalog:
    """Fake catalogue: song_details answers, search legs are absent."""

    def __init__(self, track):
        self._track = track

    def song_details(self, video_id):
        return self._track


def _run_and_collect(job: SearchJob) -> list[tuple[str, object]]:
    """Run the job, recording (kind, payload) pairs from emit_safe."""
    payloads: list[tuple[str, object]] = []

    class _FakeCarrier:
        finished = "finished-marker"
        failed = "failed-marker"

        @staticmethod
        def emit_safe(signal, value):
            payloads.append((signal, value))

    original = job.signals
    job.signals = _FakeCarrier()
    try:
        job.run()
    finally:
        job.signals = original
    return payloads


def test_search_job_uses_everywhere_with_fallback():
    tracks = [make_track(video_id="a"), make_track(video_id="b")]
    catalog = EverywhereCatalog(tracks)
    job = SearchJob(catalog, "daft punk", limit=15)
    payloads = _run_and_collect(job)
    assert payloads and payloads[0] == ("finished-marker", tracks)
    query, limit, had_fallback = catalog.calls[0]
    assert query == "daft punk"
    assert limit == 15
    assert had_fallback is True   # the web fallback is wired in


def test_search_job_pasted_link_known_by_catalogue():
    track = make_track(video_id="abc12345678")
    job = SearchJob(DetailsOnlyCatalog(track), "https://youtu.be/abc12345678")
    payloads = _run_and_collect(job)
    assert payloads and payloads[0] == ("finished-marker", [track])


def test_search_job_pasted_link_unknown_by_catalogue(monkeypatch):
    fallback_track = make_track(video_id="abc12345678", title="Raw upload")
    calls: list[str] = []

    def fake_web_track_for_id(video_id: str) -> list[Track]:
        calls.append(video_id)
        return [fallback_track]

    monkeypatch.setattr(
        "hearth.catalog.web_track_for_id", fake_web_track_for_id
    )
    job = SearchJob(DetailsOnlyCatalog(None), "https://youtu.be/abc12345678")
    payloads = _run_and_collect(job)
    assert calls == ["abc12345678"]
    assert payloads and payloads[0] == ("finished-marker", [fallback_track])


def test_web_track_for_id_maps_yt_dlp_info(monkeypatch):
    info = {
        "id": "abc12345678",
        "title": "Some Rare Session",
        "uploader": "Tiny Desk",
        "channel_id": "UCchannel123",
        "duration": 254,
        "thumbnails": [{"url": "https://img/small"}, {"url": "https://img/big"}],
    }

    class FakeYDL:
        def __init__(self, opts):
            pass

        def extract_info(self, url, download=False):
            assert "abc12345678" in url
            return info

    fake_module = SimpleNamespace(YoutubeDL=FakeYDL)
    monkeypatch.setitem(__import__("sys").modules, "yt_dlp", fake_module)
    tracks = web_track_for_id("abc12345678")
    assert len(tracks) == 1
    t = tracks[0]
    assert t.video_id == "abc12345678"
    assert t.title == "Some Rare Session"
    assert t.artist == "Tiny Desk"
    assert t.duration_sec == 254
    assert t.thumbnail == "https://img/big"
    assert t.artist_id == "UCchannel123"


def test_web_track_for_id_never_raises(monkeypatch):
    class BoomYDL:
        def __init__(self, opts):
            pass

        def extract_info(self, url, download=False):
            raise RuntimeError("bot-checked")

    fake_module = SimpleNamespace(YoutubeDL=BoomYDL)
    monkeypatch.setitem(__import__("sys").modules, "yt_dlp", fake_module)
    assert web_track_for_id("abc12345678") == []
