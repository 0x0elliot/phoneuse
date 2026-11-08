"""The browser mirror: the phone's screen, with mouse and keyboard, on a local
web page (http://localhost:PORT, `web_port` in config.toml).

The video comes from the hub (hub.py) as RTP over localhost. When a tab joins,
this server asks the hub for a keyframe, so the tab shows the phone right away.

Each tab gets encoded frames over a WebSocket and decodes them itself
(WebCodecs). Mouse and keyboard events come back over the same WebSocket and
go to the phone through pointer.py, like the mirror window's. Input is only
accepted while the phone is mirroring and the tab is showing it.

Listens on 127.0.0.1 only: anyone who can open the page can control the phone.

Unlocking: the page's settings panel saves the phone's passcode in
~/.config/phoneuse/passcode (mode 600). `phoneuse unlock` asks to use it (POST /api/unlock); the owner answers on
the page or in a desktop notification, and only then is it typed (unlock.py).
"""
import asyncio
import json
import os
import secrets
import sys
import threading
import time

import gi

gi.require_version("Gst", "1.0")
from gi.repository import Gst  # noqa: E402
from aiohttp import web  # noqa: E402

from . import screen, unlock  # noqa: E402
from .config import CFG, NAME, SCREEN_PT, config_path  # noqa: E402
from .hidclient import Hid  # noqa: E402
from .pointer import Keys, Pointer  # noqa: E402

# Where the pointer rests while nobody uses the phone (after Bluetooth reconnects,
# after an agent session, and during keep-awake nudges): the very bottom left corner,
# clear of the dock and the home bar, where it covers nothing and touches nothing.
PARK = (0.03, 0.995)

HERE = os.path.dirname(os.path.realpath(__file__))
PAGE = os.path.join(HERE, "web", "index.html")
PORT = int(CFG.get("web_port", 8777))
RTP_PORT = screen.WEB_RTP_PORT


def log(*a):
    print(time.strftime("%H:%M:%S"), "web:", *a, flush=True)


class Stream:
    """The hub's stream (hub.py), as H.264 access units for the tabs."""

    def __init__(self, on_frame):
        self.on_frame = on_frame  # (bytes, is_keyframe), called from a GStreamer thread
        rtp = "application/x-rtp,media=video,encoding-name=H264,clock-rate=90000,payload=96"
        self.pipe = Gst.parse_launch(
            f'udpsrc address=127.0.0.1 port={RTP_PORT} buffer-size=8388608 caps="{rtp}" '
            "! rtph264depay ! h264parse config-interval=-1 ! video/x-h264,stream-format=byte-stream,alignment=au "
            "! appsink name=enc sync=false async=false emit-signals=true")
        self.pipe.get_by_name("enc").connect("new-sample", self._frame)
        bus = self.pipe.get_bus()
        bus.add_signal_watch()
        bus.connect("message::error", self._error)
        self.pipe.set_state(Gst.State.PLAYING)

    def _frame(self, sink):
        buf = sink.emit("pull-sample").get_buffer()
        ok, info = buf.map(Gst.MapFlags.READ)
        if ok:
            self.on_frame(bytes(info.data), not buf.has_flags(Gst.BufferFlags.DELTA_UNIT))
            buf.unmap(info)
        return Gst.FlowReturn.OK

    @staticmethod
    def keyframe():
        """Ask the hub for a keyframe (a tab joined or its decoder started over)."""
        try:
            screen.hub_request("keyframe")
        except OSError as e:
            log("hub:", e)

    def _error(self, _bus, msg):
        err, _ = msg.parse_error()
        log("stream error:", err.message)


