#!/usr/bin/env python3
"""Build the bnkscope mark.

Geometry lives in this file; every .svg and .png under
frontend-v2/public/icons/ is a generated artifact — edit here, then re-run.

    python3 scripts/bnkscope-icon/build.py         # SVGs only
    python3 scripts/bnkscope-icon/build.py --png   # SVGs + PNG rasterizations

PNG export drives a headless chromium. Set BNKSCOPE_CHROME if it is not on PATH.
"""
import base64
import glob
import math
import os
import random
import re
import shutil
import subprocess
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
OUT = os.path.join(ROOT, "frontend-v2", "public", "icons") + os.sep
PNG = os.path.join(OUT, "png") + os.sep
# The app-bar mark is inlined into the DOM rather than loaded through <img>,
# because an <img>-hosted SVG is style-isolated and the beam sweep is a CSS
# animation on a path inside it. Vite can only `?raw`-import from src/, so the
# same generated SVGs are mirrored there. public/ stays the favicon source.
SRC = os.path.join(ROOT, "frontend-v2", "src", "assets", "icons") + os.sep

# ---------- palette (F5) ----------
RED      = "#E4002B"   # F5 primary red
RED_HOT  = "#FF3355"
ORANGE   = "#FF6A00"
GREEN    = "#00D68F"   # matrix phosphor accent
INK      = "#0A0C10"
BEZEL_A  = "#22272E"
BEZEL_B  = "#0B0E12"

def trace_path(x0, x1, mid, amp, cycles, phase=0.0, decay=2.6, rise=0.18, step=0.5):
    """Triggered scope pulse: flat -> burst -> damped ring-out."""
    pts = []
    x = x0
    span = x1 - x0
    while x <= x1 + 1e-9:
        t = (x - x0) / span
        # envelope: fast attack, exponential decay, flat lead-in
        if t < rise:
            env = 0.0 if t < rise * 0.45 else (t - rise * 0.45) / (rise * 0.55)
        else:
            env = math.exp(-decay * (t - rise))
        y = mid - amp * env * math.sin(2 * math.pi * cycles * (t - rise * 0.45) + phase)
        pts.append((x, y))
        x += step
    d = "M{:.2f} {:.2f}".format(*pts[0])
    for p in pts[1:]:
        d += "L{:.2f} {:.2f}".format(*p)
    return d

def poly(n, cx, cy, r, rot=0.0):
    return [(cx + r*math.cos(rot + 2*math.pi*i/n - math.pi/2),
             cy + r*math.sin(rot + 2*math.pi*i/n - math.pi/2)) for i in range(n)]

def rain(seed, cols, y0, y1, color, base_op=0.55, w=1.5, glyph=1.9, gap=0.8):
    """Font-independent 'code rain': columns of short dashes fading upward."""
    rnd = random.Random(seed)
    out = []
    for cx in cols:
        head = rnd.uniform(y0 + 6, y1)
        length = rnd.randint(7, 13)
        for i in range(length):
            y = head - i * (glyph + gap)
            if y < y0 - glyph or y > y1:
                continue
            op = base_op * (1 - i / length) ** 1.15
            if i == 0:
                op = min(0.95, base_op * 1.9)
            h = glyph if rnd.random() > 0.25 else glyph * 0.55
            out.append(
                f'<rect x="{cx:.1f}" y="{y:.1f}" width="{w}" height="{h:.1f}" rx="{w/2:.1f}" '
                f'fill="{color}" opacity="{op:.2f}"/>'
            )
    return "\n      ".join(out)

