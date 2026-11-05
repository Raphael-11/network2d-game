"""Skeletal cut-out fighters.

Every body part (torso, upper arm, forearm, fist, thigh, shin, boot, weapon,
cape, skirt, tail...) is painted once at high resolution with a thick ink
outline, cel shadow, highlight and costume detail. Each frame the parts are
rotated onto a skeleton and composited -- the same technique real 2D fighters
use. Poses are plain dicts of numbers so the UI can blend between them.

Local frame: fighter units, feet at (0, 0), y down, facing right.
Limb angles: 0 = hanging straight down, +pi/2 = pointing forward, pi = up.
"""
import math

import pygame

from common import characters as C
from common import physics as G
from client import art
from client.portraits import Ink, OUTLINE, path, ellipse_pts, lighten, darken, mix, metal, rivets, hair_strands

PU = 8                      # master art: pixels per fighter unit
VIS = 1.25                  # fighters are drawn larger than their hitbox
HIP_Y = -24.0
TORSO_LEN = 21.0
UARM = FARM = 10.0
THIGH = SHIN = 11.0
ANKLE_Y = -3.0
HEAD_R = 15.0
OW = 1.7                    # ink outline, in fighter units

BUILD = {"titan": 1.32, "ragnar": 1.16, "rex": 1.1, "kira": 0.9, "luna": 0.9}
FIST_WEAPONS = ("claws", "gauntlets")
DUAL = ("pistols", "claws", "gauntlets")
REACH = {"axe": 30, "katana": 37, "hammer": 32, "spear": 52, "scythe": 33,
         "pistols": 15, "claws": 15, "gauntlets": 3}

ANGLE_KEYS = ("fa", "ba", "wa", "bwa")
POSE_KEYS = ("fa", "ba", "fbend", "bbend", "wa", "bwa", "lean", "crouch", "ext",
             "ffx", "ffy", "bfx", "bfy", "head_tilt")


def build(cid):
    return BUILD.get(cid, 1.0)


# ---- painting helpers --------------------------------------------------------
def _canvas(x0, y0, x1, y1):
    pad = 10
    w = int((x1 - x0) * PU) + 2 * pad
    h = int((y1 - y0) * PU) + 2 * pad
    return Ink(w, h, -x0 * PU + pad, -y0 * PU + pad, PU, ow=int(OW * PU))


def _done(ink):
    return ink.s, (ink.cx, ink.cy)


def limb_shape(L, w0, wm, w1, bulge=0.0):
    """Tapered limb from the pivot (0, 0) down to (0, L), rounded caps, optional front bulge."""
    n = 12
    right, left = [], []
    for i in range(n + 1):
        t = i / n
        w = (1 - t) ** 2 * w0 + 2 * (1 - t) * t * wm + t * t * w1
        right.append((w / 2 + bulge * math.sin(math.pi * t), t * L))
        left.append((-w / 2, t * L))
    bot = [(math.cos(a) * w1 / 2, L + math.sin(a) * w1 * 0.42) for a in (k * math.pi / 8 for k in range(1, 8))]
    top = [(-math.cos(a) * w0 / 2, -math.sin(a) * w0 * 0.42) for a in (k * math.pi / 8 for k in range(1, 8))]
    return right + bot + left[::-1] + top


def shade_limb(ink, shape, L, ww, base):
    ink.poly(shape, base, 0)
    ink.clip(shape, [(-ww, -ww), (-ww * 0.06, -ww), (-ww * 0.14, L + ww), (-ww, L + ww)], darken(base, 0.26))
    ink.clip(shape, [(ww * 0.1, -ww * 0.2), (ww * 0.28, -ww * 0.2), (ww * 0.22, L * 0.8), (ww * 0.06, L * 0.8)],
             lighten(base, 0.32))


def band(ink, shape, y0, y1, col, ww=20):
    ink.clip(shape, [(-ww, y0), (ww, y0), (ww, y1), (-ww, y1)], col)
    ink.clip(shape, [(-ww, y0), (-ww * 0.05, y0), (-ww * 0.05, y1), (-ww, y1)], darken(col, 0.25))


def stripes(ink, shape, y0, y1, step, col, slant=1.5, w=None):
    y = y0
    while y < y1:
        ink.clip(shape, [(-20, y), (20, y - slant), (20, y - slant + 0.45), (-20, y + 0.45)], col)
        y += step


# ---- costume palette -----------------------------------------------------------
def palette(cid):
    L = art.look(cid)
    skin, prim, sec, met = L["skin"], L["primary"], L["secondary"], L["metal"]
    gold = (232, 190, 74)
    P = {
        "ragnar": dict(torso=prim, uarm=skin, farm=skin, hand=skin, thigh=(110, 80, 52), shin=(132, 98, 66),
                       boot=(92, 62, 40), trim=gold),
        "kira": dict(torso=prim, uarm=prim, farm=(226, 226, 236), hand=(34, 34, 46), thigh=prim,
                     shin=(226, 226, 236), boot=(26, 26, 34), trim=sec),
        "blaze": dict(torso=prim, uarm=prim, farm=prim, hand=skin, thigh=(92, 50, 36), shin=(206, 160, 104),
                      boot=(120, 74, 40), trim=gold),
        "titan": dict(torso=met, uarm=met, farm=met, hand=met, thigh=met, shin=met, boot=darken(met, 0.15), trim=sec),
        "vex": dict(torso=(214, 196, 156), uarm=(214, 196, 156), farm=skin, hand=(108, 70, 42),
                    thigh=(64, 84, 124), shin=(64, 84, 124), boot=(110, 66, 36), trim=(206, 172, 92)),
        "luna": dict(torso=prim, uarm=prim, farm=prim, hand=skin, thigh=(56, 38, 84), shin=(56, 38, 84),
                     boot=darken(prim, 0.2), trim=(214, 210, 236)),
        "rex": dict(torso=skin, uarm=skin, farm=skin, hand=skin, thigh=prim, shin=skin, boot=skin, trim=sec),
        "aria": dict(torso=(238, 238, 248), uarm=(238, 238, 248), farm=met, hand=(238, 238, 248),
                     thigh=(238, 238, 248), shin=met, boot=met, trim=met),
    }[cid]
    P["skin"] = skin
    P["metal"] = met
    P["sec"] = sec
    P["prim"] = prim
    return P


