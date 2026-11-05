"""Pygame front end: title, lobby, fighter & arena select, battle and results.

The server is authoritative; this module renders what client_core decoded and
interpolated, plus local-only presentation (pose blending, hit-freeze, impact
effects, dust, follow camera) that never feeds back into gameplay.
"""
import math
import random
import time
from collections import deque

import pygame

from common import protocol as P
from common import physics as G
from common import characters as C
from common import maps as M
from common.timing import high_res_timer
from client import art, rig, stage
from client.art import OUTLINE, lighten, darken, lerp, lerp_col
from client.sfx import Sfx
from client.client_core import (ClientState, SCREEN_LOGIN, SCREEN_LOBBY, SCREEN_ROOM,
                                SCREEN_GAME, SCREEN_RESULTS)

W, H = 1280, 720
HUD_H = 108
FS = stage.ZOOM * rig.VIS            # battle: screen px per fighter unit

TEXT = (240, 238, 248)
MUTED = (160, 156, 190)
GOLD = (255, 204, 72)
PANEL = (24, 20, 44)
PANEL_EDGE = (92, 80, 140)
GOOD = (110, 230, 140)
BAD = (255, 92, 104)
ACCENT = (110, 200, 255)

CONTROLS = [("Move", "WASD / ZQSD"), ("Jump / Double", "W / Z / Space"), ("Fast-fall  (hold: drop)", "S / Down"),
            ("Light attack", "Mouse / E"), ("Heavy attack", "X"), ("Signature", "F"), ("Dodge", "Q / A / Shift")]
MOVE_LABEL = {"jab": "JAB", "lunge": "LUNGE", "sweep": "SWEEP", "spike": "SPIKE", "launcher": "LAUNCHER",
              "smash": "SMASH", "quake": "QUAKE", "cyclone": "CYCLONE"}
COMIC_WORDS = ["POW!", "BAM!", "WHAM!", "KRAK!", "SMASH!", "BOOM!", "THWACK!", "KAPOW!"]
ATTACK_ACTIONS = (G.A_LIGHT, G.A_WINDUP, G.A_HEAVY, G.A_SPECIAL, G.A_DODGE)


def starburst(cx, cy, r_out, r_in, n=12, rot=0.0, jitter=None):
    pts = []
    for i in range(n * 2):
        a = rot + i * math.pi / n
        r = r_out if i % 2 == 0 else r_in
        if jitter:
            r *= jitter[i % len(jitter)]
        pts.append((cx + math.cos(a) * r, cy + math.sin(a) * r))
    return pts


def damage_color(d):
    stops = [(0, (255, 255, 255)), (40, (255, 236, 120)), (80, (255, 160, 60)),
             (120, (255, 70, 60)), (180, (170, 20, 40))]
    for (d0, c0), (d1, c1) in zip(stops, stops[1:]):
        if d <= d1:
            return lerp_col(c0, c1, max(0.0, (d - d0) / (d1 - d0)))
    return stops[-1][1]


def wrap_pi(a):
    return (a + math.pi) % math.tau - math.pi


class Particle:
    __slots__ = ("x", "y", "vx", "vy", "life", "maxlife", "color", "r", "grav", "drag", "kind")

    def __init__(self, x, y, vx, vy, life, color, r=3.0, grav=900.0, drag=0.0, kind="dot"):
        self.x, self.y, self.vx, self.vy = x, y, vx, vy
        self.life = self.maxlife = life
        self.color, self.r, self.grav, self.drag, self.kind = color, r, grav, drag, kind

    def update(self, dt):
        self.vx *= 1 - min(1.0, self.drag * dt)
        self.vy = self.vy * (1 - min(1.0, self.drag * dt)) + self.grav * dt
        self.x += self.vx * dt
        self.y += self.vy * dt
        self.life -= dt
        return self.life > 0


class Vis:
    """Per-fighter presentation state (never sent anywhere)."""
    __slots__ = ("pose", "phase", "tumble", "air", "vy", "facing", "land_t", "jump_t", "freeze_until",
                 "freeze_at", "flash_until", "hurt_until", "anim", "dust_t", "smoke_t", "alive", "jitter_dir")

    def __init__(self):
        self.pose = None
        self.phase = 0.0
        self.tumble = 0.0
        self.air = False
        self.vy = 0.0
        self.facing = 1
        self.land_t = self.jump_t = -9.0
        self.freeze_until = self.flash_until = self.hurt_until = 0.0
        self.freeze_at = 0.0
        self.anim = None
        self.dust_t = self.smoke_t = 0.0
        self.alive = True
        self.jitter_dir = 1


