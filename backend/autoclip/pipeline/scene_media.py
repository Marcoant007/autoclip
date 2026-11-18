"""Validated scene uploads; moving images become silent, browser-playable MP4."""

from __future__ import annotations

import io
import math
import subprocess
import tempfile
import warnings
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError

from .. import paths
from . import ffmpeg

MAX_UPLOAD_BYTES = 50 * 1024 * 1024
MAX_IMAGE_BYTES = 15 * 1024 * 1024


class SceneMediaError(ValueError):
    """An actionable upload failure with an appropriate HTTP status."""

    def __init__(self, message: str, *, status_code: int = 422, hint: str = ""):
        super().__init__(message)
        self.status_code = status_code
        self.hint = hint


def asset_directory(creation_id: str) -> Path:
    return paths.root() / "creation-assets" / creation_id


def asset_path(creation_id: str, asset_id: str) -> Path:
    base = asset_directory(creation_id) / asset_id
    video = base.with_suffix(".mp4")
    return video if video.is_file() else base.with_suffix(".png")


def normalize_image(data: bytes, target: Path) -> None:
    """Normalize a still raster image, stripping metadata and capping dimensions."""
    with warnings.catch_warnings():
        warnings.simplefilter("error", Image.DecompressionBombWarning)
        with Image.open(io.BytesIO(data), formats=["JPEG", "PNG", "WEBP", "GIF"]) as image:
            if image.width * image.height > 20_000_000:
                raise ValueError("Use uma imagem de até 20 megapixels.")
            image = ImageOps.exif_transpose(image).convert("RGB")
            image.thumbnail((2160, 3840), Image.Resampling.LANCZOS)
            target.parent.mkdir(parents=True, exist_ok=True)
            image.save(target, format="PNG")


def _run(args: list[str]) -> None:
    command = [ffmpeg.ffmpeg_path(), "-nostdin", "-hide_banner", "-loglevel", "error", "-y", *args]
    result = subprocess.run(
        command,
        capture_output=True,
        timeout=90,
    )
    if result.returncode:
        raise ffmpeg.FFmpegError(
            "Não foi possível decodificar a mídia enviada.",
            command=command,
            stderr=result.stderr.decode("utf-8", errors="replace"),
        )


def _raster_animation_duration(data: bytes) -> float:
    """Read frame timing when a raster demuxer has no container duration (e.g. WebP)."""
    elapsed = 0.0
    with Image.open(io.BytesIO(data), formats=["PNG", "WEBP", "GIF"]) as image:
        for index in range(image.n_frames):
            try:
                image.seek(index)
                # Pillow populates animated WebP duration only after decoding the frame.
                image.load()
            except (OSError, EOFError) as exc:
                raise SceneMediaError(
                    "A animação contém um quadro incompleto ou inválido."
                ) from exc
            duration_ms = float(image.info.get("duration") or 100)
            if not math.isfinite(duration_ms) or duration_ms < 0:
                raise SceneMediaError("A animação contém um tempo de quadro inválido.")
            elapsed += duration_ms / 1000
            if elapsed > 180:
                raise SceneMediaError("Use uma animação de até 180 segundos.")
    return elapsed


def save_visual(data: bytes, base: Path) -> str:
    """Return image/video after content validation, independent of upload filename/MIME."""
    if not data:
        raise SceneMediaError("O arquivo enviado está vazio.", status_code=400)
    try:
        return _save_visual(data, base)
    except UnidentifiedImageError as exc:
        raise SceneMediaError(
            "Não foi possível reconhecer o formato do arquivo enviado.",
            status_code=415,
            hint="Envie o arquivo original em PNG, JPG, WebP, GIF ou MP4. "
            "Trocar apenas a extensão do nome não converte o formato.",
        ) from exc
    except (Image.DecompressionBombWarning, Image.DecompressionBombError) as exc:
        raise SceneMediaError(
            "A imagem ultrapassa o limite de resolução.", status_code=413
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise SceneMediaError(
            "A conversão da mídia ultrapassou o tempo disponível.",
            status_code=504,
            hint="Tente um trecho menor ou exporte o vídeo em MP4 H.264.",
        ) from exc
    except ffmpeg.FFmpegError as exc:
        if not exc.command:
            raise SceneMediaError(
                "FFmpeg ou ffprobe não está disponível no servidor.",
                status_code=503,
                hint="Confira a instalação com autoclip doctor e reinicie o AutoClip.",
            ) from exc
        raise SceneMediaError(
            "Não foi possível ler ou converter a animação enviada.",
            hint="Confira se o arquivo abre por completo em um player. "
            "O terminal do AutoClip contém o erro detalhado do conversor.",
        ) from exc


def _save_visual(data: bytes, base: Path) -> str:
    is_mp4 = len(data) >= 12 and data[4:8] == b"ftyp"
    image_format = ""
    if not is_mp4:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data), formats=["PNG", "JPEG", "WEBP", "GIF"]) as image:
                if image.width * image.height > 20_000_000:
                    raise SceneMediaError("Use uma imagem de até 20 megapixels.", status_code=413)
                animated = getattr(image, "is_animated", False)
                image_format = image.format or ""
                if not animated:
                    if len(data) > MAX_IMAGE_BYTES:
                        raise SceneMediaError(
                            "Use uma imagem estática de até 15 MB.", status_code=413
                        )
                    normalize_image(data, base.with_suffix(".png"))
                    return "image"
    if len(data) > MAX_UPLOAD_BYTES:
        raise SceneMediaError("Use um GIF ou MP4 de até 50 MB.", status_code=413)
    base.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="upload-", dir=base.parent) as workspace:
        source = Path(workspace) / ("source.mp4" if is_mp4 else f"source.{image_format.lower()}")
        source.write_bytes(data)
        info = ffmpeg.probe(source)
        duration_s = info.duration_s
        if image_format and (not math.isfinite(duration_s) or duration_s <= 0):
            duration_s = _raster_animation_duration(data)
        if (
            not info.has_video
            or not math.isfinite(duration_s)
            or not 0 < duration_s <= 180
            or not info.width
            or not info.height
            or info.width * info.height > 20_000_000
        ):
            raise SceneMediaError("Use um GIF ou MP4 de até 180 segundos e 20 megapixels.")
        staged = Path(workspace) / "normalized.mp4"
        _run(
            [
                "-protocol_whitelist",
                "file,pipe",
                "-i",
                str(source),
                "-map",
                "0:v:0",
                "-an",
                "-sn",
                "-dn",
                "-map_metadata",
                "-1",
                "-vf",
                "scale=w='min(1080,iw)':h='min(1920,ih)':"
                "force_original_aspect_ratio=decrease:force_divisible_by=2,"
                "fps=30,setsar=1,format=yuv420p",
                "-t",
                "180",
                "-c:v",
                "libx264",
                "-preset",
                "veryfast",
                "-crf",
                "20",
                "-movflags",
                "+faststart",
                str(staged),
            ]
        )
        output_info = ffmpeg.probe(staged)
        if not output_info.has_video or output_info.duration_s <= 0:
            raise SceneMediaError("O arquivo não contém uma animação válida.")
        poster = Path(workspace) / "poster.png"
        _run(["-i", str(staged), "-frames:v", "1", "-update", "1", str(poster)])
        poster.replace(base.with_suffix(".poster.png"))
        staged.replace(base.with_suffix(".mp4"))
    return "video"
