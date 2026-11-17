"""Durable render queue, with immutable snapshots of script and options."""

from __future__ import annotations

import sqlite3

from ..config import ExportSettings
from ..creation import Creation
from ..production import CreationRender, RenderOptions, RenderStatus
from . import connection
from .models import new_id, utcnow


def create(snapshot: Creation, options: RenderOptions, settings: ExportSettings) -> CreationRender:
    now = utcnow()
    with connection() as conn:
        # Check revision and pending work in the same write transaction. Two tabs
        # must not enqueue duplicate renders or render an already stale revision.
        conn.execute("BEGIN IMMEDIATE")
        current = conn.execute(
            "SELECT revision FROM creations WHERE id = ?", (snapshot.id,)
        ).fetchone()
        if current is None or current["revision"] != snapshot.revision:
            raise ValueError(
                "O roteiro foi alterado. Reabra a versão atual antes de gerar o vídeo."
            )
        active = conn.execute(
            "SELECT id FROM creation_renders WHERE creation_id = ? "
            "AND status IN ('queued','running')",
            (snapshot.id,),
        ).fetchone()
        if active:
            raise ValueError("Já existe um vídeo desta produção na fila ou em processamento.")
        render = CreationRender(
            id=new_id(),
            creation_id=snapshot.id,
            revision=snapshot.revision,
            snapshot=snapshot,
            export_settings=settings,
            options=options,
            created_at=now,
            updated_at=now,
        )
        conn.execute(
            """INSERT INTO creation_renders
               (id, creation_id, revision, snapshot_json, options_json, export_json,
                status, stage, progress, error, duration_s, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, 'queued', 'Na fila', 0, NULL, 0, ?, ?)""",
            (
                render.id,
                snapshot.id,
                snapshot.revision,
                snapshot.model_dump_json(),
                options.model_dump_json(),
                settings.model_dump_json(),
                now,
                now,
            ),
        )
    return render


def _from_row(row: sqlite3.Row) -> CreationRender:
    return CreationRender(
        **{
            key: row[key]
            for key in (
                "id",
                "creation_id",
                "revision",
                "status",
                "stage",
                "progress",
                "error",
                "duration_s",
                "created_at",
                "updated_at",
            )
        },
        snapshot=Creation.model_validate_json(row["snapshot_json"]),
        options=RenderOptions.model_validate_json(row["options_json"]),
        export_settings=ExportSettings.model_validate_json(row["export_json"]),
    )


def get(render_id: str) -> CreationRender | None:
    with connection() as conn:
        row = conn.execute("SELECT * FROM creation_renders WHERE id = ?", (render_id,)).fetchone()
    return _from_row(row) if row else None


def list_recent(creation_id: str, limit: int = 10) -> list[CreationRender]:
    with connection() as conn:
        rows = conn.execute(
            "SELECT * FROM creation_renders WHERE creation_id = ? ORDER BY rowid DESC LIMIT ?",
            (creation_id, limit),
        ).fetchall()
    return [_from_row(row) for row in rows]


def next_queued() -> CreationRender | None:
    with connection() as conn:
        row = conn.execute(
            "SELECT * FROM creation_renders WHERE status = 'queued' "
            "ORDER BY created_at, rowid LIMIT 1"
        ).fetchone()
    return _from_row(row) if row else None


def update(
    render_id: str,
    *,
    status: RenderStatus | None = None,
    stage: str | None = None,
    progress: float | None = None,
    error: str | None = None,
    duration_s: float | None = None,
) -> None:
    fields = {
        key: value
        for key, value in {
            "status": status,
            "stage": stage,
            "progress": progress,
            "duration_s": duration_s,
        }.items()
        if value is not None
    }
    fields.update(error=error, updated_at=utcnow())
    with connection() as conn:
        conn.execute(
            f"UPDATE creation_renders SET {', '.join(f'{key} = ?' for key in fields)} WHERE id = ?",
            (*fields.values(), render_id),
        )


def retry(render_id: str) -> bool:
    with connection() as conn:
        # The partial unique index also prevents a retry while a newer render
        # of the same creation is active.
        try:
            cursor = conn.execute(
                """UPDATE creation_renders SET status = 'queued', stage = 'Na fila',
                   error = NULL, progress = 0, updated_at = ?
                   WHERE id = ? AND status IN ('failed', 'cancelled')""",
                (utcnow(), render_id),
            )
        except sqlite3.IntegrityError:
            return False
    return cursor.rowcount > 0


def requeue_interrupted() -> None:
    with connection() as conn:
        conn.execute(
            "UPDATE creation_renders SET status = 'queued', stage = 'Retomando', "
            "error = NULL WHERE status = 'running'"
        )


def queued_count() -> int:
    with connection() as conn:
        return conn.execute(
            "SELECT count(*) FROM creation_renders WHERE status = 'queued'"
        ).fetchone()[0]
