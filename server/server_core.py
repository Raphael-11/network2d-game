"""Accounts, lobby, rooms and the fixed-rate game loop.

Transport-agnostic: works against any object implementing the
ServerTransport interface (see transport_tcp.py / transport_udp.py).
Player ids are whatever the transport hands back from poll() / on_disconnect
(for TCP: one id per accepted connection; for UDP: one id per session token).
"""
import time
import traceback

from common import protocol as P
from common import physics as G
from common import characters as C
from common import maps as M


class Room:
    def __init__(self, name, host_pid):
        self.name = name
        self.host_pid = host_pid
        self.players = {}   # pid -> name, join order preserved
        self.chars = {}     # pid -> character id
        self.map_id = M.DEFAULT
        self.match = None   # G.Match while a game is running

    def add(self, pid, name):
        self.players[pid] = name
        taken = set(self.chars.values())
        self.chars[pid] = next((c for c in C.ORDER if c not in taken), C.DEFAULT)

    def remove(self, pid):
        self.players.pop(pid, None)
        self.chars.pop(pid, None)

    def player_list(self):
        return [{"pid": pid, "name": name, "host": pid == self.host_pid,
                 "char": self.chars.get(pid, C.DEFAULT)}
                for pid, name in self.players.items()]

    @property
    def started(self):
        return self.match is not None


