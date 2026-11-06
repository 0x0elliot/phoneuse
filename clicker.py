#!/usr/bin/python
"""Use the mirror window like the iPhone's screen: the phone's pointer follows
your cursor while it is over the mirror, clicks tap, drags swipe.

Positions go to the iPhone as absolute pointer reports (hidd 'a' command),
which iOS places exactly, so there is no steering or calibration. iOS ignores
absolute moves while the button is held, so a drag presses with an absolute
report and then moves with relative reports (hidd 'm'), like a real mouse. Mouse buttons
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
    sent = None  # last (fx, fy) hovered, sent as absolute
    drag = None  # while pressed: [last fx, last fy, leftover units x, leftover units y]
    while True:
        buttons.changed.wait(RATE)
        buttons.changed.clear()
        try:
            now = time.time()
            if now - window_checked > 0.5:
                window = next(((c["at"], c["size"]) for c in hypr("j/clients") if c["class"] == "uxplay"), None)
                window_checked = now
            if window is None:
                drag = None
                continue
            cur = hypr("j/cursorpos")
            (x, y), (w, h) = window
            fx, fy = (cur["x"] - x) / w, (cur["y"] - y) / h
            inside = 0 <= fx <= 1 and 0 <= fy <= 1
            cfx, cfy = min(max(fx, 0.0), 1.0), min(max(fy, 0.0), 1.0)
            hid = hid or steer.Hid()

            if drag is None and buttons.down and inside:
                # press: put the dot exactly here and touch down
                hid.cmd(f"a {cfx:.5f} {cfy:.5f} 0")
                hid.cmd(f"a {cfx:.5f} {cfy:.5f} 1")
                drag = [cfx, cfy, 0.0, 0.0]
                log("down", f"({cfx:.3f}, {cfy:.3f})")
            elif drag is not None and buttons.down:
                # held: follow the cursor with relative motion (absolute is ignored while pressed)
                drag[2] += (cfx - drag[0]) / steer.GAIN_X
                drag[3] += (cfy - drag[1]) / steer.GAIN_Y
                drag[0], drag[1] = cfx, cfy
                while abs(drag[2]) >= 1 or abs(drag[3]) >= 1:
                    ux = int(max(-127, min(127, drag[2])))
                    uy = int(max(-127, min(127, drag[3])))
                    hid.cmd(f"m {ux} {uy} 0 1")
                    drag[2] -= ux
                    drag[3] -= uy
            elif drag is not None:
                # released: let go where the cursor is
                hid.cmd("m 0 0 0 0")
                hid.cmd(f"a {cfx:.5f} {cfy:.5f} 0")
                log("up", f"({cfx:.3f}, {cfy:.3f})")
                drag = None
                sent = (round(cfx, 4), round(cfy, 4))
            elif inside:
                # hover: the dot follows the cursor
                state = (round(cfx, 4), round(cfy, 4))
                if state != sent:
                    hid.cmd(f"a {state[0]:.5f} {state[1]:.5f} 0")
                    sent = state
        except Exception as e:
            log("error:", e)
            hid, sent, drag = None, None, None
            time.sleep(1)

if __name__ == "__main__":
    main()
