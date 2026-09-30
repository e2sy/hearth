"""Stylesheets, palette packs, and lyrics typography.

The 2020s layer: every flat fill from the last decade gets depth —
vertical gradients, glassy surfaces, soft hairlines, accent glows.
All extra tones are derived from the Palette at compile time, so every
theme inherits the modern look without new color tokens.

Palettes are portable too: a pack is one small JSON file ({key, label,
color fields}) that anyone can drop into their hearth.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import dataclass, replace
from pathlib import Path
from string import Template

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont, QImage

from . import config
from .config import Palette
from .utils import mix as _mix

log = logging.getLogger(__name__)

_FONT_STACK = (
    '"Segoe UI Variable Display", "Segoe UI", Inter, "SF Pro Display", '
    '"Noto Sans", Ubuntu, Cantarell, "Helvetica Neue", Arial, sans-serif'
)

_STYLESHEET = Template(
    """
QWidget {
    background: qlineargradient(x1:0 y1:0 x2:0 y2:1,
        stop:0 $bg_hi, stop:1 $bg);
    color: $text; font-size: 13px; font-family: $font_stack;
}
QLabel { background: transparent; }
QLabel[dim="true"] { color: $text_dim; }
QLabel[header="true"] { font-size: 15px; font-weight: 600; }
QLabel[hero="true"] { font-size: 24px; font-weight: 800; color: $text_hi; }
QLabel[shelf="true"] {
    font-size: 17px; font-weight: 700; color: $text_hi; background: transparent;
}
QLabel[kicker="true"] {
    font-size: 11px; font-weight: 700; color: $accent;
    background: transparent;
}

QLineEdit {
    background: $surface_alt; color: $text;
    border: 1px solid $hairline; border-radius: 11px;
    padding: 8px 13px; selection-background-color: $selection;
}
QLineEdit:focus { border: 1px solid $accent; background: $surface_focus; }

QPushButton {
    background: qlineargradient(x1:0 y1:0 x2:0 y2:1,
        stop:0 $surface_hi, stop:1 $surface_alt);
    color: $text;
    border: 1px solid $hairline; border-radius: 10px;
    padding: 7px 13px; font-weight: 600;
}
QPushButton:hover { border: 1px solid $accent; color: $accent_soft; }
QPushButton:pressed { background: $surface; }
QPushButton[accent="true"] {
    background: qlineargradient(x1:0 y1:0 x2:0 y2:1,
        stop:0 $accent_soft, stop:1 $accent);
    color: $bg_solid; border: none; border-radius: 11px; font-weight: 700;
}
QPushButton[accent="true"]:hover {
    background: qlineargradient(x1:0 y1:0 x2:0 y2:1,
        stop:0 $accent, stop:1 $accent_deep);
}
QPushButton[accent="true"]:pressed { background: $accent_deep; }
QPushButton[flat="true"] {
    background: transparent; border: none; color: $text_dim; font-weight: 600;
}
QPushButton[flat="true"]:hover { color: $accent; background: $hover_tint; border-radius: 10px; }
QPushButton[nav="true"] {
    background: transparent; border: none; border-radius: 10px;
    padding: 9px 14px; text-align: left; font-size: 14px; font-weight: 600;
    color: $text_dim;
}
QPushButton[nav="true"]:hover { color: $text; background: $hover_tint; }
QPushButton[nav="true"]:checked {
    color: $text_hi;
    background: qlineargradient(x1:0 y1:0 x2:1 y2:0,
        stop:0 $selection, stop:1 $selection_fade);
    border-left: 3px solid $accent;
}
QPushButton[card="true"] {
    background: qlineargradient(x1:0 y1:0 x2:0 y2:1,
        stop:0 $surface_hi, stop:1 $surface);
    border: 1px solid $hairline; border-radius: 14px;
    padding: 0; text-align: left;
}
QPushButton[card="true"]:hover {
    border: 1px solid $accent;
    background: qlineargradient(x1:0 y1:0 x2:0 y2:1,
        stop:0 $surface_focus, stop:1 $surface_alt);
}

