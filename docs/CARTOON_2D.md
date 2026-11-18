# 2D cartoon pilot and frontend contract

This backend stage draws scenery and independently articulated characters on each
frame: walks, hand gestures, expressions, blinking and mouths driven by real speech
energy. It needs no video-generation service or Claude API connection. Narration
still uses online Edge TTS. The frontend is being developed separately; this change
contains no frontend edits.

## Try the pilot

Import `examples/moneyzi-cartoon-pilot.json` using **Importar roteiro JSON**, then
generate the video. The default `auto` mode detects its animation plans. Choose the
clean caption preset for the pilot's look. The conversation is fictional and its
symbolic phone screen is not a demonstration of Moneyzi's actual interface.

For a separate preview database and export:

```powershell
.venv\Scripts\python.exe examples/render_cartoon_pilot.py
```

The output is `.autoclip/moneyzi-cartoon-pilot.mp4`. Choose another `--output` path
if it already exists. Only spoken text goes to the narration service; character
drawing and encoding happen locally.

## Generate or plan animation

Add `animate: true` to the existing `POST /api/creations` body:

```json
{
  "brief": {
    "topic": "Uma conversa sobre organizar as contas antes de comprar um carro",
    "niche": "general",
    "language": "pt-BR",
    "duration_s": 30,
    "visual_style": "illustrated",
    "instructions": "Conversa natural entre Rafa e Lara; cenas curtas."
  },
  "provider": "ollama",
  "animate": true
}
```

Writing and direction use separate validated schemas. The writing schema stays
small for local models. A dialogue scene sets `speaker` to the character's name;
off-screen narration leaves it null. Direction supplies a cast and one shot per
scene, with ordered acting keys. Invalid output gets one repair attempt; a failed
direction request returns an error rather than silently substituting cards.

To direct an existing script:

```http
POST /api/creations/{creation_id}/animation
Content-Type: application/json

{"revision": 1, "provider": "ollama"}
```

This preserves approved spoken text and saves a new revision containing
`storyboard.cast` and `storyboard.scenes[].animation`. Stale revisions return 409.
Replanning preserves approved cast designs and known speaking actor IDs. Newly
planned speaking characters receive voices matching the brief's language when no
voice was selected.

The frontend should show a planning state, then replace the editor's creation and
revision with the response. Preserve `cast`, scene `speaker`, and `animation` when
editing other fields; rebuilding scenes from only their three text fields would
discard direction metadata.

## Render modes

`POST /api/creations/{creation_id}/renders` accepts:

```json
{
  "revision": 2,
  "options": {
    "visual_mode": "cartoon",
    "resolution": "720p",
    "caption_style": "clean_lower",
    "rate_percent": 0
  }
}
```

| Mode | Behavior |
| --- | --- |
| `cartoon` | Every scene must have a valid animation plan; never falls back to cards. |
| `images` | Every scene must have an uploaded image; applies camera movement. |
| `cards` | Explicitly uses the legacy text-card artwork. |
| `auto` | Chooses each scene's animation plan, then uploaded image, then legacy card. |

Old clients keep `auto`. A UI option labelled **Cartoon 2D** should plan first,
then explicitly send `cartoon`. Do not label a card render as character animation.
Progress distinguishes **Animando personagens** from **Compondo imagens e cartelas**.

A speaking cast member's voice overrides the production voice; null inherits it.
A null shot speaker means an off-screen narrator: rigs still move and react, but
their mouths do not mimic the narrator. Renders retain the existing immutable
snapshots, FIFO queue, cancel/retry, preview/poster and MP4/SRT endpoints.

## Current art vocabulary

- Sets: street, furnished room, ancient courtyard; day, sunset or night sky.
- Original human rigs: skin, clothing and hair colours; short/curly/long/no hair;
  glasses; casual clothing or robes.
- Acting poses: rest, present, point, think, celebrate, shrug; face expressions,
  horizontal walk marks, blinking and audio-driven mouth shapes.
- Props: car, plant, desk, chest, coins; held phone or book.
- Normalized keyframe times run from 0 to 1 and scale to measured narration length.
  Camera focus/zoom is independent of rig movement.

This is a finite 2D engine. Custom scenery, 3D characters, contact physics and
phoneme-level lip sync require additional renderers or rig/set extensions.

## Skia dialogue engine (pilot)

`backend/autoclip/toon/` is a second, higher-fidelity renderer built for
character acting. It is not yet wired into the creation UI or the
`POST /renders` flow; the pilot runs from a script.

```powershell
.venv\Scripts\python.exe -m pip install -e ".[toon]"   # adds skia-python
.venv\Scripts\python.exe examples/render_toon_pilot.py              # MP4 + stills
.venv\Scripts\python.exe examples/render_toon_pilot.py --stills     # stills only
```

Output: `.autoclip/toon-pilot/rafa-lara-pilot.mp4` plus `.srt`, `.json`, preview
PNGs and `.sheet.png`. Narration uses the existing Edge TTS helper (online,
no key); drawing, lip sync and encoding are local.

| Module | Role |
| --- | --- |
| `draw.py` | Skia paints, Bézier/Catmull-Rom paths, path booleans, cel shading (form shadow + rim light). |
| `character.py` | Articulated rig: hips, torso lean, shrug, 2.5D head turn (cranium + rotating face mask), eyes with lids/iris/highlights, brows, visemic mouth, two-bone IK arms with continuous elbow swing, hand shapes (`relax`, `open`, `point`, `chin`, `phone`, `pocket`), curly hair with secondary motion. |
| `street.py` | Golden-hour street set in parallax layers; swaying tree and bougainvillea, moving leaf light, dust, falling leaves, car reflection. |
| `acting.py` | Keyframed channels with easing; cues anchored to spoken words (`"r2:bolso"`, `"l1.end+0.3"`, `"r1@0.5"`); breathing, idle drift, blinks, saccades, speech-driven head emphasis; viseme lip sync scaled by the real audio energy. |
| `scene.py` | Per-line TTS, timeline from measured durations, audio mix, ASS/SRT captions (existing presets), multiprocess rendering piped to FFmpeg with the configured encoder and loudness filter. |

The shot is described in `examples/toon-pilot/pilot.json`: cast looks and
voices, dialogue lines with gaps, camera keys, and per-character `base` pose,
named `presets` and `keys` (`at`, `dur`, `ease`, `use`, `set`, `blink`).
Specific to the pilot: the single street set, the two looks (hair styles
`short_curls`/`big_curls`, outfits `overshirt`/`tee`) and the hand-written
choreography.
