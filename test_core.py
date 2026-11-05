"""Run from the project root:  python -m tests.test_core"""
import random

from common import protocol as P
from common import physics as G


def run_ticks(m, n, keys_by_pid=None):
    seq = m.__dict__.setdefault("_test_seq", {})   # keep seq increasing across calls
    events = []
    for _ in range(n):
        for pid, keys in (keys_by_pid or {}).items():
            seq[pid] = seq.get(pid, 0) + 1
            m.set_input(pid, seq[pid], keys)
        events += m.step()
    return events


# ---- protocol ---------------------------------------------------------------
def test_frame_split_and_merged():
    a, b = P.msg(P.LOGIN, name="alice"), P.msg(P.PING, t=1.5)
    blob = P.encode_frame(a) + P.encode_frame(b)
    d = P.FrameDecoder()
    got = []
    for i in range(len(blob)):               # worst case: 1 byte at a time
        got += d.feed(blob[i:i + 1])
    assert got == [a, b], got
    d2 = P.FrameDecoder()                     # both frames in one recv()
    assert d2.feed(blob) == [a, b]


def test_frame_rejects_garbage():
    for bad in (b"\x00\x00\x00\x00", (P.MAX_FRAME + 1).to_bytes(4, "big")):
        try:
            P.FrameDecoder().feed(bad)
            raise AssertionError("should have raised")
        except P.ProtocolError:
            pass
    try:
        P.FrameDecoder().feed(P.encode_frame({"type": "X"})[:4] + b"\xff\xfe")
    except P.ProtocolError:
        pass


def test_decode_validation():
    for bad in (b"not json", b"[1,2]", b'{"type":5}', b'{"type":"LOGIN"}'):
        try:
            P.decode(bad)
            raise AssertionError("accepted %r" % bad)
        except P.ProtocolError:
            pass
    assert P.decode(b'{"type":"LOGIN","name":"bob"}')["name"] == "bob"


def test_clean_name():
    assert P.clean_name(" bob_1 ") == "bob_1"
    for bad in ("", "x" * 40, "a b", "<script>", 12):
        try:
            P.clean_name(bad)
            raise AssertionError("accepted %r" % (bad,))
        except P.ProtocolError:
            pass


# ---- physics / rules --------------------------------------------------------
def test_lands_on_platform():
    m = G.Match([(1, "a"), (2, "b")])
    run_ticks(m, 120)
    p = m.players[1]
    assert p.on_ground and p.y in (360, 480), p.y


def test_jump_and_double_jump():
    m = G.Match([(1, "a"), (2, "b")])
    run_ticks(m, 120)
    p = m.players[1]
    y0 = p.y
    run_ticks(m, 1, {1: P.pack_keys(jump=True)})
    assert p.vy < 0 and p.jumps_left == G.MAX_JUMPS - 1
    run_ticks(m, 1, {1: 0})
    run_ticks(m, 1, {1: P.pack_keys(jump=True)})      # second press = double jump
    assert p.jumps_left == G.MAX_JUMPS - 2
    run_ticks(m, 1, {1: 0})
    run_ticks(m, 1, {1: P.pack_keys(jump=True)})      # third press: no jumps left
    assert p.jumps_left == 0
    run_ticks(m, 120)
    assert p.on_ground


def test_hit_applies_damage_and_knockback():
    m = G.Match([(1, "a"), (2, "b")])
    run_ticks(m, 150)                                  # let invuln expire + land
    a, b = m.players[1], m.players[2]
    a.x, a.y, a.facing = 600, 480, 1
    b.x, b.y = 640, 480
    ev = run_ticks(m, 1, {1: P.pack_keys(attack=True)})
    hits = [e for e in ev if e["ev"] == "HIT"]
    assert len(hits) == 1 and hits[0]["victim"] == 2
    assert b.damage == G.HIT_DAMAGE and b.vx > 0 and b.vy < 0
    ev2 = run_ticks(m, 3, {1: P.pack_keys(attack=True)})   # same swing: no double hit
    assert not [e for e in ev2 if e["ev"] == "HIT"]


def test_invulnerable_after_spawn():
    m = G.Match([(1, "a"), (2, "b")])
    a, b = m.players[1], m.players[2]
    a.x, a.y, a.facing = 600, 480, 1
    b.x, b.y = 640, 480
    ev = run_ticks(m, 1, {1: P.pack_keys(attack=True)})
    assert not [e for e in ev if e["ev"] == "HIT"]


