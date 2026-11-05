"""Client-side state machine: screens, snapshot buffering, interpolation.

No rendering here. ui.py owns pygame; this module owns "what do we know and
what should the world look like right now".
"""
import time
from collections import deque

from common import protocol as P
from common import characters as C
from common import maps as M

INTERP_TICKS = 1.8           # others: playback delay in server ticks (~60 ms) absorbs jitter
SELF_TICKS = 0.4             # own fighter: near-live, so controls feel immediate
MAX_EXTRAPOLATE = 1.5        # ticks we may run past the newest snapshot before holding
TICK_DT = 1.0 / P.TICK_RATE
SNAPSHOT_BUFFER = 32
GAME_OVER_LINGER = 2.4       # seconds of "GAME!" before the results screen

SCREEN_LOGIN, SCREEN_LOBBY, SCREEN_ROOM, SCREEN_GAME, SCREEN_RESULTS = range(5)


class RemotePlayer:
    """Interpolated view of one player's row from the snapshot stream."""
    __slots__ = ("pid", "x", "y", "facing", "damage", "stocks", "state", "seq",
                 "action", "action_t", "special_cd", "mv", "vx", "vy")

    def __init__(self, row, vx=0.0, vy=0.0):
        self.apply(row, vx, vy)

    def apply(self, row, vx, vy):
        (self.pid, self.x, self.y, self.facing, self.damage, self.stocks, self.state,
         self.seq, self.action, self.action_t, self.special_cd, self.mv) = row
        self.vx, self.vy = vx, vy


