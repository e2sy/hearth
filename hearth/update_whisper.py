"""Update whisper: one quiet candle when a newer hearth is lit (opt-in).

A tiny GitHub Releases poll that never blocks startup, never hammers
the network (at most once per UPDATE_CHECK_INTERVAL_H), and never nags
twice for the same tag. It is OFF by default —
``config.UPDATE_CHECK_ENABLED`` — so the wiring below doesn't even
schedule a timer until someone asks for it.

The fetch rides the app's job pool (urllib, 8s timeout, never raises);
the decision logic is pure and clock-injected like AlarmController, so
tests can drive months of "should I whisper?" in microseconds.
"""

from __future__ import annotations

import json
import logging
import re
import time
import urllib.request
from typing import Callable

from PyQt6.QtCore import QObject, QRunnable, QThreadPool, QTimer, pyqtSignal

from . import config

log = logging.getLogger(__name__)

# https://github.com/qtjg/hearth → https://api.github.com/repos/qtjg/hearth/…
RELEASES_API_URL = (
    config.REPO_URL.replace("https://github.com", "https://api.github.com/repos")
    .rstrip("/")
    + "/releases/latest"
)

REQUEST_TIMEOUT_S = 8.0        # one patient breath, then give up quietly
FIRST_CHECK_DELAY_S = 60.0     # never block startup: first look ≥60s after boot
DISMISS_KEY = "update/dismissed_tag"   # QSettings: never nag this tag again
LAST_CHECK_KEY = "update/last_check"   # QSettings: float epoch of last attempt

WHISPER_MESSAGE = "🕯️ A newer hearth is lit — {tag}"

_VERSION_PIECE = re.compile(r"\d+")


def _version_tuple(text: str) -> tuple[int, ...]:
    """'v0.7.0-rc1' → (0, 7, 0); 'banana' → (0,)."""
    text = str(text or "").strip().lstrip("vV")
    parts: list[int] = []
    for piece in text.split("."):
        match = _VERSION_PIECE.match(piece)
        parts.append(int(match.group()) if match else 0)
    return tuple(parts) if parts else (0,)


def compare_versions(current: str, tag: str) -> bool:
    """True when `tag` names a release strictly newer than `current`.

    Robust to "v" prefixes, missing segments and plain garbage (which
    simply never counts as newer). Pure, never raises.
    """
    try:
        return _version_tuple(tag) > _version_tuple(current)
    except Exception:  # noqa: BLE001 - a weird tag is just "no news"
        return False


