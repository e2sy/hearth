"""PyInstaller entry point for the hearth music player.

This wrapper exists because ``hearth/__main__.py`` uses a relative
import (``from .app import main``) which works for ``python -m hearth``
(the package context) but fails when PyInstaller freezes the script as
a top-level ``__main__.py`` (no package context). This wrapper does the
absolute import instead, so the frozen binary boots cleanly on every
platform (Linux ELF, Windows .exe, macOS .app).

Identical behavior to ``python -m hearth``: parse no args of its own,
defer everything to ``hearth.app.main``.
"""

import sys

from hearth.app import main

if __name__ == "__main__":
    sys.exit(main())
