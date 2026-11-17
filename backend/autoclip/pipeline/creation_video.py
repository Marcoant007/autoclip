"""Narrated scene rendering using existing FFmpeg, encoder and caption helpers."""

from __future__ import annotations

import logging
import math
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

import pysubs2
from PIL import Image, ImageDraw, ImageFont, ImageOps

from .. import paths
from ..creation import Scene
from ..db import creation_renders
from ..jobs.logs import capture_job_logs
from ..production import DEFAULT_VOICES, CreationRender
from . import captions, cartoon, export, ffmpeg, speech
from .transcript import Word

log = logging.getLogger(__name__)
FPS = 30


def asset_directory(creation_id: str) -> Path:
    return paths.root() / "creation-assets" / creation_id


def render_directory(render_id: str) -> Path:
    return paths.work_dir() / f"creation-{render_id}"


def video_path(render_id: str) -> Path:
    return render_directory(render_id) / "video.mp4"


def normalize_image(data: bytes, target: Path) -> None:
    """Decode only raster formats, remove metadata and cap decoded dimensions."""
    import io
    import warnings

    with warnings.catch_warnings():
        warnings.simplefilter("error", Image.DecompressionBombWarning)
        with Image.open(io.BytesIO(data), formats=["JPEG", "PNG", "WEBP"]) as image:
            if image.width * image.height > 20_000_000:
                raise ValueError("Use uma imagem de até 20 megapixels.")
            image = ImageOps.exif_transpose(image).convert("RGB")
            image.thumbnail((2160, 3840), Image.Resampling.LANCZOS)
            target.parent.mkdir(parents=True, exist_ok=True)
            image.save(target, format="PNG")


def _wrap(draw: ImageDraw.ImageDraw, text: str, font, width: int, max_lines: int) -> list[str]:
    # Break long tokens too: an URL or unspaced headline must not cross the frame.
    lines: list[str] = []
    line = ""
    for char in " ".join(text.split()):
        if draw.textlength(line + char, font=font) > width and line:
            if " " in line:
                head, tail = line.rsplit(" ", 1)
                lines.append(head)
                line = tail + char
            else:
                lines.append(line)
                line = char
        else:
            line += char
    if line:
        lines.append(line)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] = lines[-1].rstrip(" .,;") + "…"
    return lines


def create_card(
    scene: Scene, title: str, index: int, total: int, target: Path, size: tuple[int, int]
) -> None:
    """Local motion-graphics artwork; uploaded illustrations can replace it."""
    width, height = size
    image = Image.new("RGB", size, "#0b171b")
    draw = ImageDraw.Draw(image)
    accent = ["#88d6bd", "#f2c078", "#93b8ed"][index % 3]
    unit = width / 720
    margin = round(width * 0.09)
    for x in range(0, width, max(1, round(60 * unit))):
        draw.line((x, 0, x, height), fill="#13252b", width=1)
    for y in range(0, height, max(1, round(60 * unit))):
        draw.line((0, y, width, y), fill="#13252b", width=1)
    font = ImageFont.truetype(str(captions.FONT_DIR / "Inter-Variable.ttf"), round(26 * unit))
    heading_font = ImageFont.truetype(
        str(captions.FONT_DIR / "Anton-Regular.ttf"), round(65 * unit)
    )
    draw.rounded_rectangle(
        (margin, height * 0.08, width - margin, height * 0.085), radius=3, fill=accent
    )
    draw.text((margin, height * 0.12), f"{index + 1:02d} / {total:02d}", font=font, fill=accent)
    small = ImageFont.truetype(str(captions.FONT_DIR / "Inter-Variable.ttf"), round(23 * unit))
    for row, line in enumerate(_wrap(draw, title, small, width - 2 * margin, 2)):
        draw.text((margin, height * 0.18 + row * 32 * unit), line, font=small, fill="#adbdc4")
    headline = scene.on_screen_text.strip() or scene.narration.split(".")[0]
    for row, line in enumerate(_wrap(draw, headline, heading_font, width - 2 * margin, 5)):
        draw.text(
            (margin, height * 0.31 + row * 88 * unit), line, font=heading_font, fill="#f4f1e8"
        )
    # Original geometric motifs provide camera-motion cues without exposing
    # prompts or animation instructions to the finished video's audience.
    cx, cy, radius = width * 0.72, height * 0.82, width * 0.22
    for scale in (1, 0.7, 0.4):
        r = radius * scale
        draw.ellipse(
            (cx - r, cy - r, cx + r, cy + r), outline=accent, width=max(1, round(3 * unit))
        )
    draw.line((margin, height * 0.9, width - margin, height * 0.9), fill="#32484d", width=2)
    target.parent.mkdir(parents=True, exist_ok=True)
    image.save(target)


def _safe_ass(text: str) -> str:
    return text.replace("\\", "＼").replace("{", "｛").replace("}", "｝").replace("\n", " ")


