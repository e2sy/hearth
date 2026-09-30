#!/usr/bin/env python3
"""
generate_3d_assets.py — render animated 3D isometric graphics for this repo.

Creates two SMIL-animated SVGs (no JavaScript, GitHub-camo safe, static-complete):
  docs/assets/3d-banner.svg   wide hero banner with an extruded 3D repo name
  docs/assets/3d-langs.svg    isometric language-stack skyline from live stats

Zero dependencies (stdlib only). Live language data comes from the GitHub REST
API (set GITHUB_TOKEN to raise rate limits; anonymous access also works).

Usage:
  python tools/generate_3d_assets.py                      # this repo (default baked in)
  python tools/generate_3d_assets.py --repo owner/name    # any repo
  python tools/generate_3d_assets.py --generic            # no language data available
"""
import argparse, base64, hashlib, html, json, math, os, sys, urllib.request

DEFAULT_REPO = "qtjg/hearth"

LANG_COLORS = {
    "Python": "#3572A5", "JavaScript": "#f1e05a", "TypeScript": "#3178c6",
    "HTML": "#e34c26", "CSS": "#563d7c", "Shell": "#89e051", "C": "#555555",
    "C++": "#f34b7d", "C#": "#178600", "Go": "#00ADD8", "Rust": "#dea584",
    "Java": "#b07219", "Kotlin": "#A97BFF", "Swift": "#F05138", "PHP": "#4F5D95",
    "Ruby": "#701516", "Dart": "#00B4AB", "Vue": "#41b883",
    "Jupyter Notebook": "#DA5B0B", "Makefile": "#427819", "Dockerfile": "#384d54",
    "PowerShell": "#012456", "Lua": "#000080", "R": "#198CE7", "MATLAB": "#e16737",
    "Scala": "#c22d40", "Haskell": "#5e5086", "Vim script": "#199f4b",
    "CMake": "#DA3434", "Groovy": "#4298b8", "OCaml": "#3be133",
    "Elixir": "#6e4a7e", "Erlang": "#B83998", "Zig": "#ec915c", "Nix": "#7e7eff",
    "Julia": "#a270ba", "Perl": "#0298c3", "Objective-C": "#438eff",
    "Assembly": "#6E4C13", "GDScript": "#355570", "Batchfile": "#C1F12E",
    "HCL": "#844FBA", "SCSS": "#c6538c",
}

FONT = "'Segoe UI',-apple-system,'Helvetica Neue',Arial,sans-serif"


def hue_of(s: str) -> int:
    return int(hashlib.md5(s.encode()).hexdigest(), 16) % 360


def hex_hue(hx: str) -> int:
    hx = hx.lstrip("#")
    r, g, b = (int(hx[i:i + 2], 16) / 255.0 for i in (0, 2, 4))
    mx, mn = max(r, g, b), min(r, g, b)
    d = mx - mn
    if d <= 0:
        return 210
    if mx == r:
        h = ((g - b) / d) % 6
    elif mx == g:
        h = (b - r) / d + 2
    else:
        h = (r - g) / d + 4
    return int(round(h * 60)) % 360


def esc(s) -> str:
    return html.escape(str(s), quote=True)


def uid(repo: str) -> str:
    return hashlib.md5(repo.encode()).hexdigest()[:8]


def HSL(h, s, l):
    """hsl → hex color (maximum renderer compatibility, cairosvg-safe)."""
    h = float(h) % 360.0
    s = min(max(float(s), 0.0), 100.0) / 100.0
    l = min(max(float(l), 0.0), 100.0) / 100.0
    c = (1 - abs(2 * l - 1)) * s
    x = c * (1 - abs((h / 60.0) % 2 - 1))
    m = l - c / 2
    if h < 60:
        r, g, b = c, x, 0
    elif h < 120:
        r, g, b = x, c, 0
    elif h < 180:
        r, g, b = 0, c, x
    elif h < 240:
        r, g, b = 0, x, c
    elif h < 300:
        r, g, b = x, 0, c
    else:
        r, g, b = c, 0, x
    return "#{:02x}{:02x}{:02x}".format(int((r + m) * 255 + .5),
                                        int((g + m) * 255 + .5),
                                        int((b + m) * 255 + .5))


def fetch_json(url):
    req = urllib.request.Request(url, headers={
        "User-Agent": "generate-3d-assets",
        "Accept": "application/vnd.github+json",
    })
    tok = os.environ.get("GITHUB_TOKEN")
    if tok:
        req.add_header("Authorization", "token " + tok)
    with urllib.request.urlopen(req, timeout=25) as r:
        return json.load(r)


