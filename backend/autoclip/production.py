"""Contracts for turning saved storyboards into narrated videos."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from .config import ExportSettings
from .creation import Creation

VOICES = {
    "pt-BR-AntonioNeural": ("pt-BR", "Antônio · português"),
    "pt-BR-FranciscaNeural": ("pt-BR", "Francisca · português"),
    "en-US-GuyNeural": ("en", "Guy · inglês"),
    "en-US-JennyNeural": ("en", "Jenny · inglês"),
    "es-ES-AlvaroNeural": ("es", "Álvaro · espanhol"),
    "es-ES-ElviraNeural": ("es", "Elvira · espanhol"),
}
DEFAULT_VOICES = {
    "pt-BR": "pt-BR-AntonioNeural",
    "en": "en-US-GuyNeural",
    "es": "es-ES-AlvaroNeural",
}
RenderStatus = Literal["queued", "running", "done", "failed", "cancelled"]


class RenderOptions(BaseModel):
    visual_mode: Literal["auto", "cartoon", "images", "cards"] = "auto"
    voice: str | None = Field(default=None, max_length=100)
    rate_percent: int = Field(default=0, ge=-30, le=30)
    resolution: Literal["720p", "1080p"] = "720p"
    caption_style: Literal["bold_pop", "karaoke_fill", "clean_lower", "boxed"] = "bold_pop"


class RenderCreateIn(BaseModel):
    revision: int = Field(ge=1)
    options: RenderOptions = Field(default_factory=RenderOptions)


class CreationRender(BaseModel):
    id: str
    creation_id: str
    revision: int
    snapshot: Creation = Field(exclude=True)
    export_settings: ExportSettings = Field(exclude=True)
    options: RenderOptions
    status: RenderStatus = "queued"
    stage: str = "Na fila"
    progress: float = 0
    error: str | None = None
    duration_s: float = 0
    created_at: str
    updated_at: str
