"""Draws robot icon candidates for the driving state and renders a preview sheet.

Each candidate is a 100 x 100 grid drawing (y down) with two poses, built from shapely shapes at a stroke weight
(Regular, Semibold, Bold). The primary layer is solid; the secondary layer is drawn at 45% opacity, the way
SF Symbols' hierarchical rendering draws it. Usage:
    python ios/scripts/robot_candidates.py OUT.png
"""
import math
import sys

from PIL import Image, ImageDraw, ImageFont
from shapely.geometry import LineString, Point, Polygon, box
from shapely.ops import unary_union

WEIGHTS = {"Regular": 8.0, "Semibold": 9.5, "Bold": 11.0}
IN_RING = 0.58  # the glyph's size inside the ring; today's icons use 0.45, the ring leaves about 0.70 clear


def rrect(x0, y0, x1, y1, r):
    return box(x0 + r, y0 + r, x1 - r, y1 - r).buffer(r, quad_segs=16)


def line(pts, w):
    return LineString(pts).buffer(w / 2, quad_segs=16)


def head(x0, y0, x1, y1, w, look=0.0, tilt=0.0):
    """A solid rounded head with two round eyes cut out and an antenna. look shifts the eyes down (0..1); tilt leans
    the antenna (degrees, positive to the right)."""
    r = (x1 - x0) * 0.24
    solid = rrect(x0, y0, x1, y1, r)
    cx, h = (x0 + x1) / 2, y1 - y0
    ey = y0 + h * (0.46 + 0.12 * look)
    er = max(w * 0.62, h * 0.11)
    eyes = unary_union([Point(x0 + (x1 - x0) * 0.32, ey).buffer(er, quad_segs=16),
                        Point(x0 + (x1 - x0) * 0.68, ey).buffer(er, quad_segs=16)])
    t = math.radians(tilt)
    tip = (cx + math.sin(t) * h * 0.22, y0 - math.cos(t) * h * 0.22)
    ball = (cx + math.sin(t) * h * 0.27, y0 - math.cos(t) * h * 0.27)
    antenna = unary_union([line([(cx, y0 + 1), tip], w * 0.8), Point(*ball).buffer(w * 0.95, quad_segs=16)])
    ears = unary_union([rrect(x0 - w * 1.1, y0 + h * 0.36, x0 + 1, y0 + h * 0.66, w * 0.5),
                        rrect(x1 - 1, y0 + h * 0.36, x1 + w * 1.1, y0 + h * 0.66, w * 0.5)])
    return unary_union([solid.difference(eyes), antenna]), ears


def cursor(tipx, tipy, s):
    pts = [(0, 0), (0, 46), (11, 35), (19, 52), (27, 48), (19, 32), (34, 32)]
    return Polygon([(tipx + x * s, tipy + y * s) for x, y in pts]).buffer(1.2, quad_segs=6)


def ripple(cx, cy, r, w):
    pts = [(cx + r * math.cos(math.radians(a)), cy - r * math.sin(math.radians(a))) for a in range(30, 151, 6)]
    return line(pts, w * 0.7)


def candidates(w):
    """name -> [(primary, secondary) for pose 0 (idle) and pose 1 (tap)]"""
    out = {}
    # A: head only. The tap pose glances down.
    out["A  head"] = [head(16, 30, 84, 88, w, 0.0, 0), head(16, 30, 84, 88, w, 1.0, 22)]
    # B: head with an arm reaching out to the lower right; the tap pose lowers it, with a tap ripple.
    p0, s0 = head(8, 26, 62, 72, w)
    arm_up = line([(62, 58), (80, 50), (90, 40)], w)
    arm_dn = line([(62, 58), (80, 66), (90, 80)], w)
    out["B  head + arm"] = [(unary_union([p0, arm_up]), s0),
                            (unary_union([p0, arm_dn]), unary_union([s0, ripple(90, 92, 9, w)]))]
    # C: head with a small cursor; the tap pose moves the cursor down with a ripple.
    p0, s0 = head(6, 24, 60, 70, w)
    out["C  head + cursor"] = [(unary_union([p0, cursor(66, 40, 0.62)]), s0),
                               (unary_union([p0, cursor(66, 52, 0.62)]), unary_union([s0, ripple(66, 50, 9, w)]))]
    return out


