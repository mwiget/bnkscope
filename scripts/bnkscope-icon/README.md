# bnkscope mark

The Kubernetes heptagon as an oscilloscope bezel, with a triggered sweep in F5
red running behind falling code rain. `build.py` is the source of truth —
everything under `frontend-v2/public/icons/` is generated, so edit the script
and re-run rather than hand-patching an `.svg`.

```bash
python3 scripts/bnkscope-icon/build.py         # the four SVG builds
python3 scripts/bnkscope-icon/build.py --png   # + PNG rasterizations
```

PNG export drives a headless chromium (`chromium`, `chromium-browser`,
`google-chrome`, or the playwright cache). Override with
`BNKSCOPE_CHROME=/path/to/chrome`.

## Builds

| File | Where it is used |
|---|---|
| `bnkscope.svg` | Default. App header, favicon, anything 32 px and up. |
| `bnkscope-small.svg` | 32 px and below. No rain, no blur filters, no node dots — they turn to mud; strokes are thicker and the wave is pulled clear of the bezel. |
| `bnkscope-maskable.svg` | Android/PWA adaptive icon. Full-bleed, every drawn pixel inside the 80 %-diameter safe circle. Never use it in the UI — it has no corner radius of its own. |
| `bnkscope-mono.svg` | Single colour via `currentColor`. Toolbars, print, monochrome favicons, terminal-adjacent UI. |

PNGs land in `png/`, all with a transparent background: full build at
1024–32, trimmed at 32/24/16 (`-small`), maskable at 512/192 (`-maskable`).

## Wiring

`frontend-v2/index.html` still points at the bnk-forge `favicon.svg`. When
bnkscope takes over the shell:

```html
<link rel="icon" href="/icons/bnkscope.svg" type="image/svg+xml">
<link rel="alternate icon" href="/icons/png/bnkscope-32-small.png" sizes="32x32">
<link rel="icon" href="/icons/png/bnkscope-16-small.png" sizes="16x16">
<link rel="apple-touch-icon" href="/icons/png/bnkscope-180.png">
```

Manifest, if one gets added:

```json
"icons": [
  { "src": "/icons/png/bnkscope-192.png", "sizes": "192x192", "type": "image/png" },
  { "src": "/icons/png/bnkscope-512.png", "sizes": "512x512", "type": "image/png" },
  { "src": "/icons/png/bnkscope-512-maskable.png", "sizes": "512x512", "type": "image/png", "purpose": "maskable" }
]
```

The beam path carries `class="beam"` and `pathLength="100"`, so the trace can be
swept on mount:

```css
.appbar .beam { animation: sweep 900ms cubic-bezier(.4, 0, .2, 1); }
@keyframes sweep { from { stroke-dashoffset: 100 } to { stroke-dashoffset: 0 } }
```

## Palette

`#E4002B` F5 red (bezel, beam) · `#FF3355` trigger burst · `#FF6A00` phosphor
tail · `#0A0C10` screen · `#22272E` housing.

Geometry knobs in `build.py`: `trace_path(x0, x1, mid, amp, cycles, decay)` for
the sweep, `rain(seed, cols, ...)` for the code rain, `poly(7, ...)` for the
heptagon.
