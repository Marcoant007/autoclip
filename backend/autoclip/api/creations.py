"""Create, review and export original-video storyboards."""

from __future__ import annotations

import asyncio
from typing import Annotated

from fastapi import APIRouter, HTTPException, Path, Query, UploadFile
from fastapi.responses import FileResponse, Response

from .. import providers
from ..animation import direct_storyboard
from ..config import load as load_settings
from ..creation import (
    Creation,
    CreationDirectIn,
    CreationGenerateIn,
    CreationImportIn,
    CreationUpdateIn,
    generate_storyboard,
)
from ..db import creation_renders, creations
from ..db.models import new_id
from ..jobs.logs import read_logs
from ..jobs.queue import queue
from ..pipeline import export
from ..pipeline.creation_video import asset_directory, normalize_image, render_directory, video_path
from ..production import DEFAULT_VOICES, VOICES, CreationRender, RenderCreateIn
from ..providers import ProviderError

router = APIRouter(prefix="/api/creations", tags=["creations"])
AssetId = Annotated[str, Path(pattern=r"^[a-f0-9]{16}$")]


@router.post("", response_model=Creation, status_code=201)
async def generate_creation(payload: CreationGenerateIn) -> Creation:
    try:
        provider = await asyncio.to_thread(providers.build_provider, payload.provider)
        storyboard = await generate_storyboard(payload.brief, provider)
        if payload.animate:
            storyboard = await direct_storyboard(payload.brief, storyboard, provider)
    except ProviderError as exc:
        raise HTTPException(
            status_code=502, detail={"message": exc.args[0], "hint": exc.hint}
        ) from exc
    return await asyncio.to_thread(
        creations.create, payload.brief, storyboard, provider.name, provider.model
    )


@router.get("", response_model=list[Creation])
async def list_creations(limit: int = Query(default=25, ge=1, le=100)) -> list[Creation]:
    return await asyncio.to_thread(creations.list_recent, limit)


@router.post("/import", response_model=Creation, status_code=201)
async def import_creation(payload: CreationImportIn) -> Creation:
    # Downloads contain asset IDs, not image bytes. A new creation must never
    # inherit references to another creation's local files.
    for scene in payload.storyboard.scenes:
        scene.image_id = None
    return await asyncio.to_thread(
        creations.create, payload.brief, payload.storyboard, "imported", ""
    )


async def _get(creation_id: str) -> Creation:
    creation = await asyncio.to_thread(creations.get, creation_id)
    if creation is None:
        raise HTTPException(status_code=404, detail="Roteiro não encontrado.")
    return creation


@router.get("/{creation_id}", response_model=Creation)
async def get_creation(creation_id: str) -> Creation:
    return await _get(creation_id)


@router.post("/{creation_id}/animation", response_model=Creation)
async def plan_animation(creation_id: str, payload: CreationDirectIn) -> Creation:
    creation = await _get(creation_id)
    if creation.revision != payload.revision:
        raise HTTPException(
            status_code=409, detail="O roteiro foi alterado. Reabra a versão atual."
        )
    try:
        provider = await asyncio.to_thread(providers.build_provider, payload.provider)
        storyboard = await direct_storyboard(creation.brief, creation.storyboard, provider)
    except ProviderError as exc:
        raise HTTPException(
            status_code=502, detail={"message": exc.args[0], "hint": exc.hint}
        ) from exc
    updated = await asyncio.to_thread(creations.update, creation_id, storyboard, payload.revision)
    if updated is None:
        raise HTTPException(
            status_code=409, detail="O roteiro mudou durante o planejamento. Reabra a versão atual."
        )
    return updated


@router.put("/{creation_id}", response_model=Creation)
async def update_creation(creation_id: str, payload: CreationUpdateIn) -> Creation:
    await _get(creation_id)
    updated = await asyncio.to_thread(
        creations.update, creation_id, payload.storyboard, payload.revision
    )
    if updated is None:
        raise HTTPException(
            status_code=409,
            detail="Este roteiro foi atualizado em outra aba. Reabra-o antes de salvar novamente.",
        )
    return updated


@router.get("/{creation_id}/download")
async def download_creation(creation_id: str) -> Response:
    creation = await _get(creation_id)
    return Response(
        content=creation.model_dump_json(indent=2),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="roteiro-{creation.id}.json"'},
    )


@router.get("/{creation_id}/voices")
async def list_voices(creation_id: str) -> list[dict]:
    creation = await _get(creation_id)
    return [
        {"id": voice, "label": label, "default": voice == DEFAULT_VOICES[creation.brief.language]}
        for voice, (language, label) in VOICES.items()
        if language == creation.brief.language
    ]


@router.post("/{creation_id}/images", status_code=201)
async def upload_image(creation_id: str, file: UploadFile) -> dict:
    await _get(creation_id)
    try:
        data = await file.read(15 * 1024 * 1024 + 1)
    finally:
        await file.close()
    if len(data) > 15 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Use uma imagem de até 15 MB.")
    image_id = new_id()
    target = asset_directory(creation_id) / f"{image_id}.png"
    try:
        await asyncio.to_thread(normalize_image, data, target)
    except Exception as exc:
        target.unlink(missing_ok=True)
        raise HTTPException(
            status_code=415, detail="Imagem inválida. Use PNG, JPG ou WebP de até 20 megapixels."
        ) from exc
    return {"image_id": image_id}


