"""Render the included acting pilot without touching the user's project database.

Run from the repository: .venv/Scripts/python.exe examples/render_cartoon_pilot.py
Narration uses the existing Edge TTS service; drawing and encoding run locally.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import shutil
from pathlib import Path

from autoclip import config, db, paths
from autoclip.creation import CreationImportIn
from autoclip.db import creation_renders, creations
from autoclip.db.models import new_id
from autoclip.pipeline.creation_video import CreationVideoRunner, video_path
from autoclip.production import RenderOptions


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--storyboard", type=Path, default=Path(__file__).with_name("moneyzi-cartoon-pilot.json")
    )
    parser.add_argument("--output", type=Path, default=Path(".autoclip/moneyzi-cartoon-pilot.mp4"))
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Output already exists; choose a new --output path.")
    logging.basicConfig(level=logging.INFO)
    sample = CreationImportIn.model_validate_json(args.storyboard.read_text(encoding="utf-8"))
    settings = config.load().export.model_copy()
    home = Path(".autoclip").resolve() / ("cartoon-pilot-" + new_id())
    os.environ[paths.ENV_HOME] = str(home)
    db.reset_connections()
    db.init()
    creation = creations.create(sample.brief, sample.storyboard, "pilot", "local-2d-rig")
    record = creation_renders.create(
        creation, RenderOptions(visual_mode="cartoon", caption_style="clean_lower"), settings
    )
    asyncio.run(CreationVideoRunner(record, cancelled=lambda: False).run())
    finished = creation_renders.get(record.id)
    if finished is None or finished.status != "done":
        raise RuntimeError(finished.error if finished else "Render disappeared.")
    source = video_path(record.id)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with source.open("rb") as source_file, args.output.open("xb") as output:
        shutil.copyfileobj(source_file, output)
    result = {
        "home": str(home),
        "creation_id": creation.id,
        "render_id": record.id,
        "video": str(args.output.resolve()),
        "duration_s": finished.duration_s,
        "script": str(args.storyboard.resolve()),
    }
    args.output.with_suffix(".json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2), flush=True)


if __name__ == "__main__":
    main()
