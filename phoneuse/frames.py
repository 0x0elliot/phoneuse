"""The frames service: watches the phone's picture for agents. It tells when the
screen has settled after an action, and hands out screenshots.

It joins the video hub (hub.py) like any viewer, so it gets a keyframe whenever
it starts: unlike the hub, it can restart at any time without Screen Mirroring
being restarted. Control is a unix socket (config.FRAMES_SOCKET), one line per
request:

  status       "ok live=1 seq=N": live while it has a picture of the phone; N
               counts meaningful picture changes (not pointer moves or carets)
  settle [N|-] [Q]  wait until the picture is still (after change N's successor,
               when given) for Q seconds (default 0.1); at once when nothing changes
  shot         PNG of the current picture (2 px per phone point):
               "ok LENGTH\\n" + bytes
"""
import os
import socket
import threading
import time

import gi
import numpy as np

gi.require_version("Gst", "1.0")
gi.require_version("GstVideo", "1.0")
from gi.repository import GLib, Gst, GstVideo  # noqa: E402

from . import screen  # noqa: E402
from .config import FRAMES_SOCKET, SCREEN_PT, decoder  # noqa: E402


def log(*a):
    print(time.strftime("%H:%M:%S"), "frames:", *a, flush=True)


class Frames:
    def __init__(self, dec):
        self.last = None
        self.caps = None
        self.vinfo = None
        self.seq = 0  # meaningful picture changes (see _changed)
        self.frame_at = 0.0  # when the last meaningful change arrived
        self.ref = None  # luma thumbnail at the last meaningful change
        self.cv = threading.Condition()
        self.shot_lock = threading.Lock()
        rtp = "application/x-rtp,media=video,encoding-name=H264,clock-rate=90000,payload=96"
        # System memory: NVDEC's own CUDA surfaces get reused while we hold the last one.
        download = "video/x-raw ! " if dec.startswith("nvh264dec") else ""
        w, h = SCREEN_PT[0] * 2, SCREEN_PT[1] * 2
        self.pipe = Gst.parse_launch(
            f'udpsrc address=127.0.0.1 port={screen.FRAMES_RTP_PORT} buffer-size=8388608 caps="{rtp}" '
            f"! rtph264depay ! h264parse ! {dec} ! {download}appsink name=raw sync=false async=false emit-signals=true "
            f"appsrc name=shot format=time do-timestamp=true ! videoconvert ! videoscale "
            f"! video/x-raw,format=RGB,width={w},height={h} ! pngenc compression-level=1 "
            f"! appsink name=png sync=false async=false max-buffers=1 drop=true")
        self.shot_src = self.pipe.get_by_name("shot")
        self.png = self.pipe.get_by_name("png")
        self.pipe.get_by_name("raw").connect("new-sample", self._decoded)
        bus = self.pipe.get_bus()
        bus.add_signal_watch()
        bus.connect("message::error", lambda _b, m: log("stream error:", m.parse_error()[0].message))
        self.pipe.set_state(Gst.State.PLAYING)

    def _decoded(self, sink):
        sample = sink.emit("pull-sample")
        if self.caps is None or not sample.get_caps().is_equal(self.caps):
            self.caps = sample.get_caps()
            self.vinfo = GstVideo.VideoInfo.new_from_caps(self.caps)
            self.shot_src.set_property("caps", self.caps)
        self.last = sample.get_buffer()
        if self._changed(self.last):
            with self.cv:
                self.seq += 1
                self.frame_at = time.time()
                self.cv.notify_all()
        return Gst.FlowReturn.OK

    def _changed(self, buf):
        """Did this frame change the picture meaningfully? Compares a coarse luma
        thumbnail (every 16th pixel) with the one at the last change: more than
        0.4% of its cells must differ. The pointer moving, a blinking caret or a
        small spinner stay under that, so they don't keep the screen "moving"."""
        try:
            ok, m = buf.map(Gst.MapFlags.READ)
            if not ok:
                return True
            try:
                vi = self.vinfo
                stride, h, w = vi.stride[0], vi.height, vi.width
                y = np.frombuffer(m.data, np.uint8, count=stride * h).reshape(h, stride)
                thumb = y[::16, :w:16].astype(np.int16)
            finally:
                buf.unmap(m)
        except Exception:
            return True
        if self.ref is None or self.ref.shape != thumb.shape or (np.abs(thumb - self.ref) > 12).mean() > 0.004:
            self.ref = thumb
            return True
        return False

    def settle(self, since=None, change=1.0, quiet=0.1, limit=4.0):
        """Wait until the picture is still. With `since` (the change count before
        an action), first wait for that action's first visible change, up to
        `change` seconds (an action may change nothing). Then wait until nothing
        meaningful has changed for `quiet` seconds. At once when nothing happens."""
        start = time.time()
        with self.cv:
            if since is not None:
                while self.seq <= since and time.time() - start < change:
                    self.cv.wait(change - (time.time() - start))
            while time.time() - start < limit:
                idle = time.time() - self.frame_at
                if idle >= quiet:
                    break
                self.cv.wait(quiet - idle)
            return self.seq

    def screenshot(self):
        with self.shot_lock:
            if self.last is None:
                return None
            while self.png.emit("try-pull-sample", 0):  # drop a stale one
                pass
            self.shot_src.emit("push-buffer", self.last.copy())
            sample = self.png.emit("try-pull-sample", 2 * Gst.SECOND)
            if sample is None:
                return None
            buf = sample.get_buffer()
            return buf.extract_dup(0, buf.get_size())

    def stay_joined(self):
        # Keep subscribed to the hub; a first join (or one after the hub restarts)
        # brings a keyframe. Forget the picture when mirroring ends.
        joined = False
        while True:
            try:
                line, _ = screen.hub_request(f"{'keep' if joined else 'join'} {screen.FRAMES_RTP_PORT}")
                joined = line.startswith("ok")
            except OSError:
                joined = False
            if self.last is not None and not screen.airplay_mirroring():
                self.last = None
            time.sleep(1)

    def serve(self):
        try:
            os.unlink(FRAMES_SOCKET)
        except FileNotFoundError:
            pass
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.bind(FRAMES_SOCKET)
        os.chmod(FRAMES_SOCKET, 0o600)
        s.listen(16)
        log("control on", FRAMES_SOCKET)
        while True:
            conn, _ = s.accept()
            threading.Thread(target=self._client, args=(conn,), daemon=True).start()

    def _client(self, conn):
        with conn:
            for line in conn.makefile("rb"):
                cmd, _, arg = line.decode().strip().partition(" ")
                try:
                    if cmd == "status":
                        conn.sendall(f"ok live={int(self.last is not None)} seq={self.seq}\n".encode())
                    elif cmd == "settle":  # settle [SINCE|-] [QUIET]
                        a = arg.split()
                        since = int(a[0]) if a and a[0] != "-" else None
                        quiet = float(a[1]) if len(a) > 1 else 0.1
                        conn.sendall(f"ok seq={self.settle(since, quiet=quiet)}\n".encode())
                    elif cmd == "shot":
                        png = self.screenshot()
                        conn.sendall(b"err not mirroring\n" if png is None else f"ok {len(png)}\n".encode() + png)
                    else:
                        conn.sendall(b"err unknown command\n")
                except Exception as e:
                    log("control error:", e)
                    conn.sendall(f"err {e}\n".encode())


def main():
    Gst.init(None)
    f = Frames(os.environ.get("PHONEUSE_DECODER") or decoder())
    threading.Thread(target=f.serve, daemon=True).start()
    threading.Thread(target=f.stay_joined, daemon=True).start()
    GLib.MainLoop().run()


if __name__ == "__main__":
    main()
