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


HEROES = {
    "hero": ("Искатель", 100, 163),
    "guard": ("Дозорная", 125, 145),
}


class Player:
    def __init__(self, hero="hero"):
        self.pos = V2(150, 188)
        self.moving = False
        self.left = False
        self.hero = hero
        _, self.max_hp, self.speed = HEROES[hero]
        self.hp = self.max_hp
        self.aim = V2(1, 0)
        self.aim_point = self.pos + (100, 0)
        self.slots = [Magazine("pistol", WEAPONS["pistol"].magazine, None), None]
        self.active = 0
        self.cooldown = 0.0
        self.reload = 0.0
        self.invulnerable = 0.0
        self.hurt_flash = 0.0
        self.flash = 0.0
        self.melee_timer = 0.0
        self.melee_flash = 0.0
        self.slash_direction = self.aim.copy()
        self.power = 0
        self.spin = 0.0
        self.charge = 0.0
        self.focus_target = None
        self.focus_hits = 0

    @property
    def clip(self):
        return self.slots[self.active]

    @property
    def selected(self):
        return self.clip.name

    @property
    def weapon(self):
        return WEAPONS[self.selected]

    def magazine_for(self, name):
        return next((clip for clip in self.slots if clip and clip.name == name), None)

    def steer(self, direction, dt, barriers):
        self.moving = direction.length_squared() > 0
        if self.moving:
            self.pos = move(self.pos, direction.normalize() * self.speed * dt, 8, barriers)

    def tick(self, dt, aim, firing=False):
        self.aim_point = aim
        self.aim = unit(aim - self.pos, self.aim)
        self.left = self.aim.x < 0
        self.cooldown = max(0.0, self.cooldown - dt)
        self.invulnerable = max(0.0, self.invulnerable - dt)
        self.hurt_flash = max(0.0, self.hurt_flash - dt)
        self.flash = max(0.0, self.flash - dt)
        self.melee_timer = max(0.0, self.melee_timer - dt)
        self.melee_flash = max(0.0, self.melee_flash - dt)
        if self.selected == "pulse" and firing and self.clip.rounds and not self.reload:
            self.spin = min(1.0, self.spin + dt * 1.8)
        else:
            self.spin = max(0.0, self.spin - dt * 2.8)
        if self.selected == "rapier" and firing and self.clip.rounds and not self.reload:
            self.charge = min(RAPIER_CHARGE, self.charge + dt)
        else:
            self.charge = 0.0
        if self.reload <= 0:
            return
        self.reload = max(0.0, self.reload - dt)
        if self.reload == 0:
            clip = self.clip
            missing = self.weapon.magazine - clip.rounds
            refill = missing if clip.reserve is None else min(missing, clip.reserve)
            if not refill and clip.rounds == 0 and self.out_of_ammo():
                clip.reserve = min(5, self.weapon.magazine)
                refill = clip.reserve
            clip.rounds += refill
            if clip.reserve is not None:
                clip.reserve -= refill

    def select(self, slot):
        if 0 <= slot < len(self.slots) and self.slots[slot] is not None and self.active != slot:
            self.active = slot
            self.reload = 0
            self.reset_weapon_state()

    def reset_weapon_state(self):
        self.spin = self.charge = 0.0
        self.focus_target = None
        self.focus_hits = 0

    def out_of_ammo(self):
        return all(not clip or (clip.rounds == 0 and clip.reserve == 0) for clip in self.slots)

    def start_reload(self):
        clip = self.clip
        if self.reload == 0 and clip.rounds < self.weapon.magazine:
            if clip.reserve != 0:
                self.reload = self.weapon.reload_time
            elif self.out_of_ammo():
                # A slow emergency refill prevents a locked arena with two dry weapons.
                self.reload = 2.3

    def shoot(self):
        if self.cooldown > 0 or self.reload > 0:
            return []
        clip = self.clip
        if clip.rounds == 0:
            self.start_reload()
            return []
        key = self.selected
        if key == "rapier" and self.charge < RAPIER_CHARGE:
            return []
        self.charge = 0.0
        clip.rounds -= 1
        self.cooldown = self.weapon.interval - (0.116 * self.spin if key == "pulse" else 0)
        self.flash = 0.11
        target = clip_position(self.aim_point, 10, ())[0] if key == "anvil" else None
        return [Bullet(self.pos.copy(), self.aim.rotate(angle) * self.weapon.speed,
                       self.weapon.damage + self.power, self.weapon.color, ttl=2.15 if key=="saw" else 1.4,
                       piercing=self.weapon.piercing, blast=self.weapon.blast,
                       weapon=key, destination=target)
                for angle in self.weapon.angles]

    def swing(self):
        if self.melee_timer > 0:
            return False
        self.melee_timer = MELEE_INTERVAL
        self.melee_flash = MELEE_FLASH
        self.slash_direction = self.aim.copy()
        return True

    def hurt(self, amount):
        if self.invulnerable or self.hp <= 0:
            return False
        self.hp = max(0, self.hp - amount)
        self.invulnerable = 0.68
        self.hurt_flash = 0.18
        return True


def unit(delta, default=(0, 0)):
    return delta.normalize() if delta.length_squared() else V2(default)


@dataclass
class Hazard:
    point: V2
    wait: float
    radius: int
    damage: int
    end: V2 | None = None