# ---- parts -------------------------------------------------------------------
def part_torso(cid, P):
    b = build(cid)
    cw, hw, T = 12.5 * b, 8.5 * b, TORSO_LEN
    ink = _canvas(-cw - 5, -T - 6, cw + 5, 5)
    shape = path(((-hw, 0.5), (-cw * 1.02, -6), (-cw * 0.92, -16)),
                 ((-cw * 0.92, -16), (-cw * 0.85, -T + 1), (-5 * b, -T)),
                 ((-5 * b, -T), (0, -T - 1), (5 * b, -T)),
                 ((5 * b, -T), (cw * 0.92, -T + 1), (cw, -15)),
                 ((cw, -15), (cw * 1.06, -7), (hw, 0.5)),
                 ((hw, 0.5), (0, 2.4), (-hw, 0.5)))
    base = P["torso"]
    ink.poly(shape, base, 0)
    ink.clip(shape, [(-cw - 2, -T - 2), (-cw * 0.3, -T - 2), (-cw * 0.42, 3), (-cw - 2, 3)], darken(base, 0.26))
    ink.clip(shape, [(cw * 0.42, -T + 2), (cw * 0.62, -T + 2), (cw * 0.66, -8), (cw * 0.46, -8)], lighten(base, 0.3))
    ink.clip(shape, ellipse_pts(cw * 0.1, -6.5, cw * 0.9, 2.2), darken(base, 0.12))
    sec, trim = P["sec"], P["trim"]
    if cid == "ragnar":
        strap = [(cw * 0.75, -T + 1), (cw * 0.98, -T + 3.5), (-hw + 1.5, -1.5), (-hw - 1, -4)]
        ink.clip(shape, strap, (96, 60, 32))
        ink.circle(cw * 0.2, -10, 1.6, (236, 196, 80), int(0.8 * PU))
        band(ink, shape, -4.5, -0.8, (90, 56, 30), cw + 2)
        ink.poly(ellipse_pts(1.5, -2.6, 2.4, 1.9), (236, 196, 80), int(0.8 * PU))
        mantle = [(-cw - 2.5, -T + 6)]
        for i in range(10):
            x = -cw - 2 + i * (2 * cw + 4) / 9
            mantle.append((x, -T - 1.5 - (1.8 if i % 2 else 0)))
        mantle.append((cw + 2.5, -T + 6))
        for i in range(9, -1, -1):
            x = -cw - 2 + i * (2 * cw + 4) / 9
            mantle.append((x, -T + 6.5 + (2.2 if i % 2 else 0)))
        ink.poly(mantle, (132, 98, 66), 0)
        ink.clip(mantle, [(-cw - 4, -T - 4), (-cw * 0.2, -T - 4), (-cw * 0.3, -T + 10), (-cw - 4, -T + 10)], (100, 72, 46))
        hair_strands(ink, mantle, (132, 98, 66), 26, -cw, cw, -T - 1.5, -T + 5, 5, 0.25)
        ink.poly(mantle, None)
    elif cid == "kira":
        ink.clip(shape, [(-3, -T - 1), (-1.2, -T - 1), (4, -9), (2.2, -9)], lighten(base, 0.18))
        ink.clip(shape, [(4, -T - 1), (5.8, -T - 1), (2.2, -9), (0.4, -9)], lighten(base, 0.18))
        ink.clip(shape, [(cw * 0.8, -T + 2), (cw + 1, -T + 4.5), (-hw + 1, -1), (-hw - 1, -3.5)], sec)
        band(ink, shape, -5, -1, sec, cw + 2)
        ink.circle(-hw + 1.5, -3, 1.8, (200, 204, 214), int(0.7 * PU))
    elif cid == "blaze":
        ink.clip(shape, [(-4.5, -T - 1), (-2.5, -T - 1), (2.5, -7), (0.5, -7)], trim)
        ink.clip(shape, [(4.5, -T - 1), (6.5, -T - 1), (2.5, -7), (0.5, -7)], trim)
        band(ink, shape, -6, -2, (255, 150, 40), cw + 2)
        ink.poly([(2.0, -2.5), (4.5, 1.5), (1.0, 3.5), (-0.5, 0.5)], (255, 150, 40), int(0.8 * PU))
        flame = [(cw * 0.42, -16), (cw * 0.55, -12), (cw * 0.5, -10), (cw * 0.62, -11), (cw * 0.5, -8.5),
                 (cw * 0.3, -9.5), (cw * 0.36, -12)]
        ink.poly(flame, (255, 196, 60), int(0.6 * PU))
    elif cid == "titan":
        plate = [(-cw * 0.7, -T + 2), (cw * 0.8, -T + 2), (cw * 0.85, -11), (0, -8), (-cw * 0.75, -11)]
        metal(ink, plate, lighten(base, 0.12))
        ink.poly(plate, None, int(0.9 * PU))
        rivets(ink, [(-cw * 0.55, -T + 3.5), (cw * 0.62, -T + 3.5), (-cw * 0.6, -12), (cw * 0.68, -12)], 0.9, base)
        ink.glow(cw * 0.12, -14.5, 6.5, sec, 200)
        ink.poly(ellipse_pts(cw * 0.12, -14.5, 2.6, 2.6), sec, int(0.8 * PU))
        ink.poly(ellipse_pts(cw * 0.12, -14.5, 1.2, 1.2), lighten(sec, 0.7), 0)
        for y in (-6, -3.5):
            ink.line([(-cw * 0.7, y), (cw * 0.8, y + 0.4)], darken(base, 0.35), int(0.6 * PU))
        band(ink, shape, -2.5, 0.8, darken(base, 0.3), cw + 2)
    elif cid == "vex":
        vest_back = [(-cw - 2, -T - 2), (-1.5, -T - 2), (0.5, 3), (-cw - 2, 3)]
        vest_front = [(3.5, -T - 2), (cw + 2, -T - 2), (cw + 2, 3), (4.8, 3)]
        ink.clip(shape, vest_back, (110, 70, 44))
        ink.clip(shape, vest_front, (130, 84, 52))
        ink.clip(shape, [(cw * 0.6, -T + 1), (cw * 0.72, -T + 1), (cw * 0.72, -2), (cw * 0.6, -2)], (150, 100, 64))
        for y in (-16, -12, -8):
            ink.circle(4.0, y, 0.55, (230, 210, 150), 0)
        a, bb = (cw * 0.85, -T + 2), (-hw + 1, -2)
        ink.clip(shape, [(a[0], a[1]), (a[0] + 1.8, a[1] + 1.8), (bb[0] + 1.8, bb[1] + 1.8), bb], (64, 42, 26))
        for i in range(1, 6):
            ink.circle(a[0] + (bb[0] - a[0]) * i / 6 + 0.9, a[1] + (bb[1] - a[1]) * i / 6 + 0.9, 0.6, (236, 200, 90),
                       int(0.3 * PU))
        band(ink, shape, -4.5, -1, (74, 46, 26), cw + 2)
        metal(ink, [(0.2, -4.3), (4.4, -4.3), (4.4, -1.2), (0.2, -1.2)], (210, 212, 222))
        ink.poly([(-4, -T - 0.5), (4, -T - 0.5), (0.8, -T + 5)], (196, 40, 40), int(0.7 * PU))
    elif cid == "luna":
        ink.clip(shape, [(-4, -T - 1), (-2.4, -T - 1), (2.2, -8), (0.6, -8)], trim)
        ink.clip(shape, [(4.4, -T - 1), (6, -T - 1), (2.2, -8), (0.6, -8)], trim)
        rngs = [(-6, -14), (-3, -6), (6.5, -11), (-8, -9), (7, -5)]
        for x, y in rngs:
            ink.circle(x * b, y, 0.35, (240, 232, 255), 0)
        band(ink, shape, -5.5, -2.5, trim, cw + 2)
        ink.circle(2.6, -T + 4, 1.6, (255, 246, 200), int(0.6 * PU))
        ink.circle(3.1, -T + 3.7, 1.3, base, 0)
    elif cid == "rex":
        ink.clip(shape, ellipse_pts(cw * 0.35, -9, cw * 0.55, 8), lighten(base, 0.35))
        hair_strands(ink, shape, base, 22, -cw, cw, -T, -2, 7, 0.25)
        for side in (1, -1):
            ink.clip(shape, [(side * cw, -T + 1), (side * cw + 1.6 * side, -T + 2.6), (-side * hw * 0.2, -2),
                             (-side * hw * 0.2 - 1.6 * side, -3.5)], (90, 60, 36))
        for i in range(5):
            x = -5 + i * 2.6
            ink.poly([(x - 0.7, -T + 0.5), (x + 0.7, -T + 0.5), (x, -T + 3.2)], (240, 236, 214), int(0.4 * PU))
        band(ink, shape, -3, 0.8, P["thigh"], cw + 2)
    elif cid == "aria":
        plate = [(-cw * 0.85, -T + 1), (cw * 0.88, -T + 1), (cw * 0.95, -12), (cw * 0.3, -8.5), (-cw * 0.8, -11)]
        metal(ink, plate, (226, 230, 240))
        ink.line([(-cw * 0.85, -T + 1.6), (cw * 0.88, -T + 1.6)], trim, int(0.8 * PU))
        ink.line([(cw * 0.95, -12), (cw * 0.3, -8.5), (-cw * 0.8, -11)], trim, int(0.8 * PU))
        ink.poly(plate, None, int(0.9 * PU))
        ink.poly(ellipse_pts(cw * 0.15, -14, 1.5, 1.5), art.look(cid)["eye"], int(0.6 * PU))
        band(ink, shape, -5, -2, trim, cw + 2)
    ink.poly(shape, None)
    return _done(ink)


def part_uarm(cid, P):
    b = build(cid)
    w0, wm, w1 = 8.6 * b, 11 * b, 7.6 * b
    if cid in ("blaze", "luna"):
        w0, wm, w1 = 9.5 * b, 12.5 * b, 10 * b
    ink = _canvas(-wm, -w0, wm, UARM + w1)
    shape = limb_shape(UARM, w0, wm, w1, bulge=0.9 * b)
    shade_limb(ink, shape, UARM, wm, P["uarm"])
    if cid == "titan":
        band(ink, shape, 2, 4, darken(P["metal"], 0.3), wm)
        rivets(ink, [(2.2, 3), (-1.5, 3)], 0.6, P["metal"])
    elif cid == "vex":
        band(ink, shape, UARM - 2.4, UARM + 2, lighten(P["uarm"], 0.15), wm)
        ink.line([(-w1 / 2, UARM - 2.4), (w1 / 2 + 0.6, UARM - 2.4)], darken(P["uarm"], 0.35), int(0.5 * PU))
    elif cid == "aria":
        band(ink, shape, UARM - 2, UARM + 2, P["metal"], wm)
    elif cid == "kira":
        band(ink, shape, UARM - 1.5, UARM + 2, darken(P["uarm"], 0.25), wm)
    elif cid in ("blaze", "luna"):
        ink.line([(w0 * 0.1, 1), (w1 * 0.2, UARM - 1)], darken(P["uarm"], 0.3), int(0.45 * PU))
    elif cid == "rex":
        hair_strands(ink, shape, P["uarm"], 10, -wm / 2, wm / 2, 0, UARM, 11, 0.22)
    elif cid == "ragnar":
        ink.line([(-1.5, 3.5), (1.8, 2.8), (3.4, 4.5)], darken(P["skin"], 0.35), int(0.45 * PU))
    ink.poly(shape, None)
    return _done(ink)