def test_ko_by_falling_and_ranking():
    m = G.Match([(1, "a"), (2, "b"), (3, "c")])
    run_ticks(m, 150)
    victim = m.players[3]
    for _ in range(G.START_STOCKS):                    # c falls off 3 times
        victim.x, victim.y = -500, 0
        run_ticks(m, 1)
        run_ticks(m, G.RESPAWN_TICKS + 2)
    assert victim.stocks == 0 and 3 in m.elimination_order and not m.over
    m.players[2].x, m.players[2].y = -500, 0           # now b falls out 3 times
    for _ in range(G.START_STOCKS):
        m.players[2].x, m.players[2].y = -500, 0
        run_ticks(m, 1)
        run_ticks(m, G.RESPAWN_TICKS + 2)
    assert m.over and m.winner == 1
    r = m.results()
    assert [x["pid"] for x in r] == [1, 2, 3], r       # winner, then later-eliminated first


def test_ko_credit():
    m = G.Match([(1, "a"), (2, "b")])
    run_ticks(m, 150)
    a, b = m.players[1], m.players[2]
    a.x, a.y, a.facing = 600, 480, 1
    b.x, b.y = 640, 480
    run_ticks(m, 1, {1: P.pack_keys(attack=True)})     # a hits b
    b.x, b.y = -500, 0                                 # b then falls out
    ev = run_ticks(m, 1)
    ko = [e for e in ev if e["ev"] == "KO"][0]
    assert ko["by"] == 1 and a.kos == 1


def test_forfeit_ranked_last_and_game_ends():
    m = G.Match([(1, "a"), (2, "b"), (3, "c")])
    ev = m.remove_player(1)                            # a disconnects mid-game
    assert {"ev": "PLAYER_LEFT", "pid": 1} in ev and not m.over   # b and c still fight
    assert m.remove_player(1) == []                    # idempotent
    ev = m.remove_player(2)                            # b disconnects -> c is alone
    assert m.over and m.winner == 3
    assert {"ev": "GAME_OVER", "winner": 3} in ev
    r = m.results()
    assert [x["pid"] for x in r] == [3, 2, 1], r       # winner, then forfeits (latest first)
    assert [x["forfeit"] for x in r] == [False, True, True]


def test_lone_survivor_wins_when_others_leave():
    m = G.Match([(1, "a"), (2, "b"), (3, "c")])
    m.remove_player(2)
    ev = m.remove_player(3)
    assert m.over and m.winner == 1
    assert [x["pid"] for x in m.results()][0] == 1


def test_stale_input_ignored():
    m = G.Match([(1, "a"), (2, "b")])
    m.set_input(1, 10, P.KEY_LEFT)
    m.set_input(1, 5, P.KEY_RIGHT)                     # late, out-of-order packet
    assert m.players[1].keys == P.KEY_LEFT
    m.set_input(99, 1, 0)                              # unknown pid: no crash


def test_snapshot_fits_in_one_datagram():
    m = G.Match([(1, "alice"), (2, "bob"), (3, "carol")])
    run_ticks(m, 30)
    size = len(P.encode(P.msg(P.SNAPSHOT, **m.snapshot())))
    assert size < 500, size


def test_random_bot_match_terminates_without_errors():
    rng = random.Random(7)
    m = G.Match([(1, "a"), (2, "b"), (3, "c")])
    keys = {1: 0, 2: 0, 3: 0}
    for t in range(60 * P.TICK_RATE):                  # up to 60 simulated seconds
        if t % 6 == 0:
            for pid in keys:
                keys[pid] = P.pack_keys(left=rng.random() < .3, right=rng.random() < .4,
                                        jump=rng.random() < .15, attack=rng.random() < .35)
        run_ticks(m, 1, keys)
        if m.over:
            break
    r = m.results()
    assert len(r) == 3 and sorted(x["rank"] for x in r) == [1, 2, 3]


# ---- advanced combat ----------------------------------------------------------
def _duel(char_a=None, char_b=None, ax=600, bx=640):
    a_entry = (1, "a", char_a) if char_a else (1, "a")
    b_entry = (2, "b", char_b) if char_b else (2, "b")
    m = G.Match([a_entry, b_entry])
    run_ticks(m, 150)
    a, b = m.players[1], m.players[2]
    a.x, a.y, a.facing, a.vx = ax, 480, 1, 0.0
    b.x, b.y, b.vx = bx, 480, 0.0
    return m, a, b