class ClientState:
    def __init__(self, net, name):
        self.net = net
        self.name = name
        self.screen = SCREEN_LOGIN
        self.pid = None
        self.error = None
        self.error_at = 0.0

        self.rooms = []                      # lobby room list
        self.room_name = None
        self.host_pid = None
        self.room_players = []               # [{pid,name,host,char}]

        self.names = {}                      # pid -> name
        self.chars = {}                      # pid -> character id
        self.order = []                      # pids in slot order for the current match
        self.room_map = M.DEFAULT            # arena chosen in the room
        self.map_id = M.DEFAULT              # arena of the current match
        self._snaps = deque(maxlen=SNAPSHOT_BUFFER)   # snapshot dicts, ascending tick
        self._arrivals = deque(maxlen=12)    # (arrival time, tick) of recent snapshots
        self._play = None                    # playback position on the server-tick timeline
        self._last_pump = None
        self.view = {}                       # pid -> RemotePlayer, interpolated
        self.projectiles = []                # [(id, x, y, kind, dir)] interpolated
        self.countdown = 0                   # ticks left, from newest snapshot
        self.fx = deque()                    # game events for the UI to turn into effects
        self.feed = deque(maxlen=5)          # recent kill-feed lines
        self.results = None
        self.winner = None
        self.game_over_at = None

        self.input_seq = 0
        self.my_keys = 0
        self._next_ping = 0.0
        self._pending_pings = {}
        self._probe_results = deque(maxlen=20)
        self.ping_ms = None

    # -- helpers -------------------------------------------------------------
    def name_of(self, pid):
        return self.names.get(pid, "p%s" % pid)

    def char_of(self, pid):
        return self.chars.get(pid, C.DEFAULT)

    def slot_of(self, pid):
        if pid in self.order:
            return self.order.index(pid)
        for i, p in enumerate(self.room_players):
            if p["pid"] == pid:
                return i
        return 0

    @property
    def my_char(self):
        for p in self.room_players:
            if p["pid"] == self.pid:
                return p["char"]
        return C.DEFAULT

    @property
    def is_host(self):
        return self.pid is not None and self.host_pid == self.pid

    def set_error(self, text):
        self.error = text
        self.error_at = time.monotonic()

    # -- outgoing ----------------------------------------------------------
    def login(self, name):
        self.name = name
        self.net.send(P.msg(P.LOGIN, name=name))

    def list_rooms(self):
        self.net.send(P.msg(P.LIST_ROOMS))

    def create_room(self, room):
        self.net.send(P.msg(P.CREATE_ROOM, room=room))

    def join_room(self, room):
        self.net.send(P.msg(P.JOIN_ROOM, room=room))

    def leave_room(self):
        self.net.send(P.msg(P.LEAVE_ROOM))

    def start_game(self):
        self.net.send(P.msg(P.START_GAME))

    def select_char(self, char_id):
        self.net.send(P.msg(P.SELECT_CHAR, char=char_id))

    def select_map(self, map_id):
        self.net.send(P.msg(P.SELECT_MAP, map=map_id))

    def send_input(self, keys):
        if keys == self.my_keys and self.input_seq > 0:
            return
        self.my_keys = keys
        self.input_seq += 1
        self.net.send(P.msg(P.INPUT, seq=self.input_seq, keys=keys))

    # -- incoming ------------------------------------------------------------
    def pump(self):
        """Process everything the network thread has queued. Call once/frame."""
        now = time.monotonic()
        if now >= self._next_ping:
            stamp = now
            self._pending_pings[stamp] = stamp
            self.net.send(P.msg(P.PING, t=stamp))
            self._next_ping = now + P.HEARTBEAT_INTERVAL
        for stamp in list(self._pending_pings):
            if now - stamp > P.DISCONNECT_TIMEOUT:
                self._pending_pings.pop(stamp)
                self._probe_results.append(False)
        for msg in self.net.poll():
            self._handle(msg)
        self._interpolate()
        if (self.game_over_at is not None and self.screen == SCREEN_GAME
                and time.monotonic() - self.game_over_at > GAME_OVER_LINGER):
            self.screen = SCREEN_RESULTS

    def _handle(self, msg):
        t = msg["type"]
        if t == P.PONG:
            stamp = msg.get("t")
            if stamp in self._pending_pings:
                self._pending_pings.pop(stamp)
                self._probe_results.append(True)
                self.ping_ms = max(0, round((time.monotonic() - stamp) * 1000))
        elif t == P.LOGIN_OK:
            self.pid = msg["pid"]
            self.name = msg["name"]
            self.error = None
            self.screen = SCREEN_LOBBY
            self.list_rooms()
        elif t == P.LOGIN_ERR:
            self.set_error(msg["reason"])
        elif t == P.ROOM_LIST:
            self.rooms = msg["rooms"]
        elif t == P.ROOM_UPDATE:
            self.room_name = msg["room"]
            self.host_pid = msg["host"]
            self.room_players = msg["players"]
            self.room_map = msg.get("map", self.room_map)
            for p in self.room_players:
                self.names[p["pid"]] = p["name"]
                self.chars[p["pid"]] = p["char"]
            if self.screen == SCREEN_LOBBY:
                self.screen = SCREEN_ROOM
        elif t == P.ROOM_LEFT:
            self.room_name = None
            self.room_players = []
            self.screen = SCREEN_LOBBY
            self.list_rooms()
        elif t == P.GAME_STARTED:
            for p in msg["players"]:
                self.names[p["pid"]] = p["name"]
                self.chars[p["pid"]] = p["char"]
            self.order = [p["pid"] for p in msg["players"]]
            self.map_id = msg.get("map", self.room_map)
            self._snaps.clear()
            self._arrivals.clear()
            self._play = None
            self.view.clear()
            self.projectiles = []
            self.fx.clear()
            self.feed.clear()
            self.results = None
            self.winner = None
            self.game_over_at = None
            self.input_seq = 0
            self.my_keys = 0
            self.screen = SCREEN_GAME
        elif t == P.SNAPSHOT:
            if self._snaps and msg["tick"] <= self._snaps[-1]["tick"]:
                return                            # stale / duplicate: newest wins
            self._arrivals.append((msg.get("_rt", time.monotonic()), msg["tick"]))
            self._snaps.append(msg)
            self.countdown = msg.get("cd", 0)
        elif t == P.EVENT:
            self._on_event(msg)
        elif t == P.GAME_OVER:
            self.winner = msg["winner"]
            self.results = msg["results"]
            self.game_over_at = time.monotonic()
            self.fx.append({"ev": "GAME_OVER", "winner": self.winner})
        elif t == P.ERROR:
            self.set_error(msg["reason"])

    def _on_event(self, ev):
        self.fx.append(ev)
        kind = ev["ev"]
        if kind == "KO":
            by = ev.get("by")
            line = ("%s  >  %s" % (self.name_of(by), self.name_of(ev["victim"])) if by
                    else "%s fell" % self.name_of(ev["victim"]))
            self.feed.append((line, time.monotonic()))
        elif kind == "PLAYER_LEFT":
            self.feed.append(("%s left the match" % self.name_of(ev["pid"]), time.monotonic()))

    # -- interpolation -------------------------------------------------------
    def server_tick_now(self, now):
        """Best estimate of the server's current tick: the most on-time recent arrival wins."""
        return max(tick + (now - at) / TICK_DT for at, tick in self._arrivals)

    def _advance_playback(self):
        """A playback clock that runs at real speed and gently steers toward the server.

        It never jumps for ordinary jitter, and it adapts if the server's real tick
        rate drifts from nominal, so motion stays smooth instead of stall-then-jump.
        """
        now = time.monotonic()
        dt = 0.0 if self._last_pump is None else min(0.1, now - self._last_pump)
        self._last_pump = now
        target = self.server_tick_now(now)
        if self._play is None or abs(target - self._play) > 8:
            self._play = target
        else:
            self._play += dt / TICK_DT
            self._play += (target - self._play) * min(1.0, dt * 3.0)
        return self._play

    def _bracket(self, rt):
        snaps = self._snaps
        newest = snaps[-1]["tick"]
        rt = min(rt, newest + MAX_EXTRAPOLATE)
        if len(snaps) == 1 or rt <= snaps[0]["tick"]:
            s0 = s1 = snaps[0]
        elif rt >= newest:
            s0, s1 = snaps[-2], snaps[-1]           # extrapolate a little along the last motion
        else:
            s0 = s1 = snaps[-1]
            for i in range(len(snaps) - 1, 0, -1):
                if snaps[i - 1]["tick"] <= rt <= snaps[i]["tick"]:
                    s0, s1 = snaps[i - 1], snaps[i]
                    break
        span = s1["tick"] - s0["tick"]
        return s0, s1, (0.0 if span <= 0 else (rt - s0["tick"]) / span), span

    @staticmethod
    def _blend_row(pid, s0, s1, frac, span):
        r1 = next((r for r in s1["p"] if r[0] == pid), None)
        if r1 is None:
            return None, 0.0, 0.0
        r0 = next((r for r in s0["p"] if r[0] == pid), r1)
        if abs(r1[1] - r0[1]) > 200 or abs(r1[2] - r0[2]) > 200:
            r0 = r1                                  # don't smear across a respawn
        row = list(r1)
        row[1] = r0[1] + (r1[1] - r0[1]) * frac
        row[2] = r0[2] + (r1[2] - r0[2]) * frac
        vx = (r1[1] - r0[1]) / (span * TICK_DT) if span > 0 else 0.0
        vy = (r1[2] - r0[2]) / (span * TICK_DT) if span > 0 else 0.0
        return row, vx, vy

    def _interpolate(self):
        if not self._snaps:
            return
        live = self._advance_playback()
        others = self._bracket(live - INTERP_TICKS)
        mine = self._bracket(live - SELF_TICKS)
        s0, s1, frac, span = others
        for r1 in s1["p"]:
            pid = r1[0]
            row, vx, vy = self._blend_row(pid, *(mine if pid == self.pid else others))
            if row is None:
                continue
            if pid in self.view:
                self.view[pid].apply(row, vx, vy)
            else:
                self.view[pid] = RemotePlayer(row, vx, vy)

        pr0 = {p[0]: p for p in s0.get("pr", [])}
        out = []
        for p1 in s1.get("pr", []):
            p0 = pr0.get(p1[0], p1)
            out.append((p1[0], p0[1] + (p1[1] - p0[1]) * frac,
                        p0[2] + (p1[2] - p0[2]) * frac, p1[3], p1[4]))
        self.projectiles = out

    def latest_tick(self):
        return self._snaps[-1]["tick"] if self._snaps else 0
