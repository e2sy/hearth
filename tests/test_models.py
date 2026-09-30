"""Track model, duration helpers, JSON roundtrip."""

from hearth.models import Track, format_duration, parse_duration


def make_track(**overrides) -> Track:
    base = dict(
        video_id="dQw4w9WgXcQ",
        title="Never Gonna Give You Up",
        artist="Rick Astley",
        duration="3:33",
        duration_sec=213,
        thumbnail="https://example.com/art.jpg",
    )
    base.update(overrides)
    return Track(**base)


def test_roundtrip_dict():
    t = make_track()
    assert Track.from_dict(t.to_dict()) == t


def test_roundtrip_json_preserves_unicode():
    t = make_track(title="Bésame Mucho – Café Version")
    t2 = Track.from_json(t.to_json())
    assert t2.title == t.title
    assert t2 == t


def test_unknown_keys_are_dropped():
    t = Track.from_dict({**make_track().to_dict(), "future_field": 42})
    assert not hasattr(t, "future_field")


def test_display_name_with_artist():
    assert make_track().display_name == "Rick Astley — Never Gonna Give You Up"


def test_display_name_without_artist():
    t = make_track(artist="")
    assert t.display_name == t.title


def test_format_duration_minutes():
    assert format_duration(213) == "3:33"


def test_format_duration_hours():
    assert format_duration(3723) == "1:02:03"


def test_format_duration_garbage():
    assert format_duration(None) == ""
    assert format_duration(-5) == ""


def test_parse_duration():
    assert parse_duration("3:33") == 213
    assert parse_duration("1:02:03") == 3723
    assert parse_duration("") == 0
    assert parse_duration("abc") == 0
