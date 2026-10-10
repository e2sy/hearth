# Hearth in Relief — the 3D depth frame

Spotify is a flat 2D poster: panels, no light, no shadows. Hearth locks into 3D.
This document is the frame every depth change must fit — read it before touching
the look. If a change does not serve one of the five principles below, it does
not belong in the UI.

## Why depth works

The eye reads height from exactly three cues: **light direction**, **shadow**,
and **bevel**. Give a surface a bright top lip, a dark under-lip, and a soft
ground shadow, and the brain has no choice — it floats. Take them away and the
same pixels go flat. That is the whole trick; everything else is discipline.

## The five principles

1. **One light source.** Above, slightly forward — firelight. Top edges catch
   light (bright lips), bottom edges fall dark (under-lips). Never mix
   directions; one inconsistent edge breaks the whole room.
2. **Height = shadow.** The closer a layer floats, the wider, softer, and lower
   its shadow. A hard small shadow is a sticker, not a surface.
3. **Depth is quiet.** Gradients are 4–8% luminance shifts across a surface,
   never posters. If a gradient shouts, it is decoration, not depth.
4. **Chrome floats, content breathes.** Hero chrome (player bar, mini player,
   launcher, toast, floating panel) hovers with real drop shadows. The content
   area stays open floor under one spotlight so cards have something to sit on.
5. **Motion confirms height.** Surfaces rise into place (toast), views
   crossfade, hover tilts a card's face toward the light. Stillness is fine;
   wrong-direction motion is not.

## The layer map (bottom → top)

| Layer | Surfaces | Elevation | Treatment |
|---|---|---|---|
| L0 floor | window canvas | — | radial spotlight from the top edge, fading to bg |
| L1 recess | sidebar, view floor | 0 | transparent — shares the floor, hairline separation |
| L2 content | shelf cards, list shells, tiles | E1 | carved faces + soft ground shadow on home shelves |
| L3 floaters | player bar, mini player, launcher, toast, side panel | E2 | floating rounded shells, real drop shadows |
| L4 popovers | menus, tooltips | E3 | lit faces, light rims (native window shadow) |

## Tokens

Colors are always derived from the active `Palette` at compile time (no new
color fields): `canvas_glow`, `canvas_hi` (spotlight stops), `accent_hi` /
`accent_deep` (glossy accent ramp), `surface_deep` / `shadow_edge` (under-lips),
`inset_top` / `inset_bottom` (pressed-in channels), `edge_hi` (light lips).

Geometry and shadow strength live in `config.py`:

- `DEPTH_RADIUS` — corner radius of floating chrome (player bar, mini player).
- `DEPTH_SHADOWS` — the elevation table: `{card, bar, float}` →
  `(blur_radius, y_offset, alpha)` for `effects.add_shadow`.

## Recipes

- **Spotlight canvas** — `qradialgradient` centered at the top of the window:
  `canvas_glow` → `canvas_hi` → `bg`. One rule, the whole floor.
- **Raised face** (cards, buttons, lists, tiles) — vertical `qlineargradient`
  `surface_hi` → `surface`, border `hairline` with `border-top-color: edge_hi`
  and `border-bottom-color: shadow_edge`.
- **Pressed / inset** — flip the face (deep on top) or pour an inset channel
  (`inset_top` → `inset_bottom`) for search fields and slider grooves.
- **Glossy accent** — `accent_hi` → `accent` → `accent_deep` ramp with a white
  top lip; pressed sinks to `accent_deep` → `accent`.
- **Floaters** — `effects.add_shadow` from the `DEPTH_SHADOWS` table + rounded
  QSS shells; frameless windows get real shadows this way.
- **Slider** — inset groove (dark channel with a dark top lip), sub-page in an
  accent ramp, handle a glossy sphere (`qradialgradient` off-center highlight).

## What must not change

Icons, the type scale, layout geometry, palette packs, wallpaper engine, and
every behavior. Depth is a skin poured through the same tokens; the 854-test
suite must stay green and no feature may move.

## Where it lives

- `hearth/config.py` — depth tokens (the elevation table).
- `hearth/theme.py` — the depth stylesheet language (spotlight, carved faces,
  inset channels, glossy accents, 3D sliders).
- `hearth/effects.py` — real drop shadows (`add_shadow`) and motion.
- `hearth/window.py` — floating player bar dock, home shelf card shadows.
- `hearth/minimode.py`, `hearth/panel.py`, `hearth/command_palette.py`,
  `hearth/toast.py` — floater shells.
- `tests/test_depth.py` — pins the tokens and the stylesheet language.
