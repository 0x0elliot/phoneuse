#!/usr/bin/python
"""Bluetooth HID mouse + keyboard for an iPhone, driven over a Unix socket.

Run as root. bluetoothd must be started with --noplugin=input so this process
can own the HID PSMs (17 control, 19 interrupt). See install.sh.

Commands on /run/iphone-hid.sock, one per line, reply "ok ..." or "err ...":
  move DX DY        relative pointer move (split into small steps)
  click [left|right|middle]
  down [btn] / up   hold / release a button (for drags)
  scroll N          wheel; positive scrolls up
  key NAME [MOD..]  e.g. "key h gui" (Cmd+H = home), "key enter", "key tab shift"
  type TEXT         US-layout text
  corner            slam pointer to the top-left corner
  connect           page the paired iPhone once (it usually reconnects by itself)
  pair [SECONDS]    make the adapter discoverable/pairable (default 120 s)
  status
"""
import os
import socket
import threading
import time

import dbus
import dbus.mainloop.glib
import dbus.service
from gi.repository import GLib

HERE = os.path.dirname(os.path.abspath(__file__))
SOCK_PATH = "/run/iphone-hid.sock"
PSM_CTRL, PSM_INTR = 0x11, 0x13
HID_UUID = "00001124-0000-1000-8000-00805f9b34fb"
PROFILE_PATH = "/io/airwisp/hid/profile"
AGENT_PATH = "/io/airwisp/hid/agent"

# Report 1: boot-style keyboard (mods, reserved, 6 keys). Report 2: mouse (buttons, x, y, wheel).
REPORT_MAP = bytes.fromhex(
    "05010906a1018501050719e029e71500250175019508810295017508810395067508150025650507190029658100c0"
    +"05010902a10185020901a1000509190129031500250195037501810295017505810305010930093109381581257f750895038106c0c0"
)


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


# ---------- key tables (US layout) ----------
MODS = {"ctrl": 0x01, "shift": 0x02, "alt": 0x04, "gui": 0x08, "cmd": 0x08,
        "rctrl": 0x10, "rshift": 0x20, "ralt": 0x40, "rgui": 0x80}
NAMED = {"enter": 40, "return": 40, "esc": 41, "escape": 41, "backspace": 42, "tab": 43,
         "space": 44, "right": 79, "left": 80, "down": 81, "up": 82, "delete": 76,
         "home": 74, "end": 77, "pageup": 75, "pagedown": 78}
CHARS = {}
for i, c in enumerate("abcdefghijklmnopqrstuvwxyz"):
    CHARS[c] = (4 + i, 0)
    CHARS[c.upper()] = (4 + i, 0x02)
for i, c in enumerate("1234567890"):
    CHARS[c] = (30 + i, 0)
for i, c in enumerate("!@#$%^&*()"):
    CHARS[c] = (30 + i, 0x02)
for plain, shifted, code in [("-", "_", 45), ("=", "+", 46), ("[", "{", 47), ("]", "}", 48),
                             ("\\", "|", 49), (";", ":", 51), ("'", '"', 52), ("`", "~", 53),
                             (",", "<", 54), (".", ">", 55), ("/", "?", 56)]:
    CHARS[plain] = (code, 0)
    CHARS[shifted] = (code, 0x02)
CHARS[" "] = (44, 0)
CHARS["\n"] = (40, 0)
CHARS["\t"] = (43, 0)
BUTTONS = {"left": 1, "right": 2, "middle": 4}


class HID:
    def __init__(self):
        self.ctrl = None
        self.intr = None
        self.peer = None
        self.buttons = 0
        self.lock = threading.Lock()

    @property
    def connected(self):
        return self.intr is not None

    def send(self, report_id, payload):
        with self.lock:
            if not self.intr:
                raise RuntimeError("no iPhone connected")
            try:
                self.intr.send(bytes([0xA1, report_id]) + bytes(payload))
            except OSError as e:
                self.drop(f"send failed: {e}")
                raise RuntimeError("connection lost")

    def drop(self, why):
        log("disconnect:", why)
        for s in (self.intr, self.ctrl):
            try:
                s and s.close()
            except OSError:
                pass
        self.ctrl = self.intr = None

    # mouse
    def mouse(self, dx=0, dy=0, wheel=0):
        b = lambda v: v & 0xFF
        self.send(2, [self.buttons, b(dx), b(dy), b(wheel)])

    def move(self, dx, dy, step=8, delay=0.008):
        # Small, evenly paced steps keep iOS pointer acceleration predictable.
        while dx or dy:
            sx = max(-step, min(step, dx))
            sy = max(-step, min(step, dy))
            self.mouse(sx, sy)
            dx -= sx
            dy -= sy
            time.sleep(delay)

    def corner(self):
        for _ in range(60):
            self.mouse(-127, -127)
            time.sleep(0.008)

    def press(self, btn):
        self.buttons |= BUTTONS[btn]
        self.mouse()

    def release(self):
        self.buttons = 0
        self.mouse()

    def click(self, btn="left"):
        self.press(btn)
        time.sleep(0.05)
        self.release()

    def scroll(self, n):
        sign = 1 if n > 0 else -1
        for _ in range(abs(n)):
            self.mouse(wheel=sign)
            time.sleep(0.02)

    # keyboard
    def key(self, code, mods=0):
        self.send(1, [mods, 0, code, 0, 0, 0, 0, 0])
        time.sleep(0.012)
        self.send(1, [0] * 8)
        time.sleep(0.012)

    def type(self, text):
        for ch in text:
            if ch not in CHARS:
                raise ValueError(f"cannot type {ch!r}")
            self.key(*CHARS[ch])


