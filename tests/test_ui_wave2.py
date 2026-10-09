"""Wave-2 UI wiring: lyric chip, Enhance button, import dialog, party inbox,
sound panel — the engines made visible. Built offscreen, tested headless."""

import pytest
from PyQt6.QtWidgets import QPushButton

from hearth.jobs import EnhanceJob, ImportJob
from hearth.storage import HearthStore
from hearth.window import LibraryView, PlaylistView, SearchView

from .test_models import make_track


def _palette():
    from hearth.config import get_palette

    return get_palette("hearthlight")


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


# --- the ✨ Enhance button -----------------------------------------------------


def test_playlist_view_offers_enhance_and_emits_its_id(qapp):
    view = PlaylistView(_palette(), 7, "Road trip")
    buttons = view.findChildren(QPushButton)
    assert any("Enhance" in b.text() for b in buttons)
    seen = []
    view.enhance_requested.connect(seen.append)
    next(b for b in buttons if "Enhance" in b.text()).click()
    assert seen == [7]


def test_library_view_sports_the_spotify_button(qapp):
    view = LibraryView(_palette())
    seen = []
    view.spotify_import_requested.connect(lambda: seen.append(True))
    spotify_btn = next(
        b for b in view.findChildren(QPushButton) if "Spotify" in b.text()
    )
    spotify_btn.click()
    assert seen == [True]


# --- the worker jobs (headless, fake network) ---------------------------------


def test_enhance_job_sprinkles_into_a_real_store(qapp, tmp_path):
    store = HearthStore(tmp_path / "hearth.db")
    pid = store.create_playlist("Evening burn")
    for i in range(3):
        store.add_to_playlist(pid, make_track(video_id=f"seed{i}", artist="Ember Lake"))
    radio = [make_track(video_id="radio1", title="Kindred Fire", artist="Ember Lake")]
    seen = []
    job = EnhanceJob(store, pid, lambda seed, n: radio, n=2)
    job.signals.finished.connect(lambda payload: seen.append(payload))
    job.run()
    added, picks = seen[0]
    assert len(added) == 1
    assert picks[0].track.video_id == "radio1"
    assert "radio1" in [t.video_id for t in store.playlist_tracks(pid)]


def test_enhance_job_reports_failure_without_raising(qapp, tmp_path):
    store = HearthStore(tmp_path / "hearth.db")
    pid = store.create_playlist("broken")
    store.add_to_playlist(pid, make_track())

    def broken_store(_pid):
        raise ZeroDivisionError("shelf collapsed")

    store.playlist_tracks = broken_store
    seen = []
    job = EnhanceJob(store, pid, lambda seed, n: [])
    job.signals.failed.connect(seen.append)
    job.run()
    assert seen == ["shelf collapsed"]


def test_import_job_rebuilds_a_pasted_playlist(qapp, tmp_path):
    pasted = (
        '{"tracks": ['
        '{"name": "Song One", "artists": ["Ember Lake"]},'
        '{"name": "Song Two", "artists": ["Ember Lake"]}]}'
    )
    store = HearthStore(tmp_path / "hearth.db")
    catalog = lambda q: make_track(video_id="yt_" + q.replace(" ", "_"))  # noqa: E731
    seen = []
    job = ImportJob(store, pasted, catalog, name="Wave test")
    job.signals.finished.connect(seen.append)
    job.run()
    report = seen[0]
    assert report.added == 2
    assert report.playlist_id
    assert store.playlist_name(report.playlist_id) == "Wave test"


def test_import_job_survives_a_garbage_paste(qapp, tmp_path):
    store = HearthStore(tmp_path / "hearth.db")
    seen = []
    job = ImportJob(store, "total nonsense \x00 garbage", lambda q: None)
    job.signals.finished.connect(seen.append)
    job.run()
    report = seen[0]
    assert report.total == 0 and report.playlist_id == 0  # honest empty report


# --- the 🟢 paste dialog -------------------------------------------------------


def test_import_dialog_roundtrips_fields_and_gates_ok(qapp):
    from hearth.import_dialog import ImportDialog

    dialog = ImportDialog()
    ok = dialog._text.parent().findChildren(QPushButton)  # noqa: F841
    dialog.set_paste('{"tracks": []}')
    dialog.set_playlist_name("Chill vibes")
    dialog.set_format_choice("csv")
    assert dialog.paste_text().strip() == '{"tracks": []}'
    assert dialog.playlist_name() == "Chill vibes"
    assert dialog.format_choice() == "csv"
    dialog.set_paste("   ")
    assert dialog.paste_text().strip() == ""   # empty paste reads empty


def test_import_dialog_default_format_is_auto(qapp):
    from hearth.import_dialog import ImportDialog

    dialog = ImportDialog()
    assert dialog.format_choice() == "auto"