DEFS = f"""
  <defs>
    <linearGradient id="bezel" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="{BEZEL_A}"/><stop offset="1" stop-color="{BEZEL_B}"/>
    </linearGradient>
    <linearGradient id="edge" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="{RED_HOT}" stop-opacity=".85"/>
      <stop offset=".55" stop-color="{RED}" stop-opacity=".35"/>
      <stop offset="1" stop-color="{ORANGE}" stop-opacity=".55"/>
    </linearGradient>
    <linearGradient id="beam" x1="0" y1="0" x2="1" y2="0">
      <stop offset="0" stop-color="{RED}" stop-opacity=".30"/>
      <stop offset=".20" stop-color="{RED_HOT}" stop-opacity="1"/>
      <stop offset=".58" stop-color="{RED}" stop-opacity="1"/>
      <stop offset="1" stop-color="{ORANGE}" stop-opacity=".50"/>
    </linearGradient>
    <radialGradient id="crt" cx=".5" cy=".38" r=".75">
      <stop offset="0" stop-color="#151A20"/><stop offset="1" stop-color="{INK}"/>
    </radialGradient>
    <filter id="glow" x="-60%" y="-60%" width="220%" height="220%">
      <feGaussianBlur stdDeviation="0.9" result="b"/>
      <feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge>
    </filter>
    <filter id="softglow" x="-60%" y="-60%" width="220%" height="220%">
      <feGaussianBlur stdDeviation="2.2"/>
    </filter>
  </defs>"""

DEFS = f"""
  <defs>
    <linearGradient id="bezel" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="{BEZEL_A}"/><stop offset="1" stop-color="{BEZEL_B}"/>
    </linearGradient>
    <linearGradient id="edge" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="{RED_HOT}" stop-opacity=".85"/>
      <stop offset=".55" stop-color="{RED}" stop-opacity=".35"/>
      <stop offset="1" stop-color="{ORANGE}" stop-opacity=".55"/>
    </linearGradient>
    <linearGradient id="beam" x1="0" y1="0" x2="1" y2="0">
      <stop offset="0" stop-color="{RED}" stop-opacity=".30"/>
      <stop offset=".20" stop-color="{RED_HOT}" stop-opacity="1"/>
      <stop offset=".58" stop-color="{RED}" stop-opacity="1"/>
      <stop offset="1" stop-color="{ORANGE}" stop-opacity=".50"/>
    </linearGradient>
    <radialGradient id="crt" cx=".5" cy=".38" r=".75">
      <stop offset="0" stop-color="#151A20"/><stop offset="1" stop-color="{INK}"/>
    </radialGradient>
    <filter id="glow" x="-60%" y="-60%" width="220%" height="220%">
      <feGaussianBlur stdDeviation="0.9" result="b"/>
      <feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge>
    </filter>
    <filter id="softglow" x="-60%" y="-60%" width="220%" height="220%">
      <feGaussianBlur stdDeviation="2.2"/>
    </filter>
  </defs>"""

# ================= C: kubernetes heptagon =================
hept = poly(7, 32, 32.6, 22.5)
hept_d = "M" + "L".join(f"{x:.2f} {y:.2f}" for x, y in hept) + "Z"
hept_in = poly(7, 32, 32.6, 19.2)
hept_in_d = "M" + "L".join(f"{x:.2f} {y:.2f}" for x, y in hept_in) + "Z"
nodes = "".join(f'<circle cx="{x:.2f}" cy="{y:.2f}" r="1.9" fill="{INK}" stroke="{RED_HOT}" stroke-width="1.1"/>'
                for x, y in hept)

# ========== C-small: trimmed for 24px and below ==========
# No rain, no graticule, no blur filters, flat fills, fatter strokes: the
# heptagon silhouette and one beam are all that survive at that size anyway.
hept_mono = poly(7, 32, 32.6, 24.0)
hept_mono_d = "M" + "L".join(f"{x:.2f} {y:.2f}" for x, y in hept_mono) + "Z"
hept_clip_mono = poly(7, 32, 32.6, 21.2)
hept_clip_mono_d = "M" + "L".join(f"{x:.2f} {y:.2f}" for x, y in hept_clip_mono) + "Z"

