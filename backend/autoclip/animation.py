"""Declarative 2D direction: original characters, sets and timed acting.

The model supplies bounded data, never executable drawing code. Each keyframe
uses a fraction of the spoken scene, so direction survives a voice/rate change.
"""

from __future__ import annotations

import json
from typing import Annotated, Literal

from pydantic import BaseModel, Field, StringConstraints, model_validator

ActorId = Annotated[str, StringConstraints(pattern=r"^[a-zA-Z][a-zA-Z0-9_-]{0,23}$")]
Colour = Annotated[str, StringConstraints(pattern=r"^#[0-9a-fA-F]{6}$")]
Voice = Literal[
    "pt-BR-AntonioNeural",
    "pt-BR-FranciscaNeural",
    "pt-BR-ThalitaMultilingualNeural",
    "en-US-GuyNeural",
    "en-US-JennyNeural",
    "es-ES-AlvaroNeural",
    "es-ES-ElviraNeural",
]
Pose = Literal["rest", "present", "point", "think", "celebrate", "shrug"]
Expression = Literal["neutral", "happy", "worried", "surprised", "confident"]


class CharacterDesign(BaseModel):
    id: ActorId
    name: str = Field(min_length=1, max_length=60)
    skin: Colour = "#d69a72"
    hair_colour: Colour = "#302b34"
    shirt: Colour = "#3e8d86"
    trousers: Colour = "#34465a"
    hair: Literal["short", "curly", "long", "none"] = "short"
    outfit: Literal["casual", "robe"] = "casual"
    glasses: bool = False
    voice: Voice | None = None


class PoseKey(BaseModel):
    at: float = Field(
        ge=0, le=1, description="Fraction of scene time, not seconds: 0 is start, 1 is end."
    )
    x: float = Field(ge=0.05, le=0.95)
    pose: Pose = "rest"
    expression: Expression = "neutral"


class ActorTrack(BaseModel):
    actor_id: ActorId
    scale: float = Field(default=1, ge=0.6, le=1.35)
    facing: Literal["left", "right"] = "right"
    holding: Literal["none", "phone", "book"] = "none"
    keys: list[PoseKey] = Field(
        min_length=2,
        max_length=8,
        description="Strictly increasing timeline. First key at exactly 0; last key at exactly 1.",
    )

    @model_validator(mode="after")
    def ordered_keys(self):
        times = [key.at for key in self.keys]
        if times[0] != 0 or times[-1] != 1:
            raise ValueError("Actor keys must start at 0 and end at 1.")
        if any(b <= a for a, b in zip(times, times[1:], strict=False)):
            raise ValueError("Actor keyframe times must be strictly increasing.")
        return self


class SceneProp(BaseModel):
    kind: Literal["car", "plant", "desk", "chest", "coins"]
    x: float = Field(default=0.5, ge=-0.2, le=1.2)
    scale: float = Field(default=1, ge=0.3, le=1.8)


class ShotPlan(BaseModel):
    setting: Literal["street", "room", "courtyard"]
    time_of_day: Literal["day", "sunset", "night"] = "day"
    actors: list[ActorTrack] = Field(min_length=1, max_length=3)
    speaker: ActorId | None = None
    props: list[SceneProp] = Field(default_factory=list, max_length=6)
    zoom_start: float = Field(default=1, ge=1, le=1.8)
    zoom_end: float = Field(default=1.06, ge=1, le=1.8)
    focus_x: float = Field(default=0.5, ge=0.2, le=0.8)
    focus_y: float = Field(default=0.64, ge=0.35, le=0.8)

    @model_validator(mode="after")
    def actors_and_speaker(self):
        ids = [actor.actor_id for actor in self.actors]
        if len(set(ids)) != len(ids):
            raise ValueError("A character may appear only once in a shot.")
        if self.speaker is not None and self.speaker not in ids:
            raise ValueError("The speaking character must appear in this shot.")
        return self


class AnimationDirection(BaseModel):
    cast: list[CharacterDesign] = Field(min_length=1, max_length=4)
    shots: list[ShotPlan] = Field(min_length=1, max_length=12)

    @model_validator(mode="after")
    def cast_references(self):
        ids = [actor.id for actor in self.cast]
        if len(set(ids)) != len(ids):
            raise ValueError("Cast identifiers must be unique.")
        for shot in self.shots:
            if any(actor.actor_id not in ids for actor in shot.actors):
                raise ValueError("Every actor in a shot must reference the cast.")
        return self


