"""Small Skia helpers: colours, paints, path building and cel shading."""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from functools import lru_cache

import skia

Point = tuple[float, float]


# ---------------------------------------------------------------- numbers


def clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return low if value < low else high if value > high else value


def lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def smoothstep(t: float) -> float:
    t = clamp(t)
    return t * t * (3 - 2 * t)


def ease_out_back(t: float, overshoot: float = 1.4) -> float:
    t = clamp(t) - 1
    return 1 + (overshoot + 1) * t * t * t + overshoot * t * t


def ease_in_out(t: float) -> float:
    t = clamp(t)
    return 4 * t * t * t if t < 0.5 else 1 - (-2 * t + 2) ** 3 / 2


def noise1(t: float, seed: float = 0.0) -> float:
    """Cheap smooth pseudo-noise in [-1, 1]: incommensurate sines never loop visibly."""
    return (
        math.sin(t * 1.13 + seed * 7.1) * 0.5
        + math.sin(t * 2.31 + seed * 3.3) * 0.3
        + math.sin(t * 4.77 + seed * 1.7) * 0.2
    )


# ---------------------------------------------------------------- colours


@lru_cache(maxsize=1024)
def rgb(colour: str) -> tuple[int, int, int]:
    value = colour.lstrip("#")
    return int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16)


def col(colour: str, alpha: float = 1.0) -> int:
    r, g, b = rgb(colour)
    return skia.Color(r, g, b, round(clamp(alpha) * 255))


def mix(a: str, b: str, t: float) -> str:
    ra, ga, ba = rgb(a)
    rb, gb, bb = rgb(b)
    t = clamp(t)
    return f"#{round(lerp(ra, rb, t)):02x}{round(lerp(ga, gb, t)):02x}{round(lerp(ba, bb, t)):02x}"


def shade_of(colour: str, amount: float, tint: str = "#3b1d2e") -> str:
    """Shadow colour: darker and slightly purple, like painted warm light."""
    return mix(colour, tint, amount)


# ---------------------------------------------------------------- paints


def fill(
    colour: str,
    alpha: float = 1.0,
    *,
    blur: float = 0.0,
    blend: skia.BlendMode | None = None,
    shader: skia.Shader | None = None,
) -> skia.Paint:
    paint = skia.Paint(AntiAlias=True, Color=col(colour, alpha))
    if shader is not None:
        paint.setShader(shader)
        paint.setAlphaf(alpha)
    if blur > 0:
        paint.setMaskFilter(skia.MaskFilter.MakeBlur(skia.kNormal_BlurStyle, blur))
    if blend is not None:
        paint.setBlendMode(blend)
    return paint


def stroke(
    colour: str,
    width: float,
    alpha: float = 1.0,
    *,
    cap: skia.Paint.Cap = skia.Paint.kRound_Cap,
    blur: float = 0.0,
) -> skia.Paint:
    paint = skia.Paint(
        AntiAlias=True,
        Color=col(colour, alpha),
        Style=skia.Paint.kStroke_Style,
        StrokeWidth=width,
        StrokeCap=cap,
        StrokeJoin=skia.Paint.kRound_Join,
    )
    if blur > 0:
        paint.setMaskFilter(skia.MaskFilter.MakeBlur(skia.kNormal_BlurStyle, blur))
    return paint


def linear(
    p0: Point,
    p1: Point,
    colours: Sequence[str],
    alphas: Sequence[float] | None = None,
    stops: Sequence[float] | None = None,
) -> skia.Shader:
    alphas = alphas or [1.0] * len(colours)
    return skia.GradientShader.MakeLinear(
        [skia.Point(*p0), skia.Point(*p1)],
        [col(c, a) for c, a in zip(colours, alphas, strict=True)],
        list(stops) if stops else None,
    )


def radial(
    centre: Point,
    radius: float,
    colours: Sequence[str],
    alphas: Sequence[float] | None = None,
    stops: Sequence[float] | None = None,
) -> skia.Shader:
    alphas = alphas or [1.0] * len(colours)
    return skia.GradientShader.MakeRadial(
        skia.Point(*centre),
        radius,
        [col(c, a) for c, a in zip(colours, alphas, strict=True)],
        list(stops) if stops else None,
    )


# ---------------------------------------------------------------- paths


class PathBuilder:
    """Fluent wrapper so shapes read like SVG path data."""

    def __init__(self) -> None:
        self.path = skia.Path()

    def m(self, x: float, y: float) -> PathBuilder:
        self.path.moveTo(x, y)
        return self

    def l(self, x: float, y: float) -> PathBuilder:  # noqa: E743 - SVG path naming
        self.path.lineTo(x, y)
        return self

    def q(self, cx: float, cy: float, x: float, y: float) -> PathBuilder:
        self.path.quadTo(cx, cy, x, y)
        return self

    def c(self, c1x: float, c1y: float, c2x: float, c2y: float, x: float, y: float) -> PathBuilder:
        self.path.cubicTo(c1x, c1y, c2x, c2y, x, y)
        return self

    def z(self) -> skia.Path:
        self.path.close()
        return self.path

    def done(self) -> skia.Path:
        return self.path


def smooth(points: Sequence[Point], closed: bool = True, tension: float = 1.0) -> skia.Path:
    """Catmull-Rom spline through points, emitted as cubic Béziers."""
    path = skia.Path()
    count = len(points)
    if count < 2:
        return path
    path.moveTo(*points[0])
    segments = count if closed else count - 1
    for i in range(segments):
        p0 = points[(i - 1) % count] if closed or i > 0 else points[0]
        p1 = points[i]
        p2 = points[(i + 1) % count]
        p3 = points[(i + 2) % count] if closed or i + 2 < count else points[-1]
        k = tension / 6
        path.cubicTo(
            p1[0] + (p2[0] - p0[0]) * k,
            p1[1] + (p2[1] - p0[1]) * k,
            p2[0] - (p3[0] - p1[0]) * k,
            p2[1] - (p3[1] - p1[1]) * k,
            p2[0],
            p2[1],
        )
    if closed:
        path.close()
    return path


