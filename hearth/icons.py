"""Real icons: crisp geometric strokes drawn in memory — no emoji, no assets.

Every icon is SVG path data in a 24×24 box, rendered through QSvgRenderer
at any size/color and cached. Stroke icons use round caps and a constant
pen weight so the whole set reads as one hand; brand marks (flame, play
triangles) are filled paths.

The house rule holds: no third-party marks, nothing loaded from disk —
the icons are born in memory and die in the pixmap cache.
"""

from __future__ import annotations

from PyQt6.QtCore import QByteArray, Qt
from PyQt6.QtGui import QIcon, QPixmap
from PyQt6.QtSvg import QSvgRenderer

_VIEWBOX = 24
_STROKE_W = 1.8

# name -> tuple of SVG path elements (each: (kind, d)) where kind is
# "s" (stroke) or "f" (fill). Drawn inside a 24x24 viewBox.
_ICONS: dict[str, tuple[tuple[str, str], ...]] = {
    # --- navigation -------------------------------------------------------
    "home": (
        ("s", "M3 10.8 12 3.2l9 7.6"),
        ("s", "M5.5 9.5V20a1 1 0 0 0 1 1H9.8v-6.2h4.4V21h3.3a1 1 0 0 0 1-1V9.5"),
    ),
    "compass": (
        ("s", "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18Z"),
        ("f", "M15.9 8.1l-2.2 6.2-5.6 1.6 2.2-6.2 5.6-1.6Z"),
    ),
    "globe": (
        ("s", "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18Z"),
        ("s", "M3 12h18"),
        ("s", "M12 3a13.5 13.5 0 0 1 0 18M12 3a13.5 13.5 0 0 0 0 18"),
    ),
    "search": (
        ("s", "M11 18a7 7 0 1 0 0-14 7 7 0 0 0 0 14Z"),
        ("s", "M16.2 16.2 21 21"),
    ),
    "library": (
        ("s", "M5 4v16"),
        ("s", "M10 4v16"),
        ("s", "M14.2 5.1l4.6 14.3"),
    ),
    "folder": (
        ("s", "M3 7.2A2.2 2.2 0 0 1 5.2 5h4l2 2.4h7.6A2.2 2.2 0 0 1 21 9.6v7.2a2.2 2.2 0 0 1-2.2 2.2H5.2A2.2 2.2 0 0 1 3 16.8V7.2Z"),
    ),
    "disc": (
        ("s", "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18Z"),
        ("f", "M12 14.2a2.2 2.2 0 1 1 0-4.4 2.2 2.2 0 0 1 0 4.4Z"),
    ),
    "chart": (
        ("s", "M6 20v-6"),
        ("s", "M12 20V4"),
        ("s", "M18 20v-10"),
    ),
    "clock": (
        ("s", "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18Z"),
        ("s", "M12 7v5l3.4 2"),
    ),
    "theater": (
        ("s", "M3.5 5.5h17v13h-17Z"),
        ("s", "M7.5 5.5v13M16.5 5.5v13M3.5 9.5h4M3.5 14.5h4M16.5 9.5h4M16.5 14.5h4"),
    ),
    # --- transport --------------------------------------------------------
    "play": (
        ("f", "M8.2 5.4v13.2a.7.7 0 0 0 1.06.6l10.2-6.6a.7.7 0 0 0 0-1.2L9.26 4.8a.7.7 0 0 0-1.06.6Z"),
    ),
    "pause": (
        ("f", "M7.5 4.8h3v14.4h-3Z"),
        ("f", "M13.5 4.8h3v14.4h-3Z"),
    ),
    "next": (
        ("f", "M5.5 5.8v12.4a.6.6 0 0 0 .92.5l8.3-6.2a.6.6 0 0 0 0-1l-8.3-6.2a.6.6 0 0 0-.92.5Z"),
        ("f", "M15.8 5h2.4v14h-2.4Z"),
    ),
    "prev": (
        ("f", "M18.5 5.8v12.4a.6.6 0 0 1-.92.5l-8.3-6.2a.6.6 0 0 1 0-1l8.3-6.2a.6.6 0 0 1 .92.5Z"),
        ("f", "M5.8 5h2.4v14H5.8Z"),
    ),
    "shuffle": (
        ("s", "M16.5 3.5H21V8"),
        ("s", "M3.5 20.5 21 3.5"),
        ("s", "M21 16v4.5h-4.5"),
        ("s", "M14.8 14.8l6.2 5.7"),
        ("s", "M3.5 3.5l6.5 6"),
    ),
    "repeat": (
        ("s", "M17 2.5l4 4-4 4"),
        ("s", "M3 11.5V10a3.5 3.5 0 0 1 3.5-3.5H21"),
        ("s", "M7 21.5l-4-4 4-4"),
        ("s", "M21 12.5V14a3.5 3.5 0 0 1-3.5 3.5H3"),
    ),
    "queue": (
        ("s", "M8.5 6h12"),
        ("s", "M8.5 12h12"),
        ("s", "M8.5 18h12"),
        ("f", "M4 7.1a1.1 1.1 0 1 0 0-2.2 1.1 1.1 0 0 0 0 2.2Z"),
        ("f", "M4 13.1a1.1 1.1 0 1 0 0-2.2 1.1 1.1 0 0 0 0 2.2Z"),
        ("f", "M4 19.1a1.1 1.1 0 1 0 0-2.2 1.1 1.1 0 0 0 0 2.2Z"),
    ),
    "volume": (
        ("f", "M11.5 4.9 6.8 8.8H3.6a.6.6 0 0 0-.6.6v5.2a.6.6 0 0 0 .6.6h3.2l4.7 3.9a.55.55 0 0 0 .9-.42V5.32a.55.55 0 0 0-.9-.42Z"),
        ("s", "M15.2 8.7a4.7 4.7 0 0 1 0 6.6"),
        ("s", "M18 6a8.4 8.4 0 0 1 0 12"),
    ),
    "radio": (
        ("f", "M12 14.1a2.1 2.1 0 1 1 0-4.2 2.1 2.1 0 0 1 0 4.2Z"),
        ("s", "M15.4 8.6a4.8 4.8 0 0 1 0 6.8"),
        ("s", "M8.6 15.4a4.8 4.8 0 0 1 0-6.8"),
        ("s", "M18.2 5.8a8.8 8.8 0 0 1 0 12.4"),
        ("s", "M5.8 18.2a8.8 8.8 0 0 1 0-12.4"),
    ),
    # --- marks & actions --------------------------------------------------
    "flame": (
        ("f", "M12 2.4c.4 2.9-.8 4.9-2.4 6.9C8 11.3 6 13.2 6 16.2A6 6 0 0 0 18 16.2c0-2.1-1-3.9-2.2-5.5-.5 1-1 1.6-2 2.2.3-3.4-.5-7.4-1.8-10.5Z"),
    ),
    "heart": (
        ("f", "M12 20.1C7.2 16.4 3.6 13.4 3.6 9.9A4.7 4.7 0 0 1 12 7.2a4.7 4.7 0 0 1 8.4 2.7c0 3.5-3.6 6.5-8.4 10.2Z"),
    ),
    "plus": (
        ("s", "M12 5.5v13"),
        ("s", "M5.5 12h13"),
    ),
    "upload": (
        ("s", "M20.5 15.5v3.6a1.9 1.9 0 0 1-1.9 1.9H5.4a1.9 1.9 0 0 1-1.9-1.9v-3.6"),
        ("s", "M16.4 8 12 3.6 7.6 8"),
        ("s", "M12 3.6V15"),
    ),
    "download": (
        ("s", "M20.5 15.5v3.6a1.9 1.9 0 0 1-1.9 1.9H5.4a1.9 1.9 0 0 1-1.9-1.9v-3.6"),
        ("s", "M7.6 11.5 12 15.9l4.4-4.4"),
        ("s", "M12 15.9V3.5"),
    ),
    "palette": (
        ("s", "M12 3.2S5.5 9 5.5 13.6a6.5 6.5 0 0 0 13 0C18.5 9 12 3.2 12 3.2Z"),
    ),
    "layers": (
        ("f", "M12 2.6 2.5 7.4 12 12.2l9.5-4.8L12 2.6Z"),
        ("s", "M2.5 12.2 12 17l9.5-4.8"),
        ("s", "M2.5 17 12 21.8 21.5 17"),
    ),
    "spark": (
        ("f", "M12 2.5l2 6 6 2-6 2-2 6-2-6-6-2 6-2 2-6Z"),
        ("f", "M19.5 15.5l.9 2.6 2.6.9-2.6.9-.9 2.6-.9-2.6-2.6-.9 2.6-.9.9-2.6Z"),
    ),
    "music": (
        ("f", "M9.6 17.4a2.7 2.7 0 1 1-5.4 0 2.7 2.7 0 0 1 5.4 0Z"),
        ("f", "M21 15.4a2.7 2.7 0 1 1-5.4 0 2.7 2.7 0 0 1 5.4 0Z"),
        ("s", "M9.6 17.4V5.4L21 3.4v12"),
    ),
    "expand": (
        ("s", "M14.5 3.5H20.5V9.5"),
        ("s", "M9.5 20.5H3.5V14.5"),
        ("s", "M20.5 3.5l-7.2 7.2"),
        ("s", "M3.5 20.5l7.2-7.2"),
    ),
    "close": (
        ("s", "M6 6l12 12"),
        ("s", "M18 6 6 18"),
    ),
    "pin": (
        ("s", "M9.5 3.5h5l-.6 6.2 2.9 3.3v1.5H7.2v-1.5l2.9-3.3-.6-6.2Z"),
        ("s", "M12 14.5v6"),
    ),
    "moon": (
        ("f", "M20.8 13.2A8.8 8.8 0 1 1 10.8 3.2a7 7 0 0 0 10 10Z"),
    ),
    "sliders": (
        ("s", "M5 20.5v-6.2"),
        ("s", "M5 10.5v-7"),
        ("s", "M12 20.5v-9"),
        ("s", "M12 7.5v-4"),
        ("s", "M19 20.5v-3.7"),
        ("s", "M19 13V3.5"),
        ("s", "M2.6 14.3h4.8"),
        ("s", "M9.6 7.5h4.8"),
        ("s", "M16.6 16.8h4.8"),
    ),
    "users": (
        ("s", "M16 20.5v-1.8a3.8 3.8 0 0 0-3.8-3.8H6.3a3.8 3.8 0 0 0-3.8 3.8v1.8"),
        ("f", "M9.25 11.4a3.9 3.9 0 1 0 0-7.8 3.9 3.9 0 0 0 0 7.8Z"),
        ("s", "M21.5 20.5v-1.8a3.8 3.8 0 0 0-2.9-3.7"),
        ("s", "M15.4 3.8a3.9 3.9 0 0 1 0 7.5"),
    ),
    "check": (
        ("s", "M4.5 12.5l5 5L19.5 7"),
    ),
    "film": (
        ("s", "M3.5 5.8A1.8 1.8 0 0 1 5.3 4h13.4a1.8 1.8 0 0 1 1.8 1.8v12.4a1.8 1.8 0 0 1-1.8 1.8H5.3a1.8 1.8 0 0 1-1.8-1.8V5.8Z"),
        ("s", "M7.8 4v16M16.2 4v16M3.5 9h4.3M3.5 15h4.3M16.2 9h4.3M16.2 15h4.3"),
    ),
    "gift": (
        ("s", "M20.5 8.5h-17v4h17v-4Z"),
        ("s", "M4.5 12.5v6.6a1.9 1.9 0 0 0 1.9 1.9h11.2a1.9 1.9 0 0 0 1.9-1.9v-6.6"),
        ("s", "M12 8.5v12.5"),
        ("s", "M12 8.3c-1.2-.1-4.6-.4-4.6-2.7A1.9 1.9 0 0 1 11 4.7c.7 1 .9 2.4 1 3.6.1-1.2.3-2.6 1-3.6a1.9 1.9 0 0 1 3.6.9c0 2.3-3.4 2.6-4.6 2.7Z"),
    ),
    "mic": (
        ("s", "M12 15.2a3.6 3.6 0 0 0 3.6-3.6V6.1a3.6 3.6 0 0 0-7.2 0v5.5a3.6 3.6 0 0 0 3.6 3.6Z"),
        ("s", "M18.5 11.5a6.5 6.5 0 0 1-13 0"),
        ("s", "M12 18v3"),
    ),
    "image": (
        ("s", "M3.5 6.3A1.8 1.8 0 0 1 5.3 4.5h13.4a1.8 1.8 0 0 1 1.8 1.8v11.4a1.8 1.8 0 0 1-1.8 1.8H5.3a1.8 1.8 0 0 1-1.8-1.8V6.3Z"),
        ("f", "M9 10.9a1.6 1.6 0 1 1 0-3.2 1.6 1.6 0 0 1 0 3.2Z"),
        ("s", "M20.5 14.5l-4.5-4.5-8 8"),
    ),
    "stethoscope": (
        ("s", "M5 3.5v5a4 4 0 0 0 8 0v-5"),
        ("s", "M4 3.5h2M12 3.5h2"),
        ("s", "M9 12.5v3a4.5 4.5 0 0 0 9 0v-1.6"),
        ("f", "M19.6 11.6a1.9 1.9 0 1 0 0-3.8 1.9 1.9 0 0 0 0 3.8Z"),
    ),
    "phone": (
        ("s", "M7.5 2.5h9A1.5 1.5 0 0 1 18 4v16a1.5 1.5 0 0 1-1.5 1.5h-9A1.5 1.5 0 0 1 6 20V4a1.5 1.5 0 0 1 1.5-1.5Z"),
        ("s", "M10.5 18.5h3"),
    ),
    "dots": (
        ("f", "M5.2 13.4a1.4 1.4 0 1 0 0-2.8 1.4 1.4 0 0 0 0 2.8Z"),
        ("f", "M12 13.4a1.4 1.4 0 1 0 0-2.8 1.4 1.4 0 0 0 0 2.8Z"),
        ("f", "M18.8 13.4a1.4 1.4 0 1 0 0-2.8 1.4 1.4 0 0 0 0 2.8Z"),
    ),
    "arrow-up": (
        ("s", "M12 19.5v-15"),
        ("s", "M5.5 11 12 4.5 18.5 11"),
    ),
    "external": (
        ("s", "M14 4.5h5.5V10"),
        ("s", "M19.5 4.5 11 13"),
        ("s", "M19.5 13.8v4.7a1.9 1.9 0 0 1-1.9 1.9H5.6a1.9 1.9 0 0 1-1.9-1.9V6.5a1.9 1.9 0 0 1 1.9-1.9h4.7"),
    ),
}

