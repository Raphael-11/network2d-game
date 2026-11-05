"""Deterministic platform-fighter simulation. No networking in here.

The server owns one Match per room and calls step() at TICK_RATE. Both the TCP
and UDP versions use this exact code, so only the transport differs.
Coordinates: x grows right, y grows DOWN (screen style). A player's (x, y) is
the centre of their feet.

Combat kit (every fighter): eight directional attacks (see MOVES), dodge
(short invulnerable dash), fast-fall, drop through soft platforms (hold down),
and one signature special from common/characters.py.
"""
from . import protocol as P
from . import characters as C
from . import maps as M

DT = 1.0 / P.TICK_RATE

# The default ("classic") arena; real layouts live in common/maps.py.
_CLASSIC = M.MAPS["classic"]
BLAST_L, BLAST_R, BLAST_TOP, BLAST_BOTTOM = _CLASSIC["blast"]
PLATFORMS = [(xl, xr, y) for xl, xr, y, _solid in _CLASSIC["platforms"]]
SPAWNS = _CLASSIC["spawns"]

# player tuning (pixels, seconds); scaled per character by common/characters.py
HALF_W, HEIGHT = 20, 60
RUN_SPEED = 300.0
GROUND_ACCEL = 3000.0
AIR_ACCEL = 1500.0
FRICTION = 2200.0
OVERSPEED_DRAG = 600.0     # slows knockback speed back toward RUN_SPEED
GRAVITY = 1800.0
MAX_FALL = 900.0
FAST_FALL = 1300.0
JUMP_V = 650.0
MAX_JUMPS = 2
DROP_TICKS = 8
DROP_HOLD_TICKS = 4        # hold down this long to fall through; a tap stays free for down-attacks

# combat
START_STOCKS = 3
ATTACK_ACTIVE_TICKS = 4
ATTACK_COOLDOWN_TICKS = 15
ATTACK_REACH, ATTACK_H = 60, 50
HIT_DAMAGE = 10.0
HEAVY_WINDUP_TICKS = 9
HEAVY_ACTIVE_TICKS = 5
HEAVY_COOLDOWN_TICKS = 34
HEAVY_DAMAGE = 17.0
KB_BASE, KB_SCALE = 250.0, 7.0
KB_UP = 0.55
HITSTUN_TICKS = 8
DODGE_TICKS = 9
DODGE_COOLDOWN_TICKS = 42
DODGE_SPEED = 640.0
ARMOR_DAMAGE_MULT = 0.7
ARMOR_KB_MULT = 0.3
RESPAWN_TICKS = 45
INVULN_TICKS = 60
KO_CREDIT_TICKS = 3 * P.TICK_RATE
COUNTDOWN_TICKS = 3 * P.TICK_RATE

# snapshot state bits
S_ALIVE, S_ATTACK, S_INVULN, S_GROUND, S_ARMOR = 1, 2, 4, 8, 16
# snapshot action codes (drive client animation)
A_IDLE, A_LIGHT, A_WINDUP, A_HEAVY, A_SPECIAL, A_DODGE, A_STUN = range(7)

SLAM_MOVE = {"name": "special", "dmg": 14.0, "kb": 1.3, "ang": 1.0}
PULL_MOVE = {"name": "special", "dmg": 6.0, "kb": 0.0, "ang": 0.0}