QPushButton[chip="true"] {
    background: transparent; color: $text_dim;
    border: 1px solid $hairline; border-radius: 14px;
    padding: 4px 15px; font-weight: 700;
}
QPushButton[chip="true"]:hover { color: $text; border: 1px solid $accent; }
QPushButton[chip="true"]:checked {
    background: qlineargradient(x1:0 y1:0 x2:0 y2:1,
        stop:0 $accent_soft, stop:1 $accent);
    color: $bg_solid; border: 1px solid $accent;
}

QLabel[tile="true"] {
    background: $surface_alt; border-radius: 12px;
}

QListWidget {
    background: $surface; border: 1px solid $hairline;
    border-radius: 12px; outline: none; padding: 4px;
}
QListWidget::item { border-radius: 9px; padding: 8px; margin: 2px; color: $text; }
QListWidget::item:selected {
    background: qlineargradient(x1:0 y1:0 x2:1 y2:0,
        stop:0 $selection, stop:1 $selection_fade);
    color: $accent_soft;
}
QListWidget::item:hover { background: $hover_tint; }
QListWidget[rows="true"] {
    background: transparent; border: none; border-radius: 0; padding: 0;
}
QListWidget[rows="true"]::item { padding: 4px; margin: 0; border-radius: 10px; }
QListWidget[rows="true"]::item:selected {
    background: qlineargradient(x1:0 y1:0 x2:1 y2:0,
        stop:0 $selection, stop:1 $selection_fade);
    color: $text;
}
QListWidget[sidebar="true"] {
    background: transparent; border: none; padding: 0;
}

QWidget[playerbar="true"] {
    background: qlineargradient(x1:0 y1:0 x2:0 y2:1,
        stop:0 $surface_hi, stop:1 $surface);
    border-top: 1px solid $edge_hi;
}
QWidget[ribbon="true"] {
    background: qlineargradient(x1:0 y1:0 x2:0 y2:1,
        stop:0 $surface_hi, stop:1 $surface);
    border-bottom: 1px solid $edge_hi;
}
QWidget[glass="true"] {
    background: qlineargradient(x1:0 y1:0 x2:0 y2:1,
        stop:0 $surface_focus, stop:1 $surface);
}
QWidget[sidebar="true"] {
    background: transparent;
    border-right: 1px solid $hairline;
}
QFrame[card="true"] {
    background: qlineargradient(x1:0 y1:0 x2:0 y2:1,
        stop:0 $surface_hi, stop:1 $surface);
    border: 1px solid $hairline; border-radius: 14px;
}
QFrame[sidebar="true"] {
    background: transparent; border-right: 1px solid $hairline;
}

QMenu {
    background: $surface_alt; border: 1px solid $edge_hi;
    border-radius: 12px; padding: 7px;
}
QMenu::item { padding: 8px 24px; border-radius: 8px; }
QMenu::item:selected { background: $selection; color: $accent_soft; }
QMenu::separator { height: 1px; background: $hairline; margin: 6px 9px; }

QSlider::groove:horizontal {
    height: 5px; background: $surface_alt; border-radius: 3px;
}
QSlider::sub-page:horizontal {
    background: qlineargradient(x1:0 y1:0 x2:1 y2:0,
        stop:0 $accent_deep, stop:1 $accent);
    border-radius: 3px;
}
QSlider::handle:horizontal {
    width: 14px; height: 14px; margin: -5px 0;
    background: $text_hi; border: 2px solid $accent; border-radius: 7px;
}
QSlider::handle:horizontal:hover { background: $accent_soft; }
QSlider::add-page:horizontal { background: $surface_alt; border-radius: 3px; }

QScrollBar:vertical { background: transparent; width: 9px; margin: 2px; }
QScrollBar::handle:vertical {
    background: $scroll; border-radius: 4px; min-height: 28px;
}
QScrollBar::handle:vertical:hover { background: $accent; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar:horizontal { background: transparent; height: 9px; margin: 2px; }
QScrollBar::handle:horizontal {
    background: $scroll; border-radius: 4px; min-width: 28px;
}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }

QScrollArea { background: transparent; border: none; }