def part_farm(cid, P):
    b = build(cid)
    w0, wm, w1 = 7.6 * b, 11.6 * b, 7.2 * b
    flare = cid in ("blaze", "luna")
    if flare:
        w0, wm, w1 = 9 * b, 12.5 * b, 15 * b
    ink = _canvas(-max(wm, w1), -w0, max(wm, w1), FARM + w1)
    shape = limb_shape(FARM, w0, wm, w1, bulge=0.6 * b)
    shade_limb(ink, shape, FARM, max(wm, w1), P["farm"])
    ww = max(wm, w1)
    if cid == "ragnar":
        band(ink, shape, FARM * 0.45, FARM + 3, (96, 60, 34), ww)
        for y in (FARM * 0.6, FARM * 0.85):
            ink.circle(2.2, y, 0.65, (220, 220, 228), int(0.35 * PU))
    elif cid == "kira":
        stripes(ink, shape, -1, FARM + 2, 2.0, (150, 150, 170))
        band(ink, shape, FARM - 1, FARM + 3, P["hand"], ww)
    elif cid in ("blaze", "luna"):
        band(ink, shape, FARM - 1.6, FARM + 4, P["trim"], ww)
        ink.line([(0, 1), (-w1 * 0.25, FARM - 2)], darken(P["farm"], 0.3), int(0.45 * PU))
        ink.line([(w0 * 0.2, 1), (w1 * 0.3, FARM - 2)], darken(P["farm"], 0.3), int(0.45 * PU))
    elif cid == "titan":
        band(ink, shape, 1, 3, darken(P["metal"], 0.25), ww)
        ink.clip(shape, [(1.2, 3), (2.2, 3), (2.2, FARM), (1.2, FARM)], P["sec"])
        ink.glow(1.7, FARM * 0.6, 3.2, P["sec"], 120)
        rivets(ink, [(-2, FARM - 1.5), (3, FARM - 1.5)], 0.6, P["metal"])
    elif cid == "vex":
        band(ink, shape, FARM - 1.4, FARM + 3, P["hand"], ww)
    elif cid == "rex":
        ink.clip(shape, [(1, -2), (ww, -2), (ww, FARM + 3), (1.5, FARM + 3)], lighten(P["farm"], 0.32))
        hair_strands(ink, shape, P["farm"], 10, -ww / 2, ww / 2, 0, FARM, 13, 0.22)
        ink.poly([(-w1 / 2 - 1.2, FARM - 2), (-w1 / 2 + 1, FARM - 3), (-w1 / 2 - 0.5, FARM - 4.5)], P["farm"], int(0.5 * PU))
    elif cid == "aria":
        ink.clip(shape, [(-ww, 2), (ww, 2), (ww, 3), (-ww, 3)], (200, 160, 50))
        ink.clip(shape, [(-ww, FARM - 1.5), (ww, FARM - 1.5), (ww, FARM - 0.5), (-ww, FARM - 0.5)], (200, 160, 50))
    ink.poly(shape, None)
    return _done(ink)


def part_hand(cid, P):
    b = build(cid)
    r = 5.0 * b
    ink = _canvas(-r * 1.5, -2, r * 1.6, r * 2.4)
    base = P["hand"]
    fist = path(((-r * 0.9, 0.2), (-r * 1.15, r * 1.2), (-r * 0.6, r * 2.05)),
                ((-r * 0.6, r * 2.05), (r * 0.2, r * 2.35), (r * 0.95, r * 1.75)),
                ((r * 0.95, r * 1.75), (r * 1.25, r * 0.9), (r * 0.8, 0.0)),
                ((r * 0.8, 0.0), (0, -0.8), (-r * 0.9, 0.2)))
    ink.poly(fist, base, 0)
    ink.clip(fist, [(-r * 2, -2), (-r * 0.25, -2), (-r * 0.35, r * 3), (-r * 2, r * 3)], darken(base, 0.25))
    ink.clip(fist, ellipse_pts(r * 0.45, r * 0.8, r * 0.3, r * 0.5), lighten(base, 0.3))
    if cid == "rex":
        for k in range(3):
            y = r * (1.0 + k * 0.42)
            ink.poly([(r * 0.95, y - 0.8), (r * 1.9, y + 0.6), (r * 0.95, y + 0.8)], (246, 242, 226), int(0.45 * PU))
    elif cid == "titan":
        for k in range(3):
            y = r * (0.9 + k * 0.42)
            ink.line([(r * 0.1, y), (r * 1.0, y - 0.2)], darken(base, 0.4), int(0.5 * PU))
        rivets(ink, [(-r * 0.3, r * 0.5)], 0.6, base)
    else:
        for k in range(3):
            y = r * (0.95 + k * 0.38)
            ink.line([(r * 0.25, y), (r * 1.0, y - 0.3)], darken(base, 0.42), int(0.45 * PU))
        thumb = ellipse_pts(r * 0.6, r * 0.45, r * 0.42, r * 0.28, -0.5)
        ink.poly(thumb, lighten(base, 0.08), int(0.5 * PU))
    if cid == "aria":
        band(ink, fist, -1, r * 0.4, (220, 180, 60), r * 2)
    ink.poly(fist, None)
    return _done(ink)


def part_thigh(cid, P):
    b = build(cid)
    w0, wm, w1 = 10.4 * b, 12.6 * b, 8.8 * b
    ink = _canvas(-wm, -w0, wm, THIGH + w1)
    shape = limb_shape(THIGH, w0, wm, w1, bulge=0.4 * b)
    shade_limb(ink, shape, THIGH, wm, P["thigh"])
    if cid == "titan":
        metal(ink, [(-3.5 * b, 1), (3.8 * b, 1), (3.2 * b, THIGH - 2), (-3 * b, THIGH - 2)], lighten(P["metal"], 0.1))
        ink.poly([(-3.5 * b, 1), (3.8 * b, 1), (3.2 * b, THIGH - 2), (-3 * b, THIGH - 2)], None, int(0.6 * PU))
    elif cid == "rex":
        jag = [(-wm, THIGH * 0.55)]
        for i in range(7):
            jag.append((-wm / 2 + i * wm / 6, THIGH * 0.62 + (1.4 if i % 2 else 0)))
        jag += [(wm, THIGH * 0.55), (wm, THIGH + 6), (-wm, THIGH + 6)]
        ink.clip(shape, jag, P["skin"])
        ink.clip(shape, [(-wm, THIGH * 0.62), (-wm * 0.1, THIGH * 0.62), (-wm * 0.1, THIGH + 6), (-wm, THIGH + 6)],
                 darken(P["skin"], 0.25))
    elif cid == "vex":
        ink.line([(w0 * 0.15, 1), (w1 * 0.2, THIGH)], darken(P["thigh"], 0.3), int(0.45 * PU))
    elif cid == "ragnar":
        stripes(ink, shape, 2, THIGH, 3.2, darken(P["thigh"], 0.28))
    elif cid == "aria":
        ink.line([(0, 1), (0, THIGH)], (210, 214, 230), int(0.45 * PU))
    ink.poly(shape, None)
    return _done(ink)


def part_shin(cid, P):
    b = build(cid)
    w0, wm, w1 = 8.6 * b, 10.4 * b, 7.4 * b
    ink = _canvas(-wm, -w0, wm, SHIN + w1)
    shape = limb_shape(SHIN, w0, wm, w1, bulge=-0.3 * b)
    shade_limb(ink, shape, SHIN, wm, P["shin"])
    if cid in ("ragnar", "kira", "blaze"):
        stripes(ink, shape, 0, SHIN + 2, 2.3, darken(P["shin"], 0.3))
        if cid == "ragnar":
            band(ink, shape, 3, 4.2, (80, 52, 30), wm)
            band(ink, shape, 7.5, 8.7, (80, 52, 30), wm)
    elif cid in ("titan", "aria"):
        plate = [(-1 * b, -1), (4.6 * b, 0), (4 * b, SHIN), (0, SHIN + 1)]
        metal(ink, plate, lighten(P["shin"], 0.1))
        ink.poly(plate, None, int(0.6 * PU))
        ink.poly(ellipse_pts(1.5 * b, 0.5, 3.4 * b, 2.4 * b), lighten(P["shin"], 0.18), int(0.6 * PU))
    elif cid == "rex":
        ink.clip(shape, [(1, -2), (wm, -2), (wm, SHIN + 3), (1.5, SHIN + 3)], lighten(P["shin"], 0.32))
        hair_strands(ink, shape, P["shin"], 8, -wm / 2, wm / 2, 0, SHIN, 17, 0.22)
    ink.poly(shape, None)
    return _done(ink)


