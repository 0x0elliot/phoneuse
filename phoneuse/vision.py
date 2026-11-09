"""Vision service for phoneuse: keeps OCR loaded.

Runs in .venv-vision (its own deps; `python -m phoneuse.vision`). Listens on $XDG_RUNTIME_DIR/phoneuse-vision.sock;
one JSON request per connection, one JSON reply:
  {"op": "text", "image": PATH}            -> {"lines": [{"text", "x", "y", "w", "h", "conf"}]}

Models (chosen 2026-11-06 on real iPhone screenshots):
  OCR: RapidOCR with PP-OCRv6 small (ONNX; GPU with onnxruntime-gpu, else CPU).
       Exact on iOS UI text incl. arrows, ~0.18 s per screen on an RTX 5090
       (~1.2 s on the CPU); Tesseract garbled symbols.
  (A GUI grounding model, GoClick-Large, used to find elements from descriptions;
  removed 2026-11-08: agents tap text by OCR and everything else by position.)
"""
import json
import os
import socket
import sys
import threading
import time

from .config import VISION_SOCKET as SOCK  # noqa: E402  (shared with the CLI)


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, file=sys.stderr, flush=True)


class Vision:
    def __init__(self):
        from rapidocr import RapidOCR
        import logging
        import onnxruntime
        logging.getLogger("RapidOCR").setLevel(logging.WARNING)
        # No text-orientation classifier: iOS text is upright (saves ~75 ms). On an
        # NVIDIA GPU (onnxruntime-gpu) a screen takes ~0.18 s, on the CPU ~1.2 s.
        params = {"Global.use_cls": False, "Det.limit_side_len": 960,
                  "EngineConfig.onnxruntime.intra_op_num_threads": min(8, os.cpu_count() or 4)}
        if "CUDAExecutionProvider" in onnxruntime.get_available_providers():
            params["EngineConfig.onnxruntime.use_cuda"] = True
        self.ocr = RapidOCR(params=params)
        self.ocr_device = "cuda" if params.get("EngineConfig.onnxruntime.use_cuda") else "cpu"
        log("OCR on", self.ocr_device)
        self.lock = threading.Lock()

    def text(self, image):
        from PIL import Image
        W, H = Image.open(image).size
        r = self.ocr(image)
        lines = []
        for box, txt, conf in zip(r.boxes if r.boxes is not None else [], r.txts or [], r.scores or []):
            xs = [float(p[0]) for p in box]
            ys = [float(p[1]) for p in box]
            lines.append({"text": txt, "x": round(sum(xs) / 4 / W, 4), "y": round(sum(ys) / 4 / H, 4),
                          "w": round((max(xs) - min(xs)) / W, 4), "h": round((max(ys) - min(ys)) / H, 4),
                          "conf": round(float(conf), 3)})
        return {"lines": lines}

    def handle(self, req):
        with self.lock:
            if req["op"] == "text":
                return self.text(req["image"])
            if req["op"] == "ping":
                return {"ok": True}
            return {"error": "unknown op"}


def serve():
    v = Vision()
    try:
        os.unlink(SOCK)
    except FileNotFoundError:
        pass
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.bind(SOCK)
    s.listen(8)
    log("vision service on", SOCK)
    while True:
        conn, _ = s.accept()
        threading.Thread(target=_client, args=(v, conn), daemon=True).start()


def _client(v, conn):  # requests: {"op": "text" | "ping", ...}
    with conn:
        try:
            req = json.loads(conn.makefile().readline())
            reply = v.handle(req)
        except Exception as e:
            reply = {"error": str(e)}
        try:
            data = json.dumps(reply)
        except TypeError as e:
            data = json.dumps({"error": f"bad reply: {e}"})
        conn.sendall((data + "\n").encode())


if __name__ == "__main__":
    serve()