@router.get("/{creation_id}/images/{image_id}")
async def get_image(creation_id: str, image_id: AssetId) -> FileResponse:
    await _get(creation_id)
    target = asset_directory(creation_id) / f"{image_id}.png"
    if not target.is_file():
        raise HTTPException(status_code=404, detail="Imagem não encontrada.")
    return FileResponse(target, media_type="image/png")


@router.post("/{creation_id}/renders", response_model=CreationRender, status_code=201)
async def create_render(creation_id: str, payload: RenderCreateIn) -> CreationRender:
    creation = await _get(creation_id)
    if creation.revision != payload.revision:
        raise HTTPException(
            status_code=409, detail="O roteiro foi alterado. Reabra a versão atual."
        )
    voice = payload.options.voice or DEFAULT_VOICES[creation.brief.language]
    if voice not in VOICES or VOICES[voice][0] != creation.brief.language:
        raise HTTPException(
            status_code=400, detail="Escolha uma voz compatível com o idioma do roteiro."
        )
    payload.options.voice = voice
    if payload.options.visual_mode == "cartoon" and not all(
        scene.animation is not None for scene in creation.storyboard.scenes
    ):
        raise HTTPException(
            status_code=400,
            detail="Planeje a animação de todas as cenas antes de renderizar o cartoon.",
        )
    if payload.options.visual_mode == "images" and not all(
        scene.image_id for scene in creation.storyboard.scenes
    ):
        raise HTTPException(
            status_code=400, detail="Envie uma imagem para cada cena antes de usar este modo."
        )
    if any(
        actor.voice and VOICES[actor.voice][0] != creation.brief.language
        for actor in creation.storyboard.cast
    ):
        raise HTTPException(
            status_code=400, detail="As vozes dos personagens precisam usar o idioma do roteiro."
        )
    for index, scene in enumerate(creation.storyboard.scenes):
        if (
            scene.image_id
            and not (asset_directory(creation_id) / f"{scene.image_id}.png").is_file()
        ):
            raise HTTPException(
                status_code=400,
                detail=f"Envie novamente a imagem da cena {index + 1} e salve o roteiro.",
            )
    try:
        render = await asyncio.to_thread(
            creation_renders.create, creation, payload.options, load_settings().export
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    queue.notify()
    return render


@router.get("/{creation_id}/renders", response_model=list[CreationRender])
async def list_renders(creation_id: str) -> list[CreationRender]:
    await _get(creation_id)
    return await asyncio.to_thread(creation_renders.list_recent, creation_id)


async def _render(creation_id: str, render_id: str) -> CreationRender:
    record = await asyncio.to_thread(creation_renders.get, render_id)
    if record is None or record.creation_id != creation_id:
        raise HTTPException(status_code=404, detail="Produção não encontrada.")
    return record


@router.get("/{creation_id}/renders/{render_id}", response_model=CreationRender)
async def get_render(creation_id: str, render_id: str) -> CreationRender:
    return await _render(creation_id, render_id)


@router.post("/{creation_id}/renders/{render_id}/cancel", response_model=CreationRender)
async def cancel_render(creation_id: str, render_id: str) -> CreationRender:
    await _render(creation_id, render_id)
    if not queue.cancel_creation_render(render_id):
        raise HTTPException(status_code=409, detail="Esta produção já foi finalizada.")
    return await _render(creation_id, render_id)


@router.post("/{creation_id}/renders/{render_id}/retry", response_model=CreationRender)
async def retry_render(creation_id: str, render_id: str) -> CreationRender:
    await _render(creation_id, render_id)
    if not await asyncio.to_thread(creation_renders.retry, render_id):
        raise HTTPException(
            status_code=409,
            detail="Só é possível retomar uma falha ou cancelamento, sem outra produção ativa.",
        )
    queue.reset_cancellation(render_id)
    queue.notify()
    return await _render(creation_id, render_id)


@router.get("/{creation_id}/renders/{render_id}/logs")
async def render_logs(creation_id: str, render_id: str) -> list[dict]:
    await _render(creation_id, render_id)
    return await asyncio.to_thread(read_logs, render_id)


@router.get("/{creation_id}/renders/{render_id}/media")
async def render_media(creation_id: str, render_id: str, download: bool = False) -> FileResponse:
    record = await _render(creation_id, render_id)
    target = video_path(record.id)
    if record.status != "done" or not target.is_file():
        raise HTTPException(status_code=409, detail="O vídeo ainda não está disponível.")
    filename = (
        f"{export.slugify_title(record.snapshot.storyboard.title) or record.id}.mp4"
        if download
        else None
    )
    return FileResponse(target, media_type="video/mp4", filename=filename)


@router.get("/{creation_id}/renders/{render_id}/subtitles")
async def render_subtitles(creation_id: str, render_id: str) -> FileResponse:
    record = await _render(creation_id, render_id)
    target = render_directory(record.id) / "captions.srt"
    if record.status != "done" or not target.is_file():
        raise HTTPException(status_code=409, detail="As legendas ainda não estão disponíveis.")
    return FileResponse(
        target, media_type="application/x-subrip", filename=f"legendas-{record.id}.srt"
    )


@router.get("/{creation_id}/renders/{render_id}/poster")
async def render_poster(creation_id: str, render_id: str) -> FileResponse:
    record = await _render(creation_id, render_id)
    target = render_directory(record.id) / "scene-0" / "visual.png"
    if record.status != "done" or not target.is_file():
        raise HTTPException(status_code=409, detail="A prévia ainda não está disponível.")
    return FileResponse(target, media_type="image/png")