hept_s = poly(7, 32, 32.6, 23.0)
hept_s_d = "M" + "L".join(f"{x:.2f} {y:.2f}" for x, y in hept_s) + "Z"
hept_clip = poly(7, 32, 32.6, 20.6)
hept_clip_d = "M" + "L".join(f"{x:.2f} {y:.2f}" for x, y in hept_clip) + "Z"

C_SMALL = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" width="64" height="64" role="img" aria-label="bnkscope">
  <title>bnkscope</title>
  <defs>
    <linearGradient id="beam" x1="0" y1="0" x2="1" y2="0">
      <stop offset="0" stop-color="{RED_HOT}"/>
      <stop offset=".55" stop-color="{RED_HOT}"/>
      <stop offset="1" stop-color="{ORANGE}"/>
    </linearGradient>
    <clipPath id="scr"><path d="{hept_clip_d}"/></clipPath>
  </defs>
  <rect x="2" y="2" width="60" height="60" rx="14" fill="#15181D"/>
  <path d="{hept_s_d}" fill="{INK}"/>
  <g clip-path="url(#scr)">
    <path d="{trace_path(15, 48, 33.0, 7.2, 1.75, decay=1.8)}" fill="none" stroke="url(#beam)"
          stroke-width="4.0" stroke-linecap="round" stroke-linejoin="round"/>
  </g>
  <path d="{hept_s_d}" fill="none" stroke="{RED}" stroke-width="2.6" stroke-linejoin="round"/>
</svg>
"""


C_CORE = f"""  <clipPath id="scrC"><path d="{hept_in_d}"/></clipPath>
  <path d="{hept_in_d}" fill="url(#crt)"/>
  <g clip-path="url(#scrC)">
      {rain(3, [17.0, 21.4, 25.8, 30.2, 34.6, 39.0, 43.4], 10, 54, RED_HOT, base_op=.30)}
    <path d="{trace_path(12.5, 51.5, 32.6, 9.2, 2.5, decay=2.3)}" fill="none" stroke="{RED}" stroke-opacity=".45"
          stroke-width="3.2" stroke-linecap="round" stroke-linejoin="round" filter="url(#softglow)"/>
    <path d="{trace_path(12.5, 51.5, 32.6, 9.2, 2.5, decay=2.3)}" fill="none" stroke="url(#beam)"
          stroke-width="2.3" stroke-linecap="round" stroke-linejoin="round" filter="url(#glow)"/>
  </g>
  <path d="{hept_in_d}" fill="none" stroke="#fff" stroke-opacity=".10" stroke-width="1"/>
  <path d="{hept_d}" fill="none" stroke="{RED}" stroke-opacity=".75" stroke-width="1.6"
        stroke-linejoin="round"/>
  {nodes}"""

C = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" width="64" height="64" role="img" aria-label="bnkscope">
  <title>bnkscope</title>{DEFS}
  <rect x="2" y="2" width="60" height="60" rx="15" fill="url(#bezel)"/>
  <rect x="2.6" y="2.6" width="58.8" height="58.8" rx="14.4" fill="none" stroke="url(#edge)" stroke-width="1.2"/>
{C_CORE}
</svg>
"""

# ========== C-maskable: Android adaptive icon ==========
# Full-bleed square (the launcher supplies the shape) with every drawn pixel
# inside the 80%-diameter safe circle: the mark is scaled to .84 about its own
# centre, which puts the outermost node dot at r=21.4 against a safe r=25.6.
C_MASK = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" width="64" height="64" role="img" aria-label="bnkscope">
  <title>bnkscope</title>{DEFS}
  <radialGradient id="field" cx=".5" cy=".42" r=".78">
    <stop offset="0" stop-color="#1A1F26"/><stop offset="1" stop-color="#0A0C10"/>
  </radialGradient>
  <rect width="64" height="64" fill="url(#field)"/>
  <g transform="translate(32 32.6) scale(.84) translate(-32 -32.6)">
{C_CORE}
  </g>
