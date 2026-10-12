# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the hearth music player.

Single-file build that bundles the ``hearth`` package plus the
PyQt6/QtMultimedia backend, yt-dlp, ytmusicapi, and requests.
No external data files need bundling — every icon is painted
procedurally (``QPixmap`` in ``hearth/icons.py``, ``hearth/tray.py``)
and every font is resolved from the OS via Qt's font database.

The build is platform-native: produce a Linux ELF here, a Windows
.exe on a Windows runner, and a macOS .app on a macOS runner — same
spec works for all three (PyInstaller picks the right hook set per
platform automatically).
"""

from PyInstaller.utils.hooks import collect_submodules

block_cipher = None

import os  # noqa: E402

# Force-collect the Qt multimedia plugin trees so the FFmpeg backend
# ships inside the bundle (the lazy imports inside ``player.py`` hide
# the dependency from PyInstaller's static analysis).
hiddenimports = [
    "PyQt6.QtMultimedia",
    "PyQt6.QtMultimediaWidgets",
]
hiddenimports += collect_submodules("yt_dlp")
hiddenimports += collect_submodules("ytmusicapi")

# Some Qt shared libs are loaded via dlopen at runtime (libEGL, libGLESv2
# on Linux; these are bundled with the PyQt6 wheel under Qt6/lib).
# PyInstaller's static analysis misses them, so we add them manually.
_qt_lib_dir = os.path.join(
    os.path.dirname(__import__("PyQt6").__file__),
    "Qt6", "lib",
)
_binaries = []
for _so in ("libEGL.so.1", "libGLESv2.so.2"):
    _p = os.path.join(_qt_lib_dir, _so)
    if os.path.exists(_p):
        _binaries.append((_p, "."))

a = Analysis(
    ["launcher.py"],
    pathex=["."],
    binaries=_binaries,
    datas=[],
    hiddenimports=hiddenimports,
    runtime_hooks=[],
    excludes=[
        # Test-only deps we never want in a shipping bundle.
        "tests",
        "pytest",
        "_pytest",
    ],
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="hearth",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,  # UPX not present in build env; turn off to avoid noise
    # A real icon would live under packaging/hearth.ico (Windows) or
    # packaging/hearth.icns (macOS). For now ship without — the
    # window icon is painted at runtime.
    console=False,  # GUI app: no console window on Windows
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
