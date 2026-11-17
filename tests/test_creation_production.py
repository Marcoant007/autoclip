"""Production contracts, speech resume, shared queue and actual narrated renders."""

from __future__ import annotations

import asyncio
import io
import math
import struct
import subprocess
import wave
from collections.abc import Iterator
from types import SimpleNamespace

import edge_tts
import pysubs2
import pytest
from autoclip import db
from autoclip.app import ENV_NO_WORKER, create_app
from autoclip.config import ExportSettings
from autoclip.creation import CreationBrief, Scene, Storyboard
from autoclip.db import creation_renders, creations, store
from autoclip.db.models import Job, Source, new_id
from autoclip.jobs.queue import JobQueue
from autoclip.pipeline import creation_video, ffmpeg, speech
from autoclip.pipeline.transcript import Word
from autoclip.production import RenderOptions
from fastapi.testclient import TestClient
from PIL import Image


@pytest.fixture
def client(autoclip_home, monkeypatch) -> Iterator[TestClient]:
    monkeypatch.setenv(ENV_NO_WORKER, "1")
    with TestClient(create_app()) as test_client:
        yield test_client


@pytest.fixture
def creation(initialised_db):
    storyboard = Storyboard(
        title="Uma explicação",
        description="Descrição para o vídeo.",
        scenes=[
            Scene(
                narration="Um teste de voz.",
                visual_description="Uma ilustração azul.",
                on_screen_text=f"Parte {i + 1}",
            )
            for i in range(3)
        ],
    )
    return creations.create(CreationBrief(topic="Um tema"), storyboard, "ollama", "test")


def png_bytes() -> bytes:
    output = io.BytesIO()
    image = Image.new("RGB", (200, 300))
    for x in range(200):
        for y in range(300):
            image.putpixel((x, y), (x, y % 256, (x + y) % 256))
    image.save(output, format="PNG")
    return output.getvalue()


def test_render_api_snapshot_revision_and_duplicate_protection(client, creation):
    endpoint = f"/api/creations/{creation.id}/renders"
    response = client.post(endpoint, json={"revision": creation.revision})
    assert response.status_code == 201
    record = response.json()
    assert record["options"]["voice"] == "pt-BR-AntonioNeural"
    assert record["status"] == "queued"
    assert "snapshot" not in record and "export_settings" not in record
    assert client.post(endpoint, json={"revision": creation.revision}).status_code == 409
    assert len(client.get(endpoint).json()) == 1

    edited = creation.storyboard.model_copy(deep=True)
    edited.scenes[0].narration = "Narração nova."
    creations.update(creation.id, edited, creation.revision)
    snapshot = creation_renders.get(record["id"]).snapshot
    assert snapshot.storyboard.scenes[0].narration == "Um teste de voz."
    assert client.post(endpoint, json={"revision": creation.revision}).status_code == 409


def test_cancel_and_retry_allow_only_valid_states(client, creation):
    endpoint = f"/api/creations/{creation.id}/renders"
    record = client.post(endpoint, json={"revision": 1}).json()
    url = f"{endpoint}/{record['id']}"
    assert client.get(url + "/media").status_code == 409
    assert client.get(url + "/subtitles").status_code == 409
    assert client.get(url + "/poster").status_code == 409
    assert client.post(url + "/retry").status_code == 409
    assert client.post(url + "/cancel").json()["status"] == "cancelled"
    assert client.post(url + "/cancel").status_code == 409
    assert client.post(url + "/retry").json()["status"] == "queued"
    from autoclip.jobs.queue import queue

    assert not queue.is_cancelled(record["id"])
    creation_renders.update(record["id"], status="done")
    assert client.post(url + "/retry").status_code == 409


def test_retry_is_blocked_while_a_new_render_is_active(client, creation):
    endpoint = f"/api/creations/{creation.id}/renders"
    first = client.post(endpoint, json={"revision": 1}).json()
    creation_renders.update(first["id"], status="failed", error="Network failure")
    assert client.post(endpoint, json={"revision": 1}).status_code == 201
    assert client.post(f"{endpoint}/{first['id']}/retry").status_code == 409