def cube(cx, by, w, v, h, sat=58, lit=58, op=1.0):
    """Isometric cube: (cx, by) = bottom vertex; w = half width; v = vertical height."""
    hh = w / 2.0
    c_top = HSL(h, sat, lit)
    c_left = HSL(h, sat, lit * 0.70)
    c_right = HSL(h, sat, lit * 0.50)
    edge = HSL(h, min(sat + 22, 95), min(lit + 26, 92))
    body = (
        f'<polygon points="{cx:.1f},{by - v:.1f} {cx + w:.1f},{by - v - hh:.1f} {cx:.1f},{by - v - 2 * hh:.1f} {cx - w:.1f},{by - v - hh:.1f}" fill="{c_top}" stroke="{edge}" stroke-width="0.8"/>'
        f'<polygon points="{cx - w:.1f},{by - hh:.1f} {cx:.1f},{by:.1f} {cx:.1f},{by - v:.1f} {cx - w:.1f},{by - v - hh:.1f}" fill="{c_left}"/>'
        f'<polygon points="{cx:.1f},{by:.1f} {cx + w:.1f},{by - hh:.1f} {cx + w:.1f},{by - v - hh:.1f} {cx:.1f},{by - v:.1f}" fill="{c_right}"/>'
    )
    if op < 1:
        body = f'<g opacity="{op}">{body}</g>'
    return body


def floater(inner, dur, delay, amp=6):
    return (f'<g><animateTransform attributeName="transform" type="translate" '
            f'values="0 0; 0 {-amp}; 0 0" dur="{dur}s" begin="{delay}s" '
            f'repeatCount="indefinite" calcMode="spline" '
            f'keySplines="0.45 0 0.55 1; 0.45 0 0.55 1" keyTimes="0;0.5;1"/>{inner}</g>')


def shine(W, H, dur=7.0, op=0.055):
    return (f'<g clip-path="url(#clip)"><polygon points="0,0 150,0 60,{H} -90,{H}" '
            f'fill="#ffffff" opacity="{op}">'
            f'<animateTransform attributeName="transform" type="translate" '
            f'from="-260 0" to="{W + 260} 0" dur="{dur}s" repeatCount="indefinite"/>'
            f'</polygon></g>')


def banner_svg(repo, desc, h):
    name = repo.split("/", 1)[1]
    W, H = 880, 240
    u = uid(repo + "-banner")
    maxw = 600.0
    fs = int(min(58.0, maxw / (0.62 * max(len(name), 1))))
    cx, ty = W / 2, 126

    d = (desc or "").strip()
    if len(d) > 72:
        d = d[:71].rstrip() + "…"

    cubes = [
        floater(cube(86, 196, 36, 70, h), 5.2, 0.0, 6),
        floater(cube(64, 226, 26, 42, (h + 18) % 360), 6.1, 0.7, 5),
        floater(cube(112, 152, 22, 28, (h - 24) % 360, lit=62), 5.7, 1.4, 7),
        floater(cube(794, 200, 38, 76, (h + 30) % 360), 5.5, 0.4, 6),
        floater(cube(816, 228, 26, 44, (h - 38) % 360), 6.4, 1.1, 5),
        floater(cube(768, 154, 22, 30, (h + 8) % 360, lit=62), 5.9, 1.8, 7),
        floater(cube(252, 58, 14, 18, (h + 44) % 360, lit=60, op=0.85), 6.8, 0.3, 8),
        floater(cube(632, 52, 13, 16, (h - 46) % 360, lit=60, op=0.85), 7.3, 1.5, 8),
    ]

    layers = []
    for i in (6, 5, 4, 3, 2, 1):
        layers.append(
            f'<text x="{cx + i}" y="{ty + i}" font-family="{FONT}" font-size="{fs}" '
            f'font-weight="800" text-anchor="middle" fill="{HSL(h, 45, 9 + i)}">{esc(name)}</text>'
        )
    layers.append(
        f'<text x="{cx}" y="{ty}" font-family="{FONT}" font-size="{fs}" font-weight="800" '
        f'text-anchor="middle" fill="url(#lg{u})" letter-spacing="1">{esc(name)}</text>'
    )

    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" role="img" aria-label="{esc(repo)} 3D banner">
