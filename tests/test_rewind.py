"""The Rewind story: pure scene-builder math, Qt-free (v0.7.1)."""

from hearth.models import Track
from hearth.rewind import (
    EMPTY_STORY,
    build_rewind_story,
    busiest_month,
    longest_streak,
    peak_day,
)

from .test_models import make_track


def rich_stats() -> dict:
    return {
        "total_plays": 1204,
        "unique_tracks": 388,
        "est_minutes": 5010,
        "days_listened": 210,
        "first_play": "2026-01-02T09:00:00",
        "top_tracks": [make_track(title="Ember Song", artist="Pyre & Co")],
        "top_artists": [("Pyre & Co", 240), ("Kindling", 90)],
    }


def rich_days() -> list[tuple[str, int]]:
    return [
        ("2026-01-02", 3),
        ("2026-01-03", 5),
        ("2026-01-04", 9),   # peak
        ("2026-03-01", 40),
        ("2026-03-02", 38),  # busiest month overall
    ]


# --- helpers ---


def test_peak_day_picks_loudest():
    assert peak_day(rich_days()) == ("2026-03-01", 40)


def test_peak_day_empty():
    assert peak_day([]) is None
    assert peak_day(None) is None


def test_longest_streak_counts_consecutive_days():
    days = [("2026-01-01", 1), ("2026-01-02", 2), ("2026-01-03", 1),
            ("2026-01-07", 4), ("2026-01-08", 1)]
    assert longest_streak(days) == 3


def test_longest_streak_ignores_single_days():
    assert longest_streak([("2026-01-01", 5)]) == 0


def test_longest_streak_bad_dates_survive():
    days = [("2026-01-01", 1), ("2026-01-02", 1), ("garbage", 1)]
    assert longest_streak(days) == 2


def test_busiest_month_sums():
    assert busiest_month(rich_days()) == ("2026-03", 78)


def test_busiest_month_thin():
    assert busiest_month([]) is None


# --- the story itself ---


def test_empty_history_returns_empty_story():
    stats = {"total_plays": 0}
    assert build_rewind_story(stats, [], [], []) == EMPTY_STORY


def test_empty_stats_dict_is_safe():
    assert build_rewind_story(None, None, [], []) == EMPTY_STORY


def test_rich_history_weaves_all_scenes():
    scenes = build_rewind_story(rich_stats(), rich_days(),
                                rich_stats()["top_tracks"],
                                rich_stats()["top_artists"])
    text = "\n".join(scenes)
    assert any("1,204 plays" in s for s in scenes)
    assert "Pyre & Co owned your year" in text
    assert "Ember Song" in text
    assert "March 1, 2026 burned brightest" in text
    assert "March 2026 was your loudest month" in text
    assert any("streak" in s for s in scenes)
    assert any("began on" in s for s in scenes)


def test_story_capped_at_max_scenes():
    stats = rich_stats()
    stats["unique_tracks"] = 999   # every optional scene present
    scenes = build_rewind_story(stats, rich_days(),
                                stats["top_tracks"], stats["top_artists"])
    assert len(scenes) <= 8


def test_thin_stats_still_tell_something():
    stats = {"total_plays": 3, "unique_tracks": 0, "est_minutes": 0,
             "days_listened": 1, "first_play": None,
             "top_tracks": [], "top_artists": []}
    scenes = build_rewind_story(stats, [], [], [])
    assert scenes and "3 plays" in scenes[0]


def test_corrupt_artist_rows_do_not_crash():
    stats = rich_stats()
    stats["top_artists"] = [("", 5)]   # blank name is skipped
    scenes = build_rewind_story(stats, rich_days(), stats["top_tracks"],
                                stats["top_artists"])
    assert not any("owned your year" in s for s in scenes)


def test_track_without_attributes_survives():
    stats = rich_stats()
    stats["top_tracks"] = [object()]   # duck-typed junk
    scenes = build_rewind_story(stats, [], stats["top_tracks"], [])
    assert scenes   # falls back to placeholder words, never raises


def test_first_play_odd_format_degrades():
    stats = rich_stats()
    stats["first_play"] = "not-a-date"
    scenes = build_rewind_story(stats, [], [], [])
    assert not any("began on" in s for s in scenes)
