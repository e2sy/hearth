"""Wave-2 UI wiring: lyric chip, Enhance button, import dialog, party inbox,
sound panel — the engines made visible. Built offscreen, tested headless."""

import pytest
from PyQt6.QtWidgets import QLabel, QPushButton

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


# --- the 🎉 party inbox dialog --------------------------------------------------


def _inbox_with_two():
    from hearth.remote import SuggestionInbox

    box = SuggestionInbox()
    box.push({"video_id": "aaaaaaaaaaa", "title": "Guest song", "artist": "DJ Ember"})
    box.push({"video_id": "bbbbbbbbbbb", "title": "Second pick"})
    return box


def test_party_dialog_lists_pending_guests(qapp):
    from hearth.party_dialog import PartyInboxDialog

    dialog = PartyInboxDialog(_inbox_with_two())
    assert "2 guest suggestion(s)" in dialog._head.text()
    labels = [w.text() for w in dialog.findChildren(QLabel)
              if w.text()]
    assert any("Guest song" in t for t in labels)
    assert any("DJ Ember" in t for t in labels)


def test_party_dialog_accept_emits_and_empties(qapp):
    from hearth.party_dialog import PartyInboxDialog

    box = _inbox_with_two()
    dialog = PartyInboxDialog(box)
    accepted = []
    dialog.accept_requested.connect(accepted.append)
    queue_btns = [b for b in dialog.findChildren(QPushButton) if "Queue" in b.text()]
    assert len(queue_btns) == 2
    queue_btns[0].click()                    # the first guest's pick
    assert len(accepted) == 1
    assert accepted[0]["video_id"] == "aaaaaaaaaaa"
    assert len(box) == 1                     # the pick left the inbox
    queue_btns[1].click()                    # the second guest's pick
    assert len(accepted) == 2
    assert len(box) == 0
    assert "empty" in dialog._head.text().lower()


def test_party_dialog_skip_leaves_nothing_behind(qapp):
    from hearth.party_dialog import PartyInboxDialog

    box = _inbox_with_two()
    dialog = PartyInboxDialog(box)
    skip_btns = [b for b in dialog.findChildren(QPushButton) if b.text() == "Skip"]
    skip_btns[0].click()
    skip_btns[1].click()
    assert len(box) == 0
    assert "empty" in dialog._head.text().lower()


# --- the 🎚️ Sound Forge panel ----------------------------------------------------


def test_sound_forge_roundtrips_a_state_through_the_knobs(qapp):
    from hearth.sound_panel import SoundForgeDialog
    from hearth.sound_shape import SoundState

    state = SoundState(gains=(6, 4, 2, 0, 0, 0, 0, 0, -2, -4),
                       preamp_db=-3, karaoke=True, karaoke_strength=0.7)
    dialog = SoundForgeDialog(state=state)
    loaded = dialog.current_state()
    assert loaded.gains == state.gains
    assert loaded.preamp_db == -3
    assert loaded.karaoke is True
    assert loaded.karaoke_strength == pytest.approx(0.7)


def test_sound_forge_slider_move_emits_state(qapp):
    from hearth.sound_panel import SoundForgeDialog
    from hearth.sound_shape import SoundState

    dialog = SoundForgeDialog(state=SoundState())
    seen = []
    dialog.state_changed.connect(seen.append)
    dialog._band_sliders[0].setValue(6)          # drag the 31 Hz band up
    assert len(seen) == 1
    assert seen[0].gains[0] == 6.0
    dialog._preamp.setValue(-4)
    assert seen[-1].preamp_db == -4


def test_sound_forge_preset_loads_curve_and_names_itself(qapp):
    from hearth.sound_panel import SoundForgeDialog
    from hearth.sound_shape import SoundState

    dialog = SoundForgeDialog(state=SoundState())
    seen = []
    dialog.state_changed.connect(seen.append)
    index = dialog._preset.findData("Bass Boost")
    dialog._preset.setCurrentIndex(index)
    loaded = dialog.current_state()
    assert loaded.gains[0] > 0                    # the low end lifts
    assert dialog._preset.currentData() == "Bass Boost"   # box stays honest


def test_sound_forge_programmatic_set_stays_quiet(qapp):
    from hearth.sound_panel import SoundForgeDialog
    from hearth.sound_shape import SoundState

    dialog = SoundForgeDialog(state=SoundState())
    seen = []
    dialog.state_changed.connect(seen.append)
    dialog.set_state(SoundState(gains=(3, 0, 0, 0, 0, 0, 0, 0, 0, 0)))
    assert seen == []                             # loading must not echo


def test_playback_core_preamp_shapes_volume(tmp_path):
    from PyQt6.QtCore import QCoreApplication

    app = QCoreApplication.instance() or QCoreApplication([])
    from hearth.player import PlaybackCore
    from hearth.sound_shape import db_to_linear

    core = PlaybackCore()
    core.set_volume(0.8)
    core.set_preamp(-6.0)
    assert core.preamp_db == -6.0
    assert core.effective_volume() == pytest.approx(0.8 * db_to_linear(-6.0))
    core.set_preamp(99)                           # clamps, never raises
    assert core.preamp_db == 6.0
    core.set_volume(0.5)                          # volume changes keep the preamp
    assert core.effective_volume() == pytest.approx(0.5 * db_to_linear(6.0))
    core.set_preamp(0.0)
    assert core.effective_volume() == pytest.approx(0.5)
