"""Procedurally synthesized sound effects (no asset files needed).

If the audio device is unavailable everything degrades to silent no-ops.
"""
import array
import math
import random

import pygame

RATE = 22050


def _env(i, n, attack=0.01):
    a = int(n * attack) or 1
    return i / a if i < a else (1 - (i - a) / max(1, n - a)) ** 2


def _noise_hit(rng, dur, freq, noise_amt):
    n = int(RATE * dur)
    out, lp = [], 0.0
    for i in range(n):
        t = i / RATE
        lp += (rng.uniform(-1, 1) - lp) * 0.35
        f = freq * (1 - 0.5 * i / n)
        s = math.sin(2 * math.pi * f * t) * (1 - noise_amt) + lp * noise_amt * 2
        out.append(s * _env(i, n, 0.005))
    return out


def _sweep(dur, f0, f1, square=False, vol=1.0):
    n = int(RATE * dur)
    out, ph = [], 0.0
    for i in range(n):
        f = f0 + (f1 - f0) * i / n
        ph += 2 * math.pi * f / RATE
        s = math.sin(ph)
        if square:
            s = 0.6 if s > 0 else -0.6
        out.append(s * _env(i, n, 0.05) * vol)
    return out


def _whoosh(rng, dur):
    n = int(RATE * dur)
    out, lp = [], 0.0
    for i in range(n):
        cutoff = 0.05 + 0.4 * math.sin(math.pi * i / n)
        lp += (rng.uniform(-1, 1) - lp) * cutoff
        out.append(lp * math.sin(math.pi * i / n) * 1.6)
    return out


def _mix(*tracks):
    n = max(len(t) for t in tracks)
    return [sum(t[i] for t in tracks if i < len(t)) / len(tracks) * 1.4 for i in range(n)]


def _chord(dur, freqs):
    n = int(RATE * dur)
    return [sum(math.sin(2 * math.pi * f * i / RATE) for f in freqs) / len(freqs) * _env(i, n, 0.02)
            for i in range(n)]


class Sfx:
    def __init__(self):
        self.ok = False
        self.sounds = {}
        global RATE
        try:
            if not pygame.mixer.get_init():
                pygame.mixer.init(RATE, -16, 1, 512)
            RATE, _, self.channels = pygame.mixer.get_init()   # synthesize at the device rate
            self._build()
            self.ok = True
        except (pygame.error, TypeError):
            pass

    def _make(self, samples, vol=0.5):
        buf = array.array("h")
        for s in samples:
            v = int(max(-1.0, min(1.0, s)) * 32767 * vol)
            buf.extend([v] * self.channels)
        return pygame.mixer.Sound(buffer=buf.tobytes())

    def _build(self):
        rng = random.Random(7)
        self.sounds = {
            "hit": self._make(_noise_hit(rng, 0.13, 160, 0.6), 0.55),
            "heavy": self._make(_mix(_noise_hit(rng, 0.28, 90, 0.5), _sweep(0.2, 220, 60)), 0.75),
            "ko": self._make(_mix(_noise_hit(rng, 0.8, 55, 0.7), _sweep(0.7, 600, 40)), 0.85),
            "swing": self._make(_whoosh(rng, 0.14), 0.30),
            "heavy_swing": self._make(_whoosh(rng, 0.24), 0.40),
            "jump": self._make(_sweep(0.09, 280, 620, square=True, vol=0.5), 0.18),
            "dodge": self._make(_whoosh(rng, 0.18), 0.30),
            "special": self._make(_mix(_sweep(0.32, 200, 900), _whoosh(rng, 0.32)), 0.45),
            "shot": self._make(_noise_hit(rng, 0.09, 900, 0.8), 0.35),
            "fire": self._make(_mix(_whoosh(rng, 0.35), _sweep(0.35, 120, 70)), 0.5),
            "shock": self._make(_noise_hit(rng, 0.45, 50, 0.6), 0.85),
            "select": self._make(_sweep(0.06, 880, 1100, square=True), 0.18),
            "click": self._make(_sweep(0.04, 600, 500, square=True), 0.15),
            "beep": self._make(_sweep(0.16, 660, 660), 0.45),
            "go": self._make(_chord(0.6, [523, 659, 784, 1046]), 0.5),
            "victory": self._make(_chord(1.2, [392, 494, 587, 784]), 0.45),
            "respawn": self._make(_sweep(0.25, 400, 1200), 0.25),
        }

    def play(self, name, vol=1.0):
        if not self.ok:
            return
        snd = self.sounds.get(name)
        if snd is not None:
            ch = snd.play()
            if ch is not None:
                ch.set_volume(max(0.0, min(1.0, vol)))
