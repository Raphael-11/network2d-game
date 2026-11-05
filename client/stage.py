"""Arenas: follow camera, painted parallax backgrounds, stage art and ambient life.

The camera only pans (fixed zoom), and its offset is rounded to whole pixels
so the stage, background and fighters never jitter against each other.
Stage art is painted once per map at 2x and cached; only small animated
details (fire, lanterns, glows, grass, ambient particles) are drawn per frame.
"""
import math
import os
import random

import pygame

from common import maps as M
from client import art
from client.art import OUTLINE, lighten, darken, lerp_col, glow, poly

ASSET_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")
ZOOM = 1.3                  # fighters ~120 px tall: the art reads, and the arena feels big
RS = 2.0


# ---- camera --------------------------------------------------------------------
class Camera:
    def __init__(self, map_id, w, h, hud_h):
        mp = M.get(map_id)
        mains = [p for p in mp["platforms"] if p[3]] or mp["platforms"]
        self.cx0 = (min(p[0] for p in mains) + max(p[1] for p in mains)) / 2
        self.cy0 = min(p[2] for p in mains) - 150
        self.x, self.y = self.cx0, self.cy0
        self.zoom = ZOOM
        self.w, self.h, self.hud_h = w, h, hud_h
        self._ox = self._oy = 0

    def update(self, pts, dt):
        if pts:
            tx = sum(p[0] for p in pts) / len(pts)
            ty = sum(p[1] for p in pts) / len(pts) - 70
        else:
            tx, ty = self.cx0, self.cy0
        tx = max(self.cx0 - 380, min(self.cx0 + 380, tx))
        ty = max(self.cy0 - 190, min(self.cy0 + 90, ty))
        if abs(ty - self.y) < 40:                       # vertical dead-zone: jumps don't bob the view
            ty = self.y
        self.x += (tx - self.x) * (1 - math.exp(-dt * 2.6))
        self.y += (ty - self.y) * (1 - math.exp(-dt * 1.6))
        self._ox = round(self.w / 2 - self.x * self.zoom)
        self._oy = round((self.h - self.hud_h) / 2 - self.y * self.zoom)

    def to_screen(self, x, y):
        return (x * self.zoom + self._ox, y * self.zoom + self._oy)


