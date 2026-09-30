"""Shared pytest fixtures: offscreen Qt platform + one QApplication."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6.QtWidgets import QApplication


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance() or QApplication(["hearth-test"])
    yield app
