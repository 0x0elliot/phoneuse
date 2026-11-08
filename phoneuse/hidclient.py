"""Client for the phoneuse HID daemon's command socket (see hid_daemon.py)."""
import socket
import threading

from .config import HID_SOCKET


class Hid:
    """One connection to the daemon. Thread-safe: commands are serialized. When the
    daemon restarts, the next command reconnects and is sent again once, so long-lived
    clients (the mirror window, the browser mirror) keep working."""

    def __init__(self, path=HID_SOCKET):
        self.path = path
        self.lock = threading.Lock()
        self._connect()

    def _connect(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.connect(self.path)
        self.f = self.sock.makefile()

    def _send(self, line):
        self.sock.sendall((line + "\n").encode())
        reply = self.f.readline().strip()
        if not reply:  # the daemon closed the connection
            raise ConnectionResetError("the HID daemon closed the connection")
        return reply

    def cmd(self, line):
        with self.lock:
            try:
                reply = self._send(line)
            except OSError:
                try:
                    self.sock.close()
                except OSError:
                    pass
                self._connect()  # the daemon restarted: a new connection, then once more
                reply = self._send(line)
        if not reply.startswith("ok"):
            raise RuntimeError(reply)
        return reply