# ---- painted background ----------------------------------------------------------
class Backdrop:
    """A painted panorama with parallax, plus a living layer of ambient effects."""

    def __init__(self, map_id, w, h):
        self.map_id = map_id
        self.mp = M.get(map_id)
        self.theme = self.mp["theme"]
        self.w, self.h = w, h
        self.image = None
        bg = self.mp.get("bg")
        if bg and os.path.isfile(os.path.join(ASSET_DIR, bg)):
            try:
                img = pygame.image.load(os.path.join(ASSET_DIR, bg))
                self.src_size = img.get_size()
                sc = max(w * 1.45 / img.get_width(), h * 1.25 / img.get_height())
                self.scale = sc
                self.image = pygame.transform.smoothscale(img, (int(img.get_width() * sc), int(img.get_height() * sc)))
                if pygame.display.get_surface() is not None:
                    self.image = self.image.convert()
            except (pygame.error, OSError):
                self.image = None
        if self.image is None:
            self.fallback = art.Background(w, h)
        self.ox = self.oy = 0.0
        rng = random.Random(hash(map_id) & 0xFFFF)
        self.rng = rng
        night = self.theme != "day"
        self.night = night
        self.stars = [(rng.uniform(0, 1), rng.uniform(0, 0.35), rng.uniform(0, 6), rng.uniform(0.6, 1.6))
                      for _ in range(70 if night else 0)]
        self.clouds = [[rng.uniform(-0.2, 1.2), rng.uniform(0.05, 0.45), rng.uniform(4, 10), self._cloud(rng, night)]
                       for _ in range(5)]
        self.birds = [] if night else [self._flock(rng, first=True)]
        self.leaves = [[rng.uniform(0, w), rng.uniform(-h, h), rng.uniform(0, 6)] for _ in range(26)]
        self.flies = [[rng.uniform(0, w), rng.uniform(h * 0.3, h), rng.uniform(0, 6), rng.uniform(0, 6)]
                      for _ in range(14 if night else 0)]
        self.fog = [[rng.uniform(0, w), h * rng.uniform(0.72, 0.95), rng.uniform(260, 520), rng.uniform(8, 20)]
                    for _ in range(6)]
        self._fog_sprite = self._soft_blob(420, 90, (210, 220, 255) if night else (255, 255, 255), 46)

    # -- generated sprites
    @staticmethod
    def _soft_blob(w, h, col, alpha):
        s = pygame.Surface((w, h), pygame.SRCALPHA)
        for i in range(12, 0, -1):
            k = i / 12
            a = int(alpha * (1 - k) ** 1.2)
            pygame.draw.ellipse(s, (*col, a), (w * (1 - k) / 2, h * (1 - k) / 2, w * k, h * k))
        return s

    def _cloud(self, rng, night):
        cw = rng.randint(220, 380)
        s = pygame.Surface((cw, cw // 2), pygame.SRCALPHA)
        col = (190, 200, 240) if night else (255, 255, 255)
        for _ in range(9):
            r = rng.randint(cw // 9, cw // 5)
            x = rng.randint(r, cw - r)
            y = rng.randint(cw // 5, cw // 2 - r // 2)
            blob = self._soft_blob(r * 2, r * 2, col, 60 if night else 85)
            s.blit(blob, (x - r, y - r))
        return s

    def _flock(self, rng, first=False):
        d = rng.choice((-1, 1))
        y = rng.uniform(0.12, 0.38) * self.h
        x = rng.uniform(0, self.w) if first else (-80 if d > 0 else self.w + 80)
        birds = [(rng.uniform(-40, 40), rng.uniform(-18, 18), rng.uniform(0, 6)) for _ in range(rng.randint(4, 7))]
        return {"x": x, "y": y, "d": d, "speed": rng.uniform(26, 44), "birds": birds}

    # -- coordinates of the painted image
    def img_to_screen(self, ix, iy):
        return (ix * self.scale + self.ox, iy * self.scale + self.oy)

    def draw(self, surf, cam, t, dt):
        if self.image is None:
            self.fallback.draw(surf, cam.x if cam else 640, t, dt)
            return
        iw, ih = self.image.get_size()
        px = -(cam.x - cam.cx0) * 0.28 if cam else math.sin(t * 0.07) * 120
        py = -(cam.y - cam.cy0) * 0.12 if cam else 0
        self.ox = max(self.w - iw, min(0, (self.w - iw) / 2 + px))
        self.oy = max(self.h - ih, min(0, (self.h - ih) * 0.55 + py))
        surf.blit(self.image, (self.ox, self.oy))
        self._ambient_back(surf, t, dt)

    def _ambient_back(self, surf, t, dt):
        w, h = self.w, self.h
        if self.night:
            for x, y, ph, r in self.stars:
                a = 0.5 + 0.5 * math.sin(t * 2.2 + ph)
                if a > 0.75:
                    c = (x * w, y * h)
                    k = (a - 0.75) * 4
                    pygame.draw.line(surf, (255, 255, 255), (c[0] - 4 * r * k, c[1]), (c[0] + 4 * r * k, c[1]))
                    pygame.draw.line(surf, (255, 255, 255), (c[0], c[1] - 4 * r * k), (c[0], c[1] + 4 * r * k))
                    glow(surf, (200, 210, 255), c, 6 * r, int(120 * k))
            moon = {"moon_harbor": (1475, 135), "citadel": (1602, 141)}.get(self.map_id)
            if moon:
                mx, my = self.img_to_screen(*moon)
                glow(surf, (170, 190, 255), (mx, my), 150, int(55 + 25 * math.sin(t * 0.8)))
            if self.map_id == "moon_harbor":
                for i in range(7):
                    rx, ry = self.img_to_screen(1500 + math.sin(t * 0.9 + i * 1.7) * 26, 610 + i * 13)
                    ln = 30 + 16 * math.sin(t * 2.3 + i)
                    pygame.draw.line(surf, (200, 220, 255), (rx - ln / 2, ry), (rx + ln / 2, ry), 2)
        else:
            for ix0, ix1, iy0, iy1 in ((356, 422, 520, 760), (1330, 1385, 425, 565), (1250, 1288, 550, 640)):
                x0, y0 = self.img_to_screen(ix0, iy0)
                x1, y1 = self.img_to_screen(ix1, iy1)
                for k in range(6):
                    xx = x0 + (x1 - x0) * (k + 0.5) / 6
                    off = (t * 140 + k * 37) % max(1, (y1 - y0))
                    pygame.draw.line(surf, (235, 245, 255), (xx, y0 + off), (xx, min(y1, y0 + off + 26)), 2)
                glow(surf, (255, 255, 255), ((x0 + x1) / 2, y1), (x1 - x0) * 1.2, 60)
            for fl in self.birds:
                fl["x"] += fl["d"] * fl["speed"] * dt
                for bx, by, ph in fl["birds"]:
                    x, y = fl["x"] + bx, fl["y"] + by + math.sin(t * 1.5 + ph) * 3
                    flap = math.sin(t * 9 + ph) * 4
                    pygame.draw.lines(surf, (40, 50, 80), False, [(x - 7, y - flap), (x, y), (x + 7, y - flap)], 2)
            if self.birds and (self.birds[0]["x"] < -200 or self.birds[0]["x"] > w + 200):
                self.birds = [self._flock(self.rng)]
        for c in self.clouds:
            c[0] += c[2] * dt / w
            if c[0] > 1.25:
                c[0] = -0.3
            surf.blit(c[3], (c[0] * w + self.ox * 0.2, c[1] * h))

    def draw_front(self, surf, t, dt):
        """Foreground life drawn over the stage and fighters (kept sparse and soft)."""
        w, h = self.w, self.h
        for f in self.fog:
            f[0] += f[3] * dt
            if f[0] - f[2] > w:
                f[0] = -f[2]
            spr = self._fog_sprite
            surf.blit(spr, (f[0] - spr.get_width() / 2, f[1] - spr.get_height() / 2))
        petal = (255, 170, 210) if self.theme != "day" else (140, 200, 90)
        for lf in self.leaves:
            lf[1] += 34 * dt
            lf[0] += math.sin(t * 1.3 + lf[2]) * 22 * dt + 12 * dt
            if lf[1] > h + 10:
                lf[1] = -10
                lf[0] = random.uniform(-40, w)
            a = t * 3 + lf[2]
            dx, dy = math.cos(a) * 5, math.sin(a) * 2.2
            pygame.draw.polygon(surf, petal, [(lf[0] - dx, lf[1] - dy), (lf[0] + dy, lf[1] - dx * 0.4),
                                              (lf[0] + dx, lf[1] + dy), (lf[0] - dy, lf[1] + dx * 0.4)])
        for fl in self.flies:
            fl[0] += math.sin(t * 0.7 + fl[2]) * 18 * dt
            fl[1] += math.cos(t * 0.6 + fl[3]) * 12 * dt
            k = 0.5 + 0.5 * math.sin(t * 3 + fl[2])
            glow(surf, (210, 255, 150), (fl[0], fl[1]), 10, int(60 + 120 * k))


# ---- stage art -----------------------------------------------------------------
THEMES = {
    "day": dict(stone=(150, 146, 156), stone_d=(118, 112, 128), rock=[(118, 104, 112), (98, 84, 96), (80, 66, 80), (62, 50, 66)],
                moss=(76, 168, 70), moss_l=(150, 222, 96), banner=(176, 36, 56), trim=(232, 190, 74),
                crystal=(120, 220, 255), fire=((255, 110, 40), (255, 200, 70))),
    "harbor": dict(stone=(84, 88, 118), stone_d=(64, 66, 96), rock=[(70, 74, 104), (56, 58, 88), (44, 44, 72), (32, 32, 56)],
                   moss=(60, 120, 90), moss_l=(110, 180, 120), banner=(178, 34, 48), trim=(230, 180, 80),
                   wood=(126, 70, 44), red=(196, 44, 44), crystal=(255, 140, 90), fire=((255, 120, 50), (255, 220, 120))),
    "citadel": dict(stone=(92, 78, 120), stone_d=(70, 58, 98), rock=[(80, 66, 104), (64, 52, 88), (50, 40, 72), (38, 30, 58)],
                    moss=(90, 70, 140), moss_l=(170, 130, 230), banner=(120, 30, 90), trim=(230, 180, 90),
                    crystal=(200, 120, 255), fire=((170, 90, 255), (240, 200, 255))),
}


class StageArt:
    def __init__(self, map_id):
        self.mp = M.get(map_id)
        self.theme = self.mp["theme"]
        self.T = THEMES[self.theme]
        plats = self.mp["platforms"]
        self.x0 = min(p[0] for p in plats) - 90
        self.x1 = max(p[1] for p in plats) + 90
        self.y0 = min(p[2] for p in plats) - 140
        self.y1 = max(p[2] for p in plats) + 360
        self.surf = pygame.Surface((int((self.x1 - self.x0) * RS), int((self.y1 - self.y0) * RS)), pygame.SRCALPHA)
        self.rng = random.Random(11)
        self.fx = []            # animated details: (kind, x, y, extra)
        self.grass = []
        for xl, xr, y, solid in plats:
            if solid:
                self._main(xl, xr, y)
        for i, (xl, xr, y, solid) in enumerate(plats):
            if not solid:
                self._soft(xl, xr, y, i)
        self._scaled = {}

    # -- coordinate helpers (world -> canvas px)
    def p(self, x, y):
        return ((x - self.x0) * RS, (y - self.y0) * RS)

    def ps(self, pts):
        return [self.p(x, y) for x, y in pts]

    def poly(self, pts, fill, ow=2.5, out=OUTLINE):
        pp = self.ps(pts)
        pygame.draw.polygon(self.surf, fill, pp)
        if ow:
            pygame.draw.polygon(self.surf, out, pp, max(1, int(ow * RS)))

    def rect(self, x, y, w, h, fill, ow=2.5, radius=0):
        r = pygame.Rect(*self.p(x, y), w * RS, h * RS)
        pygame.draw.rect(self.surf, fill, r, border_radius=int(radius * RS))
        if ow:
            pygame.draw.rect(self.surf, OUTLINE, r, max(1, int(ow * RS)), border_radius=int(radius * RS))
        return r

    def masked(self, outline_pts, painter):
        layer = pygame.Surface(self.surf.get_size(), pygame.SRCALPHA)
        painter(layer)
        mask = pygame.Surface(self.surf.get_size(), pygame.SRCALPHA)
        pygame.draw.polygon(mask, (255, 255, 255, 255), self.ps(outline_pts))
        layer.blit(mask, (0, 0), special_flags=pygame.BLEND_RGBA_MIN)
        self.surf.blit(layer, (0, 0))

    def rock_body(self, pts, top_y):
        T = self.T

        def paint(layer):
            y = top_y
            for i, (hgt, c) in enumerate(((16, T["rock"][0]), (34, T["rock"][1]), (60, T["rock"][2]), (400, T["rock"][3]))):
                wob = [self.p(x, y + math.sin(x * 0.03 + i) * 5) for x in range(int(self.x0), int(self.x1) + 30, 30)]
                pygame.draw.polygon(layer, c, wob + [self.p(self.x1 + 30, self.y1 + 10), self.p(self.x0 - 30, self.y1 + 10)])
                y += hgt
            for _ in range(160):
                x = self.rng.uniform(self.x0, self.x1)
                yy = self.rng.uniform(top_y, self.y1)
                r = self.rng.uniform(3, 9)
                c = lighten(T["rock"][1], 0.14) if self.rng.random() < 0.5 else darken(T["rock"][2], 0.25)
                pygame.draw.polygon(layer, c, [self.p(x + math.cos(a) * r, yy + math.sin(a) * r * 0.6)
                                               for a in (k * math.tau / 6 for k in range(6))])
            for _ in range(28):
                x = self.rng.uniform(self.x0, self.x1)
                yy = self.rng.uniform(top_y + 20, self.y1)
                line = [self.p(x, yy)]
                for _ in range(4):
                    x += self.rng.uniform(-8, 8)
                    yy += self.rng.uniform(6, 14)
                    line.append(self.p(x, yy))
                pygame.draw.lines(layer, darken(T["rock"][3], 0.35), False, line, int(2 * RS))
        pygame.draw.polygon(self.surf, (12, 10, 26), self.ps([(x + 12, y + 16) for x, y in pts]))
        self.masked(pts, paint)
        pygame.draw.polygon(self.surf, OUTLINE, self.ps(pts), int(3 * RS))

    def vines(self, xl, xr, y, n):
        for _ in range(n):
            vx = self.rng.uniform(xl + 10, xr - 10)
            ln = self.rng.uniform(25, 85)
            pts = [self.p(vx + math.sin(k * 0.6) * 4, y + k * ln / 8) for k in range(9)]
            pygame.draw.lines(self.surf, darken(self.T["moss"], 0.35), False, pts, int(3 * RS))
            for px, py in pts[2::2]:
                pygame.draw.ellipse(self.surf, self.T["moss"], (px - 4 * RS, py - 2 * RS, 8 * RS, 5 * RS))

    def grass_top(self, xl, xr, y, thick=10):
        T = self.T
        r = self.rect(xl - 3, y - 6, xr - xl + 6, thick, T["moss"], 0, 5)
        pygame.draw.rect(self.surf, T["moss_l"], (r.x, r.y, r.w, 3.5 * RS), border_radius=int(3 * RS))
        x = xl
        while x < xr:
            drip = self.rng.uniform(3, 11)
            pygame.draw.ellipse(self.surf, T["moss"], (*self.p(x, y + thick - 9), 9 * RS, drip * RS))
            x += self.rng.uniform(9, 20)
        pygame.draw.rect(self.surf, OUTLINE, r, int(2 * RS), border_radius=int(5 * RS))
        for _ in range(int((xr - xl) / 9)):
            self.grass.append((self.rng.uniform(xl, xr), y - 5, self.rng.uniform(4, 11)))

    def banner(self, x, y, w, h):
        T = self.T
        pts = [(x - w / 2, y), (x + w / 2, y), (x + w / 2, y + h), (x, y + h - w * 0.35), (x - w / 2, y + h)]
        self.poly(pts, T["banner"])
        self.poly([(x - w / 2, y), (x - w * 0.2, y), (x - w * 0.2, y + h - w * 0.25), (x - w / 2, y + h)],
                  darken(T["banner"], 0.25), 0)
        pygame.draw.lines(self.surf, T["trim"], False, self.ps([(x - w / 2 + 2, y + 2), (x - w / 2 + 2, y + h - 3)]), int(1.5 * RS))
        pygame.draw.lines(self.surf, T["trim"], False, self.ps([(x + w / 2 - 2, y + 2), (x + w / 2 - 2, y + h - 3)]), int(1.5 * RS))
        cy = y + h * 0.42
        em = [(x, cy - w * 0.32), (x + w * 0.24, cy - w * 0.05), (x + w * 0.1, cy - w * 0.02), (x, cy + w * 0.28),
              (x - w * 0.1, cy - w * 0.02), (x - w * 0.24, cy - w * 0.05)]
        self.poly(em, T["trim"], 1.2)
        self.poly([(x - w / 2 - 3, y - 4), (x + w / 2 + 3, y - 4), (x + w / 2 + 3, y + 1), (x - w / 2 - 3, y + 1)], (90, 66, 44), 1.5)

    # -- platforms
    def _main(self, xl, xr, y):
        T = self.T
        th = self.theme
        mid = (xl + xr) / 2
        width = xr - xl
        under = [(xl - 6, y + 66), (xr + 6, y + 66), (xr - width * 0.05, y + 120), (xr - width * 0.16, y + 190),
                 (mid + width * 0.2, y + 240), (mid + width * 0.05, y + 310), (mid - width * 0.08, y + 250),
                 (mid - width * 0.24, y + 205), (xl + width * 0.12, y + 140), (xl + width * 0.03, y + 96)]
        self.rock_body(under, y + 66)
        for i in range(3):
            cx = xl + width * (0.25 + i * 0.25) + self.rng.uniform(-30, 30)
            cy = y + 120 + self.rng.uniform(0, 80)
            h = self.rng.uniform(14, 24)
            pts = [(cx, cy - h), (cx + h * 0.45, cy), (cx, cy + h * 0.7), (cx - h * 0.45, cy)]
            self.poly(pts, T["crystal"], 2)
            self.poly([(cx, cy - h), (cx + h * 0.2, cy - h * 0.1), (cx, cy + h * 0.3)], lighten(T["crystal"], 0.5), 0)
            self.fx.append(("crystal", cx, cy, h))
        if th == "harbor":
            for k in range(int(width // 90) + 1):
                px = xl + 20 + k * (width - 40) / max(1, int(width // 90))
                self.rect(px - 7, y + 10, 14, 80, darken(T["wood"], 0.25), 2.2)
            self.rect(xl - 4, y + 4, width + 8, 16, T["stone_d"], 2.5, 3)
            deck = self.rect(xl - 6, y - 4, width + 12, 10, T["wood"], 2.5, 2)
            x = xl
            while x < xr:
                pygame.draw.line(self.surf, darken(T["wood"], 0.3), self.p(x, y - 4), self.p(x, y + 6), int(1.5 * RS))
                x += 22
            pygame.draw.line(self.surf, lighten(T["wood"], 0.3), deck.topleft, deck.topright, int(2 * RS))
            for k, px in enumerate((xl + 18, xr - 18)):
                self.rect(px - 4, y - 70, 8, 66, darken(T["wood"], 0.15), 2)
                self.rect(px - 11, y - 76, 22, 8, T["red"], 2, 2)
                self.fx.append(("lantern", px + (14 if k == 0 else -14), y - 52, 0))
                pygame.draw.line(self.surf, OUTLINE, self.p(px, y - 68), self.p(px + (14 if k == 0 else -14), y - 64), int(1.5 * RS))
            for k in range(3):
                cx = xl + width * (0.3 + 0.2 * k)
                pygame.draw.lines(self.surf, (200, 170, 120), False,
                                  [self.p(cx - 36 + i * 9, y + 22 + math.sin(i / 8 * math.pi) * 10) for i in range(9)], int(2 * RS))
            return
        wall_top, wall_h = y + 6, 62
        self.rect(xl - 4, wall_top, width + 8, wall_h, T["stone"], 3)
        rows = 4
        for r in range(rows):
            yy = wall_top + r * wall_h / rows
            off = 0 if r % 2 else 18
            x = xl - 4 + off
            pygame.draw.line(self.surf, T["stone_d"], self.p(xl - 4, yy), self.p(xr + 4, yy), int(1.5 * RS))
            while x < xr:
                pygame.draw.line(self.surf, T["stone_d"], self.p(x, yy), self.p(x, yy + wall_h / rows), int(1.5 * RS))
                x += 36
        n_arch = max(2, int(width // 230))
        for k in range(n_arch):
            ax = xl + width * (k + 0.5) / n_arch
            if abs(ax - mid) < 60 and n_arch % 2:
                continue
            aw = 64
            arch = [(ax - aw / 2, wall_top + wall_h + 2), (ax - aw / 2, wall_top + 26)]
            arch += [(ax + math.cos(a) * aw / 2, wall_top + 26 - math.sin(a) * 18) for a in
                     (math.pi - i * math.pi / 10 for i in range(11))]
            arch += [(ax + aw / 2, wall_top + wall_h + 2)]
            self.poly(arch, (24, 20, 38), 3)
            self.poly([(ax - aw / 2 - 5, wall_top + 24), (ax - aw / 2 + 4, wall_top + 24), (ax - aw / 2 + 4, wall_top + wall_h),
                       (ax - aw / 2 - 5, wall_top + wall_h)], T["stone_d"], 1.5)
            self.poly([(ax + aw / 2 - 4, wall_top + 24), (ax + aw / 2 + 5, wall_top + 24), (ax + aw / 2 + 5, wall_top + wall_h),
                       (ax + aw / 2 - 4, wall_top + wall_h)], T["stone_d"], 1.5)
        for cx in (xl - 4, xr - 10):
            self.rect(cx, wall_top - 2, 14, wall_h + 4, T["trim"], 2)
            self.rect(cx + 3, wall_top + 8, 8, 8, lighten(T["trim"], 0.3), 1.2)
        self.rect(xl - 8, y - 4, width + 16, 12, lighten(T["stone"], 0.1), 2.5, 3)
        self.banner(mid, wall_top + 4, 46, 88)
        for side in (-1, 1):
            cx = mid + side * width * 0.36
            self.banner(cx, wall_top + 4, 30, 58)
        self.grass_top(xl - 4, xr + 4, y)
        self.vines(xl, xr, y + 8, 12)
        for px, broken in ((xl + 22, False), (xr - 22, True)):
            h = 110 if not broken else 90
            body = pygame.Rect(*self.p(px - 13, y - 6 - h), 26 * RS, h * RS)
            pygame.draw.rect(self.surf, (14, 10, 26), body.move(6 * RS, 4 * RS))
            pygame.draw.rect(self.surf, lighten(T["stone"], 0.12), body)
            pygame.draw.rect(self.surf, T["stone_d"], (body.x, body.y, body.w * 0.35, body.h))
            pygame.draw.rect(self.surf, OUTLINE, body, int(2.5 * RS))
            if broken:
                self.poly([(px - 14, y - 6 - h), (px - 5, y - 18 - h), (px + 2, y - 8 - h), (px + 9, y - 20 - h),
                           (px + 14, y - 8 - h)], lighten(T["stone"], 0.12), 2.5)
            else:
                self.rect(px - 19, y - 18 - h, 38, 12, lighten(T["stone"], 0.2), 2.5, 2)
            self.poly([(px - 10, y - 50), (px + 10, y - 50), (px + 6, y - 42), (px - 6, y - 42)], (80, 62, 52), 2)
            self.fx.append(("fire", px, y - 50, 0))

    def _soft(self, xl, xr, y, idx):
        T = self.T
        th = self.theme
        mid = (xl + xr) / 2
        width = xr - xl
        if th == "harbor":
            if width > 220:                                     # red bridge
                self.poly([(xl, y - 3), (xr, y - 3), (xr, y + 9), (xl, y + 9)], T["wood"], 2.2)
                for k in range(int(width // 40) + 1):
                    px = xl + k * width / int(width // 40)
                    self.rect(px - 3, y - 30, 6, 28, T["red"], 1.8)
                    self.rect(px - 5, y - 34, 10, 6, T["trim"], 1.5, 2)
                self.rect(xl, y - 28, width, 5, T["red"], 1.8)
                for k in (0.25, 0.75):
                    self.fx.append(("lantern", xl + width * k, y + 26, 0))
                    pygame.draw.line(self.surf, OUTLINE, self.p(xl + width * k, y + 9), self.p(xl + width * k, y + 18), int(1.5 * RS))
                return
            roof = [(xl - 22, y + 18), (xl - 8, y + 4), (xl + 6, y - 2), (xr - 6, y - 2), (xr + 8, y + 4), (xr + 22, y + 18),
                    (xr + 6, y + 14), (xl - 6, y + 14)]
            self.poly(roof, (40, 46, 82), 2.5)
            for k in range(int(width // 14) + 3):
                px = xl - 14 + k * 14
                pygame.draw.line(self.surf, (70, 78, 120), self.p(px, y), self.p(px - 4, y + 14), int(1.5 * RS))
            self.rect(xl + 4, y + 14, width - 8, 9, T["red"], 2)
            self.rect(xl - 2, y - 5, width + 4, 6, (90, 96, 140), 2, 2)
            self.fx.append(("lantern", mid, y + 36, 0))
            pygame.draw.line(self.surf, OUTLINE, self.p(mid, y + 23), self.p(mid, y + 28), int(1.5 * RS))
            return
        is_ledge = xl < 230 or xr > 1050
        if is_ledge:
            rock = [(xl - 4, y + 4), (xr + 4, y + 4), (xr - 8, y + 30), (xr - 24, y + 58), (mid + 6, y + 86),
                    (mid - 18, y + 64), (xl + 10, y + 38)]
            self.rock_body(rock, y + 4)
            self.grass_top(xl - 2, xr + 2, y, 9)
            bx = xl + 26 if mid < 640 else xr - 26
            pygame.draw.rect(self.surf, (14, 10, 26), (*self.p(bx - 8 + 4, y - 66 + 3), 16 * RS, 60 * RS))
            self.rect(bx - 8, y - 66, 16, 60, lighten(T["stone"], 0.12), 2.2)
            self.rect(bx - 12, y - 72, 24, 8, lighten(T["stone"], 0.2), 2.2, 2)
            self.banner(bx, y - 60, 18, 34)
            tx = xr - 30 if mid < 640 else xl + 30
            for dx, dy, r in ((0, -16, 15), (-12, -8, 11), (12, -8, 11)):
                pygame.draw.circle(self.surf, darken(T["moss"], 0.15), self.p(tx + dx, y + dy), r * RS)
                pygame.draw.circle(self.surf, T["moss_l"], self.p(tx + dx - 3, y + dy - 4), r * 0.45 * RS)
            pygame.draw.circle(self.surf, OUTLINE, self.p(tx, y - 16), 15 * RS, int(2 * RS))
            return
        top = idx == max(range(len(self.mp["platforms"])), key=lambda i: -self.mp["platforms"][i][2])
        under = [(xl + 8, y + 12), (xr - 8, y + 12), (xr - 26, y + 30), (mid + 10, y + 48), (mid - 12, y + 42), (xl + 24, y + 28)]
        self.poly(under, T["rock"][2], 2.5)
        self.rect(xl, y - 2, width, 16, T["stone"] if not top else lighten(T["stone"], 0.1), 2.5, 4)
        for k in range(1, int(width // 30)):
            px = xl + k * 30
            pygame.draw.line(self.surf, T["stone_d"], self.p(px, y + 4), self.p(px, y + 13), int(1.5 * RS))
        for ex in (xl, xr):
            self.poly([(ex - 6, y - 4), (ex + 6, y - 4), (ex + 8, y + 16), (ex - 8, y + 16)], T["trim"], 2)
        self.grass_top(xl + 2, xr - 2, y, 7)
        self.vines(xl, xr, y + 10, 3)
        self.fx.append(("rune", mid, y + 30, 0))
        if top:
            self.banner(mid, y + 16, 26, 44)

    def scaled(self, zoom):
        img = self._scaled.get(zoom)
        if img is None:
            w = int(self.surf.get_width() * zoom / RS)
            h = int(self.surf.get_height() * zoom / RS)
            img = pygame.transform.smoothscale(self.surf, (w, h))
            if pygame.display.get_surface() is not None:
                img = img.convert_alpha()
            self._scaled[zoom] = img
        return img

    def draw(self, surf, cam, t):
        surf.blit(self.scaled(cam.zoom), cam.to_screen(self.x0, self.y0))

    def draw_fx(self, surf, cam, t):
        ts = cam.to_screen
        z = cam.zoom
        T = self.T
        for kind, x, y, h in self.fx:
            if kind == "crystal":
                glow(surf, T["crystal"], ts(x, y), h * 2.4 * z, 80 + 30 * math.sin(t * 2 + x))
            elif kind == "rune":
                glow(surf, T["crystal"], ts(x, y), 26 * z, int(70 + 40 * math.sin(t * 3 + x)))
            elif kind == "lantern":
                c = ts(x, y)
                fl = 0.85 + 0.15 * math.sin(t * 7 + x)
                glow(surf, (255, 150, 70), c, 46 * z * fl, 130)
                r = pygame.Rect(0, 0, 13 * z, 17 * z)
                r.center = c
                pygame.draw.ellipse(surf, (230, 60, 50), r)
                pygame.draw.ellipse(surf, (255, 200, 120), r.inflate(-6 * z, -8 * z))
                pygame.draw.ellipse(surf, OUTLINE, r, max(1, int(2 * z)))
            elif kind == "fire":
                base = ts(x, y)
                c0, c1 = T["fire"]
                glow(surf, c0, (base[0], base[1] - 8 * z), 66 * z, 110 + 30 * math.sin(t * 9 + x))
                for i, (c, sc) in enumerate(((c0, 1.0), (c1, 0.62), ((255, 255, 235), 0.3))):
                    hh = 24 * sc * (1 + math.sin(t * 17 + x + i) * 0.15) * z
                    ww = 10 * sc * z
                    pygame.draw.polygon(surf, c, [(base[0] - ww, base[1]), (base[0] + ww, base[1]),
                                                  (base[0] + math.sin(t * 11 + i) * 2 * z, base[1] - hh)])
        lc = T["moss_l"]
        for gx, gy, gh in self.grass:
            sway = math.sin(t * 2.4 + gx * 0.05) * 2.2
            pygame.draw.line(surf, lc, ts(gx, gy), ts(gx + sway, gy - gh), max(1, int(1.6 * z)))


_stage_cache = {}


def stage_art(map_id):
    st = _stage_cache.get(map_id)
    if st is None:
        st = _stage_cache[map_id] = StageArt(map_id)
    return st


_backdrops = {}


def backdrop(map_id, w, h):
    bd = _backdrops.get(map_id)
    if bd is None:
        bd = _backdrops[map_id] = Backdrop(map_id, w, h)
    return bd


_thumbs = {}


def thumbnail(map_id, w, h):
    key = (map_id, w, h)
    img = _thumbs.get(key)
    if img is None:
        mp = M.get(map_id)
        path = os.path.join(ASSET_DIR, mp["bg"]) if mp.get("bg") else None
        img = pygame.Surface((w, h))
        if path and os.path.isfile(path):
            src = pygame.image.load(path)
            sc = max(w / src.get_width(), h / src.get_height())
            big = pygame.transform.smoothscale(src, (int(src.get_width() * sc) + 1, int(src.get_height() * sc) + 1))
            img.blit(big, ((w - big.get_width()) / 2, (h - big.get_height()) / 2))
        else:
            img.fill((60, 50, 90))
        if pygame.display.get_surface() is not None:
            img = img.convert()
        _thumbs[key] = img
    return img