</svg>
"""

# ========== C-mono: single-colour fallback ==========
# Inherits currentColor, no fills, no filters: toolbars, print, monochrome
# favicons, anywhere the red-on-black build cannot go.
C_MONO = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" width="64" height="64" fill="none"
     stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" role="img" aria-label="bnkscope">
  <title>bnkscope</title>
  <clipPath id="scrM"><path d="{hept_clip_mono_d}"/></clipPath>
  <path d="{hept_mono_d}" stroke-width="3"/>
  <g clip-path="url(#scrM)">
    <path d="{trace_path(15, 48, 33.0, 7.2, 1.75, decay=1.8)}" stroke-width="4.5"/>
  </g>
</svg>
"""



def finalize(svg, pfx):
    """Namespace ids so several icons can be inlined on one page; tag the live beam."""
    ids = re.findall(r'id="([^"]+)"', svg)
    for i in ids:
        svg = svg.replace(f'id="{i}"', f'id="{pfx}-{i}"')
        svg = svg.replace(f'url(#{i})', f'url(#{pfx}-{i})')
    svg = svg.replace('stroke="url(#%s-beam)"' % pfx,
                      'class="beam" pathLength="100" stroke="url(#%s-beam)"' % pfx)
    return re.sub(r'\n\s*\n', '\n', svg)


BUILDS = [("bnkscope.svg", C, "bs"),
          ("bnkscope-small.svg", C_SMALL, "bss"),
          ("bnkscope-maskable.svg", C_MASK, "bsm"),
          ("bnkscope-mono.svg", C_MONO, "bsn")]

# full detail down to 32px; the trimmed cut takes over at 32 and below
RASTER = [("bnkscope.svg", s, "") for s in (1024, 512, 256, 192, 180, 128, 96, 64, 48, 32)] + \
         [("bnkscope-small.svg", s, "-small") for s in (32, 24, 16)] + \
         [("bnkscope-maskable.svg", s, "-maskable") for s in (512, 192)]


def find_chrome():
    env = os.environ.get("BNKSCOPE_CHROME")
    if env:
        return env
    for name in ("chromium", "chromium-browser", "google-chrome", "chrome"):
        found = shutil.which(name)
        if found:
            return found
    cached = sorted(glob.glob(os.path.expanduser(
        "~/.cache/ms-playwright/chromium*/chrome-*linux64/chrome*")))
    return cached[-1] if cached else None


def rasterize(chrome):
    os.makedirs(PNG, exist_ok=True)
    shim = os.path.join(OUT, ".build-shim.html")
    for src, size, tag in RASTER:
        uri = "data:image/svg+xml;base64," + base64.b64encode(
            open(OUT + src, "rb").read()).decode()
        with open(shim, "w") as fh:
            fh.write(f'<style>html,body{{margin:0;padding:0;background:transparent}}'
                     f'img{{display:block;width:{size}px;height:{size}px}}</style>'
                     f'<img src="{uri}" alt="">')
        out = f"{PNG}bnkscope-{size}{tag}.png"
        subprocess.run([chrome, "--headless", "--no-sandbox", "--disable-gpu",
                        "--hide-scrollbars", "--default-background-color=00000000",
                        "--force-device-scale-factor=1", f"--window-size={size},{size}",
                        f"--screenshot={out}", shim], check=True, capture_output=True)
        print("  " + os.path.relpath(out, ROOT))
    os.remove(shim)


def main():
    os.makedirs(OUT, exist_ok=True)
    os.makedirs(SRC, exist_ok=True)
    for name, svg, pfx in BUILDS:
        rendered = finalize(svg, pfx)
        for directory in (OUT, SRC):
            with open(directory + name, "w") as fh:
                fh.write(rendered)
            print("  " + os.path.relpath(directory + name, ROOT))
    if "--png" in sys.argv:
        chrome = find_chrome()
        if not chrome:
            sys.exit("no chromium found — set BNKSCOPE_CHROME=/path/to/chrome")
        rasterize(chrome)


if __name__ == "__main__":
    main()
