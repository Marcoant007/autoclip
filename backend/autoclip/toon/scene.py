"""Dialogue shot: narration timing, frame rendering and MP4 encoding.

A shot spec (JSON) names the cast, the dialogue lines and word-anchored acting
keys. ``prepare`` synthesises each line with the existing Edge TTS helper and
lays the lines on a timeline using their measured durations; ``render`` draws
every frame with Skia and streams it to FFmpeg with the existing caption and
encoder settings.
"""

from __future__ import annotations

import json
import math
import multiprocessing
import subprocess
import wave
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import numpy as np
import skia

from ..pipeline import captions, ffmpeg, speech
from ..pipeline.transcript import Word
from .acting import (
    Cues,
    Performer,
    TimedLine,
    TimedWord,
    build_channels,
    mouth_tracks,
    speech_energy,
)
from .character import Character, Look
from .draw import fill, linear
from .street import Camera, H, StreetSet, W

SAMPLE_RATE = 48_000


def load_spec(path: Path) -> dict[str, Any]:
    spec = json.loads(path.read_text(encoding="utf-8"))
    for line in spec["lines"]:
        if line.get("speaker") is not None and line["speaker"] not in spec["cast"]:
            raise ValueError(f"Line {line['id']!r} names an unknown speaker.")
    return spec


# ---------------------------------------------------------------- audio and timing


@dataclass
class Prepared:
    spec: dict[str, Any]
    lines: list[TimedLine]
    duration: float
    audio: Path
    captions: Path
    energy: np.ndarray
    mouths: dict[str, np.ndarray]


def _decode(path: Path) -> np.ndarray:
    command = [
        ffmpeg.ffmpeg_path(),
        "-v",
        "error",
        "-i",
        str(path.resolve()),
        "-f",
        "f32le",
        "-ac",
        "1",
        "-ar",
        str(SAMPLE_RATE),
        "pipe:1",
    ]
    result = subprocess.run(command, capture_output=True, check=False)
    if result.returncode:
        raise ffmpeg.FFmpegError(
            "Could not decode narration.",
            command=command,
            stderr=result.stderr.decode("utf-8", "replace"),
        )
    return np.frombuffer(result.stdout, dtype="<f4").copy()


