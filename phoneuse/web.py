"""The browser mirror: the phone's screen, with mouse and keyboard, on a local
web page (http://localhost:PORT, `web_port` in config.toml).

UxPlay sends the phone's H.264 stream here as RTP over localhost, as it does to
the mirror window. iOS sends a full keyframe only when mirroring starts, so a
browser tab that opens later couldn't decode the original stream. This server
therefore decodes the stream once and encodes it again for browsers (NVENC
when available). It keeps the last decoded frame, and when a tab joins it
encodes that frame again as a keyframe, so the tab shows the phone right away.

Each tab gets encoded frames over a WebSocket and decodes them itself
(WebCodecs). Mouse and keyboard events come back over the same WebSocket and
go to the phone through pointer.py, like the mirror window's. Input is only
accepted while the phone is mirroring and the tab is showing it.

Listens on 127.0.0.1 only: anyone who can open the page can control the phone.
"""
import asyncio
import json
import os
import sys
import threading
import time

import gi

gi.require_version("Gst", "1.0")
gi.require_version("GstVideo", "1.0")
from gi.repository import Gst, GstVideo  # noqa: E402
from aiohttp import web  # noqa: E402

from . import screen  # noqa: E402
from .config import CFG, NAME, SCREEN_PT, decoder  # noqa: E402
from .hidclient import Hid  # noqa: E402
from .pointer import Keys, Pointer  # noqa: E402

HERE = os.path.dirname(os.path.realpath(__file__))
PAGE = os.path.join(HERE, "web", "index.html")
PORT = int(CFG.get("web_port", 8777))
RTP_PORT = screen.WEB_RTP_PORT


def log(*a):
    print(time.strftime("%H:%M:%S"), "web:", *a, flush=True)


def encoder(dec):
    """H.264 encoder for browsers: no B-frames or lookahead (each frame leaves
    the encoder as soon as it is encoded), keyframes only on request, high
    quality for text."""
    if dec.startswith("nvh264dec"):
        return ("nvh264enc preset=p4 tune=ultra-low-latency zerolatency=true bframes=0 gop-size=-1 "
                "rc-mode=vbr const-quality=20 max-bitrate=40000 repeat-sequence-header=true")
    return "x264enc tune=zerolatency speed-preset=veryfast key-int-max=0 pass=quant quantizer=20"


class Stream:
    """Decode the phone's stream, keep the last frame, encode for browsers."""

    def __init__(self, dec, on_frame):
        self.on_frame = on_frame  # (bytes, is_keyframe), called from a GStreamer thread
        self.last = None  # last decoded frame (a Gst.Buffer)
        self.caps = None
        self.frames_at = 0.0  # when the last frame arrived from the phone
        rtp = "application/x-rtp,media=video,encoding-name=H264,clock-rate=90000,payload=96"
        # One pipeline for both halves, so the decoder and encoder share a GPU context.
        self.pipe = Gst.parse_launch(
            f'udpsrc address=127.0.0.1 port={RTP_PORT} buffer-size=8388608 caps="{rtp}" '
            f"! rtph264depay ! h264parse ! {dec} ! appsink name=raw sync=false async=false emit-signals=true "
            f"appsrc name=src is-live=true format=time do-timestamp=true "
            f"! {encoder(dec)} ! h264parse ! video/x-h264,stream-format=byte-stream,alignment=au "
            f"! appsink name=enc sync=false async=false emit-signals=true")
        self.src = self.pipe.get_by_name("src")
        self.enc = self.pipe.get_by_name("enc")
        self.pipe.get_by_name("raw").connect("new-sample", self._decoded)
        self.enc.connect("new-sample", self._encoded)
        bus = self.pipe.get_bus()
        bus.add_signal_watch()
        bus.connect("message::error", self._error)
        self.pipe.set_state(Gst.State.PLAYING)

    def _decoded(self, sink):
        sample = sink.emit("pull-sample")
        if self.caps is None or not sample.get_caps().is_equal(self.caps):
            self.caps = sample.get_caps()
            self.src.set_property("caps", self.caps)
        self.last = sample.get_buffer()
        self.frames_at = time.time()
        self.src.emit("push-buffer", self.last.copy())
        return Gst.FlowReturn.OK

    def _encoded(self, sink):
        buf = sink.emit("pull-sample").get_buffer()
        ok, info = buf.map(Gst.MapFlags.READ)
        if ok:
            self.on_frame(bytes(info.data), not buf.has_flags(Gst.BufferFlags.DELTA_UNIT))
            buf.unmap(info)
        return Gst.FlowReturn.OK

    def keyframe(self):
        """Encode the last frame again, as a keyframe (a tab just joined)."""
        self.enc.send_event(GstVideo.video_event_new_upstream_force_key_unit(Gst.CLOCK_TIME_NONE, True, 0))
        if self.last is not None:
            self.src.emit("push-buffer", self.last.copy())

    def forget(self):
        """Mirroring ended: the last frame no longer shows the phone."""
        self.last = None

    def _error(self, _bus, msg):
        err, _ = msg.parse_error()
        log("stream error:", err.message)


