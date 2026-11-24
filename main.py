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


# Combat ----------------------------------------------------------------------
@dataclass(frozen=True)
class Weapon:
    name: str
    magazine: int
    damage: int
    interval: float
    reload_time: float
    speed: int
    color: str
    note: str
    angles: tuple[int, ...] = (0,)
    piercing: int = 0
    blast: int = 0


WEAPONS = {
    "pistol": Weapon("Искра", 12, 17, .20, .73, 460, GOLD,
                     "Попадания подряд в цель наращивают урон"),
    "scatter": Weapon("Осколок", 7, 10, .46, 1.0, 385, "#e0aeff",
                      "Пять осколков отскакивают от стен", (-24,-12,0,12,24)),
    "pulse": Weapon("Импульс", 24, 12, .18, .98, 500, CYAN,
                    "При удержании ЛКМ скорострельность растёт"),
    "coil": Weapon("Струна", 9, 38, .34, 1.00, 600, "#9ec6ff",
                   "Разряд перескакивает между врагами"),
    "nova": Weapon("Жаровня", 5, 24, .52, 1.14, 335, "#ff9e72",
                   "Попадание оставляет горящую лужу"),
    "rapier": Weapon("Рапира", 6, 94, .26, 1.32, 850, "#e3f0f2",
                     "Удерживай ЛКМ для заряженного пробоя", piercing=3),
    "locust": Weapon("Саранча", 36, 9, .085, 1.40, 420, "#d8dc77",
                     "Снаряды сами доводятся до ближних целей"),
    "frost": Weapon("Иней", 15, 22, .22, .89, 535, "#96e0ed",
                    "Три попадания замораживают обычного врага"),
    "anvil": Weapon("Кувалда", 4, 105, .66, 1.42, 290, "#ffae67",
                    "Навесной снаряд взрывается в точке прицела", blast=51),
    "saw": Weapon("Циркуляр", 13, 27, .29, 1.22, 335, "#aadc93",
                  "Диск возвращается и может ударить дважды", piercing=4),
    "fork": Weapon("Трезубец", 12, 25, .29, 1.04, 455, "#86bfdc",
                   "Один снаряд делится на три в полёте"),
    "salt": Weapon("Картечь", 5, 14, .50, 1.20, 420, "#f5dba1",
                   "Бьёт в упор и отбрасывает отдачей", (-26,-17,-8,0,8,17,26)),
    "comet": Weapon("Комета", 8, 28, .34, 1.26, 345, "#ef9fb7",
                    "Снаряд разгоняется и усиливается на дистанции"),
    "eclipse": Weapon("Затмение", 7, 31, .44, 1.16, 455, "#c9a8ec",
                      "Воронка стягивает врагов и схлопывается"),
    "ember": Weapon("Уголёк", 20, 16, .14, .81, 445, "#fa8869",
                    "Каждая третья метка на цели взрывается"),
}


@dataclass
class Magazine:
    name: str
    rounds: int
    reserve: int | None


@dataclass
class Bullet:
    pos: V2
    vel: V2
    damage: int
    color: str
    hostile: bool = False
    ttl: float = 1.4
    piercing: int = 0
    blast: int = 0
    hit_targets: set = field(default_factory=set)
    curve: float = 0
    weapon: str = ""
    age: float = 0.0
    distance: float = 0.0
    bounced: bool = False
    returning: bool = False
    destination: V2 | None = None


@dataclass
class WeaponField:
    kind: str
    pos: V2
    radius: int
    ttl: float
    damage: int
    next_tick: float = 0.0
