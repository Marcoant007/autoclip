"""Animation direction, independent rig motion and real cartoon encoding."""

from __future__ import annotations

import json
import math
import struct
import wave
from pathlib import Path

import numpy as np
import pytest
from autoclip import providers
from autoclip.animation import ActorTrack, AnimationDirection, PoseKey, direct_storyboard
from autoclip.app import ENV_NO_WORKER, create_app
from autoclip.creation import CreationImportIn
from autoclip.db import creations
from autoclip.pipeline import captions, cartoon, ffmpeg
from autoclip.pipeline.transcript import Word
from autoclip.providers.base import LLMProvider, ProviderStatus
from fastapi.testclient import TestClient
from pydantic import ValidationError


@pytest.fixture
def pilot():
    path = Path(__file__).resolve().parents[1] / "examples/moneyzi-cartoon-pilot.json"
    return CreationImportIn.model_validate_json(path.read_text(encoding="utf-8"))


def direction_payload(pilot):
    return {
        "cast": [actor.model_dump(mode="json") for actor in pilot.storyboard.cast],
        "shots": [scene.animation.model_dump(mode="json") for scene in pilot.storyboard.scenes],
    }


class DirectionProvider(LLMProvider):
    name = "ollama"
    requires_key = False

    def __init__(self, responses):
        super().__init__("test")
        self.responses = responses
        self.calls = []

    async def _complete(self, system, user, config):
        self.calls.append((system, user, config))
        return json.dumps(self.responses.pop(0))

    async def health_check(self):
        return ProviderStatus(name=self.name, available=True)


def test_direction_rejects_unknown_cast_and_offscreen_speaker(pilot):
    payload = direction_payload(pilot)
    payload["shots"][0]["actors"][0]["actor_id"] = "unknown"
    with pytest.raises(ValidationError):
        AnimationDirection.model_validate(payload)
    payload = direction_payload(pilot)
    payload["shots"][0]["speaker"] = "unknown"
    with pytest.raises(ValidationError):
        AnimationDirection.model_validate(payload)


@pytest.mark.parametrize("times", [[0.1, 1], [0, 0.9], [0, 0.5, 0.5, 1], [0, 0.8, 0.6, 1]])
def test_direction_requires_bounded_ordered_keyframes(times):
    with pytest.raises(ValidationError):
        ActorTrack(actor_id="rafa", keys=[PoseKey(at=time, x=0.3) for time in times])


async def test_director_repairs_scene_count_without_changing_the_script(pilot):
    before = [scene.narration for scene in pilot.storyboard.scenes]
    invalid = direction_payload(pilot)
    invalid["shots"] = invalid["shots"][:1]
    provider = DirectionProvider([invalid, direction_payload(pilot)])
    result = await direct_storyboard(pilot.brief, pilot.storyboard, provider)
    assert [scene.narration for scene in result.scenes] == before
    assert len(provider.calls) == 2
    assert "exactly 3 shots" in provider.calls[1][1]
    assert result.cast[1].voice == "pt-BR-FranciscaNeural"


async def test_director_keeps_approved_speakers_and_designs_when_model_changes_them(pilot):
    payload = direction_payload(pilot)
    payload["cast"][0]["skin"] = "#000000"
    for shot in payload["shots"]:
        shot["speaker"] = None
    result = await direct_storyboard(pilot.brief, pilot.storyboard, DirectionProvider([payload]))
    assert result.cast[0].skin == pilot.storyboard.cast[0].skin
    assert [scene.animation.speaker for scene in result.scenes] == ["rafa", "lara", "rafa"]


def test_actor_walk_starts_and_stops_at_marks():
    track = ActorTrack(actor_id="rafa", keys=[PoseKey(at=0, x=0.1), PoseKey(at=1, x=0.5)])
    start = cartoon.acting_state(track, 0)
    middle = cartoon.acting_state(track, 0.5)
    end = cartoon.acting_state(track, 1)
    assert start.x == 0.1 and end.x == 0.5
    assert middle.x == pytest.approx(0.3)
    assert start.walking == end.walking == 0
    assert middle.walking > 0.5


def test_fixed_camera_has_independent_acting_and_mouth_motion(pilot):
    shot = pilot.storyboard.scenes[0].animation.model_copy(deep=True)
    shot.zoom_start = shot.zoom_end = 1
    scene = cartoon.CartoonScene(shot, pilot.storyboard.cast, (360, 640), 6, supersampling=1)
    first = np.asarray(scene.frame(0.4, 0))
    later = np.asarray(scene.frame(3.9, 0))
    # The sky/buildings stay fixed while the entrance and arm/face rigs change.
    assert np.array_equal(first[:240], later[:240])
    assert np.count_nonzero(first[280:560] != later[280:560]) > 1000
    silent = np.asarray(scene.frame(2, 0))
    talking = np.asarray(scene.frame(2, 0.8))
    assert np.count_nonzero(silent != talking) > 30
    assert np.array_equal(silent[:, 240:], talking[:, 240:])


