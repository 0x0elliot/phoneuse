"""The mirror window on screen: Hyprland IPC, where the phone picture is,
screenshots of it, and finding the orange pointer in them.

Positions are fractions of the phone screen: (0, 0) top-left, (1, 1) bottom-right.
Requires Hyprland (window geometry and cursor come from its IPC socket) and grim.
"""
import glob
import io
import json
import os
import socket
import subprocess

import numpy as np
from PIL import Image

from .config import PHONE_ASPECT

MIRROR_CLASS = "uxplay"  # window class of the AirPlay receiver


def _find_hyprland():
    # tmux servers started before a Hyprland restart keep a stale signature, so
    # hyprctl fails (exit 4). Use the saved one only if its socket answers;
    # otherwise the newest instance whose socket does.
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


def hypr(cmd):
    """One Hyprland IPC request ('j/cursorpos', 'j/clients', ...) as parsed JSON (~0.03 ms)."""
    path = os.path.join(os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}"),
                        "hypr", os.environ.get("HYPRLAND_INSTANCE_SIGNATURE", ""), ".socket.sock")
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.connect(path)
    s.sendall(cmd.encode())
    data = b""
    while chunk := s.recv(65536):
        data += chunk
    s.close()
    return json.loads(data)


def mirror_client():
    return next((c for c in hypr("j/clients") if c["class"] == MIRROR_CLASS), None)


def mirror_window():
    c = mirror_client()
    if c is None:
        raise RuntimeError("mirror window not found")
    return c["at"], c["size"]


def picture_rect(at, size):
    """Where the phone picture sits inside the mirror window (centered, aspect-fit)."""
    (x, y), (w, h) = at, size
    if w / h < PHONE_ASPECT:
        pw, ph = w, w / PHONE_ASPECT
    else:
        pw, ph = h * PHONE_ASPECT, h
    return x + (w - pw) / 2, y + (h - ph) / 2, pw, ph


def grab_png():
    """PNG of the phone picture. Captures that area of the screen, so the mirror
    window must not be covered by other windows."""
    x, y, w, h = picture_rect(*mirror_window())
    return subprocess.check_output(["grim", "-g", f"{round(x)},{round(y)} {round(w)}x{round(h)}", "-"])


def grab_rgb():
    return np.asarray(Image.open(io.BytesIO(grab_png())).convert("RGB"))


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