# Directional moveset. reach is a multiplier of ATTACK_REACH (then of the
# fighter's own reach). ang < 0 knocks the victim DOWN (a spike).
# shapes: front | frontup (front + high) | below | around (both sides)
MOVES = {
    "jab":      dict(cat="light", startup=0, active=ATTACK_ACTIVE_TICKS, cd=ATTACK_COOLDOWN_TICKS,
                     dmg=HIT_DAMAGE, kb=1.0, ang=KB_UP, shape="front", reach=1.0, h=ATTACK_H, yoff=0),
    "lunge":    dict(cat="light", startup=2, active=5, cd=18, dmg=9.0, kb=1.0, ang=0.35,
                     shape="front", reach=1.25, h=44, yoff=6, dash=480.0),
    "sweep":    dict(cat="light", startup=1, active=5, cd=18, dmg=8.0, kb=0.9, ang=1.15, xr=0.6,
                     shape="front", reach=1.35, h=26, yoff=34),
    "spike":    dict(cat="light", startup=2, active=5, cd=20, dmg=9.0, kb=1.0, ang=-0.9, xr=0.35,
                     shape="below", reach=0.8),
    "launcher": dict(cat="heavy", startup=HEAVY_WINDUP_TICKS, active=HEAVY_ACTIVE_TICKS, cd=HEAVY_COOLDOWN_TICKS,
                     dmg=HEAVY_DAMAGE, kb=1.35, ang=1.45, xr=0.4, shape="frontup", reach=1.1),
    "smash":    dict(cat="heavy", startup=11, active=5, cd=38, dmg=19.0, kb=1.55, ang=0.55,
                     shape="front", reach=1.45, h=60, yoff=-5, dash=380.0),
    "quake":    dict(cat="heavy", startup=10, active=6, cd=40, dmg=14.0, kb=1.3, ang=0.95,
                     shape="around", reach=1.3, h=30, yoff=32),
    "cyclone":  dict(cat="heavy", startup=5, active=8, cd=34, dmg=13.0, kb=1.2, ang=0.8,
                     shape="around", reach=0.9, h=70, yoff=-5),
}
MOVE_IDS = [None] + list(MOVES)          # index sent in snapshots for animation


def pick_move(cat, k, on_ground):
    """Choose the directional variant from the held keys at the moment of the press."""
    down = k & P.KEY_DOWN
    side = (k & P.KEY_LEFT) or (k & P.KEY_RIGHT)
    if cat == "light":
        if down:
            return "sweep" if on_ground else "spike"
        return "lunge" if side else "jab"
    if not on_ground:
        return "cyclone"
    if down:
        return "quake"
    return "smash" if side else "launcher"


def _build_move(key, ch):
    m = dict(MOVES[key])
    m["key"] = key
    m["name"] = m["cat"]
    m["reach"] = ATTACK_REACH * m["reach"] * ch["reach"]
    return m


def _sign(v):
    return 1 if v >= 0 else -1


class Player:
    def __init__(self, pid, name, slot, char_id=C.DEFAULT, spawns=SPAWNS):
        self.pid, self.name, self.slot = pid, name, slot
        self.spawns = spawns
        self.char_id = char_id if char_id in C.CHARACTERS else C.DEFAULT
        self.ch = C.CHARACTERS[self.char_id]
        self.stocks = START_STOCKS
        self.kos = 0
        self.damage_dealt = 0.0
        self.keys = 0
        self.prev_keys = 0
        self.last_input_seq = 0
        self.last_hit_by = None
        self.last_hit_tick = -10**9
        self.forfeited = False
        self.spawn()
        self.alive = True
        self.respawn_timer = 0

    def spawn(self):
        self.x, self.y = self.spawns[self.slot % len(self.spawns)]
        self.vx = self.vy = 0.0
        self.facing = 1 if self.x <= 640 else -1
        self.on_ground = False
        self.ground_solid = False
        self.jumps_left = MAX_JUMPS
        self.damage = 0.0
        self.attack_timer = 0
        self.attack_cd = 0
        self.move = None
        self.windup = 0
        self.pending = None      # move key waiting for its startup to finish
        self.mv = 0              # MOVE_IDS index of the current/last attack (animation)
        self.down_hold = 0
        self.special_t = 0
        self.special_cd = 0
        self.slamming = False
        self.armor = 0
        self.dodge_t = 0
        self.dodge_cd = 0
        self.drop_t = 0
        self.hitstun = 0
        self.invuln = INVULN_TICKS
        self.hit_this_swing = set()
        self.action = A_IDLE
        self.action_t = 0


