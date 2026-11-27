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

    def progress_gate(self):
        return self.room.kind == "exit" or (
            self.room.kind == "boss" and self.room.cleared and self.level < TOTAL_FLOORS)

    def chest_drop_position(self):
        # Favor the side facing the visitor. Leave room for both their body and the item.
        approach = unit(self.player.pos - CENTER, (0,1))
        angles = (90, -90, 45, -45, 135, -135, 180, 0)
        for radius in (38, 46):
            for angle in angles:
                point = CENTER + approach.rotate(angle) * radius
                body = target_rect(point, 9)
                if ARENA.contains(body) and not any(body.colliderect(rect) for rect in self.barriers):
                    return point
        # The center has at most a few separated props, but retain a safe fallback.
        for y in range(105, 270, 16):
            for x in range(92, 570, 16):
                point = V2(x,y)
                if point.distance_to(CENTER) >= 29 and target_rect(point,9).collidelist(self.barriers) == -1:
                    return point
        raise RuntimeError("Room has no free position for chest loot")

    def interact(self):
        action, target, _ = self.nearby()
        if action == "weapon":
            drop = target
            clip = self.player.magazine_for(drop.kind)
            if clip is not None:
                if clip.reserve is not None:
                    clip.reserve = min(160, clip.reserve + 23)
                self.room.loot.remove(drop)
                self.notify("Патроны пополнены")
                self.audio.play("pickup")
            else:
                self.pending_weapon = drop
                self.change_state("swap")
        elif action == "chest":
            self.audio.play("chest")
            self.burst(CENTER, GOLD, 20, 80)
            landing = self.chest_drop_position()
            self.room.opened = True
            self.room.opened_at = self.t
            self.room.loot.append(Drop(self.room.chest, landing, origin=CENTER.copy(), born=self.t))
        elif action == "stairs":
            next_region = self.room.kind == "boss"
            self.level += 1
            self.player.hp = self.player.max_hp if next_region else min(self.player.max_hp, self.player.hp + FLOOR_RECOVERY)
            if next_region:
                self.player.power += 2
            self.load_level()
            self.checkpoint()
            self.audio.play("chest")
        elif action == "door" and self.room.cleared:
            dx, dy = target
            self.enter_room((self.coord[0] + dx, self.coord[1] + dy), self.doors[target][1])

    def equip_pending(self, index):
        drop = self.pending_weapon
        old = self.player.slots[index]
        if old:
            self.room.loot.append(Drop(old.name, drop.pos.copy(), old))
        magazine = WEAPONS[drop.kind].magazine
        reserve = None if drop.kind == "pistol" else max(32, magazine * 3)
        self.player.slots[index] = drop.clip or Magazine(drop.kind, magazine, reserve)
        self.player.active = index
        self.player.reload = 0
        self.player.reset_weapon_state()
        self.room.loot.remove(drop)
        self.pending_weapon = None
        self.change_state("play")
        self.notify(f"{WEAPONS[drop.kind].name} в слоте {index+1}")
        self.audio.play("pickup")
        self.burst(drop.pos, CYAN, 12, 55)

    def collect(self):
        for drop in self.room.loot[:]:
            if drop.kind in WEAPONS or not drop.ready(self.t) or self.player.pos.distance_to(drop.pos) >= 17:
                continue
            p = self.player
            if drop.kind == "heal":
                if p.hp == p.max_hp:
                    continue
                p.hp = min(p.max_hp, p.hp + 30)
            elif drop.kind == "ammo":
                magazines = [c for c in p.slots if c and c.reserve is not None and c.reserve < 160]
                if not magazines:
                    continue
                for clip in magazines:
                    clip.reserve = min(160, clip.reserve + 22)
            elif drop.kind == "vital":
                p.max_hp += 15
                p.hp += 15
            elif drop.kind == "power":
                p.power += 2
            self.room.loot.remove(drop)
            self.notify(LOOT[drop.kind])
            self.audio.play("pickup")
            self.burst(drop.pos, CYAN, 9, 45)

    def notify(self, message):
        self.message, self.message_until = message, self.t + 2.0


    def rect(self, color, bounds, width=0):
        pg.draw.rect(self.target, color, pg.Rect(bounds), width)

    def line(self, color, start, end, width=1):
        pg.draw.line(self.target, color, start, end, width)

    def put_sprite(self, sprite, pos, size=None):
        if size is not None:
            sprite = pg.transform.scale(sprite, size)
        self.target.blit(sprite, pos)

    def make_floor(self, seed):
        rng = random.Random(seed)
        theme = self.room.theme
        secret = self.room.kind == "secret"
        assets = self.secret_theme if secret else self.themes[theme]
        floor = assets["floor"]
        wall = assets["wall"]
        self.backdrop = pg.Surface((WIDTH,HEIGHT))
        self.backdrop.fill(("#222630","#241e2b","#182635")[theme])
        self.target = self.backdrop

        for y in range(53,326,16):
            for x in range(24,609,16):
                dx, dy = x + 8 - 320, y + 8 - 188
                near_x, near_y = abs(dx) <= 27, abs(dy) <= 26
                doorway_x = (-1 if dx<0 else 1,0) in self.doors
                doorway_y = (0,-1 if dy<0 else 1) in self.doors
                path = (near_y and doorway_x) or (near_x and doorway_y) or (near_x and near_y)
                if theme==2:
                    # Keep glassy blue seams visible between the paler, snow-covered tiles.
                    path = path or rng.random()<0.15
                if self.room.kind in ("boss","secret"):
                    path = 82 < x < 556 and 89 < y < 288
                regular = rng.choices((0,1,2,3,4,5),(7,3,2,3,1,2))[0]
                variant = rng.randint(6,11) if path else regular
                self.put_sprite(floor[variant], (x,y))

        for edge_y,direction in ((48,(0,-1)),(308,(0,1))):
            for x in range(24,615,16):
                if direction not in self.doors or not (294 < x < 345):
                    self.put_sprite(wall,(x,edge_y))
        for edge_x,direction in ((17,(-1,0)),(598,(1,0))):
            for y in range(72,308,16):
                if direction not in self.doors or not (157<y<214):
                    self.put_sprite(wall,(edge_x,y),(22,18))

        if secret:
            for x,y in ((320,116),(242,151),(398,151),(242,219),(398,219),(320,265)):
                self.rect("#302534",(x-15,y-8,30,16))
                self.line("#925267",(x-13,y),(x,y-6),2)
                self.line("#925267",(x,y-6),(x+13,y),2)
                self.line("#744256",(x+13,y),(x,y+6),2)
                self.line("#744256",(x,y+6),(x-13,y),2)
                self.rect("#cd7c63",(x-2,y-2,4,4))
        elif theme == 0:
            tree=assets["props"][2]
            # Layer trees in the upper border without adding invisible collision.
            tree_centers = (47,72,102,151,177,231,254,284,
                            354,380,428,471,498,553,586)
            for x in tree_centers:
                if (0,-1) in self.doors and 277<x<367:
                    continue
                dy = rng.randint(-7,3)
                mini = rng.choice(((30,35),(34,40),(39,43)))
                self.put_sprite(tree,(x-17,34+dy),mini)
            for x,y in ((36,82),(570,80),(38,260),(567,265)):
                self.put_sprite(tree,(x,y), (30,36))
            for _ in range(14):
                x,y=rng.randrange(47,593),rng.randrange(83,290)
                if abs(x-320)>55 and abs(y-188)>36:
                    pg.draw.lines(self.target,"#4c6c55",False,((x-5,y+2),(x-2,y+1),(x+3,y+1)),2)
                    self.rect("#55745a",(x-2,y-3,2,4))
                    if rng.random()<0.26:
                        self.rect("#a69e75",(x-2,y-3,2,2))
        elif theme == 1:
            for x in (113,211,416,511):
                for y in (124,251):
                    self.rect("#4a353d",(x-13,y-7,26,14))
                    self.rect("#9e7158",(x-11,y-6,22,1))
                    self.rect("#6e5352",(x-10,y+3,20,2))
                    for i in range(-1,2):
                        self.rect("#b18766",(x+6*i-1,y-2,3,3))
            for x in (88,151,231,400,480,539):
                self.rect("#332733",(x,50,12,19))
                self.rect("#bb7954",(x+2,51,8,2))
                self.rect("#8f4d43",(x+3,54,6,10))
                self.rect("#e0a26a",(x+4,55,4,2))
                self.rect("#9c6551",(x+2,65,8,2))
            for x in (77,196,306,433,548):
                for y in (91,282):
                    self.rect("#3d3038",(x,y,13,5))
                    self.rect("#856757",(x+2,y+1,9,2))
        else:
            for x in (90,155,227,403,480,540):
                for y in (70,310):
                    self.rect("#547887",(x,y,15,3))
                    self.rect("#a0c5c6",(x+1,y,12,2))
                    self.rect("#7198a4",(x+6,y+3,4,5))
            for _ in range(10):
                x,y=rng.randrange(50,587),rng.randrange(84,290)
                if abs(x-320)>78 or abs(y-188)>30:
                    self.line("#2e5566",(x,y),(x+9,y-4))
                    self.line("#76a0ac",(x+1,y),(x+9,y-3))

        if self.room.kind in ("exit","boss"):
            # Inlaid marks identify the destination without a directional arrow.
            for x,y in ((320,113),(254,166),(386,166),(254,217),(386,217),(320,265)):
                self.rect("#262933",(x-8,y-4,16,9))
                self.rect(THEME_COLORS[theme],(x-6,y-3,12,1))
                self.line(THEME_COLORS[theme],(x-3,y+1),(x,y+3))
                self.line(THEME_COLORS[theme],(x,y+3),(x+3,y+1))

        self.target = self.screen

    def text_bitmap(self, words, size, color):
        words = words.upper()
        key=(words,size,color)
        if key in self.text_cache:
            return self.text_cache[key]
        if color not in self.ink_atlases:
            atlas = self.glyphs.copy()
            atlas.fill(pg.Color(color), special_flags=pg.BLEND_RGBA_MULT)
            self.ink_atlases[color]=atlas
        atlas=self.ink_atlases[color]
        surface = pg.Surface((max(1,len(words)*6-1),7), pg.SRCALPHA)
        for index,char in enumerate(words):
            glyph = self.glyph_indices.get(char,self.glyph_indices["?"])
            surface.blit(atlas,(index*6,0),(glyph*6,0,5,7))
        if size!=1:
            surface=pg.transform.scale_by(surface,size)
        if len(self.text_cache)>=420:
            self.text_cache.clear()
        self.text_cache[key]=surface
        return surface

    def label(self, words, x, y, size=1, color=PAPER, align="left"):
        glyphs=self.text_bitmap(words,size,color)
        if align=="center":
            x-=glyphs.get_width()//2
        elif align=="right":
            x-=glyphs.get_width()
        self.target.blit(glyphs,(round(x),round(y)))

    def panel(self,bounds,fill="#272631",edge="#69545a"):
        x,y,w,h=bounds
        self.rect("#171821",(x-2,y-2,w+4,h+4))
        self.rect(edge,(x,y,w,h))
        self.rect(fill,(x+1,y+1,w-2,h-2))
        self.rect(edge,(x+2,y+2,2,2))
        self.rect(edge,(x+w-4,y+2,2,2))
        self.rect(edge,(x+w-4,y+h-4,2,2))
        self.rect(edge,(x+2,y+h-4,2,2))

    def button(self, words, x, y, action, width=198):
        rect=pg.Rect(x,y,width,26)
        self.buttons.append((rect,action))
        hover=rect.collidepoint(self.mouse())
        self.panel(rect, "#483e45" if hover else "#302c37",
                   GOLD if hover else "#7e6561")
        size=2 if len(words)<=max((width-15)//12,1) else 1
        self.label(words,x+width//2,y+(26-7*size)//2,size,PAPER,"center")

    def viewport(self):
        w, h = self.window.get_size()
        factor = min(w / WIDTH, h / HEIGHT)
        sw, sh = max(1, int(WIDTH * factor)), max(1, int(HEIGHT * factor))
        return pg.Rect((w - sw) // 2, (h - sh) // 2, sw, sh)

    def mouse(self, position=None):
        rect = self.viewport()
        x, y = pg.mouse.get_pos() if position is None else position
        return V2((x - rect.x) * WIDTH / rect.w, (y - rect.y) * HEIGHT / rect.h)

    def show_controls(self):
        self.change_state("controls")

    def choose_hero(self, hero):
        self.chosen_hero = hero

    def start(self):
        self.setup_room()
        self.checkpoint()
        self.change_state("play")

    def checkpoint(self):
        p = self.player
        self.profile.checkpoint = {
            "level": self.level, "seed": self.seed, "kills": self.kills,
            "hp": p.hp, "max_hp": p.max_hp, "power": p.power, "active": p.active, "hero": p.hero,
            "slots": [[c.name, c.rounds, c.reserve] if c else None for c in p.slots],
        }
        self.profile.best = max(self.profile.best, self.level)
        self.profile.save()

    def continue_run(self):
        restored = Profile.restore(self.profile.checkpoint)
        if restored is not None:
            self.level, self.seed, self.kills, self.player = restored
            self.chosen_hero = self.player.hero
            self.load_level()
            self.change_state("play")

    def finish_run(self, won):
        self.change_state("win" if won else "dead")
        if won or self.room.kind != "secret":
            self.profile.checkpoint = None
        self.profile.wins += int(won)
        self.profile.save()
        if won:
            self.audio.play("chest")

    def change_state(self, state):
        self.buttons.clear()
        self.state = state
        self.melee_pressed = False
        pg.mouse.set_visible(state != "play")
        self.sync_music()

    def settings(self):
        self.settings_from = self.state
        self.change_state("settings")

    def option(self, key, direction=1):
        options = self.profile.options
        if key in ("music", "effects"):
            options[key] = min(100, max(0, options[key] + direction * 10))
        elif key == "scale":
            options[key] = (options[key] - 1 + direction) % 3 + 1
            options["fullscreen"] = False
            self.set_window()
        elif key == "fullscreen":
            options[key] = not options[key]
            self.set_window()
        else:
            options[key] = not options[key]
        self.audio.apply(options)
        self.profile.save()

    def quit(self):
        self.running = False

    def escape(self):
        if self.state == "play":
            self.change_state("pause")
        elif self.state == "pause":
            self.change_state("play")
        elif self.state == "settings":
            self.change_state(self.settings_from)
        elif self.state == "swap":
            self.pending_weapon = None
            self.change_state("play")
        elif self.state in ("dead", "win", "controls"):
            self.change_state("menu")
        else:
            self.quit()

    def events(self):
        for event in pg.event.get():
            if event.type == pg.QUIT:
                self.quit()
                return
            if (event.type == pg.WINDOWFOCUSLOST and self.state == "play"
                    and pg.time.get_ticks() >= self.focus_grace_until):
                self.change_state("pause")
            if event.type == pg.KEYDOWN:
                if event.key == pg.K_F11:
                    playing = self.state == "play"
                    self.option("fullscreen")
                    if playing:
                        self.change_state("play")
                elif event.key == pg.K_ESCAPE:
                    self.escape()
                elif self.state == "controls":
                    if event.key in (pg.K_RETURN, pg.K_KP_ENTER):
                        self.start()
                    elif event.key in (pg.K_1, pg.K_2):
                        self.choose_hero(tuple(HEROES)[event.key-pg.K_1])
                elif self.state == "swap" and event.key in (pg.K_1, pg.K_2):
                    self.equip_pending(event.key - pg.K_1)
                elif self.state == "play" and self.player.hp > 0:
                    if self.check_secret_key(event):
                        continue
                    if event.key == pg.K_e:
                        self.interact()
                    elif event.key == pg.K_r:
                        self.player.start_reload()
                    elif event.key in (pg.K_1, pg.K_2):
                        self.player.select(event.key - pg.K_1)
            if event.type == pg.MOUSEBUTTONDOWN and event.button == 1:
                for rect, action in self.buttons[:]:
                    if rect.collidepoint(self.mouse(event.pos)):
                        action()
                        break
            elif event.type == pg.MOUSEBUTTONDOWN and event.button == 3 and self.state == "play":
                self.melee_pressed = True


    def update(self, dt):
        if self.state == "play":
            keys = pg.key.get_pressed()
            direction = V2((keys[pg.K_d] or keys[pg.K_RIGHT]) - (keys[pg.K_a] or keys[pg.K_LEFT]),
                           (keys[pg.K_s] or keys[pg.K_DOWN]) - (keys[pg.K_w] or keys[pg.K_UP]))
            buttons = pg.mouse.get_pressed()
            melee = self.melee_pressed or buttons[2]
            self.melee_pressed = False
            self.update_play(dt, direction, self.mouse(), buttons[0], melee)

    def update_play(self, dt, direction, aim, firing, melee=False):
        if self.state != "play":
            return
        player = self.player
        before = player.pos
        player.steer(direction, dt, self.barriers)
        self.step_timer -= dt
        if player.pos.distance_squared_to(before) > 0.25 and self.step_timer <= 0:
            self.audio.play("step")
            self.step_timer = 0.29
            self.burst(player.pos+(0,4), "#77716a", 3, 25)
        self.shake = max(0.0, self.shake - dt)
        for particle in self.particles:
            particle.update(dt)
        self.particles[:] = [p for p in self.particles if p.ttl > 0]
        self.blasts[:] = [(pos, ttl-dt, r) for pos, ttl, r in self.blasts if ttl > dt]
        self.beam_flashes[:] = [(hazard, ttl-dt) for hazard, ttl in self.beam_flashes if ttl > dt]
        self.arcs[:] = [(start, end, color, ttl-dt) for start,end,color,ttl in self.arcs if ttl > dt]
        player.tick(dt, aim, firing)
        if melee and player.swing():
            self.melee_attack()
        if firing:
            shots = player.shoot()
            if shots:
                self.bullets.extend(shots)
                self.on_shot(shots)
        for enemy in self.enemies:
            if enemy.hp <= 0:
                continue
            enemy.tick_status(dt)
            slowed = 0.80 if isinstance(enemy,Boss) else 0.24
            self.bullets.extend(enemy.step(dt*slowed if enemy.frozen else dt, player, self.barriers))
            if (isinstance(enemy,Demon) and enemy.recovering and enemy.volley_index % 30 == 0
                    and enemy.last_resupply != enemy.volley_index):
                enemy.last_resupply = enemy.volley_index
                for point in (V2(94,180),V2(551,208)):
                    if not any(drop.pos == point for drop in self.room.loot):
                        self.room.loot.append(Drop("ammo",point))
            self.update_hazards(enemy, dt)
            if enemy.explosion is not None:
                self.on_explosion(enemy.explosion, enemy.blast_radius)
                if enemy.explosion.distance_to(player.pos) < enemy.blast_radius:
                    self.hit_player(enemy.damage + 4)
            if (enemy.burst > 0 or isinstance(enemy, Boss)) and enemy.pos.distance_to(player.pos) < enemy.radius + 7:
                self.hit_player(enemy.damage)
        self.space_out_enemies(dt)
        self.update_fields(dt)
        self.update_bullets(dt)
        for enemy in self.enemies[:]:
            if enemy.hp <= 0:
                self.enemies.remove(enemy)
                self.on_enemy_dead(enemy)
        if self.room.kind == "secret" and self.room.cleared:
            self.finish_run(True)
            return
        if player.hp <= 0:
            self.finish_run(False)
            return
        self.update_waves(dt)
        self.collect()
        if self.room.cleared:
            self.gate_open = min(0.26,self.gate_open + dt)
        if self.room.kind == "boss" and self.room.cleared:
            if self.level == TOTAL_FLOORS:
                self.finish_run(True)
            elif not self.room.rewarded:
                self.room.rewarded = True
                self.sync_music()
                self.notify("Ворота открыты")
                self.burst(CENTER,THEME_COLORS[self.room.theme],26,60)

    def melee_attack(self):
        player = self.player
        self.audio.play("slash")
        for enemy in self.enemies:
            delta = enemy.pos - player.pos
            if (enemy.hp <= 0 or delta.length_squared() > (MELEE_REACH + enemy.radius) ** 2
                    or unit(delta, player.slash_direction).dot(player.slash_direction) < 0.47
                    or any(rect.clipline(player.pos, enemy.pos) for rect in self.barriers)):
                continue
            enemy.receive_hit(MELEE_DAMAGE + player.power)
            if not isinstance(enemy, Boss):
                knockback = unit(delta, player.slash_direction) * 12
                enemy.pos = move(enemy.pos, knockback, enemy.radius, self.barriers)
            self.burst(enemy.pos, "#ffe3ae", 12, 72)
            self.shake = max(self.shake, 0.10)

    def update_hazards(self, enemy, dt):
        for hazard in enemy.hazards[:]:
            hazard.wait -= dt
            if hazard.wait > 0:
                continue
            enemy.hazards.remove(hazard)
            if hazard.end is None:
                self.on_explosion(hazard.point, hazard.radius)
                hits = hazard.point.distance_squared_to(self.player.pos) < hazard.radius ** 2
            else:
                self.beam_flashes.append((hazard, 0.19))
                self.audio.play("explosion")
                axis = hazard.end - hazard.point
                fraction = (self.player.pos - hazard.point).dot(axis) / axis.length_squared()
                foot = hazard.point.lerp(hazard.end, max(0, min(1, fraction)))
                hits = (0 <= fraction <= 1 and foot.distance_squared_to(self.player.pos) < hazard.radius ** 2
                        and not any(rect.clipline(foot, self.player.pos) for rect in self.barriers))
            if hits:
                self.hit_player(hazard.damage)

    def space_out_enemies(self, dt):
        # Keep overlapping crowds readable while preserving walls and cover.
        for index, left in enumerate(self.enemies):
            for right in self.enemies[index + 1:]:
                delta = left.pos - right.pos
                distance = delta.length()
                separation = left.radius + right.radius + 3
                if distance < separation:
                    offset = unit(delta, (1, 0)) * min(45 * dt, (separation - distance) / 2)
                    left.pos = move(left.pos, offset, left.radius, self.barriers)
                    right.pos = move(right.pos, -offset, right.radius, self.barriers)

    def update_waves(self, dt):
        room = self.room
        if room.enemies or not room.reinforcements:
            return
        if room.wave_wait is None:
            room.wave_wait = WAVE_DELAY
            # Old enemy shots should not hide the reinforcement warning.
            self.bullets[:] = [bullet for bullet in self.bullets if not bullet.hostile]
            self.audio.play("impact")
            return
        room.wave_wait -= dt
        if room.wave_wait > 0:
            return
        room.wave = 2
        room.wave_wait = None
        for enemy in room.reinforcements:
            enemy.timer = max(enemy.timer, 0.95)
            self.burst(enemy.pos, THEME_COLORS[room.theme], 7, 36)
        room.enemies.extend(room.reinforcements)
        room.reinforcements.clear()

    def burst(self, pos, color, count, speed):
        for _ in range(count):
            velocity = V2(speed * self.fx_rng.uniform(0.3, 1.0), 0).rotate(self.fx_rng.randrange(360))
            self.particles.append(Particle(V2(pos), velocity, self.fx_rng.uniform(0.12, 0.41),
                                           color, self.fx_rng.choice((1, 2, 3))))

    def on_explosion(self, pos, radius=46):
        self.audio.play("explosion")
        self.shake = max(self.shake, 0.22)
        self.blasts.append((V2(pos), 0.35, radius))
        self.burst(pos, "#f49fb3", 35, 107)

    def hit_player(self, amount):
        if self.player.hurt(amount):
            self.audio.play("hurt")
            self.shake = max(self.shake, 0.16)
            self.burst(self.player.pos, RED, 14, 65)

    def on_shot(self, shots):
        self.audio.play("shot")
        point = shots[0].pos + self.player.aim * 15
        self.burst(point, shots[0].color, 4, 34)
        if shots[0].weapon == "salt":
            player = self.player
            player.pos = move(player.pos, -player.aim * 14, 8, self.barriers)

    def on_enemy_dead(self, enemy):
        self.kills += 1
        self.audio.play("kill")
        self.burst(enemy.pos, "#d1afff", 18, 90)
        if isinstance(enemy, Boss):
            self.on_explosion(enemy.pos)
            return
        kind = monster_drop(self.drops_rng.randrange(DROP_TICKETS))
        if kind:
            self.room.loot.append(Drop(kind, enemy.pos.copy()))

    def update_bullets(self, dt):
        active, self.bullets = self.bullets, []
        for bullet in active:
            bullet.age += dt
            bullet.ttl -= dt
            if not bullet.hostile:
                if self.prepare_player_shot(bullet, dt):
                    continue
            if bullet.curve:
                bullet.vel.rotate_ip(bullet.curve * dt)
            start = bullet.pos
            end = start + bullet.vel * dt
            if bullet.hostile:
                # The secret fight can have hundreds of hostile bullets at once.
                self.advance_hostile(bullet, end)
                continue
            obstacle, normal = terrain_hit(start, end, self.barriers)
            limit = min(obstacle, start.distance_squared_to(end) + .01)
            hits = sorted(((segment_hit(start,end,target_rect(enemy.pos,enemy.radius)),enemy)
                           for enemy in self.enemies if enemy.hp > 0 and enemy not in bullet.hit_targets),
                          key=lambda pair: pair[0])
            stopped_on_enemy = False
            travel = unit(bullet.vel)
            for distance, enemy in hits:
                if distance >= limit:
                    break
                if enemy.hp <= 0:
                    continue
                point = start + travel * math.sqrt(distance)
                self.weapon_hit(bullet, enemy, bullet.distance + math.sqrt(distance))
                self.on_impact(bullet, point)
                if not bullet.piercing:
                    stopped_on_enemy = True
                    break
                bullet.piercing -= 1
                bullet.hit_targets.add(enemy)
            if stopped_on_enemy:
                self.finish_shot(bullet, point, hit=True)
                continue
            if normal is not None:
                point = start + travel * math.sqrt(obstacle)
                self.on_impact(bullet, point)
                if bullet.weapon == "scatter" and not bullet.bounced:
                    bullet.bounced = True
                    bullet.vel.reflect_ip(normal)
                    bullet.pos = point + normal * 2
                    bullet.damage += 4
                    self.bullets.append(bullet)
                    continue
                if bullet.weapon == "saw" and not bullet.returning:
                    bullet.pos = point + normal * 2
                    self.return_saw(bullet)
                    self.bullets.append(bullet)
                    continue
                self.finish_shot(bullet, point + normal * 3)
                continue
            bullet.distance += start.distance_to(end)
            bullet.pos = end
            if bullet.ttl > 0:
                self.bullets.append(bullet)
            else:
                self.finish_shot(bullet, end)

    def advance_hostile(self, bullet, end):
        player_hit = segment_hit(bullet.pos, end, target_rect(self.player.pos, 8))
        terrain = min((segment_hit(bullet.pos,end,rect) for rect in self.barriers),
                      default=float("inf"))
        if player_hit < terrain:
            self.hit_player(bullet.damage)
        elif terrain < float("inf"):
            self.on_impact(bullet, bullet.pos + unit(bullet.vel) * math.sqrt(terrain))
        elif bullet.ttl > 0 and ARENA.collidepoint(end):
            bullet.pos = end
            self.bullets.append(bullet)

    def prepare_player_shot(self, bullet, dt):
        """Advance weapon-specific flight before generic swept collisions."""
        key = bullet.weapon
        if key == "anvil":
            if bullet.age >= self.mortar_time(bullet):
                self.on_explosion(bullet.destination, bullet.blast)
                self.area_damage(bullet.destination, bullet.blast, bullet.damage, over_cover=True)
            else:
                self.bullets.append(bullet)
            return True
        if key == "locust":
            direction = unit(bullet.vel)
            candidates = [enemy for enemy in self.enemies if enemy.hp > 0
                          and bullet.pos.distance_squared_to(enemy.pos) < 148**2
                          and direction.dot(unit(enemy.pos-bullet.pos)) > 0.17
                          and self.visible(bullet.pos, enemy.pos)]
            target = min(candidates, key=lambda enemy: bullet.pos.distance_squared_to(enemy.pos), default=None)
            if target:
                turn = bullet.vel.angle_to(target.pos-bullet.pos)
                turn = (turn + 180) % 360 - 180
                bullet.vel.rotate_ip(max(-280*dt, min(280*dt, turn)))
        elif key == "fork" and bullet.age >= .17:
            for angle in (-26,0,26):
                self.bullets.append(Bullet(bullet.pos.copy(),bullet.vel.rotate(angle),
                                           bullet.damage,bullet.color,ttl=.48,weapon="fork_shard"))
            self.burst(bullet.pos,bullet.color,7,53)
            return True
        elif key == "comet":
            speed = min(850, bullet.vel.length() + 1180 * dt)
            bullet.vel.scale_to_length(speed)
        elif key == "saw":
            if not bullet.returning and bullet.age >= .39:
                self.return_saw(bullet)
            if bullet.returning:
                delta = self.player.pos - bullet.pos
                if delta.length() < 15:
                    return True
                bullet.vel = unit(delta) * 440
        return False

    @staticmethod
    def mortar_time(bullet):
        return .34 + min(.66, bullet.pos.distance_to(bullet.destination) / 640)

    @staticmethod
    def return_saw(bullet):
        bullet.returning = True
        bullet.hit_targets.clear()
        bullet.piercing = WEAPONS["saw"].piercing

    def visible(self, start, end):
        return not any(rect.clipline(start, end) for rect in self.barriers)

    def weapon_hit(self, bullet, enemy, distance):
        key = bullet.weapon
        damage = bullet.damage
        player = self.player
        if key == "pistol" and player.selected == key:
            player.focus_hits = min(5, player.focus_hits + 1) if player.focus_target is enemy else 1
            player.focus_target = enemy
            damage += 4 * (player.focus_hits - 1)
            if player.focus_hits == 5:
                self.burst(enemy.pos, GOLD, 5, 51)
        elif key == "comet":
            damage += min(57, int(distance * .20))
        elif key == "salt":
            damage = max(3, int(damage * max(.25, 1.8 - distance / 59)))
        enemy.receive_shot(bullet, damage)

        if key == "coil":
            self.chain_lightning(enemy, damage, bullet.color)
        elif key == "frost":
            enemy.frost_marks += 1
            enemy.frost_window = 1.55
            if enemy.frost_marks >= 3:
                enemy.frost_marks = 0
                enemy.frozen = .34 if isinstance(enemy,Boss) else .92
                self.burst(enemy.pos, "#b5eaf1", 12, 62)
        elif key == "ember":
            enemy.ember_marks += 1
            enemy.ember_window = 1.5
            if enemy.ember_marks >= 3:
                enemy.ember_marks = 0
                self.on_explosion(enemy.pos,26)
                self.area_damage(enemy.pos,26,45 + self.player.power)

    def chain_lightning(self, enemy, damage, color):
        visited = {enemy}
        for strength in (.75,.53,.38):
            candidates = (other for other in self.enemies if other.hp > 0 and other not in visited
                          and enemy.pos.distance_squared_to(other.pos) < 108**2
                          and self.visible(enemy.pos,other.pos))
            target = min(candidates, key=lambda other: enemy.pos.distance_squared_to(other.pos), default=None)
            if target is None:
                break
            target.receive_hit(round(damage * strength))
            self.arcs.append((enemy.pos.copy(), target.pos.copy(),color,.15))
            visited.add(target)
            enemy = target

    def finish_shot(self, bullet, point, hit=False):
        if bullet.weapon == "pistol" and self.player.selected == "pistol" and not hit:
            self.player.focus_hits = 0
            self.player.focus_target = None
        if bullet.weapon == "nova":
            self.fields.append(WeaponField("nova",point,32,1.85,18+self.player.power))
            self.burst(point, "#ffb97f", 14, 62)
        elif bullet.weapon == "eclipse":
            self.fields.append(WeaponField("eclipse",point,73,.85,63+self.player.power))
            self.burst(point, "#c9a8ec", 14, 69)
        elif bullet.blast:
            self.on_explosion(point, bullet.blast)
            self.area_damage(point, bullet.blast, bullet.damage)

    def area_damage(self, point, radius, damage, over_cover=False):
        for enemy in self.enemies:
            if (enemy.hp > 0 and enemy.pos.distance_squared_to(point) < (radius+enemy.radius*.5)**2
                    and (over_cover or self.visible(point, enemy.pos))):
                enemy.receive_hit(damage)

    def update_fields(self, dt):
        for field in self.fields[:]:
            field.ttl -= dt
            field.next_tick -= dt
            if field.kind == "nova" and field.next_tick <= 0 and field.ttl > 0:
                self.area_damage(field.pos, field.radius, field.damage)
                field.next_tick += .30
            elif field.kind == "eclipse":
                for enemy in self.enemies:
                    distance = enemy.pos.distance_to(field.pos)
                    if (enemy.hp > 0 and not isinstance(enemy,Boss) and 5 < distance < field.radius
                            and self.visible(field.pos,enemy.pos)):
                        delta = unit(field.pos-enemy.pos) * min(distance,dt*145)
                        enemy.pos = move(enemy.pos,delta,enemy.radius,self.barriers)
            if field.ttl <= 0:
                if field.kind == "eclipse":
                    self.on_explosion(field.pos,37)
                    self.area_damage(field.pos,37,field.damage)
                self.fields.remove(field)

    def on_impact(self, bullet, pos):
        if not bullet.hostile:
            self.audio.play("impact")
        self.burst(pos, bullet.color, 4, 49)

    @staticmethod
    def light_stamp(color, radius):
        size=2*radius+2
        tile=pg.Surface((size,size))
        for step in range(5,0,-1):
            d=step*radius//5
            c=tuple(value*(6-step)//29 for value in color)
            corners=((radius-d,radius-d//2),(radius-d//2,radius-d),(radius+d//2,radius-d),
                     (radius+d,radius-d//2),(radius+d,radius+d//2),(radius+d//2,radius+d),
                     (radius-d//2,radius+d),(radius-d,radius+d//2))
            pg.draw.polygon(tile,c,corners)
        return tile

    def gate_sprite(self, direction, point, frame):
        assets=self.themes[self.room.theme]
        side=direction[0]!=0
        sprite=assets["side" if side else "gate"][frame]
        if direction[0]==-1:
            sprite=pg.transform.flip(sprite,True,False)
        x,y=point
        if side:
            return sprite, (x-sprite.get_width()//2,y-sprite.get_height()//2)
        offset = 31 if direction[1] < 0 else 28
        return sprite,(x-sprite.get_width()//2,y-offset)

    def render_zone(self, point, radius, active=True):
        x,y = int(point.x),int(point.y)
        color="#f79571" if active else "#a85663"
        rect=pg.Rect(x-radius,y-radius,radius*2,radius*2)
        base=pg.Surface(rect.size,pg.SRCALPHA)
        for row in range(4,rect.h,6):
            for col in range(4+(row//6)%2*3,rect.w,6):
                if (row-radius)**2+(col-radius)**2 < radius**2:
                    pg.draw.rect(base,(196,77,86,112),(col,row,3,2))
        self.target.blit(base,rect)
        # Pixel corner brackets mark the radius while the attacker uses only a red “!”.
        for dx in (-1,1):
            for dy in (-1,1):
                corner=(x+dx*(radius-4),y+dy*(radius-4))
                self.line(color,corner,(corner[0]-dx*9,corner[1]),2)
                self.line(color,corner,(corner[0],corner[1]-dy*9),2)

    def draw_wave_spawns(self):
        if self.room.wave_wait is None:
            return
        phase = int(self.room.wave_wait * 12) % 2
        color = "#eea17c" if phase else "#cf796e"
        for enemy in self.room.reinforcements:
            x, y = enemy.pos
            for dx, dy in ((-1,-1), (-1,1), (1,-1), (1,1)):
                corner = x + 12 * dx, y + 9 * dy
                self.line(color, corner, (corner[0] - 5 * dx, corner[1]), 2)
                self.line(color, corner, (corner[0], corner[1] - 4 * dy), 2)

    def draw_arena(self):
        self.screen.blit(self.backdrop,(0,0))
        theme=self.room.theme
        accent="#ed9279" if self.room.kind == "secret" else THEME_COLORS[theme]
        layers=self.cover_layers.copy()
        frame=0 if not self.room.cleared else (2 if self.gate_open >= 0.20 else 1)
        for direction,(point,_,_) in self.doors.items():
            sprite, pos = self.gate_sprite(direction,point,frame)
            if direction[1] > 0:
                layers.append((point[1]+4,sprite,V2(pos)))
            else:
                self.put_sprite(sprite,pos)

        flame_t=int(self.t*9)
        for index, (x,y) in enumerate(((52,88),(574,88),(52,279),(574,279))):
            shape=self.flames[(flame_t+index)%4]
            lamp=self.lantern_light[(2 if theme==2 else 0)+(flame_t+index)//2%2]
            self.screen.blit(lamp,lamp.get_rect(center=(x,y-4)),special_flags=pg.BLEND_RGB_ADD)
            self.put_sprite(shape,(x-8,y-12))
        for phase,x,y in self.motes:
            tick=int((self.t*6+phase)%15)
            if tick<10:
                drift=-tick//2 if theme==1 else tick//2
                self.rect(accent if tick in (4,5) else ("#71855e","#9e6650","#92a7ad")[theme],
                          (x+(tick//3)%3, y+drift, 1+(tick in (4,5)),1))

        if self.progress_gate():
            asset= self.themes[theme]["gate"][2]
            self.put_sprite(asset,CENTER-(28,30))
            for side in (-1,1):
                self.rect(accent,(CENTER.x+side*19-2,CENTER.y-5,3,5))
        if self.room.chest:
            chest_frame = 0 if not self.room.opened else (1 if self.t-self.room.opened_at < 0.13 else 2)
            chest=self.chests[chest_frame]
            layers.append((CHEST_RECT.bottom,chest,CENTER-(17,20)))

        for pos,ttl,radius in self.blasts:
            if ttl>0.22:
                width=max(2,round(radius*(1-ttl/0.35)))
                x,y=pos
                for dx,dy in ((0,-1),(0,1),(-1,0),(1,0),(-1,-1),(1,1),(1,-1),(-1,1)):
                    bias=width if dx==0 or dy==0 else width*0.67
                    self.rect("#f6c08f",(x+dx*bias-2,y+dy*bias-2,4,4))
            elif ttl>0:
                self.rect("#645260",(pos.x-3,pos.y-2,7,4))

        for drop in self.room.loot:
            icon=self.items.get(drop.kind) or self.weapons_art[drop.kind]
            pos=drop.position(self.t)
            self.rect("#292933",(drop.pos.x-6,drop.pos.y+5,12,3))
            if drop.ready(self.t):
                self.rect(GOLD if drop.kind in WEAPONS else accent,(pos.x-1,pos.y-11,2,2))
            size=(24,14) if drop.kind in WEAPONS else (12,12)
            self.put_sprite(icon,pos-V2(size)/2,size)

        self.draw_wave_spawns()
        self.draw_weapon_fields()
        markers=[]
        for enemy in self.enemies:
            if enemy.warning is not None:
                self.render_zone(enemy.warning,enemy.blast_radius,int(self.t*9)%2==0)
            for hazard in enemy.hazards:
                active = hazard.wait < 0.36 or int(self.t * 9) % 2 == 0
                if hazard.end is None:
                    self.render_zone(hazard.point, hazard.radius, active)
                else:
                    self.draw_beam(hazard, active)
            kind="demon" if isinstance(enemy,Demon) else f"{enemy.kind}-{theme}"
            sprite=self.actor_frame(enemy,kind,enemy.flash>0,enemy.attacking or enemy.burst>0)
            self.queue_actor(layers,enemy.pos,sprite)
            if enemy.attacking:
                height=84 if isinstance(enemy,Demon) else 53 if isinstance(enemy,Boss) else 34
                y=max(43,enemy.pos.y-height)
                markers.append((enemy.pos.x-4,y))
            if enemy.frozen or enemy.frost_marks:
                self.rect("#afe7ef",(enemy.pos.x-6,enemy.pos.y+7,12 if enemy.frozen else enemy.frost_marks*4,2))
            if enemy.ember_marks:
                self.rect("#ff9a67",(enemy.pos.x-4,enemy.pos.y+11,enemy.ember_marks*4,2))
        p=self.player
        self.queue_actor(layers,p.pos,self.actor_frame(p,p.hero,p.hurt_flash>0,p.flash>0 or p.melee_flash>0))
        for _,sprite,pos in sorted(layers,key=lambda layer:layer[0]):
            self.put_sprite(sprite,pos)

        for enemy in self.enemies:
            if isinstance(enemy,Demon) and enemy.exposed > 0:
                x,y=enemy.pos-(0,25)
                outline = "#f3ba87" if int(self.t*12)%2 else "#e68768"
                pg.draw.polygon(self.target,outline,((x,y-9),(x+8,y),(x,y+9),(x-8,y)),2)
                self.rect("#ffe7b3",(x-2,y-3,5,6))
            elif not isinstance(enemy,Boss) and not enemy.attacking:
                x,y=enemy.pos
                self.bar((x-9,y-23,18,2),enemy.hp/enemy.max_hp,"#ea786e")
        for mark in markers:
            self.put_sprite(self.warning_icon,mark)
        for hazard, _ in self.beam_flashes:
            self.draw_beam(hazard, True, fired=True)
        for start,end,color,_ in self.arcs:
            mid = start.lerp(end,.50) + unit(end-start).rotate(90)*6
            pg.draw.lines(self.target, color, False, (start,mid,end),3)
            pg.draw.lines(self.target, "#fcf2ed", False, (start,mid,end))

        aim=round(p.aim.angle_to(V2(1,0))/15)*15
        gun=self.gun_angles[p.selected][aim%360]
        self.screen.blit(gun,gun.get_rect(center=p.pos+p.aim*15))
        if p.flash>0:
            tip=p.pos+p.aim*27
            x,y=tip
            self.rect("#ffce88",(x-2,y-2,5,5))
            self.rect("#fff4bd",(x-1,y-1,3,3))
            self.rect("#f5a468",(x+p.aim.x*5,y+p.aim.y*5,2,2))
        if p.melee_flash > 0:
            self.draw_slash(p)
        if p.charge > 0:
            spot = p.pos + p.aim*25
            size = 2 + int(p.charge / RAPIER_CHARGE * 7)
            self.rect("#eff3e4",(spot.x-size//2,spot.y-size//2,size,size),1)

        for bullet in self.bullets:
            self.draw_bullet(bullet)

        for spark in self.particles:
            size=max(1,spark.size if spark.ttl>0.10 else spark.size-1)
            self.rect(spark.color,(*spark.pos,size,size))
        self.draw_hud()
        if self.state=="play":
            self.draw_cursor()

    def actor_frame(self,actor,kind,hurt,attack):
        row=3 if hurt else 2 if attack else 1 if actor.moving else 0
        rate=(5,13,17,20)[row]
        return self.frames[kind][actor.left][row][int(self.t*rate)%6]

    def draw_weapon_fields(self):
        for field in self.fields:
            x,y=field.pos
            if field.kind == "nova":
                bounds=(x-field.radius,y-field.radius/2,field.radius*2,field.radius)
                pg.draw.ellipse(self.target, "#5e313c", bounds)
                pg.draw.ellipse(self.target, "#ed9260", bounds, 2)
                for index in range(11):
                    angle = index*137.51 + int(self.t*10)*8
                    spot = field.pos + V2(4+index*2.4,0).rotate(angle)
                    self.rect("#eaa56c",(spot.x,spot.y,2,2+(index%3)))
            else:
                for index in range(3):
                    angle = self.t*250+index*120
                    points = [field.pos + V2(10+step*4,0).rotate(angle-step*15) for step in range(8)]
                    pg.draw.lines(self.target,"#ad72c1",False,points,2)
                pg.draw.circle(self.target, "#312038", field.pos, 8)

    def draw_bullet(self, bullet):
        pos = bullet.pos
        if bullet.weapon == "anvil":
            fraction = min(1, bullet.age/self.mortar_time(bullet))
            ground = pos.lerp(bullet.destination, fraction)
            pos = ground - (0,math.sin(math.pi*fraction)*64)
            pg.draw.circle(self.target,bullet.color,bullet.destination,bullet.blast,1)
            self.rect("#3c3038",(ground.x-4,ground.y-1,8,3))
            self.rect(bullet.color,(pos.x-4,pos.y-3,8,6))
            self.rect("#ffedba",(pos.x-2,pos.y-2,3,3))
            return
        x,y=pos
        if bullet.weapon == "saw":
            pg.draw.circle(self.target, "#303642",pos,6)
            pg.draw.circle(self.target,bullet.color,pos,5,2)
            angle = bullet.age*1600
            for index in range(3):
                tooth = pos+V2(4,0).rotate(angle+120*index)
                self.rect(bullet.color,(*tooth,3,3))
            return
        tail=pos-bullet.vel*(0.033 if bullet.piercing or bullet.weapon=="comet" else 0.019)
        self.line("#3a303d",pos,tail,3)
        self.line(bullet.color,pos,tail,2)
        self.rect(bullet.color,(x-2,y-2,5 if bullet.hostile else 4,4))
        self.rect("#f7e7bc",(x-1,y-1,2,2))

    def draw_slash(self, player):
        progress = 1 - player.melee_flash / MELEE_FLASH
        sweep = -61 + 88 * progress
        for radius, color, thickness in ((39,"#c77c65",4),(42,"#f6c185",4),(45,"#fff3c9",2)):
            points = [player.pos + player.slash_direction.rotate(sweep + offset) * radius
                      for offset in range(0,37,6)]
            pg.draw.lines(self.target, color, False, points, thickness)

    def draw_beam(self, hazard, active, fired=False):
        axis = hazard.end - hazard.point
        if fired:
            self.line("#b95058", hazard.point, hazard.end, hazard.radius * 2)
            self.line("#ff9f88", hazard.point, hazard.end, hazard.radius)
            self.line("#fff0c0", hazard.point, hazard.end, 3)
        else:
            normal = axis.normalize().rotate(90) * hazard.radius
            color = "#df786d" if active else "#9c5660"
            for offset in (-normal, normal):
                self.line(color, hazard.point + offset, hazard.end + offset)
            self.line("#ad5d63", hazard.point, hazard.end)

    def queue_actor(self,queue,pos,frame):
        side=frame.get_width()
        shadow=pg.Rect(0,0,int(side*0.67),int(side*0.16))
        shadow.center=pos+(0,4)
        self.rect("#262832",shadow)
        self.rect("#20232c",(shadow.x+2,shadow.y+1,shadow.w-4,max(1,shadow.h-2)))
        queue.append((pos.y,frame,pos-(side/2,side*0.78)))

    def bar(self,bounds,fraction,color):
        x,y,w,h=bounds
        self.rect("#1c1b25",(x-1,y-1,w+2,h+2))
        self.rect("#42404a",bounds)
        filled=int(w*max(0,min(1,fraction)))
        if filled:
            self.rect(color,(x,y,filled,h))

    def draw_map(self):
        xs,ys=zip(*self.rooms)
        min_x,min_y=min(xs),min(ys)
        step=min(10,32//(max(ys)-min_y+1))
        map_width=(max(xs)-min_x+1)*step
        map_height=(max(ys)-min_y+1)*step
        self.panel((547,3,73,37),"#211f2a","#514957")
        start=V2(583-map_width//2,21-map_height//2)
        positions={key:start+((key[0]-min_x)*step,(key[1]-min_y)*step)
                   for key in self.rooms}
        for coord,room in self.rooms.items():
            for dx,dy in room.links:
                point=positions[coord]+(step/2,step/2)
                neighbor=self.rooms[(coord[0]+dx,coord[1]+dy)]
                color=THEME_COLORS[room.theme] if room.visited and neighbor.visited else "#565461"
                self.line(color,point,point+(dx*step/2,dy*step/2))
        for coord,room in self.rooms.items():
            x,y=positions[coord]
            color=THEME_COLORS[room.theme] if room.visited else "#767482"
            self.rect(color,(x+1,y+1,step-2,step-2))
        px,py=positions[self.coord]+(step//2,step//2)
        self.rect("#461e2e",(px-2,py-2,5,5))
        self.rect("#ff495b",(px-1,py-1,3,3))

    def draw_hud(self):
        self.rect(INK,(0,0,WIDTH,43))
        self.rect(INK,(0,336,WIDTH,24))
        self.line("#6d5b61",(19,42),(621,42))
        self.line("#6d5b61",(19,336),(621,336))
        p=self.player
        self.put_sprite(self.items["vital"],(21,13),(15,15))
        self.label(f"{p.hp}/{p.max_hp}",42,10,2)
        self.bar((42,30,97,4),p.hp/p.max_hp,"#e98476")
        location=self.room.theme
        if self.room.kind == "secret":
            self.label("РАЗЛОМ",176,8,2,"#f0a77f")
            self.label("СЕКРЕТНАЯ АРЕНА",178,27,1,MUTED)
        else:
            self.label(f"{('I','II','III')[location]}   {LEVELS[location]}",176,8,2,THEME_COLORS[location])
            self.label(f"ЭТАЖ {floor_of(self.level)}/5   /   {ROOM_LABELS[self.room.kind]}",178,27,1,MUTED)
        if self.room.kind in ("combat", "vault") and self.enemies:
            self.label(f"ВОЛНА {self.room.wave}  ВРАГИ {len(self.enemies)}",426,28,1,GOLD)
        self.draw_map()

        for index,clip in enumerate(p.slots):
            x=19+index*137
            current=index==p.active
            self.panel((x,341,128,15), "#39343d" if current else "#262431",
                       GOLD if current else "#5f525d")
            self.label(str(index+1),x+5,345,1,GOLD if current else MUTED)
            if clip:
                self.put_sprite(self.weapons_art[clip.name],(x+15,344),(19,10))
                self.label(WEAPONS[clip.name].name,x+37,345,1)
                ammo=str(clip.rounds) if clip.reserve is None else f"{clip.rounds}/{clip.reserve}"
                if current and p.reload:
                    ammo=f"{p.reload:0.1f}С"
                self.label(ammo,x+123,345,1,GOLD if current else MUTED,"right")
            else:
                self.label("Пусто",x+37,345,1,MUTED)
        self.label(f"ПОВЕРЖЕНО {self.kills}",619,345,1,MUTED,"right")
        blade = GOLD if p.melee_timer == 0 else MUTED
        pg.draw.polygon(self.target, blade, ((297,350),(304,343),(305,343),(305,345),(299,352)))
        self.line(blade,(296,349),(300,353))
        self.rect(blade,(295,353,2,2))
        self.bar((310,347,24,3),1-p.melee_timer/MELEE_INTERVAL,GOLD)
        meter = {"pistol":p.focus_hits/5, "pulse":p.spin, "rapier":p.charge/RAPIER_CHARGE}.get(p.selected)
        if meter is not None:
            self.bar((346,347,22,3),meter,p.weapon.color)

        boss=next((e for e in self.enemies if isinstance(e,Boss)),None)
        if isinstance(boss,Demon):
            self.panel((139,69,362,27),"#302239","#a56a70")
            self.label(boss.name,150,74,1,"#fbd2a4")
            self.label(f"{max(0,boss.hp)}/{boss.max_hp}",490,74,1,"#fbd2a4","right")
            self.label("ЯДРО ОТКРЫТО" if boss.exposed else f"ФАЗА {boss.phase}/3",
                       320,74,1,GOLD if boss.exposed else MUTED,"center")
            self.bar((150,87,340,4),boss.hp/boss.max_hp,GOLD if boss.exposed else "#ef776f")
        elif boss:
            self.panel((200,74,240,23),edge="#9b676e")
            self.label(boss.name,320,78,1,"#f8c69c","center")
            self.bar((211,90,218,3),boss.hp/boss.max_hp,
                     "#e8786d" if boss.enraged else "#cb8c75")

        if self.state=="play":
            if self.room.wave_wait is not None:
                self.panel((220,80,200,24),"#3b2b3d","#c7856c")
                self.label("ВТОРАЯ ВОЛНА",320,85,2,"#ffd79b","center")
            hint=self.nearby()[2]
            if hint:
                x=max(106,min(WIDTH-106,p.pos.x))
                y=p.pos.y-47 if p.pos.y>117 else p.pos.y+24
                self.panel((x-100,y,200,15),edge="#8e786b")
                self.label(hint,x,y+4,1,GOLD,"center")
            elif self.t<self.message_until:
                self.label(self.message,405,345,1,THEME_COLORS[location],"center")
            elif self.room.kind=="entry" and self.t-self.room_arrived<1.15:
                self.panel((212,106,216,31))
                self.label(LEVELS[location],320,112,1,THEME_COLORS[location],"center")
                self.label(f"Этаж {floor_of(self.level)}/5",320,125,1,PAPER,"center")

    def draw_cursor(self):
        x,y=self.mouse()
        if ARENA.collidepoint(x,y):
            for a,b in (((x-7,y),(x-3,y)),((x+3,y),(x+7,y)),
                        ((x,y-7),(x,y-3)),((x,y+3),(x,y+7))):
                self.line("#e8d6a9",a,b)
            self.rect("#453343",(x,y,1,1))

    def overlay(self):
        self.screen.blit(self.scrim,(0,0))

    def draw_menu(self):
        self.screen.blit(self.cover,(0,0))
        self.label("DUNGEONFALL",28,82,3,"#8d5452")
        self.label("DUNGEONFALL",28,79,3,"#f4d8a7")
        self.label("ПОДЗЕМЕЛЬЕ ТРЁХ ПЕЧАТЕЙ",30,112,1,"#c5a581")
        y=146
        self.button("Новая игра",27,y,self.show_controls,190)
        y+=34
        if self.profile.checkpoint is not None:
            level=self.profile.checkpoint["level"]
            self.button(f"Продолжить {region_of(level)+1}-{floor_of(level)}",
                        27,y,self.continue_run,190)
            y+=34
        self.button("Настройки",27,y,self.settings,190)
        self.button("Выход",27,y+34,self.quit,190)
        self.label(f"ЭТАЖ {self.profile.best}/{TOTAL_FLOORS}   ПОБЕДЫ {self.profile.wins}",30,322,1,"#b5a396")

    def draw_controls(self):
        self.panel((32,35,576,290),"#302a37","#917672")
        self.label("ПЕРЕД СПУСКОМ",57,55,2,GOLD)
        self.label("УПРАВЛЕНИЕ",58,87,1,MUTED)
        controls=(("WASD / СТРЕЛКИ","Движение"),("МЫШЬ / ЛКМ","Прицел и огонь"),
                  ("ПКМ","Удар вблизи"),("R","Перезарядка"),("1 / 2","Слоты оружия"),
                  ("E","Ворота / взять"),("ESC / F11","Пауза / экран"))
        for i,(key,meaning) in enumerate(controls):
            y=111+i*21
            self.label(key,60,y,1,"#e5b883")
            self.label(meaning,151,y,1,PAPER)
        self.label("ГЕРОЙ",344,87,1,MUTED)
        for index,(key,(name,hp,speed)) in enumerate(HEROES.items()):
            y=109+index*74
            selected=key==self.chosen_hero
            bounds=(344,y,235,64)
            self.panel(bounds,"#464050" if selected else "#30303d",
                       GOLD if selected else "#79676c")
            self.buttons.append((pg.Rect(bounds),lambda k=key:self.choose_hero(k)))
            sprite=self.frames[key][0][0][int(self.t*5)%6]
            self.put_sprite(sprite,(351,y+11),(41,41))
            self.label(f"{index+1}  {name}",401,y+10,1,GOLD if selected else PAPER)
            self.label(f"{hp} ЗДОРОВЬЯ",402,y+27,1,PAPER)
            self.label("БЫСТРЕЕ" if speed>150 else "БОЛЬШЕ ЗДОРОВЬЯ",402,y+44,1,MUTED)
        self.button("Начать спуск",57,274,self.start,181)
        self.button("Назад",251,274,self.escape,114)

    def draw_settings(self):
        self.panel((121,36,398,284),"#302a37","#917672")
        self.label("НАСТРОЙКИ",147,53,2,GOLD)
        options=self.profile.options
        for index,(name,key) in enumerate((("Музыка","music"),("Звуки","effects"))):
            y=94+32*index
            self.label(name,148,y+10,1)
            self.button("-",332,y,lambda k=key:self.option(k,-1),34)
            self.label(f"{options[key]}%",393,y+10,1,GOLD,"center")
            self.button("+",421,y,lambda k=key:self.option(k,1),34)
        descriptions=(
            ("Масштаб окна",f"{options['scale']}X","scale"),
            ("Полный экран (F11)","Вкл." if options["fullscreen"] else "Выкл.","fullscreen"),
            ("Встряска при уроне","Вкл." if options["shake"] else "Выкл.","shake"),
        )
        for i,(name,value,key) in enumerate(descriptions):
            y=158+32*i
            self.label(name,148,y+10,1)
            self.button(value,332,y,lambda k=key:self.option(k),123)
        self.button("Назад",148,263,self.escape,122)
        if not self.audio.ready:
            self.label("Аудиоустройство недоступно",149,304,1,MUTED)

    def draw_swap(self):
        drop=self.pending_weapon
        weapon=WEAPONS[drop.kind]
        self.panel((111,54,418,244),"#302a37","#917672")
        self.label(weapon.name,320,72,2,GOLD,"center")
        self.label(weapon.note,320,102,1,PAPER,"center")
        self.put_sprite(self.weapons_art[drop.kind],(291,111),(58,33))
        self.label("ВЫБЕРИ СЛОТ",320,151,1,MUTED,"center")
        for index in range(2):
            clip=self.player.slots[index]
            text=WEAPONS[clip.name].name if clip else "Пусто"
            x=130+index*195
            self.button(f"{index+1} {text}",x,166,lambda i=index:self.equip_pending(i),179)
            note="ОРУЖИЕ УПАДЁТ НА ПОЛ" if clip else "СВОБОДНЫЙ СЛОТ"
            self.label(note,x,203,1,MUTED)
        self.button("Оставить",245,246,self.escape,150)

    def draw_end(self):
        won=self.state=="win"
        self.overlay()
        self.panel((189,81,262,207),"#302a37","#917672")
        demon = self.room.kind == "secret"
        title = ("ДЕМОН ПОВЕРЖЕН" if demon else "РАЗЛОМ ЗАКРЫТ") if won else "ПОРАЖЕНИЕ"
        self.label(title,
                   320,101,2,GOLD if won else RED,"center")
        result = f"ЭТАЖ {self.level}/{TOTAL_FLOORS}  ПОВЕРЖЕНО {self.kills}"
        if demon:
            result = "ПОБЕДА НА СЕКРЕТНОЙ АРЕНЕ" if won else "ДЕМОН РАЗЛОМА"
        self.label(result,320,139,1,PAPER,"center")
        self.button("Новая попытка",211,174,self.show_controls,218)
        self.button("Главное меню",211,211,lambda:self.change_state("menu"),218)

    def draw(self):
        self.buttons.clear()
        if self.state=="menu":
            self.draw_menu()
        elif self.state in ("settings","controls"):
            if self.state=="settings" and self.settings_from=="pause":
                self.draw_arena()
            else:
                self.screen.blit(self.cover,(0,0))
            self.overlay()
            if self.state=="settings":
                self.draw_settings()
            else:
                self.draw_controls()
        else:
            self.draw_arena()
            if self.state=="pause":
                self.overlay()
                self.panel((207,80,226,195),"#302a37","#917672")
                self.label("ПАУЗА",320,100,2,GOLD,"center")
                self.button("Продолжить",222,135,lambda:self.change_state("play"))
                self.button("Настройки",222,173,self.settings)
                self.button("Главное меню",222,211,lambda:self.change_state("menu"))
            elif self.state=="swap":
                self.overlay()
                self.draw_swap()
            elif self.state in ("dead","win"):
                self.draw_end()
        if self.profile.error:
            self.panel((359,338,268,18))
            self.label("ПРОВЕРЬ ФАЙЛ СОХРАНЕНИЯ",368,343,1,RED)
        rect=self.viewport()
        if self.state=="play" and self.shake>0 and self.profile.options["shake"]:
            rect.move_ip(self.fx_rng.choice((-3,0,3)),self.fx_rng.choice((-3,0,3)))
        self.window.fill("#14131c")
        frame=self.screen if rect.size==(WIDTH,HEIGHT) else pg.transform.scale(self.screen,rect.size)
        self.window.blit(frame,rect)
        pg.display.flip()

    def run(self):
        while self.running:
            dt = min(self.clock.tick(60) / 1000, 0.05)
            self.t += dt
            self.events()
            self.update(dt)
            self.draw()
        pg.quit()


if __name__ == "__main__":
    Game().run()