def part_boot(cid, P):
    b = build(cid)
    ink = _canvas(-7 * b, -7 * b, 13 * b, 4.5)
    base = P["boot"]
    if cid == "luna":
        shape = path(((-3.5 * b, -4.5 * b), (3.5 * b, -4.5 * b), (4 * b, -1)),
                     ((4 * b, -1), (8 * b, 0.5), (11 * b, -1.8)),
                     ((11 * b, -1.8), (10.5 * b, 2.2), (5 * b, 3)),
                     ((5 * b, 3), (-2 * b, 3.2), (-4.2 * b, 1.5)),
                     ((-4.2 * b, 1.5), (-4.5 * b, -1.5), (-3.5 * b, -4.5 * b)))
    elif cid == "vex":
        shape = path(((-3.8 * b, -6.5 * b), (3.8 * b, -6.5 * b), (4.2 * b, -1)),
                     ((4.2 * b, -1), (8.5 * b, -0.2), (11 * b, 1.2)),
                     ((11 * b, 1.2), (11 * b, 2.6), (6 * b, 2.6)),
                     ((6 * b, 2.6), (0, 2.6), (-4.6 * b, 3.4)),
                     ((-4.6 * b, 3.4), (-4.6 * b, -1), (-3.8 * b, -6.5 * b)))
    else:
        top = -6.5 * b if cid in ("titan", "aria", "ragnar") else -4.5 * b
        shape = path(((-4.2 * b, top), (4.2 * b, top), (4.6 * b, -0.6)),
                     ((4.6 * b, -0.6), (9.5 * b, -0.6), (10.6 * b, 1.4)),
                     ((10.6 * b, 1.4), (10.4 * b, 3.2), (6 * b, 3.2)),
                     ((6 * b, 3.2), (0, 3.2), (-4.8 * b, 3.0)),
                     ((-4.8 * b, 3.0), (-5.2 * b, 0), (-4.2 * b, top)))
    if cid == "blaze":
        foot = path(((-3.2, -2.5), (3.2, -2.5), (4, 0)), ((4, 0), (9.5, 0.2), (10, 2)), ((10, 2), (4, 3.2), (-4, 3)),
                    ((-4, 3), (-4.4, 0), (-3.2, -2.5)))
        ink.poly(foot, P["skin"], 0)
        ink.clip(foot, [(-6, 2), (12, 2), (12, 4), (-6, 4)], (120, 74, 40))
        for x in (0.5, 4.5):
            ink.clip(foot, [(x, -3), (x + 1.3, -3), (x + 2.3, 3), (x + 1, 3)], (120, 74, 40))
        ink.poly(foot, None)
        return _done(ink)
    if cid == "rex":
        ink.poly(shape, base, 0)
        ink.clip(shape, [(-6, -8), (-1, -8), (-1, 4), (-6, 4)], darken(base, 0.25))
        hair_strands(ink, shape, base, 8, -4, 9, -5, 2, 19, 0.22)
        ink.poly(shape, None)
        for k in range(3):
            x = 7.5 * b + k * 1.6
            ink.poly([(x, 1.2), (x + 2.6, 2.6), (x + 0.4, 3.0)], (246, 242, 226), int(0.4 * PU))
        return _done(ink)
    ink.poly(shape, base, 0)
    ink.clip(shape, [(-7, -8), (-1, -8), (-1.5, 4), (-7, 4)], darken(base, 0.25))
    ink.clip(shape, ellipse_pts(7 * b, -0.2, 2.4 * b, 1.0), lighten(base, 0.35))
    ink.clip(shape, [(-7, 1.9), (13, 1.9), (13, 5), (-7, 5)], darken(base, 0.45))
    if cid == "ragnar":
        fur = [(-5.2 * b, -6.5 * b), (5 * b, -6.5 * b), (5.6 * b, -3.6 * b), (-5.6 * b, -3.6 * b)]
        ink.poly(fur, (150, 112, 76), 0)
        hair_strands(ink, fur, (150, 112, 76), 10, -5, 5, -7.5, -4, 23, 0.25)
        ink.poly(fur, None, int(0.8 * PU))
    elif cid == "kira":
        ink.line([(8.6 * b, -0.6), (8.6 * b, 3)], (60, 60, 74), int(0.5 * PU))
    elif cid in ("titan", "aria"):
        rivets(ink, [(-1.5 * b, -4 * b), (2 * b, -4 * b)], 0.6, base)
        ink.line([(-4 * b, -2.2 * b), (4.4 * b, -2.2 * b)], lighten(base, 0.3) if cid == "titan" else (210, 170, 50),
                 int(0.6 * PU))
    elif cid == "vex":
        ink.line([(-3.5 * b, -3.5 * b), (3.6 * b, -3.0 * b)], (160, 110, 60), int(0.5 * PU))
        ink.circle(-5.6 * b, 1.0, 1.4, (210, 212, 222), int(0.4 * PU))
    ink.poly(shape, None)
    return _done(ink)


