"""Where local models live, whether this machine can run them, and downloads."""

from __future__ import annotations

import gc
import importlib.util
import logging
import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .. import config, paths

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class ModelSpec:
    key: str
    label: str
    repo: str
    folder: str
    size_gb: float
    license: str
    patterns: tuple[str, ...]
    marker: str  # a file that exists only after a complete download


SDXL = ModelSpec(
    key="sdxl",
    label="SDXL base 1.0 (ilustrações)",
    repo="stabilityai/stable-diffusion-xl-base-1.0",
    folder="sdxl-base-1.0",
    size_gb=7.0,
    license="OpenRAIL++",
    patterns=(
        "model_index.json",
        "scheduler/*",
        "tokenizer/*",
        "tokenizer_2/*",
        "text_encoder/config.json",
        "text_encoder/model.fp16.safetensors",
        "text_encoder_2/config.json",
        "text_encoder_2/model.fp16.safetensors",
        "unet/config.json",
        "unet/diffusion_pytorch_model.fp16.safetensors",
        "vae/config.json",
        "vae/diffusion_pytorch_model.fp16.safetensors",
    ),
    marker="unet/diffusion_pytorch_model.fp16.safetensors",
)
WAN = ModelSpec(
    key="wan",
    label="Wan 2.2 TI2V-5B (animação)",
    repo="Wan-AI/Wan2.2-TI2V-5B-Diffusers",
    folder="wan2.2-ti2v-5b",
    size_gb=34.2,
    license="Apache 2.0",
    patterns=("*.json", "*.txt", "*.model", "**/*.json", "**/*.safetensors", "**/*.model", "**/*.txt"),
    marker="transformer/diffusion_pytorch_model-00005-of-00005.safetensors",
)
MODELS = {model.key: model for model in (SDXL, WAN)}
PYTHON_PACKAGES = ("torch", "diffusers", "transformers", "accelerate", "bitsandbytes")


def models_dir() -> Path:
    configured = config.load().local_ai.models_dir.strip()
    if configured:
        return Path(configured).expanduser()
    env = os.environ.get("AUTOCLIP_MODELS_DIR")
    return Path(env).expanduser() if env else paths.root() / "models" / "genai"


def model_path(model: ModelSpec) -> Path:
    return models_dir() / model.folder


def installed(model: ModelSpec) -> bool:
    return (model_path(model) / model.marker).is_file()


def status() -> dict:
    packages = {name: importlib.util.find_spec(name) is not None for name in PYTHON_PACKAGES}
    gpu = {"available": False, "name": None, "vram_gb": 0.0}
    if packages["torch"]:
        try:
            import torch

            if torch.cuda.is_available():
                props = torch.cuda.get_device_properties(0)
                gpu = {"available": True, "name": props.name, "vram_gb": round(props.total_memory / 1024**3, 1)}
        except Exception as exc:  # pragma: no cover - driver specific
            log.warning("Could not query CUDA: %s", exc)
    models = {
        model.key: {
            "label": model.label,
            "installed": installed(model),
            "size_gb": model.size_gb,
            "license": model.license,
            "path": str(model_path(model)),
        }
        for model in MODELS.values()
    }
    ready = all(packages.values()) and gpu["available"]
    return {
        "packages": packages,
        "gpu": gpu,
        "models": models,
        "models_dir": str(models_dir()),
        "images_ready": ready and models["sdxl"]["installed"],
        "video_ready": ready and models["wan"]["installed"],
    }


def download(model: ModelSpec, on_progress: Callable[[str], None] = lambda message: None) -> Path:
    """Fetch a model from Hugging Face into the models folder (resumable)."""
    from huggingface_hub import snapshot_download

    target = model_path(model)
    target.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
    on_progress(f"Baixando {model.label} ({model.size_gb:.0f} GB)…")
    snapshot_download(model.repo, local_dir=str(target), allow_patterns=list(model.patterns))
    if not installed(model):
        raise RuntimeError(f"O download de {model.label} terminou incompleto. Tente novamente.")
    return target


def free_gpu() -> None:
    gc.collect()
    try:
        import torch

        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except ImportError:
        pass


def require(model: ModelSpec) -> Path:
    missing = [name for name in PYTHON_PACKAGES if importlib.util.find_spec(name) is None]
    if missing:
        raise RuntimeError(
            "A IA local precisa das bibliotecas " + ", ".join(missing) + '. Instale com: pip install -e ".[local-ai]"'
        )
    import torch

    if not torch.cuda.is_available():
        raise RuntimeError("A IA local precisa de uma GPU NVIDIA com CUDA disponível.")
    if not installed(model):
        raise RuntimeError(f"Baixe o modelo {model.label} em Configurações → IA local.")
    return model_path(model)
