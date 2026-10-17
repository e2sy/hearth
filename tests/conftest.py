"""Shared pytest fixtures: offscreen Qt platform + one QApplication."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

# CI-only: when a hard SIGSEGV hits (the intermittent macOS runner crash),
# faulthandler must print every thread's C-level stack so the next red run
# pinpoints the frame. Locally this is a no-op (no CI env var).
if os.environ.get("CI"):
    import faulthandler

    faulthandler.enable(all_threads=True)

import pytest
from PyQt6.QtWidgets import QApplication


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance() or QApplication(["hearth-test"])
    yield app