async def direct_storyboard(brief, storyboard, provider):
    """Keep the approved narration and generate only the visual acting plan."""
    scenes = [
        {
            "index": i,
            "narration": scene.narration,
            "visual_description": scene.visual_description,
            "speaker_name": scene.speaker,
            "speaker_hint": scene.animation.speaker if scene.animation else None,
        }
        for i, scene in enumerate(storyboard.scenes)
    ]
    system = (
        "You direct a simple original 2D cartoon. Produce bounded JSON direction, "
        "not code. Use a consistent cast, readable staging and purposeful actions. "
        "The renderer supports only street, room and ancient courtyard sets, "
        "walks, hand gestures, facial expressions, blinking and speech-driven mouths. "
        "Do not claim it can draw arbitrary scenery. Match the supplied story using "
        "these sets and props. Use original adult characters. Never change or add "
        "spoken lines. Choose a speaker only when the existing narration is that "
        "character's dialogue; otherwise use null for a narrator. A speaker_hint "
        "is already approved: preserve that exact character ID. speaker_name names "
        "the person delivering dialogue and must be mapped to their cast ID. Cast voices must "
        "match the brief's language; use null to inherit the selected production voice. "
        "Use 3-4 keyframes for each speaking actor, including a distinct acting beat "
        "around 0.3 or 0.6. Use 2-4 for listeners. Avoid frozen poses: "
        "stage an entrance, a gesture "
        "or a clear reaction. Use x positions around 0.27 and 0.73 for two people. "
        "Avoid overlapping heads. Keep screen text out of the artwork. "
        "Return one shot per input scene, in the same order."
        " For EVERY actor, the first key MUST have at=0 and the last MUST have at=1. "
        "Use at values [0, 0.35, 0.7, 1] for speakers and [0, 1] for listeners. "
        "These are fractions of scene duration, NEVER seconds. Keep x around .27 or .73."
    )
    approved_cast = json.dumps(
        [actor.model_dump(mode="json") for actor in storyboard.cast], ensure_ascii=False
    )
    prompt = (
        f"Brief: {brief.model_dump_json()}\nScenes: {json.dumps(scenes, ensure_ascii=False)}\n"
        f"Approved cast: {approved_cast}\n"
        "When an approved cast exists, preserve all cast IDs exactly, including letter case.\n"
        f"Return exactly {len(scenes)} shots. JSON schema:\n"
        f"{json.dumps(AnimationDirection.model_json_schema())}"
    )

    # Count validation happens alongside the structured-output validation so an
    # incomplete plan gets one repair rather than silently losing scene alignment.
    class DirectionForStoryboard(AnimationDirection):
        @model_validator(mode="before")
        @classmethod
        def preserve_approved_metadata(cls, payload):
            if not isinstance(payload, dict):
                return payload
            # Approved identity and dialogue are inputs, not new creative
            # decisions. Merge them before validating the generated staging.
            if storyboard.cast:
                payload["cast"] = [actor.model_dump(mode="json") for actor in storyboard.cast]
            cast_rows = payload.get("cast", [])
            shots = payload.get("shots", [])
            if not isinstance(cast_rows, list) or not isinstance(shots, list):
                return payload
            for source, shot in zip(scenes, shots, strict=False):
                if not isinstance(shot, dict):
                    continue
                speaker = source["speaker_hint"]
                if speaker is None and source["speaker_name"]:
                    matches = [
                        row.get("id")
                        for row in cast_rows
                        if isinstance(row, dict)
                        and isinstance(row.get("name"), str)
                        and row["name"].casefold() == source["speaker_name"].casefold()
                    ]
                    if len(matches) == 1:
                        speaker = matches[0]
                if speaker is not None:
                    shot["speaker"] = speaker
            return payload

        @model_validator(mode="after")
        def shot_count(self):
            if len(self.shots) != len(scenes):
                raise ValueError(f"Expected exactly {len(scenes)} shots in original order.")
            if storyboard.cast and {actor.id for actor in self.cast} != {
                actor.id for actor in storyboard.cast
            }:
                raise ValueError("Preserve all approved cast IDs exactly, including letter case.")
            for source, shot in zip(scenes, self.shots, strict=True):
                if source["speaker_hint"] and shot.speaker != source["speaker_hint"]:
                    raise ValueError(f"Scene {source['index']} must preserve its speaker_hint.")
                if source["speaker_name"]:
                    names = [
                        actor.id
                        for actor in (storyboard.cast or self.cast)
                        if actor.name.casefold() == source["speaker_name"].casefold()
                    ]
                    if shot.speaker not in names:
                        raise ValueError(f"Scene {source['index']} must assign its named speaker.")
                if shot.speaker:
                    speaker_track = next(
                        actor for actor in shot.actors if actor.actor_id == shot.speaker
                    )
                    if len(speaker_track.keys) < 3:
                        raise ValueError(
                            "A speaking actor needs at least 3 keys for readable acting beats."
                        )
            return self

    direction = await provider.generate_structured(
        system, prompt, DirectionForStoryboard, max_output_tokens=4096
    )
    updated = storyboard.model_copy(deep=True)
    updated.cast = [actor.model_copy(deep=True) for actor in (storyboard.cast or direction.cast)]
    if not storyboard.cast:
        from .production import VOICES

        voices = [voice for voice, (language, _) in VOICES.items() if language == brief.language]
        for index, actor in enumerate(updated.cast):
            if actor.voice is None and any(shot.speaker == actor.id for shot in direction.shots):
                actor.voice = voices[index % len(voices)]
    for scene, shot in zip(updated.scenes, direction.shots, strict=True):
        scene.animation = shot
    return updated
