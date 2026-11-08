#!/usr/bin/env python3
"""A mock of the PC's companion API (docs/COMPANION.md) for testing the iOS app.

    python3 -m venv .venv && .venv/bin/pip install cryptography
    .venv/bin/python mock_server.py [--host 127.0.0.1] [--port 8778] [--open]

It prints a pairing link (--open opens it in the booted simulator), checks every request's signature, time
and nonce the way the PC does, unseals secrets, and keeps a state that the endpoints change. Every request is
logged to stdout as one JSON line. --bonjour advertises _phoneuse._tcp with dns-sd.
"""

import argparse
import hmac
import json
import os
import secrets
import subprocess
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from companion_crypto import b64url_encode, sign, unseal

PC_ID = "a1b2c3d4e5f60718"
PC_NAME = "mock-pc"


def initial_state():
    now = int(time.time())
    return {
        "pc": {"id": PC_ID, "name": PC_NAME, "version": "mock"},
        "mirroring": True,
        "phone": "LXEPhone17Pro",
        "bluetooth": {"connected": True, "via": "bridge"},
        "agent": {"state": "driving", "action": "Opening Gmail", "since": now - 95, "steps": 12},
        "awake": False,
        "audio": {"on": True, "needs_remirror": False},
        "session": {"ask": False, "pending": {"id": "s1", "since": now - 3, "action": "Opening Gmail"}},
        "unlock": {"passcode_saved": False, "pending": {"id": "u1", "since": now - 5}},
        "bridge": {"saved": True, "id": "bridge-01", "ip": "192.168.0.51", "ssid": "Giraffe IoT", "use": True,
                   "online": True, "rtt_ms": 15},
    }


NETWORKS = [
    {"ssid": "Giraffe IoT", "rssi": -48, "secure": True},
    {"ssid": "Giraffe", "rssi": -55, "secure": True},
    {"ssid": "Coffee Shop", "rssi": -71, "secure": False},
]


class Mock:
    def __init__(self, key: bytes, cursor_delay: float):
        self.key = key
        self.cursor_delay = cursor_delay
        self.state = initial_state()
        self.nonces: dict[str, float] = {}
        self.passcode = None
        self.push = {}
        self.keyboard_shown = False
        self.lock = threading.Lock()


