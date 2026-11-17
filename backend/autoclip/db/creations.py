"""Persist original-video briefs and their editable storyboards."""

from __future__ import annotations

from ..creation import Creation, CreationBrief, Storyboard
from . import connection
from .models import new_id, utcnow


def create(brief: CreationBrief, storyboard: Storyboard, provider: str, model: str) -> Creation:
    now = utcnow()
    creation = Creation(
        id=new_id(),
        brief=brief,
        storyboard=storyboard,
        provider=provider,
        model=model,
        created_at=now,
        updated_at=now,
    )
    with connection() as conn:
        conn.execute(
            """INSERT INTO creations
               (id, brief_json, storyboard_json, provider, model, revision, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                creation.id,
                brief.model_dump_json(),
                storyboard.model_dump_json(),
                provider,
                model,
                creation.revision,
                now,
                now,
            ),
        )
    return creation


def _from_row(row) -> Creation:
    return Creation(
        id=row["id"],
        brief=CreationBrief.model_validate_json(row["brief_json"]),
        storyboard=Storyboard.model_validate_json(row["storyboard_json"]),
        provider=row["provider"],
        model=row["model"],
        revision=row["revision"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def get(creation_id: str) -> Creation | None:
    with connection() as conn:
        row = conn.execute("SELECT * FROM creations WHERE id = ?", (creation_id,)).fetchone()
    return _from_row(row) if row else None


def list_recent(limit: int = 25) -> list[Creation]:
    with connection() as conn:
        rows = conn.execute(
            "SELECT * FROM creations ORDER BY created_at DESC, rowid DESC LIMIT ?", (limit,)
        ).fetchall()
    return [_from_row(row) for row in rows]


def update(creation_id: str, storyboard: Storyboard, revision: int) -> Creation | None:
    """Compare-and-swap prevents a stale tab from overwriting newer edits."""
    with connection() as conn:
        cursor = conn.execute(
            """UPDATE creations SET storyboard_json = ?, revision = revision + 1, updated_at = ?
               WHERE id = ? AND revision = ?""",
            (storyboard.model_dump_json(), utcnow(), creation_id, revision),
        )
        if cursor.rowcount == 0:
            return None
        row = conn.execute("SELECT * FROM creations WHERE id = ?", (creation_id,)).fetchone()
    return _from_row(row)
