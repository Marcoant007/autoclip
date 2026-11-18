"""Timing: keyframed channels, word-anchored cues, procedural life and lip sync.

Acting keys are authored against the dialogue, not against seconds: a cue such
as ``"r1:carro"`` resolves to the measured start of the word *carro* in line
``r1``. Changing the voice or speaking rate keeps gestures on their words.
"""

from __future__ import annotations

import math
import random
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from .character import FLOAT_FIELDS, TEXT_FIELDS, Pose
from .draw import clamp, ease_in_out, ease_out_back, lerp, noise1, smoothstep

# ---------------------------------------------------------------- dialogue timing


@dataclass
class TimedWord:
    text: str
    start: float
    end: float


@dataclass
class TimedLine:
    id: str
    speaker: str
    text: str
    start: float
    end: float
    words: list[TimedWord]


def fold(text: str) -> str:
    """Lower-case, accent-free letters only, for matching cue words."""
    text = unicodedata.normalize("NFD", text.lower())
    return "".join(ch for ch in text if ch.isalpha())


class Cues:
    """Resolve textual time references against the measured dialogue."""

    def __init__(self, lines: list[TimedLine], duration: float):
        self.lines = {line.id: line for line in lines}
        self.duration = duration

    def resolve(self, ref: Any) -> float:
        if isinstance(ref, (int, float)):
            return float(ref)
        text = str(ref).strip()
        try:
            return float(text)
        except ValueError:
            pass
        offset = 0.0
        # Offsets may stack ("s1:carro+0.20+0.30"); fold them right to left.
        while True:
            match = re.match(r"^(.*?)([+-]\d+(?:\.\d+)?)$", text)
            if not (match and match.group(1)):
                break
            text, offset = match.group(1), offset + float(match.group(2))
        if text == "end":
            return self.duration + offset
        if text == "start":
            return offset
        edge = "start"
        if text.endswith(".end"):
            text, edge = text[:-4], "end"
        if "@" in text:
            line_id, fraction = text.split("@", 1)
            line = self._line(line_id)
            return lerp(line.start, line.end, float(fraction)) + offset
        if ":" in text:
            line_id, word = text.split(":", 1)
            line = self._line(line_id)
            wanted = fold(word)
            for item in line.words:
                if fold(item.text) == wanted:
                    return (item.end if edge == "end" else item.start) + offset
            raise ValueError(f"Cue word {word!r} not found in line {line_id!r}.")
        line = self._line(text)
        return (line.end if edge == "end" else line.start) + offset

    def _line(self, line_id: str) -> TimedLine:
        if line_id not in self.lines:
            raise ValueError(f"Unknown dialogue line {line_id!r} in a cue.")
        return self.lines[line_id]


# ---------------------------------------------------------------- keyframed channels


EASES = {
    "inout": ease_in_out,
    "smooth": smoothstep,
    "back": ease_out_back,
    "linear": lambda t: clamp(t),
}


@dataclass
class Segment:
    start: float
    end: float
    value: Any
    ease: str


class Channels:
    """Per-channel motion: each key moves a channel to a value by a given time."""

    def __init__(self, base: dict[str, Any]):
        self.base = dict(base)
        self.segments: dict[str, list[Segment]] = {}

    def add(self, time: float, values: dict[str, Any], duration: float, ease: str) -> None:
        for name, value in values.items():
            self.segments.setdefault(name, []).append(Segment(time - duration, time, value, ease))

    def finish(self) -> None:
        for items in self.segments.values():
            items.sort(key=lambda segment: segment.end)

    def value(self, name: str, t: float) -> Any:
        value = self.base.get(name)
        for segment in self.segments.get(name, ()):
            if t >= segment.end:
                value = segment.value
                continue
            if t <= segment.start:
                break
            amount = (t - segment.start) / max(1e-6, segment.end - segment.start)
            if isinstance(segment.value, str) or isinstance(value, str):
                return segment.value if amount >= 0.5 else value
            return lerp(value, segment.value, EASES[segment.ease](amount))
        return value


# ---------------------------------------------------------------- lip sync

VOWELS = {
    "a": (0.95, 0.35, 0.0),
    "e": (0.6, 0.8, 0.0),
    "i": (0.38, 1.0, 0.0),
    "o": (0.7, 0.0, 0.8),
    "u": (0.42, 0.0, 1.0),
}
CLOSED = (0.0, 0.15, 0.0)  # m, b, p
LABIODENTAL = (0.14, 0.45, 0.0)  # f, v
CONSONANT = (0.26, 0.45, 0.05)