QPlainTextEdit[lyrics="true"] {
    background: qlineargradient(x1:0 y1:0 x2:0 y2:1,
        stop:0 $surface_hi, stop:1 $surface);
    color: $text;
    border: 1px solid $hairline; border-radius: 14px;
    padding: 14px; font-size: 14px; line-height: 150%;
    selection-background-color: $selection;
}

QDockWidget { titlebar-close-icon: none; titlebar-normal-icon: none; }
QDockWidget::title { background: $surface; padding: 8px; border: 1px solid $hairline; }

QToolTip {
    background: $surface_alt; color: $text;
    border: 1px solid $accent; border-radius: 9px; padding: 6px 10px;
}
"""
)


def _rgba(color: str, alpha_pct: int) -> str:
    """#rrggbb + percent alpha → Qt stylesheet rgba() string."""
    r, g, b = int(color[1:3], 16), int(color[3:5], 16), int(color[5:7], 16)
    return f"rgba({r}, {g}, {b}, {alpha_pct}%)"


# ----------------------------------------------------------------- style packs
#
# A palette says *which* colors; a style pack says *how* they're poured —
# opaque gradients, frosted glass panes, a lighter veil, or neon rims.
# Styles are pure token/append transforms, so every palette inherits all
# of them for free.

_RADIUS_RE = re.compile(r"border-radius: (\d+)px")


@dataclass(frozen=True)
class StylePack:
    """A visual language layered over any palette.

    glass        surfaces (and the canvas under a wallpaper) turn translucent
    panel_alpha  surface opacity in glass mode, percent
    radius_delta added to every border-radius (softness dial)
    lift         how much surfaces mix toward the text color (lighter glass)
    rim          accent-tinted edges instead of neutral hairlines
    """

    key: str
    label: str
    blurb: str
    glass: bool = False
    panel_alpha: int = 100
    radius_delta: int = 0
    lift: float = 0.0
    rim: bool = False


STYLES: dict[str, StylePack] = {
    "hearth": StylePack(
        key="hearth", label="Hearth",
        blurb="the classic warm gradients",
    ),
    "glass": StylePack(
        key="glass", label="Frosted Glass",
        blurb="translucent panes, soft rims",
        glass=True, panel_alpha=72, radius_delta=4,
    ),
    "veil": StylePack(
        key="veil", label="Morning Veil",
        blurb="light glass, airy and bright",
        glass=True, panel_alpha=56, radius_delta=6, lift=0.16,
    ),
    "neon": StylePack(
        key="neon", label="Neon Rim",
        blurb="dark glass with glowing edges",
        glass=True, panel_alpha=64, radius_delta=4, rim=True,
    ),
}

DEFAULT_STYLE = "hearth"

# active look — module state so every surface (window, panel, toast,
# overlay) picks it up through build_stylesheet without new plumbing
_style_key: str = DEFAULT_STYLE
_wallpaper_alpha: int | None = None


def set_style(key: str | None) -> None:
    """Choose the active style pack (unknown keys fall back to the default)."""
    global _style_key
    _style_key = key if key in STYLES else DEFAULT_STYLE


def active_style() -> str:
    return _style_key


def set_wallpaper_alpha(alpha: int | None) -> None:
    """How much the UI skin lets a wallpaper glow through (None = no wallpaper)."""
    global _wallpaper_alpha
    _wallpaper_alpha = alpha


def active_wallpaper_alpha() -> int | None:
    return _wallpaper_alpha


def get_style(key: str | None = None) -> StylePack:
    """Look up a style pack by key (None = active), falling back to default."""
    k = key if key in STYLES else (_style_key if _style_key in STYLES else DEFAULT_STYLE)
    return STYLES[k]


def _bump_radii(css: str, delta: int) -> str:
    if delta <= 0:
        return css
    return _RADIUS_RE.sub(lambda m: f"border-radius: {int(m.group(1)) + delta}px", css)


