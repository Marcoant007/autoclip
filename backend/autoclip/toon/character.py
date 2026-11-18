"""Articulated characters drawn from code.

Skeleton (torso space, origin at the base of the neck, +y down)::

    hips pivot (0, 600) ── torso lean
      ├─ neck top (0, -70) ── head tilt ── head centre (0, -145 from neck top)
      ├─ left shoulder  ── upper arm ── elbow ── forearm ── wrist ── hand
      └─ right shoulder ── upper arm ── elbow ── forearm ── wrist ── hand

Arms are solved with two-bone IK toward a hand target, so acting keys say
"hand goes here" instead of listing joint angles. The head is a 2.5D
construction: the cranium is a ball, the face mask and features rotate around a
vertical axis, so a head turn reveals the back of the skull and hides the far
ear instead of sliding a flat face sideways.

"Left" and "right" always mean screen sides, not the character's own sides.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field, fields

import skia

from .draw import (
    INK,
    PathBuilder,
    capsule,
    cel,
    circle,
    clamp,
    clipped,
    col,
    difference,
    ellipse,
    fill,
    lerp,
    linear,
    mix,
    offset,
    radial,
    rrect,
    shade_of,
    smooth,
    stroke,
    union,
)

# ---------------------------------------------------------------- data


@dataclass(frozen=True)
class Look:
    """Visual identity of a rig. Colours are hex strings."""

    name: str
    skin: str
    hair: str
    hair_light: str
    hair_style: str  # "short_curls" | "big_curls"
    outfit: str  # "overshirt" | "tee"
    top: str
    trousers: str
    undershirt: str = "#e9dcc4"
    iris: str = "#4a2a18"
    lips: str | None = None
    belt: str | None = None
    glasses: str | None = None
    earrings: str | None = None
    wristband: str | None = None
    bag: str | None = None
    necklace: str | None = None
    stubble: bool = False
    lashes: bool = False
    #: -1 chest faces screen-left, +1 faces screen-right.
    body_turn: float = 0.0
    shoulder: float = 142.0
    upper_arm: float = 212.0
    forearm: float = 196.0
    jaw_width: float = 1.0
    head_scale: float = 1.1
    seed: int = 1


@dataclass
class Pose:
    """Every animatable channel of a rig. Floats interpolate; strings switch."""

    lean: float = 0.0  # degrees around the hips
    shift: float = 0.0  # hip shift in px
    bob: float = 0.0  # vertical body offset in px
    shrug: float = 0.0  # 0..1 shoulders up
    breath: float = 0.0  # -1..1
    head_turn: float = 0.0  # -1..1 yaw (positive looks screen-right)
    head_tilt: float = 0.0  # degrees roll
    head_nod: float = 0.0  # -1..1 pitch, positive = chin down
    gaze_x: float = 0.0
    gaze_y: float = 0.0
    lid: float = 0.92
    blink: float = 0.0
    squint: float = 0.0
    brow_l: float = 0.0
    brow_r: float = 0.0
    brow_in: float = 0.0  # +1 worried (inner corners up), -1 frown
    smile: float = 0.0
    jaw: float = 0.0
    wide: float = 0.0
    round: float = 0.0
    mouth_asym: float = 0.0
    lhx: float = -150.0
    lhy: float = 420.0
    lrot: float = 0.0
    lhand: str = "relax"
    lbend: float = 1.0
    rhx: float = 150.0
    rhy: float = 420.0
    rrot: float = 0.0
    rhand: str = "relax"
    rbend: float = -1.0
    phone_face: float = 0.0  # 0 back of phone toward camera, 1 screen
    hair_dx: float = 0.0  # secondary motion: lag of the hair behind the head
    hair_dy: float = 0.0
    wind: float = 0.0
    time: float = 0.0


FLOAT_FIELDS = [f.name for f in fields(Pose) if f.type in ("float", float)]
TEXT_FIELDS = [f.name for f in fields(Pose) if f.type in ("str", str)]


def blend_pose(a: Pose, b: Pose, t: float) -> Pose:
    out = Pose()
    for name in FLOAT_FIELDS:
        setattr(out, name, lerp(getattr(a, name), getattr(b, name), t))
    for name in TEXT_FIELDS:
        setattr(out, name, getattr(b if t >= 0.5 else a, name))
    return out


# ---------------------------------------------------------------- geometry helpers

FACE_R = 108.0


def ik(shoulder, target, l1, l2, bend):
    """Two-bone IK. ``bend`` in [-1, 1] picks the elbow side; values in between
    swing the elbow continuously (the arm rotating toward/away from camera)
    instead of flipping it, keeping both bone lengths."""
    sx, sy = shoulder
    tx, ty = target
    dx, dy = tx - sx, ty - sy
    distance = math.hypot(dx, dy)
    distance = clamp(distance, abs(l1 - l2) + 2, l1 + l2 - 0.5)
    base = math.atan2(dy, dx)
    cos_a = clamp((l1 * l1 + distance * distance - l2 * l2) / (2 * l1 * distance), -1, 1)
    angle = base + clamp(bend, -1, 1) * math.acos(cos_a)
    elbow = (sx + l1 * math.cos(angle), sy + l1 * math.sin(angle))
    ex, ey = tx - elbow[0], ty - elbow[1]
    length = math.hypot(ex, ey) or 1
    wrist = (elbow[0] + ex / length * l2, elbow[1] + ey / length * l2)
    return elbow, wrist


def _ribbon(points, widths) -> skia.Path:
    """A filled stroke whose width varies along a polyline (brows, strands)."""
    left, right = [], []
    count = len(points)
    for i, (x, y) in enumerate(points):
        a = points[max(0, i - 1)]
        b = points[min(count - 1, i + 1)]
        dx, dy = b[0] - a[0], b[1] - a[1]
        length = math.hypot(dx, dy) or 1
        nx, ny = -dy / length, dx / length
        w = widths[i] / 2
        left.append((x + nx * w, y + ny * w))
        right.append((x - nx * w, y - ny * w))
    outline = left + right[::-1]
    return smooth(outline, closed=True, tension=0.8)


def _quad_points(p0, p1, p2, n=9):
    out = []
    for i in range(n):
        t = i / (n - 1)
        out.append(
            (
                (1 - t) ** 2 * p0[0] + 2 * (1 - t) * t * p1[0] + t * t * p2[0],
                (1 - t) ** 2 * p0[1] + 2 * (1 - t) * t * p1[1] + t * t * p2[1],
            )
        )
    return out


# ---------------------------------------------------------------- character


@dataclass
class Character:
    look: Look
    _curls: dict = field(default_factory=dict)
    _legs_path: skia.Path | None = None
    _above_shoulders: skia.Path | None = None
    _panels: dict = field(default_factory=dict)

    def __post_init__(self):
        rng = random.Random(self.look.seed)
        if self.look.hair_style == "big_curls":
            back = []
            # Volume mass behind the head and shoulders, denser near the edge so
            # the silhouette reads as many coils instead of one blob.
            for _ in range(70):
                a = rng.uniform(0, math.tau)
                r = math.sqrt(rng.uniform(0.15, 1.0))
                x = math.cos(a) * r * 178
                y = 30 + math.sin(a) * r * 238
                if y < -205:
                    continue
                back.append((x, y, rng.uniform(27, 42), rng.uniform(0, math.tau)))
            frame = []
            for i in range(14):  # crown curls along the hairline
                a = math.radians(lerp(196, 344, i / 13))
                frame.append(
                    (
                        math.cos(a) * 108 + rng.uniform(-5, 5),
                        -62 + math.sin(a) * 100 + rng.uniform(-5, 5),
                        rng.uniform(21, 28),
                        rng.uniform(0, math.tau),
                    )
                )
            for side in (-1, 1):  # curtains that frame the face
                for j in range(9):
                    y = -24 + j * 31 + rng.uniform(-5, 5)
                    x = side * (120 + 14 * math.sin(j * 0.9) + j * 4 + rng.uniform(-5, 5))
                    frame.append((x, y, rng.uniform(21, 30), rng.uniform(0, math.tau)))
            self._curls = {"back": back, "front": frame}
        else:
            top = []
            for i in range(15):  # ring along the skull
                a = math.radians(lerp(195, 345, i / 14))
                top.append(
                    (
                        math.cos(a) * 104,
                        -50 + math.sin(a) * 104,
                        rng.uniform(21, 26),
                        rng.uniform(0, math.tau),
                    )
                )
            for i in range(11):  # volume on top
                a = math.radians(lerp(210, 330, i / 10))
                top.append(
                    (
                        math.cos(a) * 92,
                        -78 + math.sin(a) * 112,
                        rng.uniform(25, 31),
                        rng.uniform(0, math.tau),
                    )
                )
            for _ in range(9):
                top.append(
                    (
                        rng.uniform(-60, 60),
                        rng.uniform(-150, -100),
                        rng.uniform(24, 30),
                        rng.uniform(0, math.tau),
                    )
                )
            for i in range(6):  # loose curls on the forehead
                top.append(
                    (
                        lerp(-62, 56, i / 5) + rng.uniform(-6, 6),
                        -70 + rng.uniform(-6, 8),
                        rng.uniform(13, 18),
                        rng.uniform(0, math.tau),
                    )
                )
            self._curls = {"top": top}

    # ------------------------------------------------------------ entry

    def draw(self, c: skia.Canvas, pose: Pose, x: float, y: float, scale: float) -> None:
        look = self.look
        c.save()
        c.translate(x + pose.shift * scale, y + pose.bob * scale)
        c.scale(scale, scale)
        c.rotate(pose.lean, 0, 520)
        shrug = pose.shrug * 16 + pose.breath * 2.2
        sy = 40 - shrug
        s = look.shoulder

        head_matrix = skia.Matrix()
        head_matrix.preTranslate(0, -70 - shrug * 0.35)
        head_matrix.preRotate(pose.head_tilt)
        head_matrix.preTranslate(0, -128)
        head_matrix.preScale(look.head_scale, look.head_scale, 0, 120)

        if look.hair_style == "big_curls":
            c.save()
            c.concat(head_matrix)
            self._hair_back(c, pose)
            c.restore()
        self._legs(c, pose)
        self._neck(c, pose, shrug)
        self._torso(c, pose, shrug)

        # Sleeves must not poke above the shoulder line of the torso.
        above = PathBuilder().m(-600, -900).l(600, -900).l(600, sy + 60)
        above.l(s + 30, sy + 26).q(s - 30, sy - 22, 50, -16).l(-50, -16).q(
            -s + 30, sy - 22, -s - 30, sy + 26
        )
        above.l(-600, sy + 60)
        self._above_shoulders = above.z()

        arms = []
        for side in (-1, 1):
            joint = (side * (s - 20), sy + 22)
            hy = pose.lhy if side < 0 else pose.rhy
            shape = pose.lhand if side < 0 else pose.rhand
            arms.append((hy < -40 or shape == "chin", side, joint, self._solve(pose, side, joint)))
        for over, side, joint, solved in arms:
            if not over:
                self._arm(c, pose, side, joint, solved)
        c.save()
        c.concat(head_matrix)
        self._head(c, pose)
        c.restore()
        for over, side, joint, solved in arms:
            if over:
                self._arm(c, pose, side, joint, solved)
        c.restore()

    # ------------------------------------------------------------ body

    def _legs(self, c, pose):
        look = self.look
        k = 26 * look.body_turn
        waist = 430 if look.outfit == "overshirt" else 392
        hip = 124 if look.outfit == "overshirt" else 136
        crotch = 640 if look.outfit == "overshirt" else 610
        legs = (
            PathBuilder()
            .m(-hip + 6, waist)
            .c(-hip - 8, 560, -hip - 2, 800, -hip + 8, 1500)
            .l(k - 10, 1500)
            .q(k, 900, k, crotch)
            .q(k, 900, k + 10, 1500)
            .l(hip - 8, 1500)
            .c(hip + 2, 800, hip + 8, 560, hip - 6, waist)
            .z()
        )
        self._legs_path = legs
        cel(c, legs, look.trousers, shadow=0.38, depth=34, rim=0.25)
        fold = stroke(shade_of(look.trousers, 0.45), 3, 0.6)
        c.drawPath(PathBuilder().m(k, crotch + 20).q(k - 4, 980, k - 2, 1500).done(), fold)
        for side in (-1, 1):
            c.drawPath(
                PathBuilder()
                .m(side * (hip - 20), waist + 24)
                .q(side * (hip - 50), waist + 80, side * (hip - 30), waist + 150)
                .done(),
                fold,
            )
            c.drawPath(
                PathBuilder()
                .m(side * 52 + k, crotch + 60)
                .q(side * 62 + k, crotch + 160, side * 54 + k, crotch + 280)
                .done(),
                stroke(shade_of(look.trousers, 0.4), 2.5, 0.45),
            )
        if look.belt:
            belt = (
                PathBuilder()
                .m(-hip + 4, waist - 24)
                .q(k, waist - 12, hip - 4, waist - 24)
                .l(hip - 2, waist + 8)
                .q(k, waist + 20, -hip + 2, waist + 8)
                .z()
            )
            cel(c, belt, look.belt, shadow=0.35, depth=10, width=2.5)
            buckle = rrect(k - 24, waist - 24, k + 24, waist + 18, 7)
            c.drawPath(buckle, stroke("#c99a3c", 6))
            c.drawPath(buckle, stroke("#7a5a1c", 1.5, 0.8))
            c.drawPath(
                PathBuilder().m(k - 30, waist - 4).l(k + 6, waist - 4).done(), stroke("#c99a3c", 4)
            )
            for side in (-1, 1):
                c.drawPath(
                    rrect(side * 88 + k - 6, waist - 26, side * 88 + k + 6, waist + 14, 3),
                    stroke(shade_of(look.belt, 0.4), 2.5),
                )

    def _neck(self, c, pose, shrug):
        look = self.look
        top = -70 - shrug * 0.35
        neck = (
            PathBuilder()
            .m(-42, top - 34)
            .l(42, top - 34)
            .q(40, -30, 54, 8)
            .l(-54, 8)
            .q(-40, -30, -42, top - 34)
            .z()
        )
        cel(c, neck, look.skin, shadow=0.3, depth=16, width=2.5)
        with clipped(c, neck):
            c.drawPath(ellipse(10, top + 6, 70, 36), fill(shade_of(look.skin, 0.42), 0.85, blur=6))

    def _torso(self, c, pose, shrug):
        look = self.look
        k = 34 * look.body_turn
        s = look.shoulder
        sy = 40 - shrug
        if look.outfit == "overshirt":
            hem = 575
            tee = (
                PathBuilder()
                .m(-60, -8)
                .q(k, 6, 60, -8)
                .l(72 + k, 260)
                .l(66 + k, hem + 10)
                .l(-66 + k, hem + 10)
                .l(-72 + k, 260)
                .z()
            )
            cel(c, tee, look.undershirt, shadow=0.22, depth=26, width=2.5)
            c.drawPath(
                PathBuilder().m(-54 + k * 0.3, -6).q(k, 46, 54 + k * 0.3, -6).done(),
                stroke(shade_of(look.undershirt, 0.35), 6),
            )
            c.drawPath(
                PathBuilder().m(-48 + k * 0.3, -1).q(k, 38, 48 + k * 0.3, -1).done(),
                stroke(INK, 2.2, 0.7),
            )
            for side in (-1, 1):
                edge = side * 48 + k
                panel = (
                    PathBuilder()
                    .m(side * 54, -14)
                    .q(side * (s - 40), sy - 30, side * (s + 8), sy - 2)
                    .q(side * (s + 16), sy + 50, side * (s + 4), sy + 140)
                    .q(side * (s - 8), 360, side * (s + 6), hem)
                    .q(side * 70 + k, hem + 16, edge, hem + 10)
                    .q(edge - side * 6, 330, edge + side * 4, 140)
                    .l(side * 52 + k * 0.4, 30)
                    .z()
                )
                tone = look.top if side < 0 else mix(look.top, "#2e3b26", 0.12)
                self._panels[side] = (panel, tone)
                cel(c, panel, tone, shadow=0.34, depth=30, rim=0.35 if side < 0 else 0.0)
                fold = stroke(shade_of(look.top, 0.5), 3, 0.55)
                c.drawPath(
                    PathBuilder()
                    .m(side * (s - 24), sy + 110)
                    .q(side * (s - 42), 260, side * (s - 28), 400)
                    .done(),
                    fold,
                )
                c.drawPath(
                    PathBuilder()
                    .m(edge + side * 22, 430)
                    .q(edge + side * 36, 500, edge + side * 26, hem)
                    .done(),
                    fold,
                )
                collar = (
                    PathBuilder()
                    .m(side * 54, -16)
                    .q(side * 76, -26, side * 100, -4)
                    .q(side * 86, 40, edge + side * 14, 118)
                    .q(side * 54, 56, side * 54, -16)
                    .z()
                )
                cel(c, collar, mix(look.top, "#56683f", 0.25), shadow=0.25, depth=10, width=2.6)
            px = -s + 54
            pocket = rrect(px, 128, px + 62, 212, 7)
            cel(c, pocket, look.top, shadow=0.22, depth=8, width=2.2)
            flap = (
                PathBuilder()
                .m(px - 3, 124)
                .l(px + 65, 124)
                .l(px + 63, 158)
                .q(px + 31, 168, px - 1, 158)
                .z()
            )
            cel(c, flap, mix(look.top, "#56683f", 0.2), shadow=0.25, depth=6, width=2.2)
            c.drawPath(circle(px + 31, 154, 5.5), fill("#d8c7a2"))
            c.drawPath(circle(px + 31, 154, 5.5), stroke(INK, 1.4, 0.8))
            for by in (150, 260, 370, 480):
                bx = 48 + k + 14
                c.drawPath(circle(bx, by, 6), fill("#d8c7a2"))
                c.drawPath(circle(bx, by, 6), stroke(INK, 1.4, 0.8))
            return

        hem = 392
        tee = (
            PathBuilder()
            .m(-56, -12)
            .q(k, 64, 56, -12)
            .q(s - 40, sy - 26, s + 6, sy - 2)
            .q(s + 12, sy + 60, s - 2, sy + 150)
            .q(s - 26, 280, s - 12, hem)
            .q(k, hem + 14, -s + 12, hem)
            .q(-s + 26, 280, -s + 2, sy + 150)
            .q(-s - 12, sy + 60, -s - 6, sy - 2)
            .q(-s + 40, sy - 26, -56, -12)
            .z()
        )
        cel(c, tee, look.top, shadow=0.34, depth=34, rim=0.35)
        c.drawPath(
            PathBuilder().m(-56, -12).q(k, 64, 56, -12).done(), stroke(shade_of(look.top, 0.4), 6)
        )
        fold = stroke(shade_of(look.top, 0.5), 3, 0.5)
        for side in (-1, 1):
            c.drawPath(
                PathBuilder()
                .m(side * (s - 34), 250)
                .q(side * (s - 60), 320, side * (s - 44), hem - 6)
                .done(),
                fold,
            )
        c.drawPath(PathBuilder().m(k - 34, hem - 40).q(k, hem - 14, k + 36, hem - 36).done(), fold)
        if look.necklace:
            c.drawPath(PathBuilder().m(-46, -6).q(k, 96, 46, -6).done(), stroke(look.necklace, 2.2))
            c.drawPath(circle(k * 0.6, 45, 5), fill(look.necklace))
            c.drawPath(circle(k * 0.6 - 1.5, 43.5, 1.8), fill("#fff4cf", 0.9))
        if look.bag:
            route = [(s - 40, sy - 18), (40 + k, 160), (-70 + k, 330), (-s + 4, 470)]
            cel(c, _ribbon(route, [16, 16, 16, 16]), look.bag, shadow=0.3, depth=6, width=2)
            c.drawPath(smooth(route, closed=False), stroke("#e2b07c", 1.2, 0.6))
            self._bag(c)

    def _bag(self, c):
        look = self.look
        s = look.shoulder
        x0, y0 = -s - 70, 460
        bag = rrect(x0, y0, x0 + 112, y0 + 170, 18)
        cel(c, bag, look.bag, shadow=0.35, depth=20, rim=0.3)
        flap = (
            PathBuilder()
            .m(x0 - 2, y0)
            .l(x0 + 114, y0)
            .l(x0 + 112, y0 + 88)
            .q(x0 + 56, y0 + 108, x0, y0 + 88)
            .z()
        )
        cel(c, flap, mix(look.bag, "#5a2c14", 0.2), shadow=0.3, depth=10, width=2.5)
        c.drawPath(rrect(x0 + 46, y0 + 76, x0 + 66, y0 + 100, 3), fill("#c99a3c"))

    # ------------------------------------------------------------ arms & hands

    def _solve(self, pose, side, joint):
        look = self.look
        if side < 0:
            target, rot, shape, bend = (pose.lhx, pose.lhy), pose.lrot, pose.lhand, pose.lbend
        else:
            target, rot, shape, bend = (pose.rhx, pose.rhy), pose.rrot, pose.rhand, pose.rbend
        elbow, wrist = ik(joint, target, look.upper_arm, look.forearm, bend)
        return elbow, wrist, rot, shape

    def _arm(self, c, pose, side, joint, solved):
        look = self.look
        elbow, wrist, rot, shape = solved
        skin = look.skin
        c.save()
        c.clipPath(self._above_shoulders, skia.ClipOp.kDifference, True)
        if look.outfit == "overshirt":
            cel(c, capsule(elbow, wrist, 54, 42), skin, shadow=0.32, depth=12, rim=0.4)
            if look.wristband and side > 0:
                band = capsule(
                    (lerp(elbow[0], wrist[0], 0.8), lerp(elbow[1], wrist[1], 0.8)),
                    (lerp(elbow[0], wrist[0], 0.9), lerp(elbow[1], wrist[1], 0.9)),
                    48,
                    46,
                )
                cel(c, band, look.wristband, shadow=0.2, depth=4, width=2)
            sleeve = capsule(joint, elbow, 82, 66)
            cel(c, sleeve, look.top, shadow=0.34, depth=18, rim=0.3)
            fold = stroke(shade_of(look.top, 0.5), 2.6, 0.55)
            c.drawPath(
                PathBuilder()
                .m(*_along(joint, elbow, 0.55, 28))
                .q(*_along(joint, elbow, 0.65, 4), *_along(joint, elbow, 0.75, 22))
                .done(),
                fold,
            )
            # Rolled cuff: a straight band across the forearm, slightly flared.
            a0, a1 = _along(elbow, wrist, 0.0, 37), _along(elbow, wrist, 0.0, -37)
            b0, b1 = _along(elbow, wrist, 0.2, 33), _along(elbow, wrist, 0.2, -33)
            m0, m1 = _along(elbow, wrist, 0.1, 39), _along(elbow, wrist, 0.1, -39)
            cuff = PathBuilder().m(*a0).q(*m0, *b0).l(*b1).q(*m1, *a1).z()
            cel(c, cuff, mix(look.top, "#c9c59a", 0.18), shadow=0.3, depth=8, width=2.6)
            c.drawPath(
                PathBuilder()
                .m(*_along(elbow, wrist, 0.1, 38))
                .l(*_along(elbow, wrist, 0.1, -38))
                .done(),
                stroke(shade_of(look.top, 0.5), 2.2, 0.6),
            )
        else:
            limb = union([capsule(joint, elbow, 60, 48), capsule(elbow, wrist, 48, 37)])
            cel(c, limb, skin, shadow=0.32, depth=12, rim=0.4)
            mid = (lerp(joint[0], elbow[0], 0.48), lerp(joint[1], elbow[1], 0.48))
            sleeve = capsule((joint[0] - side * 4, joint[1] - 8), mid, 86, 74)
            cel(c, sleeve, look.top, shadow=0.34, depth=16, rim=0.3)
            c.drawPath(
                PathBuilder()
                .m(*_along(joint, mid, 0.96, 35))
                .l(*_along(joint, mid, 0.96, -35))
                .done(),
                stroke(shade_of(look.top, 0.5), 2.4, 0.6),
            )
        c.restore()
        if shape == "pocket":
            # The hand slides into the trouser pocket under the open shirt:
            # re-draw the shirt panel over the wrist so the hand disappears.
            wx, wy = wrist
            panel, tone = self._panels.get(side, (None, None))
            if panel is not None:
                below = (
                    PathBuilder()
                    .m(wx - 120, wy - 34)
                    .l(wx + 90, wy - 50)
                    .l(wx + 90, wy + 500)
                    .l(wx - 120, wy + 500)
                    .z()
                )
                with clipped(c, below):
                    cel(c, panel, tone, shadow=0.34, depth=30, rim=0.35 if side < 0 else 0.0)
                    c.drawPath(
                        PathBuilder()
                        .m(wx - 24, wy - 34)
                        .q(wx - 34, wy + 30, wx - 22, wy + 90)
                        .done(),
                        stroke(shade_of(look.top, 0.5), 3, 0.55),
                    )
                # A shadowed lip where the forearm slips under the shirt.
                lip = PathBuilder().m(wx - 120, wy - 34).l(wx + 90, wy - 50).done()
                with clipped(c, panel):
                    c.drawPath(lip, stroke(shade_of(tone, 0.55), 10, 0.55))
                    c.drawPath(lip, stroke(INK, 2.6, 0.85))
            return
        self._hand(c, wrist, elbow, rot, shape, side, pose)

    def _hand(self, c, wrist, elbow, rot, shape, side, pose):
        look = self.look
        angle = math.degrees(math.atan2(wrist[1] - elbow[1], wrist[0] - elbow[0])) - 90 + rot
        if shape in ("phone", "chin"):
            angle = 180 + rot  # held upright whatever the elbow does
        c.save()
        c.translate(*wrist)
        c.rotate(angle)
        # Hand local frame: +y toward the fingertips; the thumb faces the body
        # centre for a hanging hand.
        thumb = -side
        skin = look.skin
        palm_tone = mix(skin, "#f0bf98", 0.35)
        palm = smooth([(-21, -4), (-25, 28), (-22, 52), (0, 58), (23, 52), (26, 26), (21, -4)])
        if shape == "open":
            parts = [palm]
            for i, (fx, length, spread) in enumerate(
                ((-17, 34, -9), (-6, 41, -3), (6, 40, 2), (17, 32, 8))
            ):
                a = math.radians(spread)
                start = (fx * thumb, 48)
                end = (start[0] + math.sin(a) * length * thumb, start[1] + math.cos(a) * length)
                parts.append(capsule(start, end, 13 - i * 0.4, 11))
            ta = math.radians(58)
            parts.append(
                capsule(
                    (thumb * 18, 14),
                    (thumb * (18 + math.sin(ta) * 36), 14 + math.cos(ta) * 36),
                    16,
                    12,
                )
            )
            hand = union(parts)
            cel(c, hand, palm_tone, shadow=0.28, depth=8, width=2.6)
            for fx in (-11, 0, 11):
                c.drawPath(
                    PathBuilder().m(fx * thumb, 46).l(fx * thumb * 1.1, 62).done(),
                    stroke(INK, 1.6, 0.5),
                )
            c.drawPath(
                PathBuilder().m(-14 * thumb, 22).q(0, 36, 14 * thumb, 30).done(),
                stroke(shade_of(skin, 0.4), 1.8, 0.6),
            )
        elif shape == "point":
            curl = smooth([(-24, 40), (-26, 66), (-8, 76), (12, 70), (20, 52)])
            index = capsule((thumb * 15, 46), (thumb * 18, 100), 13, 11)
            thumb_part = capsule((thumb * 20, 16), (thumb * 24, 50), 15, 12)
            hand = union([palm, curl, index, thumb_part])
            cel(c, hand, skin, shadow=0.3, depth=8, width=2.6)
            for fy in (58, 68):
                c.drawPath(
                    PathBuilder().m(-20 * thumb, fy).l(4 * thumb, fy + 2).done(),
                    stroke(INK, 1.6, 0.55),
                )
        elif shape == "phone":
            hand_back = union([palm, capsule((thumb * 20, 18), (thumb * 30, 70), 15, 12)])
            cel(c, hand_back, skin, shadow=0.3, depth=8, width=2.6)
            self._phone(c, pose.phone_face, thumb)
            for fy in (62, 88, 112):
                tip = capsule((-thumb * 30, fy), (-thumb * 40, fy + 6), 13, 12)
                cel(c, tip, skin, shadow=0.25, depth=4, width=2.2)
            tip = capsule((thumb * 26, 34), (thumb * 36, 74), 15, 12)
            cel(c, tip, skin, shadow=0.25, depth=5, width=2.4)
        elif shape == "chin":
            fist = smooth([(-24, -2), (-28, 32), (-22, 60), (2, 70), (24, 60), (28, 30), (22, -2)])
            index = capsule((thumb * 18, 52), (thumb * 2, 82), 14, 13)
            hand = union([fist, index])
            cel(c, hand, skin, shadow=0.3, depth=8, width=2.6)
            for fy in (44, 58):
                c.drawPath(
                    PathBuilder().m(-22 * thumb, fy).q(-4 * thumb, fy + 6, 10 * thumb, fy).done(),
                    stroke(INK, 1.6, 0.5),
                )
        else:  # relaxed, fingers softly curled
            curl = smooth([(-24, 40), (-25, 70), (-12, 84), (8, 82), (24, 66), (22, 42)])
            thumb_part = capsule((thumb * 20, 14), (thumb * 25, 54), 15, 12)
            hand = union([palm, curl, thumb_part])
            cel(c, hand, skin, shadow=0.3, depth=8, width=2.6)
            for fx in (-10, 3, 15):
                c.drawPath(
                    PathBuilder().m(fx, 62).q(fx + 2, 72, fx, 80).done(), stroke(INK, 1.5, 0.5)
                )
        c.restore()

    def _phone(self, c, face, thumb):
        width = abs(1 - 2 * face)
        show_screen = face >= 0.5
        c.save()
        c.translate(0, 72)
        c.scale(max(0.04, width), 1)
        body = rrect(-36, -72, 36, 72, 11)
        if show_screen:
            c.drawPath(body, fill("#1b1f24"))
            screen = rrect(-31, -66, 31, 66, 8)
            c.drawPath(
                screen, fill("#0f1d24", shader=linear((0, -66), (0, 66), ["#173640", "#0d1a20"]))
            )
            with clipped(c, screen):
                # Generic budget card: bars and a positive balance line. Not a
                # depiction of any real app's interface.
                c.drawPath(rrect(-24, -56, 24, -40, 4), fill("#2b5b55"))
                c.drawPath(rrect(-20, -51, 4, -46, 2), fill("#cfe9df", 0.9))
                for i, (h, tone) in enumerate(
                    ((34, "#e8b04a"), (52, "#e0675a"), (24, "#e8b04a"), (60, "#4cc79a"))
                ):
                    bx = -22 + i * 12
                    c.drawPath(rrect(bx, 18 - h, bx + 8, 18, 2), fill(tone))
                c.drawPath(rrect(-24, 28, 24, 44, 5), fill("#4cc79a", 0.25))
                c.drawPath(rrect(-20, 33, 8, 39, 2), fill("#4cc79a"))
                c.drawPath(ellipse(0, -10, 50, 70), fill("#9ff0d0", 0.08, blur=10))
        else:
            c.drawPath(body, fill("#24382f"))
            c.drawPath(
                rrect(-26 * thumb - 6, -62, -26 * thumb + 18 if thumb < 0 else -2, -30, 7),
                fill("#1a2a23"),
            )
            c.drawPath(circle(-14 * thumb, -54, 5), fill("#0b1210"))
            c.drawPath(circle(-14 * thumb, -40, 5), fill("#0b1210"))
            c.drawPath(PathBuilder().m(-30, 60).l(28, -64).done(), stroke("#ffffff", 3, 0.08))
        c.drawPath(body, stroke(INK, 2.5 / max(0.3, width), 0.9))
        c.restore()

    # ------------------------------------------------------------ head

    def _head(self, c, pose):
        look = self.look
        yaw = pose.head_turn * 0.62
        sy = math.sin(yaw)
        nod = pose.head_nod * 10

        def rx(x, r=FACE_R):
            theta = math.asin(clamp(x / r, -1, 1))
            return r * math.sin(clamp(theta + yaw, -math.pi / 2, math.pi / 2))

        def fs(x, r=FACE_R):
            theta = math.asin(clamp(x / r, -0.99, 0.99))
            return clamp(math.cos(theta + yaw) / max(0.3, math.cos(theta)), 0.3, 1.25)

        cranium = ellipse(-sy * 30, -40, 106, 113)
        jw = look.jaw_width
        jaw_pts = [
            (-103, -40),
            (-104, 16),
            (-98 * jw, 62),
            (-84 * jw, 104),
            (-56 * jw, 136),
            (-24, 152),
            (0, 156),
            (24, 152),
            (56 * jw, 136),
            (84 * jw, 104),
            (98 * jw, 62),
            (104, 16),
            (103, -40),
            (60, -72),
            (0, -82),
            (-60, -72),
        ]
        face = smooth(
            [
                (
                    rx(x, 110 if abs(y) < 140 else 112),
                    y + ((nod * 0.4 + pose.jaw * 10 * (y - 60) / 96) if y > 60 else 0),
                )
                for x, y in jaw_pts
            ]
        )
        head = union([cranium, face])

        # Ears: the one on the far side of a turn tucks behind the face.
        ears_behind, ears_front = [], []
        for side in (-1, 1):
            theta = side * math.pi / 2 * 0.93 + yaw
            visible = abs(theta) < math.pi / 2 + 0.02
            ex = FACE_R * math.sin(clamp(theta, -math.pi / 2, math.pi / 2))
            width = 26 * clamp(math.cos(theta) * 1.4 + 0.45, 0.4, 1)
            entry = (ex + side * 6 * (1 if abs(theta) > 1.2 else 0.3), 30 + nod * 0.3, width, side)
            if not visible:
                continue
            (ears_front if abs(theta) < 1.25 else ears_behind).append(entry)
        for ex, ey, width, side in ears_behind:
            self._ear(c, ex, ey, width, side)
        cel(c, head, look.skin, shadow=0.3, depth=18, rim=0.45, rim_depth=6, width=3.2)

        with clipped(c, head):
            # Cheeks and the hair's shadow on the forehead give the face volume.
            for side in (-1, 1):
                cx = rx(side * 60)
                c.drawPath(
                    ellipse(cx, 66 + nod, 24 * fs(side * 60), 13), fill("#e0705a", 0.22, blur=8)
                )
            if look.stubble:
                beard = (
                    PathBuilder()
                    .m(rx(-96), 70)
                    .q(rx(-80), 140, rx(0, 112), 158)
                    .q(rx(80), 140, rx(96), 70)
                    .q(rx(60), 130, rx(0, 112), 128)
                    .q(rx(-60), 130, rx(-96), 70)
                    .z()
                )
                c.drawPath(beard, fill(look.hair, 0.16, blur=3))
                c.drawPath(
                    ellipse(rx(0, 116), 88 + nod, 34 * fs(0), 8), fill(look.hair, 0.14, blur=3)
                )
        for ex, ey, width, side in ears_front:
            self._ear(c, ex, ey, width, side)
            if look.earrings:
                swing = pose.hair_dx * 0.8
                c.save()
                c.translate(ex, ey + 30)
                c.rotate(-swing)
                c.drawPath(ellipse(side * 2, 18, 12, 17), stroke(look.earrings, 4))
                c.drawPath(ellipse(side * 2, 18, 12, 17), stroke("#fff1c4", 1.2, 0.5))
                c.restore()

        # ---- features
        eye_y = 8 + nod
        for side in (-1, 1):
            ex = rx(side * 44)
            self._eye(c, pose, ex, eye_y, 54 * fs(side * 44), 33, side)
        for side in (-1, 1):
            raise_amount = pose.brow_l if side < 0 else pose.brow_r
            bx = rx(side * 46)
            self._brow(c, bx, -34 + nod, 58 * fs(side * 46), side, raise_amount, pose.brow_in)
        self._nose(c, yaw, rx(0, 128), 60 + nod, rx(0, 112))
        self._mouth(c, pose, rx(0, 114), 104 + nod * 1.1, fs(0))

        if look.glasses:
            self._glasses(c, rx, fs, eye_y, yaw)

        if look.hair_style == "big_curls":
            self._hair_front(c, pose, yaw, rx)
        else:
            self._hair_short(c, pose, yaw, sy)

    def _ear(self, c, ex, ey, width, side):
        look = self.look
        ear = ellipse(ex, ey, width / 2 + 2, 26)
        cel(c, ear, look.skin, shadow=0.35, depth=6, width=2.6)
        c.drawPath(
            PathBuilder()
            .m(ex + side * width * 0.15, ey - 14)
            .q(ex - side * width * 0.25, ey - 4, ex + side * width * 0.05, ey + 14)
            .done(),
            stroke(shade_of(look.skin, 0.5), 2.4, 0.8),
        )

    def _eye(self, c, pose, cx, cy, w, h, side):
        look = self.look
        openness = clamp(pose.lid * (1 - pose.blink))
        inner = (cx - side * w / 2, cy + 3)
        outer = (cx + side * w / 2, cy - 3)
        if openness < 0.14:
            sag = 4 + pose.squint * 4
            line = PathBuilder().m(*inner).q(cx, cy + sag, *outer).done()
            c.drawPath(line, stroke(INK, 4.2))
            if look.lashes:
                for i in range(3):
                    t = 0.55 + i * 0.2
                    px = lerp(inner[0], outer[0], t)
                    py = lerp(inner[1], outer[1], t) + sag * 0.5
                    c.drawPath(
                        PathBuilder().m(px, py).l(px + side * 5, py + 7).done(), stroke(INK, 2.2)
                    )
            return
        top = h * 1.05 * openness
        bottom = h * 0.55 * (1 - 0.65 * pose.squint)
        shape = (
            PathBuilder()
            .m(*inner)
            .c(
                inner[0] + side * w * 0.18,
                cy - top * 1.2,
                outer[0] - side * w * 0.22,
                cy - top * 1.25,
                *outer,
            )
            .c(
                outer[0] - side * w * 0.12,
                cy + bottom * 0.9,
                inner[0] + side * w * 0.2,
                cy + bottom * 1.05,
                *inner,
            )
            .z()
        )
        c.drawPath(shape, fill("#fbf2e6"))
        with clipped(c, shape):
            ix = cx + pose.gaze_x * w * 0.3
            iy = cy + pose.gaze_y * h * 0.34 + 1
            r = h * 0.6
            rw = r * clamp(w / 48, 0.55, 1.1)
            iris = ellipse(ix, iy, rw, r)
            c.drawPath(
                iris,
                fill(
                    look.iris,
                    shader=radial(
                        (ix, iy + r * 0.4),
                        r * 1.3,
                        [mix(look.iris, "#c08a52", 0.45), look.iris, "#1c0f08"],
                        stops=[0, 0.55, 1],
                    ),
                ),
            )
            c.drawPath(ellipse(ix, iy, rw * 0.5, r * 0.52), fill("#120804"))
            c.drawPath(
                ellipse(cx, cy - top * 0.9, w * 0.7, h * 0.45), fill("#4a2618", 0.28, blur=4)
            )
            c.drawPath(circle(ix - rw * 0.32, iy - r * 0.38, r * 0.27), fill("#ffffff", 0.95))
            c.drawPath(circle(ix + rw * 0.34, iy + r * 0.3, r * 0.11), fill("#ffffff", 0.8))
        lid = (
            PathBuilder()
            .m(*inner)
            .c(
                inner[0] + side * w * 0.18,
                cy - top * 1.2,
                outer[0] - side * w * 0.22,
                cy - top * 1.25,
                *outer,
            )
            .done()
        )
        c.drawPath(lid, stroke(INK, 4.6))
        c.drawPath(
            PathBuilder().m(*outer).l(outer[0] + side * 7, outer[1] - 4).done(), stroke(INK, 3.4)
        )
        crease = (
            PathBuilder()
            .m(inner[0] + side * w * 0.1, inner[1] - 8)
            .c(
                inner[0] + side * w * 0.25,
                cy - top * 1.25 - 10,
                outer[0] - side * w * 0.2,
                cy - top * 1.3 - 9,
                outer[0] + side * 2,
                outer[1] - 10,
            )
            .done()
        )
        c.drawPath(crease, stroke(shade_of(look.skin, 0.55), 2, 0.55))
        low = (
            PathBuilder()
            .m(outer[0] - side * 4, outer[1] + 3)
            .c(
                outer[0] - side * w * 0.15,
                cy + bottom * 0.9,
                inner[0] + side * w * 0.2,
                cy + bottom * 1.05,
                inner[0] + side * 3,
                inner[1],
            )
            .done()
        )
        c.drawPath(low, stroke(shade_of(look.skin, 0.55), 1.8, 0.6))
        if look.lashes:
            for i in range(3):
                t = 0.62 + i * 0.16
                px = lerp(inner[0], outer[0], t)
                py = cy - top * (1.0 - (t - 0.6) * 1.2) * 0.95
                c.drawPath(
                    PathBuilder().m(px, py).l(px + side * 7, py - 6).done(), stroke(INK, 2.4)
                )

    def _brow(self, c, cx, cy, w, side, raise_amount, inner_up):
        look = self.look
        inner = (cx - side * w * 0.48, cy - raise_amount * 12 - inner_up * 9 + 3)
        mid = (cx - side * w * 0.05, cy - raise_amount * 14 - 7 - inner_up * 3)
        outer = (cx + side * w * 0.5, cy - raise_amount * 10 + 1 + inner_up * 4)
        pts = _quad_points(inner, mid, outer, 7)
        widths = [9.5, 9.5, 8.5, 7.5, 6.2, 4.8, 3.2]
        c.drawPath(_ribbon(pts, widths), fill(look.hair))

    def _nose(self, c, yaw, tip_x, tip_y, base_x):
        look = self.look
        side = 1 if yaw >= 0 else -1
        amount = abs(math.sin(yaw))
        shadow = ellipse(tip_x - side * 6, tip_y + 8, 18, 9)
        c.drawPath(shadow, fill(shade_of(look.skin, 0.4), 0.55, blur=4))
        bridge = (
            PathBuilder()
            .m(base_x + side * 6, 12)
            .q(tip_x + side * (6 + 8 * amount), tip_y - 18, tip_x + side * 6, tip_y + 2)
            .q(tip_x + side * 2, tip_y + 10, tip_x - side * 6, tip_y + 9)
            .done()
        )
        c.drawPath(bridge, stroke(shade_of(look.skin, 0.6), 2.6, 0.55 + 0.35 * amount))
        c.drawPath(
            PathBuilder()
            .m(tip_x - side * 18, tip_y + 2)
            .q(tip_x - side * 22, tip_y + 9, tip_x - side * 12, tip_y + 10)
            .done(),
            stroke(INK, 2.4, 0.7),
        )
        c.drawPath(circle(tip_x - side * 2, tip_y - 4, 4), fill("#ffe2c0", 0.35, blur=2))

    def _mouth(self, c, pose, cx, cy, fs):
        look = self.look
        smile = pose.smile
        w = 54 * (1 + 0.26 * pose.wide - 0.4 * pose.round + 0.14 * max(0.0, smile)) * fs
        lift = smile * 9
        left = (cx - w / 2, cy - lift - pose.mouth_asym * 5)
        right = (cx + w / 2, cy - lift + pose.mouth_asym * 5)
        opening = 36 * pose.jaw * (1 + 0.2 * pose.round)
        if opening < 2.5:
            line = PathBuilder().m(*left).q(cx, cy + smile * 8 + 1, *right).done()
            if look.lips:
                lower = (
                    PathBuilder()
                    .m(left[0] + 4, left[1] + 1)
                    .q(cx, cy + 15 + smile * 4, right[0] - 4, right[1] + 1)
                    .q(cx, cy + smile * 8 + 2, left[0] + 4, left[1] + 1)
                    .z()
                )
                c.drawPath(lower, fill(look.lips, 0.85))
                upper = (
                    PathBuilder()
                    .m(*left)
                    .q(cx - w * 0.2, cy - 9, cx, cy - 5)
                    .q(cx + w * 0.2, cy - 9, *right)
                    .q(cx, cy + smile * 8 + 1, *left)
                    .z()
                )
                c.drawPath(upper, fill(shade_of(look.lips, 0.2), 0.85))
            c.drawPath(line, stroke(INK, 3.6))
            if smile > 0.3:
                for corner, s in ((left, -1), (right, 1)):
                    c.drawPath(
                        PathBuilder()
                        .m(corner[0] + s * 1, corner[1] - 5)
                        .q(corner[0] + s * 6, corner[1], corner[0] + s * 2, corner[1] + 5)
                        .done(),
                        stroke(INK, 2.2, 0.7),
                    )
            c.drawPath(
                PathBuilder()
                .m(cx - 10, cy + 16 + smile * 4)
                .q(cx, cy + 20 + smile * 4, cx + 10, cy + 16 + smile * 4)
                .done(),
                stroke(shade_of(look.skin, 0.45), 2.4, 0.5),
            )
            return
        top_mid = cy - opening * 0.18 + smile * 3
        bottom_mid = cy + opening * (1.05 + 0.1 * pose.round) - lift * 0.3
        bulge = w * (0.25 + 0.25 * pose.round)
        shape = (
            PathBuilder()
            .m(*left)
            .c(left[0] + bulge * 0.4, top_mid - 4, right[0] - bulge * 0.4, top_mid - 4, *right)
            .c(right[0] - bulge * 0.1, bottom_mid, left[0] + bulge * 0.1, bottom_mid, *left)
            .z()
        )
        if look.lips:
            c.drawPath(offset(shape, 0, 0), stroke(look.lips, 7))
        c.drawPath(shape, fill("#4b1519"))
        with clipped(c, shape):
            teeth_h = min(12.0, opening * 0.4)
            c.drawPath(
                rrect(cx - w * 0.42, top_mid - 8, cx + w * 0.42, top_mid + teeth_h, 4),
                fill("#fbf3ea"),
            )
            if pose.jaw > 0.35:
                c.drawPath(ellipse(cx, bottom_mid - 2, w * 0.3, opening * 0.32), fill("#c4555c"))
        c.drawPath(shape, stroke(INK, 3.2))
        c.drawPath(
            PathBuilder()
            .m(cx - 12, bottom_mid + 12)
            .q(cx, bottom_mid + 16, cx + 12, bottom_mid + 12)
            .done(),
            stroke(shade_of(look.skin, 0.45), 2.4, 0.5),
        )

    def _glasses(self, c, rx, fs, eye_y, yaw):
        look = self.look
        frame = look.glasses
        lenses = []
        for side in (-1, 1):
            ex = rx(side * 44)
            w = 40 * fs(side * 44)
            lenses.append((ex, w))
            lens = ellipse(ex, eye_y - 2, w, 36)
            c.drawPath(lens, fill("#ffffff", 0.06))
            with clipped(c, lens):
                c.drawPath(
                    PathBuilder().m(ex - w, eye_y + 30).l(ex + w * 0.2, eye_y - 40).done(),
                    stroke("#ffffff", 8, 0.12),
                )
            c.drawPath(lens, stroke(frame, 4.2))
            c.drawPath(lens, stroke("#6e4d1b", 1.2, 0.6))
        (lx, lw), (rx_, rw) = lenses
        c.drawPath(
            PathBuilder()
            .m(lx + lw, eye_y - 10)
            .q((lx + rx_) / 2, eye_y - 20, rx_ - rw, eye_y - 10)
            .done(),
            stroke(frame, 3.6),
        )
        side = -1 if yaw > 0 else 1
        ex, w = lenses[0] if side < 0 else lenses[1]
        temple_end = rx(side * 104)
        c.drawPath(
            PathBuilder().m(ex + side * w, eye_y - 12).l(temple_end, eye_y - 4).done(),
            stroke(frame, 3.4),
        )

    # ------------------------------------------------------------ hair

    def _hair_short(self, c, pose, yaw, sy):
        look = self.look
        cx0 = -sy * 30

        def rx(x, r=FACE_R):
            theta = math.asin(clamp(x / r, -1, 1))
            return r * math.sin(clamp(theta + yaw, -math.pi / 2, math.pi / 2))

        cap = ellipse(cx0, -52, 109, 112)
        below = smooth(
            [
                (-260, 10),
                (rx(-104), -18),
                (rx(-82), -46),
                (rx(-40), -66),
                (rx(0), -72),
                (rx(40), -66),
                (rx(82), -46),
                (rx(104), -18),
                (260, 10),
                (260, 400),
                (-260, 400),
            ]
        )
        base = difference(cap, below)
        bounce = pose.hair_dy * 0.4
        placed = []
        for x, y, r, phase in self._curls["top"]:
            front = clamp((y + 120) / 60)
            px = lerp(cx0 + x * math.cos(yaw), rx(x) if abs(x) < FACE_R else cx0 + x, front)
            lag = pose.hair_dx * 0.35 * clamp((-y - 40) / 120)
            placed.append((px + lag, y + bounce, r, phase))
        hair = union([base, *[circle(x, y, r) for x, y, r, _ in placed]])
        c.save()
        c.clipPath(ellipse(cx0, -40, 106, 113), doAntiAlias=True)
        c.drawPath(offset(hair, 5, 13), fill(shade_of(look.skin, 0.5), 0.55))
        c.restore()
        cel(
            c,
            hair,
            look.hair,
            shadow=0.3,
            depth=10,
            rim=0.6,
            rim_colour="#d08a50",
            rim_depth=6,
            width=3,
        )
        with clipped(c, hair):
            for x, y, r, phase in placed:
                arc = skia.Path()
                box = skia.Rect.MakeLTRB(x - r * 0.62, y - r * 0.62, x + r * 0.62, y + r * 0.62)
                arc.addArc(box, math.degrees(phase), 210)
                c.drawPath(arc, stroke(look.hair_light, 3, 0.8))
                c.drawPath(
                    circle(x + r * 0.25, y + r * 0.3, r * 0.32), fill(shade_of(look.hair, 0.4), 0.6)
                )
        # Short faded sides around the visible ear.
        for side in (-1, 1):
            theta = side * math.pi / 2 * 0.86 + yaw
            if abs(theta) > math.pi / 2:
                continue
            x = FACE_R * math.sin(theta)
            c.drawPath(
                PathBuilder()
                .m(x - side * 2, -60)
                .q(x + side * 14, -20, x + side * 2, 12)
                .q(x - side * 14, -14, x - side * 2, -60)
                .z(),
                fill(look.hair, 0.55),
            )

    def _hair_back(self, c, pose):
        look = self.look
        yaw = pose.head_turn * 0.62
        cx0 = -math.sin(yaw) * 40
        pieces = []
        for x, y, r, phase in self._curls["back"]:
            k = clamp((y + 120) / 360)
            dx = (
                pose.hair_dx * k * 1.4
                + math.sin(pose.time * 1.6 + phase) * 3 * k
                + pose.wind * 8 * k
            )
            dy = pose.hair_dy * k * 0.6
            pieces.append((cx0 + x + dx, y + dy, r, phase))
        mass = union([circle(x, y, r) for x, y, r, _ in pieces])
        cel(
            c,
            mass,
            look.hair,
            shadow=0.3,
            depth=26,
            rim=0.5,
            rim_colour="#c98450",
            rim_depth=8,
            width=3,
        )
        with clipped(c, mass):
            for x, y, r, phase in pieces:
                arc = skia.Path()
                arc.addArc(
                    skia.Rect.MakeLTRB(x - r * 0.6, y - r * 0.6, x + r * 0.6, y + r * 0.6),
                    math.degrees(phase),
                    220,
                )
                c.drawPath(arc, stroke(look.hair_light, 3.2, 0.55))
                c.drawPath(
                    circle(x + r * 0.2, y + r * 0.35, r * 0.3),
                    fill(shade_of(look.hair, 0.3), 0.5, blur=3),
                )

    def _hair_front(self, c, pose, yaw, rx):
        look = self.look
        pieces = []
        for x, y, r, phase in self._curls["front"]:
            k = clamp((y + 40) / 260)
            dx = pose.hair_dx * k + math.sin(pose.time * 1.9 + phase) * 2.2 * k + pose.wind * 6 * k
            base_x = rx(x) if abs(x) < FACE_R else x - math.sin(yaw) * 26
            # Curtains on the side the face turns toward slide over the cheek.
            pieces.append((base_x + dx, y + pose.hair_dy * k * 0.5, r, phase))
        cranium_cx = -math.sin(yaw) * 30
        hairline = smooth(
            [
                (-260, 20),
                (rx(-106), -10),
                (rx(-80), -50),
                (rx(-36), -70),
                (rx(0), -74),
                (rx(36), -70),
                (rx(80), -50),
                (rx(106), -10),
                (260, 20),
                (260, 400),
                (-260, 400),
            ]
        )
        cap = difference(ellipse(cranium_cx, -46, 112, 118), hairline)
        mass = union([cap, *[circle(x, y, r) for x, y, r, _ in pieces]])
        c.save()
        c.clipPath(ellipse(-math.sin(yaw) * 30, -40, 106, 200), doAntiAlias=True)
        c.drawPath(offset(mass, 3, 10), fill(shade_of(look.skin, 0.5), 0.55, blur=6))
        c.restore()
        cel(
            c,
            mass,
            look.hair,
            shadow=0.3,
            depth=14,
            rim=0.55,
            rim_colour="#d28d52",
            rim_depth=7,
            width=3,
        )
        with clipped(c, mass):
            for x, y, r, phase in pieces:
                arc = skia.Path()
                arc.addArc(
                    skia.Rect.MakeLTRB(x - r * 0.58, y - r * 0.58, x + r * 0.58, y + r * 0.58),
                    math.degrees(phase),
                    220,
                )
                c.drawPath(arc, stroke(look.hair_light, 3, 0.65))


def _along(a, b, t, normal):
    x = lerp(a[0], b[0], t)
    y = lerp(a[1], b[1], t)
    dx, dy = b[0] - a[0], b[1] - a[1]
    length = math.hypot(dx, dy) or 1
    return x - dy / length * normal, y + dx / length * normal


__all__ = ["Character", "Look", "Pose", "blend_pose", "col"]
