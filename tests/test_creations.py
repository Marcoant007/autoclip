"""Original-video planning: provider contracts, persisted edits and API errors."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator

import httpx
import pytest
from autoclip import db, providers
from autoclip.app import ENV_NO_WORKER, create_app
from autoclip.creation import CreationBrief, Storyboard, generate_storyboard
from autoclip.db import creations, store
from autoclip.db.models import Source, new_id
from autoclip.db.schema import _migration_v1, migrate
from autoclip.providers.base import DetectionConfig, LLMProvider, ProviderError, ProviderStatus
from fastapi.testclient import TestClient

SCRIPT = {
    "title": "Como um computador guarda informações?",
    "description": "Entenda a diferença entre memória e armazenamento.",
    "scenes": [
        {
            "narration": "A memória é uma mesa de trabalho.",
            "visual_description": "Mesa com cartões azuis, câmera aproxima devagar.",
            "on_screen_text": "Memória",
        },
        {
            "narration": "O armazenamento é o armário onde você guarda tudo.",
            "visual_description": "Mesmo cenário e paleta, cartões seguem para um armário.",
            "on_screen_text": "Armazenamento",
        },
        {
            "narration": "Os dois trabalham juntos para você encontrar suas informações.",
            "visual_description": "Diagrama conecta a mesa ao armário.",
            "on_screen_text": "Cada um tem sua função",
        },
    ],
    "references": ["Documentação do sistema operacional utilizado"],
    "review_notes": ["A analogia simplifica o funcionamento."],
}


class ScriptProvider(LLMProvider):
    name = "ollama"
    requires_key = False

    def __init__(self, responses: list[str] | None = None):
        super().__init__("test-model")
        self.responses = responses if responses is not None else [json.dumps(SCRIPT)]
        self.calls: list[tuple[str, str, DetectionConfig]] = []

    async def _complete(self, system, user, config):
        self.calls.append((system, user, config))
        return self.responses.pop(0)

    async def health_check(self):
        return ProviderStatus(name=self.name, available=True)


@pytest.fixture
def client(autoclip_home, monkeypatch) -> Iterator[TestClient]:
    monkeypatch.setenv(ENV_NO_WORKER, "1")
    with TestClient(create_app()) as test_client:
        yield test_client


@pytest.fixture
def scripted(monkeypatch):
    provider = ScriptProvider()
    monkeypatch.setattr(providers, "build_provider", lambda name=None: provider)
    return provider


async def test_generation_uses_storyboard_schema_and_the_user_brief():
    provider = ScriptProvider()
    brief = CreationBrief(topic="Davi e Golias", niche="biblical", duration_s=75)

    storyboard = await generate_storyboard(brief, provider)

    assert storyboard.title == SCRIPT["title"]
    system, user, config = provider.calls[0]
    assert "Davi e Golias" in user
    assert "188 spoken words" in user
    assert "biblical" in system
    assert "no browsing" in system
    assert config.response_schema["required"] == ["title", "description", "scenes"]
    assert "clips" not in config.response_schema["properties"]
    assert config.max_output_tokens == 4096


async def test_invalid_script_is_repaired_once_with_validation_feedback():
    invalid = {**SCRIPT, "scenes": SCRIPT["scenes"][:1]}
    provider = ScriptProvider([json.dumps(invalid), json.dumps(SCRIPT)])

    result = await generate_storyboard(CreationBrief(topic="Memória"), provider)

    assert len(result.scenes) == 3
    assert len(provider.calls) == 2
    assert "Validation error" in provider.calls[1][1]


async def test_malformed_script_twice_is_an_actionable_failure():
    provider = ScriptProvider(["not json", '{"clips":[]}'])
    with pytest.raises(ProviderError, match="malformed script data twice"):
        await generate_storyboard(CreationBrief(topic="Memória"), provider)


async def test_ollama_receives_the_storyboard_schema(monkeypatch):
    captured = []

    def respond(request):
        captured.append(json.loads(request.content))
        return httpx.Response(200, json={"response": json.dumps(SCRIPT), "done_reason": "stop"})

    original_client = httpx.AsyncClient
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: original_client(transport=httpx.MockTransport(respond), **kwargs),
    )
    provider = providers.OllamaProvider("local-test-model")

    result = await generate_storyboard(CreationBrief(topic="Memória"), provider)

    assert len(result.scenes) == 3
    assert "scenes" in captured[0]["format"]["properties"]
    assert "clips" not in captured[0]["format"]["properties"]
    assert captured[0]["options"]["num_predict"] == 4096


def test_create_edit_reopen_and_download(client, scripted):
    response = client.post("/api/creations", json={"brief": {"topic": "Memória e armazenamento"}})
    assert response.status_code == 201
    created = response.json()
    assert created["provider"] == "ollama"
    assert created["model"] == "test-model"
    assert created["revision"] == 1
    assert len(client.get("/api/creations").json()) == 1
    assert client.get(f"/api/creations/{created['id']}").json() == created

    # Counts from a client/model must not be trusted after a narration edit.
    edited = created["storyboard"]
    edited["scenes"][0]["narration"] = "Texto novo para a primeira cena."
    edited["narration_word_count"] = 90000
    response = client.put(
        f"/api/creations/{created['id']}",
        json={
            "storyboard": edited,
            "revision": created["revision"],
        },
    )
    assert response.status_code == 200
    saved = response.json()
    assert saved["revision"] == 2
    assert saved["storyboard"]["narration_word_count"] < 100

    reopened = client.get(f"/api/creations/{created['id']}").json()
    assert reopened == saved
    download = client.get(f"/api/creations/{created['id']}/download")
    assert download.json() == saved
    assert "attachment" in download.headers["content-disposition"]
    assert "application/json" in download.headers["content-type"]
    assert "settings" not in download.json()


def test_stale_tab_cannot_overwrite_a_saved_script(client, scripted):
    created = client.post("/api/creations", json={"brief": {"topic": "Memória"}}).json()
    endpoint = f"/api/creations/{created['id']}"
    payload = {"storyboard": created["storyboard"], "revision": 1}
    assert client.put(endpoint, json=payload).status_code == 200
    payload["storyboard"]["title"] = "Stale overwrite"
    assert client.put(endpoint, json=payload).status_code == 409
    assert client.get(endpoint).json()["storyboard"]["title"] == SCRIPT["title"]


@pytest.mark.parametrize(
    "brief",
    [
        {"topic": "   "},
        {"topic": "a" * 301},
        {"topic": "Memória", "duration_s": 0},
        {"topic": "Memória", "niche": "unknown"},
        {"topic": "Memória", "duration_s": 181},
    ],
)
def test_invalid_brief_never_calls_the_provider(client, scripted, brief):
    assert client.post("/api/creations", json={"brief": brief}).status_code == 422
    assert scripted.calls == []


def test_provider_failure_does_not_save_a_broken_creation(client, monkeypatch):
    provider = ScriptProvider(["not json", "not json"])
    monkeypatch.setattr(providers, "build_provider", lambda name=None: provider)
    response = client.post("/api/creations", json={"brief": {"topic": "Memória"}})
    assert response.status_code == 502
    assert response.json()["detail"]["hint"]
    assert client.get("/api/creations").json() == []


def test_missing_creation_and_invalid_limits(client):
    assert client.get("/api/creations/missing").status_code == 404
    assert client.get("/api/creations/missing/download").status_code == 404
    assert (
        client.put("/api/creations/missing", json={"storyboard": SCRIPT, "revision": 1}).status_code
        == 404
    )
    assert client.get("/api/creations?limit=0").status_code == 422
    assert client.get("/api/creations?limit=101").status_code == 422


def test_whitespace_only_scene_cannot_replace_saved_work(client, scripted):
    created = client.post("/api/creations", json={"brief": {"topic": "Memória"}}).json()
    endpoint = f"/api/creations/{created['id']}"
    payload = {"storyboard": created["storyboard"], "revision": 1}
    payload["storyboard"]["scenes"][0]["narration"] = "   "
    assert client.put(endpoint, json=payload).status_code == 422
    assert client.get(endpoint).json()["revision"] == 1


def test_migration_preserves_existing_media_and_creations_survive_reopen(initialised_db):
    source = store.create_source(Source(id=new_id(), type="upload", path="/video.mp4"))
    script = creations.create(
        CreationBrief(topic="Memória"), Storyboard.model_validate(SCRIPT), "ollama", "test"
    )
    db.reset_connections()
    db.init()
    assert store.get_source(source.id).path == "/video.mp4"
    assert creations.get(script.id) == script


def test_upgrade_from_v1_keeps_existing_sources():
    conn = sqlite3.connect(":memory:")
    try:
        _migration_v1(conn)
        conn.execute("PRAGMA user_version = 1")
        conn.execute("""INSERT INTO sources (id, type, path, created_at)
                        VALUES ('existing', 'upload', '/video.mp4', '2026-01-01')""")
        migrate(conn)
        assert conn.execute("SELECT id FROM sources").fetchone()[0] == "existing"
        assert conn.execute("SELECT count(*) FROM creations").fetchone()[0] == 0
    finally:
        conn.close()