def _hits(ev):
    return [e for e in ev if e["ev"] == "HIT"]


def test_heavy_attack_winds_up_then_hits_harder():
    m, a, b = _duel(bx=650)
    ev = run_ticks(m, 1, {1: P.pack_keys(heavy_attack=True)})
    assert not _hits(ev) and a.windup > 0 and a.action == G.A_WINDUP
    ev = run_ticks(m, G.HEAVY_WINDUP_TICKS + 1, {1: 0})
    hits = _hits(ev)
    assert len(hits) == 1 and hits[0]["move"] == "heavy", ev
    assert b.damage == G.HEAVY_DAMAGE and b.action == G.A_STUN


def test_dodge_grants_invulnerability():
    m, a, b = _duel()
    run_ticks(m, 1, {2: P.pack_keys(dodge=True)})
    assert b.dodge_t > 0 and b.invuln > 0 and b.action == G.A_DODGE
    ev = run_ticks(m, 1, {1: P.pack_keys(attack=True), 2: P.pack_keys(dodge=True)})
    assert not _hits(ev) and b.damage == 0


def test_projectile_special_hits_at_range():
    m, a, b = _duel("blaze", None, ax=400, bx=800)
    ev = run_ticks(m, 1, {1: P.pack_keys(special=True)})
    assert m.projectiles and [e for e in ev if e["ev"] == "SPECIAL"]
    snap = m.snapshot()
    assert "pr" in snap and len(P.encode(P.msg(P.SNAPSHOT, **snap))) < 500
    ev = run_ticks(m, 40, {1: 0})
    hits = _hits(ev)
    assert hits and hits[0]["victim"] == 2 and hits[0]["move"] == "special"
    assert not m.projectiles


def test_special_has_cooldown():
    m, a, b = _duel("vex", None, ax=400, bx=900)
    run_ticks(m, 1, {1: P.pack_keys(special=True)})
    run_ticks(m, 1, {1: 0})
    run_ticks(m, 1, {1: P.pack_keys(special=True)})       # still on cooldown
    assert m._proj_id == 1 and a.special_cd > 0


def test_armor_prevents_stun_and_cuts_knockback():
    m, a, b = _duel(None, "titan")
    run_ticks(m, 1, {2: P.pack_keys(special=True)})
    assert b.armor > 0
    ev = run_ticks(m, 1, {1: P.pack_keys(attack=True)})
    assert _hits(ev) and b.hitstun == 0
    assert b.damage == G.HIT_DAMAGE * G.ARMOR_DAMAGE_MULT


def test_slam_shockwave_hits_grounded_neighbour():
    m, a, b = _duel("ragnar", None, ax=600, bx=700)
    run_ticks(m, 1, {1: P.pack_keys(special=True)})
    ev = run_ticks(m, 40, {1: 0})
    assert [e for e in ev if e["ev"] == "SHOCK"]
    assert [h for h in _hits(ev) if h["victim"] == 2]


def test_drop_through_soft_platform_but_not_main():
    m = G.Match([(1, "a"), (2, "b")])
    run_ticks(m, 120)
    p = m.players[1]
    assert p.on_ground and p.y == 360                # spawn lands on a soft platform
    run_ticks(m, 1, {1: P.pack_keys(down=True)})
    run_ticks(m, 5, {1: 0})
    assert p.on_ground and p.y == 360                # a tap does not drop (free for down-attacks)
    run_ticks(m, G.DROP_HOLD_TICKS + 1, {1: P.pack_keys(down=True)})
    run_ticks(m, 60, {1: 0})
    assert p.on_ground and p.y == 480                # held: fell through to the main island
    run_ticks(m, 10, {1: P.pack_keys(down=True)})
    run_ticks(m, 30, {1: 0})
    assert p.on_ground and p.y == 480                # main island is solid


def test_directional_move_selection():
    K = P.pack_keys
    assert G.pick_move("light", K(), True) == "jab"
    assert G.pick_move("light", K(right=True), True) == "lunge"
    assert G.pick_move("light", K(down=True), True) == "sweep"
    assert G.pick_move("light", K(down=True), False) == "spike"
    assert G.pick_move("heavy", K(), True) == "launcher"
    assert G.pick_move("heavy", K(left=True), True) == "smash"
    assert G.pick_move("heavy", K(down=True), True) == "quake"
    assert G.pick_move("heavy", K(), False) == "cyclone"


