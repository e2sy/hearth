"""Pre-import crash dumper for the frozen hearth binary.

The Problem
-----------
When the app runs as a PyInstaller-frozen binary with ``console=False``
(the default for GUI apps on Windows), there is **no stderr at all**.
A PyQt6 DLL load error, a Qt Multimedia FFmpeg backend crash, an
import-time side effect — anything that would normally print a
traceback to the console — vanishes silently. The user sees the
window open and then close, with no clue why.

This Module
-----------
Installs three layers of capture, in order, before any PyQt6 import:

1. **stdout/stderr redirect to a file** — captures every byte the
   interpreter or Qt writes to stdout/stderr, so even pre-Python
   crashes (FFmpeg DLL load failures, Qt plugin warnings) leave a
   breadcrumb.
2. **sys.excepthook** — catches any unhandled Python exception and
   writes a full traceback to the same log, plus a Windows
   MessageBox so the user sees *something*.
3. **faulthandler** — stdlib module that catches hard crashes
   (SIGSEGV, illegal instruction, abort) and dumps the thread state
   to the log before the process dies. Not a full backtrace, but
   enough to point at the offending C frame in the Qt backend.

The log lives next to the rolling ``hearth.log`` so the user can
find it: ``%APPDATA%/hearth/Hearth/hearth-crash.log`` on Windows,
``~/.local/share/Hearth/hearth/hearth-crash.log`` on Linux,
``~/Library/Application Support/Hearth/hearth/hearth-crash.log``
on macOS.

Call :func:`install` **before** importing anything PyQt6 — the
launcher shim does this.
"""

from __future__ import annotations

import datetime
import faulthandler
import logging
import os
import sys
import traceback
from pathlib import Path

log = logging.getLogger(__name__)

_INSTALLED = False
_CRASH_LOG: Path | None = None
_FAULT_FD = None  # keep a ref so faulthandler doesn't close the fd


def _crash_log_path() -> Path:
    """Resolve the per-OS crash log path.

    Uses :class:`QStandardPaths.AppDataLocation` if Qt is already
    available; otherwise falls back to ``~/.hearth`` so the file is
    always writable even when Qt is broken (the most common crash
    case). The fallback dir is created if it doesn't exist.
    """
    try:
        from PyQt6.QtCore import QStandardPaths  # noqa: E402
        base = QStandardPaths.writableLocation(
            QStandardPaths.StandardLocation.AppDataLocation
        )
        if base:
            p = Path(base)
            p.mkdir(parents=True, exist_ok=True)
            return p / "hearth-crash.log"
    except Exception:  # noqa: BLE001 - Qt broken is the whole reason we're here
        pass
    # Fallback: a per-user dotdir that's always writable.
    p = Path.home() / ".hearth"
    p.mkdir(parents=True, exist_ok=True)
    return p / "hearth-crash.log"


def _open_crash_log() -> object | None:
    """Open the crash log for append. Returns a file object or None.

    Opened in line-buffered mode so partial output lands even if the
    process is killed. If the file can't be opened (read-only fs,
    permission error), the dumper degrades to "no file capture" and
    still installs the excepthook + faulthandler.
    """
    global _CRASH_LOG, _FAULT_FD
    try:
        _CRASH_LOG = _crash_log_path()
        fd = open(_CRASH_LOG, "a", encoding="utf-8", buffering=1)
        _FAULT_FD = fd
        return fd
    except Exception as exc:  # noqa: BLE001
        # No log file — but we still want the excepthook installed
        # so a Python exception at least tries to pop a MessageBox.
        print(f"[crashdumper] could not open crash log: {exc}", file=sys.__stderr__)
        return None


