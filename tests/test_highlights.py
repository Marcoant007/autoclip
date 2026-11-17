"""Window coverage and actionable failures during highlight detection."""

from __future__ import annotations

import pytest
from autoclip.pipeline.highlights import LOCAL_MAX_WORDS, HighlightError, build_windows, detect
from autoclip.pipeline.transcript import Transcript, Word
from autoclip.providers import ClipCandidates, DetectionConfig
from autoclip.providers.base import LLMProvider, ProviderError, ProviderStatus


def transcript(count=1200, spacing=0.4):
    return Transcript(
        words=[
            Word(text=f"word{i}.", start=i * spacing, end=i * spacing + spacing)
            for i in range(count)
        ]
    )


@pytest.mark.parametrize("spacing", [0.0, 0.01, 0.4, 4.0])
def test_word_limited_windows_cover_every_word_without_gaps(spacing):
    source = transcript(spacing=spacing)
    windows = build_windows(source, max_words=400)
    assert all(window.word_count <= 400 for window in windows)
    assert windows[0].first_word == 0
    assert windows[-1].last_word == len(source.words) - 1
    assert all(b.first_word > a.first_word for a, b in zip(windows, windows[1:], strict=False))
    assert all(b.first_word <= a.last_word + 1 for a, b in zip(windows, windows[1:], strict=False))
    # Very fast speech must not degenerate into advancing one word per request.
    assert len(windows) <= 15


def test_time_limit_still_applies_when_word_cap_is_present():
    windows = build_windows(transcript(), window_s=60, overlap_s=10, max_words=400)
    assert all(window.duration_s <= 60.01 for window in windows)


@pytest.mark.parametrize("limit", [0, 1, -1])
def test_invalid_word_limit_is_rejected(limit):
    with pytest.raises(ValueError, match="max_words"):
        build_windows(transcript(), max_words=limit)


class RecordingProvider(LLMProvider):
    def __init__(self, name, error=None):
        super().__init__("test-model")
        self.name = name
        self.windows = []
        self.error = error

    async def detect_highlights(self, window, config):
        self.windows.append(window)
        if self.error:
            raise self.error
        return ClipCandidates(clips=[])

    async def _complete(self, system, user, config):
        raise AssertionError("No network in this test")

    async def health_check(self):
        return ProviderStatus(name=self.name, available=True)


@pytest.mark.parametrize("name", ["ollama", "openai"])
async def test_only_local_provider_uses_word_limited_windows(name):
    provider = RecordingProvider(name)
    with pytest.raises(HighlightError, match="No clips were found"):
        await detect(transcript(), provider, DetectionConfig(), job_id="test")
    largest = max(window.word_count for window in provider.windows)
    assert (largest <= LOCAL_MAX_WORDS) if name == "ollama" else (largest > LOCAL_MAX_WORDS)


async def test_provider_failure_is_preserved_in_final_error():
    provider = RecordingProvider("ollama", ProviderError("Ollama timed out."))
    with pytest.raises(HighlightError, match="First error: Ollama timed out"):
        await detect(transcript(), provider, DetectionConfig(), job_id="test")