def visemes(word: str) -> list[tuple[float, tuple[float, float, float]]]:
    """(weight, (open, wide, round)) segments for one word, Portuguese-flavoured."""
    letters = fold(word)
    out: list[tuple[float, tuple[float, float, float]]] = []
    for index, ch in enumerate(letters):
        if ch in VOWELS:
            shape, weight = VOWELS[ch], 1.0
            # Nasal endings ("-ão", "-em", "-om") close toward the end.
            if index == len(letters) - 1 and ch in "o" and len(letters) > 1 and letters[-2] == "a":
                shape = (0.55, 0.2, 0.55)
        elif ch in "mbp":
            shape, weight = CLOSED, 0.75
        elif ch in "fv":
            shape, weight = LABIODENTAL, 0.65
        else:
            shape, weight = CONSONANT, 0.45
        if out and out[-1][1] == shape:
            out[-1] = (out[-1][0] + weight * 0.5, shape)
        else:
            out.append((weight, shape))
    return out or [(1.0, VOWELS["a"])]


def mouth_tracks(words: list[TimedWord], energy: np.ndarray, fps: int) -> np.ndarray:
    """Per-frame (open, wide, round) for one speaker, smoothed like a real jaw."""
    count = len(energy)
    target = np.zeros((count, 3), dtype=np.float32)
    for word in words:
        segments = visemes(word.text)
        total = sum(weight for weight, _ in segments)
        first = max(0, int(math.floor(word.start * fps)))
        last = min(count - 1, int(math.ceil(word.end * fps)))
        for frame in range(first, last + 1):
            t = frame / fps
            if not (word.start <= t < word.end):
                continue
            u = (t - word.start) / max(1e-3, word.end - word.start) * total
            acc = 0.0
            for weight, shape in segments:  # noqa: B007 - shape is read after break
                if u <= acc + weight:
                    break
                acc += weight
            loud = float(energy[frame])
            gain = 0.35 + 0.85 * loud if loud > 0.04 else 0.25
            target[frame] = (min(1.0, shape[0] * gain), shape[1], shape[2])
    # Two cascaded exponential followers (~35 ms each): a fast jaw attack
    # without frame-to-frame chatter, unconditionally stable at any fps.
    alpha = 1 - math.exp(-(1 / fps) / 0.035)
    smooth = np.zeros_like(target)
    first = np.zeros(3, dtype=np.float32)
    second = np.zeros(3, dtype=np.float32)
    for frame in range(count):
        first += (target[frame] - first) * alpha
        second += (first - second) * alpha
        smooth[frame] = np.clip(second, 0, 1)
    return smooth


def speech_energy(samples: np.ndarray, rate: int, fps: int, frames: int) -> np.ndarray:
    energy = np.zeros(frames, dtype=np.float32)
    step = rate / fps
    for index in range(frames):
        block = samples[int(index * step) : int((index + 1) * step)]
        if len(block):
            energy[index] = float(np.sqrt(np.mean(block * block)))
    voiced = energy[energy > 1e-4]
    peak = float(np.percentile(voiced, 92)) if len(voiced) else 1.0
    return np.clip(energy / max(peak, 1e-4), 0, 1)


# ---------------------------------------------------------------- performance


