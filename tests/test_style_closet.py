"""v0.8.0 style closet: glass style packs, the live style picker, and the
custom wallpaper engine — headless and offscreen, no network, no sleeps."""

import re
from pathlib import Path

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QImage
from PyQt6.QtWidgets import QFileDialog

from hearth import config, theme
from hearth.config import get_palette
from hearth.window import MainWindow, StylePickerDialog

from .test_app_smoke import make_hearth

GROVE = get_palette("grove")   # surface #131917, bg #0e1210, accent #1db954


@pytest.fixture(autouse=True)
def _reset_style_policy():
    """Style tests flip theme module state — always hand it back intact."""
    saved_style = theme.active_style()
    saved_alpha = theme.active_wallpaper_alpha()
    yield
    theme.set_style(saved_style)
    theme.set_wallpaper_alpha(saved_alpha)


def _radii(css: str) -> set[int]:
    return {int(r) for r in re.findall(r"border-radius: (\d+)px", css)}


def _png(tmp_path, name="src.png", w=32, h=24,
         color=Qt.GlobalColor.darkCyan) -> str:
    img = QImage(w, h, QImage.Format.Format_RGB32)
    img.fill(QColor(color))
    path = tmp_path / name
    assert img.save(str(path))
    return str(path)


# ----------------------------------------------------------------- style packs

def test_style_registry_shape():
    assert list(theme.STYLES)[0] == "hearth"          # default wears first
    assert len(theme.STYLES) >= 4                     # a closet, not a hallway
    labels = [pack.label for pack in theme.STYLES.values()]
    assert len(set(labels)) == len(labels)
    assert all(pack.blurb for pack in theme.STYLES.values())
    assert theme.get_style("no-such-style").key == "hearth"


def test_unknown_style_falls_back_to_default():
    theme.set_style("bogus")
    assert theme.active_style() == "hearth"
    theme.set_style("glass")
    assert theme.active_style() == "glass"
    theme.set_style(None)
    assert theme.active_style() == "hearth"


def test_classic_style_stays_backward_compatible():
    css = theme.build_stylesheet(GROVE)
    assert f"stop:1 {GROVE.bg}" in css                # opaque canvas gradient
    assert f"background: {GROVE.surface_alt};" in css  # opaque surfaces
    assert "1px solid rgba(29, 185, 84" not in css    # no neon rims
    assert theme.STYLES["hearth"].radius_delta == 0


def test_glass_style_translates_panes():
    theme.set_style("glass")
    css = theme.build_stylesheet(GROVE)
    # surfaces become frosted panes at the pack's alpha
    assert "rgba(19, 25, 23, 72%)" in css             # grove surface @ 72%
    assert f"color: {GROVE.bg};" in css               # accent text stays opaque
    assert f"color: {GROVE.text};" in css             # readable text untouched
    # every radius softens by exactly the pack's delta
    classic = theme.build_stylesheet(GROVE, "hearth")
    assert _radii(css) == {r + 4 for r in _radii(classic)}


def test_glass_canvas_stays_solid_without_wallpaper():
    theme.set_style("glass")
    css = theme.build_stylesheet(GROVE)
    assert "rgba(14, 18, 16, 100%)" in css            # bg opaque until wallpaper


def test_veil_style_lifts_surfaces_toward_light():
    veil = theme.STYLES["veil"]
    theme.set_style("veil")
    css = theme.build_stylesheet(GROVE)
    lifted = theme._mix(GROVE.surface, GROVE.text, veil.lift)
    r, g, b = (int(lifted[i:i + 2], 16) for i in (1, 3, 5))
    assert f"rgba({r}, {g}, {b}, {veil.panel_alpha}%)" in css


def test_neon_style_adds_accent_rims():
    neon = theme.build_stylesheet(GROVE, "neon")
    classic = theme.build_stylesheet(GROVE, "hearth")
    assert "border: 1px solid rgba(29, 185, 84, 42%)" in neon
    assert "rgba(29, 185, 84, 42%)" not in classic


def test_wallpaper_alpha_glow_and_clamp():
    wp60 = theme.build_stylesheet(GROVE, "hearth", 60)
    assert "rgba(14, 18, 16, 60%)" in wp60            # canvas glows at 60%
    assert theme.build_stylesheet(p=GROVE, style_key="hearth",
                                  wallpaper_alpha=5) \
        == theme.build_stylesheet(p=GROVE, style_key="hearth",
                                  wallpaper_alpha=config.WALLPAPER_ALPHA_MIN)
    assert theme.build_stylesheet(p=GROVE, style_key="hearth",
                                  wallpaper_alpha=500) \
        == theme.build_stylesheet(p=GROVE, style_key="hearth",
                                  wallpaper_alpha=config.WALLPAPER_ALPHA_MAX)


def test_wallpaper_policy_uses_module_state():
    theme.set_wallpaper_alpha(70)
    assert "rgba(14, 18, 16, 70%)" in theme.build_stylesheet(GROVE)
    theme.set_wallpaper_alpha(None)
    assert f"stop:1 {GROVE.bg}" in theme.build_stylesheet(GROVE)