class Mirror:
    def __init__(self):
        self.loop = None
        self.tabs = set()
        self.stream = Stream(self._frame)
        self.mirroring = False
        self.hub_live = False
        self.hid = None
        self.taken_over = False
        self.agent_until = 0.0
        self.bluetooth = True  # the phone's Bluetooth link (mouse and keyboard)
        self.last_frame_at = 0.0  # when the phone's picture last changed
        self.stale = False  # the picture stopped following the phone (see check_stale)
        self.last_input_at = 0.0  # when the page or an agent last sent input
        self.awake = os.path.exists(AWAKE_FILE)  # keep the screen awake (see keep_awake)
        self.screen_dark = False  # a keep-awake nudge drew no frame: the screen is off
        self.hover_at = PARK  # where the page's pointer last was (screen fractions)
        self.agent_action = ""  # what the agent is doing, for the companion app's Live Activity
        self.agent_phase = "thinking"  # acting (sending input), reading (the screen) or thinking (between actions)
        self.phase_at = 0.0  # when agent_phase last changed
        self.agent_steps = 0  # actions in this agent session
        self.agent_started = 0.0  # when this agent session started
        self.unlocks = None
        self.sessions = None

    def get_hid(self):
        if self.hid is None:
            self.hid = Hid()
        return self.hid

    def live(self):
        return self.mirroring and self.hub_live

    # ---- keep awake: stop Auto-Lock while nobody uses the phone ----
    AWAKE_EVERY = 1.0  # seconds between nudges
    AWAKE_QUIET = 2.0  # skip nudges this long after real input

    def set_awake(self, on):
        self.awake = on
        if on:
            os.makedirs(os.path.dirname(AWAKE_FILE), exist_ok=True)
            open(AWAKE_FILE, "w").close()
        elif os.path.exists(AWAKE_FILE):
            os.remove(AWAKE_FILE)
        self.screen_dark = False
        log("keep awake", "on" if on else "off")
        self.broadcast_state()

    async def keep_awake(self):
        """While on, move the pointer a few pixels and back about once a second so
        Auto-Lock never fires. Real input (the page, an agent) takes over; a nudge
        that draws no new frame means the screen is off (the pointer always shows
        when it moves), so nudging pauses until the picture changes again rather
        than waking a phone that was just locked."""
        # Absolute moves: they land exactly on every phone, while a small relative
        # move can shift the pointer less than a pixel at a slow tracking speed.
        sign, misses = 1, 0
        loop = asyncio.get_running_loop()
        while True:
            await asyncio.sleep(self.AWAKE_EVERY)
            if (not self.awake or self.screen_dark or not self.live() or self.agent() != "idle"
                    or time.time() - self.last_input_at < self.AWAKE_QUIET):
                continue
            before = self.last_frame_at
            try:
                x, y = PARK
                x += 0.01 * sign
                r = await loop.run_in_executor(None, self.get_hid().cmd, f"a {x:.4f} {min(max(y, 0.0), 1.0):.4f} 0")
            except Exception:
                self.hid = None
                continue
            sign = -sign
            if "dropped" in r:  # the link was busy; this nudge never left
                continue
            await asyncio.sleep(0.8)
            if self.last_frame_at != before or time.time() - self.last_input_at < self.AWAKE_QUIET:
                misses = 0
                continue
            misses += 1
            if misses >= 3:  # three nudges in a row drew nothing: the screen is off
                misses = 0
                self.screen_dark = True
                log("keep awake: no picture after three nudges; the screen is off, pausing")

    # Releasing the link while idle (so iOS shows its own keyboard) is off: after
    # phoneuse drops the link, iOS refuses phoneuse's reconnects ("Connection
    # refused", measured 2026-11-07) until the owner taps PhoneUse in Bluetooth
    # settings, so the next input could never reach the phone. The daemon keeps
    # its release command for a better trigger.
    RELEASE_IDLE = None

    def bluetooth_up(self):
        """Whether the link works: connected, or released on purpose."""
        try:
            st = self.get_hid().cmd("status")
            return "connected=True" in st or "released=True" in st
        except Exception:
            self.hid = None
            return False

    # ---- agent sessions: who is driving the phone ----
    # An agent session ends this long after its last action (s). An agent's model can
    # think for a while between actions, and with "ask before agent starts" on, the
    # owner's approval lasts exactly as long as this visible session.
    AGENT_IDLE = 60.0

    def agent(self):
        """"driving" while an agent acts (the page shows it and takes no input),
        "paused" after the user took over, else "idle"."""
        if self.taken_over:
            return "paused"
        return "driving" if time.time() < self.agent_until else "idle"

    THINK_AFTER = 3.0  # an agent quiet this long after acting or reading is thinking

    def current_phase(self):
        """What the agent does now: acting, reading, or thinking once it has been quiet
        for THINK_AFTER seconds (no tool call tells us when its model starts thinking)."""
        if self.agent_phase in ("acting", "reading") and time.time() - self.phase_at > self.THINK_AFTER:
            return "thinking"
        return self.agent_phase

    def agent_acts(self, action="", phase="acting"):
        """Called before every agent action (CLI or MCP). False while the user has
        taken over: the agent must stop."""
        if self.taken_over:
            return False
        was = self.agent()
        if was != "driving":
            self.agent_started, self.agent_steps = time.time(), 0
        self.agent_steps += 1
        self.agent_action = action or self.agent_action
        self.agent_phase, self.phase_at = phase, time.time()
        msg = json.dumps({"type": "agent-action", "action": self.agent_action, "steps": self.agent_steps})
        for tab in list(self.tabs):
            asyncio.ensure_future(tab.ws.send_str(msg))
        self.agent_until = time.time() + self.AGENT_IDLE
        self.last_input_at = time.time()
        if was != "driving":
            self.broadcast_state()
        # Tell the pages when the session runs out, so none keeps showing (and
        # obeying) a session that is over.
        if self.loop:
            self.loop.call_soon_threadsafe(self.loop.call_later, self.AGENT_IDLE + 0.1, self._agent_expired)
        return True

    def park(self):
        """Move the pointer to PARK, out of the way (in a thread: the link can be slow)."""
        def go():
            try:
                self.get_hid().cmd(f"a {PARK[0]} {PARK[1]} 0")
            except Exception:
                self.hid = None
        if self.live():
            threading.Thread(target=go, daemon=True).start()

    def _agent_expired(self):
        if self.agent() == "idle":
            self.park()
            self.broadcast_state()

    def take_over(self, take):
        self.taken_over = take
        self.agent_until = 0.0
        if take and self.sessions:
            self.sessions.end()
        elif self.sessions:
            threading.Thread(target=self.sessions.sync_gate, daemon=True).start()
        self.broadcast_state()

    STALE_INPUT = 1.5  # s: input that should change the picture, with no new frame since
    STALE_CLOCK = 4.0  # s past a minute boundary (the status-bar clock changes) with no new frame

    def check_stale(self):
        """Whether the mirror shows an old picture: input went to the phone and no frame
        followed, or a minute rolled over (the phone's clock changed) and no frame
        arrived. Either means the phone's screen is off, or mirroring stalled or lags.
        Agents get a warning with every screen read; the pages show it."""
        now = time.time()
        if not self.live() or not self.last_frame_at:
            stale = False
        else:
            unanswered = self.last_input_at > self.last_frame_at and now - self.last_input_at > self.STALE_INPUT
            clock = now > (self.last_frame_at // 60 + 1) * 60 + self.STALE_CLOCK
            stale = unanswered or clock
        if stale != self.stale:
            self.stale = stale
            log("the picture " + ("stopped updating: the phone's screen is off, or mirroring stalled"
                                  if stale else "is updating again"))
            self.broadcast_state()
        return stale

    def broadcast_state(self):
        for tab in list(self.tabs):
            tab.state()

    def _frame(self, data, key):
        self.last_frame_at = time.time()
        if self.stale:
            self.loop.call_soon_threadsafe(self.check_stale)
        if self.screen_dark:
            self.screen_dark = False
        self.loop.call_soon_threadsafe(self._send_frame, data, key)

    def _send_frame(self, data, key):
        for tab in list(self.tabs):
            if key:
                tab.synced = True
            if tab.synced:
                tab.send(bytes([1 if key else 0]) + data)

    async def watch(self):
        # Stay subscribed to the hub, and follow whether the phone is mirroring and
        # the hub has a picture of it.
        loop = asyncio.get_running_loop()
        joined = False
        while True:
            try:
                line, _ = await loop.run_in_executor(None, screen.hub_request, f"{'keep' if joined else 'join'} {RTP_PORT}")
                joined = line.startswith("ok")
                line, _ = await loop.run_in_executor(None, screen.hub_request, "status")
                self.hub_live = "live=1" in line
            except OSError:
                joined, self.hub_live = False, False  # the hub is (re)starting
            mirroring = screen.airplay_mirroring()
            bt = await loop.run_in_executor(None, self.bluetooth_up)
            changed = mirroring != self.mirroring or bt != self.bluetooth
            if bt and not self.bluetooth:  # (re)connected: rest the pointer where it touches nothing
                self.hover_at = PARK
                try:
                    await asyncio.get_running_loop().run_in_executor(
                        None, self.get_hid().cmd, f"a {PARK[0]} {PARK[1]} 0")
                    log("Bluetooth back: pointer parked at the bottom middle")
                except Exception:
                    self.hid = None
            self.mirroring, self.bluetooth = mirroring, bt
            for tab in list(self.tabs):
                if changed or tab.told_live != self.live() or tab.told_agent != self.agent():
                    tab.state()
            await asyncio.sleep(0.5)


class Tab:
    """One browser tab: its video feed and its input."""

    def __init__(self, mirror, ws):
        self.mirror, self.ws = mirror, ws
        self.synced = False  # has had a keyframe
        self.playing = False  # has shown a frame (the page says so)
        self.told_live = False
        self.told_agent = None
        self.pointer = Pointer(mirror.get_hid, log)
        self.keys = Keys(mirror.get_hid)
        self.queue = asyncio.Queue(maxsize=8)

    def send(self, data):
        # Drop frames for a tab that can't keep up rather than queueing delay;
        # it gets a keyframe to start again from.
        if self.queue.full():
            self.synced = False
            while not self.queue.empty():
                self.queue.get_nowait()
            self.mirror.stream.keyframe()
            return
        self.queue.put_nowait(data)

    def state(self):
        live = self.mirror.live()
        self.told_live = live
        self.told_agent = self.mirror.agent()
        msg = json.dumps({"type": "state", "live": live, "mirroring": self.mirror.mirroring,
                          "agent": self.told_agent, "bluetooth": self.mirror.bluetooth,
                          "awake": self.mirror.awake, "stale": self.mirror.stale,
                          "name": NAME, "screen": SCREEN_PT,
                          "bezel": screen.BEZEL, "radius": screen.SCREEN_RADIUS})
        asyncio.ensure_future(self.ws.send_str(msg))

    async def pump(self):
        while True:
            await self.ws.send_bytes(await self.queue.get())

    def handle(self, msg):
        t = msg.get("t")
        if t in ("move", "down", "up", "scroll", "mod", "key", "consumer"):
            self.mirror.last_input_at = time.time()
            if "x" in msg:
                self.mirror.hover_at = (float(msg["x"]), float(msg["y"]))
        if t in ("move", "down", "up", "scroll", "mod", "key", "consumer", "blur") and os.path.exists(INPUT_TRACE + ".on"):
            # Debugging: `touch $XDG_RUNTIME_DIR/phoneuse-input.jsonl.on` logs the page's input.
            with open(INPUT_TRACE, "a") as f:
                f.write(json.dumps({"at": time.time(), **msg}) + "\n")
        if t == "playing":
            self.playing = True
            return
        if t == "keyframe":  # the tab's decoder failed and starts over
            self.synced = False
            self.mirror.stream.keyframe()
            return
        # While an agent drives, the page's mouse and keyboard don't reach the phone
        # (mixing in input would confuse the agent); the user takes over first.
        if t == "blur" or not (self.playing and self.mirror.live()) or self.mirror.agent() == "driving":
            self.pointer.release()
            self.keys.release_all()
            return
        if t == "move":
            self.pointer.hover(msg["x"], msg["y"])
        elif t == "down":
            self.pointer.press(msg["x"], msg["y"])
        elif t == "up":
            self.pointer.release()
        elif t == "scroll":  # fractions of the screen to drag the content by
            self.pointer.hover(msg["x"], msg["y"])
            self.pointer.scroll(msg["dx"] * SCREEN_PT[0], msg["dy"] * SCREEN_PT[1])
        elif t == "mod":
            self.keys.modifier(int(msg["bit"]), bool(msg["down"]))
        elif t == "key":
            self.keys.key(int(msg["usage"]), bool(msg["down"]))
        elif t == "consumer" and msg.get("key") in ("siri", "home", "search", "eject"):
            self.keys.consumer(msg["key"], bool(msg["down"]))

    def close(self):
        try:
            self.pointer.close()
            self.keys.release_all()
        except Exception as e:
            log("closing tab:", e)


AWAKE_FILE = os.path.join(os.path.dirname(config_path()), "keep-awake")  # exists while "keep the screen awake" is on
INPUT_TRACE = os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"), "phoneuse-input.jsonl")


def same_origin(req):
    """Requests from the page itself, not from other websites (which could send
    the browser here): their Origin must be this server."""
    return req.headers.get("Origin") in (f"http://localhost:{PORT}", f"http://127.0.0.1:{PORT}")


class UnlockRequests:
    """`phoneuse unlock` asks; the owner answers on the page or in a desktop
    notification; only then is the saved passcode typed (unlock.py)."""

    def __init__(self, mirror):
        self.mirror = mirror
        self.pending = None  # {"id", "event", "approved", "notice", "since"}
        self.companion = None

    def broadcast(self, msg):
        for tab in list(self.mirror.tabs):
            asyncio.ensure_future(tab.ws.send_str(json.dumps(msg)))

    async def ask(self, req):
        if self.pending:
            return web.json_response({"result": "another unlock request is waiting for the owner"}, status=409)
        if not await asyncio.get_running_loop().run_in_executor(None, unlock.saved):
            return web.json_response({"result": "no passcode saved: the owner can save one in the browser "
                                                "mirror's settings, or unlock the phone themselves"}, status=409)
        rid = secrets.token_hex(8)
        p = self.pending = {"id": rid, "event": asyncio.Event(), "approved": False, "notice": None,
                            "since": time.time()}
        self.broadcast({"type": "unlock-request", "id": rid})
        if self.companion:  # the companion app's notification, with Unlock and Deny
            asyncio.get_running_loop().run_in_executor(None, self.companion.push_unlock, rid)
        asyncio.ensure_future(self._notify(p))
        log("unlock requested; waiting for the owner")
        try:
            await asyncio.wait_for(p["event"].wait(), 120)
        except asyncio.TimeoutError:
            pass
        finally:
            self.pending = None
            self.broadcast({"type": "unlock-done"})
            if self.companion:
                asyncio.get_running_loop().run_in_executor(None, self.companion.push_request_over, "unlock", rid)
            if p["notice"] and p["notice"].returncode is None:
                p["notice"].kill()
        if not p["event"].is_set():
            return web.json_response({"result": "no answer from the owner within 2 minutes"})
        if not p["approved"]:
            log("unlock denied")
            return web.json_response({"result": "denied by the owner"})
        result = await asyncio.get_running_loop().run_in_executor(None, self._unlock)
        log("unlock:", result)
        return web.json_response({"result": result})

    @staticmethod
    def _unlock():
        try:
            from . import cli
            return unlock.unlock(cli.screen_text)
        except BaseException as e:  # cli helpers exit on errors; never take the server down
            return f"failed: {e}"

    async def _notify(self, p):
        # A desktop notification with Unlock / Deny, where the notification daemon supports actions.
        try:
            p["notice"] = await asyncio.create_subprocess_exec(
                "notify-send", "-a", "phoneuse", "-u", "critical", "--wait", "-A", "unlock=Unlock", "-A", "deny=Deny",
                "Unlock the iPhone?", f"Agent asks to enter your saved passcode. Answer here or at "
                f"http://localhost:{PORT}", stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
            out, _ = await p["notice"].communicate()
            answer = out.decode().strip()
            if answer in ("unlock", "deny") and self.pending is p:
                p["approved"] = answer == "unlock"
                p["event"].set()
        except (OSError, asyncio.CancelledError):
            pass

    async def answer(self, req):
        if not same_origin(req):
            return web.Response(status=403)
        body = await req.json()
        p = self.pending
        if not p or body.get("id") != p["id"]:
            return web.json_response({"ok": False})
        p["approved"] = bool(body.get("approve"))
        p["event"].set()
        return web.json_response({"ok": True})


ASK_FILE = os.path.join(os.path.dirname(config_path()), "ask-before-session")  # older setting: "ask"
START_FILE = os.path.join(os.path.dirname(config_path()), "agent-start.json")
START_MODES = ("auto", "countdown", "ask")  # go ahead / wait N s (then start) / ask me (wait for Allow)


def start_setting():
    """When an agent starts: {"mode": auto | countdown | ask, "seconds": 5..30}."""
    try:
        with open(START_FILE) as f:
            d = json.load(f)
    except (OSError, ValueError):
        d = {"mode": "ask" if os.path.exists(ASK_FILE) else "auto"}
    mode = d.get("mode") if d.get("mode") in START_MODES else "auto"
    seconds = int(min(30, max(5, d.get("seconds", 10))))
    return {"mode": mode, "seconds": seconds}


def set_start_setting(mode=None, seconds=None):
    cur = start_setting()
    if mode in START_MODES:
        cur["mode"] = mode
    if seconds is not None:
        cur["seconds"] = int(min(30, max(5, float(seconds))))
    with open(START_FILE, "w") as f:
        json.dump(cur, f)
    if os.path.exists(ASK_FILE):
        os.remove(ASK_FILE)  # moved into agent-start.json
    return cur


def ask_before_session():
    """Whether an agent's first action waits for the owner (a countdown or an Allow)."""
    return start_setting()["mode"] != "auto"


def set_ask_before_session(on):
    set_start_setting("ask" if on else "auto")


class SessionRequests:
    """With "ask before an agent session" on, an agent's first action waits until the owner
    allows the session: in the companion app's notification, a desktop notification or the
    browser mirror. Once allowed, the agent keeps the phone until it hands it back
    (`phoneuse done`), the owner takes over, or it sends no action for ASK_GAP
    seconds, the same moment the page and the Live Activity show the owner in control."""

    ASK_GAP = Mirror.AGENT_IDLE  # the approval ends when the visible session does
    WAIT = 120.0

    def __init__(self, mirror):
        self.mirror = mirror
        self.pending = None  # {"id", "event", "approved", "notice", "since", "action"}
        self.allowed_until = 0.0  # the allowed session lasts while actions keep coming
        self.companion = None

    def needed(self):
        return ask_before_session() and time.time() > self.allowed_until

    def acted(self):
        if ask_before_session():
            self.allowed_until = time.time() + self.ASK_GAP
        self.sync_gate()

    # The HID daemon enforces the approval (its agent gate): agents' input is refused
    # there unless this says the session is allowed. Its own connection, so a slow
    # input command on the shared one never delays the gate.
    _gate_hid = None
    _gate_sent = None

    def gate_value(self):
        if self.mirror.taken_over:
            return "closed"
        if not ask_before_session():
            return "open"
        return f"until {self.allowed_until:.3f}" if self.allowed_until > time.time() else "closed"

    def sync_gate(self, force=False):
        v = self.gate_value()
        if v == self._gate_sent and not force:
            return
        try:
            if self._gate_hid is None:
                self._gate_hid = Hid()
            self._gate_hid.cmd("gate " + v)
            self._gate_sent = v
        except Exception as e:
            self._gate_hid = None
            log("couldn't set the agent gate in the HID daemon:", e)

    async def keep_gate(self):
        """Resend the gate now and then: the daemon starts closed after a restart."""
        while True:
            await asyncio.sleep(2.0)
            await asyncio.get_running_loop().run_in_executor(None, self.sync_gate, True)

    def broadcast(self, msg):
        for tab in list(self.mirror.tabs):
            asyncio.ensure_future(tab.ws.send_str(json.dumps(msg)))

    async def ask(self, action):
        """True once the owner allows the session; else the reason it can't start.
        Concurrent first actions share one request. The request ends for everyone when
        the owner answers, after WAIT seconds, when the agent ends its session, or when
        every waiting agent gives up (its request was cancelled); the browser mirror,
        the desktop notification and the companion app all drop it then."""
        p = self.pending
        if not p:
            st = start_setting()
            now = time.time()
            p = self.pending = {"id": secrets.token_hex(8), "event": asyncio.Event(), "approved": False,
                                "notice": None, "since": now, "action": action, "waiters": 0,
                                "answered": False, "mode": st["mode"],
                                # countdown: the agent starts at the deadline unless the owner stops it
                                "deadline": now + st["seconds"] if st["mode"] == "countdown" else None}
            self.broadcast({"type": "session-request", "id": p["id"], "action": action, "mode": p["mode"],
                            "deadline": p["deadline"]})
            if self.companion:
                asyncio.get_running_loop().run_in_executor(None, self.companion.push_session, p["id"], action)
            asyncio.ensure_future(self._notify(p))
            log("an agent wants the phone; " + (f"starting in {st['seconds']} s unless the owner stops it"
                                               if p["deadline"] else "waiting for the owner"))
        p["waiters"] += 1
        try:
            limit = (p["deadline"] if p["deadline"] else p["since"] + self.WAIT) - time.time()
            await asyncio.wait_for(asyncio.shield(p["event"].wait()), max(0.0, limit))
        except asyncio.TimeoutError:
            if p["deadline"] and not p["event"].is_set():  # the countdown ran out: the agent starts
                p["approved"], p["answered"] = True, True
                self._close(p, "the countdown ran out; allowed")
            else:
                self._close(p, "timed out")
        finally:
            p["waiters"] -= 1
            if p["waiters"] == 0 and not p["event"].is_set():
                self._close(p, "the agent stopped waiting")  # cancelled: nobody waits any more
        if not p["answered"]:
            return "The owner didn't allow the agent session within 2 minutes. Stop and tell the user."
        if not p["approved"]:
            log("agent session declined")
            return "The owner declined the agent session. Stop; don't retry unless the user asks you to."
        self.allowed_until = time.time() + self.ASK_GAP
        await asyncio.get_running_loop().run_in_executor(None, self.sync_gate)  # open before the agent hears yes
        return True

    def _close(self, p, why):
        """End a request everywhere: the page's prompt, the desktop notification and
        the companion app's notification."""
        if not p["event"].is_set():
            p["event"].set()
        if self.pending is not p:
            return
        self.pending = None
        self.broadcast({"type": "session-done"})
        if p["notice"] and p["notice"].returncode is None:
            p["notice"].kill()
        if self.companion:
            asyncio.get_running_loop().run_in_executor(None, self.companion.push_request_over, "session", p["id"])
        log(f"agent session request over: {why}")

    def answer_id(self, rid, approve):
        p = self.pending
        if not p or rid != p["id"]:
            return False
        p["approved"], p["answered"] = bool(approve), True
        if p["approved"]:
            log("agent session allowed")
        self._close(p, "allowed" if p["approved"] else "declined")
        return True

    def end(self):
        """The agent handed the phone back (or the owner took over): forget the allowed
        session, and drop a request nobody needs now."""
        self.allowed_until = 0.0
        if self.pending:
            self._close(self.pending, "the agent ended its session")
        threading.Thread(target=self.sync_gate, daemon=True).start()

    async def answer(self, req):
        if not same_origin(req):
            return web.Response(status=403)
        body = await req.json()
        return web.json_response({"ok": self.answer_id(body.get("id"), body.get("approve"))})

    async def setting(self, req):
        # The browser mirror's settings: when an agent starts ({"mode", "seconds"}; the
        # older {"on": bool} means ask / go ahead).
        if req.method == "POST":
            if not same_origin(req):
                return web.Response(status=403)
            b = await req.json()
            if "mode" in b or "seconds" in b:
                set_start_setting(b.get("mode"), b.get("seconds"))
            else:
                set_ask_before_session(bool(b.get("on")))
            await asyncio.get_running_loop().run_in_executor(None, self.sync_gate)
        st = start_setting()
        return web.json_response({"on": st["mode"] != "auto", **st})

    async def _notify(self, p):
        try:
            p["notice"] = await asyncio.create_subprocess_exec(
                *(["notify-send", "-a", "phoneuse", "-u", "critical", "--wait", "-A", "deny=Stop",
                   "-A", "allow=Start now", f"Agent starts in {round(p['deadline'] - time.time())} s",
                   f"First step: {p['action'] or 'using the phone'}. Stop it here or at http://localhost:{PORT}"]
                  if p["deadline"] else
                  ["notify-send", "-a", "phoneuse", "-u", "critical", "--wait", "-A", "allow=Allow", "-A", "deny=Deny",
                   "Agent wants control of your iPhone",
                   f"First step: {p['action'] or 'using the phone'}. Answer here or at http://localhost:{PORT}"]),
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
            out, _ = await p["notice"].communicate()
            choice = out.decode().strip()
            if choice in ("allow", "deny"):
                self.answer_id(p["id"], choice == "allow")
        except OSError:
            pass


def app(mirror):
    unlocks = mirror.unlocks = UnlockRequests(mirror)
    sessions = mirror.sessions = SessionRequests(mirror)

    async def page(_req):
        return web.FileResponse(PAGE, headers={"Cache-Control": "no-cache"})

    async def passcode(req):
        # The page's settings panel: whether a passcode is saved, save one, or remove
        # it. The passcode itself is never sent back.
        loop = asyncio.get_running_loop()
        if req.method != "GET" and not same_origin(req):
            return web.Response(status=403)
        try:
            if req.method == "POST":
                await loop.run_in_executor(None, unlock.save, (await req.json()).get("code", ""))
            elif req.method == "DELETE":
                await loop.run_in_executor(None, unlock.forget)
        except (ValueError, OSError) as e:
            return web.json_response({"error": str(e)}, status=400)
        return web.json_response({"saved": await loop.run_in_executor(None, unlock.saved)})

    async def awake(req):
        # Keep the screen awake: the page's setting and `phoneuse awake on|off`.
        # Other websites can't switch it (a browser always sends their Origin).
        if req.headers.get("Origin") and not same_origin(req):
            return web.Response(status=403)
        if req.method == "POST":
            mirror.set_awake(bool((await req.json()).get("on")))
        return web.json_response({"on": mirror.awake})

    async def ws(req):
        sock = web.WebSocketResponse(max_msg_size=1 << 16, heartbeat=20)
        await sock.prepare(req)
        tab = Tab(mirror, sock)
        mirror.tabs.add(tab)
        tab.state()
        mirror.stream.keyframe()
        pump = asyncio.ensure_future(tab.pump())
        log("tab joined;", len(mirror.tabs), "open")
        try:
            async for m in sock:
                if m.type == web.WSMsgType.TEXT:
                    try:
                        tab.handle(json.loads(m.data))
                    except Exception as e:
                        log("input error:", e)
                        mirror.hid = None
        finally:
            pump.cancel()
            mirror.tabs.discard(tab)
            tab.close()
            log("tab left;", len(mirror.tabs), "open")
        return sock

    async def agent_act(req):
        # The CLI and MCP server call this before every agent action.
        try:
            action = str((await req.json()).get("action", ""))[:80]
        except ValueError:
            action = ""
        if not mirror.taken_over and mirror.sessions.needed():
            allowed = await mirror.sessions.ask(action)
            if allowed is not True:
                return web.json_response({"ok": False, "result": allowed}, status=409)
        if mirror.agent_acts(action):
            mirror.sessions.acted()
            return web.json_response({"ok": True})
        return web.json_response({"ok": False, "result": "The user took over the phone. Stop and wait; "
                                  "continue only when they tell you to (they resume you on the page)."},
                                 status=409)

    async def agent_phase(req):
        # The CLI and MCP server: "reading" while the agent reads the screen, "thinking" once an
        # action returns (its model works out the next step).
        try:
            phase = (await req.json()).get("phase")
        except ValueError:
            phase = None
        if mirror.agent() == "driving" and phase in ("reading", "thinking"):
            mirror.agent_phase, mirror.phase_at = phase, time.time()
        return web.json_response({"ok": True})

    async def keyboard(req):
        # The page's keyboard button: Eject shows or hides the on-screen keyboard.
        if not same_origin(req):
            return web.Response(status=403)
        try:
            await asyncio.get_running_loop().run_in_executor(None, mirror.get_hid().cmd, "eject")
            return web.json_response({"ok": True})
        except Exception as e:
            mirror.hid = None
            return web.json_response({"ok": False, "error": str(e)}, status=503)

    async def agent_cursor(req):
        # Where the agent points or touches, for the page's glowing dot.
        b = await req.json()
        msg = json.dumps({"type": "agent-cursor", "x": float(b["x"]), "y": float(b["y"]), "down": bool(b.get("down"))})
        for tab in list(mirror.tabs):
            asyncio.ensure_future(tab.ws.send_str(msg))
        return web.json_response({"ok": True})

    async def agent_done(_req):
        # The agent's session is over: control goes back to the page at once.
        mirror.agent_until = 0.0
        mirror.sessions.end()
        mirror.park()
        mirror.broadcast_state()
        return web.json_response({"ok": True})

    async def agent_takeover(req):
        if not same_origin(req):
            return web.Response(status=403)
        mirror.take_over(bool((await req.json()).get("take")))
        return web.json_response({"agent": mirror.agent()})

    a = web.Application()
    a.router.add_get("/", page)
    a.router.add_get("/ws", ws)
    a.router.add_route("*", "/api/passcode", passcode)
    a.router.add_post("/api/unlock", unlocks.ask)
    a.router.add_post("/api/agent/act", agent_act)
    a.router.add_post("/api/agent/phase", agent_phase)
    a.router.add_get("/api/picture", lambda _r: web.json_response(
        {"live": mirror.live(), "stale": mirror.stale, "paused": mirror.taken_over, "frame_age": round(time.time() - mirror.last_frame_at, 1)
         if mirror.last_frame_at else None}))
    a.router.add_post("/api/agent/takeover", agent_takeover)
    a.router.add_post("/api/agent/cursor", agent_cursor)
    a.router.add_post("/api/agent/done", agent_done)
    a.router.add_post("/api/keyboard", keyboard)
    a.router.add_route("*", "/api/awake", awake)
    from .bridge_web import BridgeRoutes
    BridgeRoutes(same_origin).add(a)
    a.router.add_post("/api/unlock/answer", unlocks.answer)
    a.router.add_post("/api/session/answer", sessions.answer)
    a.router.add_route("*", "/api/session/ask", sessions.setting)

    async def companion_pair(req):
        # `phoneuse app pair`: a one-time link that pairs the companion app.
        if req.headers.get("Origin") and not same_origin(req):
            return web.Response(status=403)
        from . import companion
        return web.json_response({"link": await asyncio.get_running_loop().run_in_executor(None, companion.new_pairing)})
    a.router.add_post("/api/companion/pair", companion_pair)
    return a


def main():
    Gst.init(None)
    mirror = Mirror()
    # GStreamer's bus signals need a GLib main loop; run one beside asyncio.
    from gi.repository import GLib
    threading.Thread(target=GLib.MainLoop().run, daemon=True).start()

    async def start():
        mirror.loop = asyncio.get_running_loop()
        runner = web.AppRunner(app(mirror), access_log=None)
        await runner.setup()
        await web.TCPSite(runner, "127.0.0.1", PORT).start()
        log(f"browser mirror on http://localhost:{PORT}")
        asyncio.ensure_future(mirror.keep_awake())
        asyncio.ensure_future(mirror.sessions.keep_gate())

        async def stale_loop():
            while True:
                await asyncio.sleep(0.5)
                mirror.check_stale()
        asyncio.ensure_future(stale_loop())
        try:  # the companion app's API on the local network (companion.py)
            from .companion import Companion
            c = mirror.unlocks.companion = mirror.sessions.companion = Companion(mirror, mirror.unlocks)
            await c.start()
        except OSError as e:
            log("companion API off:", e)
        await mirror.watch()

    try:
        asyncio.run(start())
    except OSError as e:
        log("can't serve:", e)
        sys.exit(1)


if __name__ == "__main__":
    main()