def _show_message_box(title: str, body: str) -> None:
    """Best-effort native message box for a fatal error.

    Tries Qt first (a real QMessageBox is the most legible), then
    falls back to the Windows MessageBox API via ctypes (so the
    user sees something even if Qt itself crashed at import time),
    then to stderr.
    """
    # 1. Try Qt — only if QApplication is already up.
    try:
        from PyQt6.QtWidgets import QApplication, QMessageBox  # noqa: E402
        app = QApplication.instance()
        if app is not None:
            box = QMessageBox()
            box.setIcon(QMessageBox.Icon.Critical)
            box.setWindowTitle(title)
            box.setText(body)
            box.setDetailedText(f"Crash log:\n{_CRASH_LOG}")
            box.exec()
            return
    except Exception:  # noqa: BLE001 - we're crashing, we don't care
        pass

    # 2. Try Windows MessageBox via ctypes — works without Qt.
    if sys.platform == "win32":
        try:
            import ctypes  # noqa: E402
            MB_ICONERROR = 0x00000010
            MB_OK = 0x00000000
            ctypes.windll.user32.MessageBoxW(
                0, body, title, MB_ICONERROR | MB_OK
            )
            return
        except Exception:  # noqa: BLE001
            pass

    # 3. Last resort: stderr (visible only when launched from a console).
    print(f"\n*** {title} ***\n{body}\n", file=sys.__stderr__)


def _excepthook(exc_type, exc_value, exc_tb) -> None:
    """sys.excepthook replacement: log + MessageBox + propagate."""
    # The default excepthook prints to sys.stderr; we want a richer
    # surface for the frozen binary.
    try:
        tb = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
        if _FAULT_FD is not None:
            _FAULT_FD.write(
                f"\n=== unhandled exception "
                f"{datetime.datetime.now().isoformat(timespec='seconds')} ===\n"
                f"{tb}\n"
            )
            _FAULT_FD.flush()
        else:
            # Crash log couldn't be opened; fall back to stderr.
            print(tb, file=sys.__stderr__)
    except Exception:  # noqa: BLE001 - dumper must never bite
        pass

    # Show the user a native message box so they at least know the
    # app crashed (and where to find the log). Skip KeyboardInterrupt.
    if not issubclass(exc_type, KeyboardInterrupt):
        msg = f"{exc_type.__name__}: {exc_value}"
        _show_message_box("Hearth crashed", msg[:500])


def install() -> None:
    """Install the stdout/stderr redirect, excepthook, and faulthandler.

    Idempotent: calling twice is a no-op. Safe to call from any thread.
    """
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True

    # 1. Open the crash log and redirect stdout/stderr into it.
    fd = _open_crash_log()
    if fd is not None:
        # Write a session header so each run is identifiable.
        fd.write(
            f"\n=== hearth session "
            f"{datetime.datetime.now().isoformat(timespec='seconds')} ===\n"
            f"frozen={getattr(sys, 'frozen', False)} "
            f"platform={sys.platform} "
            f"python={sys.version.split()[0]}\n"
        )
        fd.flush()
        # Replace the high-level streams; keep sys.__stdout__ /
        # sys.__stderr__ for the rare code path that wants the real
        # console (e.g. the message-box fallback in _show_message_box).
        sys.stdout = fd
        sys.stderr = fd

    # 2. faulthandler — catches hard C-level crashes (SIGSEGV, SIGABRT)
    # and dumps the thread state to the file *before* the process dies.
    # The dump is not a full Python traceback, but it's enough to point
    # at the offending Qt/FFmpeg frame.
    if fd is not None:
        try:
            faulthandler.enable(fd, all_threads=True)
        except Exception as exc:  # noqa: BLE001
            fd.write(f"[crashdumper] faulthandler.enable failed: {exc}\n")

    # 3. Replace the excepthook with our logger + MessageBox.
    sys.excepthook = _excepthook

    # 4. Tell the user where the crash log lives — visible in the
    # crash log itself (so a user who pastes the log back to us
    # sees the path), and also via stderr (visible if launched from
    # a console).
    where = str(_CRASH_LOG) if _CRASH_LOG else "(no log file opened)"
    msg = f"[crashdumper] crash log → {where}"
    try:
        print(msg, file=sys.__stderr__)
    except Exception:  # noqa: BLE001
        pass
    if fd is not None:
        fd.write(msg + "\n")
        fd.flush()
