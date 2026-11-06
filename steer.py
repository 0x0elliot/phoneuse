#!/usr/bin/python
"""Find and steer the iPhone's AssistiveTouch pointer using the mirror window.

Positions are fractions of the phone screen: (0, 0) top-left, (1, 1) bottom-right.
The mirror window shows the whole phone screen, so a fraction of the window is
the same fraction of the phone.
"""
import io
import json
import socket
import subprocess
import time

import numpy as np
from PIL import Image

SOCK_PATH = "/run/iphone-hid.sock"


def _find_hyprland():
    # tmux servers started before a Hyprland restart keep a stale signature, so
    # hyprctl fails (exit 4). Use the saved one only if its socket answers;
    # otherwise the newest instance whose socket does.
    import glob, os
    run = os.environ.get("XDG_RUNTIME_DIR", "/run/user/%d" % os.getuid())

    def alive(sock):
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            s.connect(sock)
            return True
        except OSError:
            return False
        finally:
            s.close()

    sig = os.environ.get("HYPRLAND_INSTANCE_SIGNATURE")
    if sig and alive(os.path.join(run, "hypr", sig, ".socket.sock")):
        return
    socks = sorted(glob.glob(os.path.join(run, "hypr", "*", ".socket.sock")), key=os.path.getmtime, reverse=True)
    for sock in socks:
        if alive(sock):
            os.environ["HYPRLAND_INSTANCE_SIGNATURE"] = os.path.basename(os.path.dirname(sock))
            return


_find_hyprland()


class Hid:
    def __init__(self):
        import threading
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.connect(SOCK_PATH)
        self.f = self.sock.makefile()
        self.lock = threading.Lock()

    def cmd(self, line):
        with self.lock:
            self.sock.sendall((line + "\n").encode())
            reply = self.f.readline().strip()
        if not reply.startswith("ok"):
            raise RuntimeError(reply)
        return reply

    def rel(self, dx, dy, buttons=0):
        self.cmd(f"m {dx} {dy} 0 {buttons}")


def mirror_window():
    for c in json.loads(subprocess.check_output(["hyprctl", "clients", "-j"])):
        if c["class"] == "uxplay":
            return c["at"], c["size"]
    raise RuntimeError("mirror window not found")


PHONE_ASPECT = 1206 / 2622  # iPhone 17 Pro screen, width / height


def picture_rect(at, size):
    """Where the phone picture sits inside the mirror window (centered, aspect-fit)."""
    (x, y), (w, h) = at, size
    if w / h < PHONE_ASPECT:
        pw, ph = w, w / PHONE_ASPECT
    else:
        pw, ph = h * PHONE_ASPECT, h
    return x + (w - pw) / 2, y + (h - ph) / 2, pw, ph


def grab_png():
    """PNG bytes of just the phone picture (not the frame strips)."""
    x, y, w, h = picture_rect(*mirror_window())
    return subprocess.check_output(["grim", "-g", f"{round(x)},{round(y)} {round(w)}x{round(h)}", "-"])


def grab():
    """Phone picture as a float32 grayscale array (physical pixels)."""
    png = grab_png()
    return np.asarray(Image.open(io.BytesIO(png)).convert("L"), dtype=np.float32)