@pytest.mark.parametrize(
    "options",
    [
        {"voice": "unknown"},
        {"voice": "en-US-GuyNeural"},
        {"rate_percent": 100},
        {"resolution": "4k"},
        {"caption_style": "unknown"},
    ],
)
def test_invalid_render_options_are_rejected(client, creation, options):
    response = client.post(
        f"/api/creations/{creation.id}/renders", json={"revision": 1, "options": options}
    )
    assert response.status_code in (400, 422)
    assert creation_renders.list_recent(creation.id) == []


def test_uploaded_image_is_normalized_and_scoped_to_creation(client, creation):
    endpoint = f"/api/creations/{creation.id}"
    result = client.post(
        endpoint + "/images", files={"file": ("../../image.png", png_bytes(), "image/png")}
    )
    assert result.status_code == 201
    image_id = result.json()["image_id"]
    data = client.get(f"{endpoint}/images/{image_id}")
    assert data.status_code == 200
    with Image.open(io.BytesIO(data.content)) as image:
        assert image.size == (200, 300)
        assert image.mode == "RGB"
    assert client.get(f"{endpoint}/images/not-an-asset").status_code == 422
    assert client.get(f"{endpoint}/images/{new_id()}").status_code == 404
    assert (
        client.post(
            endpoint + "/images", files={"file": ("bad.svg", b"<svg/>", "image/svg+xml")}
        ).status_code
        == 415
    )


def test_missing_image_prevents_enqueue(client, creation):
    creation.storyboard.scenes[0].image_id = new_id()
    updated = creations.update(creation.id, creation.storyboard, creation.revision)
    response = client.post(
        f"/api/creations/{creation.id}/renders", json={"revision": updated.revision}
    )
    assert response.status_code == 400


def test_import_downloaded_storyboard_assigns_new_identity_and_clears_asset_refs(client, creation):
    creation.storyboard.scenes[0].image_id = new_id()
    payload = creation.model_dump(mode="json")
    response = client.post("/api/creations/import", json=payload)
    assert response.status_code == 201
    imported = response.json()
    assert imported["id"] != creation.id
    assert imported["provider"] == "imported"
    assert imported["revision"] == 1
    assert imported["storyboard"]["title"] == creation.storyboard.title
    assert imported["storyboard"]["scenes"][0]["image_id"] is None
    assert client.get(f"/api/creations/{imported['id']}").status_code == 200


def test_render_cannot_be_read_through_another_creation(client, creation):
    render = creation_renders.create(creation, RenderOptions(), ExportSettings())
    other = creations.create(creation.brief, creation.storyboard, "ollama", "test")
    assert client.get(f"/api/creations/{other.id}/renders/{render.id}").status_code == 404
    assert client.get(f"/api/creations/{other.id}/renders/{render.id}/media").status_code == 404


def test_interrupted_render_is_requeued_after_restart(creation):
    render = creation_renders.create(creation, RenderOptions(), ExportSettings())
    creation_renders.update(render.id, status="running", stage="Narração", progress=0.2)
    db.reset_connections()
    db.init()
    creation_renders.requeue_interrupted()
    assert creation_renders.get(render.id).status == "queued"
    assert creation_renders.next_queued().id == render.id


async def test_shared_worker_respects_fifo_across_clips_and_creations(creation, monkeypatch):
    render = creation_renders.create(creation, RenderOptions(), ExportSettings())
    source = store.create_source(Source(id=new_id(), type="upload", path="/test.mp4"))
    job = store.create_job(Job(id=new_id(), source_id=source.id, created_at="9999-01-01"))
    worker = JobQueue()
    seen = []
    finished = asyncio.Event()

    async def run_creation(item):
        seen.append(item.id)
        creation_renders.update(item.id, status="done")

    async def run_clip(item):
        seen.append(item.id)
        store.update_job(item.id, status="done")
        finished.set()

    monkeypatch.setattr(worker, "_run_creation", run_creation)
    monkeypatch.setattr(worker, "_run_one", run_clip)
    await worker.start()
    try:
        await asyncio.wait_for(finished.wait(), timeout=3)
    finally:
        await worker.stop()
    assert seen == [render.id, job.id]


