"""A deterministic vector-style puppet renderer with per-frame acting.

Characters are rigs: feet, knees, arms, hands, eyes, brows, hair and mouths have
their own motion. The static set is cached separately, so camera movement is
not the animation source. No image/video generation service is required.
"""

from __future__ import annotations

import math
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from ..animation import ActorTrack, CharacterDesign, Pose, ShotPlan
from . import ffmpeg
from .transcript import Word

WORLD = (720, 1280)
INK = "#2d303a"
GROUND = 1090


def ease(value: float) -> float:
    value = min(1.0, max(0.0, value))
    return value * value * (3 - 2 * value)


def mix(a: float, b: float, amount: float) -> float:
    return a + (b - a) * amount


@dataclass
class ActingState:
    x: float
    pose_a: Pose
    pose_b: Pose
    blend: float
    expression: str
    walking: float


def acting_state(track: ActorTrack, progress: float) -> ActingState:
    progress = min(1.0, max(0.0, progress))
    previous, following = track.keys[-2:]
    for left, right in zip(track.keys, track.keys[1:], strict=False):
        if progress <= right.at:
            previous, following = left, right
            break
    local = (progress - previous.at) / (following.at - previous.at)
    amount = ease(local)
    # Velocity falls to zero at each mark. This makes feet settle before an
    # acting beat instead of walking in place after the character has stopped.
    velocity = abs(following.x - previous.x) * 6 * max(0.0, local * (1 - local))
    return ActingState(
        x=mix(previous.x, following.x, amount),
        pose_a=previous.pose,
        pose_b=following.pose,
        blend=amount,
        expression=previous.expression if local < 0.55 else following.expression,
        walking=min(1.0, velocity * 8),
    )


class Canvas:
    """Logical coordinates keep rig proportions independent of output size."""

    def __init__(self, image: Image.Image, *, zoom: float = 1, focus_x: float = 0.5):
        self.image = image
        self.draw = ImageDraw.Draw(image)
        self.sx, self.sy = image.width / WORLD[0], image.height / WORLD[1]
        self.zoom = zoom
        self.cx, self.cy = focus_x * WORLD[0], 820

    def point(self, point):
        x, y = point
        return (
            (self.cx + (x - self.cx) * self.zoom) * self.sx,
            (self.cy + (y - self.cy) * self.zoom) * self.sy,
        )

    def polygon(self, points, fill, outline=INK, width=3):
        points = [self.point(point) for point in points]
        self.draw.polygon(points, fill=fill)
        if outline and width:
            self.draw.line(
                [*points, points[0]],
                fill=outline,
                width=max(1, round(width * self.sx * self.zoom)),
                joint="curve",
            )

    def ellipse(self, box, fill, outline=None, width=2):
        x0, y0, x1, y1 = box
        self.draw.ellipse(
            (*self.point((x0, y0)), *self.point((x1, y1))),
            fill=fill,
            outline=outline,
            width=max(1, round(width * self.sx * self.zoom)),
        )

    def line(self, points, fill=INK, width=4):
        mapped = [self.point(point) for point in points]
        actual = max(1, round(width * self.sx * self.zoom))
        self.draw.line(mapped, fill=fill, width=actual, joint="curve")
        radius = actual / 2
        for x, y in (mapped[0], mapped[-1]):
            self.draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=fill)

    def rounded_rect(self, box, fill, radius=10, outline=None, width=2):
        x0, y0, x1, y1 = box
        self.draw.rounded_rectangle(
            (*self.point((x0, y0)), *self.point((x1, y1))),
            radius=max(1, round(radius * self.sx * self.zoom)),
            fill=fill,
            outline=outline,
            width=max(1, round(width * self.sx * self.zoom)),
        )