hid = HID()


# ---------- L2CAP ----------
def handle_ctrl(sock):
    # Answer HID control-channel requests (SET_PROTOCOL, SET_IDLE, ...) with HANDSHAKE OK.
    while True:
        try:
            data = sock.recv(64)
        except OSError:
            break
        if not data:
            break
        t = data[0] >> 4
        if t == 0x0:  # HANDSHAKE from host: ignore
            continue
        if t == 0x1 and data[0] & 0x0F in (0x3, 0x4, 0x5):  # HID_CONTROL suspend/exit/unplug
            log("control op", hex(data[0]))
            continue
        try:
            if t == 0x4:  # GET_REPORT -> empty report of the asked id
                rid = data[1] if len(data) > 1 else 1
                sock.send(bytes([0xA1, rid]) + bytes(8 if rid == 1 else 4))
            elif t == 0x6:  # GET_PROTOCOL -> report protocol
                sock.send(b"\xa0\x01")
            else:
                sock.send(b"\x00")
        except OSError:
            break
    if hid.ctrl is sock:
        hid.drop("control channel closed")


def listen(psm):
    s = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_SEQPACKET, socket.BTPROTO_L2CAP)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind((socket.BDADDR_ANY, psm))
    s.listen(1)
    return s


def accept_loop():
    sc, si = listen(PSM_CTRL), listen(PSM_INTR)
    log("listening on PSM 17/19")
    while True:
        c, addr = sc.accept()
        log("control from", addr[0])
        i, _ = si.accept()
        log("interrupt from", addr[0])
        if hid.connected:
            hid.drop("replaced by new connection")
        hid.ctrl, hid.intr, hid.peer = c, i, addr[0]
        threading.Thread(target=handle_ctrl, args=(c,), daemon=True).start()


def connect_out():
    # Page each paired iPhone once. No background loop: constant paging keeps the
    # radio busy and makes it miss the iPhone's own connection attempts.
    if hid.connected:
        return "already connected"
    errors = []
    for addr in paired_devices():
        socks = []
        try:
            for psm in (PSM_CTRL, PSM_INTR):
                s = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_SEQPACKET, socket.BTPROTO_L2CAP)
                socks.append(s)
                s.settimeout(8)
                s.connect((addr, psm))
                s.settimeout(None)
        except OSError as e:
            for s in socks:
                s.close()
            errors.append(f"{addr}: {e}")
            continue
        hid.ctrl, hid.intr = socks
        hid.peer = addr
        log("connected out to", addr)
        threading.Thread(target=handle_ctrl, args=(hid.ctrl,), daemon=True).start()
        return f"connected to {addr}"
    raise RuntimeError("; ".join(errors) or "no paired iPhone")


# ---------- D-Bus: profile, agent, adapter ----------
bus = None


def adapter():
    return dbus.Interface(bus.get_object("org.bluez", "/org/bluez/hci0"), "org.freedesktop.DBus.Properties")


def paired_devices():
    om = dbus.Interface(bus.get_object("org.bluez", "/"), "org.freedesktop.DBus.ObjectManager")
    out = []
    for path, ifaces in om.GetManagedObjects().items():
        d = ifaces.get("org.bluez.Device1")
        if d and d.get("Paired"):
            out.append(str(d["Address"]))
    return out


class Profile(dbus.service.Object):
    @dbus.service.method("org.bluez.Profile1", in_signature="", out_signature="")
    def Release(self):
        pass

    @dbus.service.method("org.bluez.Profile1", in_signature="oha{sv}", out_signature="")
    def NewConnection(self, path, fd, props):
        os.close(fd.take())  # we own the PSMs directly

    @dbus.service.method("org.bluez.Profile1", in_signature="o", out_signature="")
    def RequestDisconnection(self, path):
        pass