@pytest.fixture
def fake_speech(monkeypatch):
    calls = []
    chunks = [
        {"type": "audio", "data": b"fake mp3 audio"},
        {"type": "WordBoundary", "text": "Teste", "offset": 1000000, "duration": 4000000},
    ]

    class FakeCommunicate:
        def __init__(self, text, voice, **kwargs):
            calls.append((text, voice, kwargs))

        async def stream(self):
            for chunk in chunks:
                yield chunk

    monkeypatch.setattr(edge_tts, "Communicate", FakeCommunicate)
    monkeypatch.setattr(speech.ffmpeg, "probe", lambda _: SimpleNamespace(duration_s=1.0))
    return calls, chunks


async def test_speech_uses_word_boundaries_and_reuses_matching_cache(tmp_path, fake_speech):
    calls, _ = fake_speech
    result = await speech.synthesize("Teste.", "pt-BR-AntonioNeural", 10, tmp_path, lambda: False)
    assert result.words[0].start == 0.1
    assert result.words[0].end == 0.5
    assert calls[0][2]["boundary"] == "WordBoundary"
    assert calls[0][2]["rate"] == "+10%"
    await speech.synthesize("Teste.", "pt-BR-AntonioNeural", 10, tmp_path, lambda: False)
    assert len(calls) == 1
    await speech.synthesize("Outro texto.", "pt-BR-AntonioNeural", 10, tmp_path, lambda: False)
    assert len(calls) == 2


async def test_corrupt_speech_cache_is_regenerated(tmp_path, fake_speech):
    calls, _ = fake_speech
    await speech.synthesize("Teste.", "pt-BR-AntonioNeural", 0, tmp_path, lambda: False)
    (tmp_path / "speech.json").write_text("{broken", encoding="utf-8")
    await speech.synthesize("Teste.", "pt-BR-AntonioNeural", 0, tmp_path, lambda: False)
    assert len(calls) == 2


async def test_invalid_speech_timings_never_commit_audio(tmp_path, fake_speech):
    _, chunks = fake_speech
    chunks[1]["offset"] = 50000000
    with pytest.raises(RuntimeError, match="tempos de palavras"):
        await speech.synthesize("Teste.", "pt-BR-AntonioNeural", 0, tmp_path, lambda: False)
    assert not (tmp_path / "narration.mp3").exists()
    assert not (tmp_path / "speech.json").exists()


async def test_cancelled_speech_cleans_partial_file(tmp_path, fake_speech):
    with pytest.raises(ffmpeg.Cancelled):
        await speech.synthesize("Teste.", "pt-BR-AntonioNeural", 0, tmp_path, lambda: True)
    assert not (tmp_path / "narration.partial.mp3").exists()


async def test_runner_reports_voice_failure_and_can_be_cancelled(creation, monkeypatch):
    async def fail(*args):
        raise RuntimeError("Voice service unavailable")

    monkeypatch.setattr(speech, "synthesize", fail)
    render = creation_renders.create(creation, RenderOptions(), ExportSettings())
    await creation_video.CreationVideoRunner(render, lambda: False).run()
    failed = creation_renders.get(render.id)
    assert failed.status == "failed" and "Voice service" in failed.error
    assert not creation_video.video_path(render.id).exists()
    assert creation_renders.retry(render.id)
    await creation_video.CreationVideoRunner(creation_renders.get(render.id), lambda: True).run()
    assert creation_renders.get(render.id).status == "cancelled"


