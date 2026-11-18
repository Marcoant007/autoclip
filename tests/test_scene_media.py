"""Scene upload and real moving-media rendering through the public API."""

from __future__ import annotations

import io
import subprocess
import wave

import numpy as np
import pytest
from autoclip.animation import ActorTrack, CharacterDesign, PoseKey, ShotPlan
from autoclip.app import ENV_NO_WORKER, create_app
from autoclip.creation import CreationBrief, Scene, Storyboard
from autoclip.db import creation_renders, creations
from autoclip.pipeline import creation_video, ffmpeg, speech
from autoclip.pipeline.scene_media import SceneMediaError, _raster_animation_duration, asset_path
from autoclip.pipeline.transcript import Word
from fastapi.testclient import TestClient
from PIL import Image


@pytest.fixture
def client(autoclip_home, monkeypatch):
    monkeypatch.setenv(ENV_NO_WORKER, "1")
    with TestClient(create_app()) as client:
        yield client


@pytest.fixture
def creation(initialised_db):
    return creations.create(
        CreationBrief(topic="Teste de mídias"),
        Storyboard(
            title="Animação enviada",
            description="Cena com mídia local.",
            scenes=[
                Scene(narration="Uma fala de teste.", visual_description="Cores.") for _ in range(3)
            ],
        ),
        "imported",
        "",
    )


def gif_bytes(*, animated=True):
    frames = [Image.new("RGB", (64, 96), color) for color in ("red", "blue")]
    output = io.BytesIO()
    frames[0].save(
        output,
        format="GIF",
        save_all=animated,
        append_images=frames[1:] if animated else [],
        duration=300,
        loop=0,
    )
    return output.getvalue()


def webp_bytes(durations=(300, 300)):
    output = io.BytesIO()
    frames = [Image.new("RGB", (64, 96), color) for color in ("red", "blue")]
    frames[0].save(
        output,
        format="WEBP",
        save_all=True,
        append_images=frames[1:],
        lossless=True,
        duration=list(durations),
        loop=0,
    )
    return output.getvalue()


def test_webp_frame_timing_is_read_after_decoding_and_respects_limits():
    data = webp_bytes(durations=(80, 420))
    with Image.open(io.BytesIO(data)) as image:
        assert image.info.get("duration") is None
    assert _raster_animation_duration(data) == pytest.approx(0.5)
    with pytest.raises(SceneMediaError, match="180 segundos"):
        _raster_animation_duration(webp_bytes(durations=(100_000, 100_000)))


def test_thalita_is_selectable_for_narration_and_characters(client, creation):
    endpoint = f"/api/creations/{creation.id}"
    voice = "pt-BR-ThalitaMultilingualNeural"
    assert voice in {item["id"] for item in client.get(endpoint + "/voices").json()}
    actor = CharacterDesign(id="speaker", name="Personagem", voice=voice)
    storyboard = creation.storyboard.model_copy(deep=True)
    storyboard.cast = [actor]
    saved = client.put(endpoint, json={"revision": 1, "storyboard": storyboard.model_dump()})
    assert saved.status_code == 200
    render = client.post(endpoint + "/renders", json={"revision": 2, "options": {"voice": voice}})
    assert render.status_code == 201
    assert render.json()["options"]["voice"] == voice


def test_single_frame_gif_becomes_still_image(client, creation):
    endpoint = f"/api/creations/{creation.id}/images"
    result = client.post(
        endpoint, files={"file": ("still.gif", gif_bytes(animated=False), "image/gif")}
    )
    assert result.status_code == 201
    assert result.json()["media_type"] == "image"
    response = client.get(endpoint + "/" + result.json()["image_id"])
    assert response.headers["content-type"] == "image/png"


def test_fake_mp4_is_rejected_without_leaving_assets(client, creation, caplog):
    result = client.post(
        f"/api/creations/{creation.id}/images",
        files={"file": ("fake.mp4", b"\x00\x00\x00\x18ftypisomgarbage", "video/mp4")},
    )
    assert result.status_code == 422
    assert "converter" in result.json()["detail"]["message"]
    assert "Could not read source.mp4" in caplog.text
    directory = creation_video.asset_directory(creation.id)
    assert not directory.exists() or list(directory.iterdir()) == []


def test_unexpected_upload_failure_is_reported_as_internal_error(
    client, creation, monkeypatch, caplog
):
    from autoclip.api import creations as api

    def fail(*args):
        raise PermissionError("diagnostic: cannot write asset")

    monkeypatch.setattr(api, "save_visual", fail)
    result = client.post(
        f"/api/creations/{creation.id}/images",
        files={"file": ("valid.gif", gif_bytes(), "image/gif")},
    )
    assert result.status_code == 500
    assert "falha interna" in result.json()["detail"]["message"]
    assert "cannot write asset" in caplog.text


def test_empty_upload_has_actionable_error(client, creation):
    result = client.post(
        f"/api/creations/{creation.id}/images",
        files={"file": ("empty.png", b"", "image/png")},
    )
    assert result.status_code == 400
    assert "vazio" in result.json()["detail"]["message"]


def test_still_image_size_limit_is_not_reported_as_unsupported_format(
    client, creation, monkeypatch
):
    from autoclip.pipeline import scene_media

    monkeypatch.setattr(scene_media, "MAX_IMAGE_BYTES", 16)
    result = client.post(
        f"/api/creations/{creation.id}/images",
        files={"file": ("still.gif", gif_bytes(animated=False), "image/gif")},
    )
    assert result.status_code == 413
    assert "15 MB" in result.json()["detail"]["message"]