def test_explicit_style_arg_overrides_module_state():
    theme.set_style("glass")
    assert theme.build_stylesheet(GROVE, "hearth") \
        == theme.build_stylesheet(GROVE, "hearth", wallpaper_alpha=None)
    assert f"stop:1 {GROVE.bg}" in theme.build_stylesheet(GROVE, "hearth")


# ----------------------------------------------------------------- wallpapers

def test_import_wallpaper_copies_and_dedupes(tmp_path):
    src = _png(tmp_path)
    dest_dir = tmp_path / "store"
    stored = theme.import_wallpaper(src, dest_dir)
    assert stored is not None
    assert Path(stored).parent == dest_dir
    assert Path(stored).is_file()
    again = theme.import_wallpaper(src, dest_dir)
    assert again == stored                            # content-hash dedupe
    assert len(list(dest_dir.iterdir())) == 1


def test_import_wallpaper_rejects_garbage(tmp_path):
    assert theme.import_wallpaper(tmp_path / "missing.png", tmp_path) is None
    fake = tmp_path / "text.png"
    fake.write_text("definitely not an image", encoding="utf-8")
    assert theme.import_wallpaper(fake, tmp_path) is None
    txt = tmp_path / "notes.txt"
    txt.write_text("plain text", encoding="utf-8")
    assert theme.import_wallpaper(txt, tmp_path) is None
    empty = tmp_path / "empty.jpg"
    empty.write_bytes(b"")
    assert theme.import_wallpaper(empty, tmp_path) is None


def test_import_wallpaper_normalizes_jpg(tmp_path):
    src = _png(tmp_path, name="photo.jpg")            # png bytes, jpg suffix
    stored = theme.import_wallpaper(src, tmp_path / "store")
    assert stored is not None and not QImage(stored).isNull()


def test_import_wallpaper_downscales_huge_images(tmp_path):
    img = QImage(3000, 2000, QImage.Format.Format_RGB32)
    img.fill(QColor(Qt.GlobalColor.darkMagenta))
    src = tmp_path / "huge.png"
    assert img.save(str(src))
    stored = theme.import_wallpaper(src, tmp_path / "store", max_dim=1000)
    assert stored is not None
    out = QImage(stored)
    assert max(out.width(), out.height()) == 1000
    # default limit comes from config
    stored2 = theme.import_wallpaper(src, tmp_path / "store2")
    out2 = QImage(stored2)
    assert max(out2.width(), out2.height()) == config.WALLPAPER_MAX_DIM


def test_remove_wallpaper_never_raises(tmp_path):
    src = _png(tmp_path)
    stored = theme.import_wallpaper(src, tmp_path / "store")
    theme.remove_wallpaper(stored)
    assert not Path(stored).exists()
    theme.remove_wallpaper(stored)                    # already gone — fine
    theme.remove_wallpaper("/nonexistent/path.png")   # never raises


# ----------------------------------------------------------------- main window

def test_window_background_image_roundtrip(tmp_path, qapp):
    win = MainWindow("grove")
    win.show()
    stored = _png(tmp_path)
    assert win.set_background_image(stored) is True
    assert win.wallpaper_path == stored
    assert win._bg_label.isVisible()
    assert not win._bg_label.pixmap().isNull()
    # resize re-covers the stage
    win.resize(800, 600)
    assert win._bg_label.geometry().size() == win.size()
    win.set_background_image(None)
    assert win.wallpaper_path is None
    assert not win._bg_label.isVisible()
    win.close()


def test_window_background_rejects_bad_images(tmp_path, qapp):
    win = MainWindow("grove")
    good = _png(tmp_path)
    assert win.set_background_image(good) is True
    fake = tmp_path / "fake.png"
    fake.write_text("nope", encoding="utf-8")
    assert win.set_background_image(str(fake)) is False
    assert win.wallpaper_path == good                 # old wallpaper kept
    win.set_background_image(None)
    win.close()


# ----------------------------------------------------------------- the dialog

def test_style_picker_trial_and_commit(qapp):
    dlg = StylePickerDialog("hearth", 80, False)
    trials: list[str] = []
    dlg.style_trial.connect(trials.append)
    dlg._cards["glass"].click()
    assert trials == ["glass"]
    assert dlg._current == "glass"
    assert dlg._cards["glass"].isChecked()
    assert not dlg._cards["hearth"].isChecked()
    chosen: list[str] = []
    dlg.style_chosen.connect(chosen.append)
    dlg._commit()
    assert chosen == ["glass"] and dlg.saved and dlg.result()


def test_style_picker_cancel_commits_nothing(qapp):
    dlg = StylePickerDialog("hearth", 80, False)
    chosen: list[str] = []
    dlg.style_chosen.connect(chosen.append)
    dlg._cards["neon"].click()
    dlg.reject()
    assert chosen == [] and not dlg.saved