def part_weapon(cid, P):
    weapon = C.get(cid)["weapon"]
    L = art.look(cid)
    met = L["metal"]
    wood = (122, 80, 46)
    o = int(1.2 * PU)
    if weapon == "axe":
        ink = _canvas(-11, -9, 15, 33)
        handle = [(-1.3, -8), (1.3, -8), (1.6, 28), (-1.6, 28)]
        shade_limb(ink, handle, 36, 3, wood)
        for y in (-1, 2, 5):
            ink.clip(handle, [(-3, y), (3, y - 0.8), (3, y + 0.6), (-3, y + 1.4)], (72, 46, 26))
        ink.poly(handle, None, o)
        blade = path(((1.2, 15), (6, 14), (11, 11)), ((11, 11), (14.5, 21), (11, 31)),
                     ((11, 31), (6, 28), (1.2, 27)))
        metal(ink, blade, met)
        ink.line(path(((11.3, 11.5), (14.6, 21), (11.3, 30.5))), lighten(met, 0.7), int(0.8 * PU))
        ink.poly(blade, None, o)
        spike = [(-1.2, 17), (-8, 20), (-1.2, 24)]
        metal(ink, spike, darken(met, 0.1), hi=False)
        ink.poly(spike, None, o)
        collar = [(-2.2, 15), (2.2, 15), (2.2, 27), (-2.2, 27)]
        metal(ink, collar, darken(met, 0.25), hi=False)
        ink.poly(collar, None, o)
        ink.line([(5.5, 18.5), (8, 21), (5.5, 23.5)], (120, 200, 255), int(0.6 * PU))
    elif weapon == "katana":
        ink = _canvas(-4, -9, 5, 40)
        grip = [(-1.4, -8.5), (1.4, -8.5), (1.4, 0), (-1.4, 0)]
        ink.poly(grip, (40, 30, 30), o)
        for y in (-7, -4.5, -2):
            ink.poly([(-1.4, y), (0, y - 1.2), (1.4, y), (0, y + 1.2)], (200, 40, 60), 0)
        blade = path(((-0.9, 0.5), (-0.6, 20), (0.6, 37)), ((0.6, 37), (1.6, 33), (1.6, 0.5)))
        blade += [(1.6, 0.5), (-0.9, 0.5)]
        ink.poly(blade, (214, 222, 234), 0)
        ink.clip(blade, [(0.6, 0), (3, 0), (3, 40), (0.6, 40)], (250, 252, 255))
        ink.line(path(((0.7, 2), (1.0, 12), (0.6, 18)), ((0.6, 18), (1.0, 26), (0.8, 33))), (170, 180, 196),
                 int(0.35 * PU))
        ink.poly(blade, None, o)
        ink.poly(ellipse_pts(0.2, 0.3, 3.4, 1.1), (226, 186, 76), int(0.7 * PU))
    elif weapon == "hammer":
        ink = _canvas(-14, -7, 14, 36)
        handle = [(-1.5, -6), (1.5, -6), (1.7, 24), (-1.7, 24)]
        shade_limb(ink, handle, 30, 3.4, wood)
        for y in (0, 4, 18):
            ink.clip(handle, [(-3, y), (3, y), (3, y + 1.2), (-3, y + 1.2)], darken(met, 0.2))
        ink.poly(handle, None, o)
        head = [(-12, 21), (12, 21), (12.8, 33.5), (-12.8, 33.5)]
        metal(ink, head, met)
        ink.clip(head, [(-14, 21), (-8.5, 21), (-8.5, 34), (-14, 34)], darken(met, 0.3))
        ink.clip(head, [(8.5, 21), (14, 21), (14, 34), (8.5, 34)], darken(met, 0.15))
        ink.poly(head, None, o)
        ink.glow(0, 27.3, 4.5, L["secondary"], 140)
        ink.line([(-5, 25), (-2, 29.5), (2, 25), (5, 29.5)], L["secondary"], int(0.8 * PU))
        rivets(ink, [(-10.5, 23), (10.5, 23), (-10.5, 31.5), (10.5, 31.5)], 0.7, met)
    elif weapon == "spear":
        ink = _canvas(-7, -20, 7, 55)
        shaft = [(-1.1, -19), (1.1, -19), (1.1, 36), (-1.1, 36)]
        shade_limb(ink, shaft, 55, 2.4, wood)
        for y in (-17, 30):
            ink.clip(shaft, [(-3, y), (3, y), (3, y + 1.4), (-3, y + 1.4)], L["secondary"])
        ink.poly(shaft, None, o)
        head = path(((0, 34), (3.8, 39), (2.6, 45)), ((2.6, 45), (1.4, 50), (0, 55)),
                    ((0, 55), (-1.4, 50), (-2.6, 45)), ((-2.6, 45), (-3.8, 39), (0, 34)))
        metal(ink, head, (232, 236, 244))
        ink.line([(0, 36), (0, 53)], (180, 186, 200), int(0.45 * PU))
        ink.poly(head, None, o)
        wings = [(0, 34.5), (5.5, 31), (4.2, 35.5), (0, 37), (-4.2, 35.5), (-5.5, 31)]
        ink.poly(wings, L["secondary"], o)
    elif weapon == "scythe":
        ink = _canvas(-6, -20, 22, 36)
        shaft = [(-1.1, -19), (1.1, -19), (1.1, 32), (-1.1, 32)]
        shade_limb(ink, shaft, 51, 2.4, (64, 42, 86))
        for y in (-18, -2, 26):
            ink.clip(shaft, [(-3, y), (3, y), (3, y + 1.2), (-3, y + 1.2)], (200, 196, 226))
        ink.poly(shaft, None, o)
        blade = path(((0.5, 30.5), (9, 33), (17, 28)), ((17, 28), (21, 22), (19.5, 15)),
                     ((19.5, 15), (17, 24), (9, 27.5)), ((9, 27.5), (4, 28.5), (0.5, 27.5)))
        ink.glow(14, 24, 7, L["secondary"], 90)
        metal(ink, blade, (206, 200, 236))
        ink.line(path(((1, 31), (9.5, 33.4), (17.4, 28.2)), ((17.4, 28.2), (21.2, 22), (19.6, 15.4))),
                 (255, 255, 255), int(0.6 * PU))
        ink.poly(blade, None, o)
        metal(ink, [(-2, 26.5), (2, 26.5), (2, 31.5), (-2, 31.5)], (200, 196, 226), hi=False)
    elif weapon == "pistols":
        ink = _canvas(-8, -4, 5, 17)
        grip = [(-1.6, -1), (-7, 0.5), (-7.5, 4.5), (-1.6, 4)]
        ink.poly(grip, (110, 70, 40), o)
        ink.line([(-6, 1.6), (-3, 1.2)], (80, 50, 26), int(0.4 * PU))
        barrel = [(-1.8, -2), (2.2, -2), (2.2, 16), (-1.8, 16)]
        metal(ink, barrel, (88, 90, 102))
        ink.poly(barrel, None, o)
        cyl = ellipse_pts(0.2, 3.5, 2.9, 3.4)
        metal(ink, cyl, (120, 122, 134))
        ink.poly(cyl, None, o)
        ink.line([(0.2, 7.5), (0.2, 15)], (160, 162, 175), int(0.4 * PU))
        ink.poly([(-1.8, 14.5), (-3, 15.5), (-1.8, 16)], (88, 90, 102), int(0.4 * PU))
    elif weapon == "claws":
        ink = _canvas(-6, -2, 6, 17)
        for x in (-3.2, 0, 3.2):
            blade = path(((x - 0.9, 1), (x - 0.4, 9), (x + 1.4, 16)), ((x + 1.4, 16), (x + 1.2, 9), (x + 0.9, 1)))
            metal(ink, blade, (236, 232, 214))
            ink.poly(blade, None, int(0.7 * PU))
        metal(ink, [(-5, -1), (5, -1), (5, 2.2), (-5, 2.2)], (110, 100, 90), hi=False)
        ink.poly([(-5, -1), (5, -1), (5, 2.2), (-5, 2.2)], None, int(0.7 * PU))
    else:                                   # gauntlets: flames are drawn live
        ink = _canvas(-1, -1, 1, 1)
    return _done(ink)


def part_extra(cid, P, which):
    L = art.look(cid)
    b = build(cid)
    if which == "cape":                      # pivot: upper back, hangs down
        ink = _canvas(-11, -2, 11, 36)
        cape = path(((-5, 0), (-9, 16), (-10.5, 33)), ((-10.5, 33), (-6, 31), (-2.5, 34.5)),
                    ((-2.5, 34.5), (1, 31), (4, 35)), ((4, 35), (7.5, 31), (9.5, 33)),
                    ((9.5, 33), (8, 16), (5, 0)), ((5, 0), (0, -1.5), (-5, 0)))
        base = (246, 246, 252)
        ink.poly(cape, base, 0)
        ink.clip(cape, [(-12, -2), (-3, -2), (-4, 36), (-12, 36)], (204, 208, 226))
        for x in (-3.5, 2.5):
            ink.line(path(((x, 4), (x + 1, 18), (x - 0.5, 31))), (196, 200, 220), int(0.5 * PU))
        ink.clip(cape, [(-12, 29), (12, 29), (12, 36), (-12, 36)], L["metal"])
        ink.poly(cape, None)
    elif which == "scarf":
        ink = _canvas(-4, -2, 6, 30)
        for dx, ln in ((0, 28), (3, 22)):
            tail = path(((dx - 1.6, 0), (dx - 2.8, ln * 0.5), (dx - 0.5, ln)), ((dx - 0.5, ln), (dx + 1.6, ln - 1.5), (dx + 2.2, ln - 4)),
                        ((dx + 2.2, ln - 4), (dx + 0.5, ln * 0.5), (dx + 1.8, 0)))
            ink.poly(tail, L["secondary"], 0)
            ink.clip(tail, [(dx - 4, -2), (dx, -2), (dx, ln + 2), (dx - 4, ln + 2)], darken(L["secondary"], 0.28))
            ink.poly(tail, None)
    elif which == "tail":
        ink = _canvas(-9, -2, 9, 30)
        tail = path(((-3, 0), (-7, 12), (-4.5, 22)), ((-4.5, 22), (-2, 28), (1.5, 29)),
                    ((1.5, 29), (5.5, 25), (4, 18)), ((4, 18), (2.5, 8), (3, 0)))
        ink.poly(tail, L["hair"], 0)
        ink.clip(tail, [(-10, -2), (-1, -2), (-1, 31), (-10, 31)], darken(L["hair"], 0.28))
        ink.clip(tail, [(-10, 20), (10, 20), (10, 31), (-10, 31)], lighten(L["hair"], 0.45))
        hair_strands(ink, tail, L["hair"], 14, -6, 5, 0, 26, 29, 0.25)
        ink.poly(tail, None)
    elif which == "coat":
        ink = _canvas(-11, -2, 7, 26)
        coat = path(((-8.5, 0), (-10.5, 12), (-10, 24)), ((-10, 24), (-6, 22.5), (-3, 25)),
                    ((-3, 25), (-1, 22), (2.5, 23.5)), ((2.5, 23.5), (4, 10), (4.5, 0)))
        base = (124, 80, 48)
        ink.poly(coat, base, 0)
        ink.clip(coat, [(-12, -2), (-5, -2), (-6, 27), (-12, 27)], darken(base, 0.28))
        ink.line(path(((-3, 2), (-4, 13), (-3.5, 22))), darken(base, 0.35), int(0.5 * PU))
        ink.poly(coat, None)
    elif which == "skirt":                   # luna: long robe skirt from the hips
        ink = _canvas(-15, -3, 15, 24)
        sk = path(((-9 * b, 0), (-12 * b, 10), (-14 * b, 21)), ((-14 * b, 21), (0, 23.5), (14 * b, 21)),
                  ((14 * b, 21), (12 * b, 10), (9 * b, 0)), ((9 * b, 0), (0, -1.5), (-9 * b, 0)))
        base = L["primary"]
        ink.poly(sk, base, 0)
        ink.clip(sk, [(-16, -3), (-4, -3), (-6, 25), (-16, 25)], darken(base, 0.28))
        ink.clip(sk, [(-16, 18.5), (16, 18.5), (16, 25), (-16, 25)], (214, 210, 236))
        for x in (-6, -1, 5):
            ink.line(path(((x * 0.6, 2), (x, 12), (x * 1.15, 19))), darken(base, 0.3), int(0.45 * PU))
        for x, y in ((-7, 8), (4, 13), (8, 6), (-2, 16)):
            ink.circle(x, y, 0.4, (240, 232, 255), 0)
        ink.poly(sk, None)
    elif which == "tassets":                 # aria: short armoured skirt
        ink = _canvas(-12, -3, 12, 12)
        for i, x in enumerate((-6.5, 0, 6.5)):
            pl = [(x - 4, 0), (x + 4, 0), (x + 3.5, 10), (x - 3.5, 10)]
            metal(ink, pl, L["metal"] if i != 1 else (238, 238, 248))
            ink.poly(pl, None, int(1.1 * PU))
    elif which == "pauldron":
        r = 6.5 * b
        ink = _canvas(-r - 2, -r - 2, r + 2, r + 2)
        pd = ellipse_pts(0, 0.5, r, r * 0.82)
        col = L["metal"] if cid == "titan" else (226, 230, 240)
        metal(ink, pd, lighten(col, 0.08))
        if cid == "titan":
            rivets(ink, [(-r * 0.5, 0), (r * 0.5, 0)], 0.8, col)
            ink.line([(-r * 0.8, r * 0.35), (r * 0.8, r * 0.35)], darken(col, 0.3), int(0.6 * PU))
        else:
            ink.line(path(((-r * 0.85, r * 0.3), (0, r * 0.75), (r * 0.85, r * 0.3))), L["metal"], int(0.9 * PU))
        ink.poly(pd, None)
    else:
        raise ValueError(which)
    return _done(ink)


