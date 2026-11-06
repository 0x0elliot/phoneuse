#!/usr/bin/python
"""Use the mirror window like the iPhone's screen: the phone's pointer follows
your cursor while it is over the mirror, clicks tap, drags swipe.

Positions go to the iPhone as absolute pointer reports (hidd 'a' command),
which iOS places exactly, so there is no steering or calibration. iOS ignores
absolute moves while the button is held, so a drag presses with an absolute
report and then moves with relative reports (hidd 'm'), like a real mouse. Mouse buttons
are read from /dev/input read-only; nothing is grabbed, so the PC's mouse and
keyboard keep working normally everywhere.

The mirror window is exactly the phone screen's shape, with squircle corners
and a thick dark border as the phone's bezel. Pressing on the bezel starts the
touch at the nearest screen edge (press the bottom bezel and drag up = swipe
home; left bezel and drag right = back). The window's size is locked
(min_size = max_size, plus a snap-back), so the border can't resize it.

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
FRAME = 30  # bezel: Hyprland border thickness (logical px); presses on it start edge touches
STRIP = 0.0  # no letterbox strips: the window is exactly the phone screen's shape
CORNER = 70  # screen corner radius (logical px, ~56 pt on the phone); squircle via rounding_power
MIRROR_W = 498  # logical px; height follows from the phone's aspect plus the strips
MIRROR_H = round(MIRROR_W / PHONE_ASPECT * (1 + 2 * STRIP))
# min_size = max_size locks the window: resizing the GL window crashed uxplay.
BEZEL_RULE = (
    'hl.window_rule({ name = "iphone-mirror-bezel", match = { class = "^uxplay$" }, '
    f'border_size = {FRAME}, rounding = {CORNER}, rounding_power = 3.0, border_color = "rgb(18181c) rgb(18181c)", '
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


# Linux evdev key codes -> USB HID usage codes (keyboard page)
_EV2HID = {}
for i, k in enumerate([30, 48, 46, 32, 18, 33, 34, 35, 23, 36, 37, 38, 50, 49, 24, 25, 16, 19, 31, 20, 22, 47, 17, 45, 21, 44]):
    _EV2HID[k] = 4 + i  # a..z
for i, k in enumerate([2, 3, 4, 5, 6, 7, 8, 9, 10, 11]):
    _EV2HID[k] = 30 + i  # 1..9, 0
_EV2HID.update({28: 40, 1: 41, 14: 42, 15: 43, 57: 44, 12: 45, 13: 46, 26: 47, 27: 48, 43: 49,
                39: 51, 40: 52, 41: 53, 51: 54, 52: 55, 53: 56, 58: 57,
                59: 58, 60: 59, 61: 60, 62: 61, 63: 62, 64: 63, 65: 64, 66: 65, 67: 66, 68: 67, 87: 68, 88: 69,
                110: 73, 102: 74, 104: 75, 111: 76, 107: 77, 109: 78,
                106: 79, 105: 80, 108: 81, 103: 82, 96: 88})
_EVMOD = {29: 0x01, 42: 0x02, 56: 0x04, 125: 0x08, 97: 0x10, 54: 0x20, 100: 0x40, 126: 0x80}


def keyboard_paths():
    """keyd's virtual keyboard if present (keyd grabs the physical ones), else real keyboards."""
    devs, name, handlers = [], None, ""
    for line in open("/proc/bus/input/devices"):
        if line.startswith("N: Name="):
            name = line.split("=", 1)[1].strip().strip('"')
        elif line.startswith("H: Handlers="):
            handlers = line
        elif line.startswith("B: EV=") and "kbd" in handlers and "leds" in handlers:
            ev = next((h for h in handlers.split() if h.startswith("event")), None)
            if ev:
                devs.append((name, "/dev/input/" + ev))
    keyd = [p for n, p in devs if n == "keyd virtual keyboard"]
    return keyd or [p for n, p in devs if "keyd" not in n]


class KeyForwarder:
    """Types on the iPhone while the mirror window has focus. Read-only: keys still
    reach the PC as usual (the mirror window ignores them)."""

    def __init__(self, hid_getter, focused):
        self.hid_getter = hid_getter
        self.focused = focused
        self.mods = 0
        self.held = []
        self.sending = False
        paths = keyboard_paths()
        self.fds = [os.open(p, os.O_RDONLY | os.O_NONBLOCK) for p in paths]
        log("typing to the phone from", len(paths), "keyboard(s) while the mirror is focused")
        threading.Thread(target=self._run, daemon=True).start()

    def _send(self):
        hid = self.hid_getter()
        if hid:
            hid.cmd("k %d %s" % (self.mods, " ".join(str(c) for c in self.held[-6:])))

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
                    if etype != EV_KEY or value == 2:  # ignore autorepeat; the phone repeats itself
                        continue
                    try:
                        self._key(code, value == 1)
                    except Exception as e:
                        log("key error:", e)

    def _key(self, code, down):
        if code in _EVMOD:
            self.mods = self.mods | _EVMOD[code] if down else self.mods & ~_EVMOD[code]
        elif code in _EV2HID:
            u = _EV2HID[code]
            if down and u not in self.held:
                self.held.append(u)
            elif not down and u in self.held:
                self.held.remove(u)
        else:
            return
        if self.focused():
            self.sending = True
            self._send()
        elif self.sending:  # focus left the mirror: let go of everything on the phone
            self.mods, self.held, self.sending = 0, [], False
            self._send()


def run(stop=None):
    """Mirror-window mouse handling until `stop` (a threading.Event) is set."""
    subprocess_eval(BEZEL_RULE)
    buttons = Buttons()
    hid = None
    window = None
    window_checked = 0.0
    sent = None  # last (fx, fy) hovered, sent as absolute
    finger = None  # touch.Touch while the button is held
    last_send = 0.0

    shared = {"hid": None}  # (not "state": the hover code below uses that name)

    def mirror_focused():
        try:
            return hypr("j/activewindow").get("class") == "uxplay"
        except Exception:
            return False

    def shared_hid():
        if shared["hid"] is None:
            shared["hid"] = steer.Hid()
        return shared["hid"]

    KeyForwarder(shared_hid, mirror_focused)

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
                # keep the window at its framed size: snap back any resize (resizing
                # the GL window has crashed uxplay; the rule's min/max only stops some)
                if client and (abs(client["size"][0] - MIRROR_W) > 2 or abs(client["size"][1] - MIRROR_H) > 2):
                    if finger is None:
                        frame_window(client)
                        continue
                window_checked = now
            if window is None:
                finger = None
                continue
            cur = hypr("j/cursorpos")
            (wx, wy), (ww, wh) = window
            x, y, w, h = picture_rect((wx, wy), (ww, wh))
            fx, fy = (cur["x"] - x) / w, (cur["y"] - y) / h
            # the window and its bezel (the border around it) both count; on the bezel
            # the position clamps to the nearest screen edge, so edge swipes start exactly there
            inside = (wx - FRAME <= cur["x"] <= wx + ww + FRAME) and (wy - FRAME <= cur["y"] <= wy + wh + FRAME)
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
