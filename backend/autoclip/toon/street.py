"""Golden-hour street set: painted layers with depth, plus live elements.

Static layers are rendered once into images. Per frame, the camera transform
is applied with a depth factor (parallax), and the living parts of the set are
drawn: swaying foliage and bougainvillea, moving leaf light (dapples), floating
dust, falling leaves and a slow reflection travelling over the car.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass

import skia

from .draw import (
    INK,
    PathBuilder,
    cel,
    circle,
    clipped,
    ellipse,
    fill,
    linear,
    mix,
    radial,
    rrect,
    shade_of,
    smooth,
    stroke,
)

W, H = 1080, 1920
MARGIN = 140
CAR_SCALE = 1.32


@dataclass
class Camera:
    zoom: float = 1.0
    fx: float = W / 2
    fy: float = H / 2

    def apply(self, c: skia.Canvas, depth: float) -> None:
        z = 1 + (self.zoom - 1) * depth
        fx = W / 2 + (self.fx - W / 2) * depth
        fy = H / 2 + (self.fy - H / 2) * depth
        c.translate(W / 2, H / 2)
        c.scale(z, z)
        c.translate(-fx, -fy)


def _layer(draw_fn) -> skia.Image:
    surface = skia.Surface(W + 2 * MARGIN, H + 2 * MARGIN)
    c = surface.getCanvas()
    c.clear(skia.ColorTRANSPARENT)
    c.translate(MARGIN, MARGIN)
    draw_fn(c)
    return surface.makeImageSnapshot()


def _sprite(width: int, height: int, draw_fn) -> skia.Image:
    surface = skia.Surface(width, height)
    c = surface.getCanvas()
    c.clear(skia.ColorTRANSPARENT)
    draw_fn(c)
    return surface.makeImageSnapshot()


def _blurred(image: skia.Image, sigma: float) -> skia.Image:
    surface = skia.Surface(image.width(), image.height())
    c = surface.getCanvas()
    c.clear(skia.ColorTRANSPARENT)
    paint = skia.Paint(ImageFilter=skia.ImageFilters.Blur(sigma, sigma))
    c.drawImage(image, 0, 0, skia.SamplingOptions(), paint)
    return surface.makeImageSnapshot()


def _leaf(c, x, y, length, width, angle, colour, alpha=1.0, vein=None):
    c.save()
    c.translate(x, y)
    c.rotate(angle)
    leaf = (
        PathBuilder().m(0, 0).q(width, length * 0.45, 0, length).q(-width, length * 0.45, 0, 0).z()
    )
    c.drawPath(leaf, fill(colour, alpha))
    if vein:
        c.drawPath(
            PathBuilder().m(0, length * 0.08).l(0, length * 0.9).done(),
            stroke(vein, max(1.0, width * 0.12), 0.6 * alpha),
        )
    c.restore()


class StreetSet:
    """Everything that is not a character."""

    def __init__(self, seed: int = 11, car: bool = True):
        self.has_car = car
        self.rng = random.Random(seed)
        self.far = _blurred(_layer(self._far), 2.2)
        self.mid = _layer(self._building_and_street)
        self.car_image = _layer(self._car)
        self.tree_back = _sprite(760, 760, lambda c: self._foliage(c, back=True))
        self.tree_front = _sprite(760, 760, lambda c: self._foliage(c, back=False))
        self.trunk = _layer(self._trunk)
        self.flowers = [
            _sprite(260, 360, lambda c, i=i: self._bougainvillea(c, i)) for i in range(3)
        ]
        self.plant = [
            _blurred(_sprite(560, 700, lambda c, i=i: self._plant_leaf(c, i)), 4.5)
            for i in range(5)
        ]
        self.dapples = self._dapple_sprite()
        self.grade_image = self._grade_overlay()
        rng = random.Random(seed + 5)
        self.motes = [
            (
                rng.uniform(0, W),
                rng.uniform(150, H * 0.75),
                rng.uniform(1.6, 3.6),
                rng.uniform(0, math.tau),
                rng.uniform(8, 22),
            )
            for _ in range(34)
        ]

    # ------------------------------------------------------------ static painting

    def _far(self, c: skia.Canvas) -> None:
        c.drawRect(
            skia.Rect.MakeLTRB(-MARGIN, -MARGIN, W + MARGIN, 900),
            fill(
                "#000000", shader=linear((0, -MARGIN), (0, 700), ["#9ec7d4", "#d9e2cf", "#f6d79f"])
            ),
        )
        c.drawPath(ellipse(240, 40, 220, 160), fill("#fff3c8", 0.55, blur=60))
        # Hillside with small houses, cooled and hazed by distance.
        hill = smooth(
            [
                (-200, 330),
                (-40, 190),
                (120, 150),
                (260, 120),
                (380, 160),
                (520, 230),
                (700, 300),
                (900, 330),
                (1300, 360),
                (1300, 900),
                (-200, 900),
            ]
        )
        c.drawPath(hill, fill("#90a06a"))
        rng = random.Random(4)
        for _ in range(26):
            x = rng.uniform(-60, 560)
            y = rng.uniform(140, 520) + max(0, (x - 300) * 0.25)
            w, h = rng.uniform(40, 90), rng.uniform(45, 110)
            wall = rng.choice(["#f2eadb", "#efe2c4", "#f4d9b4", "#e9e4dc"])
            c.drawRect(skia.Rect.MakeLTRB(x, y, x + w, y + h), fill(wall))
            c.drawRect(skia.Rect.MakeLTRB(x + w * 0.7, y, x + w, y + h), fill("#c9b79c", 0.55))
            roof = (
                PathBuilder().m(x - 6, y + 2).l(x + w * 0.5, y - h * 0.22).l(x + w + 6, y + 2).z()
            )
            c.drawPath(roof, fill(rng.choice(["#c4623e", "#b5573a", "#d07a4f"])))
            for wx in range(int(x + 8), int(x + w - 10), 18):
                for wy in range(int(y + 12), int(y + h - 14), 24):
                    c.drawRect(skia.Rect.MakeLTRB(wx, wy, wx + 7, wy + 10), fill("#5d6f78", 0.8))
        for _ in range(16):
            x, y = rng.uniform(-80, 600), rng.uniform(200, 620)
            c.drawPath(
                ellipse(x, y, rng.uniform(30, 60), rng.uniform(26, 44)),
                fill(rng.choice(["#6f8a4c", "#7f9a55", "#5f7b44"])),
            )
        # Mid-distance pale buildings down the street, behind the lamp post.
        for x, y, w, tone in [
            (-60, 420, 220, "#e8d4b0"),
            (150, 520, 170, "#f0dfc0"),
            (300, 600, 140, "#e2cba6"),
        ]:
            c.drawRect(skia.Rect.MakeLTRB(x, y, x + w, 1200), fill(tone))
            c.drawRect(skia.Rect.MakeLTRB(x + w - 26, y, x + w, 1200), fill("#bfa27e", 0.6))
            for wy in range(int(y + 40), 1120, 110):
                for wx in range(int(x + 24), int(x + w - 40), 62):
                    c.drawPath(rrect(wx, wy, wx + 32, wy + 62, 14), fill("#6c8794"))
                    c.drawPath(rrect(wx, wy, wx + 32, wy + 62, 14), stroke("#f7ecd8", 4))
        c.drawRect(
            skia.Rect.MakeLTRB(-MARGIN, -MARGIN, W + MARGIN, H + MARGIN), fill("#f3d3a0", 0.22)
        )

    def _building_and_street(self, c: skia.Canvas) -> None:
        left = 430
        # Facade, lit by low sun from the left.
        facade = skia.Rect.MakeLTRB(left, -MARGIN, W + MARGIN, 1185)
        c.drawRect(
            facade,
            fill("#000000", shader=linear((left, 0), (W, 900), ["#f0cd84", "#e3b46c", "#c9925a"])),
        )
        c.drawRect(skia.Rect.MakeLTRB(left - 30, -MARGIN, left + 26, 1185), fill("#f4dca2"))
        c.drawRect(skia.Rect.MakeLTRB(left + 18, -MARGIN, left + 26, 1185), fill("#b98852", 0.6))
        for y in (330, 760):
            c.drawRect(skia.Rect.MakeLTRB(left - 30, y, W + MARGIN, y + 26), fill("#f6e2b4"))
            c.drawRect(
                skia.Rect.MakeLTRB(left - 30, y + 26, W + MARGIN, y + 36), fill("#a97a4a", 0.55)
            )
        # Azulejo panel on the right.
        tiles_x = 860
        c.drawRect(skia.Rect.MakeLTRB(tiles_x, -MARGIN, W + MARGIN, 760), fill("#e9eef2"))
        size = 44
        for gx in range(tiles_x, W + MARGIN, size):
            for gy in range(-MARGIN, 760, size):
                cx, cy = gx + size / 2, gy + size / 2
                c.drawPath(circle(cx, cy, 9), fill("#2f5ea8"))
                for a in range(4):
                    ang = a * math.pi / 2 + math.pi / 4
                    c.drawPath(
                        ellipse(cx + math.cos(ang) * 15, cy + math.sin(ang) * 15, 6, 6),
                        fill("#3d6fbf", 0.9),
                    )
                for corner in ((gx, gy), (gx + size, gy), (gx, gy + size), (gx + size, gy + size)):
                    c.drawPath(circle(*corner, 7), fill("#2a4f93", 0.85))
                c.drawRect(
                    skia.Rect.MakeLTRB(gx, gy, gx + size, gy + size), stroke("#b9c6d6", 1, 0.7)
                )
        c.drawRect(skia.Rect.MakeLTRB(tiles_x, -MARGIN, W + MARGIN, 760), fill("#e8a95c", 0.18))
        c.drawRect(skia.Rect.MakeLTRB(tiles_x - 14, -MARGIN, tiles_x, 760), fill("#f4dfae"))

        def window(x0, y0, x1, y1, arch=True):
            r = (x1 - x0) / 2
            frame = PathBuilder().m(x0, y1).l(x0, y0 + (r if arch else 0))
            if arch:
                frame.q(x0, y0, x0 + r, y0).q(x1, y0, x1, y0 + r)
            else:
                frame.l(x1, y0)
            frame.l(x1, y1)
            path = frame.z()
            c.drawPath(offset_path(path, 10, 8), fill("#7d5532", 0.35))
            c.drawPath(path, fill("#264a63"))
            glass = linear((x0, y0), (x1, y1), ["#3f6f86", "#1b3447", "#2d5870"])
            inner = offset_scale(path, 0.84, (x0 + x1) / 2, (y0 + y1) / 2)
            c.drawPath(inner, fill("#1b3447", shader=glass))
            with clipped(c, inner):
                c.drawPath(
                    PathBuilder().m(x0, y1 - 40).l(x1, y0 + 30).done(), stroke("#f5d9a8", 18, 0.18)
                )
                c.drawPath(
                    PathBuilder().m(x0 + 30, y1).l(x1, y0 + 120).done(), stroke("#f5d9a8", 8, 0.12)
                )
            c.drawPath(
                PathBuilder().m((x0 + x1) / 2, y0 + 6).l((x0 + x1) / 2, y1).done(),
                stroke("#2f5d7c", 7),
            )
            for k in (0.4, 0.68):
                yy = y0 + (y1 - y0) * k
                c.drawPath(PathBuilder().m(x0 + 4, yy).l(x1 - 4, yy).done(), stroke("#2f5d7c", 6))
            c.drawPath(path, stroke("#2f5d7c", 9))
            c.drawPath(path, stroke(INK, 2, 0.6))
            c.drawRect(skia.Rect.MakeLTRB(x0 - 14, y1, x1 + 14, y1 + 16), fill("#f7e6bd"))
            c.drawRect(skia.Rect.MakeLTRB(x0 - 14, y1 + 16, x1 + 14, y1 + 22), fill("#9c7046", 0.6))

        window(490, 410, 610, 700)
        window(690, 410, 810, 700)
        window(920, 470, 1060, 760)
        window(600, -60, 720, 250, arch=False)
        window(880, -60, 1000, 250, arch=False)
        window(470, 830, 610, 1150)
        # Balcony slab and iron railing.
        c.drawRect(skia.Rect.MakeLTRB(540, 250, W + MARGIN, 276), fill("#f3ddab"))
        c.drawRect(skia.Rect.MakeLTRB(540, 276, W + MARGIN, 290), fill("#8d6644", 0.7))
        rail = stroke("#22313a", 5)
        c.drawPath(PathBuilder().m(546, 130).l(W + MARGIN, 130).done(), stroke("#22313a", 8))
        for x in range(556, W + MARGIN, 26):
            c.drawPath(PathBuilder().m(x, 134).l(x, 250).done(), rail)
        for x in range(569, W + MARGIN, 52):
            arc = skia.Path()
            arc.addOval(skia.Rect.MakeLTRB(x - 13, 160, x + 13, 200))
            c.drawPath(arc, stroke("#22313a", 3))
        c.drawPath(PathBuilder().m(546, 236).l(W + MARGIN, 236).done(), stroke("#22313a", 5))
        # Far pavement and kerb.
        c.drawRect(skia.Rect.MakeLTRB(-MARGIN, 1150, W + MARGIN, 1196), fill("#d8c3a0"))
        c.drawRect(skia.Rect.MakeLTRB(-MARGIN, 1192, W + MARGIN, 1210), fill("#a98f6e"))
        # Calçada: cobbles grow toward the camera (simple perspective).
        rng = random.Random(9)
        y = 1210.0
        row = 0
        while y < H + MARGIN:
            h = 12 + (y - 1210) * 0.055
            x = -MARGIN - rng.uniform(0, h)
            while x < W + MARGIN:
                w = h * rng.uniform(0.8, 1.35)
                jitter = rng.uniform(-0.12, 0.12) * h
                tone = rng.choice(["#d9cdb8", "#cbbda4", "#e2d8c6", "#c2b297", "#d4c6ae"])
                stone = smooth(
                    [
                        (x + 2 + rng.uniform(0, h * 0.12), y + 2 + jitter),
                        (x + w * 0.5, y + 1 + rng.uniform(0, h * 0.1)),
                        (x + w - 2 - rng.uniform(0, h * 0.12), y + 2 - jitter),
                        (x + w - 2, y + h * 0.5),
                        (x + w - 3 - rng.uniform(0, h * 0.1), y + h - 2),
                        (x + w * 0.5, y + h - 1 - rng.uniform(0, h * 0.1)),
                        (x + 3, y + h - 2),
                        (x + 2, y + h * 0.5),
                    ]
                )
                c.drawPath(stone, fill(tone))
                c.drawPath(
                    ellipse(x + w * 0.45, y + h * 0.35, w * 0.3, h * 0.18), fill("#fff6e6", 0.28)
                )
                c.drawPath(
                    PathBuilder().m(x + 3, y + h - 2).l(x + w - 3, y + h - 2).done(),
                    stroke("#7d6c58", max(1.0, h * 0.08), 0.45),
                )
                x += w
            y += h
            row += 1
        c.drawRect(
            skia.Rect.MakeLTRB(-MARGIN, 1210, W + MARGIN, H + MARGIN),
            fill("#000000", shader=linear((0, 1210), (0, H), ["#6d5a48", "#6d5a48"], [0.35, 0.0])),
        )
        # Fallen leaves.
        for _ in range(40):
            x, y2 = rng.uniform(-50, W + 50), rng.uniform(1220, H + 50)
            size = 10 + (y2 - 1200) * 0.03
            _leaf(
                c,
                x,
                y2,
                size * 1.6,
                size * 0.6,
                rng.uniform(0, 360),
                rng.choice(["#e0a33a", "#d98a2b", "#c9a140", "#b9772c"]),
                0.9,
            )
        # Lamp post on the left pavement.
        c.drawPath(PathBuilder().m(396, 1180).l(396, 330).done(), stroke("#2a2c2e", 11))
        c.drawPath(PathBuilder().m(396, 330).q(396, 290, 430, 286).done(), stroke("#2a2c2e", 7))
        lamp = PathBuilder().m(414, 286).l(446, 286).l(456, 330).l(404, 330).z()
        c.drawPath(lamp, fill("#2a2c2e"))
        c.drawPath(rrect(410, 330, 450, 340, 3), fill("#ffe1a0", 0.9))
        c.drawRect(skia.Rect.MakeLTRB(386, 1150, 406, 1182), fill("#2a2c2e"))

    def _car(self, c: skia.Canvas) -> None:
        c.translate(545, 1200)
        c.scale(CAR_SCALE, CAR_SCALE)
        c.translate(-545, -1200)
        c.drawPath(ellipse(545, 1238, 360, 34), fill("#2c1d16", 0.55, blur=16))
        body = (
            PathBuilder()
            .m(212, 1176)
            .l(206, 1112)
            .q(210, 1052, 262, 1038)
            .l(312, 1022)
            .q(352, 948, 404, 914)
            .q(500, 892, 598, 900)
            .q(650, 912, 716, 1006)
            .q(800, 1018, 846, 1042)
            .q(872, 1058, 872, 1104)
            .l(872, 1168)
            .q(870, 1190, 840, 1192)
            .l(232, 1192)
            .q(212, 1190, 212, 1176)
            .z()
        )
        body_shader = linear(
            (0, 900),
            (0, 1192),
            ["#ff6b5c", "#d42f30", "#b81f26", "#7c1218"],
            stops=[0, 0.35, 0.62, 1],
        )
        c.drawPath(body, fill("#c3262b", shader=body_shader))
        with clipped(c, body):
            # Lower body in shadow, upper edge catching the sun.
            c.drawRect(skia.Rect.MakeLTRB(200, 1120, 880, 1200), fill("#5a0c12", 0.35))
            c.drawPath(
                PathBuilder().m(230, 1046).q(520, 1030, 840, 1050).done(), stroke("#ffb19a", 5, 0.7)
            )
            c.drawPath(
                PathBuilder().m(240, 1100).q(520, 1088, 860, 1102).done(),
                stroke("#ff8f7c", 3, 0.45),
            )
            for x in range(240, 880, 70):
                c.drawPath(ellipse(x + 20, 1070, 26, 10), fill("#ffd7b8", 0.12, blur=6))
        # Windows with sky and leaf reflections.
        glass = (
            PathBuilder()
            .m(330, 1018)
            .q(368, 950, 412, 926)
            .q(500, 910, 590, 916)
            .q(630, 930, 690, 1010)
            .z()
        )
        c.drawPath(
            glass,
            fill(
                "#1d3340", shader=linear((330, 920), (690, 1010), ["#7fa9b5", "#2a4757", "#16262f"])
            ),
        )
        with clipped(c, glass):
            c.drawPath(PathBuilder().m(380, 1030).l(470, 900).done(), stroke("#e8f1ee", 26, 0.22))
            c.drawPath(PathBuilder().m(560, 1030).l(620, 905).done(), stroke("#e8f1ee", 12, 0.18))
            for _ in range(10):
                x, y = self.rng.uniform(330, 690), self.rng.uniform(920, 1010)
                c.drawPath(ellipse(x, y, 18, 8), fill("#2d4a2a", 0.35, blur=3))
        c.drawPath(PathBuilder().m(502, 916).l(512, 1014).done(), stroke("#2b1418", 12))
        c.drawPath(glass, stroke(INK, 3, 0.8))
        # Panel lines, handles, mirror, lights.
        line = stroke("#6d1016", 2.6, 0.8)
        c.drawPath(PathBuilder().m(512, 1016).l(518, 1180).done(), line)
        c.drawPath(PathBuilder().m(334, 1022).q(318, 1100, 330, 1180).done(), line)
        c.drawPath(PathBuilder().m(700, 1014).q(712, 1100, 704, 1180).done(), line)
        for hx in (440, 640):
            c.drawPath(rrect(hx, 1060, hx + 40, 1070, 5), fill("#f2c3b6", 0.9))
            c.drawPath(rrect(hx, 1060, hx + 40, 1070, 5), stroke("#5a0c12", 1.5, 0.8))
        mirror = PathBuilder().m(700, 1004).q(730, 984, 752, 996).q(748, 1020, 712, 1022).z()
        cel(c, mirror, "#c3262b", shadow=0.35, depth=6, width=2.5)
        head = PathBuilder().m(820, 1058).q(860, 1060, 870, 1080).q(848, 1094, 818, 1080).z()
        c.drawPath(head, fill("#fff6dc"))
        c.drawPath(head, stroke(INK, 2.5, 0.8))
        c.drawPath(ellipse(852, 1074, 40, 22), fill("#ffe9b0", 0.35, blur=10))
        c.drawPath(rrect(836, 1118, 872, 1150, 8), fill("#2a1416"))
        c.drawPath(rrect(206, 1070, 222, 1100, 5), fill("#ff9a76"))
        c.drawPath(body, stroke(INK, 3.2, 0.9))
        # Wheels in their arches.
        for wx in (318, 716):
            c.drawPath(ellipse(wx, 1180, 78, 70), fill("#2b0d10"))
            c.drawPath(circle(wx, 1188, 62), fill("#1f1d22"))
            c.drawPath(circle(wx, 1188, 62), stroke("#3a383f", 6))
            rim = circle(wx, 1188, 40)
            c.drawPath(
                rim,
                fill(
                    "#b8bec4",
                    shader=linear(
                        (wx - 40, 1150), (wx + 40, 1228), ["#eef2f4", "#9aa2aa", "#6b737b"]
                    ),
                ),
            )
            for k in range(5):
                a = k * math.tau / 5 - math.pi / 2
                spoke = PathBuilder().m(
                    wx + math.cos(a - 0.22) * 12, 1188 + math.sin(a - 0.22) * 12
                )
                spoke.l(wx + math.cos(a - 0.12) * 37, 1188 + math.sin(a - 0.12) * 37)
                spoke.l(wx + math.cos(a + 0.12) * 37, 1188 + math.sin(a + 0.12) * 37)
                spoke.l(wx + math.cos(a + 0.22) * 12, 1188 + math.sin(a + 0.22) * 12)
                c.drawPath(spoke.z(), fill("#5b6168"))
            c.drawPath(circle(wx, 1188, 11), fill("#d4d9dd"))
            c.drawPath(rim, stroke(INK, 2, 0.7))

    def _trunk(self, c: skia.Canvas) -> None:
        trunk = smooth(
            [
                (-120, 760),
                (-40, 520),
                (40, 330),
                (120, 170),
                (230, 40),
                (300, -40),
                (380, -150),
                (330, -170),
                (230, -60),
                (150, 40),
                (60, 180),
                (-40, 360),
                (-140, 560),
            ]
        )
        cel(c, trunk, "#5b3a26", shadow=0.4, depth=18, rim=0.5, rim_colour="#e3a35c", rim_depth=7)
        branch = smooth(
            [
                (150, 80),
                (300, 60),
                (470, 10),
                (560, -40),
                (548, -54),
                (460, -10),
                (290, 40),
                (160, 60),
            ]
        )
        cel(c, branch, "#5b3a26", shadow=0.35, depth=8, rim=0.4, rim_colour="#e3a35c")
        for y in range(-120, 700, 46):
            c.drawPath(
                PathBuilder()
                .m(-60 + (700 - y) * 0.28, y)
                .q(-40 + (700 - y) * 0.28, y + 20, -50 + (700 - y) * 0.28, y + 40)
                .done(),
                stroke("#3a2216", 3, 0.5),
            )

    def _foliage(self, c: skia.Canvas, back: bool) -> None:
        rng = random.Random(21 if back else 22)
        palette = (
            ["#6f8d3a", "#87a443", "#a7b84c", "#c9c55a", "#e1cf63"]
            if not back
            else ["#4f6b31", "#5f7c36", "#718d3c", "#869c44"]
        )
        clusters = [
            (150, 160),
            (300, 110),
            (440, 140),
            (560, 90),
            (240, 280),
            (90, 340),
            (380, 260),
            (620, 200),
            (180, 30),
            (470, 30),
        ]
        for cx, cy in clusters:
            r = rng.uniform(90, 140) if back else rng.uniform(70, 115)
            c.drawPath(
                ellipse(cx + (20 if back else 0), cy, r * 0.9, r * 0.6), fill(palette[0], 0.85)
            )
            for _ in range(70 if back else 85):
                a = rng.uniform(0, math.tau)
                d = math.sqrt(rng.uniform(0, 1)) * r
                x, y = cx + math.cos(a) * d, cy + math.sin(a) * d * 0.7
                light = clamp01((r - (x - cx + y - cy) * 0.7) / (2 * r))
                tone = palette[min(len(palette) - 1, int(light * len(palette)))]
                _leaf(
                    c,
                    x,
                    y,
                    rng.uniform(26, 40),
                    rng.uniform(9, 14),
                    rng.uniform(0, 360),
                    tone,
                    0.95,
                    vein=shade_of(tone, 0.4),
                )

    def _bougainvillea(self, c: skia.Canvas, index: int) -> None:
        rng = random.Random(40 + index)
        c.drawPath(
            PathBuilder().m(130, 0).q(100 + index * 20, 160, 120, 330).done(), stroke("#4c5e2c", 5)
        )
        for _ in range(55):
            x = 130 + rng.gauss(0, 50)
            y = rng.uniform(0, 330) ** 1.0
            x += (y / 330) * rng.uniform(-30, 30)
            _leaf(
                c,
                x,
                y,
                rng.uniform(18, 26),
                rng.uniform(7, 10),
                rng.uniform(0, 360),
                rng.choice(["#4f7a35", "#5f8b3a", "#3f6a2e"]),
                0.95,
            )
        for _ in range(120):
            x = 130 + rng.gauss(0, 55)
            y = rng.uniform(0, 300) * rng.uniform(0.5, 1.0)
            r = rng.uniform(6, 11)
            tone = rng.choice(["#d63f8c", "#e8579f", "#b8286c", "#f07ab7"])
            for k in range(3):
                a = k * math.tau / 3 + rng.uniform(0, 1)
                c.drawPath(
                    circle(x + math.cos(a) * r * 0.55, y + math.sin(a) * r * 0.55, r * 0.7),
                    fill(tone),
                )
            c.drawPath(circle(x, y, 2.2), fill("#fbe7a0"))

    def _plant_leaf(self, c: skia.Canvas, index: int) -> None:
        rng = random.Random(70 + index)
        tone = ["#2f5a2b", "#3b6b30", "#2a4f27", "#467a35", "#33612d"][index]
        length = rng.uniform(380, 520)
        width = rng.uniform(110, 150)
        c.save()
        c.translate(280, 690)
        c.rotate(-60 + index * 26)
        leaf = (
            PathBuilder()
            .m(0, 0)
            .q(width, -length * 0.45, 0, -length)
            .q(-width, -length * 0.45, 0, 0)
            .z()
        )
        c.drawPath(leaf, fill(tone))
        c.drawPath(
            leaf,
            fill(
                "#000000",
                shader=linear(
                    (-width, -length), (width, 0), ["#c8d26a", tone, "#16301a"], [0.5, 1, 1]
                ),
            ),
        )
        c.drawPath(
            PathBuilder().m(0, -10).q(10, -length * 0.5, 0, -length * 0.95).done(),
            stroke("#a9c46a", 5, 0.6),
        )
        c.restore()

    def _dapple_sprite(self) -> skia.Image:
        def draw(c):
            rng = random.Random(3)
            for _ in range(70):
                x = rng.uniform(0, W + 300)
                y = rng.uniform(0, H + 300)
                r = rng.uniform(20, 70)
                c.drawPath(
                    ellipse(x, y, r * rng.uniform(1.0, 1.8), r),
                    fill(
                        "#ffe2a8",
                        1,
                        shader=radial((x, y), r * 1.6, ["#fff0c4", "#ffd99a"], [0.9, 0.0]),
                    ),
                )

        return _sprite(W + 300, H + 300, draw)

    # ------------------------------------------------------------ per frame

    def draw_back(self, c: skia.Canvas, t: float, cam: Camera) -> None:
        sampling = skia.SamplingOptions(skia.FilterMode.kLinear)
        for image, depth in ((self.far, 0.3), (self.mid, 0.6)):
            c.save()
            cam.apply(c, depth)
            c.drawImage(image, -MARGIN, -MARGIN, sampling)
            if image is self.mid:
                self._flowers(c, t)
            c.restore()
        # Moving leaf light across wall and street.
        c.save()
        cam.apply(c, 0.6)
        paint = skia.Paint()
        paint.setAlphaf(0.16)
        c.drawImage(
            self.dapples,
            -150 + math.sin(t * 0.45) * 22,
            -150 + math.cos(t * 0.37) * 14,
            sampling,
            paint,
        )
        c.restore()
        c.save()
        cam.apply(c, 0.72)
        if self.has_car:
            c.drawImage(self.car_image, -MARGIN, -MARGIN, sampling)
            self._car_glint(c, t)
        c.restore()
        c.save()
        cam.apply(c, 0.85)
        c.drawImage(self.trunk, -MARGIN, -MARGIN, sampling)
        self._tree(c, t, self.tree_back, 0.7, 0.0)
        self._tree(c, t, self.tree_front, 1.0, 1.3)
        c.restore()

    def _flowers(self, c, t):
        sampling = skia.SamplingOptions(skia.FilterMode.kLinear)
        for i, (x, y) in enumerate(((560, 150), (690, 160), (790, 140))):
            c.save()
            c.translate(x + 130, y)
            c.rotate(math.sin(t * 0.9 + i * 1.7) * 1.6 + math.sin(t * 2.1 + i) * 0.4)
            c.drawImage(self.flowers[i], -130, 0, sampling)
            c.restore()

    def _tree(self, c, t, sprite, amount, phase):
        sampling = skia.SamplingOptions(skia.FilterMode.kLinear)
        c.save()
        c.translate(60, 330)
        c.rotate((math.sin(t * 0.7 + phase) * 0.9 + math.sin(t * 1.9 + phase) * 0.3) * amount)
        c.drawImage(sprite, -120, -480, sampling)
        c.restore()

    def _car_glint(self, c, t):
        c.save()
        c.translate(545, 1200)
        c.scale(CAR_SCALE, CAR_SCALE)
        c.translate(-545, -1200)
        position = 240 + ((t * 70) % 900)
        glint = (
            PathBuilder()
            .m(position, 1040)
            .l(position + 60, 1040)
            .l(position + 10, 1180)
            .l(position - 50, 1180)
            .z()
        )
        body = (
            PathBuilder()
            .m(212, 1176)
            .l(206, 1112)
            .q(210, 1052, 262, 1038)
            .l(312, 1022)
            .q(352, 948, 404, 914)
            .q(500, 892, 598, 900)
            .q(650, 912, 716, 1006)
            .q(800, 1018, 846, 1042)
            .q(872, 1058, 872, 1104)
            .l(872, 1168)
            .l(232, 1192)
            .z()
        )
        with clipped(c, body):
            c.drawPath(glint, fill("#ffffff", 0.16, blur=10))
        c.restore()

    def draw_front(self, c: skia.Canvas, t: float, cam: Camera) -> None:
        sampling = skia.SamplingOptions(skia.FilterMode.kLinear)
        # Floating dust in the sun.
        c.save()
        cam.apply(c, 1.0)
        for x, y, r, phase, speed in self.motes:
            px = (x + math.sin(t * 0.6 + phase) * 30 + t * 6) % W
            py = (y - t * speed) % (H * 0.8)
            twinkle = 0.35 + 0.35 * math.sin(t * 2.3 + phase * 3)
            c.drawPath(circle(px, py, r), fill("#fff1c8", twinkle, blur=1.5))
        # Two leaves drifting down across the shot.
        for start, x0, drift in ((1.2, 160, 1.0), (7.5, 820, -1.0)):
            age = t - start
            if 0 <= age <= 6:
                px = x0 + drift * age * 55 + math.sin(age * 2.2) * 45
                py = -40 + age * 210
                _leaf(c, px, py, 30, 11, age * 140 * drift, "#e1a63e", 0.95, vein="#9c6a22")
        c.restore()
        # Out-of-focus foreground plant.
        c.save()
        cam.apply(c, 1.25)
        for i, image in enumerate(self.plant):
            c.save()
            c.translate(-40, H + 90)
            c.rotate(math.sin(t * 1.1 + i * 0.9) * 1.8)
            c.drawImage(image, -280, -690, sampling)
            c.restore()
        c.restore()

    def _grade_overlay(self) -> skia.Image:
        def draw(c):
            # Sun bloom from the upper left, a warm wash and a soft vignette.
            c.drawRect(
                skia.Rect.MakeWH(W, H),
                skia.Paint(
                    Shader=radial(
                        (170, 110),
                        950,
                        ["#fff2cc", "#ffd38a", "#ffb060"],
                        [0.42, 0.16, 0.0],
                        [0, 0.45, 1],
                    )
                ),
            )
            c.drawRect(skia.Rect.MakeWH(W, H), fill("#ff9c40", 0.05))
            c.drawRect(
                skia.Rect.MakeWH(W, H),
                skia.Paint(
                    Shader=radial(
                        (W / 2, H * 0.48),
                        H * 0.78,
                        ["#2a140a", "#2a140a", "#2a140a"],
                        [0.0, 0.0, 0.5],
                        [0, 0.55, 1],
                    )
                ),
            )

        return _sprite(W, H, draw)

    def grade(self, c: skia.Canvas, t: float) -> None:
        c.drawImage(self.grade_image, 0, 0)


def clamp01(value: float) -> float:
    return 0.0 if value < 0 else 1.0 if value > 1 else value


def offset_path(path: skia.Path, dx: float, dy: float) -> skia.Path:
    moved = skia.Path(path)
    moved.offset(dx, dy)
    return moved


def offset_scale(path: skia.Path, scale: float, cx: float, cy: float) -> skia.Path:
    moved = skia.Path(path)
    matrix = skia.Matrix()
    matrix.setScale(scale, scale, cx, cy)
    moved.transform(matrix)
    return moved


__all__ = ["Camera", "StreetSet", "W", "H", "mix"]
