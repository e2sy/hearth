"""Queue comforts pinned: remaining-time labels, reverse, dedupe."""

from hearth.queue_tools import (
    dedupe,
    fmt_remaining,
    remaining_label,
    remaining_seconds,
    reverse_upcoming,
)


# ------------------------------------------------------- remaining time

def test_remaining_seconds_sums_known_durations():
    assert remaining_seconds([60, 90, 30]) == 180


def test_remaining_seconds_treats_unknown_as_zero():
    assert remaining_seconds([60, None, "junk", 90]) == 150


def test_remaining_seconds_clamps_negatives_and_survives_none_list():
    assert remaining_seconds([60, -30]) == 60
    assert remaining_seconds(None) == 0
    assert remaining_seconds([]) == 0


def test_fmt_minutes_only():
    assert fmt_remaining(42 * 60) == "42 min left"


def test_fmt_zero_stays_honest():
    assert fmt_remaining(0) == "0 min left"


def test_fmt_hour_mix():
    assert fmt_remaining((60 + 12) * 60 + 31) == "1 h 12 min left"


def test_fmt_never_shows_seconds():
    assert "sec" not in fmt_remaining(3)


def test_fmt_negative_clamps_to_zero():
    assert fmt_remaining(-100) == "0 min left"


def test_remaining_label_one_call():
    assert remaining_label([30 * 60, 12 * 60]) == "42 min left"


# ------------------------------------------------------------- reverse

def test_reverse_returns_copy_not_same_list():
    src = [1, 2, 3]
    out = reverse_upcoming(src)
    assert out == [3, 2, 1]
    assert out is not src


def test_reverse_empty_and_single():
    assert reverse_upcoming([]) == []
    assert reverse_upcoming(["a"]) == ["a"]


# --------------------------------------------------------------- dedupe

def test_dedupe_keeps_first_copy_in_order():
    assert dedupe([3, 1, 3, 2, 1], key=lambda x: x) == [3, 1, 2]


def test_dedupe_by_key_field():
    class T:
        def __init__(self, vid, title):
            self.video_id, self.title = vid, title

    a = T("x", "one")
    b = T("y", "two")
    c = T("x", "one again")
    out = dedupe([a, b, c], key=lambda t: t.video_id)
    assert out == [a, b]


def test_dedupe_empty():
    assert dedupe([]) == []


def test_dedupe_handles_unhashable_keys():
    assert dedupe([[1], [2], [1]], key=tuple) == [[1], [2]]