def test_style_picker_upload_emits_path(monkeypatch, tmp_path, qapp):
    dlg = StylePickerDialog("hearth", 80, False)
    picked: list[str] = []
    dlg.background_picked.connect(picked.append)
    src = _png(tmp_path)
    monkeypatch.setattr(QFileDialog, "getOpenFileName",
                        staticmethod(lambda *a, **k: (src, "Images")))
    dlg._pick_image()
    assert picked == [src]
    monkeypatch.setattr(QFileDialog, "getOpenFileName",
                        staticmethod(lambda *a, **k: ("", "")))
    dlg._pick_image()
    assert picked == [src]                            # cancel emits nothing


def test_style_picker_alpha_slider_and_remove_gating(qapp):
    alphas: list[int] = []
    dlg = StylePickerDialog("glass", 55, True)
    dlg.wallpaper_alpha_changed.connect(alphas.append)
    dlg._alpha.setValue(90)
    assert alphas[-1] == 90
    assert dlg._alpha.minimum() == config.WALLPAPER_ALPHA_MIN
    assert dlg._alpha.maximum() == config.WALLPAPER_ALPHA_MAX
    bare = StylePickerDialog("hearth", 80, False)
    assert not bare._remove_btn.isEnabled()
    with_bg = StylePickerDialog("hearth", 80, True)
    assert with_bg._remove_btn.isEnabled()


# ----------------------------------------------------------------- app wiring

def test_app_style_commit_and_persist(tmp_path, qapp):
    hearth = make_hearth(tmp_path)
    hearth._commit_style("glass")
    assert theme.active_style() == "glass"
    assert hearth.settings.value("ui/style") == "glass"
    assert "rgba(19, 25, 23, 72%)" in hearth.window.styleSheet()
    hearth.shutdown()

    reopened = make_hearth(tmp_path)
    assert theme.active_style() == "glass"            # the look survives
    assert "rgba(19, 25, 23, 72%)" in reopened.window.styleSheet()
    reopened.shutdown()


def test_app_style_trial_and_restore_policy(tmp_path, qapp):
    hearth = make_hearth(tmp_path)
    hearth._trial_style("veil")
    assert theme.active_style() == "veil"
    hearth._apply_style_policy("hearth", None)        # what cancel does
    assert theme.active_style() == "hearth"
    assert theme.active_wallpaper_alpha() is None
    hearth.shutdown()


def test_app_background_upload_roundtrip(tmp_path, qapp):
    hearth = make_hearth(tmp_path)
    src = _png(tmp_path, w=64, h=48)
    hearth._set_background_from_file(src)
    stored = hearth.window.wallpaper_path
    assert stored is not None
    assert hearth.settings.value("ui/background") == stored
    assert theme.active_wallpaper_alpha() == config.WALLPAPER_ALPHA_DEFAULT
    hearth.window.show()
    assert hearth.window._bg_label.isVisible()
    hearth.shutdown()

    reopened = make_hearth(tmp_path)                  # wallpaper survives too
    assert reopened.window.wallpaper_path == stored
    reopened.shutdown()


def test_app_background_bad_file_is_rejected(tmp_path, qapp):
    hearth = make_hearth(tmp_path)
    fake = tmp_path / "fake.png"
    fake.write_text("not an image", encoding="utf-8")
    hearth._set_background_from_file(str(fake))
    assert hearth.window.wallpaper_path is None
    assert not hearth.settings.contains("ui/background")
    assert theme.active_wallpaper_alpha() is None
    hearth.shutdown()


def test_app_clear_background(tmp_path, qapp):
    hearth = make_hearth(tmp_path)
    hearth._set_background_from_file(_png(tmp_path))
    assert hearth.window.wallpaper_path is not None
    hearth._clear_background()
    assert hearth.window.wallpaper_path is None
    assert not hearth.settings.contains("ui/background")
    assert theme.active_wallpaper_alpha() is None
    assert not hearth.window._bg_label.isVisible()
    hearth.shutdown()


def test_app_wallpaper_alpha_persists(tmp_path, qapp):
    hearth = make_hearth(tmp_path)
    hearth._set_background_from_file(_png(tmp_path))
    hearth._set_wallpaper_alpha(45)
    assert hearth.settings.value("ui/wallpaper_alpha") in (45, "45")
    hearth.shutdown()

    reopened = make_hearth(tmp_path)
    assert reopened._wallpaper_alpha == 45
    assert theme.active_wallpaper_alpha() == 45
    reopened.shutdown()


def test_app_boot_with_bogus_saved_style(tmp_path, qapp):
    # a hand-written ini (persist would normalize it before the next boot)
    (tmp_path / "settings.ini").write_text(
        "[General]\nui/style=does-not-exist\n", encoding="utf-8")
    reopened = make_hearth(tmp_path)
    assert theme.active_style() == "hearth"           # falls back, no crash
    reopened.shutdown()


def test_app_style_closet_signal_wiring(tmp_path, qapp, monkeypatch):
    """The 🪞 sidebar button reaches the app's closet handler.

    Qt connects the bound method at wire-up time, so patching the class's
    exec (not the instance attribute) is what stops a real modal loop.
    """
    hearth = make_hearth(tmp_path)
    opened = []
    monkeypatch.setattr(StylePickerDialog, "exec",
                        lambda self: opened.append(True) or 0)
    hearth.window.style_closet_requested.emit()
    assert opened == [True]
    hearth.shutdown()