@pytest.fixture
def voice_wav(tmp_path):
    target = tmp_path / "speech sample.wav"
    rate = 8000
    with wave.open(str(target), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(rate)
        output.writeframes(
            b"".join(
                struct.pack(
                    "<h",
                    0 if i < rate // 2 else round(7000 * math.sin(2 * math.pi * 220 * i / rate)),
                )
                for i in range(rate)
            )
        )
    return target


def test_mouth_energy_tracks_real_audio_silence(voice_wav):
    envelope = cartoon.mouth_envelope(voice_wav, 1, 30)
    assert len(envelope) == 30
    assert max(envelope[:14]) == 0
    assert min(envelope[17:]) > 0.5


def test_plan_api_saves_new_revision_and_protects_concurrent_edits(
    pilot, autoclip_home, monkeypatch
):
    monkeypatch.setenv(ENV_NO_WORKER, "1")
    with TestClient(create_app()) as client:
        created = client.post("/api/creations/import", json=pilot.model_dump(mode="json")).json()
        provider = DirectionProvider([direction_payload(pilot)])
        monkeypatch.setattr(providers, "build_provider", lambda name=None: provider)
        url = f"/api/creations/{created['id']}/animation"
        response = client.post(url, json={"revision": 1})
        assert response.status_code == 200
        assert response.json()["revision"] == 2
        assert response.json()["storyboard"]["scenes"][0]["animation"]["setting"] == "street"
        assert client.post(url, json={"revision": 1}).status_code == 409

        async def concurrent_plan(*args):
            latest = creations.get(created["id"])
            changed = latest.storyboard.model_copy(deep=True)
            changed.title = "A newer user edit"
            creations.update(latest.id, changed, latest.revision)
            return pilot.storyboard

        from autoclip.api import creations as api_creations

        monkeypatch.setattr(api_creations, "direct_storyboard", concurrent_plan)
        response = client.post(url, json={"revision": 2})
        assert response.status_code == 409
        assert creations.get(created["id"]).storyboard.title == "A newer user edit"


def test_cartoon_mode_requires_a_plan_and_cast_survives_json_import(
    pilot, autoclip_home, monkeypatch
):
    monkeypatch.setenv(ENV_NO_WORKER, "1")
    with TestClient(create_app()) as client:
        imported = client.post("/api/creations/import", json=pilot.model_dump(mode="json")).json()
        endpoint = f"/api/creations/{imported['id']}"
        assert len(imported["storyboard"]["cast"]) == 2
        assert (
            client.post(
                endpoint + "/renders", json={"revision": 1, "options": {"visual_mode": "cartoon"}}
            ).status_code
            == 201
        )
        for scene in imported["storyboard"]["scenes"]:
            scene["animation"] = None
        updated = client.put(
            endpoint, json={"storyboard": imported["storyboard"], "revision": 1}
        ).json()
        assert (
            client.post(
                endpoint + "/renders",
                json={"revision": updated["revision"], "options": {"visual_mode": "cartoon"}},
            ).status_code
            == 400
        )


@pytest.mark.slow
def test_real_cartoon_frames_encode_and_cancel_without_committing(pilot, voice_wav, tmp_path):
    directory = tmp_path / "cartoon scene"
    directory.mkdir()
    subtitle = directory / "captions.ass"
    words = [Word("Teste", 0.5, 0.95)]
    captions.write_ass(subtitle, words, captions.get_style("clean_lower"), width=180, height=320)
    ffmpeg.relative_filter_workspace(subtitle, captions.FONT_DIR)
    output = directory / "scene.mp4"
    cartoon.render_cartoon(
        pilot.storyboard.scenes[0].animation,
        pilot.storyboard.cast,
        voice_wav,
        words,
        output,
        (180, 320),
        1,
        ["-c:v", "libx264", "-preset", "ultrafast", "-crf", "25"],
        lambda: False,
        lambda p: None,
    )
    info = ffmpeg.probe(output)
    assert (info.width, info.height) == (180, 320)
    assert info.has_audio and info.duration_s == pytest.approx(1, abs=0.1)
    assert (directory / "visual.png").exists()
    cancelled_output = directory / "cancelled.mp4"
    with pytest.raises(ffmpeg.Cancelled):
        cartoon.render_cartoon(
            pilot.storyboard.scenes[0].animation,
            pilot.storyboard.cast,
            voice_wav,
            words,
            cancelled_output,
            (180, 320),
            1,
            ["-c:v", "libx264", "-preset", "ultrafast"],
            lambda: True,
            lambda p: None,
        )
    assert not cancelled_output.exists()