class Agent(dbus.service.Object):
    # NoInputNoOutput: accept every pairing ("Just Works"). Pairing is only possible while
    # the adapter is discoverable, which the "pair" command opens for a limited time.
    @dbus.service.method("org.bluez.Agent1", in_signature="", out_signature="")
    def Release(self):
        pass

    @dbus.service.method("org.bluez.Agent1", in_signature="os", out_signature="")
    def AuthorizeService(self, device, uuid):
        pass

    @dbus.service.method("org.bluez.Agent1", in_signature="ou", out_signature="")
    def RequestConfirmation(self, device, passkey):
        log("pairing confirm", device, passkey)

    @dbus.service.method("org.bluez.Agent1", in_signature="o", out_signature="")
    def RequestAuthorization(self, device):
        pass

    @dbus.service.method("org.bluez.Agent1", in_signature="o", out_signature="s")
    def RequestPinCode(self, device):
        return "0000"

    @dbus.service.method("org.bluez.Agent1", in_signature="o", out_signature="u")
    def RequestPasskey(self, device):
        return dbus.UInt32(0)

    @dbus.service.method("org.bluez.Agent1", in_signature="ouq", out_signature="")
    def DisplayPasskey(self, device, passkey, entered):
        log("passkey", passkey)

    @dbus.service.method("org.bluez.Agent1", in_signature="os", out_signature="")
    def DisplayPinCode(self, device, pin):
        log("pin", pin)

    @dbus.service.method("org.bluez.Agent1", in_signature="", out_signature="")
    def Cancel(self):
        pass


def open_pairing(seconds):
    a = adapter()
    a.Set("org.bluez.Adapter1", "PairableTimeout", dbus.UInt32(seconds))
    a.Set("org.bluez.Adapter1", "DiscoverableTimeout", dbus.UInt32(seconds))
    a.Set("org.bluez.Adapter1", "Pairable", True)
    a.Set("org.bluez.Adapter1", "Discoverable", True)


def setup_dbus():
    global bus
    dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
    bus = dbus.SystemBus()
    record = open(os.path.join(HERE, "sdp_record.xml")).read().replace("@REPORT_MAP@", REPORT_MAP.hex())
    Profile(bus, PROFILE_PATH)
    pm = dbus.Interface(bus.get_object("org.bluez", "/org/bluez"), "org.bluez.ProfileManager1")
    pm.RegisterProfile(PROFILE_PATH, HID_UUID, {
        "ServiceRecord": record, "Role": "server",
        "RequireAuthentication": False, "RequireAuthorization": False})
    Agent(bus, AGENT_PATH)
    am = dbus.Interface(bus.get_object("org.bluez", "/org/bluez"), "org.bluez.AgentManager1")
    am.RegisterAgent(AGENT_PATH, "NoInputNoOutput")
    am.RequestDefaultAgent(AGENT_PATH)
    a = adapter()
    a.Set("org.bluez.Adapter1", "Powered", True)
    a.Set("org.bluez.Adapter1", "Alias", "iphone-hid")
    log("profile + agent registered")


# ---------- command socket ----------
def run_command(line):
    parts = line.strip().split(" ", 1)
    cmd, rest = parts[0].lower(), (parts[1] if len(parts) > 1 else "")
    args = rest.split()
    if cmd == "status":
        return f"ok connected={hid.connected} peer={hid.peer} paired={paired_devices()}"
    if cmd == "connect":
        return "ok " + connect_out()
    if cmd == "pair":
        secs = int(args[0]) if args else 120
        GLib.idle_add(open_pairing, secs)
        return f"ok discoverable for {secs}s as 'iphone-hid'"
    if cmd == "move":
        hid.move(int(args[0]), int(args[1]))
    elif cmd == "corner":
        hid.corner()
    elif cmd == "click":
        hid.click(args[0] if args else "left")
    elif cmd == "down":
        hid.press(args[0] if args else "left")
    elif cmd == "up":
        hid.release()
    elif cmd == "scroll":
        hid.scroll(int(args[0]))
    elif cmd == "key":
        name, mods = args[0].lower(), 0
        for m in args[1:]:
            mods |= MODS[m.lower()]
        if name in NAMED:
            code = NAMED[name]
        else:
            code, shift = CHARS[name]
            mods |= shift
        hid.key(code, mods)
    elif cmd == "type":
        hid.type(rest)
    else:
        return f"err unknown command {cmd!r}"
    return "ok"


def serve_client(conn):
    with conn, conn.makefile("rw") as f:
        for line in f:
            if not line.strip():
                continue
            try:
                reply = run_command(line)
            except Exception as e:
                reply = f"err {e}"
            f.write(reply + "\n")
            f.flush()


def command_server():
    try:
        os.unlink(SOCK_PATH)
    except FileNotFoundError:
        pass
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.bind(SOCK_PATH)
    os.chmod(SOCK_PATH, 0o660)
    gid = int(os.environ.get("HID_GID", "0"))
    os.chown(SOCK_PATH, 0, gid)
    s.listen(4)
    log("commands on", SOCK_PATH)
    while True:
        conn, _ = s.accept()
        threading.Thread(target=serve_client, args=(conn,), daemon=True).start()


def main():
    setup_dbus()
    threading.Thread(target=accept_loop, daemon=True).start()
    threading.Thread(target=command_server, daemon=True).start()
    GLib.MainLoop().run()


if __name__ == "__main__":
    main()