class Mirror:
    def __init__(self, dec):
        self.loop = None
        self.tabs = set()
        self.stream = Stream(dec, self._frame)
        self.mirroring = False
        self.hid = None

    def get_hid(self):
        if self.hid is None:
            self.hid = Hid()
        return self.hid

    def live(self):
        return self.mirroring and self.stream.last is not None

    def _frame(self, data, key):
        self.loop.call_soon_threadsafe(self._send_frame, data, key)

    def _send_frame(self, data, key):
        for tab in list(self.tabs):
            if key:
                tab.synced = True
            if tab.synced:
                tab.send(bytes([1 if key else 0]) + data)

    async def watch(self):
        # Follow whether the phone is mirroring (the same check as the window's).
        while True:
            now = screen.airplay_mirroring()
            if now != self.mirroring:
                self.mirroring = now
                if not now:
                    self.stream.forget()
                for tab in list(self.tabs):
                    tab.state()
            elif now and self.stream.last is not None:
                for tab in list(self.tabs):
                    if not tab.told_live:
                        tab.state()
            await asyncio.sleep(0.25)


class Tab:
    """One browser tab: its video feed and its input."""

    def __init__(self, mirror, ws):
        self.mirror, self.ws = mirror, ws
        self.synced = False  # has had a keyframe
        self.playing = False  # has shown a frame (the page says so)
        self.told_live = False
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
        msg = json.dumps({"type": "state", "live": live, "name": NAME, "screen": SCREEN_PT,
                          "bezel": screen.BEZEL, "radius": screen.SCREEN_RADIUS})
        asyncio.ensure_future(self.ws.send_str(msg))

    async def pump(self):
        while True:
            await self.ws.send_bytes(await self.queue.get())

    def handle(self, msg):
        t = msg.get("t")
        if t == "playing":
            self.playing = True
            return
        if t == "keyframe":  # the tab's decoder failed and starts over
            self.synced = False
            self.mirror.stream.keyframe()
            return
        if t == "blur" or not (self.playing and self.mirror.live()):
            self.pointer.release()
            self.keys.release_all()
            return
        if t == "move":
            self.pointer.hover(msg["x"], msg["y"])
        elif t == "down":
            self.pointer.press(msg["x"], msg["y"])
        elif t == "up":
            self.pointer.release()
        elif t == "mod":
            self.keys.modifier(int(msg["bit"]), bool(msg["down"]))
        elif t == "key":
            self.keys.key(int(msg["usage"]), bool(msg["down"]))

    def close(self):
        try:
            self.pointer.close()
            self.keys.release_all()
        except Exception as e:
            log("closing tab:", e)


def app(mirror):
    async def page(_req):
        return web.FileResponse(PAGE, headers={"Cache-Control": "no-cache"})

    async def ws(req):
        sock = web.WebSocketResponse(max_msg_size=1 << 16)
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

    a = web.Application()
    a.router.add_get("/", page)
    a.router.add_get("/ws", ws)
    return a


def main():
    Gst.init(None)
    dec = os.environ.get("PHONEUSE_DECODER") or decoder()
    mirror = Mirror(dec)
    # GStreamer's bus signals need a GLib main loop; run one beside asyncio.
    from gi.repository import GLib
    threading.Thread(target=GLib.MainLoop().run, daemon=True).start()

    async def start():
        mirror.loop = asyncio.get_running_loop()
        runner = web.AppRunner(app(mirror), access_log=None)
        await runner.setup()
        await web.TCPSite(runner, "127.0.0.1", PORT).start()
        log(f"browser mirror on http://localhost:{PORT}")
        await mirror.watch()

    try:
        asyncio.run(start())
    except OSError as e:
        log("can't serve:", e)
        sys.exit(1)


if __name__ == "__main__":
    main()
