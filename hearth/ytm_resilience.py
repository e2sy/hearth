"""Junk-card tolerance for ytmusicapi's content parser.

The YT Music API sometimes returns promo playlist cards whose title runs
carry no navigationEndpoint; ytmusicapi (<= 1.12.x) then raises KeyError
for the WHOLE shelf — an entire genre category lost to one bad card.
Skipping the unparsable cards is strictly better. The library's
``parse_content_list`` is rebound (in every module that imported it)
with a fault-tolerant twin; our own mappers already drop items without
ids, so skipped cards simply vanish.

Applied once, lazily, from Catalog._get_client — ytmusicapi is only
imported there, and by then every mixin module is in sys.modules.
"""

from __future__ import annotations

import logging
import sys

log = logging.getLogger(__name__)

_APPLIED = False


def _resilient_parse_content_list(
    results: list[dict],
    parse_func,
    key: str = "musicTwoRowItemRenderer",
) -> list[dict]:
    contents = []
    for result in results or []:
        try:
            contents.append(parse_func(result[key]))
        except Exception as exc:  # noqa: BLE001 - one junk card must not kill a shelf
            log.debug("skipped unparsable catalog card: %s", exc)
    return contents


def apply() -> None:
    """Rebind parse_content_list across every ytmusicapi module (idempotent)."""
    global _APPLIED
    if _APPLIED:
        return
    from ytmusicapi.parsers import browsing  # the defining module

    browsing.parse_content_list = _resilient_parse_content_list
    patched = 1
    for module in list(sys.modules.values()):
        if module is None:
            continue
        name = getattr(module, "__name__", "")
        if not name.startswith("ytmusicapi") or name.endswith("parsers.browsing"):
            continue
        if hasattr(module, "parse_content_list"):
            try:
                module.parse_content_list = _resilient_parse_content_list
                patched += 1
            except (AttributeError, TypeError):  # pragma: no cover - frozen module
                continue
    _APPLIED = True
    log.info("ytmusicapi junk-card resilience patched into %d modules", patched)
