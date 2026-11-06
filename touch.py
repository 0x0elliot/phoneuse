"""Touch gestures on the iPhone through hidd: exact taps, and drags that follow a path.

What iOS does with our HID reports (measured 2026-11-06, iPhone 17 Pro, iOS 26):
  * The absolute pointer (hidd 'a') lands exactly where asked, anywhere on screen.
  * Button presses count only from the absolute pointer.
  * While the button is held, absolute moves are ignored; relative moves (hidd 'm')
    drag. So a drag = absolute press, then relative motion, then release.
  * Relative motion is accelerated by report size and dropped when reports come
    faster than ~8 ms apart. One report per 8 ms, sized from DRAG_PTS below,
    moves the pointer a predictable distance.
"""
import bisect
import threading
import time

SCREEN_PT = (402, 874)  # iPhone 17 Pro, points
TICK = 0.008  # one relative report per tick
RAMP = 0.95  # reports at the start of a motion get less acceleration; measured 4-9% short

# Points moved by one relative report of N units (8 ms pacing), measured.
DRAG_PTS = [(1, 3.6), (2, 6.9), (3, 12.1), (4, 17.6), (5, 25.6), (6, 33.3), (8, 46.6),
            (10, 62.1), (12, 76.3), (16, 104.1), (20, 141.8), (28, 199.7)]
_PTS = [p for _, p in DRAG_PTS]


def units_for(points):
    """Report size (units, may be fractional) that moves `points` in one report."""
    if points <= 0:
        return 0.0
    i = bisect.bisect_left(_PTS, points)
    if i == 0:
        return points / DRAG_PTS[0][1] * DRAG_PTS[0][0]
    if i >= len(DRAG_PTS):
        return DRAG_PTS[-1][0]  # cap: the rest goes in later ticks
    (u0, p0), (u1, p1) = DRAG_PTS[i - 1], DRAG_PTS[i]
    return u0 + (u1 - u0) * (points - p0) / (p1 - p0)


def points_for(units):
    """Points moved by a report of `units` (inverse of units_for)."""
    if units <= 0:
        return 0.0
    us = [u for u, _ in DRAG_PTS]
    i = bisect.bisect_left(us, units)
    if i == 0:
        return units * DRAG_PTS[0][1] / DRAG_PTS[0][0]
    if i >= len(DRAG_PTS):
        return DRAG_PTS[-1][1] * units / DRAG_PTS[-1][0]
    (u0, p0), (u1, p1) = DRAG_PTS[i - 1], DRAG_PTS[i]
    return p0 + (p1 - p0) * (units - u0) / (u1 - u0)


class Touch:
    """One finger. Positions are screen fractions (0..1)."""

    def __init__(self, hid):
        self.hid = hid
        self.down = False
        self.pos = None  # where we believe the pointer is (fractions)
        self.target = None
        self.lock = threading.Lock()

    def hover(self, fx, fy):
        fx, fy = _clamp(fx), _clamp(fy)
        self.hid.cmd(f"a {fx:.5f} {fy:.5f} 0")
        self.pos = self.target = (fx, fy)

    def press(self, fx, fy, settle=0.1):
        """Touch down at (fx, fy). The pointer is moved there first and given `settle`
        seconds: pressing in the same instant as a jump lets iOS start the touch on
        the way, which turns an edge swipe into a drag of the content."""
        fx, fy = _clamp(fx), _clamp(fy)
        if self.pos is None or abs(self.pos[0] - fx) > 0.002 or abs(self.pos[1] - fy) > 0.002:
            self.hid.cmd(f"a {fx:.5f} {fy:.5f} 0")
            time.sleep(settle)
        self.hid.cmd(f"a {fx:.5f} {fy:.5f} 1")
        self.pos = self.target = (fx, fy)
        self.down = True

    def step(self):
        """Send one relative report moving toward the target. Returns remaining distance (pt)."""
        if not self.down or self.pos is None or self.target is None:
            return 0.0
        ex = (self.target[0] - self.pos[0]) * SCREEN_PT[0]
        ey = (self.target[1] - self.pos[1]) * SCREEN_PT[1]
        dist = (ex * ex + ey * ey) ** 0.5
        if dist < 1.0:
            return dist
        u = max(1.0, units_for(dist))
        ux, uy = round(u * ex / dist), round(u * ey / dist)
        if ux == 0 and uy == 0:
            return dist
        mag = (ux * ux + uy * uy) ** 0.5
        moved = points_for(mag) * RAMP
        self.hid.cmd(f"m {ux} {uy} 0 1")
        self.pos = (self.pos[0] + moved * ux / mag / SCREEN_PT[0],
                    self.pos[1] + moved * uy / mag / SCREEN_PT[1])
        return max(0.0, dist - moved)

    def release(self):
        if not self.down:
            return
        self.hid.cmd("m 0 0 0 0")
        fx, fy = self.target or self.pos
        self.hid.cmd(f"a {fx:.5f} {fy:.5f} 0")
        self.down = False
        self.pos = (fx, fy)


def _clamp(v):
    return min(max(float(v), 0.0), 1.0)


# ---------- scripted gestures (for agents) ----------

def tap(hid, fx, fy, hold=0.06):
    t = Touch(hid)
    t.press(fx, fy)
    time.sleep(hold)
    t.release()


def long_press(hid, fx, fy, hold=0.8):
    tap(hid, fx, fy, hold)


def swipe(hid, fx0, fy0, fx1, fy1, duration=0.3, hold_end=0.0):
    """Finger down at (fx0, fy0), move to (fx1, fy1) over `duration`, lift.
    Absolute reports throughout: iOS follows absolute moves while pressed."""
    fx0, fy0, fx1, fy1 = (_clamp(v) for v in (fx0, fy0, fx1, fy1))
    hid.cmd(f"a {fx0:.5f} {fy0:.5f} 0")
    time.sleep(0.1)
    hid.cmd(f"a {fx0:.5f} {fy0:.5f} 1")
    n = max(2, int(duration / TICK))
    for i in range(1, n + 1):
        k = i / n
        hid.cmd(f"a {fx0 + (fx1 - fx0) * k:.5f} {fy0 + (fy1 - fy0) * k:.5f} 1")
        time.sleep(TICK)
    time.sleep(hold_end)
    hid.cmd(f"a {fx1:.5f} {fy1:.5f} 0")
