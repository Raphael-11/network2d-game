"""Procedural art: fighter portraits, animated fighters, stage, backgrounds.

Everything is drawn with pygame primitives (no image assets) in a bold,
outlined cartoon style. Fighter geometry uses local units where the feet are
at (0, 0), up is negative y, and the body is ~60 units tall (physics HEIGHT).
"""
import math
import random

import pygame

from common import characters as C
from common import physics as G

OUTLINE = (18, 16, 26)

LOOKS = {
    "ragnar": dict(skin=(232, 178, 138), primary=(62, 98, 150), secondary=(140, 86, 48),
                   hair=(214, 112, 42), eye=(70, 140, 220), metal=(172, 178, 190),
                   bg=((70, 110, 170), (18, 26, 58)), head="viking", scale=1.06),
    "kira": dict(skin=(240, 202, 172), primary=(38, 38, 56), secondary=(205, 40, 62),
                 hair=(24, 24, 30), eye=(220, 60, 80), metal=(215, 225, 235),
                 bg=((150, 34, 60), (28, 8, 22)), head="ninja", scale=0.95),
    "blaze": dict(skin=(246, 196, 160), primary=(186, 56, 30), secondary=(255, 176, 48),
                  hair=(255, 92, 32), eye=(255, 210, 60), metal=(255, 140, 40),
                  bg=((228, 96, 36), (70, 14, 10)), head="flame", scale=1.0),
    "titan": dict(skin=(118, 134, 156), primary=(82, 92, 112), secondary=(58, 206, 236),
                  hair=(60, 66, 80), eye=(80, 230, 255), metal=(96, 104, 122),
                  bg=((54, 82, 118), (12, 18, 34)), head="golem", scale=1.15),
    "vex": dict(skin=(206, 150, 108), primary=(118, 74, 46), secondary=(206, 172, 92),
                hair=(64, 42, 26), eye=(90, 170, 110), metal=(110, 112, 120),
                bg=((176, 118, 58), (52, 28, 14)), head="cowboy", scale=1.0),
    "luna": dict(skin=(236, 214, 236), primary=(84, 52, 136), secondary=(196, 176, 255),
                 hair=(226, 220, 250), eye=(170, 110, 255), metal=(200, 190, 240),
                 bg=((104, 66, 180), (20, 14, 52)), head="witch", scale=1.0),
    "rex": dict(skin=(148, 116, 90), primary=(92, 72, 56), secondary=(232, 200, 84),
                hair=(116, 92, 72), eye=(255, 210, 40), metal=(240, 236, 210),
                bg=((96, 132, 62), (22, 34, 14)), head="wolf", scale=1.05),
    "aria": dict(skin=(246, 212, 182), primary=(228, 230, 242), secondary=(222, 180, 58),
                 hair=(252, 214, 108), eye=(80, 170, 255), metal=(236, 196, 80),
                 bg=((74, 146, 216), (18, 40, 84)), head="valkyrie", scale=1.0),
}

PLAYER_COLORS = [(255, 82, 102), (64, 170, 255), (255, 196, 54), (110, 230, 140)]

V_VICTORY = 99            # client-only pose code for the results screen


def player_color(slot):
    return PLAYER_COLORS[slot % len(PLAYER_COLORS)]


def look(cid):
    return LOOKS.get(cid, LOOKS[C.DEFAULT])


def lighten(c, t):
    return tuple(int(v + (255 - v) * t) for v in c[:3])


def darken(c, t):
    return tuple(int(v * (1 - t)) for v in c[:3])


def lerp(a, b, t):
    return a + (b - a) * t


def ease_out(k):
    return 1 - (1 - k) ** 3


# ---- primitive helpers -------------------------------------------------------
def _cap_line(surf, col, a, b, w):
    w = max(1, int(w))
    pygame.draw.line(surf, col, a, b, w)
    r = w / 2
    if r >= 1.5:
        pygame.draw.circle(surf, col, a, r)
        pygame.draw.circle(surf, col, b, r)


def limb(surf, a, b, w, col, outline=OUTLINE, ow=3):
    _cap_line(surf, outline, a, b, w + ow)
    _cap_line(surf, col, a, b, w)


def poly(surf, col, pts, outline=OUTLINE, ow=2):
    if len(pts) < 3:
        return
    pygame.draw.polygon(surf, col, pts)
    if outline is not None and ow:
        pygame.draw.polygon(surf, outline, pts, ow)


def circle(surf, col, c, r, outline=OUTLINE, ow=2):
    pygame.draw.circle(surf, col, c, max(1, r))
    if outline is not None and ow and r > 2:
        pygame.draw.circle(surf, outline, c, max(1, r), ow)