class Enemy:
    # Crawler pursues, sentry fires from range, wisp warns before each lunge.
    SPECS = {"crawler": (37, 62, 9), "sentry": (49, 54, 10), "wisp": (34, 82, 11),
             "shield": (69, 56, 13), "alchemist": (50, 49, 12),
             "moth": (34, 83, 9), "spitter": (53, 48, 12),
             "stalker": (58, 94, 14), "prism": (48, 57, 13), "oracle": (67, 46, 14)}

    def __init__(self, kind, pos, level=1):
        self.kind = kind
        self.pos = V2(pos)
        health, speed, damage = self.SPECS[kind]
        self.max_hp = health + (level - 1) * 4
        self.hp = self.max_hp
        self.speed = speed + (level - 1) * 1.7
        self.damage = damage + (level - 1) // 2
        self.radius = 10
        self.timer = 0.7 + (self.pos.x % 30) / 30
        self.burst = 0.0
        self.dash = V2()
        self.flash = 0.0
        self.attacking = False
        self.moving = False
        self.left = False
        self.facing = V2(1, 0)
        self.warning = self.explosion = None
        self.blast_radius = 32
        self.level = level
        self.shot_direction = V2(1, 0)
        self.hazards = []
        self.orbit = -1 if self.pos.x % 2 else 1
        self.frost_marks = self.ember_marks = 0
        self.frost_window = self.ember_window = self.frozen = 0.0

    def receive_shot(self, bullet, damage):
        frontal = self.kind == "shield" and self.facing.dot(-unit(bullet.vel)) > 0.42
        if frontal and not self.attacking and not bullet.blast:
            damage = max(2, damage // 3)
        self.receive_hit(damage)

    def receive_hit(self, damage):
        self.hp -= damage
        self.flash = 0.18

    def tick_status(self, dt):
        self.frost_window = max(0, self.frost_window - dt)
        self.ember_window = max(0, self.ember_window - dt)
        self.frozen = max(0, self.frozen - dt)
        if not self.frost_window:
            self.frost_marks = 0
        if not self.ember_window:
            self.ember_marks = 0

    def specialist(self, dt, player, delta, distance, direction, obstructed):
        """Lock the aim during windup, then commit to the move or shot."""
        shots = []
        if self.kind == "stalker":
            if self.burst > 0:
                self.burst = max(0.0, self.burst - dt)
                return self.dash * 3.15, shots
            if self.attacking or (self.timer <= 0.43 and distance < 150 and not obstructed):
                if not self.attacking:
                    self.shot_direction = unit(delta, self.shot_direction)
                self.attacking = self.timer > 0
                if self.attacking:
                    return -direction * 0.42, shots
                self.burst, self.dash, self.timer = 0.29, self.shot_direction, 1.56
                self.orbit *= -1
                return self.dash * 3.15, shots
            self.timer = max(0.18, self.timer)
            return direction.rotate(self.orbit * (50 if distance < 175 else 22)), shots

        # Ranged specialists retreat in open space and close in around cover.
        if distance < 116 and not obstructed:
            direction *= -0.76
        elif distance < 205 and not obstructed:
            direction = direction.rotate(self.orbit * 85) * 0.69
        windup = 0.60 if self.kind == "oracle" else 0.48
        can_attack = distance < 240 and (self.kind == "oracle" or not obstructed)
        if not self.attacking and self.timer <= windup and can_attack:
            self.attacking = True
            self.shot_direction = unit(delta, self.shot_direction)
            if self.kind == "oracle":
                offset = self.shot_direction.rotate(90) * 33
                for point, delay in ((player.pos, 0), (player.pos + offset, 0.24)):
                    point, _ = clip_position(point, 16, ())
                    self.hazards.append(Hazard(point, max(0.25, self.timer) + delay, 26, self.damage))
        if self.attacking and self.timer <= 0:
            self.attacking = False
            self.timer = 2.38 if self.kind == "oracle" else 1.76
            if self.kind == "prism":
                for angle, curve in ((-33, 92), (0, 0), (33, -92)):
                    shots.append(Bullet(self.pos.copy(), self.shot_direction.rotate(angle) * 202,
                                        self.damage, "#c0a5f0", True, 3, curve=curve))
            self.orbit *= -1
        return direction, shots

    def step(self, dt, player, barriers):
        self.flash = max(0.0, self.flash - dt)
        self.timer -= dt
        delta = player.pos - self.pos
        distance = delta.length()
        direction = unit(delta)
        self.facing = direction
        self.explosion = None
        self.left = delta.x < 0
        obstacle = next((rect for rect in barriers if rect.clipline(self.pos, player.pos)), None)
        obstructed = obstacle is not None
        bullets = []
        advanced = self.kind in ("stalker", "prism", "oracle")
        if advanced:
            direction, bullets = self.specialist(dt, player, delta, distance, direction, obstructed)
        else:
            self.attacking = False
        if self.kind == "sentry":
            if distance < 135 and not obstructed:
                direction *= -0.78
            elif distance < 190 and not obstructed:
                direction = direction.rotate(90) * 0.6
            self.attacking = self.timer < 0.28 and not obstructed
            if self.timer <= 0 and not obstructed:
                bullets.append(Bullet(self.pos.copy(), unit(delta, (1, 0)) * 165,
                                      self.damage, "#e3a2fa", True, 3))
                self.timer = 1.45
        if self.kind in ("moth", "spitter"):
            if distance < 118 and not obstructed:
                direction *= -0.75
            elif distance < 216 and not obstructed:
                turn = -90 if self.kind == "moth" else 80
                direction = direction.rotate(turn) * 0.75
            windup = 0.50 if self.kind == "spitter" else 0.40
            self.attacking = self.timer <= windup and not obstructed
            if self.attacking:
                self.shot_direction = unit(delta, self.shot_direction)
            if self.timer <= 0 and not obstructed:
                if self.kind == "moth":
                    angles, speed, color, self.timer = (-13, 13), 196, "#b9b6f0", 1.90
                else:
                    angles, speed, color, self.timer = (-19, 0, 19), 163, "#c8dd83", 2.20
                for angle in angles:
                    velocity = self.shot_direction.rotate(angle) * speed
                    bullets.append(Bullet(self.pos.copy(), velocity, self.damage, color, True, 3))
        if self.kind == "alchemist":
            if distance < 118 and not obstructed:
                direction *= -0.62
            elif distance < 178 and not obstructed:
                direction = direction.rotate(-90) * 0.65
            self.attacking = self.warning is not None or self.timer < 0.56
            if self.timer < 0.56 and self.warning is None:
                self.warning = player.pos.copy()
            if self.timer <= 0:
                self.explosion = self.warning
                self.warning = None
                self.timer = 2.50 - 0.045 * self.level
        if self.kind == "crawler" and distance > 117 and self.burst <= 0:
            self.timer = max(self.timer, 0.62)
        if self.kind in ("crawler", "wisp", "shield"):
            self.attacking = self.timer < 0.36 and self.burst <= 0
            if self.burst > 0:
                self.burst = max(0.0, self.burst - dt)
                direction = self.dash * 2.9
            elif self.timer <= 0:
                self.burst, self.dash, self.timer = 0.30, direction, 2.15
                direction *= 2.9
            elif self.timer < 0.36:
                direction = V2()
        if obstacle is not None and not self.burst and direction.dot(unit(delta)) > 0.35:
            direction = route_around(self.pos, player.pos, obstacle, self.radius, barriers)
        previous = self.pos
        displacement = direction * self.speed * dt
        self.pos = move(self.pos, displacement, self.radius, barriers)
        if (self.pos - previous).length_squared() < 0.05 and displacement.length_squared() > 0:
            bypass = displacement.rotate(65 if int(self.timer * 2) % 2 else -65)
            self.pos = move(self.pos, bypass, self.radius, barriers)
        self.moving = (self.pos - previous).length_squared() > 0.05
        return bullets


def target_rect(pos, radius):
    rect = pg.Rect(0, 0, radius * 2, radius * 2)
    rect.center = pos
    return rect


def segment_hit(start, end, rect):
    hit = rect.clipline(start, end)
    return (V2(hit[0]) - start).length_squared() if hit else float("inf")


def terrain_hit(start, end, barriers):
    """Return the first surface and its outward normal, including the arena rim."""
    hit_distance = float("inf")
    normal = None
    for rect, interior in [(ARENA, True), *((rect, False) for rect in barriers)]:
        if interior and rect.collidepoint(end):
            continue
        hit = rect.clipline(start, end)
        if not hit:
            continue
        point = V2(hit[1 if interior else 0])
        distance = start.distance_squared_to(point)
        if distance >= hit_distance:
            continue
        sides = ((abs(point.x-rect.left),(-1,0)), (abs(point.x-(rect.right-1)),(1,0)),
                 (abs(point.y-rect.top),(0,-1)), (abs(point.y-(rect.bottom-1)),(0,1)))
        normal = V2(min(sides, key=lambda pair: pair[0])[1])
        if interior:
            normal *= -1
        hit_distance = distance
    return hit_distance, normal


def route_around(start, goal, obstacle, radius, barriers):
    """Steer past the nearest corner with a clear approach."""
    expanded = obstacle.inflate(radius * 2 + 6, radius * 2 + 6)
    corners = [V2(point) for point in
               (expanded.topleft, expanded.topright, expanded.bottomleft, expanded.bottomright)]
    blocked = [rect.inflate(radius * 2, radius * 2) for rect in barriers]
    options = [point for point in corners
               if ARENA.inflate(-radius * 2, -radius * 2).collidepoint(point)
               and point.distance_squared_to(start) > 9
               and not any(rect.clipline(start, point) for rect in blocked)]
    if not options:
        return unit(goal - start)
    waypoint = min(options, key=lambda point: point.distance_to(start) + point.distance_to(goal))
    return unit(waypoint - start)


# Dungeon ---------------------------------------------------------------------
LEVELS = ("Моховая роща", "Янтарные катакомбы", "Ледяные руины")
FLOORS_PER_REGION = 5
TOTAL_FLOORS = len(LEVELS) * FLOORS_PER_REGION
THEME_COLORS = ("#b4cb85", "#eda66c", "#afe3e4")
BOSS_NAMES = ("Терновый олень", "Печник", "Ледяная королева")
ROOM_LABELS = {
    "entry": "Вход", "combat": "Зал", "treasure": "Тайник", "vault": "Арсенал",
    "exit": "Врата спуска", "boss": "Арена босса",
}
DOORS = {
    (0, -1): ((320, 69), (320, 279), "Север"),
    (0, 1): ((320, 306), (320, 93), "Юг"),
    (-1, 0): ((40, 188), (571, 188), "Запад"),
    (1, 0): ((599, 188), (69, 188), "Восток"),
}
LAYOUTS = (
    ((0,164,120,27,16),(0,475,250,30,18),(1,339,121,38,16),(3,496,119,19,13)),
    ((2,184,160,28,18),(2,466,212,30,18),(1,286,264,36,20),(3,464,107,20,13)),
    ((0,119,125,29,17),(0,127,242,28,19),(4,501,130,35,22),(4,489,239,33,23)),
    ((1,183,121,37,18),(0,203,239,32,17),(1,440,127,35,18),(0,443,242,32,17)),
    ((2,209,121,31,19),(2,396,116,35,19),(3,235,247,19,14),(4,456,235,35,22)),
    ((0,132,146,30,18),(4,249,219,31,21),(4,389,153,30,23),(0,497,232,31,19)),
    ((3,218,159,20,14),(3,426,216,20,15),(0,285,116,34,18),(0,358,250,34,19)),
    ((2,125,114,32,19),(1,482,259,35,18),(4,249,151,32,19),(0,405,224,33,18)),
)
CENTER = V2(320, 188)
CHEST_RECT = pg.Rect(306, 180, 28, 18)
SECOND_WAVE_CHANCE = 0.50
WAVE_DELAY = 1.15
FLOOR_RECOVERY = 55
DROP_TICKETS = 200
AMMO_DROP_TICKETS = 11
HEAL_DROP_TICKETS = 9
LOOT = {"heal": "Аптечка", "ammo": "Патроны", "power": "Урон +2", "vital": "Здоровье +15"}
LOOT.update({key: weapon.name for key, weapon in WEAPONS.items()})


def region_of(level):
    return (level - 1) // FLOORS_PER_REGION


def floor_of(level):
    return (level - 1) % FLOORS_PER_REGION + 1


@dataclass
class Drop:
    kind: str
    pos: V2
    clip: Magazine | None = None
    origin: V2 | None = None
    born: float = 0.0

    def ready(self, now):
        return self.origin is None or now - self.born >= 0.30

    def position(self, now):
        if self.ready(now):
            return self.pos + (0, int(math.sin(now * 7 + self.pos.x) * 2))
        step = max(0.0, (now - self.born) / 0.30)
        return self.origin.lerp(self.pos, step) - (0, 24 * math.sin(step * math.pi))


@dataclass
class Room:
    kind: str
    theme: int
    seed: int
    props: list = field(default_factory=list)
    enemies: list = field(default_factory=list)
    reinforcements: list = field(default_factory=list)
    wave: int = 1
    wave_wait: float | None = None
    loot: list = field(default_factory=list)
    links: set = field(default_factory=set)
    chest: str = ""
    opened: bool = False
    opened_at: float = 0.0
    visited: bool = False
    rewarded: bool = False

    @property
    def barriers(self):
        obstacles = [rect for _, rect in self.props]
        return obstacles + [CHEST_RECT.copy()] if self.chest else obstacles

    @property
    def cleared(self):
        return not self.enemies and not self.reinforcements


def room_props(rng, kind, theme):
    if kind == "boss":
        return [(5, pg.Rect(x, y, 41, 13))
                for x, y in ((147,125),(450,125),(147,235),(450,235))]
    if kind in ("entry", "exit"):
        layout = [(0,120,118,28,16),(4,510,111,29,16),
                  (3,124,259,19,14),(2,514,256,27,17)]
    else:
        layout = rng.choice(LAYOUTS)
    props = []
    flip_x, flip_y = rng.choice((True, False)), rng.choice((True, False))
    for prop, x, y, w, h in layout:
        rect = pg.Rect(0,0,w,h)
        rect.center = WIDTH - x if flip_x else x, 376 - y if flip_y else y
        if kind == "treasure" and V2(rect.center).distance_to(CENTER) < 75:
            continue
        if theme == 1 and prop == 3 and rng.random() > 0.5:
            prop = 2
        props.append((prop, rect))
    for x, y in rng.sample(((74,109),(571,112),(71,256),(572,253)), 2):
        kind_index = 2 if theme == 0 else rng.choice((1,3,4))
        props.append((kind_index, pg.Rect(x-9, y-7, 18, 14)))
    if kind in ("combat", "vault"):
        candidates = [(x,y) for x in (125,232,411,518) for y in (120,174,212,265)]
        rng.shuffle(candidates)
        count = 3 if kind == "vault" else 2
        for x, y in candidates:
            rect = pg.Rect(x-21,y-7,42,14) if count % 2 == 0 else pg.Rect(x-12,y-12,24,24)
            if any(existing.inflate(43,43).colliderect(rect) for _, existing in props):
                continue
            if rect.inflate(86,70).collidepoint(CENTER):
                continue
            props.append((5 if count % 2 == 0 else 6, rect))
            count -= 1
            if count == 0:
                break
    return props


def make_dungeon(seed, level):
    """Build a reproducible connected layout with 5–8 rooms and 1–2 chests."""
    rng = random.Random(seed ^ (level * 31337))
    theme = region_of(level)
    count = rng.randint(5,8)
    side_count = 2 if count > 6 else 1
    path = [(0,0)]
    horizontal = rng.choice((-1,1))
    for _ in range(count - side_count - 1):
        x, y = path[-1]
        choices = [(x+dx,y+dy) for dx,dy in ((horizontal,0),(0,-1),(0,1))
                   if (x+dx,y+dy) not in path]
        path.append(rng.choice(choices))
    rooms = {}

    def add(coord, kind):
        rooms[coord] = Room(kind, theme, rng.randrange(10**7), room_props(rng, kind, theme))
        return rooms[coord]

    def link(a, b):
        dx, dy = b[0]-a[0], b[1]-a[1]
        rooms[a].links.add((dx,dy))
        rooms[b].links.add((-dx,-dy))

    last_kind = "boss" if floor_of(level) == FLOORS_PER_REGION else "exit"
    for index, coord in enumerate(path):
        kind = "entry" if index == 0 else last_kind if index == len(path)-1 else "combat"
        add(coord, kind)
        if index:
            link(path[index-1], coord)

    guns = [name for name in WEAPONS if name != "pistol"]
    random.Random(seed ^ 70553).shuffle(guns)
    first = rng.choice(path[1:-1])
    rooms[first].chest = guns[(level-1) % len(guns)]
    for index in range(side_count):
        branches = [((x,y),(x+dx,y+dy)) for x,y in path[:-1]
                    for dx,dy in DOORS if (x+dx,y+dy) not in rooms]
        anchor, point = rng.choice(branches)
        kind = "treasure" if index == 0 else "vault"
        room = add(point, kind)
        link(anchor, point)
        if index == 0 and (rng.random() < 0.68 or last_kind == "boss"):
            room.chest = rng.choice(("power","vital","ammo","heal"))

    pools = (
        ("crawler", "crawler", "sentry", "moth", "alchemist", "stalker"),
        ("sentry", "shield", "alchemist", "crawler", "spitter", "moth", "stalker", "prism"),
        ("wisp", "sentry", "shield", "alchemist", "spitter", "moth", "stalker", "prism", "oracle"),
    )
    for room in rooms.values():
        if room.kind == "boss":
            room.enemies.append(Boss((455, 188), theme))
            continue
        if room.kind not in ("combat", "vault"):
            continue
        qty = 4 + (floor_of(level) >= 3) + (theme == 2) + rng.randrange(2)
        if room.kind == "vault":
            qty += 1
        points = [(x, y) for x in range(105, 556, 51) for y in (110, 150, 225, 265)
                  if all(not rect.inflate(36, 36).collidepoint(x, y) for rect in room.barriers)]
        room.enemies = build_wave(rng, points, pools[theme], level, qty)
        if rng.random() < SECOND_WAVE_CHANCE:
            qty = 3 + (theme > 0) + rng.randrange(2)
            room.reinforcements = build_wave(rng, points, pools[theme], level, qty)
    return rooms


def build_wave(rng, points, pool, level, count):
    enemies = []
    ranged_kinds = ("sentry", "alchemist", "moth", "spitter", "prism", "oracle")
    ranged_limit = (count + 1) // 2
    ranged = 0
    area_attacks = 0
    specialists = {"stalker": 0, "prism": 0, "spitter": 0}
    for pos in rng.sample(points, min(len(points), count)):
        available = [kind for kind in pool
                     if (kind not in ranged_kinds or ranged < ranged_limit)
                     and (kind not in ("alchemist", "oracle") or (level > 1 and not area_attacks))
                     and specialists.get(kind, 0) < 2]
        kind = rng.choice(available)
        ranged += kind in ranged_kinds
        area_attacks += kind in ("alchemist", "oracle")
        if kind in specialists:
            specialists[kind] += 1
        enemies.append(Enemy(kind, pos, level))
    return enemies


def monster_drop(roll):
    """One roll per normal enemy, with mutually exclusive drop outcomes."""
    if roll < AMMO_DROP_TICKETS:
        return "ammo"
    if roll < AMMO_DROP_TICKETS + HEAL_DROP_TICKETS:
        return "heal"
    return None


class Boss(Enemy):
    """Five telegraphed patterns per boss, with a faster second phase."""
    def __init__(self, pos, theme):
        super().__init__("sentry", pos, (theme+1)*FLOORS_PER_REGION)
        self.kind = "boss"
        self.theme = theme
        self.name = BOSS_NAMES[theme]
        self.max_hp = self.hp = CAMPAIGN_BOSS_HP[theme]
        self.damage = (19,23,27)[theme]
        self.radius = 24
        self.timer = 1.75
        self.pattern = 0
        self.blast_radius = (38,46,48)[theme]
        self.warning = self.explosion = None
        self.locked = V2(1,0)

    @property
    def enraged(self):
        return self.hp <= self.max_hp * 0.50

    def windup(self, player, barriers):
        self.locked = unit(player.pos - self.pos, (1,0))
        if self.pattern == 2:
            self.warning = player.pos.copy()
        elif self.pattern == 3:
            self.mark_ground(player)
        elif self.pattern == 4:
            self.mark_beams(barriers)

    def mark_ground(self, player):
        # Stagger zones so staying put or dodging along the same line is risky.
        along = self.locked * (38 + 6 * self.theme)
        side = along.rotate(90)
        patterns = ((V2(), along, along * 2),
                    (V2(), side, -side, -along),
                    (V2(), along + side, along - side, -along))
        offsets = patterns[self.theme]
        if self.enraged:
            offsets += (-along + side, -along - side)
        for index, offset in enumerate(offsets):
            point, _ = clip_position(player.pos + offset, 12, ())
            self.hazards.append(Hazard(point, max(self.timer, 0.15) + 0.16 * index,
                                       (26,31,34)[self.theme], self.damage + 5))

    def mark_beams(self, barriers):
        spreads = ((0,), (-28,28), (0,90,-90))[self.theme]
        if self.enraged:
            spreads += ((180,) if self.theme != 1 else (0,))
        for index, angle in enumerate(spreads):
            direction = self.locked.rotate(angle)
            ray = self.pos + direction * WIDTH * 2
            edge = ARENA.clipline(self.pos, ray)[1]
            distance = min(((V2(edge) - self.pos).length_squared(),
                            *(segment_hit(self.pos, ray, cover) for cover in barriers)))
            if distance > 12 ** 2:
                end = self.pos + direction * math.sqrt(distance)
                self.hazards.append(Hazard(self.pos.copy(), max(self.timer, 0.15) + index * 0.12,
                                           10 + 2 * self.theme, self.damage + 8, end))

    def step(self, dt, player, barriers):
        self.explosion = None
        self.flash = max(0.0, self.flash - dt)
        self.timer -= dt
        phase = self.enraged
        windup = (0.70 if phase else 0.80) if self.pattern >= 3 else (0.46 if phase else 0.57)
        if not self.attacking and self.timer <= windup:
            self.windup(player, barriers)
        self.attacking = self.timer <= windup
        delta = player.pos-self.pos
        towards = unit(delta,(1,0))
        if self.burst > 0.0:
            self.burst = max(0.0,self.burst-dt)
            self.pos = move(self.pos,self.dash*(286 if phase else 235)*dt,self.radius,barriers)
        elif not self.attacking:
            approach = 0.67 if delta.length() > 157 else -0.52
            motion = towards*approach + towards.rotate(90)*0.66
            self.pos = move(self.pos,motion*(88 if phase else 64)*dt,self.radius,barriers)
        self.moving = not self.attacking or self.burst > 0
        # Boss art stays front-facing, so the warning remains centered over the head.
        if self.timer > 0:
            return []
        if self.pattern < 3:
            shots = (self.thorns, self.furnace, self.blizzard)[self.theme](phase)
        elif self.pattern == 3:
            shots = self.volley(self.locked, (-58,-30,30,58) if phase else (-48,48), 201)
        else:
            shots = self.volley(self.locked, range(22,360,45 if phase else 72), 146)
        pause = 0.22 if self.pattern >= 3 else 0
        self.pattern = (self.pattern+1)%5
        self.timer = (1.51,1.41,1.32)[self.theme] - (0.32 if phase else 0) + pause
        self.attacking = False
        return shots

    def thorns(self, phase):
        if self.pattern == 0:
            self.dash = self.locked
            self.burst = 0.35 if phase else 0.28
            return self.volley(self.locked, range(-44,45,11 if phase else 22),192)
        if self.pattern == 1:
            return self.volley(self.locked, range(0,360,18 if phase else 26),157)
        return self.detonate()

    def furnace(self, phase):
        if self.pattern == 0:
            return self.volley(self.locked, range(-75,76,10 if phase else 15),220)
        if self.pattern == 1:
            angles = tuple(range(0,360,18 if phase else 24))
            return self.volley(self.locked,angles,164) + self.volley(self.locked,angles[::2],230)
        return self.detonate() + self.volley(self.locked,(-42,-27,27,42),199)

    def blizzard(self, phase):
        if self.pattern == 0:
            angles = (0,9,19,90,99,109,180,189,199,270,279,289)
            if phase:
                angles = angles + (49,139,229,319)
            return self.volley(self.locked,angles,234)
        if self.pattern == 1:
            angles = tuple(range(0,360,15 if phase else 20))
            return self.volley(self.locked,angles,167) + self.volley(self.locked.rotate(7),angles[::2],248)
        return self.detonate() + self.volley(self.locked,(-66,-48,-28,28,48,66),226)

    def detonate(self):
        self.explosion, self.warning = self.warning, None
        return []

    def volley(self, direction, angles, speed):
        color = ("#f1ac71", "#fa8567", "#b8e6ed")[self.theme]
        return [Bullet(self.pos.copy(), direction.rotate(angle)*speed, self.damage,
                       color, True, 3) for angle in angles]


class Demon(Boss):
    """An optional three-phase fight with a repeating, ten-part attack cycle."""
    PATTERNS = ("кольца", "разлом", "спирали", "таран", "лучи", "метеоры",
                "ливень", "ножницы", "клетка", "раскрытие ядра")

    def __init__(self, pos):
        super().__init__(pos, 2)
        self.kind = "demon"
        self.name = "Демон разлома"
        self.hp = self.max_hp = SECRET_BOSS_HP
        self.damage = 35
        self.radius = 32
        self.timer = 1.85
        self.exposed = 0.0
        self.recovering = False
        self.volley_index = 0
        self.queued = []
        self.last_resupply = 0

    @property
    def phase(self):
        return 1 + (self.hp <= self.max_hp * .68) + (self.hp <= self.max_hp * .34)

    def receive_hit(self, damage):
        super().receive_hit(damage * (DEMON_CORE_MULTIPLIER if self.exposed > 0 else 1))

    def step(self, dt, player, barriers):
        self.flash = max(0.0,self.flash-dt)
        self.exposed = max(0.0,self.exposed-dt)
        self.timer -= dt
        phase = self.phase
        shots = self.pending_volleys(dt)
        if self.timer <= 0:
            if self.recovering:
                self.recovering = False
                self.timer = .63
            else:
                shots.extend(self.fire(player))
                self.pattern = (self.pattern+1) % len(self.PATTERNS)
                self.timer = (.70,.59,.49)[phase-1] if not self.recovering else DEMON_CORE_TIME
                self.attacking = False

        if not self.recovering and not self.attacking and self.timer <= .40:
            self.attacking = True
            self.locked = unit(player.pos-self.pos,(1,0))
            self.telegraph(player, barriers)
        if self.burst > 0:
            self.burst = max(0.0,self.burst-dt)
            self.pos = move(self.pos,self.dash*(455+phase*56)*dt,self.radius,barriers)
        elif self.recovering:
            drift = unit(CENTER-self.pos) * 48 * dt
            self.pos = move(self.pos,drift,self.radius,barriers)
        elif not self.attacking or self.pattern in (0,1,2,6,7):
            towards = unit(player.pos-self.pos,(1,0))
            turn = 1 if self.volley_index % 2 == 0 else -1
            approach = .62 if self.pos.distance_to(player.pos) > 152 else -.52
            motion = towards*approach + towards.rotate(83*turn)*.76
            before = self.pos
            speed = (151+phase*31)*(.6 if self.attacking else 1)
            self.pos = move(self.pos,motion*speed*dt,self.radius,barriers)
            if self.pos.distance_squared_to(before) < .18:
                self.pos = move(self.pos,unit(CENTER-self.pos)*speed*dt,self.radius,barriers)
        self.moving = self.burst > 0 or not self.attacking
        return shots

    def pending_volleys(self, dt):
        ready = []
        waiting = []
        for delay, shots in self.queued:
            if delay <= dt:
                ready.extend(shots)
            else:
                waiting.append((delay-dt,shots))
        self.queued = waiting
        return ready

    def demon_shots(self, point, direction, angles, speed, color="#ee795d", curve=0):
        return [Bullet(V2(point),direction.rotate(angle)*speed,self.damage,color,True,2.8,curve=curve)
                for angle in angles]

    def telegraph(self, player, barriers):
        phase = self.phase
        if self.pattern in (3,4):
            if self.pattern == 3:
                angles = (0,)
            else:
                count = 4 + phase
                angles = tuple(index * 360/count for index in range(count))
            for index, angle in enumerate(angles):
                direction = self.locked.rotate(angle)
                reach = direction * (278 if self.pattern == 3 else WIDTH*2)
                distance, _ = terrain_hit(self.pos,self.pos+reach,barriers)
                end = self.pos + direction * min(reach.length(), math.sqrt(distance))
                if end.distance_squared_to(self.pos) > 28**2:
                    self.hazards.append(Hazard(self.pos.copy(),max(.10,self.timer)+index*.035,
                                               12 if self.pattern==3 else 9,self.damage,end))
        elif self.pattern in (5,8):
            if self.pattern == 5:
                angles = range(0,360,60 if phase==1 else 45)
                positions = [player.pos] + [player.pos + self.locked.rotate(angle)*53 for angle in angles]
            else:
                angles = range(0,360,45)
                positions = [player.pos + self.locked.rotate(angle)*74 for angle in angles]
            locations = set()
            for index, point in enumerate(positions):
                point = clip_position(point,17,())[0]
                if tuple(point) not in locations:
                    locations.add(tuple(point))
                    self.hazards.append(Hazard(point,max(.12,self.timer)+.08*index,
                                               23 if self.pattern==5 else 17,self.damage+4))

    def fire(self, player):
        phase = self.phase
        pattern = self.pattern
        self.volley_index += 1
        fire = self.demon_shots
        pos, aim = self.pos, self.locked
        if pattern == 0:
            step = (14,12,10)[phase-1]
            self.queued.append((.16,fire(pos,aim.rotate(step/2),range(0,360,step),219+18*phase,"#f4b976")))
            return fire(pos,aim,range(0,360,step),166+13*phase)
        if pattern == 1:
            self.queued.append((.13,fire(pos,aim.rotate(5),range(-64,65,8),305,"#eea664")))
            return fire(pos,aim,range(-85,86,12-phase),245+13*phase)
        if pattern == 2:
            offsets = range(0,360,20-phase*3)
            return (fire(pos,aim,offsets,164+14*phase,"#ef9bc8",118)
                    + fire(pos,aim.rotate(8),offsets,183+11*phase,"#f28070",-118))
        if pattern == 3:
            self.burst, self.dash = .33, aim
            return fire(pos,aim,range(-80,81,16-phase*2),270+16*phase)
        if pattern == 4:
            return fire(pos,aim.rotate(13),range(0,360,17-phase*2),166+12*phase,"#ea9dc4")
        if pattern == 5:
            return fire(pos,aim,(-72,-53,-34,-17,0,17,34,53,72),252)
        if pattern == 6:
            shots = []
            for x in range(62,590,42-phase*3):
                point = V2(x,ARENA.top+2)
                if abs(x-player.pos.x) > 30:
                    shots.extend(fire(point,V2(.27,1), (0,),235+24*phase,"#ff9969"))
                point = V2(x,ARENA.bottom-2)
                if abs(x-player.pos.x) > 42:
                    shots.extend(fire(point,V2(-.25,-1), (0,),204+20*phase,"#e587b0"))
            return shots
        if pattern == 7:
            swings = (-70,-47,-23,23,47,70)
            return (fire(pos,aim,swings,226+12*phase,"#eb9ad6",150+phase*15)
                    + fire(pos,aim,swings,226+12*phase,"#f09570",-150-phase*15))
        if pattern == 8:
            return fire(pos,aim,range(9,360,22-2*phase),186+18*phase,"#dc6d9d")
        self.recovering = True
        self.exposed = DEMON_CORE_TIME
        return fire(pos,aim,range(16,360,30-phase*3),125+12*phase,"#edaf6f")


class Profile:
    """A checkpoint stores the start of the current floor."""
    def __init__(self, path):
        self.path = path
        defaults = json.loads((ROOT / "config/defaults.json").read_text(encoding="utf-8"))
        self.options = dict(defaults)
        self.best = 0
        self.wins = 0
        self.checkpoint = None
        self.error = False
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                return
            options = data.get("options")
            if isinstance(options, dict):
                for key in ("music", "effects"):
                    self.options[key] = self.bounded(options.get(key), 0, 100, defaults[key])
                self.options["scale"] = self.bounded(options.get("scale"), 1, 3, defaults["scale"])
                for key in ("shake", "fullscreen"):
                    if isinstance(options.get(key), bool):
                        self.options[key] = options[key]
            self.best = self.bounded(data.get("best"), 0, TOTAL_FLOORS, 0)
            self.wins = self.bounded(data.get("wins"), 0, 10**9, 0)
            save = data.get("checkpoint")
            if self.restore(save) is not None:
                self.checkpoint = save
        except FileNotFoundError:
            pass
        except (OSError, ValueError):
            self.error = True

    @staticmethod
    def bounded(value, low, high, default):
        return max(low, min(high, value)) if type(value) is int else default

    @staticmethod
    def restore(save):
        if not isinstance(save, dict):
            return None
        try:
            level, seed, kills = (save[k] for k in ("level", "seed", "kills"))
            hero = save.get("hero", "hero")
            if not isinstance(hero, str) or hero not in HEROES:
                return None
            p = Player(hero)
            p.hp, p.max_hp, p.power = (save[k] for k in ("hp", "max_hp", "power"))
            if (any(type(n) is not int for n in (level, seed, kills, p.hp, p.max_hp, p.power))
                    or not (1 <= level <= TOTAL_FLOORS and 0 <= seed < 10**9 and 0 <= kills <= 1000
                            and 0 < p.hp <= p.max_hp <= 1000 and 0 <= p.power <= 100)):
                return None
            slots = save.get("slots")
            active = save.get("active", 0)
            if slots is None:
                # Read checkpoints from the original three-weapon version.
                inventory = save["inventory"]
                selected = save["selected"]
                if not isinstance(inventory, dict) or selected not in inventory:
                    return None
                keys = ([selected] + [key for key in inventory if key != selected])[:2]
                slots = [[key, *inventory[key]] for key in keys]
                slots += [None] * (2 - len(slots))
            if not isinstance(slots, list) or len(slots) != 2 or type(active) is not int or not 0 <= active < 2:
                return None
            p.slots = [None, None]
            for index, values in enumerate(slots):
                if values is None:
                    continue
                key, rounds, reserve = values
                if key not in WEAPONS or p.magazine_for(key) or type(rounds) is not int:
                    return None
                if not 0 <= rounds <= WEAPONS[key].magazine:
                    return None
                if key == "pistol" and reserve is not None:
                    return None
                if key != "pistol" and (type(reserve) is not int or not 0 <= reserve <= 160):
                    return None
                p.slots[index] = Magazine(key, rounds, reserve)
            if p.slots[active] is None:
                return None
            p.active = active
            return level, seed, kills, p
        except (KeyError, ValueError, TypeError):
            return None

    def save(self):
        data = {"options": self.options, "best": self.best, "wins": self.wins,
                "checkpoint": self.checkpoint}
        temporary = None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(mode="w", dir=self.path.parent,
                                             encoding="utf-8", delete=False) as handle:
                temporary = Path(handle.name)
                json.dump(data, handle, ensure_ascii=False, indent=2)
            temporary.replace(self.path)
            self.error = False
        except OSError:
            self.error = True
            if temporary is not None:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    pass


class Audio:
    def __init__(self):
        self.ready = pg.mixer.get_init() is not None
        self.effects = {}
        self.track = None
        self.music_volume = 0.45
        if self.ready:
            for name in ("shot", "hurt", "impact", "kill", "chest", "pickup", "explosion", "step", "slash"):
                self.effects[name] = pg.mixer.Sound(ASSETS / "sounds" / f"{name}.ogg")

    def music(self, track):
        if self.ready and track != self.track:
            pg.mixer.music.load(ASSETS / "music" / f"{track}.ogg")
            pg.mixer.music.set_volume(self.music_volume)
            pg.mixer.music.play(-1, fade_ms=360)
            self.track = track

    def apply(self, options):
        self.music_volume = options["music"] / 100
        if self.ready:
            pg.mixer.music.set_volume(self.music_volume)
            for sound in self.effects.values():
                sound.set_volume(options["effects"] / 100)

    def play(self, name):
        if self.ready:
            self.effects[name].play()


@dataclass
class Particle:
    pos: V2
    vel: V2
    ttl: float
    color: str
    size: int

    def update(self, dt):
        self.pos += self.vel * dt
        self.vel *= max(0, 1 - dt * 4)
        self.ttl -= dt


# Application -----------------------------------------------------------------
class Game:
    def __init__(self, profile_path=ROOT / "config/profile.json"):
        pg.mixer.pre_init(44100, -16, 2, 512)
        pg.init()
        self.profile = Profile(profile_path)
        self.audio = Audio()
        self.audio.apply(self.profile.options)
        self.audio.music("vaults")
        pg.display.set_caption("Dungeonfall")
        self.set_window()
        self.screen = pg.Surface((WIDTH,HEIGHT))
        self.target = self.screen
        self.scrim = pg.Surface((WIDTH,HEIGHT), pg.SRCALPHA)
        self.scrim.fill((19,19,30,213))
        self.clock = pg.time.Clock()
        self.text_cache = {}
        self.ink_atlases = {}
        self.glyphs = image("ui/glyphs.png")
        chars = json.loads((ASSETS/"ui/glyphs.json").read_text(encoding="utf-8"))
        self.glyph_indices = {char:index for index,char in enumerate(chars)}
        self.cover = image("ui/cover.png")
        self.chosen_hero = "hero"
        self.frames = {kind:self.load_frames(kind) for kind in HEROES}
        for group in range(len(LEVELS)):
            for kind in (*Enemy.SPECS,"boss"):
                name=f"{kind}-{group}"
                self.frames[name]=self.load_frames(name,64 if kind=="boss" else 32)
        self.themes = [self.load_theme(i) for i in range(len(LEVELS))]
        self.secret_theme = {
            "floor":self.atlas("environment/secret-floor.png",16,16,12),
            "wall":image("environment/secret-wall.png"),
            "cover":self.atlas("environment/secret-cover.png",64,48,2),
        }
        self.chests = self.atlas("sprites/chest.png",34,29,3)
        self.flames = self.atlas("environment/lights.png",16,18,4)
        self.lantern_light = [self.light_stamp(c,radius)
                              for c in ((232,145,65),(173,204,201)) for radius in (25,27)]
        self.warning_icon = image("ui/warning.png")
        self.frames["demon"] = self.load_frames("demon",112)
        self.items = {key: image(f"ui/{key}.png") for key in ("heal","ammo","power","vital")}
        self.weapons_art = dict(zip(WEAPONS, self.atlas("sprites/weapons.png",28,16,len(WEAPONS))))
        self.gun_angles = {key:{angle:pg.transform.rotate(sprite,angle)
                                for angle in range(0,360,15)}
                           for key,sprite in self.weapons_art.items()}
        self.pending_weapon = None
        self.melee_pressed = False
        self.buttons = []
        self.t = 0.0
        self.running = True
        self.state = "menu"
        self.fx_rng = random.Random()
        self.setup_room()

    def set_window(self):
        self.focus_grace_until = pg.time.get_ticks() + 250
        scale = self.profile.options["scale"]
        desktop_w, desktop_h = pg.display.get_desktop_sizes()[0]
        if self.profile.options["fullscreen"]:
            self.window = pg.display.set_mode((desktop_w, desktop_h), pg.FULLSCREEN)
        else:
            factor = min(scale, (desktop_w - 24)/WIDTH, (desktop_h - 72)/HEIGHT)
            w, h = max(480, round(WIDTH*factor)), max(270, round(HEIGHT*factor))
            self.window = pg.display.set_mode((w,h), pg.RESIZABLE)

    def atlas(self, path, w, h, count):
        sheet=image(path)
        return [sheet.subsurface((i*w,0,w,h)) for i in range(count)]

    def load_frames(self,kind,size=32):
        sheet=image(f"animations/{kind}.png")
        frames=[[sheet.subsurface((i*size,j*size,size,size))
                 for i in range(6)] for j in range(4)]
        return frames,[[pg.transform.flip(frame,True,False) for frame in row] for row in frames]

    def load_theme(self, index):
        return {
            "floor":self.atlas(f"environment/floor-{index}.png",16,16,12),
            "wall":image(f"environment/wall-{index}.png"),
            "props":self.atlas(f"environment/props-{index}.png",40,48,5),
            "cover":self.atlas(f"environment/cover-{index}.png",64,48,2),
            "gate":self.atlas(f"environment/gate-{index}.png",56,43,3),
            "side":self.atlas(f"environment/gate-side-{index}.png",26,60,3),
        }

    def setup_room(self):
        self.player = Player(self.chosen_hero)
        self.level = 1
        self.seed = random.randrange(1, 10**9)
        self.kills = 0
        self.load_level()

    def load_level(self):
        self.secret_progress = ""
        self.rooms = make_dungeon(self.seed, self.level)
        self.drops_rng = random.Random(self.seed + self.level * 199)
        self.enter_room((0, 0), (150, 188))

    def enter_room(self, coord, spawn):
        self.coord = coord
        self.room = self.rooms[coord]
        self.room.visited = True
        self.barriers = self.room.barriers
        self.enemies = self.room.enemies
        self.player.pos.update(spawn)
        self.player.invulnerable = max(0.8, self.player.invulnerable)
        self.bullets = []
        self.particles = []
        self.blasts = []
        self.beam_flashes = []
        self.fields = []
        self.arcs = []
        self.melee_pressed = False
        self.player.melee_flash = 0
        self.player.reset_weapon_state()
        self.shake = 0.0
        self.gate_open = 0.26 if self.room.cleared else 0.0
        self.room_arrived = self.t
        self.step_timer = 0.0
        self.message = ""
        self.message_until = 0
        self.doors = {direction: DOORS[direction] for direction in self.room.links}
        self.make_floor(self.room.seed)
        self.cover_layers = []
        props = self.themes[self.room.theme]["props"]
        cover = (self.secret_theme if self.room.kind == "secret" else self.themes[self.room.theme])["cover"]
        for index, rect in self.room.props:
            if index >= 5:
                sprite = cover[index-5]
                w, h = sprite.get_size()
                pos = V2(rect.centerx-w/2, rect.bottom-34)
            else:
                w = rect.width + 15
                h = max(rect.height + 20, 42 if self.room.theme==0 and index==2 else 33)
                sprite = pg.transform.scale(props[index],(w,h))
                pos = V2(rect.centerx-w/2,rect.bottom-h*0.87)
            self.cover_layers.append((rect.bottom,sprite,pos))
        rng=random.Random(self.room.seed ^ 105)
        self.motes=[(rng.randrange(15),rng.randrange(46,594),rng.randrange(82,292))
                    for _ in range(23)]
        self.sync_music()

    def sync_music(self):
        active = self.state in ("play", "pause", "swap") or (
            self.state == "settings" and self.settings_from == "pause")
        if active:
            if self.room.kind == "secret":
                self.audio.music("demon")
            else:
                prefix = "boss" if self.room.kind == "boss" and not self.room.cleared else "region"
                self.audio.music(f"{prefix}-{self.room.theme}")
        else:
            self.audio.music("vaults")

    def check_secret_key(self, event):
        if self.room.kind == "secret":
            return False
        if event.key == pg.K_KP6:
            char = "6"
        elif 32 < event.key < 127:
            char = chr(event.key).lower()
        else:
            char = getattr(event, "unicode", "").lower().translate(str.maketrans("лщшдь","koilm"))
        if len(char) != 1 or not char.isalnum():
            return False
        attempt = self.secret_progress + char
        self.secret_progress = next((SECRET_CODE[:length] for length in range(len(SECRET_CODE),0,-1)
                                     if attempt.endswith(SECRET_CODE[:length])), "")
        if self.secret_progress == SECRET_CODE:
            self.open_secret()
            return True
        return False

    def open_secret(self):
        props = [(5,pg.Rect(x,y,42,15)) for x,y in ((145,121),(452,121),(145,244),(452,244))]
        room = Room("secret",1,self.seed,props)
        room.enemies.append(Demon((467,185)))
        self.rooms = {(0,0):room}
        self.player.hp = self.player.max_hp
        self.player.reload = self.player.cooldown = 0.0
        for clip in self.player.slots:
            if clip:
                magazine = WEAPONS[clip.name].magazine
                clip.rounds = magazine
                if clip.reserve is not None:
                    clip.reserve = max(clip.reserve, 3*magazine)
        self.enter_room((0,0),(154,188))
        self.audio.play("explosion")
        self.notify("РАЗЛОМ ОТКРЫТ")

    def nearby(self):
        weapon = next((drop for drop in self.room.loot
                       if drop.kind in WEAPONS and drop.ready(self.t) and self.player.pos.distance_to(drop.pos) < 26), None)
        if weapon is not None:
            return "weapon", weapon, f"E  Взять {WEAPONS[weapon.kind].name}"
        if self.room.chest and not self.room.opened and self.player.pos.distance_to(CENTER) < 37:
            if self.room.cleared:
                return "chest", None, "E  Открыть сундук"
            return "", None, "Сундук запечатан до конца боя"
        if self.progress_gate() and self.player.pos.distance_to(CENTER) < 40:
            title = "В следующую локацию" if self.room.kind == "boss" else "Спуститься"
            return "stairs", None, f"E  {title}"
        for direction, (point, _, name) in self.doors.items():
            if self.player.pos.distance_to(point) < 32:
                message = f"E  Ворота: {name}" if self.room.cleared else "Ворота заперты до конца боя"
                return "door", direction, message
        return "", None, ""
