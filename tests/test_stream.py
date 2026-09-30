"""Stream picker, loudness normalization, fake yt-dlp resolution."""

from hearth.stream import normalization_gain, pick_audio_stream, resolve_stream_url


def fmt(abr=0, codec="opus", vcodec="none", url="http://x", protocol="https", asr=44100):
    return {"abr": abr, "acodec": codec, "vcodec": vcodec, "url": url,
            "protocol": protocol, "asr": asr}


def test_prefers_highest_bitrate_audio_only():
    best = pick_audio_stream([
        fmt(abr=70, url="low"),
        fmt(abr=160, url="high"),
        fmt(abr=128, url="mid"),
    ])
    assert best["url"] == "high"


def test_skips_video_streams():
    best = pick_audio_stream([
        fmt(abr=400, codec="avc1", vcodec="avc1", url="video"),
        fmt(abr=96, url="audio"),
    ])
    assert best["url"] == "audio"


def test_skips_urlless_formats_and_hls_when_progressive_available():
    best = pick_audio_stream([
        fmt(abr=999, url=""),
        fmt(abr=140, protocol="m3u8", url="hls"),
        fmt(abr=130, protocol="https", url="progressive"),
    ])
    assert best["url"] == "progressive"


def test_falls_back_to_any_audio_stream():
    best = pick_audio_stream([fmt(abr=50, protocol="m3u8", url="only")])
    assert best["url"] == "only"


def test_empty_formats_returns_none():
    assert pick_audio_stream([]) is None
    assert pick_audio_stream([{"url": "http://x", "acodec": "none", "vcodec": "avc1"}]) is None


def test_normalization_gain_clamped():
    assert normalization_gain(None) == 0.0
    assert normalization_gain(-24.0) == 6.0      # quiet track: boost at ceiling
    assert normalization_gain(-4.0) == -6.0      # loud track: cut at floor
    assert normalization_gain(-18.0) == 2.0      # gentle nudge


class FakeYDL:
    def __init__(self, info):
        self.info = info

    def extract_info(self, url, download=False):
        return self.info


def test_resolve_uses_best_format_and_loudness():
    info = {
        "formats": [fmt(abr=128, url="mid"), fmt(abr=256, url="top")],
        "loudness": -9.0,
    }
    url, loudness = resolve_stream_url("https://youtube.com/watch?v=x",
                                       ydl_factory=lambda: FakeYDL(info))
    assert url == "top"
    assert loudness == -9.0


def test_resolve_survives_failure():
    def boom_factory():
        class Boom:
            def extract_info(self, url, download=False):
                raise RuntimeError("network down")

        return Boom()

    url, loudness = resolve_stream_url("https://youtube.com/watch?v=x", ydl_factory=boom_factory)
    assert url is None
    assert loudness is None