def test_side_heavy_lunges_forward_and_hits_hard():
    m, a, b = _duel(bx=700)
    run_ticks(m, 1, {1: P.pack_keys(right=True, heavy_attack=True)})
    assert G.MOVE_IDS[a.mv] == "smash" and a.action == G.A_WINDUP
    ev = run_ticks(m, G.MOVES["smash"]["startup"] + 3, {1: 0})
    hits = _hits(ev)
    assert hits and hits[0]["mv"] == "smash" and b.damage == G.MOVES["smash"]["dmg"]


def test_quake_hits_both_sides():
    m = G.Match([(1, "a"), (2, "b"), (3, "c")])
    run_ticks(m, 150)
    a, b, c = m.players[1], m.players[2], m.players[3]
    for p, x in ((a, 640), (b, 590), (c, 690)):
        p.x, p.y, p.vx = x, 480, 0.0
    run_ticks(m, 1, {1: P.pack_keys(down=True, heavy_attack=True)})
    ev = run_ticks(m, G.MOVES["quake"]["startup"] + 2, {1: 0})
    victims = {h["victim"] for h in _hits(ev)}
    assert victims == {2, 3}, ev
    assert b.vx < 0 < c.vx                           # knocked away on each side


def test_air_down_light_spikes_downward():
    m, a, b = _duel(bx=600)
    a.y, b.y = 300, 340                               # a above b, both airborne
    a.vy = b.vy = 0.0
    run_ticks(m, 1)                                   # refresh on_ground after the teleport
    run_ticks(m, 1, {1: P.pack_keys(down=True, light_attack=True)})
    assert G.MOVE_IDS[a.mv] == "spike"
    ev = run_ticks(m, 4, {1: P.pack_keys(down=True)})
    hits = [h for h in _hits(ev) if h["victim"] == 2]
    assert hits and hits[0]["mv"] == "spike"
    assert b.vy > 0                                   # driven down, not launched up


def test_countdown_freezes_input():
    m = G.Match([(1, "a"), (2, "b")], countdown=10)
    run_ticks(m, 5, {1: P.pack_keys(right=True, jump=True)})
    assert m.players[1].vx == 0 and "cd" in m.snapshot()
    run_ticks(m, 10, {1: P.pack_keys(right=True)})
    assert m.players[1].vx > 0 and "cd" not in m.snapshot()


# ---- server (transport-agnostic, driven through a fake transport) -----------
class FakeTransport:
    def __init__(self):
        self.sent, self.cb = [], None

    def on_disconnect(self, cb):
        self.cb = cb

    def send_reliable(self, pid, msg):
        self.sent.append((pid, msg))

    send_unreliable = send_reliable

    def poll(self):
        return []

    def close_player(self, pid):
        pass

    def of_type(self, pid, type_):
        return [m for p, m in self.sent if p == pid and m["type"] == type_]


def test_server_room_flow_char_select_and_rematch():
    from server.server_core import Server
    t = FakeTransport()
    s = Server(t)
    s._handle(1, P.msg(P.LOGIN, name="alice"))
    s._handle(2, P.msg(P.LOGIN, name="bob"))
    s._handle(3, P.msg(P.LOGIN, name="alice"))                # duplicate name
    assert t.of_type(3, P.LOGIN_ERR)
    s._handle(1, P.msg(P.CREATE_ROOM, room="arena"))
    s._handle(2, P.msg(P.JOIN_ROOM, room="arena"))
    s._handle(2, P.msg(P.SELECT_CHAR, char="titan"))
    s._handle(2, P.msg(P.SELECT_CHAR, char="nobody"))          # rejected
    assert t.of_type(2, P.ERROR)
    s._handle(2, P.msg(P.START_GAME))                          # not host
    room = s.rooms["arena"]
    assert room.match is None
    s._handle(1, P.msg(P.START_GAME))
    assert room.match.players[2].char_id == "titan" and room.match.countdown > 0
    assert t.of_type(2, P.GAME_STARTED)[0]["players"][1]["char"] == "titan"
    s._handle(2, P.msg(P.SELECT_CHAR, char="kira"))            # locked mid-game
    assert room.match.players[2].char_id == "titan"
    t.cb(2)                                                    # bob disconnects
    over = t.of_type(1, P.GAME_OVER)
    assert over and over[0]["winner"] == 1
    assert room.match is None                                  # back to select
    assert t.of_type(1, P.ROOM_UPDATE)[-1]["started"] is False