def _sky(size, period="day"):
    colours = {
        "day": ((153, 207, 217), (245, 230, 197)),
        "sunset": ((230, 154, 139), (255, 226, 175)),
        "night": ((39, 54, 85), (104, 103, 141)),
    }
    top = np.array(colours[period][0], dtype=np.float32)
    bottom = np.array(colours[period][1], dtype=np.float32)
    blend = np.linspace(0, 1, size[1], dtype=np.float32)[:, None, None]
    rows = (top[None, None, :] * (1 - blend) + bottom[None, None, :] * blend).astype(np.uint8)
    return Image.fromarray(np.repeat(rows, size[0], axis=1))


def build_set(shot: ShotPlan, size: tuple[int, int]) -> Image.Image:
    """Cache the set at render resolution; only rigs and props move per frame."""
    image = _sky(size, shot.time_of_day)
    c = Canvas(image)
    if shot.setting == "street":
        c.ellipse((525, 95, 665, 235), "#fff0bf")
        for x, y, w, h, colour in [
            (-50, 250, 205, 620, "#c7c6ad"),
            (145, 160, 210, 710, "#e7d9b6"),
            (350, 300, 150, 570, "#c8d7cb"),
            (500, 190, 260, 680, "#e9e0c3"),
        ]:
            c.polygon([(x, y), (x + w, y), (x + w, y + h), (x, y + h)], colour, outline=None)
            c.polygon(
                [(x + w - 25, y), (x + w, y), (x + w, y + h), (x + w - 25, y + h)],
                "#b7b49c",
                outline=None,
            )
            for wx in range(int(x + 30), int(x + w - 25), 59):
                for wy in range(int(y + 48), int(y + h - 40), 100):
                    c.rounded_rect((wx, wy, wx + 27, wy + 55), "#92b3b6", radius=3, outline=None)
        c.polygon([(0, 860), (720, 860), (720, 1280), (0, 1280)], "#8b9a87", outline=None)
        c.polygon([(0, 1045), (720, 1025), (720, 1280), (0, 1280)], "#67727a", outline=None)
        c.line([(0, 1052), (720, 1032)], "#ccd1ba", 12)
        for x in range(-100, 900, 300):
            c.polygon(
                [(x, 1208), (x + 145, 1200), (x + 185, 1222), (x + 25, 1230)],
                "#eddec1",
                outline=None,
            )
        _tree(c, 40, 850, 0.85)
    elif shot.setting == "room":
        c.polygon([(0, 0), (720, 0), (720, 1060), (0, 1060)], "#f1d9b6", outline=None)
        c.polygon([(0, 1000), (720, 1000), (720, 1280), (0, 1280)], "#bf8b6b", outline=None)
        for y in range(1050, 1281, 85):
            c.line([(0, y), (720, y)], "#a8735b", 2)
        c.rounded_rect((44, 110, 380, 575), "#fff1d4", radius=16, outline="#966957", width=8)
        c.rounded_rect((64, 130, 360, 555), "#a2d4d8", radius=8, outline=None)
        c.ellipse((240, 180, 312, 252), "#fff3be")
        for x, height in [(70, 120), (135, 210), (220, 155), (290, 250)]:
            c.polygon(
                [(x, 555 - height), (x + 65, 555 - height), (x + 65, 555), (x, 555)],
                "#82a6a7",
                outline=None,
            )
        c.line([(212, 132), (212, 555)], "#fff1d4", 12)
        c.line([(65, 342), (359, 342)], "#fff1d4", 12)
        c.rounded_rect((470, 170, 675, 440), "#b97859", radius=8, outline=None)
        c.rounded_rect((482, 182, 663, 428), "#fff0cb", radius=5, outline=None)
        c.ellipse((520, 230, 620, 330), "#6eaaa0")
        c.polygon([(500, 380), (625, 310), (650, 394)], "#dc9775", outline=None)
        c.line([(446, 600), (700, 600)], "#936149", 18)
        for x, h, colour in [(468, 110, "#537a91"), (500, 145, "#b97165"), (540, 95, "#e1bd66")]:
            c.rounded_rect((x, 600 - h, x + 23, 597), colour, radius=3, outline=None)
        _plant(c, 640, 1010, 1.1)
        c.ellipse((60, 1025, 620, 1160), "#d3b18d")
    else:
        c.polygon([(0, 410), (720, 410), (720, 1030), (0, 1030)], "#ddbe91", outline=None)
        for y in range(445, 1030, 85):
            c.line([(0, y), (720, y)], "#c3a175", 2)
        c.rounded_rect((245, 390, 465, 1030), "#526d71", radius=110, outline="#bf996d", width=15)
        c.polygon([(0, 1000), (720, 1000), (720, 1280), (0, 1280)], "#d5b28b", outline=None)
        for x in (20, 550):
            c.rounded_rect(
                (x, 230, x + 145, 1035), "#e9cda3", radius=20, outline="#b89367", width=4
            )
            c.rounded_rect((x - 10, 250, x + 155, 300), "#d1ad7e", radius=10, outline=None)
            for dx in (25, 65, 105):
                c.line([(x + dx, 325), (x + dx, 980)], "#d4b68c", 5)
            c.rounded_rect((x - 12, 990, x + 157, 1045), "#c2a075", radius=7, outline=None)
        _plant(c, 600, 1060, 0.9)
        c.line([(0, 1155), (720, 1155)], "#c4a180", 2)
    return image


