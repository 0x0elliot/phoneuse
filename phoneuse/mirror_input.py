#!/usr/bin/python
"""Use the mirror window like the iPhone's screen: the phone's pointer follows
your cursor while it is over the mirror, clicks tap, drags swipe.

Hover, press and release go to the iPhone as absolute pointer reports (hidd
'a'), which iOS places exactly. Motion while pressed goes as relative reports
(hidd 'm'), because iOS ends a touch when the absolute position changes while
the button is held. Mouse buttons
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
import subprocess
import threading
import time

from . import touch
from .config import PHONE_ASPECT, CFG
from .hidclient import Hid
from .screen import hypr, picture_rect, MIRROR_CLASS

EVENT = struct.Struct("llHHi")  # struct input_event on 64-bit Linux
EV_KEY, EV_REL, BTN_LEFT = 0x01, 0x02, 0x110
IDLE_WAKE = 1 / 60  # also re-check this often when the mouse is still
MIN_GAP = 1 / 250  # at most this many pointer reports per second
FRAME = 30  # bezel: Hyprland border thickness (logical px); presses on it start edge touches
STRIP = 0.0  # no letterbox strips: the window is exactly the phone screen's shape
CORNER = 70  # screen corner radius (logical px, ~56 pt on the phone); squircle via rounding_power
MIRROR_W = CFG["mirror_width"]  # logical px; height follows from the phone's aspect
MIRROR_H = round(MIRROR_W / PHONE_ASPECT * (1 + 2 * STRIP))
# min_size = max_size locks the window: resizing the GL window crashed uxplay.
BEZEL_RULE = (
    'hl.window_rule({ name = "phoneuse-mirror", match = { class = "^uxplay$" }, '
    f'border_size = {FRAME}, rounding = {CORNER}, rounding_power = 3.0, border_color = "rgb(18181c) rgb(18181c)", '
    f'min_size = {{ {MIRROR_W}, {MIRROR_H} }}, max_size = {{ {MIRROR_W}, {MIRROR_H} }} }})'
)


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


class Buttons:
    """Mouse input from every mouse, read-only. Calls on_press/on_release the moment
    the left button changes, and collects raw motion while `dragging` is set."""

    def __init__(self, on_press=None, on_release=None):
        self.down = False
        self.changed = threading.Event()
        self.on_press, self.on_release = on_press, on_release
        self.dragging = False
        self.dx = self.dy = 0
        self.lock = threading.Lock()
        paths = sorted(glob.glob("/dev/input/by-id/*event-mouse"))
        self.fds = [os.open(p, os.O_RDONLY | os.O_NONBLOCK) for p in paths]
        log("watching", len(paths), "mice")
        threading.Thread(target=self._run, daemon=True).start()

    def take_motion(self):
        with self.lock:
            dx, dy, self.dx, self.dy = self.dx, self.dy, 0, 0
        return dx, dy

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
                        try:
                            (self.on_press if value else self.on_release)()
                        except Exception as e:
                            log("button error:", e)
                        self.changed.set()
                    elif etype == EV_REL:
                        if self.dragging and code in (0, 1):  # REL_X, REL_Y
                            with self.lock:
                                if code == 0:
                                    self.dx += value
                                else:
                                    self.dy += value
                        self.changed.set()


def frame_window(client):
    """Resize the mirror window to the locked size."""
    a = client["address"]
    if not hypr_eval(f"hl.dispatch(hl.dsp.window.resize({{ x = {MIRROR_W}, y = {MIRROR_H}, window = 'address:{a}' }}))"):
        subprocess.run(["hyprctl", "dispatch", "resizewindowpixel", f"exact {MIRROR_W} {MIRROR_H},address:{a}"],
                       capture_output=True)
    log("framed mirror window", f"{MIRROR_W}x{MIRROR_H}")


def hypr_eval(lua):
    """Run Lua in Hyprland (Lua-config builds). Returns False when unsupported."""
    r = subprocess.run(["hyprctl", "eval", lua], capture_output=True, text=True)
    return r.returncode == 0 and "unknown request" not in r.stdout and not r.stdout.startswith("error")


def apply_frame_rule():
    """Phone-like frame and locked size for the mirror window. Lua-config Hyprland
    first (tested); classic hyprlang keywords as a fallback (untested)."""
    if hypr_eval(BEZEL_RULE):
        return
    m = "class:^(uxplay)$"
    subprocess.run(["hyprctl", "--batch", " ; ".join([
        f"keyword windowrule bordersize {FRAME}, {m}",
        f"keyword windowrule rounding {CORNER}, {m}",
        f"keyword windowrule minsize {MIRROR_W} {MIRROR_H}, {m}",
        f"keyword windowrule maxsize {MIRROR_W} {MIRROR_H}, {m}",
    ])], capture_output=True)


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
    """Mirror-window mouse handling until `stop` (a threading.Event) is set.

    Hover: the phone's pointer follows the cursor (absolute reports).
    Press: touch down at the pointer immediately (absolute report, button 1).
    Held: every 8 ms a relative report moves the touch by exactly what the
    cursor moved (sized from the measured table), button 0 on these reports.
    Release: absolute report, button 0.

    Verified on a touch-event test page (touchlab/): this delivers one touch
    whose path matches the request (175 -> 175 pt, flicks 144 -> 141 pt). An
    absolute move while pressed makes iOS end the touch after ~90 ms (it reads
    as a click), and relative-only presses are ignored.
    Release: touch up.
    """
    apply_frame_rule()
    shared = {"hid": None}  # (not "state": the hover code below uses that name)
    hover = {"pos": None}  # last absolute position sent while hovering = where the phone's pointer is
    touch_at = {"pos": None, "carry": [0.0, 0.0]}  # where the touch is during a drag
    win = {"rect": None, "pic": None}

    def hid():
        if shared["hid"] is None:
            shared["hid"] = Hid()
        return shared["hid"]

    def mirror_focused():
        try:
            return hypr("j/activewindow").get("class") == MIRROR_CLASS
        except Exception:
            return False

    def cursor_fraction():
        """(fx, fy, inside) for the cursor against the phone picture; the bezel counts as inside."""
        if win["rect"] is None:
            return None
        cur = hypr("j/cursorpos")
        (wx, wy), (ww, wh) = win["rect"]
        x, y, w, h = win["pic"]
        inside = (wx - FRAME <= cur["x"] <= wx + ww + FRAME) and (wy - FRAME <= cur["y"] <= wy + wh + FRAME)
        fx = min(max((cur["x"] - x) / w, 0.0), 1.0)
        fy = min(max((cur["y"] - y) / h, 0.0), 1.0)
        return fx, fy, inside

    def on_press():
        c = cursor_fraction()
        if not c or not c[2]:
            return
        # Touch down exactly where the phone's pointer already is (the last hover
        # report), not at the cursor: a press that also changes the absolute position
        # makes iOS end the touch after ~90 ms (drags die, clicks get flaky). Any gap
        # between that spot and the cursor is sent as ordinary drag motion.
        fx, fy = hover["pos"] if hover["pos"] else (c[0], c[1])
        hid().cmd(f"a {fx:.5f} {fy:.5f} 1")
        touch_at["pos"] = [fx, fy]
        touch_at["carry"] = [(c[0] - fx) * touch.SCREEN_PT[0], (c[1] - fy) * touch.SCREEN_PT[1]]
        buttons.take_motion()
        buttons.dragging = True  # only now may motion reports follow
        log("down", f"({fx:.3f}, {fy:.3f})")

    def on_release():
        if not buttons.dragging:
            return
        buttons.dragging = False
        # lift where the touch is, so the release carries no position change
        fx, fy = touch_at["pos"] or (0.5, 0.5)
        hid().cmd(f"a {fx:.5f} {fy:.5f} 0")  # touch up
        hover["pos"] = (fx, fy)
        log("up", f"({fx:.3f}, {fy:.3f})")

    buttons = Buttons(on_press, on_release)
    KeyForwarder(hid, mirror_focused)

    def motion_sender():
        # While held: every 8 ms, move the phone's touch by exactly what the cursor
        # moved over the mirror. Cursor deltas (not raw mouse counts, which are
        # DPI-scaled) are converted to phone points, then to the report size that
        # moves that far (touch.DRAG_PTS, measured; iOS accelerates by report size
        # and drops reports sent faster than ~8 ms apart). Remainders carry over.
        last = None
        carry = [0.0, 0.0]  # phone points still to move
        while stop is None or not stop.is_set():
            time.sleep(touch.TICK)
            if not buttons.dragging or win["pic"] is None:
                last, carry[:] = None, [0.0, 0.0]
                continue
            try:
                cur = hypr("j/cursorpos")
            except Exception:
                continue
            if last is None:
                last = cur
                carry[:] = touch_at["carry"]
                continue
            x, y, w, h = win["pic"]
            carry[0] += (cur["x"] - last["x"]) / w * touch.SCREEN_PT[0]
            carry[1] += (cur["y"] - last["y"]) / h * touch.SCREEN_PT[1]
            last = cur
            ux, uy = touch.whole_units(carry[0], carry[1])  # never more than the cursor moved
            # One report every tick, even with no motion: steady timing keeps iOS's
            # acceleration predictable. The button stays 0 here: iOS holds the touch
            # from the absolute press, and a button on these reports reads as a
            # second press/release (double tap sounds).
            try:
                hid().cmd(f"m {ux} {uy} 0 0")
            except Exception as e:
                log("drag error:", e)
                continue
            if ux or uy:
                mag = (ux * ux + uy * uy) ** 0.5
                moved = touch.points_for(mag)
                carry[0] -= moved * ux / mag
                carry[1] -= moved * uy / mag
                p = touch_at["pos"]
                if p:
                    p[0] = min(max(p[0] + moved * ux / mag / touch.SCREEN_PT[0], 0.0), 1.0)
                    p[1] = min(max(p[1] + moved * uy / mag / touch.SCREEN_PT[1], 0.0), 1.0)
    threading.Thread(target=motion_sender, daemon=True).start()

    sent = None
    window_checked = 0.0
    last_send = 0.0
    while stop is None or not stop.is_set():
        buttons.changed.wait(IDLE_WAKE)
        buttons.changed.clear()
        try:
            now = time.time()
            if now - window_checked > 0.5:
                client = next((c for c in hypr("j/clients") if c["class"] == MIRROR_CLASS), None)
                if client and (abs(client["size"][0] - MIRROR_W) > 2 or abs(client["size"][1] - MIRROR_H) > 2) \
                        and not buttons.dragging:
                    frame_window(client)
                    continue
                win["rect"] = (client["at"], client["size"]) if client else None
                win["pic"] = picture_rect(client["at"], client["size"]) if client else None
                window_checked = now
            if buttons.dragging or win["rect"] is None:
                continue
            if now - last_send < MIN_GAP:
                continue
            c = cursor_fraction()
            if c and c[2]:
                state = (round(c[0], 4), round(c[1], 4))
                if state != sent:
                    hid().cmd(f"a {state[0]:.5f} {state[1]:.5f} 0")
                    sent = state
                    hover["pos"] = state
                    last_send = now
        except Exception as e:
            log("error:", e)
            shared["hid"] = None
            sent = None
            time.sleep(1)

if __name__ == "__main__":
    run()