def render_scene(
    scene: Scene,
    audio: speech.Speech,
    image: Path,
    output: Path,
    size: tuple[int, int],
    style_key: str,
    settings,
    cancelled,
    on_progress,
    *,
    image_overlay: bool = False,
) -> float:
    width, height = size
    duration = math.ceil(audio.duration_s * FPS) / FPS
    frames = max(1, round(duration * FPS))
    style = replace(captions.get_style(style_key), margin_v_ratio=0.15, size_ratio=0.045)
    words = [replace(word, text=_safe_ass(word.text)) for word in audio.words]
    subs = captions.build_ass(words, style, width=width, height=height)
    if image_overlay and scene.on_screen_text.strip():
        overlay = pysubs2.SSAStyle(
            fontname="Inter",
            fontsize=height * 0.038,
            alignment=pysubs2.Alignment.TOP_CENTER,
            marginv=round(height * 0.12),
            marginl=round(width * 0.1),
            marginr=round(width * 0.1),
            primarycolor=pysubs2.Color(255, 255, 255),
            outline=2,
            shadow=1,
        )
        subs.styles["Heading"] = overlay
        subs.events.append(
            pysubs2.SSAEvent(
                start=0,
                end=round(duration * 1000),
                text=_safe_ass(scene.on_screen_text),
                style="Heading",
            )
        )
    subtitle_path = output.parent / "captions.ass"
    subs.save(str(subtitle_path), encoding="utf-8")
    cwd, subtitle_name, fonts_name = ffmpeg.relative_filter_workspace(
        subtitle_path, captions.FONT_DIR
    )
    direction = "on" if int(output.parent.name.split("-")[-1]) % 2 == 0 else f"{frames}-on"
    filters = (
        f"scale={width * 2}:{height * 2}:force_original_aspect_ratio=increase,"
        f"crop={width * 2}:{height * 2},"
        f"zoompan=z='1.02+0.06*({direction})/{frames}':"
        f"x='iw/2-iw/zoom/2':y='ih/2-ih/zoom/2':d={frames}:s={width}x{height}:fps={FPS},"
        f"setsar=1,format=yuv420p,ass=filename={subtitle_name}:fontsdir={fonts_name},"
        f"fade=t=in:st=0:d=0.15,fade=t=out:st={max(0, duration - 0.15):.4f}:d=0.15"
    )
    temporary = output.with_name("scene.partial.mp4")
    ffmpeg.run(
        [
            "-i",
            str(image.resolve()),
            "-i",
            str(audio.path.resolve()),
            "-vf",
            filters,
            "-af",
            "apad",
            "-t",
            f"{duration:.6f}",
            *export.encoder_args(settings),
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
        ],
        total_duration_s=duration,
        on_progress=on_progress,
        cancelled=cancelled,
        cwd=cwd,
    )
    temporary.replace(output)
    return duration


def render_cartoon_scene(
    scene, cast, audio, output, size, style_key, settings, cancelled, on_progress
) -> float:
    if scene.animation is None:
        raise ValueError("A cena precisa de um plano de animação para usar o modo cartoon.")
    duration = math.ceil(audio.duration_s * FPS) / FPS
    style = replace(captions.get_style(style_key), margin_v_ratio=0.08, size_ratio=0.038)
    words = [replace(word, text=_safe_ass(word.text)) for word in audio.words]
    subtitle_path = output.parent / "captions.ass"
    captions.write_ass(subtitle_path, words, style, width=size[0], height=size[1])
    ffmpeg.relative_filter_workspace(subtitle_path, captions.FONT_DIR)
    cartoon.render_cartoon(
        scene.animation,
        cast,
        audio.path,
        audio.words,
        output,
        size,
        duration,
        export.encoder_args(settings),
        cancelled,
        on_progress,
        FPS,
    )
    return duration