class Server:
    def __init__(self, transport):
        self.t = transport
        self.t.on_disconnect(self._on_disconnect)
        self.names = {}         # pid -> logged-in name
        self.rooms = {}         # room name -> Room
        self.player_room = {}   # pid -> room name
        self._tick_dt = 1.0 / P.TICK_RATE

    # -- main loop -------------------------------------------------------
    def run(self):
        next_tick = time.monotonic()
        while True:
            try:
                # wait for network input, but never past the next tick
                wait = max(0.0, min(0.01, next_tick - time.monotonic()))
                for pid, msg in self.t.poll(wait):
                    self._safe_handle(pid, msg)
                now = time.monotonic()
                if now - next_tick > 0.25:            # hopelessly behind (debugger, sleep): resync
                    next_tick = now
                steps = 0
                while now >= next_tick and steps < 3:  # fixed cadence: late ticks catch up
                    self._step_rooms()
                    next_tick += self._tick_dt
                    steps += 1
            except Exception:                         # noqa: BLE001 - keep serving everyone else
                traceback.print_exc()

    def _safe_handle(self, pid, msg):
        try:
            self._handle(pid, msg)
        except P.ProtocolError as e:
            self.t.send_reliable(pid, P.msg(P.ERROR, reason=str(e)))
        except Exception:                           # noqa: BLE001 - never crash the server
            traceback.print_exc()
            self.t.send_reliable(pid, P.msg(P.ERROR, reason="internal error"))

    # -- message dispatch --------------------------------------------------
    def _handle(self, pid, msg):
        t = msg.get("type")
        if t == P.PING:
            self.t.send_unreliable(pid, P.msg(P.PONG, t=msg.get("t")))
            return
        if t == P.LOGIN:
            self._login(pid, msg)
            return
        if pid not in self.names:
            self.t.send_reliable(pid, P.msg(P.ERROR, reason="not logged in"))
            return
        if t == P.LIST_ROOMS:
            self._send_room_list(pid)
        elif t == P.CREATE_ROOM:
            self._create_room(pid, msg)
        elif t == P.JOIN_ROOM:
            self._join_room(pid, msg)
        elif t == P.LEAVE_ROOM:
            self._leave_room(pid)
        elif t == P.START_GAME:
            self._start_game(pid)
        elif t == P.SELECT_CHAR:
            self._select_char(pid, msg)
        elif t == P.SELECT_MAP:
            self._select_map(pid, msg)
        elif t == P.INPUT:
            room = self.rooms.get(self.player_room.get(pid))
            if room and room.started:
                room.match.set_input(pid, int(msg["seq"]), int(msg["keys"]))
        else:
            self.t.send_reliable(pid, P.msg(P.ERROR, reason="unknown type %r" % t))

    # -- accounts ------------------------------------------------------------
    def _login(self, pid, msg):
        try:
            name = P.clean_name(msg["name"])
        except P.ProtocolError as e:
            self.t.send_reliable(pid, P.msg(P.LOGIN_ERR, reason=str(e)))
            return
        if name in self.names.values():
            self.t.send_reliable(pid, P.msg(P.LOGIN_ERR, reason="name taken"))
            return
        self.names[pid] = name
        self.t.send_reliable(pid, P.msg(P.LOGIN_OK, pid=pid, name=name))

    # -- lobby / rooms ---------------------------------------------------
    def _send_room_list(self, pid):
        rooms = [{"room": r.name, "players": len(r.players),
                  "max": P.MAX_PLAYERS_PER_ROOM, "started": r.started}
                 for r in self.rooms.values()]
        self.t.send_reliable(pid, P.msg(P.ROOM_LIST, rooms=rooms))

    def _create_room(self, pid, msg):
        name = P.clean_name(msg["room"])
        if name in self.rooms:
            self.t.send_reliable(pid, P.msg(P.ERROR, reason="room exists"))
            return
        self._leave_room(pid)
        room = Room(name, pid)
        room.add(pid, self.names[pid])
        self.rooms[name] = room
        self.player_room[pid] = name
        self._broadcast_room_update(room)

    def _join_room(self, pid, msg):
        name = P.clean_name(msg["room"])
        room = self.rooms.get(name)
        if room is None:
            self.t.send_reliable(pid, P.msg(P.ERROR, reason="no such room"))
            return
        if room.started:
            self.t.send_reliable(pid, P.msg(P.ERROR, reason="game in progress"))
            return
        if len(room.players) >= P.MAX_PLAYERS_PER_ROOM:
            self.t.send_reliable(pid, P.msg(P.ERROR, reason="room full"))
            return
        self._leave_room(pid)
        room.add(pid, self.names[pid])
        self.player_room[pid] = name
        self._broadcast_room_update(room)

    def _select_char(self, pid, msg):
        room = self.rooms.get(self.player_room.get(pid))
        if room is None or room.started:
            self.t.send_reliable(pid, P.msg(P.ERROR, reason="can't change fighter now"))
            return
        if msg["char"] not in C.CHARACTERS:
            self.t.send_reliable(pid, P.msg(P.ERROR, reason="unknown fighter"))
            return
        room.chars[pid] = msg["char"]
        self._broadcast_room_update(room)

    def _select_map(self, pid, msg):
        room = self.rooms.get(self.player_room.get(pid))
        if room is None or room.started or room.host_pid != pid:
            self.t.send_reliable(pid, P.msg(P.ERROR, reason="only the host picks the arena"))
            return
        if msg["map"] not in M.ORDER:
            self.t.send_reliable(pid, P.msg(P.ERROR, reason="unknown arena"))
            return
        room.map_id = msg["map"]
        self._broadcast_room_update(room)

    def _leave_room(self, pid):
        name = self.player_room.pop(pid, None)
        if name is None:
            return
        room = self.rooms.get(name)
        if room is None:
            return
        was_in_match = room.started and pid in room.players
        room.remove(pid)
        if was_in_match:
            events = room.match.remove_player(pid)
            self._broadcast_events(room, events)
        self.t.send_reliable(pid, P.msg(P.ROOM_LEFT, room=name))
        if not room.players:
            del self.rooms[name]
            return
        if room.host_pid == pid:
            room.host_pid = next(iter(room.players))
        self._broadcast_room_update(room)

    def _broadcast_room_update(self, room):
        payload = P.msg(P.ROOM_UPDATE, room=room.name, host=room.host_pid,
                         players=room.player_list(), started=room.started, map=room.map_id)
        for pid in list(room.players):
            self.t.send_reliable(pid, payload)

    def _start_game(self, pid):
        room = self.rooms.get(self.player_room.get(pid))
        if room is None or room.host_pid != pid:
            self.t.send_reliable(pid, P.msg(P.ERROR, reason="only the host can start"))
            return
        if room.started:
            return
        if len(room.players) < P.MIN_PLAYERS_TO_START:
            self.t.send_reliable(pid, P.msg(P.ERROR, reason="need more players"))
            return
        room.match = G.Match([(p, n, room.chars[p]) for p, n in room.players.items()],
                             countdown=G.COUNTDOWN_TICKS, map_id=room.map_id)
        payload = P.msg(P.GAME_STARTED, room=room.name,
                         players=room.player_list(), map=room.map_id)
        for p in list(room.players):
            self.t.send_reliable(p, payload)

    # -- simulation --------------------------------------------------------
    def _step_rooms(self):
        for room in list(self.rooms.values()):
            if not room.started or room.match.over:
                continue
            events = room.match.step()
            snap = P.msg(P.SNAPSHOT, **room.match.snapshot())
            for p in list(room.players):
                self.t.send_unreliable(p, snap)
            self._broadcast_events(room, events)

    def _broadcast_events(self, room, events):
        game_over = False
        for ev in events:
            if ev["ev"] == "GAME_OVER":
                payload = P.msg(P.GAME_OVER, winner=ev["winner"],
                                 results=room.match.results())
                game_over = True
            else:
                payload = P.msg(P.EVENT, **ev)
            for p in list(room.players):
                self.t.send_reliable(p, payload)
        if game_over:                       # room goes back to fighter select
            room.match = None
            self._broadcast_room_update(room)

    # -- disconnects ---------------------------------------------------------
    def _on_disconnect(self, pid):
        self._leave_room(pid)
        self.names.pop(pid, None)
