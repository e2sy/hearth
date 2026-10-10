"""Palette integrity and lookup."""

from hearth.config import (
    DEFAULT_PALETTE,
    PALETTES,
    Palette,
    get_palette,
    palette_keys,
    validate_palette,
)


def test_all_palettes_valid():
    for key, palette in PALETTES.items():
        assert validate_palette(palette) == [], f"{key} invalid: {validate_palette(palette)}"


def test_at_least_five_themes():
    assert len(PALETTES) >= 5


def test_keys_unique_and_match():
    for key, palette in PALETTES.items():
        assert palette.key == key


def test_get_palette_valid():
    assert get_palette("frost") is PALETTES["frost"]


def test_get_palette_fallback():
    assert get_palette("nonexistent") is PALETTES[DEFAULT_PALETTE]
    assert get_palette(None) is PALETTES[DEFAULT_PALETTE]


def test_palette_keys_tuple():
    assert DEFAULT_PALETTE in palette_keys()


def test_validate_catches_bad_color():
    bad = Palette(
        key="broken", label="Broken",
        bg="zzz", surface="#1d1712", surface_alt="#282017",
        hairline="#3a2f22", text="#f3e9d8", text_dim="#a89880",
        accent="#f0a437", accent_soft="#f6c97e", danger="#e2694f",
        success="#8fbf6f", selection="#4a3517", scroll="#3a2f22",
    )
    problems = validate_palette(bad)
    assert any("bg" in p for p in problems)


def test_validate_catches_invisible_text():
    bad = Palette(
        key="invisible", label="Invisible",
        bg="#14100c", surface="#1d1712", surface_alt="#282017",
        hairline="#3a2f22", text="#14100c", text_dim="#a89880",
        accent="#f0a437", accent_soft="#f6c97e", danger="#e2694f",
        success="#8fbf6f", selection="#4a3517", scroll="#3a2f22",
    )
    assert any("bg and text" in p for p in validate_palette(bad))


# --- the wave-3 palettes: Ember Dusk + Lantern ---

def test_ember_dusk_exists_and_is_valid():
    p = PALETTES["emberdusk"]
    assert p.label == "Ember Dusk"
    assert validate_palette(p) == []


def test_lantern_exists_and_is_valid():
    p = PALETTES["lantern"]
    assert p.label == "Lantern"
    assert validate_palette(p) == []


def test_lantern_is_genuinely_high_contrast():
    p = PALETTES["lantern"]
    # white on true black: max luminance distance, for tired eyes
    assert p.text == "#ffffff"
    assert p.bg == "#000000"
    # and the accent never drifts near the text's brightness band
    assert p.accent != p.text and p.accent_soft != p.text


def test_new_palettes_lookup_and_fall_back():
    assert get_palette("emberdusk") is PALETTES["emberdusk"]
    assert get_palette("lantern") is PALETTES["lantern"]
    assert get_palette("nope") is PALETTES[DEFAULT_PALETTE]


def test_new_palettes_ship_as_builtin_keys():
    from hearth.config import BUILTIN_PALETTE_KEYS
    assert {"emberdusk", "lantern"} <= set(BUILTIN_PALETTE_KEYS)