class CreationVideoRunner:
    def __init__(self, render: CreationRender, cancelled: Callable[[], bool]):
        self.render = render
        self.cancelled = cancelled

    def emit(self, stage: str, progress: float):
        creation_renders.update(self.render.id, stage=stage, progress=round(progress, 4))

    async def run(self) -> None:
        with capture_job_logs(self.render.id):
            creation_renders.update(self.render.id, status="running", stage="Preparando produção")
            try:
                await self._run()
            except ffmpeg.Cancelled:
                creation_renders.update(self.render.id, status="cancelled", stage="Cancelado")
                log.info("Produção cancelada.")
            except Exception as exc:
                creation_renders.update(
                    self.render.id, status="failed", stage="Falha na produção", error=str(exc)
                )
                log.exception("Falha ao produzir o vídeo.")
            else:
                creation_renders.update(
                    self.render.id, status="done", stage="Vídeo pronto", progress=1
                )

    async def _run(self) -> None:
        record = self.render
        creation = record.snapshot
        root = render_directory(record.id)
        root.mkdir(parents=True, exist_ok=True)
        size = (720, 1280) if record.options.resolution == "720p" else (1080, 1920)
        voice = record.options.voice or DEFAULT_VOICES[creation.brief.language]
        scenes = creation.storyboard.scenes
        all_words: list[Word] = []
        elapsed = 0.0
        segments = []
        for index, scene in enumerate(scenes):
            if self.cancelled():
                raise ffmpeg.Cancelled("Produção cancelada.")
            directory = root / f"scene-{index}"
            directory.mkdir(exist_ok=True)
            self.emit(f"Narração · cena {index + 1} de {len(scenes)}", 0.9 * index / len(scenes))
            log.info("Gerando narração da cena %d/%d.", index + 1, len(scenes))
            is_cartoon = record.options.visual_mode == "cartoon" or (
                record.options.visual_mode == "auto" and scene.animation is not None
            )
            scene_voice = voice
            if is_cartoon and scene.animation and scene.animation.speaker:
                speaker = next(
                    actor
                    for actor in creation.storyboard.cast
                    if actor.id == scene.animation.speaker
                )
                scene_voice = speaker.voice or voice
            audio = await speech.synthesize(
                scene.narration, scene_voice, record.options.rate_percent, directory, self.cancelled
            )
            image = directory / "visual.png"
            if is_cartoon:
                pass  # The puppet renderer creates its own scene and poster.
            elif scene.image_id and record.options.visual_mode != "cards":
                source_image = asset_directory(creation.id) / f"{scene.image_id}.png"
                if not source_image.exists():
                    raise RuntimeError(
                        f"A imagem da cena {index + 1} não foi encontrada. "
                        "Envie-a novamente e crie outro vídeo."
                    )
                if not image.exists():
                    image.write_bytes(source_image.read_bytes())
            elif not image.exists():
                create_card(scene, creation.storyboard.title, index, len(scenes), image, size)
            segment = directory / "scene.mp4"
            duration = math.ceil(audio.duration_s * FPS) / FPS
            stage = "Animando personagens" if is_cartoon else "Compondo imagens e cartelas"
            self.emit(
                f"{stage} · cena {index + 1} de {len(scenes)}", 0.9 * (index + 0.2) / len(scenes)
            )
            if not segment.exists():

                def progress(value, i=index, label=stage):
                    self.emit(
                        f"{label} · cena {i + 1} de {len(scenes)}",
                        0.9 * (i + 0.2 + 0.8 * value) / len(scenes),
                    )

                if is_cartoon:
                    duration = render_cartoon_scene(
                        scene,
                        creation.storyboard.cast,
                        audio,
                        segment,
                        size,
                        record.options.caption_style,
                        record.export_settings,
                        self.cancelled,
                        progress,
                    )
                else:
                    duration = render_scene(
                        scene,
                        audio,
                        image,
                        segment,
                        size,
                        record.options.caption_style,
                        record.export_settings,
                        self.cancelled,
                        progress,
                        image_overlay=bool(scene.image_id),
                    )
            segments.append(segment)
            all_words.extend(
                replace(word, start=word.start + elapsed, end=word.end + elapsed)
                for word in audio.words
            )
            elapsed += duration
        if self.cancelled():
            raise ffmpeg.Cancelled("Produção cancelada.")
        captions.write_srt(root / "captions.srt", all_words)
        # Names are generated, relative and immutable; user-controlled paths never
        # enter the concat manifest or the filtergraph.
        manifest = root / "scenes.txt"
        manifest.write_text(
            "\n".join(f"file 'scene-{i}/scene.mp4'" for i in range(len(segments))), encoding="utf-8"
        )
        self.emit("Montando vídeo e normalizando áudio", 0.9)
        temporary = root / "video.partial.mp4"
        ffmpeg.run(
            [
                "-f",
                "concat",
                "-safe",
                "1",
                "-i",
                str(manifest.resolve()),
                "-c:v",
                "copy",
                "-af",
                export.build_audio_filtergraph(record.export_settings),
                "-c:a",
                "aac",
                "-b:a",
                "192k",
                "-ar",
                "48000",
                "-movflags",
                "+faststart",
                str(temporary.resolve()),
            ],
            total_duration_s=elapsed,
            on_progress=lambda p: self.emit("Montando vídeo", 0.9 + 0.09 * p),
            cancelled=self.cancelled,
            cwd=root,
        )
        info = ffmpeg.probe(temporary)
        if not info.has_video or not info.has_audio or info.duration_s <= 0:
            raise RuntimeError("O arquivo final não contém áudio e vídeo válidos.")
        temporary.replace(video_path(record.id))
        creation_renders.update(record.id, duration_s=info.duration_s)
        log.info("Vídeo pronto: %.2f segundos, %d cenas.", info.duration_s, len(scenes))
