"""Builds Widgets/PUSpin.ttf: a font whose digits 0-9 are ten frames of a dot orbiting a ring.

A Live Activity can't loop an animation, but Text(timerInterval:) ticks every second on its own. Drawn in this
font and clipped to its last character (the seconds' units digit), the timer becomes an endless 1 fps spinner
that needs no pushes. The colon has no width and no outline, so only digits take space.
Run with a Python that has fonttools and shapely:  python ios/scripts/make_spinner_font.py
"""
import math
import os

from fontTools.fontBuilder import FontBuilder
from fontTools.pens.ttGlyphPen import TTGlyphPen
from shapely.geometry import LineString, Point
from shapely.geometry.polygon import orient
from shapely.ops import unary_union

EM = 1000
C = EM / 2
R = 440  # the orbit, just inside the em square


def frame(k):
    """Frame k of 10: a comet (a fading-width arc ending in a dot) at 36 * k degrees, clockwise from the top."""
    head = 90 - 36 * k  # degrees, counterclockwise from 3 o'clock; clockwise motion
    parts = [Point(C + R * math.cos(math.radians(head)), C + R * math.sin(math.radians(head))).buffer(62, quad_segs=12)]
    for i in range(1, 9):  # the tail: shrinking dots behind the head
        a = math.radians(head + 9 * i)
        parts.append(Point(C + R * math.cos(a), C + R * math.sin(a)).buffer(62 - 6.5 * i, quad_segs=10))
    return unary_union(parts)


def draw(geom):
    pen = TTGlyphPen(None)
    for poly in getattr(geom, "geoms", [geom]):
        poly = orient(poly, -1.0)  # TrueType: outer contours clockwise (y up)
        for ring in [poly.exterior, *poly.interiors]:
            pts = [(round(x), round(y)) for x, y in list(ring.coords)[:-1]]
            pen.moveTo(pts[0])
            for p in pts[1:]:
                pen.lineTo(p)
            pen.closePath()
    return pen.glyph()


def main():
    names = [".notdef", "space", "colon"] + [f"frame{k}" for k in range(10)]
    fb = FontBuilder(EM, isTTF=True)
    fb.setupGlyphOrder(names)
    cmap = {ord(" "): "space", ord(":"): "colon", **{ord(str(k)): f"frame{k}" for k in range(10)}}
    fb.setupCharacterMap(cmap)
    empty = TTGlyphPen(None).glyph()
    glyphs = {".notdef": empty, "space": empty, "colon": empty, **{f"frame{k}": draw(frame(k)) for k in range(10)}}
    fb.setupGlyf(glyphs)
    fb.setupHorizontalMetrics({n: (0 if n == "colon" else EM, 0) for n in names})
    fb.setupHorizontalHeader(ascent=EM, descent=0)
    fb.setupNameTable({"familyName": "PUSpin", "styleName": "Regular", "psName": "PUSpin-Regular"})
    fb.setupOS2(sTypoAscender=EM, sTypoDescender=0, sTypoLineGap=0, usWinAscent=EM, usWinDescent=0)
    fb.setupPost()
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "Widgets", "PUSpin.ttf")
    fb.save(out)
    print("wrote", os.path.normpath(out))


if __name__ == "__main__":
    main()