EXTRAS = {"kira": ["scarf"], "titan": ["pauldron"], "vex": ["coat"], "luna": ["skirt"],
          "rex": ["tail"], "aria": ["cape", "tassets", "pauldron"]}


def build_parts(cid):
    P = palette(cid)
    parts = {"torso": part_torso(cid, P), "uarm": part_uarm(cid, P), "farm": part_farm(cid, P),
             "hand": part_hand(cid, P), "thigh": part_thigh(cid, P), "shin": part_shin(cid, P),
             "boot": part_boot(cid, P), "weapon": part_weapon(cid, P)}
    for e in EXTRAS.get(cid, []):
        parts[e] = part_extra(cid, P, e)
    return parts


# ---- sprite cache ------------------------------------------------------------
_masters = {}
_scaled = {}
BACK_DARK = (172, 168, 190)


def masters(cid):
    m = _masters.get(cid)
    if m is None:
        m = _masters[cid] = build_parts(cid)
    return m


def sprite(cid, name, s, f, mode=None, back=False):
    """Part scaled to s px/unit, mirrored for facing f, optionally darkened/flashed/tinted."""
    key = (cid, name, round(s, 3), f, mode, back)
    hit = _scaled.get(key)
    if hit is not None:
        return hit
    if mode is not None or back:                 # variants derive from the plain scaled sprite
        base, (px, py) = sprite(cid, name, s, f)
        img = base.copy()
    else:
        surf, (px, py) = masters(cid)[name]
        k = s / PU
        w, h = max(1, int(surf.get_width() * k)), max(1, int(surf.get_height() * k))
        img = pygame.transform.smoothscale(surf, (w, h))
        px, py = px * k, py * k
        if f < 0:
            img = pygame.transform.flip(img, True, False)
            px = w - px
    if back:
        img.fill((*BACK_DARK, 255), special_flags=pygame.BLEND_RGBA_MULT)
    if mode == "flash":
        img.fill((150, 150, 150, 0), special_flags=pygame.BLEND_RGB_ADD)
    elif mode == "hurt":
        img.fill((255, 196, 196, 255), special_flags=pygame.BLEND_RGBA_MULT)
        img.fill((46, 0, 0, 0), special_flags=pygame.BLEND_RGB_ADD)
    elif mode is not None:
        img.fill((255, 255, 255, 0), special_flags=pygame.BLEND_RGB_MAX)
        img.fill((*mode[:3], 255), special_flags=pygame.BLEND_RGBA_MULT)
    if pygame.display.get_surface() is not None:
        img = img.convert_alpha()
    if len(_scaled) > 3000:
        _scaled.clear()
    hit = _scaled[key] = (img, (px, py))
    return hit


def preload(s):
    for cid in C.ORDER:
        masters(cid)
        for f in (1, -1):
            for mode in (None, "flash", "hurt"):
                art.head_sprite(cid, HEAD_R * s, f, mode)
                for name in masters(cid):
                    sprite(cid, name, s, f, mode)
                    if name in ("uarm", "farm", "hand", "thigh", "shin", "boot"):
                        sprite(cid, name, s, f, mode, back=True)


_rot_cache = {}


def rotated(key, img, angle_deg):
    """Anti-aliased rotation, cached per whole degree (poses revisit the same angles constantly)."""
    q = int(round(angle_deg)) % 360
    if q == 0:
        return img, 0
    k = (key, q)
    rot = _rot_cache.get(k)
    if rot is None:
        if len(_rot_cache) > 12000:
            _rot_cache.clear()
        rot = _rot_cache[k] = pygame.transform.rotozoom(img, q, 1.0)
    return rot, q


def blit_part(surf, img, pivot, joint, angle_deg, key):
    """Rotate img about its pivot and place the pivot on joint (screen px)."""
    rot, q = rotated(key, img, angle_deg)
    w, h = img.get_size()
    ox, oy = pivot[0] - w / 2, pivot[1] - h / 2
    a = math.radians(q)
    rx = ox * math.cos(a) + oy * math.sin(a)
    ry = -ox * math.sin(a) + oy * math.cos(a)
    rw, rh = rot.get_size()
    surf.blit(rot, (joint[0] - rx - rw / 2, joint[1] - ry - rh / 2))


# ---- poses -------------------------------------------------------------------
MOVE_ANIM = {
    "jab":      {"from": (-1.2, -1.6), "to": (1.6, 1.75), "lean": 0.18, "thrust": True},
    "lunge":    {"from": (-0.8, -1.2), "to": (1.65, 1.6), "lean": 0.45, "crouch": 4, "thrust": True, "ext": 10},
    "sweep":    {"from": (-1.0, -1.5), "to": (1.25, 1.45), "lean": 0.32, "crouch": 9, "legs": "crouch"},
    "spike":    {"from": (2.9, 3.0), "to": (0.15, 0.0), "lean": 0.12, "legs": "air"},
    "launcher": {"wind": (0.3, 0.5, 0.25, 8), "from": (0.4, 0.7), "to": (2.95, 3.1), "lean": -0.18},
    "smash":    {"wind": (-2.6, -3.0, -0.28, 4), "from": (-2.6, -3.1), "to": (1.9, 1.5), "lean": 0.42, "ext": 6},
    "quake":    {"wind": (3.0, 3.1, -0.12, 2), "from": (3.0, 3.1), "to": (0.35, 0.25), "lean": 0.2, "crouch": 9},
    "cyclone":  {"wind": (-1.4, -1.3, 0.0, 2), "spin": True, "legs": "air"},
}


def ease_out(k):
    return 1 - (1 - k) ** 3


def _clamp01(v):
    return 0.0 if v < 0 else 1.0 if v > 1 else v


def attack_angles(cid, key, k):
    A = MOVE_ANIM[key]
    weapon = C.get(cid)["weapon"]
    if A.get("spin"):
        ang = 1.57 + ease_out(k) * math.tau * 1.25
        return ang, ang + 0.15, 0.0, 0.35
    if A.get("thrust") and weapon in ("spear", "pistols") + FIST_WEAPONS:
        return 1.55, 1.57, math.sin(min(1.0, k * 1.4) * math.pi) * (12 + A.get("ext", 0)), 0.1
    ke = ease_out(k)
    (fa0, wa0), (fa1, wa1) = A["from"], A["to"]
    return lerp(fa0, fa1, ke), lerp(wa0, wa1, ke), A.get("ext", 0) * ke, 0.35


def move_progress(action, key, at):
    m = G.MOVES[key]
    if action == G.A_LIGHT:
        return _clamp01(at / (m["startup"] + 2.5))
    return _clamp01(at / 2.5)


def lerp(a, b, t):
    return a + (b - a) * t


def idle_pose(cid, t):
    weapon = C.get(cid)["weapon"]
    breath = math.sin(t * 3.2)
    p = dict(fa=0.75, ba=-0.25, fbend=0.45, bbend=0.35, wa=2.35, bwa=1.0, lean=0.06, crouch=1.5 + breath * 0.7,
             ext=0.0, ffx=6.0, ffy=ANKLE_Y, bfx=-6.0, bfy=ANKLE_Y, head_tilt=breath * 0.02)
    if weapon == "spear":
        p.update(fa=1.05, wa=2.05, ba=0.7, bbend=0.5)
    elif weapon == "pistols":
        p.update(fa=0.55, wa=1.25, ba=0.2, bwa=1.1)
    elif weapon in FIST_WEAPONS:
        p.update(fa=0.55, fbend=1.5, ba=0.3, bbend=1.45, wa=2.2, bwa=2.0)
    elif weapon == "scythe":
        p.update(fa=0.9, wa=2.6)
    p["fa"] += breath * 0.04
    return p