class App:
    def __init__(self, state: ClientState, server_label=""):
        high_res_timer()                      # otherwise Windows caps the 60 fps limiter near 30 fps
        pygame.mixer.pre_init(22050, -16, 1, 512)
        pygame.init()
        pygame.display.set_caption("Brawl Arena")
        self.screen = pygame.display.set_mode((W, H), pygame.FULLSCREEN | pygame.SCALED)
        self.clock = pygame.time.Clock()
        self.state = state
        self.server_label = server_label
        self.t = 0.0

        self.f_logo = pygame.font.SysFont("Impact", 104)
        self.f_h1 = pygame.font.SysFont("Impact", 56)
        self.f_h2 = pygame.font.SysFont("Impact", 34)
        self.f_h3 = pygame.font.SysFont("Impact", 24)
        self.f_dmg = pygame.font.SysFont("Impact", 44)
        self.f_body = pygame.font.SysFont("Segoe UI", 19, bold=True)
        self.f_small = pygame.font.SysFont("Segoe UI", 15, bold=True)
        self.f_tiny = pygame.font.SysFont("Segoe UI", 13)

        self._text_cache = {}
        self._panel_cache = {}
        self._puff_cache = {}
        self._loading()
        self.sfx = Sfx()

        self.targets = []
        self.fields = {"name": state.name or "", "room": ""}
        self.focus = "name"
        self.hover_char = None
        self.menu_pose = {}

        self.cam = None
        self.backdrop = None
        self.stage = None
        self.vis = {}
        self.particles = []
        self.rings = []              # [x, y, r0, r1, life, maxlife, color, width]
        self.slashes = []            # [x, y, angle, t0, color, heavy]
        self.lines = []              # [x, y, t0, seed, heavy]
        self.floats = []             # [x, y, text, t0, color]
        self.beams = []              # [x, y, life, color]
        self.banners = []            # [text, t0, dur, color, font, sub]
        self.comics = []             # [x, y, word, t0, dur, scale, rot, color]
        self.sparks = []             # [x, y, t0, size, rot]
        self.ghosts = {}             # pid -> deque[(t, x, y, facing, pose, rot)]
        self.hud_shake = {}
        self.prev_action = {}
        self.white_flash = 0.0
        self.last_cd = 0
        self.esc_armed = 0.0
        self.prev_screen = None
        self.confetti_t = 0.0

    # ---- loading -------------------------------------------------------------
    def _loading(self):
        steps = [("portraits", art.preload), ("fighters", lambda: rig.preload(FS))]
        for mid in M.ORDER:
            steps.append((M.MAPS[mid]["name"], lambda m=mid: (stage.stage_art(m).scaled(stage.ZOOM),
                                                               stage.backdrop(m, W, H))))
        for i, (label, fn) in enumerate(steps):
            self.screen.fill((14, 10, 28))
            self.text("BRAWL ARENA", self.f_h1, GOLD, (W / 2, H / 2 - 60), "center", outline=4)
            bar = pygame.Rect(W / 2 - 220, H / 2 + 10, 440, 16)
            pygame.draw.rect(self.screen, (40, 34, 70), bar, border_radius=8)
            pygame.draw.rect(self.screen, GOLD, (bar.x, bar.y, bar.w * i / len(steps), bar.h), border_radius=8)
            pygame.draw.rect(self.screen, OUTLINE, bar, 2, border_radius=8)
            self.text("loading %s..." % label, self.f_small, MUTED, (W / 2, H / 2 + 46), "center")
            pygame.display.flip()
            pygame.event.pump()
            fn()

    # ---- main loop -----------------------------------------------------------
    def run(self):
        running = True
        while running:
            dt = min(0.05, self.clock.tick(60) / 1000.0)
            self.t += dt
            running = self._events()
            self.state.pump()
            self._on_screen_change()
            self._consume_fx()
            self._update_effects(dt)
            self.targets = []
            self._draw(dt)
            pygame.display.flip()
        pygame.quit()

    def _on_screen_change(self):
        s = self.state.screen
        if s == self.prev_screen:
            return
        if s == SCREEN_GAME:
            for lst in (self.particles, self.rings, self.slashes, self.lines, self.floats, self.beams,
                        self.banners, self.comics, self.sparks):
                lst.clear()
            self.ghosts.clear()
            self.vis.clear()
            self.prev_action.clear()
            self.last_cd = 0
            self.cam = stage.Camera(s_map(self.state), W, H, HUD_H)
            self.backdrop = stage.backdrop(s_map(self.state), W, H)
            self.stage = stage.stage_art(s_map(self.state))
            mp = M.get(s_map(self.state))
            self.banners.append([mp["name"].upper(), self.t, 2.6, GOLD, self.f_h1, mp.get("subtitle", "")])
        elif s == SCREEN_RESULTS:
            self.sfx.play("victory")
            self.particles.clear()
        elif s == SCREEN_LOBBY:
            self.focus = "room"
        self.prev_screen = s

    # ---- input -------------------------------------------------------------
    def _events(self):
        s = self.state
        for e in pygame.event.get():
            if e.type == pygame.QUIT:
                return False
            if e.type == pygame.MOUSEBUTTONDOWN and e.button == 1:
                for rect, cb in reversed(self.targets):
                    if rect.collidepoint(e.pos):
                        cb()
                        break
            if e.type != pygame.KEYDOWN:
                continue
            if s.screen in (SCREEN_LOGIN, SCREEN_LOBBY) and self.focus in self.fields:
                val = self.fields[self.focus]
                if e.key == pygame.K_BACKSPACE:
                    self.fields[self.focus] = val[:-1]
                elif e.unicode and (e.unicode.isalnum() or e.unicode == "_") and len(val) < P.MAX_NAME_LEN:
                    self.fields[self.focus] = val + e.unicode
            if e.key == pygame.K_RETURN:
                if s.screen == SCREEN_LOGIN:
                    self._do_login()
                elif s.screen == SCREEN_LOBBY:
                    self._do_create()
                elif s.screen == SCREEN_ROOM and s.is_host:
                    self._do_start()
                elif s.screen == SCREEN_RESULTS:
                    self._do_rematch()
            elif e.key == pygame.K_ESCAPE:
                if s.screen == SCREEN_ROOM:
                    s.leave_room()
                elif s.screen == SCREEN_GAME:
                    if time.monotonic() < self.esc_armed:
                        s.leave_room()
                    else:
                        self.esc_armed = time.monotonic() + 2.0
            elif s.screen == SCREEN_ROOM and e.key in (pygame.K_LEFT, pygame.K_RIGHT, pygame.K_UP, pygame.K_DOWN,
                                                       pygame.K_a, pygame.K_d, pygame.K_w, pygame.K_s):
                i = C.ORDER.index(s.my_char)
                step = {pygame.K_LEFT: -1, pygame.K_a: -1, pygame.K_RIGHT: 1, pygame.K_d: 1,
                        pygame.K_UP: -4, pygame.K_w: -4, pygame.K_DOWN: 4, pygame.K_s: 4}[e.key]
                self._pick(C.ORDER[(i + step) % len(C.ORDER)])
            elif s.screen == SCREEN_LOBBY and e.key == pygame.K_F5:
                s.list_rooms()
            elif s.screen == SCREEN_GAME and e.key in (pygame.K_w, pygame.K_z, pygame.K_UP, pygame.K_SPACE):
                self.sfx.play("jump", 0.7)
        if s.screen == SCREEN_GAME:
            self._send_game_input()
        return True

    def _send_game_input(self):
        k = pygame.key.get_pressed()
        mouse_left = pygame.mouse.get_pressed(3)[0]
        keys = P.pack_keys(
            left=k[pygame.K_LEFT] or k[pygame.K_a] or k[pygame.K_q],
            right=k[pygame.K_RIGHT] or k[pygame.K_d],
            jump=k[pygame.K_UP] or k[pygame.K_w] or k[pygame.K_z] or k[pygame.K_SPACE],
            down=k[pygame.K_DOWN] or k[pygame.K_s],
            light_attack=mouse_left or k[pygame.K_e] or k[pygame.K_j] or k[pygame.K_c],
            heavy_attack=k[pygame.K_x] or k[pygame.K_k],
            special=k[pygame.K_f] or k[pygame.K_l] or k[pygame.K_v],
            dodge=k[pygame.K_q] or k[pygame.K_a] or k[pygame.K_LSHIFT] or k[pygame.K_RSHIFT],
        )
        self.state.send_input(keys)

    def _do_login(self):
        name = self.fields["name"].strip()
        if name:
            self.sfx.play("click")
            self.state.login(name)

    def _do_create(self):
        room = self.fields["room"].strip()
        if room:
            self.sfx.play("click")
            self.state.create_room(room)
            self.fields["room"] = ""

    def _do_start(self):
        self.sfx.play("click")
        self.state.start_game()

    def _do_rematch(self):
        self.sfx.play("click")
        if self.state.room_name:
            self.state.screen = SCREEN_ROOM
        else:
            self.state.screen = SCREEN_LOBBY
            self.state.list_rooms()

    def _pick(self, cid):
        if self.state.my_char != cid:
            self.sfx.play("select")
            self.state.select_char(cid)

    def _pick_map(self, mid):
        if self.state.is_host and self.state.room_map != mid:
            self.sfx.play("select")
            self.state.select_map(mid)

    # ---- drawing helpers -------------------------------------------------
    def text(self, txt, font, color, pos, anchor="topleft", outline=0, ocol=OUTLINE):
        key = (txt, id(font), color, outline, ocol)
        surf = self._text_cache.get(key)
        if surf is None:
            surf = art.text_outlined(font, txt, color, ocol, outline) if outline else font.render(txt, True, color)
            if len(self._text_cache) > 800:
                self._text_cache.clear()
            self._text_cache[key] = surf
        r = surf.get_rect(**{anchor: (int(pos[0]), int(pos[1]))})
        self.screen.blit(surf, r)
        return r

    @staticmethod
    def wrap(txt, font, width):
        lines, cur = [], ""
        for word in txt.split():
            trial = (cur + " " + word).strip()
            if font.size(trial)[0] > width and cur:
                lines.append(cur)
                cur = word
            else:
                cur = trial
        return lines + ([cur] if cur else [])

    def panel(self, rect, color=PANEL, alpha=215, edge=PANEL_EDGE, radius=14, width=2):
        rect = pygame.Rect(rect)
        key = (rect.size, color, alpha, radius)
        surf = self._panel_cache.get(key)
        if surf is None:
            surf = pygame.Surface(rect.size, pygame.SRCALPHA)
            pygame.draw.rect(surf, (*color, alpha), surf.get_rect(), border_radius=radius)
            if len(self._panel_cache) > 300:
                self._panel_cache.clear()
            self._panel_cache[key] = surf
        self.screen.blit(surf, rect)
        if edge:
            pygame.draw.rect(self.screen, edge, rect, width, border_radius=radius)
        return rect

    def button(self, rect, label, cb, kind="primary", enabled=True, font=None):
        rect = pygame.Rect(rect)
        hover = enabled and rect.collidepoint(pygame.mouse.get_pos())
        base = {"primary": (232, 120, 40), "secondary": (70, 62, 118), "danger": (190, 50, 70),
                "good": (50, 160, 90)}[kind]
        if not enabled:
            base = (60, 56, 80)
        top = lighten(base, 0.25 if hover else 0.1)
        r = rect.move(0, -3 if hover else 0)
        pygame.draw.rect(self.screen, darken(base, 0.45), rect.move(0, 5), border_radius=12)
        pygame.draw.rect(self.screen, base, r, border_radius=12)
        pygame.draw.rect(self.screen, top, (r.x, r.y, r.w, r.h // 2), border_top_left_radius=12, border_top_right_radius=12)
        pygame.draw.rect(self.screen, OUTLINE, r, 3, border_radius=12)
        self.text(label, font or self.f_h3, TEXT if enabled else MUTED, r.center, "center", outline=2)
        if enabled:
            self.targets.append((rect, cb))
        return rect

    def textbox(self, rect, field, placeholder):
        rect = pygame.Rect(rect)
        focused = self.focus == field
        self.panel(rect, (14, 12, 28), 230, GOLD if focused else PANEL_EDGE, 10, 3 if focused else 2)
        val = self.fields[field]
        if val:
            r = self.text(val, self.f_h3, TEXT, (rect.x + 16, rect.centery), "midleft")
            caret_x = r.right + 3
        else:
            self.text(placeholder, self.f_body, MUTED, (rect.x + 16, rect.centery), "midleft")
            caret_x = rect.x + 16
        if focused and int(self.t * 2) % 2 == 0:
            pygame.draw.line(self.screen, GOLD, (caret_x, rect.y + 12), (caret_x, rect.bottom - 12), 2)
        self.targets.append((rect, lambda: setattr(self, "focus", field)))

    def overlay(self, key, builder):
        surf = self._panel_cache.get(key)
        if surf is None:
            surf = self._panel_cache[key] = builder()
        self.screen.blit(surf, (0, 0))

    def vignette(self, alpha=120):
        def build():
            surf = pygame.Surface((W, H), pygame.SRCALPHA)
            for i in range(60):
                a = int(alpha * (1 - i / 60) ** 2)
                pygame.draw.rect(surf, (6, 4, 14, a), (i * 5, i * 3, W - i * 10, H - i * 6), 6, border_radius=40)
            return surf
        self.overlay(("vig", alpha), build)

    def dim(self, alpha=110):
        def build():
            surf = pygame.Surface((W, H), pygame.SRCALPHA)
            surf.fill((8, 6, 20, alpha))
            return surf
        self.overlay(("dim", alpha), build)

    def stat_bar(self, x, y, label, value, color):
        self.text(label, self.f_small, MUTED, (x, y), "midleft")
        bx = x + 92
        for i in range(10):
            on = i < value
            r = pygame.Rect(bx + i * 19, y - 7, 15, 14)
            pygame.draw.rect(self.screen, color if on else (44, 40, 70), r, border_radius=3)
            if on:
                pygame.draw.rect(self.screen, lighten(color, 0.4), (r.x, r.y, r.w, 4), border_radius=3)
            pygame.draw.rect(self.screen, OUTLINE, r, 2, border_radius=3)

    def puff_sprite(self, r, col):
        key = (int(r), col)
        spr = self._puff_cache.get(key)
        if spr is None:
            rr = max(2, int(r))
            spr = pygame.Surface((rr * 2, rr * 2), pygame.SRCALPHA)
            for i in range(rr, 0, -max(1, rr // 8)):
                a = int(210 * (1 - i / rr) ** 0.7)
                pygame.draw.circle(spr, (*col, a), (rr, rr), i)
            if len(self._puff_cache) > 400:
                self._puff_cache.clear()
            self._puff_cache[key] = spr
        return spr

    @staticmethod
    def _demo_action(t, keys):
        """Loop a showcase of attacks for menus: (action, action_t, move key)."""
        seq = []
        for key in keys:
            m = G.MOVES[key]
            seq.append((G.A_IDLE, 0.7, None))
            if m["cat"] == "heavy":
                seq.append((G.A_WINDUP, m["startup"] / P.TICK_RATE, key))
                seq.append((G.A_HEAVY, (m["active"] + 4) / P.TICK_RATE, key))
            else:
                seq.append((G.A_LIGHT, (m["startup"] + m["active"] + 4) / P.TICK_RATE, key))
        ph = t % sum(d for _, d, _ in seq)
        for action, d, key in seq:
            if ph < d:
                return action, ph * P.TICK_RATE, key
            ph -= d
        return G.A_IDLE, 0, None

    def menu_fighter(self, slot, cid, x, y, s, f, keys, t_off=0.0, dt=1 / 60):
        """A posed, smoothly blended showcase fighter for menus."""
        action, at, mv = self._demo_action(self.t + t_off, keys)
        air = mv in ("spike", "cyclone")
        target = rig.pose_for(cid, action, at, self.t + t_off, False, air, -40 if air else 0, mv, 0)
        key = (slot, cid)
        k = 1 - math.exp(-dt * (34 if action in ATTACK_ACTIONS else 12))
        self.menu_pose[key] = rig.blend(self.menu_pose.get(key), target, k)
        rig.draw(self.screen, cid, x, y, s, f, self.menu_pose[key], self.t + t_off, trail_col=(255, 245, 215),
                 glow_weapon=action == G.A_WINDUP)
        return mv

    # ---- screens -------------------------------------------------------------
    def _draw(self, dt):
        s = self.state
        if s.screen == SCREEN_GAME:
            self._draw_game(dt)
        else:
            mid = s.map_id if s.screen == SCREEN_RESULTS else (s.room_map if s.screen == SCREEN_ROOM else M.DEFAULT)
            stage.backdrop(mid, W, H).draw(self.screen, None, self.t, dt)
            if s.screen == SCREEN_LOGIN:
                self._draw_title(dt)
            elif s.screen == SCREEN_LOBBY:
                self._draw_lobby()
            elif s.screen == SCREEN_ROOM:
                self._draw_select(dt)
            elif s.screen == SCREEN_RESULTS:
                self._draw_results(dt)
        self._draw_net_stats()
        if s.error and time.monotonic() - s.error_at < 3.5:
            r = self.text(s.error.upper(), self.f_body, TEXT, (W / 2, 26), "center")
            self.panel(r.inflate(36, 16), (120, 24, 40), 230, BAD, 10)
            self.text(s.error.upper(), self.f_body, TEXT, (W / 2, 26), "center")
        if not s.net.connected:
            self.dim(170)
            box = self.panel((W / 2 - 260, H / 2 - 80, 520, 160), edge=BAD)
            self.text("CONNECTION LOST", self.f_h1, BAD, (box.centerx, box.y + 52), "center", outline=3)
            self.text("The server stopped responding. Close the window and reconnect.", self.f_small, MUTED,
                      (box.centerx, box.y + 112), "center")

    def _draw_net_stats(self):
        results = self.state._probe_results
        loss = (100 * sum(not ok for ok in results) / len(results)) if results else 0
        ping = "--" if self.state.ping_ms is None else "%dms" % self.state.ping_ms
        text = "FPS %d   PL %.0f%%   PING %s" % (round(self.clock.get_fps()), loss, ping)
        label = self.text(text, self.f_tiny, TEXT, (18, 16), "topleft", outline=2)
        self.panel(label.inflate(12, 8), (12, 10, 26), 190, (70, 62, 100), 6, 1)
        self.text(text, self.f_tiny, TEXT, (18, 16), "topleft", outline=2)

    def _logo(self, cx, cy):
        bob = math.sin(self.t * 2) * 4
        self.text("BRAWL", self.f_logo, GOLD, (cx - 6, cy - 46 + bob), "center", outline=6)
        self.text("ARENA", self.f_logo, (255, 120, 60), (cx + 6, cy + 46 + bob), "center", outline=6)

    def _draw_title(self, dt):
        self.vignette(170)
        for i, (cid, x, face) in enumerate((("ragnar", 230, 1), ("kira", W - 230, -1))):
            pygame.draw.ellipse(self.screen, (10, 8, 20), (x - 90, 540, 180, 26))
            self.menu_fighter(i, cid, x, 552, 3.0, face, ("jab", "smash", "lunge", "launcher"), i * 1.3, dt)
        self._logo(W / 2, 170)
        self.text("O N L I N E   P L A T F O R M   F I G H T E R", self.f_small, (230, 210, 255), (W / 2, 280), "center",
                  outline=2)
        box = self.panel((W / 2 - 230, 330, 460, 190))
        self.text("ENTER YOUR FIGHTER NAME", self.f_small, MUTED, (box.centerx, box.y + 26), "center")
        self.textbox((box.x + 30, box.y + 48, box.w - 60, 54), "name", "letters, digits, _")
        self.button((box.x + 30, box.y + 118, box.w - 60, 52), "ENTER THE ARENA", self._do_login)
        size, gap = 92, 12
        total = len(C.ORDER) * (size + gap)
        off = (self.t * 40) % total
        for rep in range(3):
            for i, cid in enumerate(C.ORDER):
                x = i * (size + gap) - off + rep * total - total / 2
                if -size < x < W:
                    self.screen.blit(art.portrait(cid, size, size), (x, H - size - 24))
                    pygame.draw.rect(self.screen, OUTLINE, (x, H - size - 24, size, size), 3, border_radius=4)
        if self.server_label:
            self.text("server " + self.server_label, self.f_tiny, MUTED, (16, H - 12), "midleft")

    def _draw_header(self, title, subtitle=None):
        self.text(title, self.f_h1, TEXT, (48, 52), "midleft", outline=4)
        if subtitle:
            self.text(subtitle, self.f_small, TEXT, (52, 92), "midleft", outline=2)
        chip = pygame.Rect(W - 300, 26, 260, 52)
        self.panel(chip, radius=26)
        self.text(self.state.name, self.f_h3, TEXT, (chip.x + 24, chip.centery), "midleft")
        self.text("ONLINE", self.f_tiny, GOOD, (chip.right - 24, chip.centery), "midright")
        pygame.draw.circle(self.screen, GOOD, (chip.right - 82, chip.centery), 5)

    def _draw_lobby(self):
        s = self.state
        self.vignette(160)
        self.dim(70)
        self._draw_header("ARENA LOBBY", "Pick an open arena or create your own")
        lst = self.panel((40, 120, 760, 560))
        self.text("OPEN ARENAS", self.f_h3, GOLD, (lst.x + 24, lst.y + 30), "midleft")
        self.button((lst.right - 150, lst.y + 12, 130, 38), "REFRESH", s.list_rooms, "secondary", font=self.f_small)
        if not s.rooms:
            self.text("No arenas yet. Create one and invite your friends!", self.f_body, MUTED,
                      (lst.centerx, lst.centery), "center")
        for i, r in enumerate(s.rooms[:6]):
            card = pygame.Rect(lst.x + 20, lst.y + 70 + i * 80, lst.w - 40, 68)
            hover = card.collidepoint(pygame.mouse.get_pos())
            self.panel(card, (40, 34, 72) if hover else (32, 28, 58), 240, PANEL_EDGE, 10)
            self.text(r["room"], self.f_h2, TEXT, (card.x + 22, card.centery), "midleft")
            for j in range(r["max"]):
                c = (card.x + 300 + j * 26, card.centery)
                pygame.draw.circle(self.screen, art.player_color(j) if j < r["players"] else (60, 56, 90), c, 9)
                pygame.draw.circle(self.screen, OUTLINE, c, 9, 2)
            full = r["players"] >= r["max"]
            label, col = (("IN BATTLE", BAD) if r["started"] else ("FULL", MUTED) if full else ("WAITING", GOOD))
            self.text(label, self.f_small, col, (card.x + 420, card.centery), "midleft")
            self.button((card.right - 130, card.y + 12, 112, 44), "JOIN",
                        lambda n=r["room"]: (self.sfx.play("click"), s.join_room(n)),
                        "good", enabled=not (r["started"] or full))
        cr = self.panel((830, 120, 410, 220))
        self.text("CREATE ARENA", self.f_h3, GOLD, (cr.x + 24, cr.y + 30), "midleft")
        self.textbox((cr.x + 24, cr.y + 60, cr.w - 48, 54), "room", "arena name")
        self.button((cr.x + 24, cr.y + 136, cr.w - 48, 54), "CREATE", self._do_create)
        ctl = self.panel((830, 360, 410, 320))
        self.text("CONTROLS", self.f_h3, GOLD, (ctl.x + 24, ctl.y + 30), "midleft")
        for i, (what, keys) in enumerate(CONTROLS):
            y = ctl.y + 70 + i * 34
            self.text(what, self.f_small, TEXT, (ctl.x + 24, y), "midleft")
            self.text(keys, self.f_small, ACCENT, (ctl.right - 24, y), "midright")

    def _draw_select(self, dt):
        s = self.state
        self.vignette(160)
        self.dim(80)
        self._draw_header("CHOOSE YOUR LEGEND", "Room: %s   |   click a fighter or use the arrow keys" % s.room_name)
        mouse = pygame.mouse.get_pos()
        size, gap = 132, 14
        gx, gy = 48, 128
        self.hover_char = None
        picks = {}
        for p in s.room_players:
            picks.setdefault(p["char"], []).append(p)
        for i, cid in enumerate(C.ORDER):
            rect = pygame.Rect(gx + (i % 4) * (size + gap), gy + (i // 4) * (size + gap + 26), size, size)
            hover = rect.collidepoint(mouse)
            if hover:
                self.hover_char = cid
            r = rect.move(0, -4 if hover else 0)
            pygame.draw.rect(self.screen, (8, 6, 16), rect.move(4, 6), border_radius=8)
            self.screen.blit(art.portrait(cid, size, size), r)
            mine = cid == s.my_char
            edge = art.player_color(s.slot_of(s.pid)) if mine else (GOLD if hover else OUTLINE)
            pygame.draw.rect(self.screen, edge, r, 5 if (mine or hover) else 3, border_radius=8)
            plate = pygame.Rect(r.x, r.bottom - 4, r.w, 28)
            pygame.draw.rect(self.screen, (16, 12, 30), plate, border_bottom_left_radius=8, border_bottom_right_radius=8)
            self.text(C.CHARACTERS[cid]["name"].upper(), self.f_h3, TEXT, plate.center, "center")
            for j, p in enumerate(picks.get(cid, [])):
                tag = pygame.Rect(r.x + 6 + j * 40, r.y + 6, 36, 22)
                pygame.draw.rect(self.screen, art.player_color(s.slot_of(p["pid"])), tag, border_radius=6)
                pygame.draw.rect(self.screen, OUTLINE, tag, 2, border_radius=6)
                self.text("P%d" % (s.slot_of(p["pid"]) + 1), self.f_small, OUTLINE, tag.center, "center")
            self.targets.append((rect, lambda c=cid: self._pick(c)))

        cid = self.hover_char or s.my_char
        ch = C.CHARACTERS[cid]
        pv = self.panel((660, 110, 580, 372))
        art.glow(self.screen, art.look(cid)["secondary"], (pv.x + 135, pv.y + 250), 160, 90)
        ped = pygame.Rect(pv.x + 40, pv.y + 300, 190, 30)
        pygame.draw.ellipse(self.screen, (10, 8, 20), ped.move(0, 6))
        pygame.draw.ellipse(self.screen, art.look(cid)["primary"], ped)
        pygame.draw.ellipse(self.screen, OUTLINE, ped, 3)
        mv = self.menu_fighter("preview", cid, ped.centerx, ped.centery, 2.6, 1, list(G.MOVES), 0.0, dt)
        if mv:
            self.text(MOVE_LABEL[mv], self.f_h3, GOLD, (ped.centerx, ped.bottom + 18), "center", outline=2)
        tx = pv.x + 272
        self.text(ch["name"].upper(), self.f_h1, TEXT, (tx, pv.y + 42), "midleft", outline=3)
        self.text(ch["title"], self.f_body, art.look(cid)["secondary"], (tx, pv.y + 82), "midleft")
        stats = [("POWER", ch["power"], 0.8, 1.35), ("SPEED", ch["speed"], 0.75, 1.3),
                 ("DEFENSE", ch["weight"], 0.8, 1.5), ("MOBILITY", ch["jump"], 0.82, 1.12),
                 ("RANGE", ch["reach"], 0.8, 1.3)]
        for i, (lbl, v, lo, hi) in enumerate(stats):
            val = max(1, min(10, round(1 + 9 * (v - lo) / (hi - lo))))
            self.stat_bar(tx, pv.y + 118 + i * 26, lbl, val, art.player_color(i + 1) if i else BAD)
        sp = ch["special"]
        moves = [("LIGHT", "Jab · Lunge · Sweep · Spike", "J"), ("HEAVY", "Launch · Smash · Quake · Cyclone", "K"),
                 ("SIGNATURE", "%s  %.1fs" % (sp["name"], sp["cd"] / P.TICK_RATE), "L")]
        for i, (kind, name, key) in enumerate(moves):
            y = pv.y + 258 + i * 26
            r = self.text(kind, self.f_small, GOLD if kind == "SIGNATURE" else MUTED, (tx, y), "midleft")
            self.text("[%s]" % key, self.f_tiny, ACCENT, (r.right + 6, y), "midleft")
            self.text(name, self.f_tiny if kind != "SIGNATURE" else self.f_small, TEXT, (tx + 114, y), "midleft")
        for i, line in enumerate(self.wrap(sp["desc"], self.f_tiny, pv.right - tx - 20)):
            self.text(line, self.f_tiny, (230, 220, 255), (tx, pv.y + 338 + i * 16), "midleft")

        # arena picker
        self.text("ARENA", self.f_h3, GOLD, (662, 506), "midleft", outline=2)
        if not s.is_host:
            self.text("(host picks)", self.f_tiny, MUTED, (730, 506), "midleft")
        for i, mid in enumerate(M.ORDER):
            card = pygame.Rect(660 + i * 197, 520, 186, 70)
            chosen = s.room_map == mid
            hover = s.is_host and card.collidepoint(mouse)
            self.screen.blit(stage.thumbnail(mid, card.w, card.h), card)
            if not chosen:
                self.panel(card, (8, 6, 20), 110, None, 0)
            plate = pygame.Rect(card.x, card.bottom - 22, card.w, 22)
            self.panel(plate, (10, 8, 22), 200, None, 0)
            self.text(M.MAPS[mid]["name"].upper(), self.f_small, GOLD if chosen else TEXT, plate.center, "center")
            pygame.draw.rect(self.screen, GOLD if chosen else (PANEL_EDGE if not hover else TEXT), card,
                             4 if chosen else 2, border_radius=6)
            if s.is_host:
                self.targets.append((card, lambda m=mid: self._pick_map(m)))

        for i in range(P.MAX_PLAYERS_PER_ROOM):
            slot = pygame.Rect(48 + i * 200, 476, 186, 120)
            col = art.player_color(i)
            if i < len(s.room_players):
                p = s.room_players[i]
                self.panel(slot, (30, 26, 56), 235, col, 12, 3)
                self.screen.blit(art.portrait(p["char"], 64, 64), (slot.x + 12, slot.y + 14))
                pygame.draw.rect(self.screen, OUTLINE, (slot.x + 12, slot.y + 14, 64, 64), 2)
                self.text("P%d" % (i + 1), self.f_h3, col, (slot.x + 88, slot.y + 28), "midleft", outline=2)
                if p["host"]:
                    self.text("HOST", self.f_tiny, GOLD, (slot.right - 12, slot.y + 28), "midright")
                self.text(p["name"], self.f_body, TEXT, (slot.x + 88, slot.y + 56), "midleft")
                self.text(C.CHARACTERS[p["char"]]["name"], self.f_small, art.look(p["char"])["secondary"],
                          (slot.x + 12, slot.y + 98), "midleft")
                if p["pid"] == s.pid:
                    self.text("YOU", self.f_tiny, GOOD, (slot.right - 12, slot.y + 98), "midright")
            else:
                self.panel(slot, (20, 18, 36), 160, (60, 56, 90), 12)
                self.text("waiting" + "." * (1 + int(self.t * 2) % 3), self.f_body, MUTED, slot.center, "center")
        self.button((48, 620, 200, 60), "LEAVE", s.leave_room, "secondary")
        need = P.MIN_PLAYERS_TO_START - len(s.room_players)
        if s.is_host:
            label = "START BATTLE" if need <= 0 else "NEED %d MORE" % need
            self.button((660, 606, 580, 76), label, self._do_start, enabled=need <= 0, font=self.f_h2)
        else:
            box = self.panel((660, 606, 580, 76))
            self.text("WAITING FOR HOST TO START" + "." * (1 + int(self.t * 2) % 3), self.f_h3, MUTED, box.center, "center")

    # ---- battle: events -> effects -------------------------------------------
    def _consume_fx(self):
        s = self.state
        while s.fx:
            ev = s.fx.popleft()
            kind = ev["ev"]
            if kind == "HIT":
                self._on_hit(ev)
            elif kind == "KO":
                col = art.player_color(s.slot_of(ev["victim"]))
                for _ in range(60):
                    a = random.uniform(0, math.tau)
                    sp = random.uniform(150, 900)
                    self.particles.append(Particle(ev["x"], ev["y"], math.cos(a) * sp, math.sin(a) * sp,
                                                   random.uniform(0.5, 1.1), random.choice([col, (255, 255, 255), GOLD]),
                                                   random.uniform(3, 7), 300, 1.5, "streak"))
                self.rings.append([ev["x"], ev["y"], 10, 260, 0.6, 0.6, col, 10])
                self.beams.append([ev["x"], ev["y"], 0.9, col])
                self.white_flash = 0.18
                self.banners.append(["K.O.!", self.t, 1.1, col, self.f_logo, ""])
                self.comics.append([ev["x"], ev["y"], "KABOOM!", self.t, 1.0, 1.7, random.uniform(-12, 12), col])
                self.sfx.play("ko")
            elif kind == "SPECIAL":
                k = ev["kind"]
                col = art.look(s.char_of(ev["pid"]))["secondary"]
                if k == "projectile":
                    self.sfx.play("fire" if s.char_of(ev["pid"]) == "blaze" else "shot")
                elif k == "pull":
                    self.rings.append([ev["x"], ev["y"], 240, 10, 0.45, 0.45, col, 6])
                    self.sfx.play("special")
                elif k == "armor":
                    self.rings.append([ev["x"], ev["y"], 10, 90, 0.4, 0.4, col, 8])
                    self.sfx.play("special")
                else:
                    self.sfx.play("special")
                    self._dust(ev["x"], ev["y"] + 28, 10, (220, 210, 200))
            elif kind == "SHOCK":
                col = art.look(s.char_of(ev["pid"]))["secondary"]
                self.rings.append([ev["x"], ev["y"], 10, 170, 0.45, 0.45, col, 9])
                for _ in range(28):
                    side = random.choice((-1, 1))
                    self.particles.append(Particle(ev["x"] + side * random.uniform(0, 40), ev["y"],
                                                   side * random.uniform(200, 520), random.uniform(-380, -80),
                                                   random.uniform(0.4, 0.8), random.choice([(150, 120, 100), (210, 190, 160), col]),
                                                   random.uniform(3, 6), 1300, 0.5))
                self._dust(ev["x"], ev["y"], 16, (210, 196, 176), spread=160)
                self.sfx.play("shock")
            elif kind == "POP":
                col = (255, 140, 40) if C.PROJ_KINDS[ev["kind"]] == "fireball" else (255, 230, 140)
                self.rings.append([ev["x"], ev["y"], 8, 60, 0.25, 0.25, col, 6])
                for _ in range(14):
                    a = random.uniform(0, math.tau)
                    self.particles.append(Particle(ev["x"], ev["y"], math.cos(a) * 300, math.sin(a) * 300,
                                                   0.35, col, 4, 200, 2, "streak"))
            elif kind == "RESPAWN":
                self.sfx.play("respawn", 0.6)
            elif kind == "GAME_OVER":
                self.banners.append(["GAME!", self.t, 2.3, GOLD, self.f_logo, ""])
                self.white_flash = 0.25
                self.sfx.play("ko")

    def _on_hit(self, ev):
        s = self.state
        heavy = ev.get("move") == "heavy" or ev.get("kb", 0) > 520
        mvk = ev.get("mv")
        att = s.view.get(ev["attacker"])
        d = 1 if att is None or att.x <= ev["x"] else -1
        col = art.player_color(s.slot_of(ev["attacker"]))
        x, y = ev["x"], ev["y"]
        freeze = 0.085 if heavy else 0.05
        for pid in (ev["attacker"], ev["victim"]):
            v = self.vis.setdefault(pid, Vis())
            v.freeze_until = self.t + freeze
        vv = self.vis[ev["victim"]]
        vv.flash_until = self.t + 0.06
        vv.hurt_until = self.t + 0.22
        vv.jitter_dir = d
        angle = {"spike": math.pi / 2, "launcher": -math.pi / 2}.get(mvk, 0.0 if d > 0 else math.pi)
        self.slashes.append([x, y, angle + random.uniform(-0.25, 0.25), self.t, col, heavy])
        self.lines.append([x, y, self.t, random.random() * 10, heavy])
        n = 16 if heavy else 9
        for _ in range(n):
            a = angle + random.uniform(-0.8, 0.8)
            sp = random.uniform(300, 760 if heavy else 520)
            self.particles.append(Particle(x, y, math.cos(a) * sp, math.sin(a) * sp - 60,
                                           random.uniform(0.18, 0.4), random.choice([col, (255, 250, 220), GOLD]),
                                           random.uniform(2.5, 4.5), 500, 3.0, "streak"))
        self.sparks.append([x, y, self.t, 1.6 if heavy else 1.0, random.uniform(0, math.pi)])
        self.rings.append([x, y, 6, 74 if heavy else 46, 0.22, 0.22, (255, 245, 210), 6])
        self.floats.append([x + random.uniform(-14, 14), y - 46, "%d%%" % ev["damage"], self.t, damage_color(ev["damage"])])
        if heavy or mvk == "spike":
            word = "SPIKE!" if mvk == "spike" else random.choice(COMIC_WORDS)
            self.comics.append([x + d * 46, y - 54, word, self.t, 0.75,
                                1.0 + min(0.6, ev.get("kb", 0) / 1200), random.uniform(-14, 14), col])
        self.hud_shake[ev["victim"]] = self.t + 0.35
        self.sfx.play("heavy" if heavy else "hit")

    def _dust(self, x, y, n, col, spread=40, up=1.0):
        for _ in range(n):
            side = random.choice((-1, 1))
            self.particles.append(Particle(x + side * random.uniform(0, spread * 0.3), y - random.uniform(0, 4),
                                           side * random.uniform(40, 160), -random.uniform(20, 90) * up,
                                           random.uniform(0.35, 0.6), col, random.uniform(6, 11), -40, 3.0, "puff"))

    # ---- battle: per-frame presentation state ---------------------------------
    def anim_time(self, pid, rp):
        v = self.vis.get(pid)
        if v is None or v.anim is None:
            return rp.action_t
        if self.t < v.freeze_until:
            return v.freeze_at
        _, _, t0, at0 = v.anim
        at = min(at0 + (self.t - t0) * P.TICK_RATE, rp.action_t + 1.5)
        v.freeze_at = at
        return at

    def _update_effects(self, dt):
        self.particles = [p for p in self.particles if p.update(dt)]
        for r in self.rings:
            r[4] -= dt
        self.rings = [r for r in self.rings if r[4] > 0]
        self.floats = [f for f in self.floats if self.t - f[3] < 0.9]
        for b in self.beams:
            b[2] -= dt
        self.beams = [b for b in self.beams if b[2] > 0]
        self.banners = [b for b in self.banners if self.t - b[1] < b[2]]
        self.comics = [c for c in self.comics if self.t - c[3] < c[4]]
        self.sparks = [sp for sp in self.sparks if self.t - sp[2] < 0.18]
        self.slashes = [sl for sl in self.slashes if self.t - sl[3] < 0.2]
        self.lines = [ln for ln in self.lines if self.t - ln[2] < 0.16]
        self.white_flash = max(0.0, self.white_flash - dt)
        if self.state.screen == SCREEN_RESULTS:
            self.confetti_t += dt
            while self.confetti_t > 0.03:
                self.confetti_t -= 0.03
                self.particles.append(Particle(random.uniform(0, W), -10, random.uniform(-40, 40), random.uniform(60, 160),
                                               4.0, random.choice(art.PLAYER_COLORS + [GOLD]), random.uniform(3, 5), 60, 0.3))
        if self.state.screen == SCREEN_GAME:
            self._update_fighters(dt)
            cd = self.state.countdown
            if cd > 0:
                if math.ceil(cd / P.TICK_RATE) != math.ceil(self.last_cd / P.TICK_RATE):
                    self.sfx.play("beep")
            elif self.last_cd > 0:
                self.banners.append(["FIGHT!", self.t, 0.9, (255, 120, 60), self.f_logo, ""])
                self.sfx.play("go")
            self.last_cd = cd

    def _update_fighters(self, dt):
        s = self.state
        now = self.t
        for pid, rp in s.view.items():
            v = self.vis.setdefault(pid, Vis())
            cid = s.char_of(pid)
            alive = bool(rp.state & G.S_ALIVE)
            airborne = not rp.state & G.S_GROUND
            if alive and not v.alive:                      # respawned
                v.pose = None
                v.air = airborne
                for _ in range(16):
                    a = random.uniform(0, math.tau)
                    self.particles.append(Particle(rp.x, rp.y - 30, math.cos(a) * 160, math.sin(a) * 160, 0.6,
                                                   art.player_color(s.slot_of(pid)), 3, -60, 2.0))
            v.alive = alive
            if not alive:
                continue
            rec = v.anim
            if rec is None or rec[:2] != (rp.action, rp.mv) or rp.action_t + 1 < rec[3]:
                v.anim = (rp.action, rp.mv, now, rp.action_t)
            prev = self.prev_action.get(pid)
            if prev != rp.action:
                vol = 1.0 if pid == s.pid else 0.5
                if rp.action == G.A_LIGHT:
                    self.sfx.play("swing", vol)
                elif rp.action == G.A_HEAVY:
                    self.sfx.play("heavy_swing", vol)
                elif rp.action == G.A_DODGE:
                    self.sfx.play("dodge", vol)
            self.prev_action[pid] = rp.action

            # movement feedback: jumps, landings, double jumps, run dust, skids
            if not v.air and airborne and rp.vy < -150:
                v.jump_t = now
                self._dust(rp.x, rp.y, 6, (226, 216, 200), up=0.4)
            elif v.air and airborne and v.vy > -80 and rp.vy < -380:
                v.jump_t = now
                self.rings.append([rp.x, rp.y + 4, 6, 34, 0.25, 0.25, (235, 240, 255), 4])
            elif v.air and not airborne:
                v.land_t = now
                self._dust(rp.x, rp.y, 9, (226, 216, 200), spread=50)
            running = not airborne and abs(rp.vx) > 40
            if running:
                v.phase += abs(rp.vx) * dt * 0.048
                if abs(rp.vx) > 200 and now - v.dust_t > 0.12:
                    v.dust_t = now
                    self.particles.append(Particle(rp.x - rp.facing * 10, rp.y - 2, -rp.facing * 40, -30, 0.4,
                                                   (220, 210, 196), 6, -20, 3.0, "puff"))
            if not airborne and rp.facing != v.facing and abs(rp.vx) > 120:
                self._dust(rp.x, rp.y, 5, (220, 210, 196), spread=20, up=0.3)
            v.facing, v.air, v.vy = rp.facing, airborne, rp.vy

            # launched fighters tumble and trail smoke
            speed = math.hypot(rp.vx, rp.vy)
            tumble = rp.action == G.A_STUN and speed > 520
            if tumble:
                v.tumble += dt * 13 * (-1 if rp.vx * rp.facing < 0 else 1)
                if now - v.smoke_t > 0.035:
                    v.smoke_t = now
                    self.particles.append(Particle(rp.x + random.uniform(-6, 6), rp.y - 30 + random.uniform(-6, 6),
                                                   -rp.vx * 0.05, -rp.vy * 0.05, 0.55, (236, 236, 240),
                                                   random.uniform(7, 11), -30, 1.0, "puff"))
            else:
                v.tumble = wrap_pi(v.tumble) * math.exp(-dt * 12)

            at = self.anim_time(pid, rp)
            mv = G.MOVE_IDS[rp.mv] if 0 <= rp.mv < len(G.MOVE_IDS) else None
            target = rig.pose_for(cid, rp.action, at, now + pid, running, airborne, rp.vy, mv, v.phase, tumble)
            if now < v.freeze_until and v.pose is not None:
                continue                                   # hit-freeze: hold the pose
            rate = 36 if rp.action in ATTACK_ACTIONS else (20 if rp.action == G.A_STUN else 14)
            v.pose = rig.blend(v.pose, target, 1 - math.exp(-dt * rate))

            fast = (rp.action == G.A_DODGE
                    or (rp.action == G.A_SPECIAL and C.get(cid)["special"]["kind"] in ("dash", "pounce", "rise", "slam"))
                    or (rp.action in (G.A_LIGHT, G.A_HEAVY) and mv in ("lunge", "smash") and abs(rp.vx) > 250))
            g = self.ghosts.setdefault(pid, deque(maxlen=5))
            if fast:
                g.append((now, rp.x, rp.y, rp.facing, dict(v.pose), v.tumble))
            while g and now - g[0][0] > 0.15:
                g.popleft()

    # ---- battle: drawing -----------------------------------------------------
    def _draw_game(self, dt):
        s = self.state
        mp = M.get(s.map_id)
        alive = [(rp.x, rp.y) for rp in s.view.values() if rp.state & G.S_ALIVE
                 and mp["blast"][0] + 100 < rp.x < mp["blast"][1] - 100 and rp.y < mp["blast"][3] - 120]
        self.cam.update(alive, dt)
        ts = self.cam.to_screen
        z = self.cam.zoom
        self.backdrop.draw(self.screen, self.cam, self.t, dt)

        for x, y, life, col in self.beams:
            a = ts(x, y)
            c = ts(self.cam.cx0, self.cam.cy0 + 100)
            k = life / 0.9
            w = 60 * k * z
            dx, dy = c[0] - a[0], c[1] - a[1]
            ln = math.hypot(dx, dy) or 1
            nx, ny = -dy / ln * w, dx / ln * w
            far = (a[0] + dx * 3, a[1] + dy * 3)
            pygame.draw.polygon(self.screen, lerp_col(col, (255, 255, 255), 0.5),
                                [(a[0] + nx * 0.2, a[1] + ny * 0.2), (a[0] - nx * 0.2, a[1] - ny * 0.2),
                                 (far[0] - nx, far[1] - ny), (far[0] + nx, far[1] + ny)])

        self.stage.draw(self.screen, self.cam, self.t)
        self.stage.draw_fx(self.screen, self.cam, self.t)

        ghosts_any = any(self.ghosts.values())
        if ghosts_any:
            layer = pygame.Surface((W, H), pygame.SRCALPHA)
            for pid, g in self.ghosts.items():
                col = art.player_color(s.slot_of(pid))
                for tt, x, y, f, pose, rot in g:
                    sx, sy = ts(x, y)
                    rig.draw(layer, s.char_of(pid), sx, sy, FS, f, pose, self.t, mode=col, rot=rot)
            layer.set_alpha(85)
            self.screen.blit(layer, (0, 0))

        for (_id, x, y, kind, d) in s.projectiles:
            art.draw_projectile(self.screen, kind, *ts(x, y), z, d, self.t)

        for rp in sorted(s.view.values(), key=lambda r: r.pid == s.pid):
            if rp.state & G.S_ALIVE:
                self._draw_fighter(rp, mp)

        self._draw_particles()
        for x, y, r0, r1, life, maxlife, col, w in self.rings:
            k = 1 - life / maxlife
            rad = lerp(r0, r1, art.ease_out(k)) * z
            pygame.draw.circle(self.screen, col, ts(x, y), max(2, rad), max(1, int(w * (1 - k) * z) + 1))
        self._draw_impacts()
        self.backdrop.draw_front(self.screen, self.t, dt)
        self._draw_hud()
        self._draw_feed()
        self._draw_overlays()

    def _ground_under(self, mp, x, y):
        best = None
        for xl, xr, py, _solid in mp["platforms"]:
            if xl <= x <= xr and py >= y - 1 and (best is None or py < best):
                best = py
        return best

    def _draw_fighter(self, rp, mp):
        s = self.state
        ts = self.cam.to_screen
        z = self.cam.zoom
        v = self.vis.get(rp.pid)
        if v is None or v.pose is None:
            return
        cid = s.char_of(rp.pid)
        slot = s.slot_of(rp.pid)
        col = art.player_color(slot)
        sx, sy = ts(rp.x, rp.y)
        gy = self._ground_under(mp, rp.x, rp.y)
        if gy is not None:
            k = max(0.0, 1 - (gy - rp.y) / 260)
            if k > 0:
                gx, gyy = ts(rp.x, gy)
                w = 46 * z * (0.45 + 0.55 * k)
                shadow = pygame.Surface((int(w), int(w * 0.24) + 2), pygame.SRCALPHA)
                pygame.draw.ellipse(shadow, (8, 6, 18, int(150 * k)), shadow.get_rect())
                self.screen.blit(shadow, (gx - w / 2, gyy - w * 0.12))
        now = self.t
        if now < v.flash_until or now < v.freeze_until:
            mode = "flash"
        elif now < v.hurt_until:
            mode = "hurt"
        elif rp.state & G.S_INVULN and rp.action not in (G.A_DODGE, G.A_SPECIAL) and int(now * 14) % 2:
            mode = "flash"
        else:
            mode = None
        if now < v.freeze_until and now >= v.flash_until:
            sx += v.jitter_dir * (2 if int(now * 60) % 2 else -2)
        sq = 1.0
        if now - v.land_t < 0.16:
            sq = 1 - 0.16 * math.sin(math.pi * (now - v.land_t) / 0.16)
        elif now - v.jump_t < 0.14:
            sq = 1 + 0.12 * math.sin(math.pi * (now - v.jump_t) / 0.14)
        speed = math.hypot(rp.vx, rp.vy)
        if speed > 520 and rp.action != G.A_STUN:
            d = 1 if rp.vx > 0 else -1
            for i in range(5):
                y = sy - (14 + i * 12) * z
                x0 = sx - d * (34 + (i % 2) * 14) * z
                pygame.draw.line(self.screen, (255, 255, 255), (x0, y), (x0 - d * (40 + i * 9) * z, y), max(1, int(2 * z)))
        mv = G.MOVE_IDS[rp.mv] if 0 <= rp.mv < len(G.MOVE_IDS) else None
        rig.draw(self.screen, cid, sx, sy, FS, rp.facing, v.pose, now + rp.pid, mode=mode, rot=v.tumble, sq=sq,
                 vx=rp.vx, trail_col=lighten(col, 0.55), armor=bool(rp.state & G.S_ARMOR),
                 glow_weapon=rp.action == G.A_WINDUP)
        if rp.action == G.A_WINDUP:
            art.glow(self.screen, art.look(cid)["secondary"], (sx, sy - 44 * z), 64 * z, 90 + 60 * math.sin(now * 30))
        tag_y = sy - 102 * FS / rig.VIS
        label = "P%d" % (slot + 1) if rp.pid != s.pid else "YOU"
        r = self.text(label, self.f_small, col, (sx, tag_y), "midbottom", outline=2)
        pygame.draw.polygon(self.screen, col, [(sx - 6, r.bottom + 1), (sx + 6, r.bottom + 1), (sx, r.bottom + 8)])
        margin = 46
        if not (margin < sx < W - margin and margin < sy - 40 < H - HUD_H - margin):
            cx = min(max(sx, margin), W - margin)
            cy = min(max(sy - 40, margin), H - HUD_H - margin)
            pygame.draw.circle(self.screen, OUTLINE, (cx, cy), 32)
            pygame.draw.circle(self.screen, col, (cx, cy), 30)
            pygame.draw.circle(self.screen, damage_color(rp.damage), (cx, cy), 25)
            hs = art.head_sprite(cid, 15, 1)
            self.screen.blit(hs, hs.get_rect(center=(cx, cy + 2)))
            ang = math.atan2(sy - 40 - cy, sx - cx)
            tip = (cx + math.cos(ang) * 46, cy + math.sin(ang) * 46)
            pygame.draw.polygon(self.screen, col, [tip, (cx + math.cos(ang + 0.4) * 33, cy + math.sin(ang + 0.4) * 33),
                                                   (cx + math.cos(ang - 0.4) * 33, cy + math.sin(ang - 0.4) * 33)])

    def _draw_particles(self):
        ts = self.cam.to_screen
        z = self.cam.zoom
        for p in self.particles:
            k = p.life / p.maxlife
            x, y = ts(p.x, p.y)
            if p.kind == "streak":
                ln = 0.035
                pygame.draw.line(self.screen, p.color, (x, y), (x - p.vx * ln * z, y - p.vy * ln * z),
                                 max(1, int(p.r * k + 0.5)))
            elif p.kind == "puff":
                r = p.r * (1 + (1 - k) * 1.4) * z
                spr = self.puff_sprite(r, p.color)
                spr.set_alpha(int(255 * k))
                self.screen.blit(spr, (x - spr.get_width() / 2, y - spr.get_height() / 2))
            else:
                pygame.draw.circle(self.screen, p.color, (x, y), max(1, p.r * z * (0.4 + 0.6 * k)))

    def _draw_impacts(self):
        ts = self.cam.to_screen
        z = self.cam.zoom
        for x, y, ang, t0, col, heavy in self.slashes:
            k = (self.t - t0) / 0.2
            c = ts(x, y)
            R = (50 if heavy else 36) * z * (0.75 + 0.45 * art.ease_out(k))
            span = 1.15
            outer, inner = [], []
            for i in range(15):
                a = ang - span + 2 * span * i / 14
                taper = math.sin(math.pi * i / 14)
                outer.append((c[0] + math.cos(a) * R, c[1] + math.sin(a) * R))
                inner.append((c[0] + math.cos(a) * R * (1 - 0.34 * taper), c[1] + math.sin(a) * R * (1 - 0.34 * taper)))
            layer_pts = outer + inner[::-1]
            fade = max(0.0, 1 - k)
            colr = lerp_col(col, (255, 255, 255), 0.35)
            pygame.draw.polygon(self.screen, lerp_col((30, 20, 40), colr, fade), layer_pts)
            inner2 = [(c[0] + math.cos(ang - span * 0.8 + 1.6 * span * i / 14) * R * (1 - 0.16 * math.sin(math.pi * i / 14)),
                       c[1] + math.sin(ang - span * 0.8 + 1.6 * span * i / 14) * R * (1 - 0.16 * math.sin(math.pi * i / 14)))
                      for i in range(15)]
            pygame.draw.lines(self.screen, (255, 255, 255), False, inner2, max(2, int(3 * z * fade + 1)))
        for x, y, t0, seed, heavy in self.lines:
            k = (self.t - t0) / 0.16
            c = ts(x, y)
            rng = random.Random(seed)
            for i in range(12 if heavy else 8):
                a = rng.uniform(0, math.tau)
                r0 = (22 + 50 * k) * z
                r1 = r0 + rng.uniform(26, 60 if heavy else 40) * z * (1 - k)
                pygame.draw.line(self.screen, (255, 255, 255), (c[0] + math.cos(a) * r0, c[1] + math.sin(a) * r0),
                                 (c[0] + math.cos(a) * r1, c[1] + math.sin(a) * r1), max(1, int(3 * (1 - k)) + 1))
        for x, y, t0, size, rot in self.sparks:
            k = (self.t - t0) / 0.18
            c = ts(x, y)
            r = (18 + 30 * art.ease_out(k)) * size * z
            pts = starburst(c[0], c[1], r, r * 0.35, 8, rot)
            pygame.draw.polygon(self.screen, (255, 252, 230) if k < 0.5 else GOLD, pts)
            pygame.draw.polygon(self.screen, OUTLINE, pts, max(2, int(2.5 * z)))
        for x, y, txt, t0, col in self.floats:
            age = self.t - t0
            pop = 1.0 + 0.6 * max(0.0, 1 - age / 0.12)
            surf = art.text_outlined(self.f_h2, txt, col, OUTLINE, 3)
            if pop != 1.0:
                surf = pygame.transform.rotozoom(surf, 0, pop)
            if age > 0.6:
                surf.set_alpha(int(255 * max(0.0, (0.9 - age) / 0.3)))
            px, py = ts(x, y - age * 50)
            self.screen.blit(surf, surf.get_rect(center=(px, py)))
        for x, y, word, t0, dur, scale, rot, col in self.comics[-2:]:
            age = self.t - t0
            pop = 0.4 + 0.6 * art.ease_out(min(1.0, age / 0.12))
            fade = 1.0 if age < dur - 0.2 else max(0.0, (dur - age) / 0.2)
            c = ts(x, y)
            sc = scale * pop * 0.62
            word_s = art.text_outlined(self.f_h3, word, (255, 255, 255), OUTLINE, 3)
            r_out = max(word_s.get_width() * 0.62, 40) * sc
            size = int(r_out * 2.4)
            layer = pygame.Surface((size, size), pygame.SRCALPHA)
            m = size / 2
            jit = [1.0, 0.82, 1.08, 0.9, 1.12, 0.86]
            burst = starburst(m, m, r_out, r_out * 0.7, 11, rot * 0.02, jit)
            pygame.draw.polygon(layer, (255, 222, 60), burst)
            pygame.draw.polygon(layer, lerp_col(col, (255, 120, 50), 0.5),
                                starburst(m, m, r_out * 0.74, r_out * 0.52, 11, rot * 0.02 + 0.15, jit))
            pygame.draw.polygon(layer, OUTLINE, burst, 3)
            txt = pygame.transform.rotozoom(word_s, rot, sc)
            layer.blit(txt, txt.get_rect(center=(m, m)))
            if fade < 1:
                layer.set_alpha(int(255 * fade))
            self.screen.blit(layer, layer.get_rect(center=c))

    # ---- HUD -------------------------------------------------------------------
    def _draw_hud(self):
        s = self.state
        pids = s.order or sorted(s.view)
        cw, gap = 286, 22
        x0 = (W - (len(pids) * cw + (len(pids) - 1) * gap)) / 2
        y0 = H - HUD_H + 8
        def build_strip():
            surf = pygame.Surface((W, HUD_H), pygame.SRCALPHA)
            for i in range(HUD_H):
                pygame.draw.line(surf, (6, 4, 16, int(220 * (i / HUD_H) ** 0.6)), (0, i), (W, i))
            return surf
        strip = self._panel_cache.get("hudstrip")
        if strip is None:
            strip = self._panel_cache["hudstrip"] = build_strip()
        self.screen.blit(strip, (0, H - HUD_H))
        for i, pid in enumerate(pids):
            rp = s.view.get(pid)
            cid = s.char_of(pid)
            col = art.player_color(s.slot_of(pid))
            x = x0 + i * (cw + gap)
            card = [(x + 26, y0 + 10), (x + cw, y0 + 10), (x + cw - 18, y0 + 88), (x + 8, y0 + 88)]
            pygame.draw.polygon(self.screen, (10, 8, 20), [(px + 4, py + 5) for px, py in card])
            pygame.draw.polygon(self.screen, (24, 20, 42), card)
            pygame.draw.polygon(self.screen, darken(col, 0.55), [(x + 26, y0 + 10), (x + cw, y0 + 10),
                                                                 (x + cw - 4, y0 + 26), (x + 22, y0 + 26)])
            pygame.draw.polygon(self.screen, col, card, 3)
            out = rp is None or rp.stocks <= 0
            dmg = 0 if rp is None else rp.damage
            cx, cy = x + 44, y0 + 46
            pygame.draw.circle(self.screen, OUTLINE, (cx, cy), 41)
            pygame.draw.circle(self.screen, col, (cx, cy), 39)
            pygame.draw.circle(self.screen, damage_color(dmg) if not out else (70, 66, 90), (cx, cy), 33)
            hs = art.head_sprite(cid, 21, 1)
            self.screen.blit(hs, hs.get_rect(center=(cx + 2, cy + 6)))
            if rp is not None and not out:
                frac = 1 - rp.special_cd / 100
                ready = rp.special_cd == 0
                sc = art.look(cid)["secondary"]
                arc = pygame.Rect(0, 0, 90, 90)
                arc.center = (cx, cy)
                pygame.draw.arc(self.screen, (40, 36, 60), arc, 0, math.tau, 5)
                if frac > 0:
                    pygame.draw.arc(self.screen, GOLD if ready else sc, arc, math.pi / 2 - frac * math.tau, math.pi / 2, 5)
                if ready and pid == s.pid:
                    art.glow(self.screen, GOLD, (cx, cy - 44), 16, 100 + 60 * math.sin(self.t * 6))
            self.text(s.name_of(pid).upper(), self.f_small, TEXT, (x + 96, y0 + 18), "midleft")
            self.text(C.CHARACTERS[cid]["name"].upper(), self.f_tiny, lighten(col, 0.3), (x + cw - 12, y0 + 18), "midright")
            jx = jy = 0
            if self.hud_shake.get(pid, 0) > self.t:
                jx, jy = random.uniform(-4, 4), random.uniform(-3, 3)
            dmg_txt = "OUT" if out else "%d%%" % dmg
            self.text(dmg_txt, self.f_dmg, MUTED if out else damage_color(dmg), (x + 96 + jx, y0 + 56 + jy),
                      "midleft", outline=3)
            if rp is not None:
                for j in range(G.START_STOCKS):
                    c = (x + cw - 34 - j * 22, y0 + 58)
                    on = j < rp.stocks
                    pygame.draw.circle(self.screen, OUTLINE, c, 9)
                    pygame.draw.circle(self.screen, col if on else (50, 46, 70), c, 7)
                    if on:
                        pygame.draw.circle(self.screen, lighten(col, 0.5), (c[0] - 2, c[1] - 2), 2)
        secs = max(0, s.latest_tick() - G.COUNTDOWN_TICKS) // P.TICK_RATE
        pill = pygame.Rect(W / 2 - 64, 10, 128, 36)
        self.panel(pill, (16, 12, 30), 200, PANEL_EDGE, 18)
        self.text("%d:%02d" % (secs // 60, secs % 60), self.f_h3, TEXT, pill.center, "center")

    def _draw_feed(self):
        now = time.monotonic()
        y = 18
        for line, at in list(self.state.feed)[-4:]:
            if now - at > 6:
                continue
            r = self.text(line, self.f_small, TEXT, (W - 22, y + 14), "midright")
            self.panel(r.inflate(24, 10), (16, 12, 30), 190, None, 8)
            self.text(line, self.f_small, TEXT, (W - 22, y + 14), "midright")
            y += 36

    def _draw_overlays(self):
        s = self.state
        cd = s.countdown
        mid_y = (H - HUD_H) / 2
        if cd > 0:
            n = math.ceil(cd / P.TICK_RATE)
            frac = (cd % P.TICK_RATE) / P.TICK_RATE
            surf = art.text_outlined(self.f_logo, str(n), GOLD, OUTLINE, 6)
            surf = pygame.transform.rotozoom(surf, 0, 1.0 + frac * 0.8)
            self.screen.blit(surf, surf.get_rect(center=(W / 2, mid_y + 30)))
        for txt, t0, dur, col, font, sub in self.banners:
            age = self.t - t0
            k = min(1.0, age / 0.18)
            sc = 2.2 - 1.2 * art.ease_out(k)
            key = ("banner", txt, id(font), col)
            base = self._text_cache.get(key)
            if base is None:
                base = self._text_cache[key] = art.text_outlined(font, txt, col, OUTLINE, 7 if font is self.f_logo else 5)
            surf = pygame.transform.rotozoom(base, 0, sc) if k < 1 else base
            alpha = 255 if age < dur - 0.25 else int(255 * max(0, (dur - age) / 0.25))
            surf.set_alpha(alpha)
            cy = mid_y - 40 if font is self.f_logo else 120
            self.screen.blit(surf, surf.get_rect(center=(W / 2, cy)))
            if sub:
                skey = ("banner_sub", sub)
                ss = self._text_cache.get(skey)
                if ss is None:
                    ss = self._text_cache[skey] = art.text_outlined(self.f_body, sub.upper(), TEXT, OUTLINE, 2)
                ss.set_alpha(alpha)
                self.screen.blit(ss, ss.get_rect(center=(W / 2, cy + 46)))
        if self.white_flash > 0:
            fl = pygame.Surface((W, H))
            fl.fill((255, 255, 255))
            fl.set_alpha(int(255 * min(1, self.white_flash / 0.25) * 0.5))
            self.screen.blit(fl, (0, 0))
        if time.monotonic() < self.esc_armed:
            box = self.panel((W / 2 - 230, 54, 460, 44), (90, 20, 40), 220, BAD, 10)
            self.text("Press ESC again to forfeit the match", self.f_body, TEXT, box.center, "center")

    # ---- results ---------------------------------------------------------
    def _draw_results(self, dt):
        s = self.state
        self.vignette(170)
        self.dim(90)
        for p in self.particles:
            pygame.draw.rect(self.screen, p.color, (p.x, p.y, p.r * 2, p.r * 1.2))
        results = s.results or []
        winner = next((r for r in results if r["rank"] == 1), None)
        if winner and s.winner is not None:
            cid = winner["char"]
            col = art.player_color(s.slot_of(winner["pid"]))
            art.glow(self.screen, art.look(cid)["secondary"], (330, 430), 260, 110)
            ped = pygame.Rect(200, 566, 260, 44)
            pygame.draw.ellipse(self.screen, (10, 8, 20), ped.move(0, 8))
            pygame.draw.ellipse(self.screen, GOLD, ped)
            pygame.draw.ellipse(self.screen, OUTLINE, ped, 4)
            pose = rig.pose_for(cid, art.V_VICTORY, 0, self.t, False, False, 0, None, 0)
            rig.draw(self.screen, cid, ped.centerx, ped.centery - 2, 3.4, 1, pose, self.t)
            self.text("VICTORY", self.f_logo, GOLD, (330, 76), "center", outline=6)
            self.text(winner["name"], self.f_h1, col, (330, 160), "center", outline=4)
            self.text(C.CHARACTERS[cid]["title"], self.f_body, TEXT, (330, 200), "center", outline=2)
        else:
            self.text("NO CONTEST", self.f_logo, MUTED, (330, 120), "center", outline=6)
        board = self.panel((640, 70, 600, 470))
        self.text("FINAL STANDINGS", self.f_h2, TEXT, (board.x + 28, board.y + 38), "midleft", outline=2)
        for lbl, x in (("KOs", 400), ("DMG", 470), ("LIVES", 540)):
            self.text(lbl, self.f_tiny, MUTED, (board.x + x, board.y + 82), "center")
        for i, r in enumerate(results):
            row = pygame.Rect(board.x + 20, board.y + 100 + i * 112, board.w - 40, 100)
            col = art.player_color(s.slot_of(r["pid"]))
            self.panel(row, (36, 30, 66) if r["rank"] == 1 else (28, 24, 50), 240, GOLD if r["rank"] == 1 else col, 12, 3)
            self.text("#%d" % r["rank"], self.f_h1, GOLD if r["rank"] == 1 else TEXT, (row.x + 20, row.centery), "midleft",
                      outline=3)
            self.screen.blit(art.portrait(r["char"], 72, 72), (row.x + 92, row.y + 14))
            pygame.draw.rect(self.screen, OUTLINE, (row.x + 92, row.y + 14, 72, 72), 3)
            self.text(r["name"], self.f_h3, TEXT, (row.x + 180, row.y + 36), "midleft")
            sub = C.CHARACTERS[r["char"]]["name"] + ("   FORFEIT" if r["forfeit"] else "")
            self.text(sub, self.f_small, BAD if r["forfeit"] else MUTED, (row.x + 180, row.y + 66), "midleft")
            for val, x in ((r["kos"], 400), (r["dealt"], 470), (r["stocks"], 540)):
                self.text(str(val), self.f_h3, TEXT, (board.x + x, row.centery), "center")
        self.button((640, 580, 290, 90), "REMATCH", self._do_rematch, font=self.f_h2, enabled=bool(s.room_name))
        self.button((950, 580, 290, 90), "LEAVE ARENA", s.leave_room, "secondary", font=self.f_h2,
                    enabled=bool(s.room_name))


def s_map(state):
    return state.map_id if state.map_id in M.MAPS else M.DEFAULT


def run(host, port, name=None):
    from client.net_tcp import NetTCP
    net = NetTCP(host, port)
    state = ClientState(net, name or "")
    app = App(state, "%s:%d (TCP)" % (host, port))
    if name:
        state.login(name)
    app.run()
