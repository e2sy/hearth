"""App-level smoke test: full wiring headless, settings persistence roundtrip."""

from hearth import config
from hearth.app import Hearth


def make_hearth(tmp_path) -> Hearth:
    return Hearth(
        argv=["hearth-test"],
        settings_path=str(tmp_path / "settings.ini"),
        data_directory=tmp_path / "data",
        single_instance=False,
        enable_streaming=False,  # keep pool jobs out of unit tests
    )


def test_app_boots_all_components(tmp_path, qapp):
    hearth = make_hearth(tmp_path)
    assert hearth.core is not None
    assert hearth.panel is not None
    assert hearth.toast is not None
    assert hearth.store is not None
    hearth.shutdown()


def test_settings_persist_volume_repeat_rate(tmp_path, qapp):
    hearth = make_hearth(tmp_path)
    hearth.core.set_volume(0.55)
    hearth.core.set_repeat(config.REPEAT_ONE)
    hearth.core.set_rate(1.25)
    hearth.shutdown()

    reopened = make_hearth(tmp_path)
    assert reopened.core.volume == 0.55
    assert reopened.core.engine.repeat == config.REPEAT_ONE
    assert reopened.core.rate == 1.25
    reopened.shutdown()


def test_pick_track_writes_history_and_updates_panel(tmp_path, qapp):
    hearth = make_hearth(tmp_path)
    from .test_models import make_track

    hearth._pick_track(make_track())
    assert len(hearth.store.history()) == 1
    assert hearth.panel._title.text() != "Hearth — nothing playing yet"
    hearth.shutdown()


# --- Qt message bridge: the terminal firehose tamer (v0.6.3 audit) ---


def test_qt_messages_route_to_logging_not_stderr(caplog):
    import logging
    from types import SimpleNamespace

    from PyQt6.QtCore import QtMsgType

    from hearth.app import _qt_message

    with caplog.at_level(logging.DEBUG, logger="qt"):
        # the exact line that flooded MAYANK's terminal, now file-only DEBUG
        _qt_message(
            QtMsgType.QtWarningMsg,
            SimpleNamespace(category=b"qt.multimedia.ffmpeg.mediadataholder"),
            b"Could not open media. FFmpeg error 403",
        )
        # ordinary Qt warnings keep their natural severity
        _qt_message(
            QtMsgType.QtWarningMsg,
            SimpleNamespace(category=b"qt.qpa.xcb"),
            b"could not connect to display",
        )
        # str payloads and empty categories must not crash the handler
        _qt_message(QtMsgType.QtCriticalMsg, SimpleNamespace(category=None), "plain text")

    by_name = {r.name: r for r in caplog.records}
    multimedia = by_name["qt.qt.multimedia.ffmpeg.mediadataholder"]
    assert multimedia.levelno == logging.DEBUG
    assert "Could not open media" in multimedia.message
    assert by_name["qt.qt.qpa.xcb"].levelno == logging.WARNING
    assert by_name["qt"].levelno == logging.ERROR


def test_qt_bridge_is_installed_on_boot(tmp_path, qapp):
    from PyQt6.QtCore import qInstallMessageHandler

    make_hearth(tmp_path).shutdown()
    assert qInstallMessageHandler(None) is not None  # something was installed