def blobs(a, b, thresh=18):
    """Centroids (fractions) of changed regions between two frames, largest first."""
    d = np.abs(a - b) > thresh
    if not d.any():
        return []
    h, w = d.shape
    # coarse connected components on a downsampled grid
    cell = 6
    g = d[: h // cell * cell, : w // cell * cell].reshape(h // cell, cell, w // cell, cell).any(axis=(1, 3))
    seen = np.zeros_like(g)
    out = []
    for sy, sx in zip(*np.nonzero(g)):
        if seen[sy, sx]:
            continue
        stack, pts = [(sy, sx)], []
        seen[sy, sx] = True
        while stack:
            cy, cx = stack.pop()
            pts.append((cy, cx))
            for ny, nx in ((cy + 1, cx), (cy - 1, cx), (cy, cx + 1), (cy, cx - 1)):
                if 0 <= ny < g.shape[0] and 0 <= nx < g.shape[1] and g[ny, nx] and not seen[ny, nx]:
                    seen[ny, nx] = True
                    stack.append((ny, nx))
        ys, xs = zip(*pts)
        out.append((len(pts), (np.mean(xs) + 0.5) * cell / w, (np.mean(ys) + 0.5) * cell / h))
    out.sort(reverse=True)
    return [(fx, fy, n) for n, fx, fy in out]


def corner(hid):
    for _ in range(40):
        hid.rel(-127, -127)
        time.sleep(0.006)


def walk(hid, ux, uy, step=2, delay=0.012):
    """Move by (ux, uy) HID units in small, evenly paced steps."""
    n = max(abs(ux), abs(uy)) // step + 1
    sent_x = sent_y = 0
    for i in range(1, n + 1):
        tx, ty = round(ux * i / n), round(uy * i / n)
        if tx != sent_x or ty != sent_y:
            hid.rel(tx - sent_x, ty - sent_y)
            sent_x, sent_y = tx, ty
        time.sleep(delay)


# Measured 2026-11-06 with walk(step=2, delay=8 ms): ~4.1 pt per HID unit across,
# ~4.0 pt down (iPhone 17 Pro, 402x874 pt). As fractions of the screen per unit:
GAIN_X = 0.0103
GAIN_Y = 0.00455
MIRROR_LAG = 0.5  # seconds the AirPlay picture trails the phone


def find_pointer(before, after, near, radius=0.15):
    """Pointer position: the changed region closest to where we expect it."""
    best = None
    for x, y, n in blobs(before, after):
        if n < 6:
            continue
        d = ((x - near[0]) ** 2 + ((y - near[1]) * 2.17) ** 2) ** 0.5  # 2.17 = aspect
        if d < radius and (best is None or d < best[0]):
            best = (d, x, y)
    return best[1:] if best else None


def settled_pointer(baseline, near, timeout=1.5):
    """Wait for the mirror to catch up, then return the pointer's position."""
    time.sleep(MIRROR_LAG * 0.8)
    last, t0 = None, time.time()
    while time.time() - t0 < timeout:
        p = find_pointer(baseline, grab(), near)
        if p and last and abs(p[0] - last[0]) < 0.006 and abs(p[1] - last[1]) < 0.004:
            return p
        last = p
    return last


def go_to(hid, fx, fy, tol=0.015):
    """Put the pointer at (fx, fy). Returns where it was last seen (or None)."""
    corner(hid)
    time.sleep(MIRROR_LAG + 0.1)
    baseline = grab()  # pointer parked in the top-left corner
    walk(hid, round(fx / GAIN_X), round(fy / GAIN_Y), step=2, delay=0.008)
    seen = settled_pointer(baseline, (fx, fy))
    if seen:
        ex, ey = fx - seen[0], fy - seen[1]
        if abs(ex) > tol or abs(ey) * 2.17 > tol:
            walk(hid, round(ex / GAIN_X), round(ey / GAIN_Y), step=1, delay=0.012)
            seen = settled_pointer(baseline, (fx, fy)) or seen
    return seen


def tap(hid, fx, fy):
    seen = go_to(hid, fx, fy)
    hid.rel(0, 0, 1)
    time.sleep(0.05)
    hid.rel(0, 0, 0)
    return seen


def swipe(hid, fx0, fy0, fx1, fy1, duration=0.25):
    go_to(hid, fx0, fy0)
    hid.rel(0, 0, 1)
    n = max(4, int(duration / 0.012))
    ux, uy = round((fx1 - fx0) / GAIN_X), round((fy1 - fy0) / GAIN_Y)
    sx = sy = 0
    for i in range(1, n + 1):
        tx, ty = round(ux * i / n), round(uy * i / n)
        hid.rel(max(-127, min(127, tx - sx)), max(-127, min(127, ty - sy)), 1)
        sx, sy = tx, ty
        time.sleep(0.012)
    hid.rel(0, 0, 0)


if __name__ == "__main__":
    import sys
    h = Hid()
    args = [float(a) for a in sys.argv[2:]]
    if sys.argv[1] == "go":
        print(go_to(h, *args))
    elif sys.argv[1] == "tap":
        print(tap(h, *args))
    elif sys.argv[1] == "swipe":
        swipe(h, *args)


def _components(mask, cell=4):
    """Connected components of a boolean mask on a coarse grid: (cells, xs, ys) each."""
    h, w = mask.shape
    g = mask[: h // cell * cell, : w // cell * cell].reshape(h // cell, cell, w // cell, cell).any(axis=(1, 3))
    lab = np.zeros(g.shape, np.int32)
    out = []
    for y0, x0 in zip(*np.nonzero(g)):
        if lab[y0, x0]:
            continue
        lab[y0, x0] = len(out) + 1
        stack, pts = [(y0, x0)], []
        while stack:
            cy, cx = stack.pop()
            pts.append((cy, cx))
            for ny in (cy - 1, cy, cy + 1):
                for nx in (cx - 1, cx, cx + 1):
                    if 0 <= ny < g.shape[0] and 0 <= nx < g.shape[1] and g[ny, nx] and not lab[ny, nx]:
                        lab[ny, nx] = lab[y0, x0]
                        stack.append((ny, nx))
        ys, xs = (np.array(v) for v in zip(*pts))
        out.append((len(pts), (xs + 0.5) * cell, (ys + 0.5) * cell))
    return out


def orange_mask(frame_rgb):
    r, g, b = (frame_rgb[..., i].astype(np.int16) for i in range(3))
    return (r > 200) & (g > 100) & (g < 185) & (b < 90) & (r - g > 60)


def find_orange(frame_rgb, baseline_rgb=None):
    """Centre (fractions) of the orange Pointer Control ring, or None.

    Needs Pointer Control: Color = Orange, large size. The ring is the orange
    component that is big (about 22% of the screen width across) and hollow,
    unlike orange app icons, which are small and solid.
    """
    mask = orange_mask(frame_rgb)
    if baseline_rgb is not None:  # drop orange that was already there (icons etc.)
        mask &= ~orange_mask(baseline_rgb)
    h, w = mask.shape
    best = None
    for n, xs, ys in _components(mask):
        bw, bh = np.ptp(xs) + 4, np.ptp(ys) + 4
        size = max(bw, bh) / w
        fill = n * 16 / (bw * bh)
        if 0.12 < size < 0.35 and fill < 0.5 and (best is None or n > best[0]):
            # a ring cut off by a screen edge: centre from the full-size side
            cx = (xs.min() + xs.max()) / 2
            cy = (ys.min() + ys.max()) / 2
            d = max(bw, bh)
            if bw < d * 0.9:
                cx = xs.max() - d / 2 if xs.min() <= 4 else xs.min() + d / 2
            if bh < d * 0.9:
                cy = ys.max() - d / 2 if ys.min() <= 4 else ys.min() + d / 2
            best = (n, cx / w, cy / h)
    return best[1:] if best else None


def grab_rgb():
    return np.asarray(Image.open(io.BytesIO(grab_png())).convert("RGB"))
