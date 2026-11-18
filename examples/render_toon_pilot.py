"""Render the 2D dialogue pilot (Rafa and Lara by the red car).

Run from the repository root:

    .venv/Scripts/python.exe examples/render_toon_pilot.py

Narration uses the existing Edge TTS helper (online, free, no API key). Drawing,
lip sync and encoding run locally with skia-python and FFmpeg. Output goes to
``.autoclip/toon-pilot/`` unless ``--output`` is given.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from pathlib import Path

from autoclip import config
from autoclip.pipeline import export
from autoclip.toon import scene

HERE = Path(__file__).resolve().parent
PREVIEWS = {
    "inicio": 0.2,
    "wow": 1.4,
    "carro": 2.3,
    "pensa": 3.9,
    "bolso": 5.6,
    "antes": 7.4,
    "contas": 8.6,
    "sobra": 9.9,
    "fim": 11.9,
}


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--spec", type=Path, default=HERE / "toon-pilot" / "pilot.json")
    parser.add_argument(
        "--output", type=Path, default=Path(".autoclip/toon-pilot/rafa-lara-pilot.mp4")
    )
    parser.add_argument("--resolution", choices=["720p", "1080p"], default="1080p")
    parser.add_argument("--workers", type=int, default=0, help="Render processes (0 = automatic).")
    parser.add_argument(
        "--stills", action="store_true", help="Only render the preview stills, no video."
    )
    args = parser.parse_args()

    spec = scene.load_spec(args.spec)
    workdir = args.output.parent / "work"
    started = time.time()
    prepared = asyncio.run(scene.prepare(spec, workdir))
    size = (1080, 1920) if args.resolution == "1080p" else (720, 1280)
    lines = [
        {
            "id": line.id,
            "speaker": line.speaker,
            "start": round(line.start, 3),
            "end": round(line.end, 3),
            "text": line.text,
        }
        for line in prepared.lines
    ]
    previews = {name: min(t, prepared.duration - 0.05) for name, t in PREVIEWS.items()}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    if args.stills:
        renderer = scene.ShotRenderer(
            spec, prepared.lines, prepared.duration, prepared.energy, prepared.mouths, size
        )
        paths = []
        for name, t in previews.items():
            path = args.output.with_name(f"{args.output.stem}.{name}.png")
            renderer.draw(t).save(str(path), scene.skia.kPNG)
            paths.append(path)
        scene.contact_sheet(paths, args.output.with_name(f"{args.output.stem}.sheet.png"))
        print(
            json.dumps(
                {"duration_s": prepared.duration, "lines": lines}, indent=2, ensure_ascii=False
            )
        )
        return

    settings = config.load().export
    last = [0.0]

    def progress(value: float) -> None:
        if value - last[0] >= 0.1 or value >= 1:
            last[0] = value
            print(f"  render {value * 100:5.1f}%  ({time.time() - started:5.1f}s)", flush=True)

    scene.render(
        prepared,
        args.output,
        size,
        export.encoder_args(settings),
        export.build_audio_filtergraph(settings),
        workers=args.workers,
        previews=previews,
        on_progress=progress,
    )
    stills = [args.output.with_name(f"{args.output.stem}.{name}.png") for name in previews]
    scene.contact_sheet(stills, args.output.with_name(f"{args.output.stem}.sheet.png"))
    srt = args.output.with_suffix(".srt")
    srt.write_text((workdir / "captions.srt").read_text(encoding="utf-8"), encoding="utf-8")
    result = {
        "video": str(args.output.resolve()),
        "subtitles": str(srt.resolve()),
        "contact_sheet": str(args.output.with_name(f"{args.output.stem}.sheet.png").resolve()),
        "duration_s": round(prepared.duration, 3),
        "resolution": f"{size[0]}x{size[1]}",
        "lines": lines,
        "elapsed_s": round(time.time() - started, 1),
    }
    args.output.with_suffix(".json").write_text(
        json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