<defs>
<linearGradient id="bg{u}" x1="0" y1="0" x2="0" y2="1">
<stop offset="0" stop-color="{HSL(h, 32, 7)}"/>
<stop offset="1" stop-color="{HSL(h, 36, 14)}"/>
</linearGradient>
<linearGradient id="lg{u}" x1="0" y1="0" x2="0" y2="1">
<stop offset="0" stop-color="{HSL(h, 88, 74)}"/>
<stop offset="1" stop-color="{HSL((h + 34) % 360, 92, 58)}"/>
</linearGradient>
<clipPath id="clip"><rect width="{W}" height="{H}"/></clipPath>
</defs>
<rect width="{W}" height="{H}" fill="url(#bg{u})"/>
<ellipse cx="100" cy="232" rx="96" ry="15" fill="{HSL(h, 70, 55)}" opacity="0.18">
<animate attributeName="opacity" values="0.12;0.26;0.12" dur="5s" repeatCount="indefinite"/>
</ellipse>
<ellipse cx="792" cy="236" rx="100" ry="15" fill="{HSL((h + 30) % 360, 70, 55)}" opacity="0.18">
<animate attributeName="opacity" values="0.12;0.26;0.12" dur="5s" begin="1.2s" repeatCount="indefinite"/>
</ellipse>
{''.join(cubes)}
<line x1="0" y1="206.5" x2="{W}" y2="206.5" stroke="{HSL(h, 40, 60)}" stroke-opacity="0.14"/>
{''.join(layers)}
<text x="{cx}" y="164" font-family="{FONT}" font-size="15" text-anchor="middle" fill="{HSL(h, 18, 78)}" opacity="0.92" letter-spacing="0.5">{esc(d)}</text>
<text x="{cx}" y="206" font-family="{FONT}" font-size="12" font-weight="600" text-anchor="middle" fill="{HSL(h, 30, 64)}" opacity="0.85" letter-spacing="3">{esc(repo)}</text>
{shine(W, H)}
<rect x="0" y="0" width="{W}" height="3" fill="url(#lg{u})" opacity="0.9"/>
<rect x="0" y="{H - 4}" width="{W}" height="4" fill="{HSL(h, 50, 42)}" opacity="0.55"/>
</svg>'''


def _platform_y(cx, x0=60, xm=440, x1=820, y0=270, dy=68):
    if cx <= xm:
        return y0 - (cx - x0) / (xm - x0) * dy
    return y0 - (x1 - cx) / (x1 - xm) * dy


def langs_svg(repo, pairs, h, generic=False):
    name = repo.split("/", 1)[1]
    W, H = 880, 360
    u = uid(repo + "-langs")
    title = "PROJECT STACK" if generic else "LANGUAGE STACK"

    n = len(pairs)
    pmax = max(p for _, p in pairs) or 1.0
    cubes, labels = [], []
    tallest_v, tallest_x, tallest_by = -1, 440, 232
    for i, (lname, pct) in enumerate(pairs):
        cx = 190 + i * (560.0 / (n - 1)) if n > 1 else 440
        v = 22 + (pct / pmax) ** 0.55 * 80
        w = 48
        by = _platform_y(cx) + 2
        chex = LANG_COLORS.get(lname)
        ch = hex_hue(chex) if chex else hue_of(lname)
        cubes.append(cube(cx, by, w, v, ch, sat=62, lit=56))
        if v > tallest_v:
            tallest_v, tallest_x, tallest_by = v, cx, by
        words = lname.split(" ")
        if len(lname) > 11 and len(words) > 1:
            mid = len(words) // 2
            l1, l2 = " ".join(words[:mid]), " ".join(words[mid:])
            labels.append(
                f'<text x="{cx:.0f}" y="{by + 30:.0f}" font-family="{FONT}" font-size="13" font-weight="600" text-anchor="middle" fill="#c9d6e8">{esc(l1)}</text>'
                f'<text x="{cx:.0f}" y="{by + 46:.0f}" font-family="{FONT}" font-size="13" font-weight="600" text-anchor="middle" fill="#c9d6e8">{esc(l2)}</text>'
                f'<text x="{cx:.0f}" y="{by + 66:.0f}" font-family="{FONT}" font-size="14" font-weight="800" text-anchor="middle" fill="{HSL(ch, 80, 72)}">{pct:.1f}%</text>'
            )
        else:
            labels.append(
                f'<text x="{cx:.0f}" y="{by + 30:.0f}" font-family="{FONT}" font-size="13" font-weight="600" text-anchor="middle" fill="#c9d6e8">{esc(lname)}</text>'
                f'<text x="{cx:.0f}" y="{by + 50:.0f}" font-family="{FONT}" font-size="14" font-weight="800" text-anchor="middle" fill="{HSL(ch, 80, 72)}">{pct:.1f}%</text>'
            )

    plat = (f'<polygon points="60,270 440,202 820,270 440,338" fill="{HSL(h, 26, 12)}" '
            f'stroke="{HSL(h, 40, 60)}" stroke-opacity="0.35" stroke-width="1.2"/>'
            f'<polygon points="60,270 440,202 820,270 440,338" fill="none" stroke="{HSL(h, 60, 70)}" '
            f'stroke-opacity="0.10" stroke-width="6"/>')

    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" role="img" aria-label="{esc(repo)} 3D language stack">
<defs>
<linearGradient id="bg{u}" x1="0" y1="0" x2="0" y2="1">
<stop offset="0" stop-color="{HSL(h, 32, 7)}"/>
<stop offset="1" stop-color="{HSL(h, 36, 13)}"/>
</linearGradient>
<clipPath id="clip"><rect width="{W}" height="{H}"/></clipPath>
</defs>
<rect width="{W}" height="{H}" fill="url(#bg{u})"/>
<text x="44" y="48" font-family="{FONT}" font-size="15" font-weight="800" letter-spacing="5" fill="{HSL(h, 30, 82)}">{title}</text>
<text x="44" y="70" font-family="{FONT}" font-size="12" letter-spacing="2" fill="{HSL(h, 15, 60)}">{esc(repo)}</text>
<ellipse cx="{tallest_x:.0f}" cy="{tallest_by + 8:.0f}" rx="64" ry="11" fill="{HSL(h, 70, 55)}" opacity="0.20">
<animate attributeName="opacity" values="0.12;0.30;0.12" dur="4s" repeatCount="indefinite"/>
</ellipse>
{plat}
{''.join(cubes)}
{''.join(labels)}
{shine(W, H, dur=8.0, op=0.045)}
<rect x="0" y="0" width="{W}" height="3" fill="{HSL(h, 70, 60)}" opacity="0.85"/>
<rect x="0" y="{H - 4}" width="{W}" height="4" fill="{HSL(h, 50, 42)}" opacity="0.5"/>
</svg>'''