def _tree(c, x, ground, scale):
    c.polygon(
        [
            (x - 11 * scale, ground),
            (x + 11 * scale, ground),
            (x + 3 * scale, ground - 260 * scale),
            (x - 8 * scale, ground - 260 * scale),
        ],
        "#8b7059",
        outline=None,
    )
    for dx, dy, r in [(-45, -270, 65), (35, -300, 70), (-10, -350, 66), (75, -250, 62)]:
        c.ellipse(
            (
                x + (dx - r) * scale,
                ground + (dy - r) * scale,
                x + (dx + r) * scale,
                ground + (dy + r) * scale,
            ),
            "#6c9e79",
        )


def _plant(c, x, ground, scale):
    c.polygon(
        [
            (x - 35 * scale, ground - 75 * scale),
            (x + 35 * scale, ground - 75 * scale),
            (x + 25 * scale, ground),
            (x - 25 * scale, ground),
        ],
        "#bc795e",
        outline="#956146",
    )
    for dx, dy in [(-55, -190), (45, -210), (-25, -250), (65, -150), (-70, -135)]:
        c.line(
            [(x, ground - 80 * scale), (x + dx * scale, ground + dy * scale)], "#48765c", 5 * scale
        )
        c.ellipse(
            (
                x + (dx - 22) * scale,
                ground + (dy - 38) * scale,
                x + (dx + 22) * scale,
                ground + (dy + 8) * scale,
            ),
            "#679776",
        )


def _car(c, x, ground, scale, time):
    def p(px, py):
        return (x + (px - 270) * scale, ground + py * scale)

    def poly(points, colour, outline=INK, width=3):
        c.polygon([p(*point) for point in points], colour, outline, width)

    def ellipse(box, fill, outline=None, width=2):
        c.ellipse((*p(box[0], box[1]), *p(box[2], box[3])), fill, outline, width)

    ellipse((0, -35, 540, 35), "#465259")
    for wx in (100, 440):
        ellipse((wx - 54, -93, wx + 54, 15), "#323640")
        ellipse((wx - 36, -75, wx + 36, -3), "#b5c0c7", INK, 3)
        ellipse((wx - 15, -54, wx + 15, -24), "#65727d")
        for angle in np.linspace(0, math.tau, 6, endpoint=False):
            c.line(
                [p(wx, -39), p(wx + 28 * math.cos(angle), -39 + 28 * math.sin(angle))], "#e2e4e1", 3
            )
    poly(
        [
            (0, -94),
            (25, -175),
            (135, -210),
            (196, -282),
            (355, -275),
            (440, -205),
            (535, -175),
            (550, -83),
            (498, -60),
            (490, -104),
            (467, -127),
            (420, -127),
            (397, -102),
            (390, -60),
            (155, -60),
            (147, -108),
            (126, -129),
            (78, -128),
            (58, -103),
            (50, -65),
        ],
        "#d56f56",
    )
    poly([(150, -211), (206, -267), (345, -260), (414, -208)], "#384653")
    poly([(180, -213), (212, -252), (270, -250), (270, -213)], "#78969f", None)
    poly([(287, -250), (337, -247), (390, -213), (287, -213)], "#607d8c", None)
    c.line([p(280, -203), p(279, -82)], "#a45146", 3)
    c.line([p(40, -163), p(510, -147)], "#ec9571", 5)
    c.rounded_rect((*p(315, -180), *p(353, -167)), "#913f3b", radius=3)
    poly([(17, -152), (50, -162), (39, -132), (9, -126)], "#ffedb1", None)
    poly([(516, -157), (537, -149), (538, -124), (511, -130)], "#a34b45", None)
    # A moving reflection makes the background prop feel lit, not flat clip art.
    reflection = 220 + 8 * math.sin(time * 0.7)
    c.line([p(reflection, -244), p(reflection + 23, -217)], "#9fb7b7", 3)


