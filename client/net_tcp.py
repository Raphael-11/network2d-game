"""TCP networking for the client: a background thread owns the socket.

recv runs on its own thread and pushes decoded messages into a thread-safe
queue; the render/input loop drains it each frame. send() is called from the
main thread and is lock-protected.
"""
import queue
import socket
import threading
import time

from common import protocol as P


class NetTCP:
    def __init__(self, host, port):
        self.sock = socket.create_connection((host, port), timeout=5)
        self.sock.settimeout(None)
        # Nagle + delayed ACKs can hold small game packets back by up to ~200 ms
        self.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self.inbox = queue.Queue()
        self.connected = True
        self._send_lock = threading.Lock()
        self._thread = threading.Thread(target=self._recv_loop, daemon=True)
        self._thread.start()

    def send(self, msg: dict):
        if not self.connected:
            return
        try:
            with self._send_lock:
                self.sock.sendall(P.encode_frame(msg))
        except OSError:
            self._die()

    def poll(self):
        """Drain and return all messages received since the last call."""
        out = []
        try:
            while True:
                out.append(self.inbox.get_nowait())
        except queue.Empty:
            pass
        return out

    def close(self):
        self.connected = False
        try:
            self.sock.close()
        except OSError:
            pass

    def _recv_loop(self):
        decoder = P.FrameDecoder()
        try:
            while True:
                data = self.sock.recv(65536)
                if not data:
                    break
                now = time.monotonic()
                for msg in decoder.feed(data):
                    msg["_rt"] = now                  # true arrival time, not frame time
                    self.inbox.put(msg)
        except (OSError, P.ProtocolError):
            pass
        finally:
            self._die()

    def _die(self):
        self.connected = False
