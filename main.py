from __future__ import annotations

import json
import math
import random
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

import pygame as pg

ROOT = Path(__file__).resolve().parent
ASSETS = ROOT / "assets"
WIDTH, HEIGHT = 640, 360
PIXELS = 3
FULL_HD = WIDTH * PIXELS, HEIGHT * PIXELS
ARENA = pg.Rect(32, 64, 576, 248)
INK = "#191923"
PAPER = "#efe2c9"
MUTED = "#aba4a6"
CYAN = "#abd2ac"
GOLD = "#f4bd71"
RED = "#fa797d"
V2 = pg.Vector2
MELEE_REACH = 43
MELEE_INTERVAL = 0.46
MELEE_FLASH = 0.18
MELEE_DAMAGE = 32
SECRET_CODE = "6koilmi6"
CAMPAIGN_BOSS_HP = (840, 1120, 1420)
SECRET_BOSS_HP = CAMPAIGN_BOSS_HP[-1] * 50
DEMON_CORE_TIME = 2.55
DEMON_CORE_MULTIPLIER = 26
RAPIER_CHARGE = 0.58


def image(path):
    return pg.image.load(ASSETS / path).convert_alpha()


def clip_position(pos, radius, barriers):
    bounds = ARENA.inflate(-radius * 2, -radius * 2)
    point = V2(max(bounds.left, min(pos.x, bounds.right)),
               max(bounds.top, min(pos.y, bounds.bottom)))
    body = pg.Rect(0, 0, radius * 2, radius * 2)
    body.center = point
    return point, body.collidelist(barriers) == -1


def move(pos, delta, radius, barriers):
    """Resolve along each axis so characters slide along corners."""
    x, clear = clip_position(pos + (delta.x, 0), radius, barriers)
    if clear:
        pos = x
    y, clear = clip_position(pos + (0, delta.y), radius, barriers)
    return y if clear else pos