def _prop(c, prop, time):
    x, scale = prop.x * 720, prop.scale
    if prop.kind == "car":
        _car(c, x, 980, scale, time)
    elif prop.kind == "plant":
        _plant(c, x, GROUND, scale)
    elif prop.kind == "desk":
        c.rounded_rect(
            (x - 125 * scale, 1000, x + 125 * scale, 1024), "#a76e50", radius=5, outline=INK
        )
        for dx in (-100, 100):
            c.line([(x + dx * scale, 1020), (x + dx * scale, 1170)], "#715b50", 12)
        c.polygon([(x - 65, 990), (x + 22, 990), (x + 45, 926), (x - 43, 926)], "#5e7382", INK, 3)
        c.polygon([(x - 30, 940), (x + 28, 940), (x + 9, 980), (x - 48, 980)], "#a8d1ca", None)
    elif prop.kind == "chest":
        c.rounded_rect(
            (x - 65 * scale, 945, x + 65 * scale, 1045), "#a56f46", radius=15, outline=INK
        )
        c.line([(x - 65 * scale, 985), (x + 65 * scale, 985)], "#d8af69", 9)
        c.rounded_rect((x - 9, 978, x + 9, 1006), "#e0bb70", radius=3, outline=INK)
    elif prop.kind == "coins":
        for i in range(4):
            y = 1050 - i * 12 * scale + 3 * math.sin(time * 2 + i)
            c.ellipse((x - 35 * scale, y - 10, x + 35 * scale, y + 10), "#e9b653", "#a77c3d", 2)


def _pose_points(pose: Pose, side: int):
    # Shoulder-relative elbow and wrist positions, mirrored by side below.
    variants = {
        "rest": ((72, -128), (65, -65)),
        "present": ((92, -160), (140, -210)),
        "point": ((105, -215), (175, -240)),
        "think": ((88, -150), (38, -292)),
        "celebrate": ((105, -265), (115, -340)),
        "shrug": ((98, -175), (145, -214)),
    }
    if side < 0 and pose in ("present", "point", "think"):
        return variants["rest"]
    return variants[pose]


