"""Draws PhoneUse's custom SF Symbols and writes them as symbol templates to Shared/Symbols.xcassets.

Each icon is built from simple shapes on a 100 x 100 grid (y down) with shapely, then placed as the Regular-M
variant of an SF Symbols template, so Xcode treats it as a symbol: it takes the font size and weight's scale, and
it's monochrome so tint works. Run with a Python that has shapely:  python ios/scripts/make_symbols.py
"""
import json
import math
import os

from shapely.geometry import LineString, Point, Polygon, box
from shapely.geometry.polygon import orient
from shapely.ops import unary_union

W = 8  # stroke width, legible at Dynamic Island size (about 18 pt)


def rrect(x0, y0, x1, y1, r):
    return box(x0 + r, y0 + r, x1 - r, y1 - r).buffer(r, quad_segs=16)


def ring(x0, y0, x1, y1, r, w=W):
    return rrect(x0, y0, x1, y1, r).difference(rrect(x0 + w, y0 + w, x1 - w, y1 - w, max(r - w, 1)))


def line(points, w=W):
    return LineString(points).buffer(w / 2, quad_segs=16)


def arc(cx, cy, r, a0, a1, w=W, n=40):
    """An arc stroke; angles in degrees, counterclockwise as seen on screen (0 = right, 90 = up)."""
    pts = [(cx + r * math.cos(math.radians(a)), cy - r * math.sin(math.radians(a)))
           for a in [a0 + (a1 - a0) * i / n for i in range(n + 1)]]
    return line(pts, w)


def phone(x0, y0, x1, y1, w=W):
    return ring(x0, y0, x1, y1, (x1 - x0) * 0.24, w)


def hand(cx, top, s=1.0):
    """A raised open hand; `top` is the palm's top edge, fingers reach above it."""
    def p(x, y):
        return (cx + x * s, top + y * s)
    fw = 7.5 * s
    palm = rrect(*p(-16, -1), *p(16, 27), 9 * s)
    fingers = [line([p(x, 2), p(x, y)], fw) for x, y in ((-11.5, -22), (-3.8, -28), (3.8, -26), (11.5, -18))]
    thumb = line([p(-12, 16), p(-24, 2)], fw)
    return unary_union([palm, thumb, *fingers])


def gap(base, top, g=4.5):
    """Cuts a gap into `base` around `top`, so overlapping shapes stay readable at small sizes."""
    return unary_union([base.difference(top.buffer(g)), top])


def sparkle(cx, cy, r, k=2.4):
    pts = []
    for i in range(160):
        t = 2 * math.pi * i / 160
        c, s = math.cos(t), math.sin(t)
        pts.append((cx + r * math.copysign(abs(c) ** k, c), cy - r * math.copysign(abs(s) ** k, s)))
    return Polygon(pts)


def question(cx, cy, r):
    pts = [(cx + r * math.cos(math.radians(a)), cy - r * math.sin(math.radians(a)))
           for a in range(180, -61, -10)]
    end = pts[-1]
    stem = [(cx + 1, end[1] + 4), (cx, cy + r + 6)]
    return unary_union([line(pts + stem, 7), Point(cx, cy + r + 15).buffer(4.6, quad_segs=16)])


def symbols():
    out = {}
    # You're in control: a phone with your hand on it.
    out["pu.idle"] = gap(phone(8, 4, 56, 96), hand(68, 52, 1.0))
    # The agent asks to start: a raised hand with a question mark.
    out["pu.asking"] = unary_union([hand(40, 44, 1.25), question(80, 18, 10)])
    # Tapping: a pointer with a tap ripple at its tip.
    cursor = Polygon([(38, 36), (38, 90), (51, 77), (61, 98), (71, 93), (61, 73), (79, 72)]).buffer(2, quad_segs=8)
    ripples = unary_union([arc(38, 36, 15, 60, 210, 6.5), arc(38, 36, 28, 70, 200, 6.5)])
    out["pu.tapping"] = gap(ripples, cursor, 3)
    # Reading: a viewfinder scanning a phone.
    corners = unary_union([line([(6, 28), (6, 6), (28, 6)]), line([(72, 6), (94, 6), (94, 28)]),
                           line([(6, 72), (6, 94), (28, 94)]), line([(72, 94), (94, 94), (94, 72)])])
    out["pu.reading"] = unary_union([corners, gap(phone(33, 22, 67, 78, 7), line([(20, 50), (80, 50)], 6.5), 3)])
    # Thinking: sparkles.
    out["pu.thinking"] = unary_union([sparkle(42, 58, 40), sparkle(82, 18, 15)])
    # You took over: a phone with pause bars, your hand on it.
    bars = unary_union([rrect(20, 24, 28, 58, 3.5), rrect(35, 24, 43, 58, 3.5)])
    out["pu.paused"] = gap(unary_union([phone(6, 4, 58, 96), bars]), hand(76, 66, 0.78))
    return out