class Match:
    def __init__(self, players, countdown=0, map_id="classic"):
        """players: list of (pid, name) or (pid, name, char_id). Order decides spawn slots."""
        self.map_id = map_id if map_id in M.MAPS else "classic"
        mp = M.MAPS[self.map_id]
        self.platforms = mp["platforms"]
        self.blast = mp["blast"]
        self.players = {}
        for i, entry in enumerate(players):
            char_id = entry[2] if len(entry) > 2 else C.DEFAULT
            self.players[entry[0]] = Player(entry[0], entry[1], i, char_id, mp["spawns"])
        self.tick = 0
        self.countdown = countdown
        self.projectiles = []
        self._proj_id = 0
        self.elimination_order = []   # pids, earliest eliminated first
        self.forfeits = []            # pids that disconnected/left mid-game
        self.over = False
        self.winner = None

    # -- input -------------------------------------------------------------
    def set_input(self, pid, seq, keys):
        p = self.players.get(pid)
        if p is None or seq <= p.last_input_seq:   # ignore stale/duplicate input
            return
        p.last_input_seq = seq
        p.keys = int(keys) & P.KEY_MASK

    def remove_player(self, pid):
        """Player disconnected or left mid-match: they forfeit (ranked last)."""
        p = self.players.get(pid)
        if p is None or p.forfeited or p.stocks <= 0:
            return []
        p.forfeited, p.stocks, p.alive = True, 0, False
        self.forfeits.append(pid)
        return [{"ev": "PLAYER_LEFT", "pid": pid}] + self._check_over()

    # -- simulation ----------------------------------------------------------
    def step(self):
        if self.over:
            return []
        self.tick += 1
        frozen = self.countdown > 0
        if frozen:
            self.countdown -= 1
        events = []
        for p in self.players.values():
            if p.stocks > 0:
                self._step_player(p, events, frozen)
        for p in self.players.values():
            if p.alive and p.attack_timer > 0 and p.move is not None:
                self._resolve_attack(p, events)
        self._step_projectiles(events)
        for p in self.players.values():
            if p.alive:
                self._check_ko(p, events)
        events += self._check_over()
        return events

    @staticmethod
    def _set_action(p, action):
        p.action = action
        p.action_t = 0

    @staticmethod
    def _friction(p):
        if p.on_ground:
            dv = FRICTION * DT
            p.vx = 0.0 if abs(p.vx) <= dv else p.vx - dv * _sign(p.vx)

    def _step_player(self, p, events, frozen=False):
        if not p.alive:
            p.respawn_timer -= 1
            if p.respawn_timer <= 0 and p.stocks > 0:
                p.spawn()
                p.alive = True
                events.append({"ev": "RESPAWN", "pid": p.pid})
            return
        k = 0 if frozen else p.keys
        pressed = k & ~p.prev_keys
        p.prev_keys = k
        p.down_hold = p.down_hold + 1 if k & P.KEY_DOWN else 0
        p.action_t += 1
        for attr in ("invuln", "attack_cd", "special_cd", "dodge_cd", "armor", "drop_t"):
            v = getattr(p, attr)
            if v > 0:
                setattr(p, attr, v - 1)
        if p.attack_timer > 0:
            p.attack_timer -= 1
            if p.attack_timer == 0:
                p.move = None
                if p.action in (A_LIGHT, A_HEAVY) or (p.action == A_SPECIAL and p.special_t == 0):
                    self._set_action(p, A_IDLE)

        stunned = p.hitstun > 0
        if stunned:
            p.hitstun -= 1
        elif p.action == A_STUN:
            self._set_action(p, A_IDLE)

        move = (1 if k & P.KEY_RIGHT else 0) - (1 if k & P.KEY_LEFT else 0)
        gravity = True
        if p.dodge_t > 0:
            p.dodge_t -= 1
            p.vy = 0.0
            gravity = False
            if p.dodge_t == 0:
                p.vx *= 0.35
                self._set_action(p, A_IDLE)
        elif p.special_t > 0:
            gravity = self._step_special(p)
        elif p.windup > 0:
            p.windup -= 1
            self._friction(p)
            if p.windup == 0 and p.pending:
                self._activate(p, p.pending)
        elif stunned:
            self._friction(p)
        else:
            self._controls(p, k, pressed, move, events)

        if abs(p.vx) > RUN_SPEED * p.ch["speed"] and p.dodge_t == 0 and p.special_t == 0:
            p.vx -= OVERSPEED_DRAG * DT * _sign(p.vx)       # knockback speed fades

        old_y = p.y
        if gravity:
            fast = (k & P.KEY_DOWN) and not stunned and p.vy > 0
            cap = FAST_FALL if fast else MAX_FALL
            p.vy = min(p.vy + GRAVITY * DT * (1.8 if fast else 1.0), max(cap, p.vy))
        p.x += p.vx * DT
        p.y += p.vy * DT
        p.on_ground = False
        if p.vy >= 0:   # one-way platforms: land only when falling from above
            for xl, xr, ys, solid in self.platforms:
                if p.drop_t > 0 and not solid:
                    continue
                if xl - HALF_W < p.x < xr + HALF_W and old_y <= ys <= p.y:
                    p.y, p.vy, p.on_ground = ys, 0.0, True
                    p.ground_solid = solid
                    p.jumps_left = MAX_JUMPS
                    break
        if p.slamming and p.on_ground:
            self._land_slam(p, events)

    def _controls(self, p, k, pressed, move, events):
        ch = p.ch
        if move:
            if p.attack_timer == 0:
                p.facing = move
            accel = (GROUND_ACCEL if p.on_ground else AIR_ACCEL) * DT
            target = move * RUN_SPEED * ch["speed"]
            if move > 0 and p.vx < target:
                p.vx = min(p.vx + accel, target)
            elif move < 0 and p.vx > target:
                p.vx = max(p.vx - accel, target)
        else:
            self._friction(p)

        if (p.down_hold == DROP_HOLD_TICKS and p.on_ground and not p.ground_solid
                and p.attack_timer == 0):
            p.drop_t = DROP_TICKS
            p.on_ground = False
        if pressed & P.KEY_JUMP and p.jumps_left > 0:          # edge-triggered
            p.vy = -JUMP_V * ch["jump"]
            p.jumps_left -= 1
            p.on_ground = False

        if pressed & P.KEY_DODGE and p.dodge_cd == 0:
            p.dodge_t = DODGE_TICKS
            p.dodge_cd = DODGE_COOLDOWN_TICKS
            p.invuln = max(p.invuln, DODGE_TICKS)
            p.vx = move * DODGE_SPEED * ch["speed"]
            p.vy = 0.0
            p.attack_timer, p.move = 0, None
            self._set_action(p, A_DODGE)
            return
        if pressed & P.KEY_SPECIAL and p.special_cd == 0 and p.attack_timer == 0:
            self._start_special(p, events)
            return
        for cat, key in (("heavy", P.KEY_HEAVY_ATTACK), ("light", P.KEY_LIGHT_ATTACK)):
            if pressed & key and p.attack_cd == 0:
                self._start_attack(p, pick_move(cat, k, p.on_ground))
                return

    def _start_attack(self, p, key):
        m = MOVES[key]
        p.mv = MOVE_IDS.index(key)
        p.attack_cd = m["cd"]
        self._set_action(p, A_WINDUP if m["cat"] == "heavy" else A_LIGHT)
        if m["startup"] == 0:
            self._activate(p, key)
        else:
            p.windup, p.pending = m["startup"], key

    def _activate(self, p, key):
        m = _build_move(key, p.ch)
        p.pending = None
        p.move = m
        p.attack_timer = m["active"]
        p.hit_this_swing = set()
        if "dash" in m:
            p.vx = p.facing * m["dash"] * p.ch["speed"]
        if m["cat"] == "heavy":
            self._set_action(p, A_HEAVY)

    # -- specials ------------------------------------------------------------
    def _start_special(self, p, events):
        sp = p.ch["special"]
        kind = sp["kind"]
        p.special_cd = sp["cd"]
        p.hit_this_swing = set()
        self._set_action(p, A_SPECIAL)
        if kind == "projectile":
            self._spawn_projectile(p, sp)
            p.special_t = 6
        elif kind == "dash":
            p.special_t = 7
            p.invuln = max(p.invuln, 7)
            p.move = {"name": "special", "dmg": 9.0, "kb": 1.0, "ang": 0.45, "shape": "body", "pad": 10}
            p.attack_timer = 7
        elif kind == "pounce":
            p.vx = p.facing * 720.0
            p.vy = -540.0
            p.on_ground = False
            p.special_t = 16
            p.move = {"name": "special", "dmg": 11.0, "kb": 1.2, "ang": 0.6, "shape": "body", "pad": 10}
            p.attack_timer = 16
        elif kind == "rise":
            p.vy = -950.0
            p.vx *= 0.3
            p.on_ground = False
            p.special_t = 12
            p.move = {"name": "special", "dmg": 10.0, "kb": 1.15, "ang": 1.5, "xr": 0.3,
                      "shape": "above", "reach": 70}
            p.attack_timer = 12
        elif kind == "slam":
            if p.on_ground:
                p.vy = -560.0
                p.on_ground = False
            p.slamming = True
            p.special_t = 45
        elif kind == "armor":
            p.armor = sp["dur"]
            p.special_t = 8
        elif kind == "pull":
            p.special_t = 10
            self._pull(p, sp, events)
        events.append({"ev": "SPECIAL", "pid": p.pid, "kind": kind,
                       "x": round(p.x), "y": round(p.y - HEIGHT / 2)})

    def _step_special(self, p):
        """Advance an in-progress special. Returns whether gravity applies."""
        p.special_t -= 1
        kind = p.ch["special"]["kind"]
        gravity = True
        if kind == "dash":
            p.vx = p.facing * 1150.0
            p.vy = 0.0
            gravity = False
            if p.special_t == 0:
                p.vx = p.facing * RUN_SPEED
        elif kind == "slam":
            if p.special_t < 37:                 # after a short hop, plummet
                p.vy = 1400.0
                gravity = False
            if p.special_t == 0:
                p.slamming = False
        elif kind in ("projectile", "armor", "pull"):
            self._friction(p)
        if p.special_t == 0 and p.action == A_SPECIAL and p.attack_timer == 0:
            self._set_action(p, A_IDLE)
        return gravity

    def _land_slam(self, p, events):
        p.slamming = False
        p.special_t = 4
        events.append({"ev": "SHOCK", "pid": p.pid, "x": round(p.x), "y": round(p.y)})
        for v in self.players.values():
            if v is p or not v.alive:
                continue
            if abs(v.x - p.x) < 150 and abs(v.y - p.y) < 80:
                self._apply_hit(p, v, SLAM_MOVE, _sign(v.x - p.x), events)

    def _pull(self, p, sp, events):
        cx, cy = p.x, p.y - HEIGHT / 2
        for v in self.players.values():
            if v is p or not v.alive or v.invuln > 0:
                continue
            dx, dy = cx - v.x, cy - (v.y - HEIGHT / 2)
            if dx * dx + dy * dy > sp["radius"] ** 2:
                continue
            if self._apply_hit(p, v, PULL_MOVE, _sign(dx), events):
                v.vx = _sign(dx) * 520.0
                v.vy = -260.0
                if v.armor == 0:
                    v.hitstun = 14

    def _spawn_projectile(self, p, sp):
        self._proj_id += 1
        self.projectiles.append({
            "id": self._proj_id, "owner": p.pid, "kind": C.PROJ_KINDS.index(sp["proj"]),
            "x": p.x + p.facing * (HALF_W + 12), "y": p.y - HEIGHT * 0.6,
            "vx": p.facing * sp["speed"], "r": sp["r"], "life": sp["life"],
            "move": {"name": "special", "dmg": float(sp["dmg"]), "kb": sp["kb"], "ang": 0.4},
        })

    def _step_projectiles(self, events):
        keep = []
        for pr in self.projectiles:
            pr["x"] += pr["vx"] * DT
            pr["life"] -= 1
            r = pr["r"]
            owner = self.players[pr["owner"]]
            hit = False
            for v in self.players.values():
                if v is owner or not v.alive or v.invuln > 0:
                    continue
                if (v.x - HALF_W - r < pr["x"] < v.x + HALF_W + r
                        and v.y - HEIGHT - r < pr["y"] < v.y + r):
                    self._apply_hit(owner, v, pr["move"], _sign(pr["vx"]), events)
                    hit = True
                    break
            if hit:
                events.append({"ev": "POP", "kind": pr["kind"], "x": round(pr["x"]), "y": round(pr["y"])})
            elif pr["life"] > 0 and self.blast[0] < pr["x"] < self.blast[1]:
                keep.append(pr)
        self.projectiles = keep

    # -- hits ----------------------------------------------------------------
    def _hitbox(self, a):
        m = a.move
        shape = m.get("shape", "front")
        if shape == "body":
            pad = m["pad"]
            return (a.x - HALF_W - pad, a.y - HEIGHT - pad, a.x + HALF_W + pad, a.y + pad)
        if shape == "above":
            return (a.x - HALF_W - 10, a.y - HEIGHT - m["reach"], a.x + HALF_W + 10, a.y - HEIGHT + 20)
        if shape == "below":
            return (a.x - HALF_W - 12, a.y - 25, a.x + HALF_W + 12, a.y + m["reach"])
        if shape == "around":
            top = a.y - HEIGHT + m["yoff"]
            return (a.x - HALF_W - m["reach"], top, a.x + HALF_W + m["reach"], top + m["h"])
        if shape == "frontup":
            x0 = a.x + (HALF_W - 15 if a.facing > 0 else -HALF_W + 15 - m["reach"])
            return (x0, a.y - HEIGHT - 50, x0 + m["reach"], a.y - HEIGHT + 50)
        reach = m["reach"]
        x0 = a.x + (HALF_W if a.facing > 0 else -HALF_W - reach)
        top = a.y - HEIGHT + m["yoff"]
        return (x0, top, x0 + reach, top + m["h"])

    def _resolve_attack(self, a, events):
        hit_l, hit_t, hit_r, hit_b = self._hitbox(a)
        for v in self.players.values():
            if v is a or not v.alive or v.invuln > 0 or v.pid in a.hit_this_swing:
                continue
            if (hit_l < v.x + HALF_W and hit_r > v.x - HALF_W
                    and hit_t < v.y and hit_b > v.y - HEIGHT):
                a.hit_this_swing.add(v.pid)
                dir_x = _sign(v.x - a.x) if a.move.get("shape") == "around" else a.facing
                self._apply_hit(a, v, a.move, dir_x, events)

    def _apply_hit(self, a, v, move, dir_x, events):
        if v.invuln > 0 or not v.alive:
            return False
        armored = v.armor > 0
        dmg = move["dmg"] * a.ch["power"] * (ARMOR_DAMAGE_MULT if armored else 1.0)
        v.damage += dmg
        a.damage_dealt += dmg
        kb = (KB_BASE + v.damage * KB_SCALE) * move["kb"] / v.ch["weight"]
        if armored:
            kb *= ARMOR_KB_MULT
        v.vx = dir_x * kb * move.get("xr", 1.0)
        v.vy = -kb * move.get("ang", KB_UP)
        v.on_ground = False
        if not armored:
            v.hitstun = HITSTUN_TICKS + int(kb / 140)
            v.windup = v.attack_timer = v.special_t = v.dodge_t = 0
            v.move = v.pending = None
            v.slamming = False
            self._set_action(v, A_STUN)
        v.last_hit_by, v.last_hit_tick = a.pid, self.tick
        events.append({"ev": "HIT", "attacker": a.pid, "victim": v.pid,
                       "damage": round(v.damage, 1), "move": move["name"],
                       "mv": move.get("key", move["name"]),
                       "x": round(v.x), "y": round(v.y - HEIGHT / 2), "kb": round(kb)})
        return True

    def _check_ko(self, p, events):
        bl, br, bt, bb = self.blast
        if not (p.x < bl or p.x > br or p.y < bt or p.y > bb):
            return
        p.stocks -= 1
        p.alive = False
        p.respawn_timer = RESPAWN_TICKS
        by = p.last_hit_by if self.tick - p.last_hit_tick <= KO_CREDIT_TICKS else None
        if by is not None and by in self.players and by != p.pid:
            self.players[by].kos += 1
        events.append({"ev": "KO", "victim": p.pid, "by": by, "stocks": p.stocks,
                       "x": round(min(max(p.x, bl), br)),
                       "y": round(min(max(p.y, bt), bb))})
        if p.stocks <= 0:
            self.elimination_order.append(p.pid)

    def _check_over(self):
        if self.over:
            return []
        standing = [p for p in self.players.values() if p.stocks > 0]
        if len(standing) > 1:
            return []
        self.over = True
        self.winner = standing[0].pid if standing else None
        return [{"ev": "GAME_OVER", "winner": self.winner}]

    # -- outputs -------------------------------------------------------------
    def snapshot(self):
        """Compact state broadcast every tick (<500 bytes for 3 players)."""
        rows = []
        for p in self.players.values():
            st = ((S_ALIVE if p.alive else 0) | (S_ATTACK if p.attack_timer > 0 else 0)
                  | (S_INVULN if p.invuln > 0 else 0) | (S_GROUND if p.on_ground else 0)
                  | (S_ARMOR if p.armor > 0 else 0))
            cd = p.ch["special"]["cd"]
            rows.append([p.pid, round(p.x, 1), round(p.y, 1), p.facing,
                         round(p.damage, 1), p.stocks, st, p.last_input_seq,
                         p.action, min(p.action_t, 99), round(100 * p.special_cd / cd), p.mv])
        snap = {"tick": self.tick, "p": rows}
        if self.projectiles:
            snap["pr"] = [[pr["id"], round(pr["x"]), round(pr["y"]), pr["kind"], _sign(pr["vx"])]
                          for pr in self.projectiles]
        if self.countdown:
            snap["cd"] = self.countdown
        return snap

    def results(self):
        """Final ranking: winner, then later eliminations, ..., forfeits last."""
        ranking = []
        if self.winner is not None:
            ranking.append(self.winner)
        ranking += [pid for pid in reversed(self.elimination_order) if pid not in ranking]
        ranking += [pid for pid in reversed(self.forfeits) if pid not in ranking]
        for pid in self.players:                 # anyone left (e.g. abandoned match)
            if pid not in ranking:
                ranking.append(pid)
        return [{"rank": i + 1, "pid": pid, "name": self.players[pid].name,
                 "char": self.players[pid].char_id,
                 "kos": self.players[pid].kos, "stocks": self.players[pid].stocks,
                 "dealt": round(self.players[pid].damage_dealt),
                 "forfeit": self.players[pid].forfeited}
                for i, pid in enumerate(ranking)]