def ellipse(cx: float, cy: float, rx: float, ry: float) -> skia.Path:
    path = skia.Path()
    path.addOval(skia.Rect.MakeLTRB(cx - rx, cy - ry, cx + rx, cy + ry))
    return path


def circle(cx: float, cy: float, r: float) -> skia.Path:
    path = skia.Path()
    path.addCircle(cx, cy, r)
    return path


def rrect(x0: float, y0: float, x1: float, y1: float, r: float) -> skia.Path:
    path = skia.Path()
    path.addRRect(skia.RRect.MakeRectXY(skia.Rect.MakeLTRB(x0, y0, x1, y1), r, r))
    return path


def capsule(a: Point, b: Point, wa: float, wb: float) -> skia.Path:
    """Tapered limb between two joints with rounded ends."""
    ax, ay = a
    bx, by = b
    dx, dy = bx - ax, by - ay
    length = math.hypot(dx, dy) or 1e-3
    nx, ny = -dy / length, dx / length
    ra, rb = wa / 2, wb / 2
    ux, uy = dx / length, dy / length
    path = skia.Path()
    path.moveTo(ax + nx * ra, ay + ny * ra)
    path.lineTo(bx + nx * rb, by + ny * rb)
    path.cubicTo(
        bx + nx * rb + ux * rb * 1.33,
        by + ny * rb + uy * rb * 1.33,
        bx - nx * rb + ux * rb * 1.33,
        by - ny * rb + uy * rb * 1.33,
        bx - nx * rb,
        by - ny * rb,
    )
    path.lineTo(ax - nx * ra, ay - ny * ra)
    path.cubicTo(
        ax - nx * ra - ux * ra * 1.33,
        ay - ny * ra - uy * ra * 1.33,
        ax + nx * ra - ux * ra * 1.33,
        ay + ny * ra - uy * ra * 1.33,
        ax + nx * ra,
        ay + ny * ra,
    )
    path.close()
    return path


def union(paths: Iterable[skia.Path]) -> skia.Path:
    """Boolean union. Skia's path ops occasionally reject near-coincident
    curves, so fall back to pairwise unions (nudging a stubborn piece by a
    hundredth of a pixel) and finally to plain path concatenation."""
    items = list(paths)
    builder = skia.OpBuilder()
    for path in items:
        builder.add(path, skia.PathOp.kUnion_PathOp)
    try:
        return builder.resolve()
    except RuntimeError:
        pass
    result = skia.Path(items[0])
    for path in items[1:]:
        for dx, dy in ((0.0, 0.0), (0.013, 0.007), (-0.011, 0.017)):
            try:
                result = skia.Op(result, offset(path, dx, dy), skia.PathOp.kUnion_PathOp)
                break
            except RuntimeError:
                continue
        else:
            result.addPath(path)
    return result


def _op(a: skia.Path, b: skia.Path, op: skia.PathOp) -> skia.Path:
    for dx, dy in ((0.0, 0.0), (0.013, 0.007)):
        try:
            return skia.Op(a, offset(b, dx, dy), op)
        except RuntimeError:
            continue
    return skia.Path()


def difference(a: skia.Path, b: skia.Path) -> skia.Path:
    return _op(a, b, skia.PathOp.kDifference_PathOp)


def intersect(a: skia.Path, b: skia.Path) -> skia.Path:
    return _op(a, b, skia.PathOp.kIntersect_PathOp)


def offset(path: skia.Path, dx: float, dy: float) -> skia.Path:
    moved = skia.Path(path)
    moved.offset(dx, dy)
    return moved


def transformed(path: skia.Path, matrix: skia.Matrix) -> skia.Path:
    moved = skia.Path(path)
    moved.transform(matrix)
    return moved


# ---------------------------------------------------------------- shading

#: Key light comes from the upper left (low golden sun), so shadows fall right.
LIGHT = (-0.82, -0.57)
INK = "#2a160f"


def cel(
    canvas: skia.Canvas,
    path: skia.Path,
    base: str,
    *,
    shadow: float = 0.32,
    depth: float = 14.0,
    rim: float = 0.0,
    rim_colour: str = "#ffd79a",
    rim_depth: float = 5.0,
    outline: str | None = INK,
    width: float = 3.0,
    soft: float = 0.0,
    light: Point = LIGHT,
) -> None:
    """Fill, form shadow away from the light, warm rim toward it, then ink."""
    canvas.drawPath(path, fill(base))
    if shadow > 0:
        lit = offset(path, light[0] * depth, light[1] * depth)
        dark = difference(path, lit)
        canvas.save()
        canvas.clipPath(path, doAntiAlias=True)
        canvas.drawPath(dark, fill(shade_of(base, shadow), blur=soft))
        canvas.restore()
    if rim > 0:
        away = offset(path, -light[0] * rim_depth, -light[1] * rim_depth)
        edge = difference(path, away)
        canvas.save()
        canvas.clipPath(path, doAntiAlias=True)
        canvas.drawPath(edge, fill(rim_colour, rim))
        canvas.restore()
    if outline:
        canvas.drawPath(path, stroke(outline, width, 0.9))


def clipped(canvas: skia.Canvas, clip: skia.Path):
    """Context manager: draw only inside ``clip``."""

    class _Clip:
        def __enter__(self):
            canvas.save()
            canvas.clipPath(clip, doAntiAlias=True)
            return canvas

        def __exit__(self, *exc):
            canvas.restore()
            return False

    return _Clip()
