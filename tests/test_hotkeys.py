"""Hotkey conflict detection and override merging."""

from hearth.config import DEFAULT_HOTKEYS
from hearth.hotkeys import effective_chords, find_hotkey_conflicts


def test_defaults_have_no_conflicts():
    assert find_hotkey_conflicts(DEFAULT_HOTKEYS) == []


def test_detects_duplicate_binding():
    problems = find_hotkey_conflicts({
        "play_pause": "Ctrl+Alt+Space",
        "next_track": "Ctrl+Alt+Space",
    })
    assert any("both" in p for p in problems)


def test_detects_reserved_system_chords():
    problems = find_hotkey_conflicts({"focus_search": "Alt+F4"})
    assert any("system shortcut" in p for p in problems)


def test_detects_empty_chord():
    problems = find_hotkey_conflicts({"play_pause": "  "})
    assert any("empty chord" in p for p in problems)


def test_case_insensitive_duplicate():
    problems = find_hotkey_conflicts({
        "play_pause": "Ctrl+Alt+E",
        "toggle_panel": "ctrl+alt+e",
    })
    assert len(problems) >= 1


def test_effective_chords_merge_overrides():
    merged = effective_chords({"next_track": "Ctrl+Alt+N"})
    assert merged["next_track"] == "Ctrl+Alt+N"
    assert merged["play_pause"] == DEFAULT_HOTKEYS["play_pause"]


def test_effective_chords_ignores_unknown_actions_and_blanks():
    merged = effective_chords({"banana": "Ctrl+1", "next_track": "  "})
    assert "banana" not in merged
    assert merged["next_track"] == DEFAULT_HOTKEYS["next_track"]