def pose_for(cid, action, at, t, running, airborne, vy, mv, phase, tumble=False):
    """Target pose for the current state; the UI blends toward it."""
    kind = C.get(cid)["special"]["kind"]
    weapon = C.get(cid)["weapon"]
    p = idle_pose(cid, t)
    swing = None
    if airborne:
        rising = vy < 0
        p.update(fa=1.3, ba=-1.0, fbend=0.6, wa=2.3, crouch=0,
                 ffx=6, ffy=-12 if rising else -6, bfx=-6, bfy=-7 if rising else -10)
        if weapon in FIST_WEAPONS:
            p.update(fa=1.0, fbend=1.6, ba=-0.6)
    elif running:
        s, c = math.sin(phase), math.cos(phase)
        p.update(fa=0.45 + s * 0.75, ba=-0.25 - s * 0.75, fbend=0.7, bbend=0.7, wa=2.0 + s * 0.3,
                 lean=0.2, crouch=1.5 + abs(c) * 1.6,
                 ffx=s * 11, ffy=ANKLE_Y - max(0.0, c) * 6, bfx=-s * 11, bfy=ANKLE_Y - max(0.0, -c) * 6)
        if weapon in FIST_WEAPONS:
            p.update(fbend=1.4, bbend=1.4, fa=0.5 + s * 0.5, ba=0.2 - s * 0.5)

    key = mv if mv in MOVE_ANIM else ("jab" if action == G.A_LIGHT else "smash")
    A = MOVE_ANIM[key]
    if action in (G.A_LIGHT, G.A_HEAVY):
        k = move_progress(action, key, at)
        fa, wa, ext, bend = attack_angles(cid, key, k)
        p.update(fa=fa, wa=wa, ext=ext, fbend=bend, lean=A.get("lean", 0.0), crouch=A.get("crouch", 0.0),
                 ba=-0.9 + k * 0.3, bbend=0.5)
        legs = A.get("legs")
        if legs == "crouch" and not airborne:
            p.update(ffx=12, ffy=ANKLE_Y, bfx=-12, bfy=ANKLE_Y)
        elif legs == "air" or airborne:
            p.update(ffx=7, ffy=-11, bfx=-6, bfy=-8)
        else:
            p.update(ffx=10 * (0.4 + k * 0.6), bfx=-8, ffy=ANKLE_Y, bfy=ANKLE_Y)
        swing = (key, k)
    elif action == G.A_WINDUP:
        wk = _clamp01(at / max(1, G.MOVES[key]["startup"]))
        e = ease_out(min(1.0, wk * 1.6))
        tremble = math.sin(t * 45) * 0.06 * wk
        wfa, wwa, wlean, wcr = A["wind"]
        p.update(fa=lerp(p["fa"], wfa, e) + tremble, wa=lerp(p["wa"], wwa, e) + tremble,
                 lean=lerp(p["lean"], wlean, e), crouch=lerp(p["crouch"], wcr, e), ba=lerp(p["ba"], 0.8, e),
                 fbend=0.4)
        if A.get("legs") == "air" or airborne:
            p.update(ffx=6, ffy=-12, bfx=-6, bfy=-9)
        else:
            p.update(ffx=lerp(6, 11, e), bfx=lerp(-6, -10, e))
    elif action == G.A_SPECIAL:
        if kind == "projectile":
            p.update(fa=1.57, ba=1.45, fbend=0.05, bbend=0.1, wa=1.57, bwa=1.57, lean=0.12, ext=6)
        elif kind == "dash":
            p.update(fa=2.1, wa=1.75, lean=0.55, crouch=6, ffx=12, bfx=-12, ffy=ANKLE_Y, bfy=-6)
        elif kind == "pounce":
            p.update(fa=1.9, ba=1.7, fbend=0.2, bbend=0.2, wa=1.9, bwa=1.9, lean=0.5, ffx=-2, ffy=-10, bfx=-10, bfy=-5)
        elif kind == "rise":
            p.update(fa=3.1, ba=-2.6, wa=3.14, fbend=0.05, lean=-0.05, ffx=3, ffy=-6, bfx=-4, bfy=-2)
            swing = ("launcher", 1.0)
        elif kind == "slam":
            if vy < 0:
                p.update(fa=3.0, ba=2.8, wa=3.1, ffx=6, ffy=-12, bfx=-6, bfy=-9)
            else:
                p.update(fa=1.0, ba=0.9, wa=1.1, lean=0.25, ffx=6, ffy=-12, bfx=-6, bfy=-9)
        elif kind == "armor":
            p.update(fa=0.9, ba=0.9, fbend=2.1, bbend=2.1, wa=2.6, crouch=6, ffx=10, bfx=-10)
        elif kind == "pull":
            p.update(fa=1.57, ba=1.25, fbend=0.1, wa=2.5, lean=-0.15)
    elif action == G.A_DODGE:
        p.update(fa=1.8, ba=-1.6, wa=2.2, lean=0.42, crouch=8, ffx=9, bfx=-12, bfy=-6)
    elif action == G.A_STUN:
        if tumble:
            p.update(fa=2.6 + math.sin(t * 18) * 0.4, ba=-2.4 + math.cos(t * 18) * 0.4, fbend=0.3, bbend=0.3,
                     wa=3.6, lean=0.1, crouch=4, ffx=4, ffy=-14, bfx=-3, bfy=-11, head_tilt=0.2)
        else:
            p.update(fa=2.3, ba=-2.1, fbend=0.7, bbend=0.7, wa=3.4, lean=-0.4, head_tilt=-0.35, crouch=3,
                     ffx=9, bfx=-8)
            if airborne:
                p.update(ffy=-9, bfy=-6)
    elif action == art.V_VICTORY:
        p.update(fa=1.75 + math.sin(t * 4) * 0.08, fbend=0.6, ba=-0.6, wa=2.9, lean=-0.05, head_tilt=-0.1)
    p["swing"] = swing
    return p


def blend(cur, target, k):
    """Move pose `cur` toward `target` by fraction k (angles take the short way round)."""
    out = dict(target)
    if cur is None:
        return out
    for key in POSE_KEYS:
        a, b = cur[key], target[key]
        if key in ANGLE_KEYS:
            d = (b - a + math.pi) % math.tau - math.pi
            out[key] = a + d * k
        else:
            out[key] = a + (b - a) * k
    return out


# ---- skeleton & drawing --------------------------------------------------------
def _rot(x, y, a, cx=0.0, cy=-30.0):
    """Rotate (x, y) clockwise by a about (cx, cy)."""
    dx, dy = x - cx, y - cy
    c, s = math.cos(a), math.sin(a)
    return cx + dx * c - dy * s, cy + dx * s + dy * c


def _ik(hip, foot, l1=THIGH, l2=SHIN):
    hx, hy = hip
    fx, fy = foot
    dx, dy = fx - hx, fy - hy
    d = max(2.0, min(l1 + l2 - 0.01, math.hypot(dx, dy)))
    base = math.atan2(dy, dx)
    cosk = (l1 * l1 + d * d - l2 * l2) / (2 * l1 * d)
    phi = math.acos(max(-1.0, min(1.0, cosk)))
    cands = [(hx + math.cos(base - phi) * l1, hy + math.sin(base - phi) * l1),
             (hx + math.cos(base + phi) * l1, hy + math.sin(base + phi) * l1)]
    knee = max(cands, key=lambda k: k[0])        # knees bend forward
    ex = hx + math.cos(base) * d
    ey = hy + math.sin(base) * d
    return knee, (ex, ey)


def _ang(a, b):
    """Local down-axis angle (0 = down, + = forward) of the segment a -> b."""
    return math.atan2(b[0] - a[0], b[1] - a[1])


