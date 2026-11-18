"""Prepare per-scene artwork for a render: illustrate, then animate, with caching.

Each model is loaded once per production and released afterwards, so an 8 GB
GPU only ever holds one of them. Outputs are cached by content hash inside the
creation's asset folder: retries and new revisions reuse finished scenes.
"""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .. import config
from ..pipeline import ffmpeg
from . import runtime
from .images import Illustrator, cache_key, scene_prompt

log = logging.getLogger(__name__)


@dataclass
class SceneArt:
    image: Path
    clip: Path | None


def _seed(creation_id: str, index: int) -> int:
    return int(hashlib.sha256(f"{creation_id}:{index}".encode()).hexdigest()[:8], 16)


def motion_prompt(scene, art_direction: str) -> str:
    base = scene.image_prompt.strip() or scene.visual_description.strip()
    speaking = (
        f"{scene.speaker} is talking with natural lip and head movement and expressive hand gestures"
        if scene.speaker
        else "the characters react naturally with small gestures and expressions"
    )
    return (
        f"{base}. {speaking}. Gentle living motion: blinking, breathing, hair and leaves "
        f"moving in a light breeze, soft drifting light. Stable camera, smooth animation. "
        f"{art_direction.strip()}"
    )


def prepare_scene_art(
    creation,
    asset_dir: Path,
    *,
    emit: Callable[[str, float], None],
    cancelled: Callable[[], bool],
) -> list[SceneArt]:
    settings = config.load().local_ai
    storyboard = creation.storyboard
    style = creation.brief.visual_style
    folder = asset_dir / "ai"
    folder.mkdir(parents=True, exist_ok=True)
    total = len(storyboard.scenes)

    images: list[Path] = []
    todo: list[tuple[int, str, int, Path]] = []
    for index, scene in enumerate(storyboard.scenes):
        if scene.image_id:
            images.append(asset_dir / f"{scene.image_id}.png")
            continue
        prompt = scene_prompt(style, storyboard.art_direction, scene.image_prompt or scene.visual_description)
        seed = _seed(creation.id, index)
        target = folder / f"img-{cache_key(prompt, seed, settings.quality, 'sdxl-v1')}.png"
        images.append(target)
        if not target.is_file():
            todo.append((index, prompt, seed, target))

    if todo:
        emit("Carregando o modelo de ilustração (IA local)", 0.0)
        illustrator = Illustrator(settings.quality)
        try:
            for done, (index, prompt, seed, target) in enumerate(todo):
                if cancelled():
                    raise ffmpeg.Cancelled("Produção cancelada.")
                log.info("Ilustrando a cena %d/%d com SDXL.", index + 1, total)

                def step(value, done=done, index=index):
                    emit(f"Ilustrando cena {index + 1} de {total} (IA local)", (done + value) / len(todo))

                illustrator.render(prompt, seed, target, on_step=step)
        finally:
            illustrator.close()

    clips: list[Path | None] = [None] * total
    if settings.animate and runtime.installed(runtime.WAN):
        from .video import Animator

        jobs = []
        for index, scene in enumerate(storyboard.scenes):
            image = images[index]
            digest = hashlib.sha256(image.read_bytes()).hexdigest()[:16]
            prompt = motion_prompt(scene, storyboard.art_direction)
            target = folder / f"clip-{cache_key(digest, prompt, settings.quality, 'wan22-v1')}.mp4"
            clips[index] = target
            if not target.is_file():
                jobs.append((index, prompt, image, target))
        if jobs:
            emit("Carregando o modelo de animação (IA local)", 0.0)
            animator = Animator(settings.quality, [prompt for _, prompt, _, _ in jobs])
            try:
                for done, (index, prompt, image, target) in enumerate(jobs):
                    if cancelled():
                        raise ffmpeg.Cancelled("Produção cancelada.")
                    log.info("Animando a cena %d/%d com Wan 2.2.", index + 1, total)

                    def step(value, done=done, index=index):
                        emit(f"Animando cena {index + 1} de {total} (IA local)", (done + value) / len(jobs))

                    animator.render(prompt, image, target, seed=_seed(creation.id, index), on_step=step, cancelled=cancelled)
            finally:
                animator.close()
    elif settings.animate:
        log.warning("Wan 2.2 não está instalado; usando movimento de câmera sobre as ilustrações.")
    return [SceneArt(image, clip) for image, clip in zip(images, clips, strict=True)]
