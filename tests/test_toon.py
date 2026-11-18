"""Skia 2D engine: cue timing, lip sync, rig geometry and a real frame render."""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pytest

skia = pytest.importorskip("skia")

from autoclip.toon.acting import (  # noqa: E402
    Cues,
    TimedLine,
    TimedWord,
    build_channels,
    mouth_tracks,
    visemes,
)
from autoclip.toon.character import ik  # noqa: E402
from autoclip.toon.scene import ShotRenderer  # noqa: E402

PILOT = Path(__file__).resolve().parents[1] / "examples/toon-pilot/pilot.json"


def lines():
    return [
        TimedLine(
            "r1",
            "rafa",
            "Esse carro é lindo…",
            1.0,
            2.0,
            [
                TimedWord("Esse", 1.0, 1.2),
                TimedWord("carro", 1.25, 1.6),
                TimedWord("lindo", 1.65, 2.0),
            ],
        ),
        TimedLine(
            "l1",
            "lara",
            "Quanto sobra no mês.",
            3.0,
            4.0,
            [
                TimedWord("Quanto", 3.0, 3.3),
                TimedWord("sobra", 3.35, 3.7),
                TimedWord("mês", 3.75, 4.0),
            ],
        ),
    ]


def test_cues_resolve_words_accents_offsets_and_edges():
    cues = Cues(lines(), 5.0)
    assert cues.resolve("r1:carro") == pytest.approx(1.25)
    assert cues.resolve("l1:mes") == pytest.approx(3.75)
    assert cues.resolve("l1:mês.end") == pytest.approx(4.0)
    assert cues.resolve("r1.end+0.35") == pytest.approx(2.35)
    assert cues.resolve("l1-0.2") == pytest.approx(2.8)
    assert cues.resolve("r1@0.5") == pytest.approx(1.5)
    assert cues.resolve("end") == pytest.approx(5.0)
    assert cues.resolve(0.9) == pytest.approx(0.9)
    with pytest.raises(ValueError):
        cues.resolve("r1:bolso")


def test_visemes_close_on_bilabials_and_round_on_o():
    shapes = [shape for _, shape in visemes("bolso")]
    assert shapes[0][0] == 0.0  # b: lips closed
    assert shapes[1][2] > 0.5  # o: rounded


def test_mouth_is_closed_outside_words_and_bounded():
    fps = 30
    energy = np.full(5 * fps, 0.8, dtype=np.float32)
    words = lines()[0].words
    mouth = mouth_tracks(words, energy, fps)
    assert np.all((mouth >= 0) & (mouth <= 1))
    assert mouth[: int(0.9 * fps), 0].max() < 0.01
    assert mouth[int(1.0 * fps) : int(2.0 * fps), 0].max() > 0.3
    assert mouth[int(2.6 * fps) :, 0].max() < 0.02


def test_ik_keeps_bone_lengths_while_elbow_swings():
    shoulder, target = (0.0, 0.0), (120.0, 160.0)
    previous = None
    for bend in np.linspace(-1, 1, 21):
        elbow, wrist = ik(shoulder, target, 200, 180, bend)
        assert math.dist(shoulder, elbow) == pytest.approx(200, abs=1e-6)
        assert math.dist(elbow, wrist) == pytest.approx(180, abs=1e-6)
        if previous is not None:
            assert math.dist(previous, elbow) < 40  # continuous, no flip
        previous = elbow


def test_keys_animate_channels_missing_from_the_base():
    channels, blinks = build_channels(
        {},
        {"tilt": {"head_tilt": 10}},
        [{"at": 2.0, "dur": 1.0, "use": ["tilt"], "blink": True}],
        Cues([], 3),
    )
    assert channels.value("head_tilt", 0.5) == 0
    assert 0 < channels.value("head_tilt", 1.5) < 10
    assert channels.value("head_tilt", 2.5) == 10
    assert blinks


def test_unknown_channel_is_rejected():
    with pytest.raises(ValueError):
        build_channels({}, {}, [{"at": 1, "set": {"elbow_magic": 1}}], Cues([], 2))


def test_pilot_renders_moving_frames():
    spec = json.loads(PILOT.read_text(encoding="utf-8"))
    spec["lines"] = [
        {"id": "r1", "speaker": "rafa", "text": "Esse carro é lindo…"},
        {"id": "r2", "speaker": "rafa", "text": "mas cabe no meu bolso?"},
        {"id": "l1", "speaker": "lara", "text": "olha quanto sobra no mês."},
    ]
    timed = [
        TimedLine(
            "r1", "rafa", "", 1.0, 2.0, [TimedWord("carro", 1.0, 1.5), TimedWord("lindo", 1.5, 2.0)]
        ),
        TimedLine(
            "r2",
            "rafa",
            "",
            2.5,
            3.5,
            [TimedWord("cabe", 2.5, 2.9), TimedWord("meu", 2.9, 3.1), TimedWord("bolso", 3.1, 3.5)],
        ),
        TimedLine(
            "l1",
            "lara",
            "",
            4.0,
            5.5,
            [
                TimedWord("Antes", 4.0, 4.3),
                TimedWord("olha", 4.3, 4.6),
                TimedWord("quanto", 4.6, 5.0),
                TimedWord("sobra", 5.0, 5.2),
                TimedWord("no", 5.2, 5.3),
                TimedWord("mês", 5.3, 5.5),
            ],
        ),
    ]
    duration, fps = 6.0, 30
    energy = np.full(int(duration * fps), 0.7, dtype=np.float32)
    mouths = {
        actor: mouth_tracks(
            [w for line in timed if line.speaker == actor for w in line.words], energy, fps
        )
        for actor in spec["cast"]
    }
    renderer = ShotRenderer(spec, timed, duration, energy, mouths, (180, 320))
    first = renderer.draw(0.2).toarray().astype(np.int16)
    later = renderer.draw(1.6).toarray().astype(np.int16)
    assert first.shape == (320, 180, 4)
    assert np.abs(first - later).mean() > 1.0