@pytest.mark.slow
@pytest.mark.parametrize("media_format", ["gif", "webp", "mp4"])
async def test_uploaded_motion_survives_looping_render_and_preserves_narration(
    client, creation, monkeypatch, tmp_path, media_format
):
    source = tmp_path / "source.gif"
    source.write_bytes(gif_bytes())
    mime = "image/gif"
    if media_format == "webp":
        source = tmp_path / "source.webp"
        source.write_bytes(webp_bytes())
        mime = "image/webp"
    if media_format == "mp4":
        mp4 = tmp_path / "source.mp4"
        ffmpeg.run(
            [
                "-stream_loop",
                "-1",
                "-i",
                str(source),
                "-f",
                "lavfi",
                "-i",
                "sine=frequency=880:duration=1.8",
                "-t",
                "1.8",
                "-map",
                "0:v:0",
                "-map",
                "1:a:0",
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                "aac",
                str(mp4),
            ]
        )
        assert ffmpeg.probe(mp4).has_audio
        source, mime = mp4, "video/mp4"
    endpoint = f"/api/creations/{creation.id}"
    uploaded = client.post(
        endpoint + "/images", files={"file": (source.name, source.read_bytes(), mime)}
    )
    assert uploaded.status_code == 201, uploaded.text
    asset = uploaded.json()
    assert asset["media_type"] == "video"
    stored = asset_path(creation.id, asset["image_id"])
    info = ffmpeg.probe(stored)
    assert info.has_video and not info.has_audio
    assert info.video_codec == "h264"
    asset_url = endpoint + "/images/" + asset["image_id"]
    assert client.get(asset_url, headers={"Range": "bytes=0-99"}).status_code == 206
    assert client.get(asset_url + "?poster=true").headers["content-type"] == "image/png"
    other = creations.create(creation.brief, creation.storyboard, "imported", "")
    assert client.get(f"/api/creations/{other.id}/images/{asset['image_id']}").status_code == 404

    storyboard = creation.storyboard.model_copy(deep=True)
    for scene in storyboard.scenes:
        scene.image_id, scene.media_type = asset["image_id"], "video"
    # Explicit uploads must also take precedence over an old animation plan in auto mode.
    storyboard.cast = [CharacterDesign(id="actor", name="Personagem")]
    storyboard.scenes[0].animation = ShotPlan(
        setting="street",
        actors=[ActorTrack(actor_id="actor", keys=[PoseKey(at=0, x=0.5), PoseKey(at=1, x=0.5)])],
    )
    updated = client.put(endpoint, json={"revision": 1, "storyboard": storyboard.model_dump()})
    assert updated.status_code == 200
    assert updated.json()["storyboard"]["scenes"][0]["media_type"] == "video"

    audio = tmp_path / "narration.wav"
    rate = 24000
    samples = (6000 * np.sin(2 * np.pi * 220 * np.arange(int(rate * 1.5)) / rate)).astype("<i2")
    with wave.open(str(audio), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(rate)
        output.writeframes(samples.tobytes())

    async def synthesize(*args):
        return speech.Speech(audio, 1.5, [Word(text="Teste", start=0.1, end=1.3)])

    monkeypatch.setattr(speech, "synthesize", synthesize)
    response = client.post(endpoint + "/renders", json={"revision": 2})
    assert response.status_code == 201, response.text
    record = creation_renders.get(response.json()["id"])
    await creation_video.CreationVideoRunner(record, lambda: False).run()
    done = creation_renders.get(record.id)
    assert done.status == "done", done.error
    output = creation_video.video_path(record.id)
    assert abs(ffmpeg.probe(output).duration_s - 4.5) < 0.15
    assert client.get(f"{endpoint}/renders/{record.id}/poster").status_code == 200
    assert "Teste" in client.get(f"{endpoint}/renders/{record.id}/subtitles").text

    # Uniform source colors make the assertion independent of overlays and camera effects.
    for time, red in ((0.2, True), (0.45, False), (0.8, True), (1.05, False)):
        pixel = subprocess.check_output(
            [
                ffmpeg.ffmpeg_path(),
                "-v",
                "error",
                "-ss",
                str(time),
                "-i",
                str(output),
                "-vf",
                "crop=32:32:200:200,scale=1:1",
                "-frames:v",
                "1",
                "-f",
                "rawvideo",
                "-pix_fmt",
                "rgb24",
                "-",
            ]
        )
        assert (pixel[0] > pixel[2]) == red, (time, pixel)
    # The 220 Hz narration survives; source MP4's 880 Hz soundtrack must not replace it.
    pcm = subprocess.check_output(
        [
            ffmpeg.ffmpeg_path(),
            "-v",
            "error",
            "-ss",
            "0.2",
            "-i",
            str(output),
            "-t",
            "0.8",
            "-vn",
            "-ac",
            "1",
            "-ar",
            str(rate),
            "-f",
            "s16le",
            "-",
        ]
    )
    data = np.frombuffer(pcm, dtype="<i2").astype(float)
    spectrum = np.abs(np.fft.rfft(data))
    peak = np.fft.rfftfreq(len(data), 1 / rate)[spectrum.argmax()]
    assert abs(peak - 220) < 5