@pytest.mark.slow
async def test_real_render_has_audio_motion_captions_and_resumes(
    client, creation, monkeypatch, tmp_path
):
    # Only speech transport is replaced. Artwork, timing, fonts, subtitles,
    # encoding, concat and final media checks all execute for real.
    voice = tmp_path / "test voice.wav"
    sample_rate = 24000
    with wave.open(str(voice), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(sample_rate)
        output.writeframes(
            b"".join(
                struct.pack("<h", round(7000 * math.sin(2 * math.pi * 440 * i / sample_rate)))
                for i in range(round(1.2 * sample_rate))
            )
        )

    async def synthesize(*args):
        return speech.Speech(
            voice,
            1.2,
            [Word("Um", 0.1, 0.35), Word("teste", 0.35, 0.65), Word("de voz.", 0.65, 1.0)],
        )

    monkeypatch.setattr(speech, "synthesize", synthesize)
    image_id = new_id()
    target = creation_video.asset_directory(creation.id) / f"{image_id}.png"
    creation_video.normalize_image(png_bytes(), target)
    creation.storyboard.scenes[1].image_id = image_id
    creation = creations.update(creation.id, creation.storyboard, creation.revision)
    record = creation_renders.create(
        creation, RenderOptions(), ExportSettings(prefer_hardware_encoder=False, crf=25)
    )
    runner = creation_video.CreationVideoRunner(record, lambda: False)
    await runner.run()
    completed = creation_renders.get(record.id)
    assert completed.status == "done", completed.error
    media = creation_video.video_path(record.id)
    info = ffmpeg.probe(media)
    assert (info.width, info.height) == (720, 1280)
    assert info.video_codec == "h264" and info.audio_codec == "aac"
    assert abs(info.duration_s - 3.6) < 0.2
    endpoint = f"/api/creations/{creation.id}/renders/{record.id}"
    assert client.get(endpoint + "/poster").headers["content-type"] == "image/png"
    assert client.get(endpoint + "/media", headers={"Range": "bytes=0-1023"}).status_code == 206
    assert (
        "attachment" in client.get(endpoint + "/media?download=true").headers["content-disposition"]
    )
    subtitles = pysubs2.load(str(media.parent / "captions.srt"))
    assert len(subtitles.events) >= 3
    assert subtitles.events[-1].end >= 3300
    assert subtitles.events[-1].end <= completed.duration_s * 1000

    def frame_hash(time):
        return subprocess.check_output(
            [
                ffmpeg.ffmpeg_path(),
                "-v",
                "error",
                "-ss",
                str(time),
                "-i",
                str(media),
                "-vf",
                "crop=720:350:0:100",
                "-frames:v",
                "1",
                "-f",
                "hash",
                "-hash",
                "md5",
                "-",
            ]
        )

    assert frame_hash(0.4) != frame_hash(0.8)
    frame = subprocess.check_output(
        [
            ffmpeg.ffmpeg_path(),
            "-v",
            "error",
            "-ss",
            "0.4",
            "-i",
            str(media),
            "-frames:v",
            "1",
            "-f",
            "image2pipe",
            "-vcodec",
            "png",
            "-",
        ]
    )
    with Image.open(io.BytesIO(frame)) as decoded:
        caption_pixels = decoded.convert("RGB").crop((0, 900, 720, 1200)).getdata()
        assert sum(r > 200 and g > 160 and b < 100 for r, g, b in caption_pixels) > 40
    volume = subprocess.run(
        [
            ffmpeg.ffmpeg_path(),
            "-hide_banner",
            "-i",
            str(media),
            "-vn",
            "-af",
            "volumedetect",
            "-f",
            "null",
            "-",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert "mean_volume: -inf" not in volume.stderr
    assert "mean_volume:" in volume.stderr
    segments = list(media.parent.glob("scene-*/scene.mp4"))
    original_times = {segment: segment.stat().st_mtime_ns for segment in segments}
    await runner.run()
    assert {segment: segment.stat().st_mtime_ns for segment in segments} == original_times
