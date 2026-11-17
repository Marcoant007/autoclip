"""Edge online speech with measured word boundaries and per-scene resume."""

from __future__ import annotations

import asyncio
import hashlib
import html
import json
import logging
import math
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path

from . import ffmpeg
from .transcript import Word

log = logging.getLogger(__name__)


@dataclass
class Speech:
    path: Path
    duration_s: float
    words: list[Word]


async def synthesize(
    text: str, voice: str, rate: int, directory: Path, cancelled: Callable[[], bool]
) -> Speech:
    import edge_tts

    directory.mkdir(parents=True, exist_ok=True)
    audio = directory / "narration.mp3"
    metadata = directory / "speech.json"
    fingerprint = hashlib.sha256(
        json.dumps([text, voice, rate, "word-boundaries-v1"]).encode()
    ).hexdigest()
    if metadata.exists() and audio.exists():
        try:
            saved = json.loads(metadata.read_text(encoding="utf-8"))
            if saved["fingerprint"] == fingerprint:
                duration = ffmpeg.probe(audio).duration_s
                words = [Word(**word) for word in saved["words"]]
                _validate(duration, words)
                return Speech(audio, duration, words)
        except (ValueError, KeyError, TypeError, OSError, ffmpeg.FFmpegError):
            log.warning("Cached speech is incomplete; regenerating this scene.")

    partial = directory / "narration.partial.mp3"
    words = []
    try:
        async with asyncio.timeout(180):
            with partial.open("wb") as output:
                stream = edge_tts.Communicate(
                    text,
                    voice,
                    rate=f"{rate:+d}%",
                    boundary="WordBoundary",
                    connect_timeout=10,
                    receive_timeout=30,
                )
                async for chunk in stream.stream():
                    if cancelled():
                        raise ffmpeg.Cancelled("Produção cancelada.")
                    if chunk["type"] == "audio":
                        output.write(chunk["data"])
                    elif chunk["type"] == "WordBoundary":
                        words.append(
                            Word(
                                text=html.unescape(chunk["text"]),
                                start=chunk["offset"] / 10_000_000,
                                end=(chunk["offset"] + chunk["duration"]) / 10_000_000,
                            )
                        )
        duration = ffmpeg.probe(partial).duration_s
        _validate(duration, words)
        partial.replace(audio)
        staged_metadata = directory / "speech.partial.json"
        staged_metadata.write_text(
            json.dumps(
                {
                    "fingerprint": fingerprint,
                    "duration_s": duration,
                    "words": [asdict(word) for word in words],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        staged_metadata.replace(metadata)
        return Speech(audio, duration, words)
    except (ffmpeg.Cancelled, asyncio.CancelledError):
        raise
    except Exception as exc:
        raise RuntimeError(
            "Não foi possível gerar a narração online. Verifique a conexão e tente novamente. "
            f"Detalhe: {exc}"
        ) from exc
    finally:
        partial.unlink(missing_ok=True)


def _validate(duration: float, words: list[Word]) -> None:
    if duration <= 0 or not math.isfinite(duration) or not words:
        raise ValueError("O serviço não retornou áudio e tempos de palavras válidos.")
    previous_start = -1.0
    for word in words:
        if (
            not math.isfinite(word.start)
            or not math.isfinite(word.end)
            or word.start < 0
            or word.start < previous_start
            or word.end > duration + 0.25
            or word.end <= word.start
        ):
            raise ValueError("O serviço retornou tempos de palavras incompatíveis com o áudio.")
        previous_start = word.start
