"""Versioned plugin hooks — tiny, honest, and never raises.

A plugin is a directory under the plugins root (default: ``<appdata>/plugins``)
containing a ``manifest.json`` shaped like::

    {
        "hearth-plugin": 1,
        "name": "Cozy Palettes",
        "entry": "cozy:register",
        "provides": ["palette", "shelf"]
    }

...plus an importable Python module (``cozy.py`` or ``cozy/__init__.py``)
whose ``register(services)`` function receives a tiny services dict::

    {"register_palette": fn, "register_shelf_source": fn}

``register_palette`` wraps ``theme.register_custom_palette`` (fed a palette
dict; invalid dicts are rejected), and ``register_shelf_source(name, fn)``
hands hearth a callable that returns a list of Track-shaped dicts — resolved
on a worker pool and rendered on the home "🔌 Plugins" shelf.

Versioning: manifests carry a ``"hearth-plugin"`` format number. hearth
refuses anything it does not speak (currently 1) with a collected warning
instead of a crash, so a future format fails soft on an older player.

SECURITY NOTE — read this honestly: plugins are *trusted user installs*.
Loading one executes that code with the full rights of the hearth process;
there is no sandbox, no capability wall, and no signature check. Manifest
validation exists to protect hearth from *accidents* (bad JSON, wrong
version, missing entry) — not from malice. Install a plugin the way you
would install any other program on your machine.

Discovery does no network I/O and the whole surface is defensive: a broken
plugin costs a warning, never a fire.
"""

from __future__ import annotations

import importlib
import json
import logging
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger(__name__)

MANIFEST_NAME = "manifest.json"
FORMAT_KEY = "hearth-plugin"
SUPPORTED_VERSION = 1

# The home shelf fed by registered shelf sources.
SHELF_NAME = "🔌 Plugins"


@dataclass(frozen=True)
class PluginInfo:
    """A parsed, validated manifest — everything hearth knows pre-load."""

    name: str
    directory: Path
    entry: str                     # "module:attr" inside the plugin directory
    provides: tuple[str, ...] = ()
    manifest: dict = field(default_factory=dict, compare=False)


def default_root() -> Path:
    """The default plugins root, derived from the app's own data directory."""
    from .app import data_dir   # local import keeps this module import-light

    return data_dir() / "plugins"


def _warn(warnings: list[str] | None, message: str) -> None:
    """One problem, logged and collected — never raised."""
    log.warning("%s", message)
    if warnings is not None:
        warnings.append(message)


# ------------------------------------------------------------- discovery

def discover_plugins(
    root: str | Path, warnings: list[str] | None = None
) -> list[PluginInfo]:
    """Parse every manifest under `root`, sorted by folder name.

    Invalid manifests (bad JSON, unsupported version, missing fields) are
    skipped with a collected warning; a folder without a manifest simply
    is not a plugin. A missing root comes back as an empty list. Never
    raises, never touches the network.
    """
    root = Path(root)
    found: list[PluginInfo] = []
    if not root.is_dir():
        # the normal state for most installs — quiet, not a problem
        log.info("no plugins root at %s — nothing to discover", root)
        return found
    try:
        children = sorted(
            p for p in root.iterdir()
            if p.is_dir() and not p.name.startswith((".", "_"))
        )
    except OSError as exc:
        _warn(warnings, f"plugins root unreadable: {root} ({exc})")
        return found
    for child in children:
        manifest_path = child / MANIFEST_NAME
        if not manifest_path.is_file():
            continue    # just clutter sharing the folder — quiet skip
        try:
            data = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            _warn(warnings, f"plugin {child.name}: unreadable manifest ({exc})")
            continue
        info = _info_from_manifest(data, child, warnings)
        if info is not None:
            found.append(info)
    return found