@dataclass
class Performer:
    """One character's whole performance for a shot."""

    id: str
    channels: Channels
    lines: list[TimedLine]
    mouth: np.ndarray
    energy: np.ndarray
    fps: int
    seed: int = 1
    blinks: list[float] = field(default_factory=list)
    saccades: list[tuple[float, float, float]] = field(default_factory=list)

    def plan_life(self, duration: float, forced_blinks: list[float]) -> None:
        rng = random.Random(self.seed)
        t = rng.uniform(0.6, 1.6)
        while t < duration:
            self.blinks.append(t)
            t += rng.uniform(2.2, 4.6)
        for forced in forced_blinks:
            if all(abs(forced - b) > 0.5 for b in self.blinks):
                self.blinks.append(forced)
        self.blinks.sort()
        t = 0.0
        while t < duration:
            t += rng.uniform(0.6, 1.5)
            self.saccades.append((t, rng.uniform(-0.07, 0.07), rng.uniform(-0.05, 0.05)))

    def speaking_at(self, t: float) -> TimedLine | None:
        for line in self.lines:
            if line.start - 0.05 <= t <= line.end + 0.1:
                return line
        return None

    def pose(self, t: float) -> Pose:
        pose = self._keyed(t)
        before = self._keyed(max(0.0, t - 0.14))
        frame = min(len(self.energy) - 1, max(0, int(round(t * self.fps))))
        seed = self.seed * 1.37
        pose.time = t
        # Breathing and idle drift keep a held pose alive.
        pose.breath = math.sin(t * math.tau / 3.7 + seed)
        pose.head_tilt += noise1(t * 0.6, seed) * 1.6
        pose.head_turn += noise1(t * 0.45, seed + 4) * 0.035
        pose.shift += noise1(t * 0.35, seed + 2) * 4
        pose.lean += noise1(t * 0.3, seed + 6) * 0.7
        # Speech drives head emphasis and brow lifts on stressed syllables.
        if self.speaking_at(t):
            level = float(self.energy[frame])
            pose.head_nod += (level - 0.45) * 0.28 + math.sin(t * 5.3 + seed) * 0.05 * level
            pose.brow_l += level * 0.16
            pose.brow_r += level * 0.16
            pose.head_tilt += math.sin(t * 2.7 + seed) * 1.6 * level
            jaw, wide, rounded = (float(v) for v in self.mouth[frame])
            pose.jaw = max(pose.jaw, jaw)
            pose.wide = lerp(pose.wide, wide, min(1.0, jaw * 2.5))
            pose.round = lerp(pose.round, rounded, min(1.0, jaw * 2.5))
        # Blinks: fast close, brief hold, slower open.
        for blink in self.blinks:
            age = t - blink
            if -0.07 <= age <= 0.16:
                closed = (
                    smoothstep((age + 0.07) / 0.07)
                    if age < 0
                    else 1 - smoothstep((age - 0.03) / 0.13)
                )
                pose.blink = max(pose.blink, closed)
        last = (0.0, 0.0)
        for when, dx, dy in self.saccades:
            if t < when:
                break
            last = (dx, dy)
        pose.gaze_x += last[0]
        pose.gaze_y += last[1]
        # Secondary motion: hair trails the head.
        pose.hair_dx = (
            (before.head_tilt - pose.head_tilt) * 1.8
            + (before.shift - pose.shift) * 0.5
            + (before.head_turn - pose.head_turn) * 40
        )
        pose.hair_dy = (before.bob - pose.bob) * 0.6 + (before.head_nod - pose.head_nod) * 10
        pose.wind = math.sin(t * 0.8 + seed) * 0.6 + math.sin(t * 1.7) * 0.3
        return pose

    def _keyed(self, t: float) -> Pose:
        pose = Pose()
        for name in FLOAT_FIELDS:
            value = self.channels.value(name, t)
            if value is not None:
                setattr(pose, name, float(value))
        for name in TEXT_FIELDS:
            value = self.channels.value(name, t)
            if value is not None:
                setattr(pose, name, str(value))
        return pose


def build_channels(
    base: dict[str, Any],
    presets: dict[str, dict[str, Any]],
    keys: list[dict[str, Any]],
    cues: Cues,
    *,
    rig: bool = True,
) -> tuple[Channels, list[float]]:
    # Every rig channel starts from the Pose default, so a key may animate a
    # channel the base never mentioned.
    defaults = (
        {name: getattr(Pose(), name) for name in (*FLOAT_FIELDS, *TEXT_FIELDS)} if rig else {}
    )
    channels = Channels({**defaults, **base})
    blinks: list[float] = []
    for key in keys:
        time = cues.resolve(key["at"])
        values: dict[str, Any] = {}
        for name in key.get("use", []):
            if name not in presets:
                raise ValueError(f"Unknown pose preset {name!r}.")
            values.update(presets[name])
        values.update(key.get("set", {}))
        unknown = set(values) - set(FLOAT_FIELDS) - set(TEXT_FIELDS)
        if unknown:
            raise ValueError(f"Unknown pose channels: {sorted(unknown)}")
        channels.add(time, values, float(key.get("dur", 0.4)), key.get("ease", "inout"))
        if key.get("blink"):
            blinks.append(time - float(key.get("dur", 0.4)) * 0.6)
    channels.finish()
    return channels, blinks


__all__ = [
    "Channels",
    "Cues",
    "Performer",
    "TimedLine",
    "TimedWord",
    "build_channels",
    "mouth_tracks",
    "speech_energy",
    "visemes",
]
