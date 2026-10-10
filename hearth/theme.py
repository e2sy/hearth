"""Stylesheets, palette packs, and lyrics typography.

The relief layer (docs/UI-DEPTH.md): one light from above, surfaces in
heights. The canvas wears a spotlight; cards and buttons are carved faces
with bright top lips and dark under-lips; fields and slider grooves are
pressed-in channels; the accent pours as a glossy ramp. All extra tones
are derived from the Palette at compile time, so every theme inherits the
depth without new color tokens.

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
    background: qradialgradient(cx: 0.5, cy: 0.04, radius: 1.45,
        stop: 0 $canvas_glow, stop: 0.45 $canvas_hi, stop: 1 $bg);
    color: $text; font-size: 13px; font-family: $font_stack;
}
QLabel { background: transparent; }
QLabel[dim="true"] { color: $text_dim; }
QLabel[header="true"] { font-size: 15px; font-weight: 600; letter-spacing: 0.2px; }
QLabel[hero="true"] { font-size: 22px; font-weight: 700; color: $text_hi; letter-spacing: -0.2px; }
QLabel[shelf="true"] {
    font-size: 15px; font-weight: 650; color: $text_hi; background: transparent;
    letter-spacing: 0.2px;
}
QLabel[kicker="true"] {
    font-size: 10px; font-weight: 700; color: $accent;
    background: transparent; letter-spacing: 1.4px;
}
QLabel[wordmark="true"] { font-size: 19px; font-weight: 750; color: $text_hi; letter-spacing: -0.3px; }

QLineEdit {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop: 0 $inset_top, stop: 0.3 $surface_alt, stop: 1 $surface_alt);
    color: $text;
    border: 1px solid $shadow_edge; border-bottom-color: $edge_hi;
    border-radius: 8px;
    padding: 8px 12px; selection-background-color: $selection;
}
QLineEdit:hover { border: 1px solid $text_dim; border-bottom-color: $edge_hi; }
QLineEdit:focus { border: 1px solid $accent; border-bottom-color: $accent; }

QPushButton {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop: 0 $surface_alt_hi, stop: 1 $surface_alt);
    color: $text;
    border: 1px solid $hairline; border-top-color: $edge_hi; border-bottom-color: $shadow_edge;
    border-radius: 8px;
    padding: 7px 13px; font-weight: 600;
}
QPushButton:hover {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop: 0 $surface_focus, stop: 1 $surface_alt);
}
QPushButton:pressed {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop: 0 $surface_deep, stop: 1 $surface_alt);
    border-top-color: $shadow_edge; border-bottom-color: $edge_hi;
}
QPushButton[accent="true"] {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop: 0 $accent_hi, stop: 0.45 $accent, stop: 1 $accent_deep);
    color: $bg_solid;
    border: 1px solid $accent_deep; border-top-color: $lip_light;
    border-radius: 8px; font-weight: 700;
}
QPushButton[accent="true"]:hover {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop: 0 $accent_soft, stop: 0.45 $accent, stop: 1 $accent_deep);
}
QPushButton[accent="true"]:pressed {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop: 0 $accent_deep, stop: 1 $accent);
    border-top-color: $shadow_edge;
}
QPushButton[flat="true"] {
    background: transparent; border: none; color: $text_dim; font-weight: 600;
}
QPushButton[flat="true"]:hover { color: $text; background: $hover_tint; border-radius: 8px; }
QPushButton[nav="true"] {
    background: transparent; border: none; border-radius: 8px;
    padding: 8px 12px; text-align: left; font-size: 13px; font-weight: 600;
    color: $text_dim;
}
QPushButton[nav="true"]:hover { color: $text; background: $hover_tint; }
QPushButton[nav="true"]:checked {
    color: $text_hi;
    background: $selection;
}
QPushButton[card="true"] {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop: 0 $surface_hi, stop: 1 $surface);
    border: 1px solid $hairline; border-top-color: $edge_hi; border-bottom-color: $shadow_edge;
    border-radius: 12px;
    padding: 0; text-align: left;
}
QPushButton[card="true"]:hover {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop: 0 $surface_focus, stop: 1 $surface_alt);
    border: 1px solid $accent; border-top-color: $accent_soft;
}

QPushButton[chip="true"] {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop: 0 $surface_alt_hi, stop: 1 $surface_alt);
    color: $text_dim;
    border: 1px solid $hairline; border-top-color: $edge_hi; border-bottom-color: $shadow_edge;
    border-radius: 999px;
    padding: 4px 14px; font-weight: 600;
}
QPushButton[chip="true"]:hover { color: $text; border: 1px solid $accent; border-top-color: $accent_soft; background: $hover_tint; }
QPushButton[chip="true"]:checked {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop: 0 $accent_hi, stop: 1 $accent);
    color: $bg_solid; border: 1px solid $accent_deep; border-top-color: $lip_light;
}

QLabel[tile="true"] {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop: 0 $surface_alt_hi, stop: 1 $surface);
    border: 1px solid $hairline; border-top-color: $edge_hi; border-bottom-color: $shadow_edge;
    border-radius: 10px;
}

QListWidget {
    background: $surface;
    border: 1px solid $hairline; border-top-color: $edge_hi; border-bottom-color: $shadow_edge;
    border-radius: 10px; outline: none; padding: 4px;
}
QListWidget::item { border-radius: 7px; padding: 8px; margin: 1px; color: $text; }
QListWidget::item:selected {
    background: $selection;
    color: $accent_soft;
}
QListWidget::item:hover { background: $hover_tint; }
QListWidget[rows="true"] {
    background: transparent; border: none; border-radius: 0; padding: 0;
}
QListWidget[rows="true"]::item { padding: 4px; margin: 0; border-radius: 8px; }
QListWidget[rows="true"]::item:selected {
    background: $selection;
    color: $text;
}
QListWidget[sidebar="true"] {
    background: transparent; border: none; padding: 0;
}

QWidget[playerbar="true"] {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop: 0 $surface_hi, stop: 0.14 $surface, stop: 1 $surface_deep);
    border: 1px solid $hairline; border-top-color: $edge_hi;
    border-radius: ${bar_radius}px;
}
QWidget[ribbon="true"] {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop: 0 $surface_hi, stop: 1 $surface);
    border-bottom: 1px solid $hairline;
}
QWidget[glass="true"] {
    background: $surface;
}
QWidget[sidebar="true"] {
    background: transparent;
    border-right: 1px solid $hairline;
}
QFrame[card="true"] {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop: 0 $surface_hi, stop: 1 $surface);
    border: 1px solid $hairline; border-top-color: $edge_hi; border-bottom-color: $shadow_edge;
    border-radius: 12px;
}
QFrame[sidebar="true"] {
    background: transparent; border-right: 1px solid $hairline;
}

QMenu {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop: 0 $surface_alt_hi, stop: 1 $surface_alt);
    border: 1px solid $edge_hi; border-top-color: $lip_light;
    border-radius: 10px; padding: 6px;
}
QMenu::item { padding: 7px 22px; border-radius: 6px; }
QMenu::item:selected { background: $selection; color: $accent_soft; }
QMenu::separator { height: 1px; background: $hairline; margin: 5px 8px; }

QSlider::groove:horizontal {
    height: 5px; border-radius: 3px;
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop: 0 $inset_top, stop: 1 $inset_bottom);
    border-top: 1px solid $lip_shade; border-bottom: 1px solid $lip_soft;
}
QSlider::sub-page:horizontal {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop: 0 $accent_soft, stop: 1 $accent);
    border-radius: 2px;
}
QSlider::handle:horizontal {
    width: 12px; height: 12px; margin: -4px 0;
    background: qradialgradient(cx: 0.35, cy: 0.3, radius: 0.85,
        stop: 0 #ffffff, stop: 0.5 $text_hi, stop: 1 $surface_alt_hi);
    border: 1px solid $shadow_edge; border-radius: 6px;
}
QSlider::handle:horizontal:hover {
    background: qradialgradient(cx: 0.35, cy: 0.3, radius: 0.85,
        stop: 0 #ffffff, stop: 0.5 $accent_soft, stop: 1 $accent);
    border: 1px solid $accent_deep;
}
QSlider::add-page:horizontal { background: $inset_bottom; border-radius: 2px; }

QScrollBar:vertical { background: transparent; width: 8px; margin: 2px; }
QScrollBar::handle:vertical {
    background: $scroll; border-radius: 4px; min-height: 28px;
}
QScrollBar::handle:vertical:hover { background: $text_dim; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar:horizontal { background: transparent; height: 8px; margin: 2px; }
QScrollBar::handle:horizontal {
    background: $scroll; border-radius: 4px; min-width: 28px;
}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }

QScrollArea { background: transparent; border: none; }

QPlainTextEdit[lyrics="true"] {
    background: $surface;
    color: $text;
    border: 1px solid $hairline; border-top-color: $edge_hi; border-bottom-color: $shadow_edge;
    border-radius: 12px;
    padding: 14px; font-size: 14px; line-height: 150%;
    selection-background-color: $selection;
}

QDockWidget { titlebar-close-icon: none; titlebar-normal-icon: none; }
QDockWidget::title { background: $surface; padding: 8px; border: 1px solid $hairline; }

QToolTip {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop: 0 $surface_alt_hi, stop: 1 $surface_alt);
    color: $text;
    border: 1px solid $accent; border-top-color: $lip_light;
    border-radius: 7px; padding: 5px 9px;
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
        # the spotlight floor: one warm light from above, falling back to bg
        "canvas_glow": _mix(p.bg, p.accent, 0.07),
        "canvas_hi": _mix(p.bg, p.text, 0.045),
        # depth: lift the top of surfaces toward the text color, sink the base
        "bg_hi": _mix(p.bg, p.text, 0.035),
        "surface_hi": _mix(p.surface, p.text, 0.045),
        "surface_focus": _mix(p.surface_alt, p.text, 0.06),
        "surface_deep": _mix(p.surface, "#000000", 0.24),
        "surface_alt_hi": _mix(p.surface_alt, p.text, 0.05),
        "inset_top": _mix(p.bg, "#000000", 0.30),
        "inset_bottom": _mix(p.surface, "#000000", 0.10),
        "text_hi": _mix(p.text, "#ffffff", 0.35),
        # accent ramp for glossy buttons / fills
        "accent_deep": _mix(p.accent, "#000000", 0.28),
        "accent_hi": _mix(p.accent, "#ffffff", 0.22),
        # translucent interaction tints (hover wash, fading selection)
        "hover_tint": _rgba(p.text, 7),
        "hover_tint2": _rgba(p.text, 12),
        "selection_fade": _rgba(p.selection, 0),
        # a lighter inner edge that reads as light catching the glass
        "edge_hi": _mix(p.hairline, p.text, 0.14),
        # carved-edge lips: light catches the top, shade pools underneath
        "shadow_edge": _mix(p.surface, "#000000", 0.32),
        "lip_light": _rgba("#ffffff", 55),
        "lip_soft": _rgba("#ffffff", 14),
        "lip_shade": _rgba("#000000", 55),
        # floating chrome geometry
        "bar_radius": str(config.DEPTH_RADIUS),
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
        # depth tones follow their parents into the glass
        derived["canvas_glow"] = _rgba(_mix(p.bg, p.accent, 0.07), root_a)
        derived["canvas_hi"] = _rgba(_mix(p.bg, p.text, 0.045), root_a)
        derived["surface_deep"] = _pane(_mix(p.surface, "#000000", 0.24))
        derived["surface_alt_hi"] = _pane(_mix(p.surface_alt, p.text, 0.05))
        derived["inset_top"] = _pane(_mix(p.bg, "#000000", 0.30))
        derived["inset_bottom"] = _pane(_mix(p.surface, "#000000", 0.10))

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
