"""v0.7.0 plugins + local library: versioned plugin hooks (palette packs,
shelf sources) and the scan-your-folder local library — headless, offscreen,
no network, tmp_path everywhere, no real timers."""

import json
import logging
import sys
import time
import uuid

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QFileDialog

from hearth import config
from hearth.app import _PluginShelfJob, _coerce_track
from hearth.config import get_palette
from hearth.local_scan import LocalScanJob, collect_local_tracks, parse_track_name
from hearth.plugins import discover_plugins, load_all, load_plugin
from hearth.storage import HearthStore
from hearth.theme import palette_to_dict
from hearth.window import LocalView, MainWindow

from .test_app_smoke import make_hearth
from .test_models import make_track


@pytest.fixture(autouse=True)
def _restore_palettes():
    """Plugin palette packs mutate config.PALETTES — restore after each."""
    saved = dict(config.PALETTES)
    yield
    config.PALETTES.clear()
    config.PALETTES.update(saved)


# ------------------------------------------------------------- helpers

def valid_manifest(name: str, entry: str) -> dict:
    return {"hearth-plugin": 1, "name": name, "entry": entry,
            "provides": ["shelf"]}


def make_plugin(root, dir_name: str, manifest: dict | None,
                module_name: str | None = None, module_body: str = ""):
    """A plugin directory on disk: manifest.json (+ an optional module)."""
    plug = root / dir_name
    plug.mkdir(parents=True, exist_ok=True)
    if manifest is not None:
        (plug / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    if module_name is not None:
        (plug / f"{module_name}.py").write_text(module_body, encoding="utf-8")
    return plug


def unique_mod(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


def boot_plugin_body(palette_key: str) -> str:
    return f'''
SEEN = {{}}

def register(services):
    SEEN["services"] = sorted(services)
    SEEN["palette_key"] = services["register_palette"]({{
        "key": "{palette_key}", "label": "Plugpack",
        "bg": "#101010", "surface": "#181818", "surface_alt": "#202020",
        "hairline": "#2a2a2a", "text": "#eeeeee", "text_dim": "#999999",
        "accent": "#ff8800", "accent_soft": "#ffbb66", "danger": "#cc3333",
        "success": "#66cc66", "selection": "#332211", "scroll": "#2a2a2a",
    }})
    SEEN["shelf"] = services["register_shelf_source"](
        "Fire picks",
        lambda: [{{"video_id": "plg1", "title": "Plugin Song",
                   "artist": "Plug"}}],
    )
    return "booted"
'''


# =================================================================
# plugins — discovery
# =================================================================

def test_discover_parses_sorted_and_ignores_clutter(tmp_path):
    root = tmp_path / "plugins"
    make_plugin(root, "zeta", valid_manifest("Zeta", "z_mod:reg"))
    make_plugin(root, "alpha", {"hearth-plugin": 1, "name": "Alpha",
                                "entry": "a_mod:reg"})
    (root / "stray.txt").write_text("not a directory")
    make_plugin(root, ".ghost", valid_manifest("Ghost", "g:r"))
    (root / "nomani").mkdir()
    (root / "nomani" / "readme.txt").write_text("no manifest, not a plugin")

    warnings: list[str] = []
    found = discover_plugins(root, warnings)
    assert [info.name for info in found] == ["Alpha", "Zeta"]   # sorted, stable
    assert found[0].provides == ()                              # optional field
    assert found[1].provides == ("shelf",)
    assert found[1].directory.name == "zeta"
    assert found[1].entry == "z_mod:reg"
    assert warnings == []


def test_discover_skips_invalid_manifests_with_warnings(tmp_path):
    root = tmp_path / "plugins"
    root.mkdir()
    broken = root / "nojson"
    broken.mkdir()
    (broken / "manifest.json").write_text("{oops", encoding="utf-8")
    make_plugin(root, "notdict", None)
    (root / "notdict" / "manifest.json").write_text("[]", encoding="utf-8")
    make_plugin(root, "noname", {"hearth-plugin": 1, "entry": "m:r"})
    make_plugin(root, "noentry", {"hearth-plugin": 1, "name": "N"})
    make_plugin(root, "oldver", {"hearth-plugin": 2, "name": "O", "entry": "m:r"})
    make_plugin(root, "strver", {"hearth-plugin": "1", "name": "S", "entry": "m:r"})
    make_plugin(root, "boolver", {"hearth-plugin": True, "name": "B", "entry": "m:r"})
    make_plugin(root, "badentry", {"hearth-plugin": 1, "name": "E",
                                   "entry": "justmodule"})

    warnings: list[str] = []
    assert discover_plugins(root, warnings) == []
    assert len(warnings) == 8
    assert any("unreadable manifest" in w for w in warnings)
    assert any("not a JSON object" in w for w in warnings)
    assert any("refused" in w for w in warnings)        # the version gate
    assert any("missing 'name'" in w for w in warnings)
    assert any("'entry' must be" in w for w in warnings)
    # a missing root is an empty list and, being normal, no warning
    missing: list[str] = ["sentinel"]
    assert discover_plugins(tmp_path / "nope", missing) == []
    assert missing == ["sentinel"]


# =================================================================
# plugins — loading
# =================================================================

def test_load_plugin_runs_entry_with_services(tmp_path):
    root = tmp_path / "plugins"
    mod = unique_mod("plug_ok")
    make_plugin(root, "ok", valid_manifest("OK", f"{mod}:register"), mod,
                "SEEN = {}\n"
                "def register(services):\n"
                "    SEEN['keys'] = sorted(services)\n"
                "    return 'cozy'\n")
    info = discover_plugins(root)[0]
    warnings: list[str] = []
    services = {"register_palette": lambda d: None,
                "register_shelf_source": lambda n, f: None}
    assert load_plugin(info, services, warnings) == "cozy"
    assert warnings == []
    assert sys.modules[mod].SEEN["keys"] == ["register_palette",
                                             "register_shelf_source"]


def test_load_plugin_failures_return_none_with_warning(tmp_path, caplog):
    root = tmp_path / "plugins"
    raise_mod = unique_mod("plug_raise")
    nc_mod = unique_mod("plug_nc")
    make_plugin(root, "raise", valid_manifest("Raise", f"{raise_mod}:register"),
                raise_mod, "def register(s):\n    raise RuntimeError('boom')\n")
    make_plugin(root, "noattr", valid_manifest("NoAttr", "nope_not_here:r"))
    make_plugin(root, "notcall",
                valid_manifest("NotCall", f"{nc_mod}:NOT_CALLABLE"), nc_mod,
                "NOT_CALLABLE = 42\n")
    with caplog.at_level(logging.WARNING, logger="hearth.plugins"):
        for info in discover_plugins(root):
            warnings: list[str] = []
            assert load_plugin(info, {}, warnings) is None
            assert warnings, f"expected a warning for {info.name}"
    assert any("boom" in r.getMessage() for r in caplog.records)


def test_load_all_collects_results_and_errors(tmp_path):
    root = tmp_path / "plugins"
    good = unique_mod("plug_good")
    bad = unique_mod("plug_bad")
    make_plugin(root, "bad", valid_manifest("Bad", f"{bad}:register"), bad,
                "def register(s):\n    raise ValueError('cold')\n")
    make_plugin(root, "good", valid_manifest("Good", f"{good}:register"), good,
                "def register(s):\n    return 'fine'\n")
    results = load_all(root, {})
    assert [info.name for info, _res in results] == ["Bad", "Good"]  # sorted
    assert isinstance(results[0][1], Exception)
    assert results[1][1] == "fine"          # load_all itself never raises


def test_load_all_deadline_skips_remaining(tmp_path):
    root = tmp_path / "plugins"
    make_plugin(root, "late", valid_manifest("Late", "late_mod:register"))
    warnings: list[str] = []
    results = load_all(root, {}, deadline=time.monotonic() - 1,
                       warnings=warnings)
    assert results == []
    assert any("window closed" in w for w in warnings)


# =================================================================
# plugins — the app services + boot wiring
# =================================================================

def test_register_palette_service_accepts_and_suffixes(tmp_path, qapp):
    hearth = make_hearth(tmp_path)
    services = hearth._plugin_services()
    pack = palette_to_dict(config.PALETTES["moss"])
    pack["key"], pack["label"] = "plug-moss", "Plug Moss"
    assert services["register_palette"](pack) == "plug-moss"
    assert config.PALETTES["plug-moss"].label == "Plug Moss"
    # a built-in key is sacred: the import gets a suffix instead
    clash = dict(pack, key="grove")
    assert services["register_palette"](clash) == "grove-2"
    assert config.PALETTES["grove"].label == "Grove"    # untouched
    hearth.shutdown()


def test_register_palette_service_rejects_invalid(tmp_path, qapp):
    hearth = make_hearth(tmp_path)
    services = hearth._plugin_services()
    before = dict(config.PALETTES)
    assert services["register_palette"]({"key": "half"}) is None      # incomplete
    pack = palette_to_dict(config.PALETTES["moss"])
    assert services["register_palette"](dict(pack, accent="nope")) is None
    assert services["register_palette"](None) is None
    assert services["register_palette"]("garbage") is None
    assert config.PALETTES == before
    hearth.shutdown()


def test_register_shelf_source_service_validates(tmp_path, qapp):
    hearth = make_hearth(tmp_path)
    register = hearth._plugin_services()["register_shelf_source"]
    assert register("Fire picks", lambda: []) is True
    assert "Fire picks" in hearth._plugin_shelves
    assert register("", lambda: []) is False           # empty name
    assert register("   ", lambda: []) is False        # whitespace name
    assert register("NoFn", "not callable") is False   # not callable
    assert list(hearth._plugin_shelves) == ["Fire picks"]
    hearth.shutdown()


def test_boot_seeded_plugin_registers_palette_and_shelf(tmp_path, qapp):
    mod = unique_mod("plug_boot")
    root = tmp_path / "data" / "plugins"       # make_hearth's data directory
    make_plugin(root, "cozy",
                {"hearth-plugin": 1, "name": "Cozy",
                 "entry": f"{mod}:register", "provides": ["palette", "shelf"]},
                mod, boot_plugin_body("plugpack"))
    hearth = make_hearth(tmp_path)

    seen = sys.modules[mod].SEEN
    assert seen["palette_key"] == "plugpack"       # register_palette worked
    assert seen["shelf"] is True                   # register_shelf_source worked
    assert seen["services"] == ["register_palette", "register_shelf_source"]
    assert "plugpack" in config.PALETTES
    assert callable(hearth._plugin_shelves["Fire picks"])

    # the shelf resolves on a job and renders through the normal path
    capture: list = []
    job = _PluginShelfJob(hearth._plugin_shelves)
    job.signals.finished.connect(capture.append)
    job.run()
    hearth._on_plugin_shelf(capture[0])
    shelf = hearth.window.home_view.shelf("🔌 Plugins")
    assert [t.title for t in shelf._tracks] == ["Plugin Song"]
    assert shelf.isVisibleTo(hearth.window.home_view)
    hearth.shutdown()


def test_boot_plugin_load_never_raises_on_garbage(tmp_path, qapp):
    root = tmp_path / "data" / "plugins"
    root.mkdir(parents=True)
    (root / "just_a_file.txt").write_text("hello")
    make_plugin(root, "broken", None)
    (root / "broken" / "manifest.json").write_text("{not json", encoding="utf-8")
    mod = unique_mod("plug_crash")
    make_plugin(root, "crashy", valid_manifest("Crashy", f"{mod}:register"),
                mod, "def register(s):\n    raise ValueError('cold')\n")
    hearth = make_hearth(tmp_path)                 # boot must simply survive
    assert hearth._plugin_shelves == {}
    hearth.shutdown()


def test_plugin_shelf_job_merges_tracks_and_reports_failures(tmp_path, qapp):
    hearth = make_hearth(tmp_path)
    sources = {
        "good": lambda: [{"video_id": "p1", "title": "P1", "artist": "A"}],
        "real": lambda: [make_track(video_id="p2")],
        "junk": lambda: ["garbage", {"title": "no id"}, None, 3],
        "bad": lambda: 1 / 0,
    }
    capture: list = []
    job = _PluginShelfJob(sources)
    job.signals.finished.connect(capture.append)
    job.run()
    results, failures = capture[0]

    notes: list[str] = []
    hearth.window.set_status = notes.append
    hearth._on_plugin_shelf((results, failures))
    shelf = hearth.window.home_view.shelf("🔌 Plugins")
    titles = [t.title for t in shelf._tracks]
    assert "P1" in titles                              # dict coerced
    assert "Never Gonna Give You Up" in titles         # Track passed through
    assert shelf.isVisibleTo(hearth.window.home_view)
    assert [name for name, _err in failures] == ["bad"]
    assert any("bad" in note for note in notes)        # failure speaks up

    hearth._on_plugin_shelf(([], []))                  # nothing → shelf hides
    assert not shelf.isVisibleTo(hearth.window.home_view)
    hearth.shutdown()


def test_coerce_track_drops_garbage_and_keeps_tracks():
    track = make_track()
    assert _coerce_track(track) is track
    assert _coerce_track(track.to_dict()) == track
    assert _coerce_track({"title": "no video id"}) is None
    assert _coerce_track("junk") is None
    assert _coerce_track(None) is None


# =================================================================
# local library — storage
# =================================================================

def test_upsert_local_track_roundtrip_and_stable_id(tmp_path):
    store = HearthStore(tmp_path / "hearth.db")
    one = store.upsert_local_track(tmp_path / "a.mp3", "A", "Art", "Alb", 213)
    two = store.upsert_local_track(str(tmp_path / "a.mp3"), "A", "Art")
    assert one.video_id == two.video_id                # stable per path
    assert one.video_id.startswith("local-")
    other = store.upsert_local_track(tmp_path / "b.mp3", "B")
    assert other.video_id != one.video_id
    assert one.duration == "3:33" and one.duration_sec == 213
    assert other.duration == "—"                       # honest unknown length
    assert other.duration_sec == 0
    rows = store.local_tracks()
    assert {t.video_id for t in rows} == {one.video_id, other.video_id}
    assert store.local_track_count() == 2
    store.close()


def test_upsert_same_path_updates_not_duplicates(tmp_path):
    store = HearthStore(tmp_path / "hearth.db")
    first = store.upsert_local_track("x/y.mp3", "Old", "OldArtist")
    again = store.upsert_local_track("x/y.mp3", "New", "NewArtist", "Al", 42)
    assert again.video_id == first.video_id
    assert store.local_track_count() == 1
    (track,) = store.local_tracks()
    assert (track.title, track.artist) == ("New", "NewArtist")
    assert track.duration_sec == 42
    store.close()


def test_remove_local_track_and_path_lookup(tmp_path):
    store = HearthStore(tmp_path / "hearth.db")
    track = store.upsert_local_track("gone/song.mp3", "Song")
    assert store.local_track_path(track.video_id) == "gone/song.mp3"
    assert store.remove_local_track("gone/song.mp3") is True
    assert store.remove_local_track("gone/song.mp3") is False
    assert store.local_track_path(track.video_id) is None
    assert store.local_track_count() == 0
    store.close()


def test_local_tracks_table_migrates_old_db(tmp_path):
    db = tmp_path / "hearth.db"
    store = HearthStore(db)
    store.upsert_local_track("a.mp3", "A")
    store._db.execute("DROP TABLE local_tracks")
    store._db.commit()
    store.close()
    reopened = HearthStore(db)                         # old DB upgrades on open
    assert reopened.local_track_count() == 0
    assert reopened.upsert_local_track("a.mp3", "A").title == "A"
    reopened.close()


def test_batch_upsert_counts_and_skips(tmp_path):
    store = HearthStore(tmp_path / "hearth.db")
    batch = [
        {"path": "a.mp3", "title": "A"},
        {"path": "b.mp3", "title": "B", "artist": "Art"},
        {"path": "a.mp3", "title": "A again"},            # within-batch dupe
        {"title": "no path"},                              # malformed
        {"path": "", "title": "empty"},                    # malformed
        "junk",                                            # malformed
    ]
    assert store.upsert_local_tracks(batch) == (2, 0)
    assert store.upsert_local_tracks(batch) == (0, 2)     # now updates
    assert store.upsert_local_tracks([]) == (0, 0)
    titles = sorted(t.title for t in store.local_tracks())
    assert titles == ["A", "B"]
    store.close()


# =================================================================
# local library — scanner
# =================================================================

@pytest.mark.parametrize("filename,expected", [
    ("Artist - Title.mp3", ("Artist", "Title")),
    ("07. X - Y.flac", ("X", "Y")),
    ("12_my_song.mp3", ("", "my song")),          # track number + underscores
    ("random.mp3", ("", "random")),
    ("09 Alone.ogg", ("", "Alone")),
    ("1979 - Smashing.m4a", ("1979", "Smashing")),  # 4 digits stay an artist
    ("Bonobo - Black Sands (Remix).mp3", ("Bonobo", "Black Sands (Remix)")),
    ("ARTIST - TiTLe.mp3", ("ARTIST", "TiTLe")),    # case preserved
    ("just_a_file.wav", ("", "just a file")),
])
def test_parse_track_name_patterns(filename, expected):
    assert parse_track_name(filename) == expected


def test_scanner_walks_tree_and_counts_skips(tmp_path):
    root = tmp_path / "music"
    (root / "Bonobo").mkdir(parents=True)
    (root / "Bonobo" / "Bonobo - Black Sands.mp3").write_bytes(b"x")
    (root / "07. X - Y.flac").write_bytes(b"x")
    (root / "random.mp3").write_bytes(b"x")
    (root / "my_song.ogg").write_bytes(b"x")
    (root / "art.m4a").write_bytes(b"x")
    (root / "deep").mkdir()
    (root / "deep" / "Wave.wav").write_bytes(b"x")
    (root / "cover.txt").write_text("not audio")

    entries, stats = collect_local_tracks([str(root)])
    assert stats == {"scanned": 6, "skipped": 1, "truncated": False}
    assert len(entries) == 6
    by_title = {e["title"]: e for e in entries}
    assert by_title["Y"]["artist"] == "X"
    assert by_title["my song"]["path"].endswith("my_song.ogg")
    assert by_title["Black Sands"]["artist"] == "Bonobo"
    assert all(e["duration_s"] == 0.0 for e in entries)   # honest: no probing
    # a vanished root is simply skipped
    entries2, stats2 = collect_local_tracks([str(root / "nope")])
    assert entries2 == [] and stats2["scanned"] == 0


def test_scanner_cap_truncates(tmp_path):
    root = tmp_path / "music"
    root.mkdir()
    for n in range(5):
        (root / f"song {n}.mp3").write_bytes(b"x")
    entries, stats = collect_local_tracks([str(root)], cap=2)
    assert len(entries) == 2
    assert stats["truncated"] is True


def test_rescan_updates_not_duplicates(tmp_path):
    root = tmp_path / "music"
    root.mkdir()
    (root / "A - B.mp3").write_bytes(b"x")
    (root / "C.mp3").write_bytes(b"x")
    store = HearthStore(tmp_path / "hearth.db")
    entries, _stats = collect_local_tracks([str(root)])
    assert store.upsert_local_tracks(entries) == (2, 0)
    assert store.upsert_local_tracks(entries) == (0, 2)   # rescan = update
    assert store.local_track_count() == 2
    assert all(t.duration == "—" for t in store.local_tracks())  # duration 0 ok
    store.close()


def test_scan_job_emits_entries_and_stats(tmp_path, qapp):
    root = tmp_path / "m"
    root.mkdir()
    (root / "A - B.mp3").write_bytes(b"x")
    got: list = []
    failed: list = []
    job = LocalScanJob([str(root)])
    job.signals.finished.connect(got.append)
    job.signals.failed.connect(failed.append)
    job.run()
    entries, stats = got[0]
    assert [e["title"] for e in entries] == ["B"]
    assert stats["scanned"] == 1
    assert failed == []


def test_scan_job_failure_emits_failed(tmp_path, qapp, monkeypatch):
    def boom(*_a, **_k):
        raise RuntimeError("walk exploded")

    monkeypatch.setattr("hearth.local_scan.collect_local_tracks", boom)
    got: list = []
    job = LocalScanJob([str(tmp_path)])
    job.signals.failed.connect(got.append)
    job.run()
    assert got == ["walk exploded"]


# =================================================================
# local library — view + app wiring
# =================================================================

def test_local_view_empty_state_and_count(qapp):
    view = LocalView(get_palette("grove"))
    assert view._head.text() == "📁 Local songs"
    view.set_tracks([])
    assert not view._empty.isHidden()      # honest empty state
    assert view._empty.text() == "no local songs yet — point hearth at a folder"
    assert view._list.isHidden()
    view.set_tracks([make_track(), make_track(video_id="t2")])
    assert view._empty.isHidden()
    assert not view._list.isHidden()
    assert view._count.text() == "2 tracks"


def test_local_view_double_click_plays_via_core(tmp_path, qapp):
    hearth = make_hearth(tmp_path)
    track = hearth.store.upsert_local_track("music/X - Y.mp3", "Y", "X")
    hearth._refresh_library()
    view = hearth.window.local_view
    assert view._list.count() == 1

    item = view._list.item(0)              # the exact signal path other views use
    assert item.data(Qt.ItemDataRole.UserRole).video_id == track.video_id
    view._list.itemDoubleClicked.emit(item)
    current = hearth.core.engine.current
    assert current is not None and current.video_id == track.video_id
    assert hearth.store.history()[0].video_id == track.video_id
    hearth.shutdown()


def test_local_file_url_resolution_rules(tmp_path, qapp):
    hearth = make_hearth(tmp_path)
    songs = tmp_path / "songs"
    songs.mkdir()
    song = songs / "Neon - Nights.mp3"
    song.write_bytes(b"not really audio")
    track = hearth.store.upsert_local_track(str(song), "Nights", "Neon")

    url = hearth._local_file_url(track)
    assert url is not None and url.startswith("file:///")
    assert url.endswith(".mp3")
    assert hearth._local_file_url(make_track()) is None      # not a local track
    assert hearth._local_file_url(None) is None

    song.unlink()                                            # gone on disk
    notes: list[str] = []
    hearth.window.set_status = notes.append
    assert hearth._local_file_url(track) is None
    assert any("gone" in note for note in notes)
    hearth.shutdown()


def test_track_changed_local_skips_network_resolve(tmp_path, qapp, monkeypatch):
    hearth = make_hearth(tmp_path)
    hearth._enable_streaming = True          # flipped after boot: no pool jobs
    songs = tmp_path / "songs"
    songs.mkdir()
    song = songs / "Neon - Nights.mp3"
    song.write_bytes(b"audio bytes go here")
    track = hearth.store.upsert_local_track(str(song), "Nights", "Neon")

    hearth._fetch_lyrics = lambda _t: None   # keep the pool out of it

    class BoomLoadJob:                       # construction = a network resolve
        def __init__(self, *_a, **_k):
            raise AssertionError("local files must not hit the stream resolver")

    monkeypatch.setattr("hearth.app.LoadJob", BoomLoadJob)

    opened: dict = {}

    def spy_set_stream(t, url, loudness_db=None, resume_ms=0):
        opened["track"], opened["url"] = t, url

    monkeypatch.setattr(hearth.core, "set_stream", spy_set_stream)
    hearth._pick_track(track)
    assert opened["url"].startswith("file://")
    assert opened["track"].video_id == track.video_id
    hearth.shutdown()


def test_add_folder_scans_end_to_end(tmp_path, qapp, monkeypatch):
    hearth = make_hearth(tmp_path)
    folder = tmp_path / "music"
    folder.mkdir()
    (folder / "A - B.mp3").write_bytes(b"x")
    (folder / "notes.txt").write_text("no")
    monkeypatch.setattr(QFileDialog, "getExistingDirectory",
                        staticmethod(lambda *a, **k: str(folder)))
    monkeypatch.setattr(hearth, "_launch", lambda job: job.run())  # synchronous

    hearth._local_add_folder()
    assert hearth._local_roots() == [str(folder)]
    assert hearth.store.local_track_count() == 1
    view = hearth.window.local_view
    assert view._list.count() == 1
    assert view.current_tracks[0].title == "B"

    hearth._local_rescan()                   # the 🔄 button: updates, no dupes
    assert hearth.store.local_track_count() == 1
    assert view._list.count() == 1
    hearth.shutdown()


def test_rescan_without_roots_opens_folder_picker(tmp_path, qapp, monkeypatch):
    hearth = make_hearth(tmp_path)
    asked: list = []

    def fake_dialog(*_a, **_k):
        asked.append("asked")
        return ""                            # user cancels

    monkeypatch.setattr(QFileDialog, "getExistingDirectory",
                        staticmethod(fake_dialog))
    hearth._local_rescan()
    assert asked == ["asked"]
    assert hearth._local_roots() == []
    hearth.shutdown()


def test_local_view_registered_in_navigation(qapp):
    window = MainWindow("grove")
    assert "local" in MainWindow.VIEWS
    assert window.VIEWS.index("local") == 5
    window.show_view("local")
    assert window.stack.currentIndex() == MainWindow.VIEWS.index("local")
    assert window._nav["local"].isChecked()
    assert window._nav["local"].text().startswith("📁")
