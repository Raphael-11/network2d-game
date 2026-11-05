"""High-detail comic portraits and head sprites.

Everything is drawn once at high resolution with layered cel shading (shapes
clipped to the face / helmet / hair), thick ink outlines and highlights, then
smooth-scaled down and cached. The same head art is reused in battle, so the
fighters on the stage have the same faces as the select screen.

Head-local coordinates: u to the right, v down, in units of the head radius R.
Heads are drawn in a 3/4 view facing right; callers flip for facing left.
"""
import math
import random

import pygame

OUTLINE = (18, 14, 26)


def lighten(c, t):
    return tuple(int(v + (255 - v) * t) for v in c[:3])


def darken(c, t):
    return tuple(int(v * (1 - t)) for v in c[:3])


def mix(a, b, t):
    return tuple(int(x + (y - x) * t) for x, y in zip(a[:3], b[:3]))


def skin_shadow(c):
    return mix(darken(c, 0.2), (120, 50, 80), 0.18)


def bez(*cp, n=14):
    """Bezier curve through control points (any degree), as a list of points."""
    out = []
    for i in range(n + 1):
        t = i / n
        pts = list(cp)
        while len(pts) > 1:
            pts = [(a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t) for a, b in zip(pts, pts[1:])]
        out.append(pts[0])
    return out


def path(*segs, n=14):
    """Join bezier segments; each segment's first point is the previous end."""
    out = []
    for seg in segs:
        pts = bez(*seg, n=n)
        out.extend(pts if not out else pts[1:])
    return out


def ellipse_pts(u, v, rw, rh, rot=0.0, n=28):
    c, s = math.cos(rot), math.sin(rot)
    return [(u + rw * math.cos(a) * c - rh * math.sin(a) * s, v + rw * math.cos(a) * s + rh * math.sin(a) * c)
            for a in (i * math.tau / n for i in range(n))]