def _character(
    c: Canvas,
    design: CharacterDesign,
    track: ActorTrack,
    time: float,
    progress: float,
    mouth: float,
    speaking: bool,
    index: int,
):
    state = acting_state(track, progress)
    scale = track.scale
    x, ground = state.x * 720, GROUND
    walk_cycle = time * 9
    bounce = -abs(math.sin(walk_cycle)) * 9 * state.walking
    breath = 2 * math.sin(time * 2.1 + index)
    sway = 3 * math.sin(time * 1.5 + index) * (1 - state.walking)

    def p(px, py):
        return (x + (px + sway) * scale, ground + (py + bounce) * scale)

    def ellipse(box, fill, outline=None, width=2):
        c.ellipse((*p(box[0], box[1]), *p(box[2], box[3])), fill, outline, width)

    def poly(points, colour, outline=INK, width=3):
        c.polygon([p(*point) for point in points], colour, outline, width)

    def line(points, colour=INK, width=4):
        c.line([p(*point) for point in points], colour, width * scale)

    c.ellipse((x - 77 * scale, ground - 12, x + 77 * scale, ground + 15), "#707b7250")
    # Legs have separate hips, knees and feet. A moving actor must articulate
    # the knees and alternate planted feet, rather than slide across the set.
    for side in (-1, 1):
        phase = walk_cycle + (math.pi if side < 0 else 0)
        stride = math.sin(phase) * 37 * state.walking
        lift = max(0, math.cos(phase)) * 21 * state.walking
        hip = (side * 24, -145)
        knee = (side * 26 + stride * 0.45, -80 - lift * 0.3)
        foot = (side * 28 + stride, -12 - lift)
        line([hip, knee, foot], INK, 27)
        line([hip, knee, foot], design.trousers, 20)
        poly(
            [
                (foot[0] - 17, foot[1] - 2),
                (foot[0] + 30, foot[1] - 2),
                (foot[0] + 36, foot[1] + 10),
                (foot[0] - 18, foot[1] + 10),
            ],
            "#f3e9cf",
            INK,
            3,
        )
    # Long hair is behind the neck/body; a small lag follows head movement.
    hair_lag = math.sin(time * 2.3 + index) * 3
    if design.hair == "long":
        ellipse((-89 + hair_lag, -438, 91 + hair_lag, -217), design.hair_colour, INK, 3)
    ellipse((-25, -333, -1, -271), design.skin, INK, 3)
    if design.outfit == "robe":
        poly([(-50, -290), (50, -290), (77, -70), (-77, -70)], design.shirt)
        line([(-56, -172), (57, -172)], "#bba16a", 11)
        line([(10, -275), (-15, -90)], "#ffffff35", 3)
    else:
        poly(
            [(-48, -287), (48, -287), (64, -245), (53, -143), (-55, -143), (-64, -245)],
            design.shirt,
        )
        line([(-17, -285), (0, -265), (18, -285)], "#ffffff70", 3)
        line([(-5, -261), (-5, -222)], "#28484e", 3)
        line([(10, -261), (10, -234)], "#28484e", 3)
        c.rounded_rect(
            (*p(-34, -197), *p(34, -164)), design.shirt, radius=8, outline="#28484e", width=2
        )
    # Head, ears and squash/nod are independent from body movement.
    nod = (3 * math.sin(time * 3.5) if speaking else math.sin(time * 1.8 + index) * 1.8) + breath
    hy = -366 + nod
    ellipse((-85, hy - 12, -65, hy + 24), design.skin, INK, 3)
    ellipse((65, hy - 12, 85, hy + 24), design.skin, INK, 3)
    ellipse((-76, hy - 88, 76, hy + 80), design.skin, INK, 3.5)
    # A light patch adds volume without turning the character into a photo.
    ellipse((-54, hy + 27, -26, hy + 42), "#e8b298")
    ellipse((30, hy + 27, 58, hy + 42), "#e8b298")
    if design.hair == "short":
        poly(
            [
                (-75, hy - 32),
                (-77, hy - 83),
                (-54, hy - 106),
                (-34, hy - 99),
                (-6, hy - 115),
                (13, hy - 101),
                (52, hy - 104),
                (78, hy - 71),
                (73, hy - 22),
                (52, hy - 62),
                (19, hy - 68),
                (-19, hy - 55),
                (-56, hy - 61),
            ],
            design.hair_colour,
        )
    elif design.hair == "curly":
        for a in np.linspace(math.pi * 0.9, math.pi * 2.1, 10):
            hx = 72 * math.cos(a) + hair_lag
            yy = hy - 20 + 77 * math.sin(a)
            ellipse((hx - 23, yy - 24, hx + 23, yy + 24), design.hair_colour, INK, 2)
    elif design.hair == "long":
        poly(
            [
                (-78, hy - 15),
                (-76, hy - 80),
                (-40, hy - 110),
                (25, hy - 111),
                (73, hy - 78),
                (80, hy - 10),
                (50, hy - 55),
                (14, hy - 73),
                (-20, hy - 41),
                (-62, hy - 22),
            ],
            design.hair_colour,
        )
    direction = -1 if track.facing == "left" else 1
    gaze = direction * 5
    blink_phase = (time + index * 0.91) % 3.6
    blink = 1 - max(0.0, 1 - abs(blink_phase - 3.25) / 0.095)
    eye_height = 26 * max(0.06, blink)
    if state.expression == "surprised":
        eye_height *= 1.14
    for ex in (-32, 32):
        if blink < 0.15:
            line([(ex - 19, hy - 7), (ex, hy - 3), (ex + 18, hy - 7)], INK, 3)
        else:
            ellipse(
                (ex - 23, hy - 10 - eye_height, ex + 23, hy - 10 + eye_height), "#fff8e8", INK, 3
            )
            pupil_height = min(15, eye_height * 0.8)
            ellipse(
                (ex - 11 + gaze, hy - 10 - pupil_height, ex + 10 + gaze, hy - 10 + pupil_height),
                "#65514e",
            )
            ellipse(
                (
                    ex - 6 + gaze,
                    hy - 10 - pupil_height * 0.8,
                    ex + 6 + gaze,
                    hy - 10 + pupil_height * 0.8,
                ),
                INK,
            )
            if blink > 0.6:
                ellipse((ex - 7 + gaze, hy - 23, ex - 1 + gaze, hy - 17), "#ffffff")
    if design.glasses:
        for ex in (-32, 32):
            c.rounded_rect(
                (*p(ex - 30, hy - 45), *p(ex + 30, hy + 24)), None, radius=13, outline=INK, width=4
            )
        line([(-3, hy - 15), (3, hy - 15)], INK, 3)
    eyebrow_y = hy - 54
    for ex in (-32, 32):
        lift = -11 if state.expression in ("surprised", "worried") else 0
        slant = (7 if ex < 0 else -7) if state.expression == "worried" else (-4 if ex < 0 else 4)
        line(
            [(ex - 19, eyebrow_y + lift + slant), (ex + 18, eyebrow_y + lift - slant)],
            design.hair_colour,
            5,
        )
    line([(3, hy + 2), (8, hy + 18), (-1, hy + 20)], "#9e6c55", 2)
    my = hy + 45
    if speaking and mouth > 0.08:
        jaw = 8 + min(1, mouth) * 20
        ellipse((-23, my - jaw * 0.45, 23, my + jaw * 0.7), "#592e36", INK, 2)
        c.rounded_rect((*p(-16, my - jaw * 0.35), *p(16, my - jaw * 0.35 + 6)), "#fff8e8", radius=2)
        if mouth > 0.45:
            ellipse((-12, my + 4, 13, my + jaw * 0.5), "#dc7c80")
    elif state.expression in ("happy", "confident"):
        line([(-22, my - 5), (-9, my + 4), (7, my + 6), (22, my - 5)], INK, 3)
    elif state.expression == "surprised":
        ellipse((-10, my - 10, 11, my + 13), "#592e36", INK, 2)
    elif state.expression == "worried":
        line([(-19, my + 7), (0, my), (19, my + 7)], INK, 3)
    else:
        line([(-17, my), (0, my + 3), (17, my)], INK, 3)
    # Arms are drawn after the face so a thinking hand can reach the chin.
    for side in (-1, 1):
        ea, wa = _pose_points(state.pose_a, side * direction)
        eb, wb = _pose_points(state.pose_b, side * direction)
        elbow = (side * mix(ea[0], eb[0], state.blend), mix(ea[1], eb[1], state.blend))
        wrist = (side * mix(wa[0], wb[0], state.blend), mix(wa[1], wb[1], state.blend))
        swing = math.sin(walk_cycle + (math.pi if side < 0 else 0)) * 23 * state.walking
        gesture = math.sin(time * 4.2) * 3 if speaking else 0
        wrist = (wrist[0] + swing, wrist[1] + gesture)
        shoulder = (side * 48, -268)
        line([shoulder, elbow, wrist], INK, 22)
        line([shoulder, elbow, wrist], design.skin, 15)
        line(
            [shoulder, (mix(shoulder[0], elbow[0], 0.55), mix(shoulder[1], elbow[1], 0.55))],
            design.shirt,
            24,
        )
        ellipse((wrist[0] - 12, wrist[1] - 12, wrist[0] + 12, wrist[1] + 12), design.skin, INK, 2)
        if side == direction and track.holding != "none":
            if track.holding == "phone":
                c.rounded_rect(
                    (*p(wrist[0] - 22, wrist[1] - 66), *p(wrist[0] + 20, wrist[1] + 8)),
                    "#2e3b4a",
                    radius=7,
                    outline=INK,
                )
                c.rounded_rect(
                    (*p(wrist[0] - 16, wrist[1] - 56), *p(wrist[0] + 14, wrist[1] - 1)),
                    "#afe0c7",
                    radius=3,
                )
                line(
                    [
                        (wrist[0] - 8, wrist[1] - 15),
                        (wrist[0], wrist[1] - 30),
                        (wrist[0] + 8, wrist[1] - 37),
                    ],
                    "#37776c",
                    3,
                )
            else:
                poly(
                    [
                        (wrist[0] - 26, wrist[1] - 55),
                        (wrist[0] + 26, wrist[1] - 55),
                        (wrist[0] + 26, wrist[1] + 8),
                        (wrist[0] - 26, wrist[1] + 8),
                    ],
                    "#aa6a51",
                    INK,
                    2,
                )


