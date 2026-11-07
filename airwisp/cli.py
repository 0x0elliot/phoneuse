#!/usr/bin/python
"""airwisp: see and operate an iPhone from a Linux PC.

Setup and running:
  airwisp install              one-time: Bluetooth HID service (sudo), bluetoothd
                               config, and the local vision models
  airwisp up                   mirror window + mouse control (click/drag on the mirror)
  airwisp status               Bluetooth link and mirror window

Agent commands. Coordinates are fractions (0..1) of the screenshot, or phone
points if any value is > 1 (screen_points in ~/.config/airwisp/config.toml):
  airwisp screenshot [PATH]    PNG of the phone screen; parks the pointer at the left
                               edge first and waits for the mirror to catch up
                               (--keep-pointer to leave the pointer where it is)
  airwisp tap X Y              tap
  airwisp longpress X Y [S]    press and hold (default 0.8 s)
  airwisp swipe X0 Y0 X1 Y1 [S]  drag from one point to another over S seconds
  airwisp scroll up|down [N]   scroll the content by N half-screens (default 1)
  airwisp home | back | switcher | control-center | notifications | dismiss
  airwisp open APP             open an app by name (search, type, Enter)
  airwisp type TEXT            type text (US layout); \\n presses Enter
  airwisp key COMBO            e.g. enter, escape, cmd+h, cmd+space, shift+tab
  airwisp where                debugging: where the pointer appears (needs Pointer
                               Control colour Orange)

Reading the screen without images (local models; a few hundred tokens instead
of ~1,300 for a screenshot):
  airwisp text [--json]        every line of text on screen with its centre (x, y)
  airwisp find WHAT            where an element is, from a plain description
                               ("clear search (X) button", "Settings app icon")
  airwisp tap-on WHAT          find it and tap it; prints where it tapped

iPhone settings this relies on: AssistiveTouch on, Dwell Control off.
"""
import os
import subprocess
import sys
import threading
import time

from . import screen, touch
from .config import NAME, SCREEN_PT, VISION_SOCKET, RUNTIME_DIR, decoder
from .hidclient import Hid

PKG = os.path.dirname(os.path.realpath(__file__))
ROOT = os.path.dirname(PKG)  # the repository checkout

PT = SCREEN_PT
LAST_ACTION = os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"), "airwisp-last-action")
MIRROR_LAG = 0.6  # seconds before the mirror shows an action's result
# Decoder: frames must leave the decoder as soon as they're decoded. iOS only
# sends a frame when the screen changes, and its streams don't declare "no
# reordering", so a default H.264 decoder may hold a frame until the next one
# pushes it out (measured: 200 ms median live). compliance=flexible releases them.
DECODER = os.environ.get("AIRWISP_DECODER") or decoder()
MIRROR_ARGS = ["uxplay", "-p", "-n", NAME, "-vd", DECODER,
               "-vs", "glimagesink", "-srgb", "no", "-vsync", "no", "-s", f"{SCREEN_PT[0] * 3}x{SCREEN_PT[1] * 3}@60", "-fps", "60",
               # audio: mirrored audio already plays unsynced (-vsync no); keep the sink's
               # buffer at 40 ms (pulsesink default is up to 200 ms) and ask the phone to
               # plan for 0.1 s instead of 0.25 s
               "-as", "pulsesink buffer-time=40000 latency-time=10000", "-al", "0.1"]


def die(msg):
    print(msg, file=sys.stderr)
    sys.exit(1)


def point(xs, ys):
    """Parse a coordinate pair: fractions, or iPhone points if either is > 1."""
    x, y = float(xs), float(ys)
    if x > 1 or y > 1:
        x, y = x / PT[0], y / PT[1]
    if not (0 <= x <= 1 and 0 <= y <= 1):
        die(f"coordinate out of range: {xs} {ys}")
    return x, y


def hid():
    try:
        h = Hid()
    except OSError:
        die("Bluetooth HID service isn't running. Run: airwisp install")
    st = h.cmd("status")
    if "connected=True" not in st:
        try:
            h.cmd("connect")
        except RuntimeError as e:
            die(f"iPhone not connected over Bluetooth ({e}). On the phone: Settings > Bluetooth > {NAME}.")
    return h


def acted():
    open(LAST_ACTION, "w").close()


def key_combo(h, combo):
    parts = combo.lower().replace("-", "+").split("+")
    mods = {"cmd": "gui", "command": "gui", "ctrl": "ctrl", "control": "ctrl", "alt": "alt",
            "option": "alt", "opt": "alt", "shift": "shift", "gui": "gui"}
    key = parts[-1]
    h.cmd("key " + " ".join([key] + [mods[p] for p in parts[:-1]]))


# ---------- gestures (recipes verified on iOS 26, see RECIPES.md) ----------

def home(h):
    h.cmd("key h gui")


def back(h):
    # finger sliding in from the very left edge (touch.press settles the pointer first)
    touch.swipe(h, 0.0, 0.5, 0.8, 0.5, duration=0.35)


def switcher(h):
    touch.swipe(h, 0.5, 1.0, 0.5, 0.62, duration=0.45, hold_end=0.6)