def svg_path(geom):
    polys = getattr(geom, "geoms", [geom])
    d = []
    for poly in polys:
        poly = orient(poly, 1.0)
        for ring_ in [poly.exterior, *poly.interiors]:
            pts = list(ring_.coords)[:-1]
            d.append("M" + " L".join(f"{x:.2f} {y:.2f}" for x, y in pts) + " Z")
    return " ".join(d)


# SF Symbols template 3.0 geometry: Regular-M sits on the medium baseline; cap height is about 70.5 units.
BASELINE_M, CAPLINE_M = 1126.0, 1055.54


def template(geom):
    x0, y0, x1, y1 = geom.bounds
    scale = 0.95  # 100 grid units -> 95 template units: a little taller than the cap height, like system symbols
    mid = (BASELINE_M + CAPLINE_M) / 2
    left = 1400.0
    tx = left - x0 * scale
    ty = mid - 50 * scale
    path = svg_path(geom)
    right = left + (x1 - x0) * scale
    return f'''<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE svg PUBLIC "-//W3C//DTD SVG 1.1//EN" "http://www.w3.org/Graphics/SVG/1.1/DTD/svg11.dtd">
<!--Generator: ios/scripts/make_symbols.py-->
<svg version="1.1" xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" width="3300" height="2200">
 <g id="Notes">
  <rect height="2200" id="artboard" style="fill:white;opacity:1" width="3300" x="0" y="0"/>
  <text id="template-version" style="stroke:none;fill:black;font-family:sans-serif;font-size:13" x="3036" y="1933">Template v.3.0</text>
 </g>
 <g id="Guides">
  <line id="Baseline-S" style="fill:none;stroke:#27AAE1;opacity:1;stroke-width:0.5;" x1="263" x2="3036" y1="696" y2="696"/>
  <line id="Capline-S" style="fill:none;stroke:#27AAE1;opacity:1;stroke-width:0.5;" x1="263" x2="3036" y1="625.541" y2="625.541"/>
  <line id="Baseline-M" style="fill:none;stroke:#27AAE1;opacity:1;stroke-width:0.5;" x1="263" x2="3036" y1="{BASELINE_M}" y2="{BASELINE_M}"/>
  <line id="Capline-M" style="fill:none;stroke:#27AAE1;opacity:1;stroke-width:0.5;" x1="263" x2="3036" y1="{CAPLINE_M}" y2="{CAPLINE_M}"/>
  <line id="Baseline-L" style="fill:none;stroke:#27AAE1;opacity:1;stroke-width:0.5;" x1="263" x2="3036" y1="1556" y2="1556"/>
  <line id="Capline-L" style="fill:none;stroke:#27AAE1;opacity:1;stroke-width:0.5;" x1="263" x2="3036" y1="1485.54" y2="1485.54"/>
  <line id="left-margin-Regular-M" style="fill:none;stroke:#00AEEF;stroke-width:0.5;opacity:1.0;" x1="{left - 4:.2f}" x2="{left - 4:.2f}" y1="1030.79" y2="1150.12"/>
  <line id="right-margin-Regular-M" style="fill:none;stroke:#00AEEF;stroke-width:0.5;opacity:1.0;" x1="{right + 4:.2f}" x2="{right + 4:.2f}" y1="1030.79" y2="1150.12"/>
 </g>
 <g id="Symbols">
  <g id="Regular-M">
   <path d="{path}" transform="matrix({scale} 0 0 {scale} {tx:.2f} {ty:.2f})"/>
  </g>
 </g>
</svg>
'''


def main():
    root = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "Shared", "Symbols.xcassets")
    os.makedirs(root, exist_ok=True)
    with open(os.path.join(root, "Contents.json"), "w") as f:
        json.dump({"info": {"author": "xcode", "version": 1}}, f, indent=2)
    for name, geom in symbols().items():
        d = os.path.join(root, name + ".symbolset")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, name + ".svg"), "w") as f:
            f.write(template(geom))
        with open(os.path.join(d, "Contents.json"), "w") as f:
            json.dump({"info": {"author": "xcode", "version": 1},
                       "symbols": [{"filename": name + ".svg", "idiom": "universal"}]}, f, indent=2)
        print(name, [round(v) for v in geom.bounds])


if __name__ == "__main__":
    main()
