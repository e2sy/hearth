"""Zero-dependency helpers in utils.py."""

import pytest

from hearth.utils import clamp, clock, looks_like_link, pretty_count


def test_clock_minutes():
    assert clock(213000) == "3:33"


def test_clock_hours():
    assert clock(3723000) == "1:02:03"


def test_clock_clamps_negative_and_zero():
    assert clock(-5) == "0:00"
    assert clock(0) == "0:00"


def test_clock_handles_none():
    assert clock(None) == "0:00"


def test_looks_like_link():
    assert looks_like_link("https://youtu.be/dQw4w9WgXcQ")
    assert looks_like_link("https://www.youtube.com/watch?v=x")
    assert looks_like_link("http://music.youtube.com/watch?v=x")
    assert not looks_like_link("daft punk one more time")
    assert not looks_like_link("")
    assert not looks_like_link(None)


def test_pretty_count_singular_and_plural():
    assert pretty_count(1, "track") == "1 track"
    assert pretty_count(12, "track") == "12 tracks"
    assert pretty_count(2, "person", "people") == "2 people"


def test_clamp():
    assert clamp(5, 0, 10) == 5
    assert clamp(-1, 0, 10) == 0
    assert clamp(99, 0, 10) == 10