def _rim_css(p: Palette) -> str:
    """Neon Rim: appended rules re-edge the chrome with accent light."""
    edge = _rgba(p.accent, 42)
    hot = _rgba(p.accent_soft, 78)
    return f"""
QFrame[card="true"], QPushButton[card="true"] {{ border: 1px solid {edge}; }}
QPushButton[chip="true"]:checked {{ border: 1px solid {hot}; }}
QPushButton[nav="true"]:checked {{ border-left: 3px solid {p.accent_soft}; }}
QWidget[playerbar="true"] {{ border-top: 1px solid {edge}; }}
QWidget[ribbon="true"] {{ border-bottom: 1px solid {edge}; }}
QLineEdit {{ border: 1px solid {edge}; }}
QLineEdit:focus {{ border: 1px solid {hot}; }}
QToolTip {{ border: 1px solid {hot}; }}
QMenu {{ border: 1px solid {edge}; }}
"""


def build_stylesheet(p: Palette, style_key: str | None = None,
                     wallpaper_alpha: int | None = None) -> str:
    """Compile the runtime stylesheet from a Palette + style pack.

    Both axes are optional: style_key None → the active style; wallpaper
    alpha None → the active wallpaper policy (no translucency when unset).
    Strict on tokens: a missing palette field is an error.
    """
    style = get_style(style_key)
    wa = wallpaper_alpha if wallpaper_alpha is not None else _wallpaper_alpha
    if wa is not None:
        wa = max(config.WALLPAPER_ALPHA_MIN, min(config.WALLPAPER_ALPHA_MAX, wa))

    derived: dict[str, str] = {
        # depth: lift the top of the canvas and surfaces toward the text color
        "bg_hi": _mix(p.bg, p.text, 0.035),
        "surface_hi": _mix(p.surface, p.text, 0.045),
        "surface_focus": _mix(p.surface_alt, p.text, 0.06),
        "text_hi": _mix(p.text, "#ffffff", 0.35),
        # accent ramp for gradient buttons / fills
        "accent_deep": _mix(p.accent, "#000000", 0.28),
        # translucent interaction tints (hover wash, fading selection)
        "hover_tint": _rgba(p.text, 7),
        "selection_fade": _rgba(p.selection, 0),
        # a lighter inner edge that reads as light catching the glass
        "edge_hi": _mix(p.hairline, p.text, 0.14),
        "font_stack": _FONT_STACK,
        # opaque canvas color for text poured onto accents (never translucent)
        "bg_solid": p.bg,
    }

    glass = style.glass or wa is not None
    if glass:
        # the canvas goes translucent only when a wallpaper shines through;
        # panes go translucent whenever the style asks for glass
        root_a = 100
        surf_a = style.panel_alpha if style.glass else 100
        if wa is not None:
            root_a = min(root_a, wa)
            surf_a = min(surf_a, min(96, wa + 10))
        lift = style.lift

        def _pane(color: str) -> str:
            c = _mix(color, p.text, lift) if lift else color
            return _rgba(c, surf_a)

        derived["bg"] = _rgba(p.bg, root_a)
        derived["bg_hi"] = _rgba(_mix(p.bg, p.text, 0.035), root_a)
        derived["surface"] = _pane(p.surface)
        derived["surface_alt"] = _pane(p.surface_alt)
        derived["surface_hi"] = _pane(_mix(p.surface, p.text, 0.045))
        derived["surface_focus"] = _pane(_mix(p.surface_alt, p.text, 0.06))

    css = _STYLESHEET.substitute(
        bg=derived.pop("bg", p.bg), surface=derived.pop("surface", p.surface),
        surface_alt=derived.pop("surface_alt", p.surface_alt),
        hairline=p.hairline, text=p.text, text_dim=p.text_dim,
        accent=p.accent, accent_soft=p.accent_soft, danger=p.danger,
        success=p.success, selection=p.selection, scroll=p.scroll,
        **derived,
    )
    if style.rim:
        css += _rim_css(p)
    return _bump_radii(css, style.radius_delta)


# ----------------------------------------------------------------- wallpaper