def fetch_latest_release(timeout: float = REQUEST_TIMEOUT_S) -> dict | None:
    """GET the latest GitHub release. Never raises — None on any failure.

    Returns {"tag_name": …, "html_url": …, "name": …} with only the
    fields the whisper actually needs. Runs on a job pool (see
    ReleaseCheckJob), never on the UI thread.
    """
    try:
        request = urllib.request.Request(
            RELEASES_API_URL,
            headers={
                "Accept": "application/vnd.github+json",
                "User-Agent": "hearth-update-whisper",
            },
        )
        with urllib.request.urlopen(request, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8", "replace"))
    except Exception as exc:  # noqa: BLE001 - offline is a normal Tuesday
        log.debug("update check failed quietly: %s", exc)
        return None
    if not isinstance(data, dict):
        return None
    tag = data.get("tag_name")
    if not isinstance(tag, str) or not tag.strip():
        return None
    html_url = data.get("html_url")
    name = data.get("name")
    return {
        "tag_name": tag.strip(),
        "html_url": html_url if isinstance(html_url, str) else "",
        "name": name if isinstance(name, str) else "",
    }


class _Carrier(QObject):
    """Signal bridge from the pool thread back to the UI thread."""

    fetched = pyqtSignal(object)   # release dict | None

    def emit_safe(self, signal, payload) -> None:
        try:
            signal.emit(payload)
        except RuntimeError:
            log.debug("update-whisper carrier gone — recipient closed")


class ReleaseCheckJob(QRunnable):
    """One GitHub Releases GET on the shared pool — never raises."""

    def __init__(self, timeout: float = REQUEST_TIMEOUT_S):
        super().__init__()
        self.setAutoDelete(False)   # lifetime managed by the receiving slot
        self.signals = _Carrier()
        self.timeout = timeout

    def run(self) -> None:  # noqa: D102 - QRunnable entry
        self.signals.emit_safe(self.signals.fetched, fetch_latest_release(self.timeout))


class UpdateWhisper(QObject):
    """The opt-in gatekeeper: due? fetched? new? not dismissed? whisper.

    Pure clock injection (like AlarmController) keeps the interval math
    honest in tests; the settings object is the same QSettings the app
    already uses, so the dismissed tag survives restarts.
    """

    whisper = pyqtSignal(str, str, str)   # message, html_url, tag

    def __init__(self, settings, clock: Callable[[], float] | None = None,
                 parent: QObject | None = None):
        super().__init__(parent)
        self._settings = settings
        self._now = clock or (lambda: time.time())
        self._timer: QTimer | None = None

    # --- persisted state (never raises on weird INI values) ---

    def dismissed_tag(self) -> str:
        try:
            return str(self._settings.value(DISMISS_KEY, "") or "")
        except Exception:  # noqa: BLE001
            return ""

    def dismiss(self, tag: str) -> None:
        """The listener waved it away — never nag about this tag again."""
        if not tag:
            return
        try:
            self._settings.setValue(DISMISS_KEY, str(tag))
        except Exception:  # noqa: BLE001
            log.debug("could not persist dismissed tag", exc_info=True)

    def _last_check(self) -> float:
        try:
            return float(self._settings.value(LAST_CHECK_KEY, 0) or 0)
        except (TypeError, ValueError):
            return 0.0

    def _note_checked(self) -> None:
        try:
            self._settings.setValue(LAST_CHECK_KEY, float(self._now()))
        except Exception:  # noqa: BLE001
            log.debug("could not persist last-check time", exc_info=True)

    # --- interval gate (pure, clock-injected) ---

    def _interval_s(self) -> float:
        return max(0.0, float(config.UPDATE_CHECK_INTERVAL_H)) * 3600.0

    def due(self) -> bool:
        """A check may run now (False whenever the whisper is off)."""
        if not config.UPDATE_CHECK_ENABLED:
            return False
        return self._now() - self._last_check() >= self._interval_s()

    def next_check_delay_s(self) -> float | None:
        """Seconds until the first permitted check; None when off.

        Always ≥ FIRST_CHECK_DELAY_S — startup never waits on (or gets
        interrupted by) the network in the first minute of life.
        """
        if not config.UPDATE_CHECK_ENABLED:
            return None
        remaining = self._last_check() + self._interval_s() - self._now()
        return max(FIRST_CHECK_DELAY_S, remaining)

    # --- scheduling + fetch (job pool; UI thread only whispers) ---

    def schedule(self, parent: QObject | None = None) -> bool:
        """Arm the boot timer. False (and nothing armed) when off."""
        delay = self.next_check_delay_s()
        if delay is None:
            return False
        self._timer = QTimer(parent) if parent is not None else QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._run_check)
        self._timer.start(int(delay * 1000))
        log.info("update whisper armed: first check in %ds", int(delay))
        return True

    def _run_check(self) -> None:
        """Fire the fetch on the shared pool; absorb() lands on the UI thread."""
        if not self.due():
            return
        job = ReleaseCheckJob()
        job.signals.fetched.connect(self.absorb)
        QThreadPool.globalInstance().start(job)

    # --- the decision ---

    def absorb(self, payload) -> None:
        """A fetched payload landed: whisper only genuinely new news.

        Records the attempt (failed or not — an offline box shouldn't
        retry every minute), then filters: disabled → silent, not
        newer → silent, already dismissed → silent.
        """
        self._note_checked()
        if not config.UPDATE_CHECK_ENABLED:
            return                     # off is off, everywhere, always
        if not isinstance(payload, dict):
            return
        tag = str(payload.get("tag_name") or "").strip()
        if not tag:
            return
        if not compare_versions(config.VERSION, tag):
            return
        if tag == self.dismissed_tag():
            return
        message = WHISPER_MESSAGE.format(tag=tag)
        log.info("update whisper: %s", message)
        self.whisper.emit(message, str(payload.get("html_url") or ""), tag)
