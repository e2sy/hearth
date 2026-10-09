"""Wave-2 UI wiring: lyric chip, Enhance button, import dialog, party inbox,
sound panel — the engines made visible. Built offscreen, tested headless."""

import pytest

from hearth.window import SearchView


# --- the 📝 Lyrics chip ------------------------------------------------------


def test_search_view_offers_the_lyrics_scope(qapp):
    view = SearchView(_palette())
    for scope, _label in view.SCOPES:
        assert scope in ("songs", "videos", "albums", "lyrics")
    assert "lyrics" in view._chips


def test_clicking_the_lyrics_chip_switches_scope(qapp):
    view = SearchView(_palette())
    view._chips["lyrics"].click()
    assert view.scope() == "lyrics"


def test_lyrics_scope_emits_search_scoped(qapp):
    view = SearchView(_palette())
    seen = []
    view.search_scoped.connect(lambda q, s: seen.append((q, s)))
    view.set_query("I was listening to the ocean")
    view._chips["lyrics"].click()           # a query is set → emits immediately
    view._emit_search()
    assert ("I was listening to the ocean", "lyrics") in seen


# --- helpers -----------------------------------------------------------------


def _palette():
    from hearth.config import get_palette

    return get_palette("hearthlight")