GENERIC_STACK = [("core", 30.0), ("api", 24.0), ("tools", 20.0), ("tests", 14.0), ("docs", 12.0)]


def main():
    ap = argparse.ArgumentParser(description="Render 3D isometric banner + language stack SVGs")
    ap.add_argument("--repo", default=DEFAULT_REPO, help="owner/name (default baked for this repo)")
    ap.add_argument("--desc", default="", help="repo description for the banner subtitle")
    ap.add_argument("--langs-json", default=None, help="path to JSON {language: bytes}; omit to fetch live")
    ap.add_argument("--generic", action="store_true", help="force generic project stack")
    ap.add_argument("--outdir", default="docs/assets")
    args = ap.parse_args()
    if not args.repo:
        sys.exit("error: --repo is required (or run the copy baked into tools/generate_3d_assets.py)")

    h = hue_of(args.repo)
    os.makedirs(args.outdir, exist_ok=True)

    pairs = None
    if not args.generic:
        data = {}
        if args.langs_json and args.langs_json != "none":
            with open(args.langs_json) as f:
                data = json.load(f)
        else:
            try:
                data = fetch_json(f"https://api.github.com/repos/{args.repo}/languages")
            except Exception:
                data = {}
        total = sum(data.values())
        if total > 0:
            items = sorted(data.items(), key=lambda kv: -kv[1])
            top, rest = items[:6], items[6:]
            pairs = [(k, v * 100.0 / total) for k, v in top]
            if rest:
                pairs.append(("Other", sum(v for _, v in rest) * 100.0 / total))
    if not pairs:
        pairs = GENERIC_STACK

    b = banner_svg(args.repo, args.desc, h)
    l = langs_svg(args.repo, pairs, h, generic=(pairs is GENERIC_STACK))
    p1 = os.path.join(args.outdir, "3d-banner.svg")
    p2 = os.path.join(args.outdir, "3d-langs.svg")
    with open(p1, "w") as f:
        f.write(b)
    with open(p2, "w") as f:
        f.write(l)
    print(p1)
    print(p2)


if __name__ == "__main__":
    main()
