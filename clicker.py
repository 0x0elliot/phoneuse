#!/usr/bin/python
"""Click the mirror window to tap the iPhone there; drag to swipe.

Reads mouse buttons from /dev/input read-only (needs the 'input' group). It
never grabs devices, so the PC's mouse and keyboard keep working normally.
"""
import glob
import json
import os
import queue
import select
import struct
import subprocess
import threading
import time

import steer

EVENT = struct.Struct("llHHi")  # struct input_event on 64-bit Linux
EV_KEY, BTN_LEFT = 0x01, 0x110
DRAG_MIN = 0.03  # fraction of the window; shorter moves count as a tap


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def mirror_fraction():
    """Cursor position as a fraction of the mirror window, or None if outside it."""
    cur = json.loads(subprocess.check_output(["hyprctl", "cursorpos", "-j"]))
    for c in json.loads(subprocess.check_output(["hyprctl", "clients", "-j"])):
        if c["class"] == "uxplay":
            (x, y), (w, h) = c["at"], c["size"]
            fx, fy = (cur["x"] - x) / w, (cur["y"] - y) / h
            if 0 <= fx <= 1 and 0 <= fy <= 1:
                return fx, fy
    return None


def mirror_focused():
    a = json.loads(subprocess.check_output(["hyprctl", "activewindow", "-j"]) or b"{}")
    return a.get("class") == "uxplay"


def worker(jobs):
    hid = None
    while True:
        kind, *pts = jobs.get()
        try:
            hid = hid or steer.Hid()
            if kind == "tap":
                seen = steer.tap(hid, *pts)
                log("tap", fmt(pts), "pointer seen at", fmt(seen) if seen else "?")
            else:
                steer.swipe(hid, *pts)
                log("swipe", fmt(pts[:2]), "->", fmt(pts[2:]))
        except Exception as e:
            log("error:", e)
            hid = None


def fmt(p):
    return "(" + ", ".join(f"{v:.2f}" for v in p) + ")"


def main():
    paths = sorted(set(glob.glob("/dev/input/by-id/*event-mouse")))
    fds = {os.open(p, os.O_RDONLY | os.O_NONBLOCK): p for p in paths}
    log("listening on", ", ".join(os.path.basename(p) for p in fds.values()))
    jobs = queue.Queue()
    threading.Thread(target=worker, args=(jobs,), daemon=True).start()
    press = None
    while True:
        ready, _, _ = select.select(list(fds), [], [])
        for fd in ready:
            try:
                data = os.read(fd, EVENT.size * 64)
            except BlockingIOError:
                continue
            for i in range(0, len(data) - EVENT.size + 1, EVENT.size):
                _, _, etype, code, value = EVENT.unpack_from(data, i)
                if etype != EV_KEY or code != BTN_LEFT:
                    continue
                try:
                    if value == 1:
                        press = mirror_fraction()
                        continue
                    if value != 0 or not press:
                        continue
                    end = mirror_fraction()
                    start, press = press, None
                    if end is None or not mirror_focused():
                        continue
                except Exception as e:
                    log("error reading cursor:", e)
                    press = None
                    continue
                if abs(end[0] - start[0]) + abs(end[1] - start[1]) < DRAG_MIN:
                    jobs.put(("tap", *end))
                else:
                    jobs.put(("swipe", *start, *end))


if __name__ == "__main__":
    main()
