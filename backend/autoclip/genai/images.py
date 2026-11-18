"""Scene illustrations with SDXL, loaded once per production."""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path

from .runtime import SDXL, free_gpu, require

log = logging.getLogger(__name__)

STYLE = {
    "illustrated": (
        "warm 2D animated film still, painterly cel-shaded illustration, expressive characters, "
        "detailed background, golden hour light, soft shadows, vibrant harmonious colours, "
        "cinematic vertical composition, high quality"
    ),
    "motion_graphics": (
        "clean flat vector illustration, bold shapes, modern motion graphics frame, soft gradients, "
        "vertical composition, high quality"
    ),
}
NEGATIVE = (
    "text, letters, watermark, logo, signature, caption, deformed hands, extra fingers, extra limbs, "
    "distorted face, blurry, lowres, jpeg artifacts, photo, photorealistic, 3d render, ugly, cropped head"
)


def scene_prompt(style: str, art_direction: str, image_prompt: str) -> str:
    parts = [image_prompt.strip(), art_direction.strip(), STYLE.get(style, STYLE["illustrated"])]
    return ", ".join(part for part in parts if part)


def cache_key(*values: object) -> str:
    return hashlib.sha256(repr(values).encode("utf-8")).hexdigest()[:20]


class Illustrator:
    """SDXL with CPU offload: fits 8 GB GPUs at 768x1344 portrait."""

    WIDTH, HEIGHT = 768, 1344

    def __init__(self, quality: str = "fast"):
        import torch
        from diffusers import DPMSolverMultistepScheduler, StableDiffusionXLPipeline

        folder = require(SDXL)
        self.steps = 24 if quality == "fast" else 36
        self.torch = torch
        pipe = StableDiffusionXLPipeline.from_pretrained(
            str(folder), torch_dtype=torch.float16, variant="fp16", use_safetensors=True
        )
        pipe.scheduler = DPMSolverMultistepScheduler.from_config(
            pipe.scheduler.config, use_karras_sigmas=True
        )
        pipe.enable_model_cpu_offload()
        pipe.vae.enable_tiling()
        pipe.set_progress_bar_config(disable=True)
        self.pipe = pipe

    def render(self, prompt: str, seed: int, target: Path, on_step=None) -> Path:
        generator = self.torch.Generator("cpu").manual_seed(seed)

        def callback(pipe, step, timestep, kwargs):
            if on_step:
                on_step((step + 1) / self.steps)
            return kwargs

        image = self.pipe(
            prompt=prompt,
            negative_prompt=NEGATIVE,
            width=self.WIDTH,
            height=self.HEIGHT,
            num_inference_steps=self.steps,
            guidance_scale=6.5,
            generator=generator,
            callback_on_step_end=callback,
        ).images[0]
        target.parent.mkdir(parents=True, exist_ok=True)
        partial = target.with_suffix(".partial.png")
        image.save(partial)
        partial.replace(target)
        return target

    def close(self) -> None:
        del self.pipe
        free_gpu()