def mouth_envelope(audio: Path, duration: float, fps: int) -> np.ndarray:
    """Use actual audio energy to animate the speaking rig's mouth."""
    command = [
        ffmpeg.ffmpeg_path(),
        "-v",
        "error",
        "-i",
        str(audio.resolve()),
        "-f",
        "f32le",
        "-ac",
        "1",
        "-ar",
        "8000",
        "pipe:1",
    ]
    result = subprocess.run(command, capture_output=True, check=False)
    if result.returncode:
        raise ffmpeg.FFmpegError(
            "Could not analyse speech for the cartoon mouth.",
            command=command,
            stderr=result.stderr.decode("utf-8", errors="replace"),
        )
    samples = np.frombuffer(result.stdout, dtype="<f4")
    count = max(1, math.ceil(duration * fps))
    energy = np.zeros(count, dtype=np.float32)
    for index in range(count):
        block = samples[round(index * 8000 / fps) : round((index + 1) * 8000 / fps)]
        if len(block):
            energy[index] = np.sqrt(np.mean(block * block))
    peak = float(np.percentile(energy, 90))
    if peak > 0.0001:
        energy = np.clip(energy / peak, 0, 1)
    return energy


class CartoonScene:
    def __init__(
        self,
        shot: ShotPlan,
        cast: list[CharacterDesign],
        size: tuple[int, int],
        duration: float,
        *,
        supersampling: int = 2,
    ):
        self.shot, self.cast, self.size, self.duration = (
            shot,
            {actor.id: actor for actor in cast},
            size,
            duration,
        )
        self.internal = (size[0] * supersampling, size[1] * supersampling)
        self.background = build_set(shot, self.internal)
        if any(track.actor_id not in self.cast for track in shot.actors):
            raise ValueError("Shot references a character that is not in the cast.")

    def frame(self, time: float, mouth: float = 0) -> Image.Image:
        progress = min(1, max(0, time / self.duration))
        image = self.background.copy()
        c = Canvas(image)
        for prop in self.shot.props:
            _prop(c, prop, time)
        for index, track in enumerate(self.shot.actors):
            _character(
                c,
                self.cast[track.actor_id],
                track,
                time,
                progress,
                mouth,
                track.actor_id == self.shot.speaker,
                index,
            )
        zoom = mix(self.shot.zoom_start, self.shot.zoom_end, ease(progress))
        if zoom != 1:
            # Camera framing is applied after independent rig animation.
            width, height = self.internal
            focus_x = width * self.shot.focus_x
            focus_y = height * self.shot.focus_y
            crop_w, crop_h = width / zoom, height / zoom
            left = min(width - crop_w, max(0, focus_x - crop_w / 2))
            top = min(height - crop_h, max(0, focus_y - crop_h / 2))
            image = image.transform(
                self.internal,
                Image.Transform.EXTENT,
                (left, top, left + crop_w, top + crop_h),
                Image.Resampling.BICUBIC,
            )
        return image.resize(self.size, Image.Resampling.LANCZOS)