class Handler(BaseHTTPRequestHandler):
    mock: Mock
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):
        pass

    def log(self, status, note=None, body=None):
        entry = {"t": time.strftime("%H:%M:%S"), "method": self.command, "path": self.path, "status": status}
        if body is not None:
            entry["body"] = body
        if note:
            entry["note"] = note
        print(json.dumps(entry), flush=True)

    def reply(self, status, obj, note=None, body=None):
        data = json.dumps(obj).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)
        self.log(status, note, body)

    def error(self, status, message, body=None):
        self.reply(status, {"error": message}, note=message, body=body)

    def check(self, body: bytes):
        t = self.headers.get("X-PU-Time", "")
        nonce = self.headers.get("X-PU-Nonce", "")
        sig = self.headers.get("X-PU-Sig", "")
        if not (t.isdigit() and len(nonce) == 32 and sig):
            return "Missing or malformed signature headers."
        if abs(time.time() - int(t)) > 60:
            return "The phone's clock is more than a minute off."
        expected = sign(self.mock.key, self.command, self.path, t, nonce, body)
        if not hmac.compare_digest(expected, sig):
            return "Bad signature. Pair the app again."
        now = time.time()
        with self.mock.lock:
            self.mock.nonces = {n: s for n, s in self.mock.nonces.items() if now - s < 120}
            if nonce in self.mock.nonces:
                return "Replayed request."
            self.mock.nonces[nonce] = now
        return None

    def handle_any(self):
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
        problem = self.check(raw)
        if problem:
            return self.error(401, problem)
        try:
            body = json.loads(raw) if raw else {}
        except ValueError:
            return self.error(400, "The body isn't JSON.")
        logged = {k: ("<sealed>" if k == "sealed" else v) for k, v in body.items()} if body else None
        m, s = self.mock, self.mock.state
        route = (self.command, urllib.parse.urlsplit(self.path).path)

        def ok(note=None, extra=None):
            self.reply(200, {"ok": True, **(extra or {})}, note, logged)

        def need_bool():
            if not isinstance(body.get("on"), bool):
                self.error(400, '"on" must be true or false.', logged)
                return None
            return body["on"]

        if route == ("GET", "/v1/state"):
            with m.lock:
                return self.reply(200, s)
        if route == ("POST", "/v1/agent/takeover"):
            s["agent"]["state"] = "paused"
            return ok()
        if route == ("POST", "/v1/agent/resume"):
            s["agent"]["state"] = "driving"
            return ok()
        if route == ("POST", "/v1/session/ask"):
            on = need_bool()
            if on is None:
                return
            s["session"]["ask"] = on
            return ok()
        if route == ("POST", "/v1/session/answer"):
            pending = s["session"]["pending"]
            if not pending or pending["id"] != body.get("id") or not isinstance(body.get("approve"), bool):
                return self.error(400, "There is no such session request.", logged)
            s["session"]["pending"] = None
            return ok("allowed" if body["approve"] else "denied")
        if route == ("POST", "/v1/unlock/answer"):
            pending = s["unlock"]["pending"]
            if not pending or pending["id"] != body.get("id") or not isinstance(body.get("approve"), bool):
                return self.error(400, "There is no such unlock request.", logged)
            s["unlock"]["pending"] = None
            return ok("approved" if body["approve"] else "denied")
        if route == ("POST", "/v1/passcode"):
            try:
                m.passcode = unseal(m.key, "passcode", body["sealed"])
            except Exception:
                return self.error(400, "The passcode couldn't be unsealed.", logged)
            s["unlock"]["passcode_saved"] = True
            return ok(f"passcode unsealed, {len(m.passcode)} digits")
        if route == ("DELETE", "/v1/passcode"):
            m.passcode = None
            s["unlock"]["passcode_saved"] = False
            return ok()
        if route == ("POST", "/v1/awake"):
            on = need_bool()
            if on is None:
                return
            s["awake"] = on
            return ok()
        if route == ("POST", "/v1/keyboard"):
            m.keyboard_shown = not m.keyboard_shown
            return ok("keyboard " + ("shown" if m.keyboard_shown else "hidden"))
        if route == ("POST", "/v1/cursor"):
            on = need_bool()
            if on is None:
                return
            time.sleep(m.cursor_delay)
            return ok("pointer " + ("on" if on else "off"))
        if route == ("POST", "/v1/bridge/use"):
            on = need_bool()
            if on is None:
                return
            if not s["bridge"]:
                return self.error(409, "There is no bridge.", logged)
            s["bridge"]["use"] = on
            s["bluetooth"]["via"] = "bridge" if on else "pc"
            return ok()
        if route == ("GET", "/v1/bridge/networks"):
            return self.reply(200, {"networks": NETWORKS})
        if route == ("POST", "/v1/bridge/network"):
            ssid = body.get("ssid")
            if not any(n["ssid"] == ssid for n in NETWORKS):
                return self.error(400, "The bridge doesn't see that network.", logged)
            password = ""
            if "sealed" in body:
                try:
                    password = unseal(m.key, "password", body["sealed"])
                except Exception:
                    return self.error(400, "The password couldn't be unsealed.", logged)
            s["bridge"]["ssid"] = ssid
            return ok(f"bridge moved to {ssid}, password unsealed ({len(password)} chars)")
        if route == ("POST", "/v1/mirror/audio"):
            on = need_bool()
            if on is None:
                return
            s["audio"] = {"on": on, "needs_remirror": True}
            s["mirroring"] = False
            return ok(extra={"needs_remirror": True})
        if route == ("POST", "/v1/push"):
            m.push.update({k: v for k, v in body.items() if v})
            return ok("tokens: " + ", ".join(sorted(m.push)))
        return self.error(404, "Unknown endpoint.", logged)

    do_GET = do_POST = do_DELETE = handle_any


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1", help="address to listen on and to put in the link")
    ap.add_argument("--port", type=int, default=8778)
    ap.add_argument("--key", help="pairing key, base64url (default: random)")
    ap.add_argument("--cursor-delay", type=float, default=3.0, help="seconds POST /v1/cursor takes")
    ap.add_argument("--open", action="store_true", help="open the pairing link in the booted simulator")
    ap.add_argument("--agent", default="driving", choices=["idle", "driving", "paused"],
                    help="the agent's state at start")
    ap.add_argument("--bonjour", action="store_true", help="advertise _phoneuse._tcp with dns-sd")
    args = ap.parse_args()

    from companion_crypto import b64url_decode
    key = b64url_decode(args.key) if args.key else secrets.token_bytes(32)
    Handler.mock = Mock(key, args.cursor_delay)
    Handler.mock.state["agent"]["state"] = args.agent
    link = "phoneuse://pair?" + urllib.parse.urlencode(
        {"id": PC_ID, "name": PC_NAME, "host": args.host, "port": args.port, "key": b64url_encode(key)},
        quote_via=urllib.parse.quote)
    print(link, flush=True)
    if args.bonjour:
        subprocess.Popen(["dns-sd", "-R", PC_NAME, "_phoneuse._tcp", "local", str(args.port),
                          f"id={PC_ID}", f"name={PC_NAME}"], stdout=subprocess.DEVNULL)
    if args.open:
        subprocess.run(["xcrun", "simctl", "openurl", "booted", link], check=False)
    ThreadingHTTPServer((args.host, args.port), Handler).serve_forever()


if __name__ == "__main__":
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    main()
