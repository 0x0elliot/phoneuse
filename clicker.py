#!/usr/bin/python
"""Use the mirror window like the iPhone's screen: the phone's pointer follows
your cursor while it is over the mirror, clicks tap, drags swipe.

Positions go to the iPhone as absolute pointer reports (hidd 'a' command),
which iOS places exactly, so there is no steering or calibration. iOS ignores
absolute moves while the button is held, so a drag presses with an absolute
report and then moves with relative reports (hidd 'm'), like a real mouse. Mouse buttons
are read from /dev/input read-only; nothing is grabbed, so the PC's mouse and
keyboard keep working normally everywhere.

The mirror window gets a phone-style frame: a thick rounded border plus a
window taller than the picture, so black strips sit above and below the
screen inside the window. Pressing a strip starts the touch at that edge of
the phone's screen (press the bottom strip and drag up = swipe home), and,
being inside the window, never triggers Hyprland's resize-on-border.

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
import touch

EVENT = struct.Struct("llHHi")  # struct input_event on 64-bit Linux
EV_KEY, EV_REL, BTN_LEFT = 0x01, 0x02, 0x110
IDLE_WAKE = 1 / 60  # also re-check this often when the mouse is still
MIN_GAP = 1 / 250  # at most this many pointer reports per second
PHONE_ASPECT = steer.PHONE_ASPECT
FRAME = 34  # border thickness (logical px)
STRIP = 0.04  # extra window height above and below the picture, as a fraction of picture height
MIRROR_W = 498  # logical px; height follows from the phone's aspect plus the strips
MIRROR_H = round(MIRROR_W / PHONE_ASPECT * (1 + 2 * STRIP))
# min_size = max_size locks the window: resizing the GL window crashed uxplay.
BEZEL_RULE = (
    'hl.window_rule({ name = "iphone-mirror-bezel", match = { class = "^uxplay$" }, '
    f'border_size = {FRAME}, rounding = 62, border_color = "rgb(18181c) rgb(18181c)", '
    f'min_size = {{ {MIRROR_W}, {MIRROR_H} }}, max_size = {{ {MIRROR_W}, {MIRROR_H} }} }})'
)


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
    """Left-button state from every mouse, read-only; also wakes the loop on motion."""

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
                    elif etype == EV_REL:
                        self.changed.set()


picture_rect = steer.picture_rect


def frame_window(client):
    """Make the mirror window taller than the picture so the strips exist."""
    (w, h) = client["size"]
    if abs(w - MIRROR_W) > 2 or abs(h - MIRROR_H) > 2:
        subprocess_eval(f"hl.dispatch(hl.dsp.window.resize({{ x = {MIRROR_W}, y = {MIRROR_H}, window = 'address:{client['address']}' }}))")
        log("framed mirror window", f"{MIRROR_W}x{MIRROR_H}")


def subprocess_eval(lua):
    import subprocess
    subprocess.run(["hyprctl", "eval", lua], capture_output=True)


def run(stop=None):
    """Mirror-window mouse handling until `stop` (a threading.Event) is set."""
    subprocess_eval(BEZEL_RULE)
    framed = set()
    buttons = Buttons()
    hid = None
    window = None
    window_checked = 0.0
    sent = None  # last (fx, fy) hovered, sent as absolute
    finger = None  # touch.Touch while the button is held
    last_send = 0.0

    def stepper():
        # one relative report per 8 ms while dragging (see touch.py for why)
        while stop is None or not stop.is_set():
            f = finger
            if f is not None and f.down:
                try:
                    f.step()
                except Exception as e:
                    log("drag error:", e)
            time.sleep(touch.TICK)
    threading.Thread(target=stepper, daemon=True).start()

    while stop is None or not stop.is_set():
        buttons.changed.wait(IDLE_WAKE)
        buttons.changed.clear()
        if finger is None and time.time() - last_send < MIN_GAP and not buttons.down:
            time.sleep(MIN_GAP - (time.time() - last_send))
        try:
            now = time.time()
            if now - window_checked > 0.5:
                client = next((c for c in hypr("j/clients") if c["class"] == "uxplay"), None)
                window = (client["at"], client["size"]) if client else None
                if client and client["address"] not in framed:
                    frame_window(client)
                    framed.add(client["address"])
                    continue
                window_checked = now
            if window is None:
                finger = None
                continue
            cur = hypr("j/cursorpos")
            (wx, wy), (ww, wh) = window
            x, y, w, h = picture_rect((wx, wy), (ww, wh))
            fx, fy = (cur["x"] - x) / w, (cur["y"] - y) / h
            # anywhere in the window counts, including the strips around the picture
            inside = wx <= cur["x"] <= wx + ww and wy <= cur["y"] <= wy + wh
            cfx, cfy = min(max(fx, 0.0), 1.0), min(max(fy, 0.0), 1.0)
            hid = hid or steer.Hid()

            if finger is None and buttons.down and inside:
                finger = touch.Touch(hid)
                finger.pos = sent  # usually already hovering here, so no settle wait
                finger.press(cfx, cfy)  # exact touch-down
                log("down", f"({cfx:.3f}, {cfy:.3f})")
            elif finger is not None and buttons.down:
                finger.target = (cfx, cfy)  # stepper drags toward it
            elif finger is not None:
                finger.target = (cfx, cfy)
                t0 = time.time()
                while finger.step() > 2 and time.time() - t0 < 0.15:
                    time.sleep(touch.TICK)
                f, finger = finger, None
                f.release()
                log("up", f"({cfx:.3f}, {cfy:.3f})")
                sent = (round(cfx, 4), round(cfy, 4))
            elif inside:
                state = (round(cfx, 4), round(cfy, 4))
                if state != sent:
                    hid.cmd(f"a {state[0]:.5f} {state[1]:.5f} 0")
                    sent = state
                    last_send = time.time()
        except Exception as e:
            log("error:", e)
            hid, sent, finger = None, None, None
            time.sleep(1)


if __name__ == "__main__":
    run()