def render_cartoon(
    shot: ShotPlan,
    cast: list[CharacterDesign],
    audio: Path,
    words: list[Word],
    output: Path,
    size: tuple[int, int],
    duration: float,
    encoder: list[str],
    cancelled: Callable[[], bool],
    on_progress: Callable[[float], None],
    fps: int = 30,
) -> None:
    """Stream frames directly to FFmpeg; keep partial output out of resume caches."""
    output.parent.mkdir(parents=True, exist_ok=True)
    scene = CartoonScene(shot, cast, size, duration)
    envelope = mouth_envelope(audio, duration, fps)
    scene.frame(min(0.5, duration / 2), 0.25).save(output.parent / "visual.png")
    temporary = output.with_name("scene.partial.mp4")
    command = [
        ffmpeg.ffmpeg_path(),
        "-hide_banner",
        "-y",
        "-nostdin",
        "-loglevel",
        "error",
        "-f",
        "rawvideo",
        "-pixel_format",
        "rgb24",
        "-video_size",
        f"{size[0]}x{size[1]}",
        "-framerate",
        str(fps),
        "-i",
        "pipe:0",
        "-i",
        str(audio.resolve()),
        "-vf",
        "ass=filename=captions.ass:fontsdir=fonts,format=yuv420p",
        "-af",
        "apad",
        "-t",
        f"{duration:.6f}",
        *encoder,
        "-c:a",
        "aac",
        "-ar",
        "48000",
        "-ac",
        "2",
        "-b:a",
        "192k",
        "-movflags",
        "+faststart",
        str(temporary.resolve()),
    ]
    with (output.parent / "encode.log").open("w", encoding="utf-8") as errors:
        process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=errors,
            cwd=output.parent,
        )
        try:
            assert process.stdin is not None
            for index, energy in enumerate(envelope):
                if cancelled():
                    raise ffmpeg.Cancelled("Produção cancelada.")
                time = index / fps
                speaking = any(word.start <= time < word.end for word in words)
                frame = scene.frame(time, float(energy) if speaking else 0)
                process.stdin.write(frame.tobytes())
                if index % 5 == 0:
                    on_progress((index + 1) / len(envelope))
            process.stdin.close()
            while True:
                if cancelled():
                    raise ffmpeg.Cancelled("Produção cancelada.")
                try:
                    process.wait(timeout=0.2)
                    break
                except subprocess.TimeoutExpired:
                    continue
            if process.returncode:
                errors.flush()
                raise ffmpeg.FFmpegError(
                    "Cartoon encoding failed.",
                    command=command,
                    stderr=(output.parent / "encode.log").read_text(encoding="utf-8"),
                )
        except BaseException:
            process.kill()
            process.wait()
            raise
        finally:
            if process.stdin is not None and not process.stdin.closed:
                process.stdin.close()
    temporary.replace(output)
    on_progress(1)