def _info_from_manifest(
    data: object, directory: Path, warnings: list[str] | None
) -> PluginInfo | None:
    """Validate one parsed manifest. None (plus a warning) when invalid."""
    where = f"plugin {directory.name}"
    if not isinstance(data, dict):
        _warn(warnings, f"{where}: manifest is not a JSON object")
        return None
    version = data.get(FORMAT_KEY)
    if isinstance(version, bool) or not isinstance(version, int):
        _warn(warnings, f"{where}: missing '{FORMAT_KEY}' version")
        return None
    if version != SUPPORTED_VERSION:
        _warn(warnings, f"{where}: plugin format {version} refused — "
                        f"hearth speaks {SUPPORTED_VERSION}")
        return None
    name = data.get("name")
    if not isinstance(name, str) or not name.strip():
        _warn(warnings, f"{where}: missing 'name'")
        return None
    entry = data.get("entry")
    if (not isinstance(entry, str)
            or entry.count(":") != 1
            or not all(part.strip() for part in entry.split(":"))):
        _warn(warnings, f"{where}: 'entry' must be 'module:attr', got {entry!r}")
        return None
    provides_raw = data.get("provides", [])
    if not isinstance(provides_raw, list):
        _warn(warnings, f"{where}: 'provides' should be a list — ignoring it")
        provides_raw = []
    return PluginInfo(
        name=name.strip(),
        directory=directory,
        entry=entry.strip(),
        provides=tuple(str(p) for p in provides_raw),
        manifest=data,
    )


# ------------------------------------------------------------- loading

class _PluginError(Exception):
    """Internal: why a plugin could not load (recorded, never raised out)."""


def _import_entry(info: PluginInfo) -> object:
    """Import the plugin's entry callable, or raise `_PluginError`.

    The plugin directory is prepended to `sys.path` just for the import
    (and removed again), so `entry: "my_plugin:register"` resolves to
    ``<plugin dir>/my_plugin.py`` (or a package's ``__init__.py``).
    """
    module_name, _sep, attr = info.entry.partition(":")
    plugin_dir = str(info.directory)
    try:
        sys.path.insert(0, plugin_dir)
        try:
            module = importlib.import_module(module_name)
        finally:
            try:
                sys.path.remove(plugin_dir)
            except ValueError:
                pass
    except Exception as exc:   # noqa: BLE001 - import errors are plugin bugs
        raise _PluginError(f"import of '{module_name}' failed: {exc}") from exc
    obj = getattr(module, attr, None)
    if obj is None:
        raise _PluginError(f"entry '{info.entry}' not found in the plugin module")
    if not callable(obj):
        raise _PluginError(f"entry '{info.entry}' is not callable")
    return obj


def load_plugin(
    info: PluginInfo, services: dict, warnings: list[str] | None = None
) -> object | None:
    """Import + run one plugin's entry with `services`; result or None.

    Any failure — missing module, absent attribute, an entry that raises —
    becomes a collected warning and ``None``. A broken plugin must never
    take the fire down.
    """
    try:
        return _import_entry(info)(services)
    except Exception as exc:   # noqa: BLE001 - the plugin boundary
        _warn(warnings, f"plugin {info.name}: {exc}")
        return None


def load_all(
    root: str | Path,
    services: dict,
    deadline: float | None = None,
    warnings: list[str] | None = None,
) -> list[tuple[PluginInfo, object | Exception]]:
    """Discover + load every plugin under `root`.

    Returns ``(PluginInfo, result)`` pairs — a healthy plugin yields
    whatever its entry returned, a broken one yields the exception so
    callers can report it without this function ever raising.
    `deadline` (a ``time.monotonic()`` stamp) time-boxes the load: once
    it has passed, the remaining plugins are skipped with a warning.
    """
    results: list[tuple[PluginInfo, object | Exception]] = []
    for info in discover_plugins(root, warnings):
        if deadline is not None and time.monotonic() > deadline:
            _warn(warnings, f"plugin load window closed — skipping {info.name}")
            break
        try:
            results.append((info, _import_entry(info)(services)))
        except Exception as exc:   # noqa: BLE001 - recorded, never raised
            results.append((info, exc))
    return results