def control_center(h):
    touch.swipe(h, 0.88, 0.0, 0.88, 0.45, duration=0.6)


def notifications(h):
    touch.swipe(h, 0.15, 0.0, 0.15, 0.7, duration=0.6)


def dismiss(h):
    """Close Control Center, Notification Center, the switcher, or go home from an app."""
    touch.swipe(h, 0.5, 1.0, 0.5, 0.15, duration=0.12)


def scroll(h, direction, n=1.0):
    d = 0.4 * n
    y0, y1 = (0.3, 0.3 + d) if direction == "up" else (0.7, 0.7 - d)
    touch.swipe(h, 0.5, y0, 0.5, min(max(y1, 0.05), 0.95), duration=0.35)


def open_app(h, name):
    h.cmd("key h gui"); time.sleep(0.8)
    h.cmd("key space gui"); time.sleep(0.7)
    h.cmd("type " + name); time.sleep(0.8)
    h.cmd("key enter")


def type_text(h, text):
    for i, chunk in enumerate(text.replace("\\n", "\n").split("\n")):
        if i:
            h.cmd("key enter")
        if chunk:
            h.cmd("type " + chunk)


# ---------- screen ----------

def screenshot(path, park=True):
    if park:
        try:
            # move the pointer to the left edge so it doesn't cover text
            Hid().cmd("a 0.0 0.62 0")
            acted()
        except (OSError, RuntimeError):
            pass
    try:
        wait = MIRROR_LAG - (time.time() - os.path.getmtime(LAST_ACTION))
        if wait > 0:
            time.sleep(wait)
    except FileNotFoundError:
        pass
    try:
        png = screen.grab_png()
    except RuntimeError:
        die(f"No mirror window. Run `airwisp up` and start Screen Mirroring to '{NAME}' on the iPhone.")
    with open(path, "wb") as f:
        f.write(png)
    from PIL import Image
    import io
    w, hgt = Image.open(io.BytesIO(png)).size
    print(f"{path} ({w}x{hgt} px = 402x874 pt; tap with fractions of this image or points)")


# ---------- vision (OCR + grounding, see vision.py) ----------

VISION_SOCK = VISION_SOCKET