def text_outlined(font, text, col, outline=OUTLINE, ow=2):
    base = font.render(text, True, col)
    w, h = base.get_width() + ow * 2, base.get_height() + ow * 2
    out = pygame.Surface((w, h), pygame.SRCALPHA)
    edge = font.render(text, True, outline)
    for dx in (-ow, 0, ow):
        for dy in (-ow, 0, ow):
            if dx or dy:
                out.blit(edge, (ow + dx, ow + dy))
    out.blit(base, (ow, ow))
    return out


_glow_cache = {}


def glow(surf, col, c, r, alpha=110):
    """Additive soft light. Colors are premultiplied onto black so ADD stays soft."""
    # quantize so flickering lights reuse a handful of cached sprites
    r = max(2, int(r) // 3 * 3 + 2)
    alpha = max(0, min(255, int(alpha) // 16 * 16 + 8))
    has_alpha = bool(surf.get_flags() & pygame.SRCALPHA)
    key = (col[:3], r, alpha, has_alpha)
    g = _glow_cache.get(key)
    if g is None:
        if has_alpha:          # transparent layer: ADD would vanish, so use a soft alpha disc
            g = pygame.Surface((r * 2, r * 2), pygame.SRCALPHA)
            for i in range(r, 0, -max(1, r // 12)):
                pygame.draw.circle(g, (*col[:3], int(alpha * 0.8 * (1 - i / r) ** 1.6)), (r, r), i)
        else:
            g = pygame.Surface((r * 2, r * 2))
            for i in range(r, 0, -max(1, r // 12)):
                k = alpha / 255 * (1 - i / r) ** 1.6
                pygame.draw.circle(g, tuple(int(v * k) for v in col[:3]), (r, r), i)
        if len(_glow_cache) > 1500:
            _glow_cache.clear()
        _glow_cache[key] = g
    if has_alpha:
        surf.blit(g, (c[0] - r, c[1] - r))
    else:
        surf.blit(g, (c[0] - r, c[1] - r), special_flags=pygame.BLEND_RGB_ADD)


def lerp_col(a, b, t):
    return tuple(int(lerp(x, y, t)) for x, y in zip(a, b))


# ---- portraits & head sprites (detailed art lives in client/portraits.py) --------
_portrait_cache = {}
_head_cache = {}
_head_src = {}


def portrait(cid, w, h, t=0.0):
    key = (cid, w, h)
    surf = _portrait_cache.get(key)
    if surf is None:
        from client import portraits
        if ("full", cid) not in _portrait_cache:
            _portrait_cache[("full", cid)] = portraits.render_portrait(cid, look(cid), 480)
        surf = pygame.transform.smoothscale(_portrait_cache[("full", cid)], (w, h))
        if pygame.display.get_surface() is not None:
            surf = surf.convert_alpha()
        _portrait_cache[key] = surf
    return surf


def preload():
    """Render all portraits up front (avoids first-frame hitches)."""
    for cid in C.ORDER:
        portrait(cid, 132, 132)


def head_sprite(cid, r_px, facing, mode=None):
    """Detailed head scaled so its radius is r_px. mode: None | 'flash' | (r, g, b) tint."""
    r_px = max(4, int(r_px))
    key = (cid, r_px, facing, mode)
    img = _head_cache.get(key)
    if img is not None:
        return img
    if cid not in _head_src:
        from client import portraits
        _head_src[cid] = portraits.render_head(cid, look(cid))
    src, R = _head_src[cid]
    size = max(2, int(src.get_width() * r_px / R))
    img = pygame.transform.smoothscale(src, (size, size))
    if facing < 0:
        img = pygame.transform.flip(img, True, False)
    if mode == "flash":
        img = img.copy()
        img.fill((110, 110, 110, 0), special_flags=pygame.BLEND_RGB_ADD)
    elif mode == "hurt":
        img = img.copy()
        img.fill((255, 196, 196, 255), special_flags=pygame.BLEND_RGBA_MULT)
        img.fill((46, 0, 0, 0), special_flags=pygame.BLEND_RGB_ADD)
    elif mode is not None:
        img = img.copy()
        img.fill((255, 255, 255, 0), special_flags=pygame.BLEND_RGB_MAX)
        img.fill((*mode[:3], 255), special_flags=pygame.BLEND_RGBA_MULT)
    if pygame.display.get_surface() is not None:
        img = img.convert_alpha()
    if len(_head_cache) > 300:
        _head_cache.clear()
    _head_cache[key] = img
    return img


# ---- projectiles -------------------------------------------------------------
def draw_projectile(surf, kind, sx, sy, zoom, direction, t):
    if C.PROJ_KINDS[kind] == "fireball":
        r = 16 * zoom
        glow(surf, (255, 120, 30), (sx, sy), r * 3.2, 150)
        for i in range(5):
            tx = sx - direction * (i + 1) * r * 0.55
            ty = sy + math.sin(t * 20 + i) * r * 0.2
            pygame.draw.circle(surf, lerp_col((255, 200, 60), (180, 40, 20), i / 5), (tx, ty), r * (0.9 - i * 0.15))
        circle(surf, (255, 170, 50), (sx, sy), r, OUTLINE, max(2, int(2.5 * zoom)))
        pygame.draw.circle(surf, (255, 245, 200), (sx + direction * r * 0.25, sy), r * 0.55)
    else:
        r = 5 * zoom
        glow(surf, (255, 230, 140), (sx, sy), r * 4, 130)
        pygame.draw.line(surf, (255, 220, 120), (sx - direction * 34 * zoom, sy), (sx, sy), max(2, int(3 * zoom)))
        circle(surf, (255, 255, 230), (sx, sy), r, OUTLINE, 2)


# ---- fallback sky (used when a map's painted backdrop is missing) ---------------
class Background:
    def __init__(self, w, h, seed=5):
        self.w, self.h = w, h
        rng = random.Random(seed)
        self.sky = pygame.Surface((w, h))
        stops = [(0.0, (22, 18, 54)), (0.45, (84, 46, 112)), (0.75, (212, 104, 104)), (1.0, (252, 176, 112))]
        for y in range(h):
            k = y / (h - 1)
            for (k0, c0), (k1, c1) in zip(stops, stops[1:]):
                if k0 <= k <= k1:
                    pygame.draw.line(self.sky, lerp_col(c0, c1, (k - k0) / (k1 - k0)), (0, y), (w, y))
                    break
        self.stars = [(rng.uniform(0, w), rng.uniform(0, h * 0.45), rng.uniform(0.5, 1.8), rng.uniform(0, 6)) for _ in range(90)]
        self.layers = []
        for depth, base, amp, color in ((0.06, 0.62, 0.16, (76, 50, 102)), (0.14, 0.72, 0.13, (58, 36, 82)),
                                        (0.26, 0.82, 0.10, (40, 24, 60))):
            pts, x = [], -800
            while x < w + 1600:
                pts.append((x, h * (base - amp * abs(math.sin(x * 0.004 + rng.uniform(0, 0.4))) - rng.uniform(0, amp * 0.4))))
                x += rng.uniform(60, 140)
            self.layers.append((depth, pts, color))
        self.clouds = []
        for _ in range(7):
            cw = rng.randint(160, 320)
            cs = pygame.Surface((cw, cw // 3), pygame.SRCALPHA)
            for _ in range(7):
                rr = rng.randint(cw // 10, cw // 5)
                pygame.draw.circle(cs, (255, 220, 230, 38), (rng.randint(rr, cw - rr), rng.randint(cw // 6, cw // 3 - rr // 3)), rr)
            self.clouds.append([rng.uniform(0, w), rng.uniform(h * 0.12, h * 0.5), rng.uniform(6, 18), cs])
        self.motes = [[rng.uniform(0, w), rng.uniform(0, h), rng.uniform(8, 26), rng.uniform(0, 6), rng.uniform(1, 2.5)] for _ in range(40)]
        self.sun = pygame.Surface((520, 520))
        for i in range(260, 0, -4):
            k = 0.4 * (1 - i / 260) ** 2
            pygame.draw.circle(self.sun, (int(255 * k), int(200 * k), int(150 * k)), (260, 260), i)
        pygame.draw.circle(self.sun, (230, 200, 150), (260, 260), 54)

    def draw_motes(self, surf, t, dt):
        for m in self.motes[:18]:
            m[1] -= m[2] * dt
            if m[1] < -10:
                m[1] = self.h + 10
                m[0] = random.uniform(0, self.w)
            glow(surf, (255, 190, 140), (m[0] + math.sin(t + m[3]) * 14, m[1]), m[4] * 4, 70)

    def draw(self, surf, cam_x, t, dt, motes=True):
        surf.blit(self.sky, (0, 0))
        for x, y, r, ph in self.stars:
            a = 0.5 + 0.5 * math.sin(t * 1.5 + ph)
            c = int(140 + 110 * a)
            pygame.draw.circle(surf, (c, c, min(255, c + 20)), (x, y), r)
        px = -(cam_x - 640) * 0.03
        surf.blit(self.sun, (self.w * 0.7 - 260 + px, self.h * 0.52 - 260), special_flags=pygame.BLEND_RGB_ADD)
        for c in self.clouds:
            c[0] += c[2] * dt
            if c[0] > self.w + 50:
                c[0] = -c[3].get_width()
            surf.blit(c[3], (c[0] - (cam_x - 640) * 0.1, c[1]))
        for depth, pts, color in self.layers:
            off = -(cam_x - 640) * depth
            shifted = [(x + off, y) for x, y in pts] + [(self.w + 1600, self.h), (-800, self.h)]
            pygame.draw.polygon(surf, color, shifted)
        if motes:
            self.draw_motes(surf, t, dt)
