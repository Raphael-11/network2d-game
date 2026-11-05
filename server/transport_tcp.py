"""Selectors-based, single-threaded TCP transport.

Implements the ServerTransport interface used by server_core.Server:
    send_reliable(pid, msg) / send_unreliable(pid, msg)   (both reliable here)
    poll() -> list[(pid, msg)]
    on_disconnect(callback)
    close_player(pid)

One connection == one player id (assigned on accept). Non-blocking sockets,
per-client recv buffer fed through protocol.FrameDecoder, per-client send
buffer flushed opportunistically.
"""
import selectors
import socket

from common import protocol as P

MAX_OUTBUF = 1 << 20


class _Conn:
    __slots__ = ("sock", "pid", "decoder", "outbuf")

    def __init__(self, sock, pid):
        self.sock = sock
        self.pid = pid
        self.decoder = P.FrameDecoder()
        self.outbuf = bytearray()


class TCPTransport:
    def __init__(self, port, host=""):
        self.sel = selectors.DefaultSelector()
        self.listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            # Windows SO_REUSEADDR lets a second server silently share the port
            self.listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        else:
            self.listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.listener.bind((host, port))
        self.listener.listen()
        self.listener.setblocking(False)
        self.sel.register(self.listener, selectors.EVENT_READ, data=None)
        self.conns = {}          # pid -> _Conn
        self._next_pid = 1
        self._disconnect_cb = None
        self._dead = []          # dropped pids, reported at the start of the next poll()

    def on_disconnect(self, callback):
        self._disconnect_cb = callback

    # -- outgoing: TCP has one reliable stream, so both map to the same send --
    def send_reliable(self, pid, msg):
        self._send(pid, msg)

    def send_unreliable(self, pid, msg):
        self._send(pid, msg)

    def _send(self, pid, msg):
        conn = self.conns.get(pid)
        if conn is None:
            return
        conn.outbuf += P.encode_frame(msg)
        if len(conn.outbuf) > MAX_OUTBUF:          # client stopped reading
            self._drop(conn)
            return
        self._try_flush(conn)

    def close_player(self, pid):
        conn = self.conns.pop(pid, None)
        if conn is None:
            return
        try:
            self.sel.unregister(conn.sock)
        except (KeyError, ValueError, OSError):
            pass
        conn.sock.close()

    # -- polling ---------------------------------------------------------
    def poll(self, timeout=0.01):
        # Report drops here, never from inside a send: the server may be
        # iterating a room's players when a send fails.
        while self._dead:
            pid = self._dead.pop(0)
            if self._disconnect_cb:
                self._disconnect_cb(pid)
        out = []
        for key, mask in self.sel.select(timeout=timeout):
            if key.data is None:
                self._accept()
                continue
            pid = key.data
            conn = self.conns.get(pid)
            if conn is None:
                continue
            if mask & selectors.EVENT_READ:
                self._read(conn, out)
            if conn.sock.fileno() != -1 and mask & selectors.EVENT_WRITE:
                self._try_flush(conn)
        return out

    def _accept(self):
        try:
            sock, _addr = self.listener.accept()
        except OSError:
            return
        sock.setblocking(False)
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)   # no Nagle batching
        pid = self._next_pid
        self._next_pid += 1
        conn = _Conn(sock, pid)
        self.conns[pid] = conn
        self.sel.register(sock, selectors.EVENT_READ, data=pid)

    def _read(self, conn, out):
        try:
            data = conn.sock.recv(65536)
        except BlockingIOError:
            return
        except OSError:
            data = b""
        if not data:
            self._drop(conn)
            return
        try:
            for msg in conn.decoder.feed(data):
                out.append((conn.pid, msg))
        except P.ProtocolError:
            self._drop(conn)

    def _try_flush(self, conn):
        if not conn.outbuf:
            return
        try:
            n = conn.sock.send(conn.outbuf)
            del conn.outbuf[:n]
        except BlockingIOError:
            pass
        except OSError:
            self._drop(conn)
            return
        events = selectors.EVENT_READ | (selectors.EVENT_WRITE if conn.outbuf else 0)
        try:
            self.sel.modify(conn.sock, events, data=conn.pid)
        except (KeyError, ValueError, OSError):
            pass

    def _drop(self, conn):
        if conn.pid in self.conns:
            self.close_player(conn.pid)
            self._dead.append(conn.pid)
