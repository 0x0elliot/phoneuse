#!/usr/bin/python
"""Use the mirror window like the iPhone's screen: the phone's pointer follows
your cursor while it is over the mirror, clicks tap, drags swipe.

Positions go to the iPhone as absolute pointer reports (hidd 'a' command),
which iOS places exactly, so there is no steering or calibration. Mouse buttons
are read from /dev/input read-only; nothing is grabbed, so the PC's mouse and
keyboard keep working normally everywhere.

iPhone settings: AssistiveTouch on, Dwell Control off.
"""
import glob
import json
import os
import select
import socket
import struct
import threading
import time

import steer  # also fixes a stale HYPRLAND_INSTANCE_SIGNATURE

EVENT = struct.Struct("llHHi")  # struct input_event on 64-bit Linux
EV_KEY, BTN_LEFT = 0x01, 0x110
RATE = 1 / 60  # pointer updates per second while over the mirror


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def hypr(cmd):
    """One Hyprland IPC request ('j/cursorpos', 'j/clients', ...) as parsed JSON."""
    path = os.path.join(os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}"),
                        "hypr", os.environ["HYPRLAND_INSTANCE_SIGNATURE"], ".socket.sock")
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.connect(path)
    s.sendall(cmd.encode())
    data = b""
    while chunk := s.recv(65536):
        data += chunk
    s.close()
    return json.loads(data)


class Buttons:
    """Left-button state from every mouse, read-only."""

    def __init__(self):
        self.down = False
        self.changed = threading.Event()
        paths = sorted(glob.glob("/dev/input/by-id/*event-mouse"))
        self.fds = [os.open(p, os.O_RDONLY | os.O_NONBLOCK) for p in paths]
        log("watching", len(paths), "mice")
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        while True:
            ready, _, _ = select.select(self.fds, [], [])
            for fd in ready:
                try:
                    data = os.read(fd, EVENT.size * 64)
                except BlockingIOError:
                    continue
                for i in range(0, len(data) - EVENT.size + 1, EVENT.size):
                    _, _, etype, code, value = EVENT.unpack_from(data, i)
                    if etype == EV_KEY and code == BTN_LEFT and value in (0, 1):
                        self.down = bool(value)
                        self.changed.set()


def main():
    buttons = Buttons()
    hid = None
    window = None
    window_checked = 0.0
    sent = None  # last (fx, fy, button) sent to the phone
    pressed_here = False  # the current press started over the mirror
    while True:
        buttons.changed.wait(RATE)
        buttons.changed.clear()
        try:
            now = time.time()
            if now - window_checked > 0.5:
                window = next(((c["at"], c["size"]) for c in hypr("j/clients") if c["class"] == "uxplay"), None)
                window_checked = now
            if window is None:
                pressed_here = False
                continue
            cur = hypr("j/cursorpos")
            (x, y), (w, h) = window
            fx, fy = (cur["x"] - x) / w, (cur["y"] - y) / h
            inside = 0 <= fx <= 1 and 0 <= fy <= 1
            if buttons.down and not pressed_here and inside and (sent is None or not sent[2]):
                pressed_here = True
            if not buttons.down:
                pressed_here = False
            if not inside and not pressed_here:
                if sent and sent[2]:  # dragged off the mirror: let go
                    hid.cmd(f"a {sent[0]:.5f} {sent[1]:.5f} 0")
                    sent = (sent[0], sent[1], 0)
                continue
            fx, fy = min(max(fx, 0.0), 1.0), min(max(fy, 0.0), 1.0)
            state = (round(fx, 4), round(fy, 4), 1 if pressed_here else 0)
            if state != sent:
                hid = hid or steer.Hid()
                hid.cmd(f"a {state[0]:.5f} {state[1]:.5f} {state[2]}")
                if sent and state[2] != sent[2]:
                    log("tap down" if state[2] else "tap up", f"({state[0]:.3f}, {state[1]:.3f})")
                sent = state
        except Exception as e:
            log("error:", e)
            hid, sent, pressed_here = None, None, False
            time.sleep(1)


if __name__ == "__main__":
    main()