async def prepare(
    spec: dict[str, Any], workdir: Path, cancelled: Callable[[], bool] = lambda: False
) -> Prepared:
    workdir.mkdir(parents=True, exist_ok=True)
    fps = int(spec.get("fps", 30))
    rate = int(spec.get("rate_percent", 0))
    cursor = float(spec.get("lead_in", 1.0))
    timed: list[TimedLine] = []
    clips: list[tuple[float, np.ndarray]] = []
    for index, line in enumerate(spec["lines"]):
        # A null speaker is an off-screen narrator: the cast reacts, no mouth moves.
        speaker = line.get("speaker")
        voice = line.get("voice") or (
            spec["cast"][speaker]["voice"] if speaker else spec["narrator_voice"]
        )
        result = await speech.synthesize(
            line["text"],
            voice,
            line.get("rate_percent", rate),
            workdir / f"line-{index}-{line['id']}",
            cancelled,
        )
        if index:
            cursor += float(line.get("gap", 0.6))
        start = cursor
        samples = _decode(result.path)
        # Edge pads each clip with near-silence; measure speech by its words.
        first = result.words[0].start
        last = result.words[-1].end
        trimmed = samples[
            int(max(0.0, first - 0.06) * SAMPLE_RATE) : int((last + 0.25) * SAMPLE_RATE)
        ]
        shift = start - max(0.0, first - 0.06)
        words = [TimedWord(w.text, w.start + shift, w.end + shift) for w in result.words]
        end = words[-1].end
        timed.append(
            TimedLine(line["id"], speaker, line["text"], words[0].start, end, words)
        )
        clips.append((start, trimmed))
        cursor = end
    duration = math.ceil((cursor + float(spec.get("tail", 1.5))) * fps) / fps
    mix = np.zeros(int(duration * SAMPLE_RATE) + SAMPLE_RATE, dtype=np.float32)
    for start, samples in clips:
        offset = int(start * SAMPLE_RATE)
        mix[offset : offset + len(samples)] += samples[: len(mix) - offset]
    mix = mix[: int(duration * SAMPLE_RATE)]
    audio = workdir / "dialogue.wav"
    with wave.open(str(audio), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(SAMPLE_RATE)
        output.writeframes((np.clip(mix, -1, 1) * 32767).astype("<i2").tobytes())
    frames = int(round(duration * fps))
    energy = speech_energy(mix, SAMPLE_RATE, fps, frames)
    mouths = {
        actor: mouth_tracks(
            [w for line in timed if line.speaker == actor for w in line.words], energy, fps
        )
        for actor in spec["cast"]
    }
    style = captions.get_style(spec.get("caption_style", "clean_lower"))
    style = replace(style, **spec.get("caption_overrides", {}))
    words = [Word(text=w.text, start=w.start, end=w.end) for line in timed for w in line.words]
    subtitle = captions.write_ass(workdir / "captions.ass", words, style, width=W, height=H)
    captions.write_srt(workdir / "captions.srt", words)
    return Prepared(spec, timed, duration, audio, subtitle, energy, mouths)


# ---------------------------------------------------------------- frame rendering


class ShotRenderer:
    def __init__(
        self,
        spec: dict[str, Any],
        lines: list[TimedLine],
        duration: float,
        energy: np.ndarray,
        mouths: dict[str, np.ndarray],
        size: tuple[int, int],
    ):
        self.spec = spec
        self.size = size
        self.fps = int(spec.get("fps", 30))
        self.duration = duration
        self.set = StreetSet(car=spec.get("prop", "car") == "car")
        cues = Cues(lines, duration)
        self.cast: list[tuple[str, Character, dict[str, Any], Performer]] = []
        for index, (actor, entry) in enumerate(spec["cast"].items()):
            acting = spec["acting"][actor]
            channels, forced = build_channels(
                acting["base"], acting.get("presets", {}), acting.get("keys", []), cues
            )
            performer = Performer(
                actor,
                channels,
                [line for line in lines if line.speaker == actor],
                mouths[actor],
                energy,
                self.fps,
                seed=index + 3,
            )
            performer.plan_life(duration, forced)
            self.cast.append((actor, Character(Look(**entry["look"])), entry, performer))
        camera = spec.get("camera", {})
        self.camera, _ = build_channels(
            {"zoom": 1.0, "fx": W / 2, "fy": H / 2, **camera.get("base", {})},
            {},
            [],
            cues,
            rig=False,
        )
        for key in camera.get("keys", []):
            self.camera.add(
                cues.resolve(key["at"]),
                key["set"],
                float(key.get("dur", 1.0)),
                key.get("ease", "inout"),
            )
        self.camera.finish()
        self.surface = skia.Surface(*size)

    def draw(self, t: float) -> skia.Image:
        c = self.surface.getCanvas()
        c.save()
        c.scale(self.size[0] / W, self.size[1] / H)
        cam = Camera(
            self.camera.value("zoom", t), self.camera.value("fx", t), self.camera.value("fy", t)
        )
        self.set.draw_back(c, t, cam)
        for _, character, entry, performer in self.cast:
            pose = performer.pose(t)
            c.saveLayer()
            c.save()
            cam.apply(c, 1.0)
            character.draw(c, pose, entry["x"], entry["y"], entry["scale"])
            c.restore()
            # Warm key light from the upper left, cooler shade toward the feet,
            # and the same moving leaf light that crosses the set.
            atop = skia.BlendMode.kSrcATop
            c.drawRect(
                skia.Rect.MakeWH(W, H),
                skia.Paint(
                    Shader=linear(
                        (0, 200), (500, H), ["#ffd391", "#ffd391", "#2c1626"], [0.2, 0.0, 0.32]
                    ),
                    BlendMode=atop,
                ),
            )
            paint = skia.Paint(BlendMode=atop)
            paint.setAlphaf(0.1)
            c.drawImage(
                self.set.dapples,
                -150 + math.sin(t * 0.45) * 22,
                -150 + math.cos(t * 0.37) * 14,
                skia.SamplingOptions(),
                paint,
            )
            c.restore()
        self.set.draw_front(c, t, cam)
        self.set.grade(c, t)
        c.restore()
        return self.surface.makeImageSnapshot()

    def frame_bytes(self, index: int) -> bytes:
        image = self.draw(index / self.fps)
        return image.toarray(colorType=skia.kRGBA_8888_ColorType).tobytes()


_worker: ShotRenderer | None = None


def _init_worker(payload: dict[str, Any]) -> None:
    global _worker
    _worker = ShotRenderer(**payload)


def _render_index(index: int) -> bytes:
    assert _worker is not None
    return _worker.frame_bytes(index)


def render(
    prepared: Prepared,
    output: Path,
    size: tuple[int, int],
    encoder: list[str],
    audio_filter: str | None,
    *,
    workers: int = 0,
    previews: dict[str, float] | None = None,
    on_progress: Callable[[float], None] = lambda value: None,
    cancelled: Callable[[], bool] = lambda: False,
) -> None:
    fps = int(prepared.spec.get("fps", 30))
    frames = int(round(prepared.duration * fps))
    payload = {
        "spec": prepared.spec,
        "lines": prepared.lines,
        "duration": prepared.duration,
        "energy": prepared.energy,
        "mouths": prepared.mouths,
        "size": size,
    }
    cwd, subtitle_name, fonts_name = ffmpeg.relative_filter_workspace(
        prepared.captions, captions.FONT_DIR
    )
    temporary = output.with_name(output.stem + ".partial.mp4")
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
        "rgba",
        "-video_size",
        f"{size[0]}x{size[1]}",
        "-framerate",
        str(fps),
        "-i",
        "pipe:0",
        "-i",
        str(prepared.audio.resolve()),
        "-vf",
        f"ass=filename={subtitle_name}:fontsdir={fonts_name},format=yuv420p",
        *(["-af", audio_filter] if audio_filter else []),
        "-t",
        f"{prepared.duration:.6f}",
        *encoder,
        "-c:a",
        "aac",
        "-ar",
        str(SAMPLE_RATE),
        "-ac",
        "2",
        "-b:a",
        "192k",
        "-movflags",
        "+faststart",
        str(temporary.resolve()),
    ]
    preview_frames = {round(t * fps): name for name, t in (previews or {}).items()}
    log_path = output.with_name(output.stem + ".encode.log")
    workers = workers or max(1, min(8, (multiprocessing.cpu_count() or 2) - 1))
    with log_path.open("w", encoding="utf-8") as errors:
        process = subprocess.Popen(
            command, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=errors, cwd=cwd
        )
        context = multiprocessing.get_context("spawn")
        pool = (
            context.Pool(workers, initializer=_init_worker, initargs=(payload,))
            if workers > 1
            else None
        )
        try:
            if pool is None:
                _init_worker(payload)
                stream = map(_render_index, range(frames))
            else:
                stream = pool.imap(_render_index, range(frames), chunksize=2)
            assert process.stdin is not None
            for index, data in enumerate(stream):
                if cancelled():
                    raise ffmpeg.Cancelled("Produção cancelada.")
                process.stdin.write(data)
                if index in preview_frames:
                    array = np.frombuffer(data, dtype=np.uint8).reshape(size[1], size[0], 4)
                    skia.Image.fromarray(array.copy(), colorType=skia.kRGBA_8888_ColorType).save(
                        str(output.with_name(f"{output.stem}.{preview_frames[index]}.png")),
                        skia.kPNG,
                    )
                if index % 10 == 0:
                    on_progress((index + 1) / frames)
            process.stdin.close()
            process.wait()
            if process.returncode:
                raise ffmpeg.FFmpegError(
                    "Toon encoding failed.",
                    command=command,
                    stderr=log_path.read_text(encoding="utf-8"),
                )
        except BaseException:
            process.kill()
            process.wait()
            raise
        finally:
            if pool is not None:
                pool.terminate()
                pool.join()
            if process.stdin is not None and not process.stdin.closed:
                process.stdin.close()
    temporary.replace(output)
    on_progress(1.0)


def contact_sheet(images: list[Path], target: Path, columns: int = 3, width: int = 360) -> None:
    """Small grid of preview frames for quick review."""
    loaded = [skia.Image.open(str(path)) for path in images]
    height = round(width * H / W)
    rows = math.ceil(len(loaded) / columns)
    surface = skia.Surface(columns * width + (columns + 1) * 12, rows * height + (rows + 1) * 12)
    c = surface.getCanvas()
    c.drawPaint(fill("#1d1612"))
    for index, image in enumerate(loaded):
        x = 12 + (index % columns) * (width + 12)
        y = 12 + (index // columns) * (height + 12)
        c.drawImageRect(
            image,
            skia.Rect.MakeXYWH(x, y, width, height),
            skia.SamplingOptions(skia.FilterMode.kLinear),
        )
    surface.makeImageSnapshot().save(str(target), skia.kPNG)


__all__ = ["Prepared", "ShotRenderer", "contact_sheet", "load_spec", "prepare", "render"]
