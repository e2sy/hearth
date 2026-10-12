"""PyInstaller entry point for the hearth music player.

This wrapper exists because ``hearth/__main__.py`` uses a relative
import (``from .app import main``) which works for ``python -m hearth``
(the package context) but fails when PyInstaller freezes the script as
a top-level ``__main__.py`` (no package context). This wrapper does the
absolute import instead, so the frozen binary boots cleanly on every
platform (Linux ELF, Windows .exe, macOS .app).

**Important**: the crash dumper is installed BEFORE any PyQt6 import so
that DLL load failures, FFmpeg backend crashes, and Qt plugin warnings
all land in ``%APPDATA%/hearth/Hearth/hearth-crash.log`` on Windows
(``~/.local/share/Hearth/hearth/hearth-crash.log`` on Linux). Without
this, a frozen GUI binary with ``console=False`` swallows every error
silently — the user sees the window open and close, with no clue why.

Identical behavior to ``python -m hearth``: parse no args of its own,
defer everything to ``hearth.app.main``.
"""

import sys

# Install the crash dumper FIRST — before any Qt or hearth import so
# even pre-import crashes leave a breadcrumb in the crash log.
from hearth.crashdumper import install as install_crashdumper

install_crashdumper()

from hearth.app import main

if __name__ == "__main__":
    sys.exit(main())