def vision(req, timeout=90):
    import json
    import socket

    def ask():
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(timeout)
        s.connect(VISION_SOCK)
        s.sendall((json.dumps(req) + "\n").encode())
        reply = json.loads(s.makefile().readline())
        s.close()
        return reply

    try:
        return ask()
    except (FileNotFoundError, ConnectionRefusedError):
        pass
    py = os.path.join(ROOT, ".venv-vision", "bin", "python")
    if not os.path.exists(py):
        die(f"Vision models aren't installed. Run: {ROOT}/scripts/setup-vision.sh")
    logf = open(os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"), "airwisp-vision.log"), "a")
    subprocess.Popen([py, "-m", "airwisp.vision"], cwd=ROOT, stdout=logf, stderr=logf, start_new_session=True)
    for _ in range(120):
        time.sleep(0.5)
        try:
            return ask()
        except (FileNotFoundError, ConnectionRefusedError):
            continue
    die("vision service didn't start; see $XDG_RUNTIME_DIR/airwisp-vision.log")


def fresh_screenshot():
    path = os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"), f"airwisp-shot-{os.getpid()}.png")
    import contextlib, io
    with contextlib.redirect_stdout(io.StringIO()):
        screenshot(path)
    return path


def text_cmd(args):
    import json
    shot = fresh_screenshot()
    r = vision({"op": "text", "image": shot})
    os.unlink(shot)
    if "error" in r:
        die(r["error"])
    if "--json" in args:
        print(json.dumps(r["lines"]))
        return
    for ln in r["lines"]:
        print(f"{ln['x']:.3f} {ln['y']:.3f}  {ln['text']}")


def find(what):
    shot = fresh_screenshot()
    r = vision({"op": "find", "image": shot, "what": what})
    os.unlink(shot)
    if "error" in r:
        die(f"not found: {what}")
    return r["x"], r["y"]


# ---------- up / install / status ----------

def up():
    if subprocess.run(["systemctl", "is-active", "--quiet", "airwisp-hid"]).returncode != 0:
        die("Bluetooth HID service isn't running. Run: airwisp install")
    print(f"Starting the mirror (AirPlay receiver '{NAME}'). On the iPhone: Control Center > Screen Mirroring > {NAME}.")
    stop = threading.Event()
    procs = {}

    def keep_mirror():
        # uxplay can die (it crashed on a window resize); start it again so the
        # phone can reconnect without restarting `airwisp up`.
        while not stop.is_set():
            env = dict(os.environ)
            out = subprocess.DEVNULL
            if os.environ.get("AIRWISP_TRACE"):  # per-element GStreamer latency, for tuning
                env.update(GST_TRACERS="latency(flags=pipeline+element)", GST_DEBUG="GST_TRACER:7")
                out = open(os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"), "airwisp-gst-trace.log"), "w")
            procs["mirror"] = subprocess.Popen(MIRROR_ARGS, stdout=out, stderr=out, env=env)
            rc = procs["mirror"].wait()
            if stop.is_set():
                break
            print(time.strftime("%H:%M:%S"), f"mirror exited ({rc}); restarting it. Reconnect Screen Mirroring on the iPhone.", flush=True)
            time.sleep(1)
    threading.Thread(target=keep_mirror, daemon=True).start()
    try:
        h = Hid()
        print("Bluetooth:", h.cmd("status").replace("ok ", ""))
        print("Mouse control on: hover, click and drag on the mirror window. Ctrl+C stops everything.")
        # The clicker runs as its own process and restarts by itself when its code
        # changes, so edits don't drop the AirPlay connection.
        watched = [os.path.join(PKG, f) for f in ("mirror_input.py", "touch.py", "screen.py", "hidclient.py")]
        mtimes = lambda: [os.path.getmtime(f) for f in watched]
        while not stop.is_set():
            seen = mtimes()
            procs["clicker"] = subprocess.Popen([sys.executable, "-m", "airwisp.mirror_input"], cwd=ROOT)
            while procs["clicker"].poll() is None:
                time.sleep(1)
                if mtimes() != seen:
                    print(time.strftime("%H:%M:%S"), "clicker code changed; reloading it (mirror stays up)", flush=True)
                    procs["clicker"].terminate()
                    procs["clicker"].wait(3)
                    break
            else:
                print(time.strftime("%H:%M:%S"), "clicker exited; restarting it", flush=True)
                time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        if procs.get("clicker") and procs["clicker"].poll() is None:
            procs["clicker"].terminate()
        mirror = procs.get("mirror")
        if mirror and mirror.poll() is None:
            mirror.terminate()
            try:
                mirror.wait(3)
            except subprocess.TimeoutExpired:
                mirror.kill()


def status():
    svc = subprocess.run(["systemctl", "is-active", "airwisp-hid"], capture_output=True, text=True).stdout.strip()
    print("HID service:", svc)
    if svc == "active":
        print("Bluetooth:", Hid().cmd("status").replace("ok ", ""))
    try:
        at, size = screen.mirror_window()
        print("Mirror window:", at, size)
    except RuntimeError:
        print(f"Mirror window: none (run `airwisp up`, then Screen Mirroring > {NAME} on the iPhone)")


def main():
    a = sys.argv[1:]
    if not a or a[0] in ("-h", "--help", "help"):
        print(__doc__)
        return
    cmd, args = a[0], a[1:]
    if cmd == "install":
        subprocess.run(["sudo", os.path.join(ROOT, "scripts", "install.sh")], check=True)
        if not os.path.exists(os.path.join(ROOT, ".venv-vision")):
            import shutil
            if shutil.which("uv"):
                subprocess.run([os.path.join(ROOT, "scripts", "setup-vision.sh")], check=True)
            else:
                print("skipping the screen-reading models (airwisp text/find): install uv, then run scripts/setup-vision.sh")
        return
    if cmd == "up":
        return up()
    if cmd == "status":
        return status()
    if cmd == "text":
        return text_cmd(args)
    if cmd == "find":
        x, y = find(" ".join(args))
        print(f"{x:.3f} {y:.3f}")
        return
    if cmd == "screenshot":
        keep = "--keep-pointer" in args
        paths = [x for x in args if x != "--keep-pointer"]
        return screenshot(paths[0] if paths else os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"), "airwisp.png"), park=not keep)
    h = hid()
    if cmd == "tap":
        touch.tap(h, *point(*args[:2]))
    elif cmd == "longpress":
        touch.long_press(h, *point(*args[:2]), hold=float(args[2]) if len(args) > 2 else 0.8)
    elif cmd == "swipe":
        x0, y0 = point(*args[0:2]); x1, y1 = point(*args[2:4])
        touch.swipe(h, x0, y0, x1, y1, duration=float(args[4]) if len(args) > 4 else 0.3)
    elif cmd == "scroll":
        scroll(h, args[0] if args else "down", float(args[1]) if len(args) > 1 else 1.0)
    elif cmd in ("home", "back", "switcher", "dismiss", "notifications"):
        globals()[cmd](h)
    elif cmd == "control-center":
        control_center(h)
    elif cmd == "open":
        open_app(h, " ".join(args))
    elif cmd == "type":
        type_text(h, " ".join(args))
    elif cmd == "key":
        key_combo(h, args[0])
    elif cmd == "tap-on":
        x, y = find(" ".join(args))
        # find always answers, even when the element isn't there; it then tends to
        # point at the status bar. Never tap there: the Dynamic Island in its middle
        # opens the Stop Mirroring popup.
        if y < 0.06:
            die(f"refusing to tap the status bar at {x:.3f} {y:.3f}: '{' '.join(args)}' is probably not on screen")
        touch.tap(h, x, y)
        print(f"tapped {x:.3f} {y:.3f}")
    elif cmd == "where":
        p = screen.find_orange(screen.grab_rgb())
        print(f"{p[0]:.3f} {p[1]:.3f}" if p else "not found")
        return
    else:
        die(f"unknown command: {cmd} (phone --help)")
    acted()
    print("ok")


if __name__ == "__main__":
    main()