def render_glyph(prim, sec, px, color):
    k = 8
    big = Image.new("RGBA", (px * k, px * k), (0, 0, 0, 0))
    d = ImageDraw.Draw(big)
    sc = px * k / 100

    def fill(g, rgba):
        for poly in getattr(g, "geoms", [g]):
            d.polygon([(x * sc, y * sc) for x, y in poly.exterior.coords], fill=rgba)
            for hole in poly.interiors:
                d.polygon([(x * sc, y * sc) for x, y in hole.coords], fill=(0, 0, 0, 0))

    fill(sec, color + (115,))
    fill(prim, color + (255,))
    return big.resize((px, px), Image.LANCZOS)


def render_ring(px, color, frame=3):
    """The app's ring: a 0.72 trim with a fading tail, turned 45 degrees per frame (a still frame of it)."""
    k = 8
    big = Image.new("RGBA", (px * k, px * k), (0, 0, 0, 0))
    d = ImageDraw.Draw(big)
    lw = max(2, px * 0.09) * k
    pad = px * 0.06 * k + lw / 2
    n = 90
    for i in range(n):
        a0 = -90 + frame * 45 + 360 * 0.72 * i / n
        a1 = -90 + frame * 45 + 360 * 0.72 * (i + 1) / n + 0.5
        alpha = int(255 * (0.05 + 0.95 * min(1, i / n * 360 * 0.72 / 260)))
        d.arc([pad, pad, px * k - pad, px * k - pad], a0, a1, fill=color + (alpha,), width=int(lw))
    return big.resize((px, px), Image.LANCZOS)


def main(out):
    P = 3  # pixels per point, like the phone
    blue = (10, 132, 255)
    font = ImageFont.truetype("/System/Library/Fonts/SFNS.ttf", 17 * P)
    font.set_variation_by_name("Semibold")
    small = ImageFont.truetype("/System/Library/Fonts/SFNS.ttf", 13 * P)
    small.set_variation_by_name("Regular")
    cands = candidates(WEIGHTS["Semibold"])
    row_h, W = 120 * P, 1400 * P
    sheet = Image.new("RGB", (W, row_h * len(cands) + 60 * P), "black")
    d = ImageDraw.Draw(sheet)
    d.text((16 * P, 14 * P), "Robot candidates, Semibold. Left to right: expanded card (ring 44 pt), pose 1 and tap pose; "
           "compact island (ring 22 pt), both poses; the glyph alone at 17 pt and 28 pt, both poses; "
           "Regular / Semibold / Bold at 28 pt.", font=small, fill=(160, 160, 165))
    for r, (name, poses) in enumerate(cands.items()):
        y = 60 * P + r * row_h
        d.text((16 * P, y), name, font=small, fill=(160, 160, 165))
        x = 16 * P
        for pose in poses:  # card size: ring 44, glyph 0.45 * 44 = 20 pt, with the title
            ring = render_ring(44 * P, blue)
            glyph = render_glyph(*pose, int(44 * IN_RING * P), blue)
            yc = y + 26 * P
            sheet.paste(ring, (x, yc), ring)
            off = (44 * P - glyph.width) // 2
            sheet.paste(glyph, (x + off, yc + off), glyph)
            d.text((x + 56 * P, yc + 4 * P), "Agent is tapping", font=font, fill="white")
            d.text((x + 56 * P, yc + 25 * P), "Opening Settings · 3 steps", font=small, fill=(150, 150, 155))
            x += 250 * P
        for pose in poses:  # compact: ring 22, glyph 10 pt
            ring = render_ring(22 * P, blue)
            glyph = render_glyph(*pose, int(22 * IN_RING * P), blue)
            yc = y + 37 * P
            sheet.paste(ring, (x, yc), ring)
            off = (22 * P - glyph.width) // 2
            sheet.paste(glyph, (x + off, yc + off), glyph)
            x += 40 * P
        x += 20 * P
        for pt in (17, 28):
            for pose in poses:
                glyph = render_glyph(*pose, pt * P, blue)
                sheet.paste(glyph, (x, y + 48 * P - pt * P // 2), glyph)
                x += (pt + 14) * P
            x += 10 * P
        x += 10 * P
        for wname, wv in WEIGHTS.items():
            prim, sec = candidates(wv)[name][0]
            glyph = render_glyph(prim, sec, 28 * P, blue)
            sheet.paste(glyph, (x, y + 34 * P), glyph)
            d.text((x, y + 66 * P), wname, font=small, fill=(110, 110, 115))
            x += 74 * P
    sheet.save(out)
    print("wrote", out, sheet.size)


if __name__ == "__main__":
    main(sys.argv[1])