class Ink:
    """A high-res drawing canvas with comic-ink helpers in head units."""

    def __init__(self, w, h, cx, cy, R, ow=None):
        self.s = pygame.Surface((w, h), pygame.SRCALPHA)
        self.w, self.h, self.cx, self.cy, self.R = w, h, cx, cy, R
        self.ow = ow or max(3, int(R * 0.065))

    def P(self, u, v):
        return (self.cx + u * self.R, self.cy + v * self.R)

    def pts(self, uv):
        return [self.P(u, v) for u, v in uv]

    def _ink(self, pts, w, col, closed):
        if len(pts) < 2:
            return
        pygame.draw.lines(self.s, col, closed, pts, w)
        r = w / 2 - 0.5
        if r >= 1:
            for p in pts:
                pygame.draw.circle(self.s, col, p, r)

    def poly(self, uv, fill, ow=None, out=OUTLINE):
        pts = self.pts(uv)
        if fill is not None:
            pygame.draw.polygon(self.s, fill, pts)
        ow = self.ow if ow is None else ow
        if ow:
            self._ink(pts, ow, out, True)

    def line(self, uv, col=OUTLINE, w=None):
        self._ink(self.pts(uv), w or self.ow, col, False)

    def circle(self, u, v, r, fill, ow=None, out=OUTLINE):
        self.poly(ellipse_pts(u, v, r, r), fill, ow, out)

    def ellipse(self, u, v, rw, rh, fill, ow=None, rot=0.0, out=OUTLINE):
        self.poly(ellipse_pts(u, v, rw, rh, rot), fill, ow, out)

    def clip(self, clip_uv, shape_uv, col):
        """Fill shape_uv, but only where it overlaps clip_uv (cel shading)."""
        sp = self.pts(shape_uv)
        cp = self.pts(clip_uv)
        x0 = max(0, int(min(p[0] for p in sp)) - 2)
        y0 = max(0, int(min(p[1] for p in sp)) - 2)
        x1 = min(self.w, int(max(p[0] for p in sp)) + 3)
        y1 = min(self.h, int(max(p[1] for p in sp)) + 3)
        if x1 <= x0 or y1 <= y0:
            return
        layer = pygame.Surface((x1 - x0, y1 - y0), pygame.SRCALPHA)
        pygame.draw.polygon(layer, col, [(x - x0, y - y0) for x, y in sp])
        mask = pygame.Surface((x1 - x0, y1 - y0), pygame.SRCALPHA)
        pygame.draw.polygon(mask, (255, 255, 255, 255), [(x - x0, y - y0) for x, y in cp])
        layer.blit(mask, (0, 0), special_flags=pygame.BLEND_RGBA_MIN)
        self.s.blit(layer, (x0, y0))

    def hatch(self, clip_uv, u0, v0, u1, v1, step=0.09, col=None, w=None):
        """Diagonal ink hatching inside clip_uv, over the box (u0, v0)-(u1, v1)."""
        col = col or (*OUTLINE, 150)
        layer = pygame.Surface((self.w, self.h), pygame.SRCALPHA)
        u = u0 - (v1 - v0)
        while u < u1:
            pygame.draw.line(layer, col, self.P(u, v1), self.P(u + (v1 - v0), v0), w or max(1, self.ow // 3))
            u += step
        mask = pygame.Surface((self.w, self.h), pygame.SRCALPHA)
        pygame.draw.polygon(mask, (255, 255, 255, 255), self.pts(clip_uv))
        layer.blit(mask, (0, 0), special_flags=pygame.BLEND_RGBA_MIN)
        self.s.blit(layer, (0, 0))

    def glow(self, u, v, r, col, alpha=120):
        rr = int(r * self.R)
        g = pygame.Surface((rr * 2, rr * 2), pygame.SRCALPHA)
        for i in range(rr, 0, -max(1, rr // 14)):
            a = int(alpha * (1 - i / rr) ** 1.5)
            pygame.draw.circle(g, (*col[:3], a), (rr, rr), i)
        x, y = self.P(u, v)
        self.s.blit(g, (x - rr, y - rr))


# ---- shared face parts -------------------------------------------------------
FACE = {
    "normal": [((0.05, -1.02), (0.82, -1.0), (0.97, -0.3)), ((0.97, -0.3), (1.02, 0.3), (0.72, 0.78)),
               ((0.72, 0.78), (0.45, 1.1), (0.12, 1.12)), ((0.12, 1.12), (-0.42, 1.08), (-0.76, 0.6)),
               ((-0.76, 0.6), (-1.0, 0.15), (-0.93, -0.35)), ((-0.93, -0.35), (-0.78, -1.0), (0.05, -1.02))],
    "square": [((0.05, -1.02), (0.85, -1.0), (0.99, -0.3)), ((0.99, -0.3), (1.04, 0.35), (0.8, 0.82)),
               ((0.8, 0.82), (0.62, 1.2), (0.12, 1.22)), ((0.12, 1.22), (-0.52, 1.2), (-0.82, 0.72)),
               ((-0.82, 0.72), (-1.02, 0.15), (-0.95, -0.35)), ((-0.95, -0.35), (-0.8, -1.0), (0.05, -1.02))],
    "soft": [((0.05, -1.02), (0.8, -1.0), (0.95, -0.3)), ((0.95, -0.3), (0.98, 0.3), (0.68, 0.74)),
             ((0.68, 0.74), (0.42, 1.04), (0.18, 1.1)), ((0.18, 1.1), (-0.32, 1.02), (-0.72, 0.56)),
             ((-0.72, 0.56), (-0.98, 0.12), (-0.92, -0.35)), ((-0.92, -0.35), (-0.76, -1.0), (0.05, -1.02))],
}
LEFT_SHADOW = [(-1.4, -1.4), (-0.5, -1.4), (-0.6, -0.5), (-0.64, 0.25), (-0.38, 0.88), (0.05, 1.4), (-1.4, 1.4)]
JAW_SHADOW = [(-1.4, 0.98), (-0.2, 1.02), (0.5, 0.86), (1.4, 0.62), (1.4, 1.5), (-1.4, 1.5)]


def face_base(ink, L, jaw="normal", ear=True):
    skin = L["skin"]
    sh = skin_shadow(skin)
    face = path(*FACE[jaw])
    ink.poly([(-0.42, 0.55), (0.38, 0.62), (0.42, 1.75), (-0.5, 1.75)], skin)
    ink.clip([(-0.42, 0.55), (0.38, 0.62), (0.42, 1.75), (-0.5, 1.75)],
             [(-0.6, 0.5), (0.6, 0.5), (0.6, 1.3), (-0.6, 1.1)], sh)
    if ear:
        ear_pts = ellipse_pts(-0.86, 0.12, 0.2, 0.3, -0.2)
        ink.poly(ear_pts, skin)
        ink.line(bez((-0.8, -0.05), (-0.95, 0.1), (-0.82, 0.3)), darken(sh, 0.15), max(2, ink.ow // 2))
    ink.poly(face, skin)
    ink.clip(face, LEFT_SHADOW, sh)
    ink.clip(face, JAW_SHADOW, sh)
    ink.clip(face, ellipse_pts(0.62, 0.32, 0.22, 0.14), lighten(skin, 0.28))
    ink.clip(face, ellipse_pts(0.25, -0.62, 0.35, 0.16), lighten(skin, 0.22))
    ink.poly(face, None)
    return face


def nose(ink, L, big=False):
    sh = skin_shadow(L["skin"])
    k = 1.25 if big else 1.0
    ink.poly([(0.2, -0.02), (0.36 * k, 0.32), (0.18, 0.38), (0.12, 0.3)], sh, 0)
    ink.line(bez((0.2, -0.04), (0.28, 0.18), (0.38 * k, 0.32), (0.28, 0.4)), OUTLINE, max(2, ink.ow * 2 // 3))
    ink.line(bez((0.12, 0.36), (0.16, 0.42), (0.22, 0.4)), OUTLINE, max(2, ink.ow // 2))


def eye(ink, u, v, w, h, iris, lashes=False, narrow=False, glow=False, slit=False, sclera=(255, 255, 255)):
    if narrow:
        h *= 0.62
    upper = bez((u - w / 2, v), (u - w * 0.05, v - h * 1.2), (u + w / 2, v - h * 0.2))
    lower = bez((u + w / 2, v - h * 0.2), (u + w * 0.05, v + h * 0.9), (u - w / 2, v))
    shape = upper + lower[1:]
    if glow:
        ink.glow(u, v, w * 1.1, iris, 150)
    ink.poly(shape, sclera, 0)
    ink.clip(shape, [(u - w, v - h * 2), (u + w, v - h * 2), (u + w, v - h * 0.35), (u - w, v - h * 0.6)],
             mix(sclera, (120, 120, 170), 0.35))
    ir = h * (0.62 if not narrow else 0.95)
    ic = (u + w * 0.08, v - h * 0.02)
    ink.clip(shape, ellipse_pts(ic[0], ic[1], ir, ir * 1.05), darken(iris, 0.25))
    ink.clip(shape, ellipse_pts(ic[0], ic[1] + ir * 0.18, ir * 0.78, ir * 0.78), iris)
    ink.clip(shape, ellipse_pts(ic[0], ic[1] + ir * 0.45, ir * 0.55, ir * 0.35), lighten(iris, 0.45))
    if slit:
        ink.clip(shape, ellipse_pts(ic[0], ic[1], ir * 0.18, ir * 0.9), OUTLINE)
    else:
        ink.clip(shape, ellipse_pts(ic[0], ic[1], ir * 0.42, ir * 0.42), OUTLINE)
    ink.circle(ic[0] + ir * 0.32, ic[1] - ir * 0.35, ir * 0.24, (255, 255, 255), 0)
    ink.circle(ic[0] - ir * 0.3, ic[1] + ir * 0.35, ir * 0.12, (255, 255, 255), 0)
    ink.line(upper, OUTLINE, int(ink.ow * 1.5))
    ink.line(lower[2:-3], darken(iris, 0.5) if not narrow else OUTLINE, max(2, ink.ow // 2))
    if lashes:
        end = upper[-1]
        ink.line([end, (end[0] + w * 0.28, end[1] - h * 0.45)], OUTLINE, ink.ow)
        ink.line([upper[-4], (upper[-4][0] + w * 0.18, upper[-4][1] - h * 0.62)], OUTLINE, max(2, ink.ow * 2 // 3))


def brow(ink, inner, outer, thick, col, arch=0.0):
    (ui, vi), (uo, vo) = inner, outer
    mid = ((ui + uo) / 2, (vi + vo) / 2 - arch)
    top = bez((ui, vi - thick), (mid[0], mid[1] - thick), (uo, vo))
    bot = bez((uo, vo), (mid[0], mid[1] + thick * 0.2), (ui, vi + thick * 0.35))
    ink.poly(top + bot[1:], col, max(2, ink.ow // 2))


def mouth(ink, kind, L):
    if kind == "grin":
        top = bez((-0.12, 0.6), (0.25, 0.66), (0.62, 0.5))
        bot = bez((0.62, 0.5), (0.35, 0.95), (-0.12, 0.6))
        shape = top + bot[1:]
        ink.poly(shape, (110, 20, 30), 0)
        ink.clip(shape, [(-0.3, 0.4), (0.8, 0.4), (0.8, 0.66), (-0.3, 0.7)], (252, 250, 240))
        ink.clip(shape, ellipse_pts(0.25, 0.86, 0.25, 0.12), (230, 90, 110))
        for x in (0.08, 0.26, 0.44):
            ink.clip(shape, [(x - 0.008, 0.5), (x + 0.008, 0.5), (x + 0.008, 0.68), (x - 0.008, 0.68)], (200, 196, 190))
        ink.poly(shape, None)
        ink.line(bez((0.62, 0.5), (0.7, 0.46), (0.72, 0.4)), OUTLINE, max(2, ink.ow // 2))
    elif kind == "shout":
        shape = ellipse_pts(0.22, 0.72, 0.32, 0.24, 0.12)
        ink.poly(shape, (100, 18, 28), 0)
        ink.clip(shape, [(-0.2, 0.4), (0.7, 0.4), (0.7, 0.6), (-0.2, 0.62)], (252, 250, 240))
        ink.clip(shape, [(-0.2, 0.86), (0.7, 0.82), (0.7, 1.1), (-0.2, 1.1)], (240, 236, 228))
        ink.clip(shape, ellipse_pts(0.24, 0.84, 0.18, 0.08), (220, 80, 100))
        ink.poly(shape, None)
    elif kind == "smirk":
        ink.line(bez((-0.05, 0.66), (0.25, 0.7), (0.55, 0.56), (0.62, 0.48)), OUTLINE, int(ink.ow * 1.1))
        ink.line(bez((0.6, 0.44), (0.66, 0.5), (0.62, 0.58)), OUTLINE, max(2, ink.ow // 2))
        ink.line(bez((0.1, 0.8), (0.25, 0.84), (0.38, 0.79)), skin_shadow(L["skin"]), max(2, ink.ow // 2))
    elif kind == "calm":
        ink.poly(bez((0.0, 0.66), (0.25, 0.6), (0.5, 0.65)) + bez((0.5, 0.65), (0.25, 0.8), (0.0, 0.66))[1:],
                 L.get("lip", (210, 110, 120)), max(2, ink.ow // 2))
        ink.line(bez((0.0, 0.66), (0.25, 0.7), (0.5, 0.65)), OUTLINE, max(2, ink.ow * 2 // 3))
    elif kind == "stern":
        ink.line(bez((0.0, 0.66), (0.25, 0.64), (0.52, 0.68)), OUTLINE, int(ink.ow * 1.1))
        ink.line(bez((0.12, 0.8), (0.25, 0.83), (0.38, 0.8)), skin_shadow(L["skin"]), max(2, ink.ow // 2))


def hair_strands(ink, base_uv, col, count, u0, u1, v0, v1, seed, w=None):
    """Ink strand lines + highlights clipped into a hair mass."""
    rng = random.Random(seed)
    for _ in range(count):
        u = rng.uniform(u0, u1)
        v = rng.uniform(v0, v1)
        du, dv = rng.uniform(-0.15, 0.15), rng.uniform(0.25, 0.6)
        pts = bez((u, v), (u + du, v + dv * 0.5), (u + du * 2, v + dv))
        layer_col = darken(col, 0.35) if rng.random() < 0.6 else lighten(col, 0.4)
        ink.clip(base_uv, _thick_line(pts, (w or 0.022) * rng.uniform(0.7, 1.3)), layer_col)


def _thick_line(pts, w):
    left, right = [], []
    for i, (x, y) in enumerate(pts):
        a = pts[max(0, i - 1)]
        b = pts[min(len(pts) - 1, i + 1)]
        dx, dy = b[0] - a[0], b[1] - a[1]
        ln = math.hypot(dx, dy) or 1
        nx, ny = -dy / ln, dx / ln
        k = w * (1 - abs(i / (len(pts) - 1) - 0.4))
        left.append((x + nx * k, y + ny * k))
        right.append((x - nx * k, y - ny * k))
    return left + right[::-1]


def metal(ink, shape, base, hi=True):
    ink.poly(shape, base, 0)
    xs = [p[0] for p in shape]
    ys = [p[1] for p in shape]
    u0, u1, v0, v1 = min(xs), max(xs), min(ys), max(ys)
    ink.clip(shape, [(u0 - 1, v0 - 1), (u0 + (u1 - u0) * 0.38, v0 - 1), (u0 + (u1 - u0) * 0.3, v1 + 1), (u0 - 1, v1 + 1)],
             darken(base, 0.25))
    if hi:
        ink.clip(shape, [(u0 + (u1 - u0) * 0.58, v0 - 1), (u0 + (u1 - u0) * 0.7, v0 - 1),
                         (u0 + (u1 - u0) * 0.64, v1 + 1), (u0 + (u1 - u0) * 0.52, v1 + 1)], lighten(base, 0.5))
    ink.poly(shape, None)


def rivets(ink, pts, r, col):
    for u, v in pts:
        ink.circle(u, v, r, lighten(col, 0.25), max(2, ink.ow // 2))
        ink.circle(u + r * 0.25, v - r * 0.25, r * 0.35, lighten(col, 0.7), 0)


# ---- per-fighter heads -----------------------------------------------------------
def head_ragnar(ink, L, t=0.0):
    face_base(ink, L, "square")
    eye(ink, 0.44, -0.02, 0.36, 0.22, L["eye"])
    eye(ink, -0.22, -0.02, 0.27, 0.2, L["eye"])
    brow(ink, (0.14, -0.14), (0.72, -0.34), 0.13, darken(L["hair"], 0.25), 0.03)
    brow(ink, (0.02, -0.14), (-0.42, -0.3), 0.11, darken(L["hair"], 0.25))
    nose(ink, L, big=True)
    beard = path(((-0.86, 0.22), (-0.7, 0.5), (-0.55, 0.45)), ((-0.55, 0.45), (-0.2, 0.42), (0.0, 0.55)),
                 ((0.0, 0.55), (0.35, 0.4), (0.7, 0.42)), ((0.7, 0.42), (0.92, 0.3), (1.0, 0.15)),
                 ((1.0, 0.15), (1.1, 0.9), (0.75, 1.5)), ((0.75, 1.5), (0.6, 1.95), (0.35, 1.7)),
                 ((0.35, 1.7), (0.2, 2.15), (-0.05, 1.8)), ((-0.05, 1.8), (-0.35, 2.05), (-0.42, 1.6)),
                 ((-0.42, 1.6), (-0.8, 1.55), (-0.86, 0.22)))
    ink.poly(beard, L["hair"], 0)
    ink.clip(beard, [(-1.2, 0), (-0.25, 0), (-0.1, 2.3), (-1.2, 2.3)], darken(L["hair"], 0.22))
    hair_strands(ink, beard, L["hair"], 26, -0.7, 0.85, 0.5, 1.6, 3, 0.03)
    ink.poly(beard, None)
    shape = ellipse_pts(0.25, 0.86, 0.26, 0.2, 0.1)
    ink.poly(shape, (90, 16, 26), 0)
    ink.clip(shape, [(-0.1, 0.6), (0.6, 0.6), (0.6, 0.8), (-0.1, 0.8)], (250, 248, 238))
    ink.poly(shape, None)
    stache = path(((-0.1, 0.56), (0.25, 0.42), (0.68, 0.5)), ((0.68, 0.5), (0.88, 0.75), (0.82, 0.98)),
                  ((0.82, 0.98), (0.65, 0.7), (0.3, 0.64)), ((0.3, 0.64), (-0.05, 0.75), (-0.22, 0.95)),
                  ((-0.22, 0.95), (-0.25, 0.68), (-0.1, 0.56)))
    ink.poly(stache, lighten(L["hair"], 0.1), 0)
    hair_strands(ink, stache, L["hair"], 10, -0.2, 0.8, 0.5, 0.8, 9, 0.02)
    ink.poly(stache, None)
    dome = path(((-1.05, -0.32), (-1.1, -1.25), (0.05, -1.3)), ((0.05, -1.3), (1.15, -1.25), (1.08, -0.32)))
    dome += [(1.08, -0.32), (-1.05, -0.32)]
    for side in (-1, 1):
        horn = path(((side * 0.85, -0.7), (side * 1.55, -0.85), (side * 1.75, -1.55)),
                    ((side * 1.75, -1.55), (side * 1.8, -1.95), (side * 1.55, -2.2)),
                    ((side * 1.55, -2.2), (side * 1.55, -1.75), (side * 1.35, -1.45)),
                    ((side * 1.35, -1.45), (side * 1.2, -1.15), (side * 0.78, -1.05)))
        ink.poly(horn, (240, 230, 204), 0)
        ink.clip(horn, [(side * 0.7, -0.9), (side * 2, -0.9), (side * 2, -0.6), (side * 0.7, -0.6)], (200, 186, 156))
        for k in range(4):
            vv = -0.95 - k * 0.25
            ink.clip(horn, [(side * 0.7, vv), (side * 2.0, vv - 0.1), (side * 2.0, vv - 0.06), (side * 0.7, vv + 0.04)],
                     (176, 160, 130))
        ink.clip(horn, [(side * 1.4, -2.3), (side * 1.9, -2.3), (side * 1.9, -1.75), (side * 1.4, -1.75)], (90, 76, 64))
        ink.poly(horn, None)
    metal(ink, dome, L["metal"])
    band = [(-1.12, -0.48), (1.15, -0.48), (1.15, -0.28), (-1.12, -0.28)]
    metal(ink, band, darken(L["metal"], 0.12), hi=False)
    ink.poly(band, None)
    ink.line([(0.05, -1.28), (0.05, -0.5)], darken(L["metal"], 0.4), max(2, ink.ow // 2))
    guard = [(0.15, -0.3), (0.32, -0.3), (0.3, 0.12), (0.22, 0.18), (0.16, 0.12)]
    metal(ink, guard, darken(L["metal"], 0.05), hi=False)
    rivets(ink, [(-0.85, -0.38), (-0.4, -0.38), (0.55, -0.38), (0.95, -0.38)], 0.05, L["metal"])


def head_kira(ink, L, t=0.0):
    hood = path(((-1.25, 0.4), (-1.35, -1.3), (0.0, -1.32)), ((0.0, -1.32), (1.25, -1.3), (1.18, 0.1)),
                ((1.18, 0.1), (1.0, 1.0), (0.4, 1.3)), ((0.4, 1.3), (-0.6, 1.4), (-1.25, 0.4)))
    for k, dv in enumerate((-0.25, 0.05)):
        tail = path(((-1.05, -0.42 + dv), (-1.6, -0.6 + dv), (-2.1, -0.2 + dv * 2 + k * 0.2)),
                    ((-2.1, -0.2 + dv * 2 + k * 0.2), (-1.65, -0.3 + dv), (-1.05, -0.28 + dv)))
        ink.poly(tail, L["secondary"])
        ink.clip(tail, [(-2.2, -1), (-1.5, -1), (-1.5, 1), (-2.2, 1)], darken(L["secondary"], 0.25))
    ink.poly(hood, L["primary"], 0)
    ink.clip(hood, [(-1.5, -1.5), (-0.55, -1.5), (-0.6, 1.5), (-1.5, 1.5)], darken(L["primary"], 0.35))
    for k in range(3):
        ink.line(bez((-1.05 + k * 0.12, -0.9), (-1.1 + k * 0.1, 0.0), (-0.85 + k * 0.08, 0.9)),
                 lighten(L["primary"], 0.15), max(2, ink.ow // 2))
    ink.poly(hood, None)
    opening = path(((-0.72, -0.6), (0.1, -0.8), (0.95, -0.55)), ((0.95, -0.55), (1.05, 0.2), (0.85, 0.3)),
                   ((0.85, 0.3), (0.0, 0.3), (-0.75, 0.25)), ((-0.75, 0.25), (-0.85, -0.2), (-0.72, -0.6)))
    ink.poly(opening, L["skin"], 0)
    ink.clip(opening, LEFT_SHADOW, skin_shadow(L["skin"]))
    ink.clip(opening, [(-1, -0.7), (1.1, -0.7), (1.1, -0.42), (-1, -0.42)], skin_shadow(L["skin"]))
    ink.poly(opening, None)
    eye(ink, 0.44, -0.08, 0.38, 0.24, L["eye"], narrow=True)
    eye(ink, -0.24, -0.08, 0.28, 0.22, L["eye"], narrow=True)
    brow(ink, (0.12, -0.2), (0.74, -0.34), 0.08, OUTLINE)
    brow(ink, (0.0, -0.2), (-0.44, -0.3), 0.07, OUTLINE)
    ink.line([(-0.36, -0.42), (-0.18, 0.12)], (190, 110, 110), max(2, ink.ow // 2))
    band = path(((-0.98, -0.66), (0.0, -0.86), (1.02, -0.62)), ((1.02, -0.62), (1.05, -0.48), (1.0, -0.4)),
                ((1.0, -0.4), (0.0, -0.62), (-0.98, -0.42)))
    ink.poly(band, L["secondary"], 0)
    ink.clip(band, [(-1.2, -1), (-0.4, -1), (-0.4, 0), (-1.2, 0)], darken(L["secondary"], 0.25))
    ink.poly(band, None)
    plate = [(0.05, -0.82), (0.48, -0.78), (0.46, -0.5), (0.05, -0.56)]
    metal(ink, plate, (200, 204, 214))
    ink.line(bez((0.16, -0.72), (0.27, -0.6), (0.36, -0.72)), OUTLINE, max(2, ink.ow // 2))
    mask = path(((-0.86, 0.2), (0.1, 0.12), (1.0, 0.22)), ((1.0, 0.22), (1.05, 0.8), (0.55, 1.15)),
                ((0.55, 1.15), (-0.2, 1.25), (-0.75, 0.9)), ((-0.75, 0.9), (-0.92, 0.6), (-0.86, 0.2)))
    ink.poly(mask, darken(L["primary"], 0.1), 0)
    ink.clip(mask, [(-1, 0), (-0.25, 0), (0.0, 1.4), (-1, 1.4)], darken(L["primary"], 0.4))
    for k in range(4):
        ink.line(bez((-0.5 + k * 0.32, 0.3), (-0.4 + k * 0.32, 0.65), (-0.45 + k * 0.3, 1.05)),
                 lighten(L["primary"], 0.12), max(2, ink.ow // 2))
    ink.line(bez((0.2, 0.18), (0.42, 0.42), (0.36, 0.62)), darken(L["primary"], 0.5), max(2, ink.ow // 2))
    ink.poly(mask, None)


def head_blaze(ink, L, t=0.0):
    flame_cols = [(196, 40, 22), (246, 96, 30), (255, 170, 40), (255, 232, 120)]
    rng = random.Random(4)
    back = []
    for i in range(9):
        a = math.pi * (1.05 + i * 0.12)
        base_l = (math.cos(a - 0.12) * 0.95, math.sin(a - 0.12) * 0.95)
        base_r = (math.cos(a + 0.12) * 0.95, math.sin(a + 0.12) * 0.95)
        ln = rng.uniform(1.75, 2.25)
        tip = (math.cos(a) * ln + 0.15, math.sin(a) * ln - 0.15)
        back.append(([base_l, ((base_l[0] + tip[0]) / 2 - 0.1, (base_l[1] + tip[1]) / 2), tip, base_r], a))
    for layer, col in enumerate(flame_cols):
        sc = 1 - layer * 0.18
        for pts, a in back:
            shrink = [(p[0] * sc + math.cos(a) * 0.12 * layer, p[1] * sc + math.sin(a) * 0.12 * layer) for p in pts]
            ink.poly(shrink, col, ink.ow if layer == 0 else 0)
    face_base(ink, L, "normal")
    cap = path(((-0.98, -0.05), (-1.05, -1.05), (0.0, -1.12)), ((0.0, -1.12), (1.05, -1.08), (0.98, -0.25)),
               ((0.98, -0.25), (0.6, -0.72), (0.0, -0.7)), ((0.0, -0.7), (-0.6, -0.62), (-0.98, -0.05)))
    ink.poly(cap, flame_cols[1], 0)
    ink.clip(cap, [(-1.2, -1.3), (-0.4, -1.3), (-0.4, 0.2), (-1.2, 0.2)], flame_cols[0])
    hair_strands(ink, cap, flame_cols[2], 14, -0.9, 0.9, -1.1, -0.7, 27, 0.03)
    ink.poly(cap, None)
    rng = random.Random(8)
    for _ in range(9):
        ink.circle(0.55 + rng.uniform(-0.15, 0.15), 0.3 + rng.uniform(-0.08, 0.1), 0.022, darken(L["skin"], 0.3), 0)
    eye(ink, 0.44, 0.0, 0.38, 0.25, L["eye"], glow=True)
    eye(ink, -0.22, 0.0, 0.28, 0.22, L["eye"], glow=True)
    brow(ink, (0.14, -0.2), (0.72, -0.4), 0.09, (170, 50, 20), 0.06)
    brow(ink, (0.02, -0.2), (-0.42, -0.36), 0.08, (170, 50, 20))
    nose(ink, L)
    mouth(ink, "grin", L)
    for i, (u0, ln, ang) in enumerate(((-0.55, 0.7, -0.3), (-0.15, 0.85, 0.15), (0.3, 0.75, 0.5))):
        base = [(u0 - 0.22, -0.82), (u0 + 0.22, -0.92)]
        tip = (u0 + math.sin(ang) * ln, -0.85 + ln * 0.75)
        bang = [base[0], (u0 - 0.05, -0.45), tip, (u0 + 0.12, -0.5), base[1]]
        ink.poly(bang, flame_cols[1])
        ink.clip(bang, [(u0 - 0.3, -0.5), (u0 + 0.4, -0.5), (u0 + 0.4, 0.2), (u0 - 0.3, 0.2)], flame_cols[3])
        ink.poly(bang, None)
    for u, v in ((-1.3, -1.6), (1.2, -1.8), (1.5, -0.6), (-1.6, -0.4)):
        ink.circle(u, v, 0.05, (255, 210, 90), 0)


def head_titan(ink, L, t=0.0):
    base = L["skin"]
    head = [(-0.95, -0.85), (-0.55, -1.12), (0.65, -1.12), (1.02, -0.8), (1.08, 0.5), (0.75, 1.1),
            (-0.35, 1.15), (-0.92, 0.6)]
    ink.poly(head, base, 0)
    ink.clip(head, [(-1.3, -1.3), (-0.45, -1.3), (-0.4, 1.3), (-1.3, 1.3)], darken(base, 0.3))
    ink.clip(head, [(0.55, -1.2), (0.7, -1.2), (0.62, 1.2), (0.48, 1.2)], lighten(base, 0.3))
    ink.poly(head, None)
    plate = [(-0.88, -0.88), (-0.5, -1.06), (0.62, -1.06), (0.98, -0.78), (0.98, -0.42), (-0.88, -0.42)]
    metal(ink, plate, L["metal"])
    rivets(ink, [(-0.6, -0.6), (0.0, -0.62), (0.6, -0.6)], 0.055, L["metal"])
    visor = [(-0.82, -0.28), (1.0, -0.28), (1.0, 0.05), (-0.82, 0.05)]
    ink.poly(visor, (16, 20, 34))
    for u, w in ((-0.25, 0.3), (0.42, 0.42)):
        ink.glow(u + w / 2, -0.12, 0.55, L["eye"], 150)
        ink.poly([(u, -0.18), (u + w, -0.2), (u + w - 0.04, -0.06), (u + 0.02, -0.05)], L["eye"], 0)
        ink.poly([(u + 0.04, -0.15), (u + w * 0.6, -0.16), (u + w * 0.55, -0.12), (u + 0.05, -0.11)],
                 lighten(L["eye"], 0.7), 0)
    grill = [(-0.2, 0.45), (0.8, 0.42), (0.7, 0.92), (-0.1, 0.95)]
    metal(ink, grill, darken(L["metal"], 0.25), hi=False)
    for k in range(5):
        x = -0.05 + k * 0.17
        ink.line([(x, 0.5), (x - 0.02, 0.88)], OUTLINE, max(2, ink.ow // 2))
    ink.poly(grill, None)
    ink.line([(-0.6, 0.2), (-0.4, 0.45), (-0.5, 0.75)], darken(base, 0.5), max(2, ink.ow // 2))
    ink.line([(0.75, 0.15), (0.9, 0.35)], darken(base, 0.5), max(2, ink.ow // 2))
    ink.glow(0.95, -0.9, 0.3, L["secondary"], 90)
    ink.poly([(0.85, -0.98), (0.95, -0.86), (0.85, -0.74), (0.75, -0.86)], L["secondary"], max(2, ink.ow // 2))


def head_vex(ink, L, t=0.0):
    ink.poly([(-0.95, -0.4), (-0.75, -0.4), (-0.7, 0.35), (-0.95, 0.2)], L["hair"])
    face = face_base(ink, L, "square")
    rng = random.Random(5)
    for _ in range(70):
        u, v = rng.uniform(-0.6, 0.95), rng.uniform(0.38, 1.15)
        ink.clip(face, ellipse_pts(u, v, 0.012, 0.012, n=6), darken(L["skin"], 0.35))
    ink.poly([(-0.92, -0.3), (-0.72, -0.32), (-0.68, 0.42), (-0.82, 0.5), (-0.94, 0.1)], L["hair"])
    eye(ink, 0.44, -0.0, 0.36, 0.2, L["eye"], narrow=True)
    eye(ink, -0.22, -0.0, 0.27, 0.18, L["eye"], narrow=True)
    brow(ink, (0.14, -0.2), (0.72, -0.26), 0.08, darken(L["hair"], 0.2), 0.04)
    brow(ink, (0.02, -0.2), (-0.42, -0.24), 0.07, darken(L["hair"], 0.2))
    nose(ink, L)
    mouth(ink, "smirk", L)
    ink.line([(0.52, 0.56), (1.2, 0.4)], (226, 196, 110), max(3, ink.ow * 2 // 3))
    ink.poly([(1.15, 0.36), (1.32, 0.3), (1.25, 0.44)], (236, 210, 120), max(2, ink.ow // 2))
    ink.line([(0.66, -0.3), (0.82, 0.18)], (196, 100, 96), max(2, ink.ow // 2))
    ink.clip(face, [(-1.2, -1.2), (1.2, -1.2), (1.2, -0.22), (-1.2, -0.14)], (*darken(L["skin"], 0.5), 90))
    brim = path(((-1.75, -0.4), (-1.6, -0.75), (-1.1, -0.62)), ((-1.1, -0.62), (0.1, -0.5), (1.15, -0.62)),
                ((1.15, -0.62), (1.7, -0.78), (1.85, -0.42)), ((1.85, -0.42), (1.2, -0.25), (0.1, -0.22)),
                ((0.1, -0.22), (-1.2, -0.25), (-1.75, -0.4)))
    crown = path(((-0.85, -0.55), (-0.95, -1.15), (-0.55, -1.42)), ((-0.55, -1.42), (-0.15, -1.25), (0.1, -1.45)),
                 ((0.1, -1.45), (0.45, -1.3), (0.72, -1.45)), ((0.72, -1.45), (1.05, -1.15), (0.92, -0.55)))
    crown += [(0.92, -0.55), (-0.85, -0.55)]
    hat = L["primary"]
    ink.poly(crown, hat, 0)
    ink.clip(crown, [(-1.2, -1.6), (-0.3, -1.6), (-0.25, 0), (-1.2, 0)], darken(hat, 0.3))
    ink.line(bez((0.1, -1.4), (0.1, -1.0), (0.05, -0.75)), darken(hat, 0.35), max(2, ink.ow // 2))
    ink.poly(crown, None)
    band = [(-0.86, -0.78), (0.93, -0.78), (0.92, -0.58), (-0.85, -0.58)]
    ink.poly(band, darken(hat, 0.45))
    for u in (-0.5, 0.15, 0.7):
        ink.circle(u, -0.68, 0.06, (210, 212, 222), max(2, ink.ow // 2))
    ink.poly(brim, lighten(hat, 0.05), 0)
    ink.clip(brim, [(-2, -1), (-0.6, -1), (-0.6, 0), (-2, 0)], darken(hat, 0.28))
    ink.clip(brim, [(-2, -0.32), (2, -0.42), (2, 0), (-2, 0)], darken(hat, 0.2))
    ink.poly(brim, None)


def head_luna(ink, L, t=0.0):
    hair = L["hair"]
    back = path(((-0.2, -1.12), (-1.25, -1.05), (-1.2, 0.2)), ((-1.2, 0.2), (-1.35, 1.4), (-1.0, 2.4)),
                ((-1.0, 2.4), (-0.4, 2.2), (-0.2, 2.5)), ((-0.2, 2.5), (0.4, 2.0), (0.8, 2.3)),
                ((0.8, 2.3), (1.05, 1.2), (1.05, 0.0)), ((1.05, 0.0), (1.1, -1.1), (-0.2, -1.12)))
    ink.poly(back, darken(hair, 0.12), 0)
    ink.clip(back, [(-1.6, -1.2), (-0.6, -1.2), (-0.6, 2.6), (-1.6, 2.6)], darken(hair, 0.3))
    hair_strands(ink, back, hair, 30, -1.2, 1.0, -0.6, 2.0, 21, 0.025)
    ink.poly(back, None)
    face_base(ink, L, "soft", ear=False)
    ink.clip(path(*FACE["soft"]), ellipse_pts(0.58, 0.42, 0.16, 0.08), (255, 160, 190))
    eye(ink, 0.43, 0.0, 0.38, 0.27, L["eye"], lashes=True)
    eye(ink, -0.22, 0.0, 0.28, 0.23, L["eye"], lashes=True)
    brow(ink, (0.16, -0.24), (0.72, -0.33), 0.05, darken(hair, 0.45), 0.06)
    brow(ink, (0.02, -0.24), (-0.4, -0.3), 0.045, darken(hair, 0.45), 0.04)
    nose(ink, L)
    mouth(ink, "calm", {**L, "lip": (176, 92, 150)})
    ink.circle(0.68, 0.62, 0.025, OUTLINE, 0)
    bangs = path(((-1.0, 0.2), (-1.05, -1.0), (-0.1, -1.1)), ((-0.1, -1.1), (0.9, -1.1), (1.02, -0.2)),
                 ((1.02, -0.2), (0.8, -0.5), (0.68, -0.35)), ((0.68, -0.35), (0.55, -0.62), (0.32, -0.42)),
                 ((0.32, -0.42), (0.1, -0.7), (-0.15, -0.45)), ((-0.15, -0.45), (-0.45, -0.75), (-0.62, -0.25)),
                 ((-0.62, -0.25), (-0.8, -0.05), (-1.0, 0.2)))
    ink.poly(bangs, hair, 0)
    ink.clip(bangs, [(-1.2, -1.2), (-0.45, -1.2), (-0.45, 0.3), (-1.2, 0.3)], darken(hair, 0.2))
    hair_strands(ink, bangs, hair, 16, -0.9, 0.9, -1.0, -0.5, 13, 0.02)
    ink.clip(bangs, path(((-0.3, -0.98), (0.3, -1.05), (0.75, -0.85)), ((0.75, -0.85), (0.3, -0.9), (-0.3, -0.9))),
             (255, 255, 255))
    ink.poly(bangs, None)
    lock = path(((0.82, -0.3), (1.12, 0.4), (0.95, 1.4)), ((0.95, 1.4), (0.85, 1.0), (0.78, 0.2)))
    ink.poly(lock, hair)
    ink.line(bez((-0.95, -0.55), (0.05, -0.75), (1.0, -0.52)), (232, 196, 90), max(3, ink.ow * 2 // 3))
    ink.glow(0.12, -0.72, 0.4, L["secondary"], 150)
    ink.circle(0.12, -0.72, 0.13, (255, 246, 200), max(2, ink.ow // 2))
    ink.circle(0.18, -0.75, 0.11, darken(L["primary"], 0.1), 0)
    ink.circle(-0.95, 0.42, 0.06, L["secondary"], max(2, ink.ow // 2))


def head_rex(ink, L, t=0.0):
    fur = L["skin"]
    light = lighten(fur, 0.38)
    for (u, v) in ((-1.15, -0.4), (-1.25, 0.15), (-1.1, 0.7), (-0.8, 1.1)):
        ink.poly([(u + 0.35, v - 0.38), (u - 0.45, v + 0.05), (u + 0.38, v + 0.34)], darken(L["hair"], 0.15))
    for side, (u0, u1) in ((-1, (-0.75, -0.2)), (1, (0.2, 0.75))):
        ear = [(u0, -0.75), ((u0 + u1) / 2 - 0.15 * side, -1.9), (u1, -0.85)]
        ink.poly(ear, fur)
        ink.poly([(u0 + 0.12, -0.82), ((u0 + u1) / 2 - 0.12 * side, -1.55), (u1 - 0.12, -0.88)], (226, 150, 160), 0)
    head = path(((0.0, -1.0), (0.9, -1.0), (1.0, -0.25)), ((1.0, -0.25), (1.05, 0.6), (0.6, 1.0)),
                ((0.6, 1.0), (-0.2, 1.15), (-0.85, 0.65)), ((-0.85, 0.65), (-1.1, 0.0), (-0.9, -0.55)),
                ((-0.9, -0.55), (-0.7, -1.0), (0.0, -1.0)))
    ink.poly(head, fur, 0)
    ink.clip(head, LEFT_SHADOW, darken(fur, 0.3))
    ink.clip(head, ellipse_pts(0.45, 0.55, 0.55, 0.45), light)
    hair_strands(ink, head, fur, 18, -0.9, 0.8, -0.9, 0.6, 31, 0.025)
    ink.poly(head, None)
    muzzle = path(((0.3, 0.0), (0.9, -0.05), (1.45, 0.12)), ((1.45, 0.12), (1.62, 0.3), (1.5, 0.45)),
                  ((1.5, 0.45), (1.0, 0.5), (0.35, 0.55)))
    ink.poly(muzzle, light, 0)
    ink.clip(muzzle, [(0.2, 0.4), (1.7, 0.36), (1.7, 0.6), (0.2, 0.6)], darken(light, 0.2))
    ink.poly(muzzle, None)
    jaw = path(((0.45, 0.6), (1.0, 0.62), (1.32, 0.65)), ((1.32, 0.65), (1.1, 0.98), (0.55, 0.92)))
    mouth_in = path(((0.4, 0.5), (0.95, 0.52), (1.45, 0.48)), ((1.45, 0.48), (1.3, 0.72), (0.45, 0.72)))
    ink.poly(mouth_in, (110, 20, 30))
    ink.poly(jaw, light)
    for u in (0.62, 0.86, 1.1, 1.3):
        ink.poly([(u - 0.05, 0.5), (u + 0.05, 0.5), (u, 0.62 if u not in (0.62, 1.3) else 0.7)], (252, 250, 238),
                 max(2, ink.ow // 2))
    for u in (0.75, 1.0):
        ink.poly([(u - 0.05, 0.66), (u + 0.05, 0.66), (u, 0.56)], (252, 250, 238), max(2, ink.ow // 2))
    ink.ellipse(1.55, 0.2, 0.14, 0.11, OUTLINE, 0)
    ink.circle(1.58, 0.15, 0.04, (150, 150, 170), 0)
    ink.line(bez((0.55, 0.05), (0.85, -0.02), (1.3, 0.05)), darken(light, 0.35), max(2, ink.ow // 2))
    eye(ink, 0.4, -0.18, 0.34, 0.2, L["eye"], narrow=True, slit=True, sclera=(255, 236, 160))
    eye(ink, -0.25, -0.16, 0.25, 0.18, L["eye"], narrow=True, slit=True, sclera=(255, 236, 160))
    brow(ink, (0.12, -0.3), (0.72, -0.5), 0.1, darken(fur, 0.45), 0.02)
    brow(ink, (0.0, -0.3), (-0.45, -0.46), 0.09, darken(fur, 0.45))
    ink.line([(0.32, -0.62), (0.62, 0.15)], (230, 220, 210), max(3, ink.ow * 2 // 3))
    ink.line([(0.32, -0.62), (0.62, 0.15)], (120, 50, 50), max(2, ink.ow // 3))


def head_aria(ink, L, t=0.0):
    hair = L["hair"]
    back = path(((-0.3, -1.0), (-1.2, -0.9), (-1.15, 0.3)), ((-1.15, 0.3), (-1.1, 1.0), (-0.75, 1.2)),
                ((-0.75, 1.2), (-0.6, 0.4), (-0.3, -1.0)))
    ink.poly(back, darken(hair, 0.15))
    for k in range(5):
        v = 1.0 + k * 0.28
        u = -1.0 + math.sin(k) * 0.05
        ink.ellipse(u, v, 0.16, 0.17, hair if k % 2 else darken(hair, 0.12), max(2, ink.ow * 2 // 3))
    face = face_base(ink, L, "soft", ear=False)
    ink.clip(face, ellipse_pts(0.6, 0.42, 0.16, 0.08), (255, 160, 170))
    eye(ink, 0.43, 0.02, 0.38, 0.25, L["eye"], lashes=True)
    eye(ink, -0.22, 0.02, 0.28, 0.22, L["eye"], lashes=True)
    brow(ink, (0.14, -0.18), (0.72, -0.3), 0.06, darken(hair, 0.45), 0.02)
    brow(ink, (0.02, -0.18), (-0.4, -0.28), 0.05, darken(hair, 0.45))
    nose(ink, L)
    mouth(ink, "stern", L)
    bangs = path(((-0.95, -0.15), (-0.9, -0.75), (-0.2, -0.55)), ((-0.2, -0.55), (0.2, -0.42), (0.55, -0.48)),
                 ((0.55, -0.48), (0.85, -0.4), (0.98, -0.15)), ((0.98, -0.15), (1.05, -0.7), (0.0, -0.85)),
                 ((0.0, -0.85), (-0.95, -0.8), (-0.95, -0.15)))
    ink.poly(bangs, hair, 0)
    hair_strands(ink, bangs, hair, 10, -0.9, 0.9, -0.8, -0.45, 17, 0.02)
    ink.poly(bangs, None)
    for side in (-1, 1):
        base_u = -0.9 if side < 0 else 0.8
        d = side
        sc = 1.0 if side < 0 else 0.8
        for k in range(4):
            f0 = (base_u, -0.75 - k * 0.04)
            tip = (base_u + d * (0.7 + k * 0.18) * sc, -1.55 - k * 0.22 * sc + k * 0.12)
            feather = path((f0, (f0[0] + d * 0.3 * sc, tip[1] + 0.25), tip),
                           (tip, (f0[0] + d * 0.45 * sc, tip[1] + 0.45), (f0[0], f0[1] + 0.12)))
            ink.poly(feather, (252, 252, 255))
            ink.clip(feather, [(base_u - 2, -0.8), (base_u + 2, -0.8), (base_u + 2, -0.5), (base_u - 2, -0.5)], (200, 206, 226))
    cap = path(((-1.02, -0.5), (-1.08, -1.25), (0.05, -1.28)), ((0.05, -1.28), (1.12, -1.25), (1.04, -0.5)),
               ((1.04, -0.5), (0.0, -0.66), (-1.02, -0.5)))
    metal(ink, cap, L["metal"])
    ink.line(bez((-0.95, -0.62), (0.0, -0.78), (0.98, -0.62)), darken(L["metal"], 0.35), max(2, ink.ow // 2))
    ink.line(bez((0.05, -1.25), (0.15, -1.0), (0.1, -0.72)), lighten(L["metal"], 0.4), max(2, ink.ow // 2))
    ink.circle(0.1, -0.86, 0.09, L["eye"], max(2, ink.ow // 2))


HEADS = {"ragnar": head_ragnar, "kira": head_kira, "blaze": head_blaze, "titan": head_titan,
         "vex": head_vex, "luna": head_luna, "rex": head_rex, "aria": head_aria}


# ---- portrait bodies / backgrounds ---------------------------------------------
def shoulders(ink, L, cid):
    prim, sec = L["primary"], L["secondary"]
    body = path(((-2.7, 3.4), (-2.65, 2.2), (-2.3, 1.75)), ((-2.3, 1.75), (-1.4, 1.25), (-0.4, 1.35)),
                ((-0.4, 1.35), (0.0, 1.5), (0.45, 1.35)), ((0.45, 1.35), (1.5, 1.25), (2.35, 1.75)),
                ((2.35, 1.75), (2.7, 2.2), (2.75, 3.4)))
    base = L["skin"] if cid == "rex" else (L["metal"] if cid == "titan" else prim)
    ink.poly(body, base, 0)
    ink.clip(body, [(-3, 1), (-0.8, 1), (-1.1, 3.5), (-3, 3.5)], darken(base, 0.3))
    ink.clip(body, [(1.4, 1.2), (1.75, 1.2), (2.1, 3.5), (1.75, 3.5)], lighten(base, 0.25))
    if cid == "ragnar":
        fur = path(((-2.6, 2.1), (-2.2, 1.35), (-0.9, 1.25)), ((-0.9, 1.25), (0.0, 1.95), (1.0, 1.25)),
                   ((1.0, 1.25), (2.3, 1.35), (2.65, 2.1)), ((2.65, 2.1), (1.4, 2.45), (0.0, 2.5)),
                   ((0.0, 2.5), (-1.4, 2.45), (-2.6, 2.1)))
        ink.poly(fur, (128, 94, 62), 0)
        hair_strands(ink, fur, (128, 94, 62), 40, -2.5, 2.5, 1.3, 2.3, 41, 0.035)
        ink.poly(fur, None)
        ink.poly([(-1.4, 3.4), (-1.1, 3.4), (0.9, 2.3), (0.6, 2.3)], (92, 58, 32))
        metal(ink, ellipse_pts(0.75, 2.4, 0.2, 0.2), (226, 186, 76))
    elif cid == "kira":
        for side in (-1, 1):
            ink.poly([(side * 0.15, 1.45), (side * 1.2, 1.6), (side * 0.2, 3.4)], darken(prim, 0.2))
        ink.poly([(-1.6, 3.4), (-1.2, 3.4), (1.3, 2.2), (1.1, 1.95)], sec)
        metal(ink, [(1.5, 1.55), (2.4, 1.85), (2.5, 2.4), (1.6, 2.2)], (190, 194, 206))
    elif cid == "blaze":
        ink.poly([(-0.6, 1.3), (0.0, 1.9), (0.6, 1.3), (0.7, 1.55), (0.0, 2.3), (-0.7, 1.55)], sec)
        ink.line([(0.0, 2.3), (0.0, 3.4)], sec, ink.ow * 2)
        ink.glow(1.6, 2.8, 0.8, (255, 140, 40), 140)
    elif cid == "titan":
        for side in (-1, 1):
            pad = ellipse_pts(side * 1.85, 1.95, 0.85, 0.55, side * 0.25)
            metal(ink, pad, lighten(L["metal"], 0.08))
            rivets(ink, [(side * 1.5, 1.7), (side * 2.2, 2.0)], 0.07, L["metal"])
        ink.glow(0.0, 2.8, 0.7, sec, 170)
        ink.poly([(0.0, 2.45), (0.22, 2.75), (0.0, 3.05), (-0.22, 2.75)], sec)
    elif cid == "vex":
        ink.poly([(-1.0, 1.35), (0.0, 2.4), (1.05, 1.35), (0.55, 1.3), (0.0, 1.85), (-0.5, 1.3)], (190, 40, 40))
        ink.poly([(-0.35, 1.4), (-1.3, 3.4), (-0.6, 3.4), (0.0, 2.2)], darken(prim, 0.15))
        ink.poly([(0.4, 1.4), (1.3, 3.4), (0.7, 3.4), (0.05, 2.2)], darken(prim, 0.15))
        ink.line([(-2.0, 1.9), (1.2, 3.4)], (64, 42, 26), ink.ow * 3)
        for k in range(5):
            ink.circle(-1.7 + k * 0.6, 2.05 + k * 0.28, 0.08, (226, 190, 90), max(2, ink.ow // 2))
    elif cid == "luna":
        collar = path(((-1.1, 1.3), (-1.5, 0.6), (-0.9, 0.45)), ((-0.9, 0.45), (-0.5, 1.2), (0.0, 1.55)),
                      ((0.0, 1.55), (0.5, 1.2), (0.95, 0.45)), ((0.95, 0.45), (1.5, 0.6), (1.1, 1.3)))
        ink.poly(collar + [(1.0, 2.0), (-1.0, 2.0)], darken(prim, 0.25))
        ink.line(bez((-1.0, 1.95), (0.0, 2.3), (1.0, 1.95)), sec, ink.ow)
        rng = random.Random(2)
        for _ in range(10):
            ink.circle(rng.uniform(-2.3, 2.3), rng.uniform(2.3, 3.3), 0.035, (240, 230, 255), 0)
        ink.circle(0.0, 2.25, 0.15, (255, 246, 200), max(2, ink.ow // 2))
        ink.circle(0.06, 2.21, 0.12, darken(prim, 0.1), 0)
    elif cid == "rex":
        hair_strands(ink, body, L["skin"], 40, -2.5, 2.5, 1.4, 3.2, 43, 0.035)
        ink.line([(-2.2, 2.1), (1.4, 3.4)], (90, 60, 36), ink.ow * 3)
        for k in range(4):
            u = -0.9 + k * 0.45
            ink.poly([(u - 0.08, 1.75), (u + 0.08, 1.75), (u, 2.1)], (240, 236, 214), max(2, ink.ow // 2))
        ink.line(bez((-1.0, 1.7), (0.0, 1.85), (1.0, 1.7)), (90, 60, 36), max(2, ink.ow // 2))
    elif cid == "aria":
        gorget = path(((-1.0, 1.3), (0.0, 1.7), (1.05, 1.3)), ((1.05, 1.3), (1.1, 2.0), (0.0, 2.25)),
                      ((0.0, 2.25), (-1.05, 2.0), (-1.0, 1.3)))
        metal(ink, gorget, L["metal"])
        for side in (-1, 1):
            metal(ink, ellipse_pts(side * 1.8, 1.95, 0.8, 0.5, side * 0.2), (226, 230, 240))
        ink.circle(0.0, 1.95, 0.12, L["eye"], max(2, ink.ow // 2))
    ink.poly(body, None)


def background(ink, L, w, h):
    s = ink.s
    top, bottom = L["bg"]
    for y in range(h):
        pygame.draw.line(s, mix(top, bottom, y / max(1, h - 1)), (0, y), (w, y))
    cx, cy = ink.cx, ink.cy
    for i in range(18):
        a0 = i * math.tau / 18
        p1 = (cx + math.cos(a0) * w * 1.5, cy + math.sin(a0) * w * 1.5)
        p2 = (cx + math.cos(a0 + 0.12) * w * 1.5, cy + math.sin(a0 + 0.12) * w * 1.5)
        pygame.draw.polygon(s, mix(top, lighten(top, 0.3), 0.35), [(cx, cy), p1, p2])
    step = max(6, w // 30)
    dot = darken(bottom, 0.35)
    for gy in range(0, h + step, step):
        for gx in range(0, w + step, step):
            k = (gx / w + gy / h) / 2
            r = step * 0.42 * max(0.0, k - 0.35) * 1.8
            if r > 0.6:
                pygame.draw.circle(s, dot, (gx + (step / 2 if (gy // step) % 2 else 0), gy), r)


def render_portrait(cid, L, size):
    n = 480
    ink = Ink(n, n, n * 0.5, n * 0.43, n * 0.2)
    background(ink, L, n, n)
    shoulders(ink, L, cid)
    HEADS[cid](ink, L)
    pygame.draw.rect(ink.s, OUTLINE, (0, 0, n, n), max(4, n // 60))
    return pygame.transform.smoothscale(ink.s, (size, size)) if size != n else ink.s


def render_head(cid, L):
    """Transparent high-res head, used for in-game sprites. Returns (surface, R in px)."""
    n = 512
    R = n * 0.17
    ink = Ink(n, n, n * 0.5, n * 0.5, R, ow=max(5, int(R * 0.09)))
    HEADS[cid](ink, L)
    return ink.s, R