def skeleton(pose, rot=0.0, sq=1.0):
    """Joint positions/angles in the local frame (before mirroring)."""
    lean = pose["lean"]
    tilt = lean * 0.75
    crouch = pose["crouch"]
    hip = (0.0, HIP_Y + crouch)

    def tor(x, y):                              # torso-local -> body local
        c, s = math.cos(tilt), math.sin(tilt)
        return hip[0] + x * c - y * s, hip[1] + x * s + y * c

    neck = tor(0, -TORSO_LEN)
    sh_f, sh_b = tor(1.8, -TORSO_LEN + 5), tor(-2.4, -TORSO_LEN + 5.5)
    hip_f, hip_b = tor(2.0, -1.0), tor(-2.2, -1.0)
    J = {"hip": hip, "neck": neck, "sh_f": sh_f, "sh_b": sh_b}

    def arm(sh, th, bend, ext):
        l1, l2 = UARM + ext * 0.5, FARM + ext * 0.5
        el = (sh[0] + math.sin(th) * l1, sh[1] + math.cos(th) * l1)
        hd = (el[0] + math.sin(th + bend) * l2, el[1] + math.cos(th + bend) * l2)
        return el, hd

    J["el_f"], J["hd_f"] = arm(sh_f, pose["fa"], pose["fbend"], pose["ext"])
    J["el_b"], J["hd_b"] = arm(sh_b, pose["ba"], pose["bbend"], 0.0)
    J["kn_f"], J["an_f"] = _ik(hip_f, (pose["ffx"], pose["ffy"]))
    J["kn_b"], J["an_b"] = _ik(hip_b, (pose["bfx"], pose["bfy"]))
    J["hip_f"], J["hip_b"] = hip_f, hip_b
    J["back"] = tor(-5.0, -TORSO_LEN + 4)
    J["tailbase"] = tor(-6.0, -4.0)
    J["head"] = tor(0.8, -TORSO_LEN - HEAD_R * 1.08)
    if sq != 1.0:
        for k, (x, y) in J.items():
            J[k] = (x / math.sqrt(sq), y * sq)
    if rot:
        for k, (x, y) in J.items():
            J[k] = _rot(x, y, rot)
    J["tilt"] = tilt + rot
    J["rot"] = rot
    return J


def weapon_tip(cid, J, wa, f, s, sx, sy):
    reach = REACH[C.get(cid)["weapon"]]
    th = wa - J["rot"]
    hx, hy = J["hd_f"]
    tip = (hx + math.sin(th) * reach, hy + math.cos(th) * reach)
    mid = (hx + math.sin(th) * reach * 0.7, hy + math.cos(th) * reach * 0.7)
    return ((sx + tip[0] * f * s, sy + tip[1] * s), (sx + mid[0] * f * s, sy + mid[1] * s))


def draw(surf, cid, sx, sy, s, f, pose, t=0.0, mode=None, rot=0.0, sq=1.0, vx=0.0,
         trail_col=None, armor=False, glow_weapon=False):
    """Draw a posed fighter with its feet at screen (sx, sy); s = screen px per unit."""
    J = skeleton(pose, rot, sq)

    def S(p):
        return (sx + p[0] * f * s, sy + p[1] * s)

    def put(name, joint, local_angle, back=False, up_axis=False):
        img, piv = sprite(cid, name, s, f, mode, back)
        deg = (-math.degrees(local_angle) if up_axis else math.degrees(local_angle)) * f
        blit_part(surf, img, piv, S(joint), deg, (cid, name, round(s, 3), f, mode, back))

    weapon = C.get(cid)["weapon"]
    extras = EXTRAS.get(cid, [])
    speed = max(-1.0, min(1.0, vx * f / 450.0))
    sway = math.sin(t * 3.1) * 0.07
    L = art.look(cid)

    if armor and mode is None:
        art.glow(surf, L["secondary"], S((0, -32)), 52 * s, int(110 + 60 * math.sin(t * 10)))

    # behind the body
    if "cape" in extras:
        put("cape", J["back"], -0.28 - max(0.0, speed) * 0.9 + sway - J["rot"])
    if "scarf" in extras:
        put("scarf", J["back"], -0.9 - max(0.0, speed) * 0.6 + sway * 2 - J["rot"])
    if "tail" in extras:
        put("tail", J["tailbase"], -1.0 + math.sin(t * 5) * 0.25 - max(0.0, speed) * 0.4 - J["rot"])
    if "coat" in extras:
        put("coat", J["hip"], -0.12 - max(0.0, speed) * 0.7 + sway - J["rot"])

    # back arm, back leg
    put("uarm", J["sh_b"], _ang(J["sh_b"], J["el_b"]), back=True)
    put("farm", J["el_b"], _ang(J["el_b"], J["hd_b"]), back=True)
    if weapon in DUAL and weapon != "gauntlets":
        put("weapon", J["hd_b"], pose["bwa"] - J["rot"], back=True)
    put("hand", J["hd_b"], _ang(J["el_b"], J["hd_b"]), back=True)
    put("thigh", J["hip_b"], _ang(J["hip_b"], J["kn_b"]), back=True)
    put("shin", J["kn_b"], _ang(J["kn_b"], J["an_b"]), back=True)
    put("boot", J["an_b"], (J["rot"] + _ang(J["kn_b"], J["an_b"]) * -0.25), back=True, up_axis=True)

    put("torso", J["hip"], J["tilt"], up_axis=True)

    put("thigh", J["hip_f"], _ang(J["hip_f"], J["kn_f"]))
    put("shin", J["kn_f"], _ang(J["kn_f"], J["an_f"]))
    put("boot", J["an_f"], (J["rot"] + _ang(J["kn_f"], J["an_f"]) * -0.25), up_axis=True)
    if "skirt" in extras:
        put("skirt", J["hip"], -max(0.0, speed) * 0.25 + sway * 0.4 - J["rot"])
    if "tassets" in extras:
        put("tassets", J["hip"], -max(0.0, speed) * 0.15 - J["rot"])

    # head (shares the portrait art)
    hs = art.head_sprite(cid, HEAD_R * s, f, mode)
    tilt_deg = -math.degrees(J["tilt"] * 0.6 + pose["head_tilt"]) * f
    hrot, _ = rotated(("head", cid, round(s, 3), f, mode), hs, tilt_deg)
    hx, hy = S(J["head"])
    surf.blit(hrot, (hx - hrot.get_width() / 2, hy - hrot.get_height() / 2))

    # weapon smear behind the front arm
    if pose.get("swing") and trail_col and mode is None:
        _smear(surf, cid, pose, J, f, s, sx, sy, trail_col)

    # front arm + weapon
    put("uarm", J["sh_f"], _ang(J["sh_f"], J["el_f"]))
    if "pauldron" in extras:
        put("pauldron", J["sh_f"], _ang(J["sh_f"], J["el_f"]) * 0.35)
    put("farm", J["el_f"], _ang(J["el_f"], J["hd_f"]))
    if weapon != "gauntlets":
        put("weapon", J["hd_f"], pose["wa"] - J["rot"])
    put("hand", J["hd_f"], _ang(J["el_f"], J["hd_f"]))
    if glow_weapon and mode is None:
        tip, _ = weapon_tip(cid, J, pose["wa"], f, s, sx, sy)
        art.glow(surf, L["secondary"], tip, 22 * s, 140)
    if weapon == "gauntlets" and mode is None:
        for hand in ("hd_f", "hd_b"):
            hx, hy = S(J[hand])
            fl = 0.8 + 0.2 * math.sin(t * 20 + (hand == "hd_b"))
            art.glow(surf, (255, 130, 40), (hx, hy + 4 * s), 12 * s * fl, 150)
    return J


def _smear(surf, cid, pose, J, f, s, sx, sy, col):
    key, k = pose["swing"]
    A = MOVE_ANIM[key]
    if k >= 1.0 and not A.get("spin"):
        return
    weapon = C.get(cid)["weapon"]
    if A.get("thrust") and weapon in ("spear", "pistols") + FIST_WEAPONS:
        tip, _ = weapon_tip(cid, J, pose["wa"], f, s, sx, sy)
        for i in range(4):
            y = tip[1] + (i - 1.5) * 4 * s
            pygame.draw.line(surf, col, (tip[0] - f * (30 + i * 8) * s, y), (tip[0] - f * 6 * s, y), max(1, int(2 * s)))
        return
    tips, mids = [], []
    span = 0.3 if A.get("spin") else 0.34
    for i in range(8):
        kk = max(0.0, k - span * i / 7)
        fa, wa, ext, bend = attack_angles(cid, key, kk)
        p2 = dict(pose, fa=fa, wa=wa, ext=ext, fbend=bend)
        J2 = skeleton(p2, J["rot"])
        tip, mid = weapon_tip(cid, J2, wa, f, s, sx, sy)
        tips.append(tip)
        mids.append((lerp(mid[0], tip[0], i / 7), lerp(mid[1], tip[1], i / 7)))
    pts = tips + mids[::-1]
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    x0, y0 = int(min(xs)) - 4, int(min(ys)) - 4
    w, h = int(max(xs)) - x0 + 8, int(max(ys)) - y0 + 8
    if w < 3 or h < 3 or w > 2000 or h > 2000:
        return
    layer = pygame.Surface((w, h), pygame.SRCALPHA)
    local = [(x - x0, y - y0) for x, y in pts]
    pygame.draw.polygon(layer, (*col[:3], 150), local)
    pygame.draw.lines(layer, (*lighten(col, 0.7), 235), False, local[:len(tips)], max(2, int(2.4 * s)))
    surf.blit(layer, (x0, y0))