_cache: dict[tuple[str, str, int], QIcon] = {}
_pixmap_cache: dict[tuple[str, str, int], QPixmap] = {}


def has(name: str) -> bool:
    return name in _ICONS


def _svg_bytes(name: str, color: str) -> QByteArray:
    parts = []
    for kind, d in _ICONS[name]:
        if kind == "f":
            parts.append(f"<path d='{d}' fill='{color}' stroke='none'/>")
        else:
            parts.append(
                f"<path d='{d}' fill='none' stroke='{color}' "
                f"stroke-width='{_STROKE_W}' stroke-linecap='round' "
                f"stroke-linejoin='round'/>"
            )
    xml = (
        f"<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 {_VIEWBOX} {_VIEWBOX}'>"
        + "".join(parts)
        + "</svg>"
    )
    return QByteArray(xml.encode("utf-8"))


def pixmap(name: str, color: str, size: int = 18) -> QPixmap:
    """One icon as a crisp QPixmap at device-pixel ratio 2 (retina-safe)."""
    key = (name, color, int(size))
    hit = _pixmap_cache.get(key)
    if hit is not None:
        return hit
    renderer = QSvgRenderer(_svg_bytes(name, color))
    px = max(1, int(size)) * 2
    img = QPixmap(px, px)
    img.fill(Qt.GlobalColor.transparent)
    from PyQt6.QtGui import QPainter

    painter = QPainter(img)
    renderer.render(painter)
    painter.end()
    img.setDevicePixelRatio(2.0)
    if len(_pixmap_cache) > 512:          # a long session changes colors a lot
        _pixmap_cache.clear()
    _pixmap_cache[key] = img
    return img


def icon(name: str, color: str, size: int = 18) -> QIcon:
    """One icon as a QIcon (cached). Unknown names give an empty QIcon."""
    if name not in _ICONS:
        return QIcon()
    key = (name, color, int(size))
    hit = _cache.get(key)
    if hit is not None:
        return hit
    ic = QIcon(pixmap(name, color, size))
    if len(_cache) > 256:
        _cache.clear()
    _cache[key] = ic
    return ic