# ---- maps ------------------------------------------------------------------
def test_every_map_spawn_lands_on_a_platform():
    from common import maps as M
    for map_id in M.ORDER:
        m = G.Match([(1, "a"), (2, "b"), (3, "c")], map_id=map_id)
        run_ticks(m, 90)
        for p in m.players.values():
            assert p.on_ground and p.alive, (map_id, p.pid, p.x, p.y)


def test_harbor_gap_is_deadly_and_docks_are_solid():
    m = G.Match([(1, "a"), (2, "b")], map_id="moon_harbor")
    run_ticks(m, 120)
    p = m.players[1]
    p.x, p.y, p.vx, p.vy = 300, 480, 0.0, 0.0           # on the left dock
    run_ticks(m, 2)
    run_ticks(m, 20, {1: P.pack_keys(down=True)})
    assert p.on_ground and p.y == 500                    # solid dock: holding down does nothing
    p.x, p.y, p.vx, p.vy = 640, 440, 0.0, 0.0            # in the gap, below the bridge
    ev = run_ticks(m, 60)
    assert [e for e in ev if e["ev"] == "KO" and e["victim"] == 1]


def test_host_picks_map_and_match_uses_it():
    from server.server_core import Server
    t = FakeTransport()
    s = Server(t)
    s._handle(1, P.msg(P.LOGIN, name="a"))
    s._handle(2, P.msg(P.LOGIN, name="b"))
    s._handle(1, P.msg(P.CREATE_ROOM, room="r"))
    s._handle(2, P.msg(P.JOIN_ROOM, room="r"))
    s._handle(2, P.msg(P.SELECT_MAP, map="citadel"))       # not host: refused
    assert s.rooms["r"].map_id != "citadel"
    s._handle(1, P.msg(P.SELECT_MAP, map="citadel"))
    assert t.of_type(2, P.ROOM_UPDATE)[-1]["map"] == "citadel"
    s._handle(1, P.msg(P.START_GAME))
    assert s.rooms["r"].match.map_id == "citadel"
    assert t.of_type(2, P.GAME_STARTED)[0]["map"] == "citadel"


def test_tcp_server_survives_simultaneous_disconnects():
    import socket
    import threading
    import time
    from server.server_core import Server
    from server.transport_tcp import TCPTransport
    transport = TCPTransport(0, "127.0.0.1")
    port = transport.listener.getsockname()[1]
    srv = Server(transport)
    th = threading.Thread(target=srv.run, daemon=True)
    th.start()

    def client(name):
        s = socket.create_connection(("127.0.0.1", port))
        s.sendall(P.encode_frame(P.msg(P.LOGIN, name=name)))
        return s

    a, b, c = client("a"), client("b"), client("c")
    time.sleep(0.1)
    a.sendall(P.encode_frame(P.msg(P.CREATE_ROOM, room="r")))
    time.sleep(0.05)
    for s in (b, c):
        s.sendall(P.encode_frame(P.msg(P.JOIN_ROOM, room="r")))
    time.sleep(0.05)
    a.sendall(P.encode_frame(P.msg(P.START_GAME)))
    time.sleep(0.2)
    b.close()
    c.close()                                        # two drops in the same instant
    a.settimeout(2.0)
    dec, got_over, deadline = P.FrameDecoder(), False, time.monotonic() + 2.0
    while not got_over and time.monotonic() < deadline:
        for m in dec.feed(a.recv(65536)):
            got_over = got_over or m["type"] == P.GAME_OVER
    a.close()
    assert th.is_alive(), "server thread died"
    assert got_over, "remaining player never got GAME_OVER"


def main():
    tests = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_")]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print("PASS", name)
        except Exception as e:                         # noqa: BLE001
            failed += 1
            print("FAIL", name, "->", repr(e))
    print("\n%d/%d passed" % (len(tests) - failed, len(tests)))
    raise SystemExit(1 if failed else 0)


if __name__ == "__main__":
    main()
