"""Shared application protocol for Brawl Arena.

Identical for the TCP and UDP versions. Only the *framing* differs:
  - TCP: 4-byte big-endian length prefix + JSON (see encode_frame / FrameDecoder)
  - UDP: one JSON datagram with a reliability header (added in transport_udp.py)
"""
import json

# ---- constants -------------------------------------------------------------
TICK_RATE = 30                    # server simulation + snapshot rate (Hz)
HEARTBEAT_INTERVAL = 1.0          # seconds between PINGs
DISCONNECT_TIMEOUT = 3.0          # silence (s) before a peer is considered gone
MAX_FRAME = 64 * 1024             # reject absurd TCP frames
MAX_PLAYERS_PER_ROOM = 3
MIN_PLAYERS_TO_START = 2
MAX_NAME_LEN = 16

# ---- message types ---------------------------------------------------------
# client -> server
LOGIN = "LOGIN"
LIST_ROOMS = "LIST_ROOMS"
CREATE_ROOM = "CREATE_ROOM"
JOIN_ROOM = "JOIN_ROOM"
LEAVE_ROOM = "LEAVE_ROOM"
START_GAME = "START_GAME"
SELECT_CHAR = "SELECT_CHAR"
SELECT_MAP = "SELECT_MAP"
INPUT = "INPUT"
# server -> client
LOGIN_OK = "LOGIN_OK"
LOGIN_ERR = "LOGIN_ERR"
ROOM_LIST = "ROOM_LIST"
ROOM_UPDATE = "ROOM_UPDATE"
ROOM_LEFT = "ROOM_LEFT"
ERROR = "ERROR"
GAME_STARTED = "GAME_STARTED"
SNAPSHOT = "SNAPSHOT"
EVENT = "EVENT"
GAME_OVER = "GAME_OVER"
# both directions
PING = "PING"
PONG = "PONG"

# Which messages the UDP version must deliver reliably. Everything else is
# "latest wins" (INPUT, SNAPSHOT, PING, PONG).
RELIABLE_TYPES = {
    LOGIN, LOGIN_OK, LOGIN_ERR, LIST_ROOMS, ROOM_LIST, CREATE_ROOM, JOIN_ROOM,
    LEAVE_ROOM, ROOM_LEFT, ROOM_UPDATE, START_GAME, GAME_STARTED, EVENT,
    GAME_OVER, ERROR, SELECT_CHAR, SELECT_MAP,
}

# Required fields per message type (used for validation of untrusted input).
_REQUIRED = {
    LOGIN: ("name",),
    CREATE_ROOM: ("room",),
    JOIN_ROOM: ("room",),
    SELECT_CHAR: ("char",),
    SELECT_MAP: ("map",),
    INPUT: ("seq", "keys"),
}


class ProtocolError(Exception):
    """Raised for malformed or invalid messages from the network."""


# ---- message helpers -------------------------------------------------------
def msg(type_, **fields):
    d = {"type": type_}
    d.update(fields)
    return d


def encode(message: dict) -> bytes:
    return json.dumps(message, separators=(",", ":")).encode("utf-8")


def decode(data: bytes) -> dict:
    """Decode and validate one message. Never trust the network."""
    try:
        m = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as e:
        raise ProtocolError("bad json: %s" % e)
    if not isinstance(m, dict) or not isinstance(m.get("type"), str):
        raise ProtocolError("message must be an object with a string 'type'")
    for field in _REQUIRED.get(m["type"], ()):
        if field not in m:
            raise ProtocolError("%s missing field %r" % (m["type"], field))
    return m


def clean_name(name) -> str:
    """Validate a username / room name from the network."""
    if not isinstance(name, str):
        raise ProtocolError("name must be a string")
    name = name.strip()
    if not name or len(name) > MAX_NAME_LEN or not name.replace("_", "").isalnum():
        raise ProtocolError("name must be 1-%d letters/digits/_" % MAX_NAME_LEN)
    return name


# ---- input keys ------------------------------------------------------------
KEY_LEFT = 1
KEY_RIGHT = 2
KEY_JUMP = 4
KEY_LIGHT_ATTACK = 8
KEY_HEAVY_ATTACK = 16
KEY_DOWN = 32
KEY_DODGE = 64
KEY_SPECIAL = 128

# Backwards-compatible name used by the original light-attack implementation.
KEY_ATTACK = KEY_LIGHT_ATTACK
KEY_MASK = (KEY_LEFT | KEY_RIGHT | KEY_JUMP | KEY_LIGHT_ATTACK
            | KEY_HEAVY_ATTACK | KEY_DOWN | KEY_DODGE | KEY_SPECIAL)


def pack_keys(left=False, right=False, jump=False, attack=False,
              down=False, light_attack=False, heavy_attack=False,
              dodge=False, special=False) -> int:
    """Pack the current controls into the integer sent in an INPUT message.

    ``attack`` remains an alias for ``light_attack`` for existing clients.
    """
    light_attack = light_attack or attack
    return (KEY_LEFT * bool(left) | KEY_RIGHT * bool(right)
            | KEY_JUMP * bool(jump) | KEY_LIGHT_ATTACK * bool(light_attack)
            | KEY_HEAVY_ATTACK * bool(heavy_attack) | KEY_DOWN * bool(down)
            | KEY_DODGE * bool(dodge) | KEY_SPECIAL * bool(special))


# ---- TCP framing -----------------------------------------------------------
def encode_frame(message: dict) -> bytes:
    body = encode(message)
    return len(body).to_bytes(4, "big") + body


class FrameDecoder:
    """Reassembles length-prefixed frames from a TCP byte stream.

    TCP has no message boundaries: one recv() may hold half a message or
    several. feed() buffers bytes and returns every complete message so far.
    """

    def __init__(self):
        self._buf = bytearray()

    def feed(self, data: bytes):
        self._buf.extend(data)
        out = []
        while True:
            if len(self._buf) < 4:
                break
            n = int.from_bytes(self._buf[:4], "big")
            if n <= 0 or n > MAX_FRAME:
                raise ProtocolError("illegal frame length %d" % n)
            if len(self._buf) < 4 + n:
                break
            body = bytes(self._buf[4:4 + n])
            del self._buf[:4 + n]
            out.append(decode(body))
        return out