def import_wallpaper(src, dest_dir, max_dim: int | None = None) -> str | None:
    """Copy an image into the app's wallpaper store, normalized + downscaled.

    Returns the stored path, or None when the file is missing, not an
    image we can read, or unwritable. The stored name is a content hash,
    so re-importing the same picture never duplicates files.
    """
    src_path = Path(src)
    if not src_path.is_file():
        return None
    if src_path.suffix.lower() not in config.IMAGE_SUFFIXES:
        return None
    try:
        raw = src_path.read_bytes()
    except OSError:
        return None
    img = QImage(str(src_path))
    if img.isNull():
        return None
    limit = max_dim if max_dim is not None else config.WALLPAPER_MAX_DIM
    if max(img.width(), img.height()) > limit:
        img = img.scaled(
            limit, limit,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        if img.isNull():
            return None
    try:
        dest_dir = Path(dest_dir)
        dest_dir.mkdir(parents=True, exist_ok=True)
        ext = ".png" if img.hasAlphaChannel() else ".jpg"
        dest = dest_dir / (hashlib.sha1(raw).hexdigest()[:12] + ext)
        if not dest.exists() and not img.save(str(dest)):
            return None
    except (OSError, RuntimeError):
        return None
    return str(dest)


def remove_wallpaper(path) -> None:
    """Best-effort delete of a stored wallpaper (never raises)."""
    try:
        Path(path).unlink(missing_ok=True)
    except OSError:
        log.info("wallpaper removal failed for %s", path, exc_info=True)


# ----------------------------------------------------------------- palette packs

_PALETTE_PACK_FORMAT = "hearth-palette"


def palette_to_dict(p: Palette) -> dict:
    """A Palette as a portable pack dict ({key, label, color fields})."""
    payload: dict = {"format": _PALETTE_PACK_FORMAT,
                     "key": p.key, "label": p.label}
    for name in p.__dataclass_fields__:
        if name not in ("key", "label"):
            payload[name] = getattr(p, name)
    return payload


def _palette_from_dict(data: dict) -> Palette | None:
    """Rebuild a Palette from a pack dict; None when anything is off."""
    if not isinstance(data, dict):
        return None
    known = {f for f in Palette.__dataclass_fields__ if f != "key"}
    fields = {name: data.get(name) for name in ("key", *known)}
    if any(not isinstance(v, str) for v in fields.values()):
        return None
    try:
        return Palette(**fields)  # type: ignore[arg-type]
    except TypeError:
        return None


def register_custom_palette(pal: Palette) -> str | None:
    """Merge a palette into config.PALETTES at runtime, returning its key.

    Built-in keys are sacred: a colliding import gets a "-2" (then -3, …)
    suffix instead. A key that was itself imported earlier is deduped by
    being replaced in place. Returns None if the palette doesn't validate.
    """
    if config.validate_palette(pal):
        return None
    candidate = pal.key
    if candidate in config.BUILTIN_PALETTE_KEYS:
        n = 1
        while candidate in config.PALETTES:
            n += 1
            candidate = f"{pal.key}-{n}"
    config.PALETTES[candidate] = replace(pal, key=candidate)
    return candidate


def export_palette(key: str, path) -> bool:
    """Write palette `key` to `path` as a JSON pack. False on any trouble."""
    pal = config.PALETTES.get(key)
    if pal is None or config.validate_palette(pal):
        return False
    try:
        payload = json.dumps(palette_to_dict(pal), ensure_ascii=False, indent=2)
        Path(path).write_text(payload, encoding="utf-8")
    except (OSError, TypeError, ValueError):
        log.info("palette export failed for %s", key, exc_info=True)
        return False
    return True


def import_palette(path) -> str | None:
    """Load a JSON palette pack and merge it in. Returns the effective key.

    Never raises: unreadable files, bad JSON, missing fields, or a palette
    that fails config.validate_palette all return None.
    """
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeDecodeError):
        return None
    if not isinstance(data, dict) or data.get("format") not in (None, _PALETTE_PACK_FORMAT):
        return None
    pal = _palette_from_dict(data)
    if pal is None:
        return None
    return register_custom_palette(pal)


# ----------------------------------------------------------------- lyrics type

def lyrics_font(size_key: str, family: str = "") -> QFont:
    """The lyrics typeface: pixel size from the S/M/L presets (unknown key
    falls back to the default), family applied when given."""
    presets = config.LYRICS_SIZE_PRESETS
    px = presets.get(size_key, presets[config.LYRICS_DEFAULT_SIZE_KEY])
    font = QFont()
    font.setPixelSize(px)
    if family:
        font.setFamily(family)
    return font
