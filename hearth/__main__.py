"""`python -m hearth` entry point."""

import sys

# Install the crash dumper BEFORE any PyQt6 import so that DLL load
# failures, FFmpeg backend crashes, and Qt plugin warnings all land
# in the crash log (next to hearth.log). Harmless when not frozen —
# the dumper is a no-op for stdout/stderr when the file can't be
# opened, and the excepthook is the only meaningful install.
from .crashdumper import install as _install_crashdumper

_install_crashdumper()

from .app import main

if __name__ == "__main__":
    sys.exit(main())
