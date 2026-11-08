#!/usr/bin/env python3
"""Draws the app icon: a phone outline with a pointer. Needs Pillow."""
import sys
from PIL import Image, ImageDraw

S = 1024
img = Image.new("RGB", (S, S))
d = ImageDraw.Draw(img)
for y in range(S):  # vertical gradient, dark teal to near black
    t = y / S
    d.line([(0, y), (S, y)], fill=(int(20 + 10 * (1 - t)), int(90 * (1 - t) + 30), int(110 * (1 - t) + 45)))
# phone outline
d.rounded_rectangle([302, 132, 722, 892], radius=86, outline=(255, 255, 255), width=40)
d.rounded_rectangle([452, 182, 572, 216], radius=17, fill=(255, 255, 255))  # island
# pointer arrow, tip at the centre of the screen
tip = (468, 400)
arrow = [(0, 0), (0, 300), (72, 232), (124, 344), (174, 322), (122, 212), (218, 212)]
pts = [(tip[0] + x, tip[1] + y) for x, y in arrow]
d.polygon([(x + 10, y + 14) for x, y in pts], fill=(0, 30, 40))  # shadow
d.polygon(pts, fill=(80, 220, 255), outline=(255, 255, 255), width=14)
img.save(sys.argv[1])
