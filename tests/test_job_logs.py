"""Job log persistence, SSE delivery, and isolation from unrelated activity."""

from __future__ import annotations

import asyncio
import logging
import threading

import pytest
from autoclip import paths
from autoclip.jobs.events import Event, EventBroker
from autoclip.jobs.logs import capture_job_logs, read_logs


def test_logs_survive_capture_and_retry(monkeypatch):
    events = []
    monkeypatch.setattr("autoclip.jobs.logs.broker.publish", events.append)
    with capture_job_logs("job-a"):
        logging.getLogger("autoclip.pipeline.transcribe").info("GPU: cuda float16")
    with capture_job_logs("job-a"):
        logging.getLogger("autoclip.providers.ollama_provider").warning("Retrying window")
    entries = read_logs("job-a")
    assert any(entry["message"] == "GPU: cuda float16" for entry in entries)
    assert any(entry["level"] == "WARNING" for entry in entries)
    assert len({entry["id"] for entry in entries}) == len(entries)
    assert [event.data["entry"] for event in events] == entries
    assert all(event.job_id == "job-a" and event.type == "log" for event in events)


def test_other_threads_and_other_loggers_do_not_leak_into_job():
    logger = logging.getLogger("autoclip.pipeline.runner")
    with capture_job_logs("job-a"):
        thread = threading.Thread(target=lambda: logger.warning("Unrelated request"))
        thread.start()
        thread.join()
        logging.getLogger("httpx").warning("Unrelated HTTP request")
        logger.info("This job")
    messages = [entry["message"] for entry in read_logs("job-a")]
    assert "This job" in messages
    assert not any("Unrelated" in message for message in messages)
    assert read_logs("job-b") == []


def test_exception_is_saved_and_logging_configuration_restored():
    logger = logging.getLogger("autoclip")
    previous_level = logger.level
    previous_handlers = list(logger.handlers)
    with pytest.raises(RuntimeError, match="GPU failed"), capture_job_logs("failed-job"):
        raise RuntimeError("GPU failed")
    assert logger.handlers == previous_handlers
    assert logger.level == previous_level
    entries = read_logs("failed-job")
    assert entries[-1]["level"] == "ERROR"
    assert "RuntimeError: GPU failed" in entries[-1]["message"]


def test_history_is_bounded_and_tolerates_partial_final_line():
    with capture_job_logs("job-a"):
        for index in range(8):
            logging.getLogger("autoclip.pipeline.runner").info("Message %d", index)
    path = paths.job_work_dir("job-a") / "logs.jsonl"
    with path.open("a", encoding="utf-8") as stream:
        stream.write('{"incomplete":')
    entries = read_logs("job-a", limit=3)
    assert len(entries) == 3
    assert entries[-1]["message"] == "Processing completed successfully."


def test_log_file_failure_does_not_prevent_processing(monkeypatch):
    from pathlib import Path

    original_open = Path.open

    def open_file(path, *args, **kwargs):
        if path.name == "logs.jsonl":
            raise PermissionError("The log file is locked")
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", open_file)
    with capture_job_logs("job-a"):
        processed = True
    assert processed


async def test_log_event_published_from_worker_reaches_subscriber():
    broker = EventBroker()
    broker.bind_loop(asyncio.get_running_loop())
    stream = broker.subscribe("job-a")
    pending = asyncio.create_task(anext(stream))
    await asyncio.sleep(0)
    event = Event(type="log", job_id="job-a", data={"entry": {"message": "GPU ready"}})
    await asyncio.to_thread(broker.publish, event)
    received = await asyncio.wait_for(pending, timeout=2)
    assert received.data["entry"]["message"] == "GPU ready"
    await stream.aclose()
    assert broker.subscriber_count("job-a") == 0


@pytest.mark.parametrize("fail", [False, True])
async def test_pipeline_run_captures_logs_and_preserves_job_outcome(
    initialised_db, monkeypatch, fail
):
    from pathlib import Path

    from autoclip.db import store
    from autoclip.db.models import Job, Source, new_id
    from autoclip.pipeline.runner import PipelineRunner
    from autoclip.pipeline.transcript import Transcript

    source = store.create_source(Source(id=new_id(), type="upload", path="source.mp4"))
    job = store.create_job(Job(id=new_id(), source_id=source.id))
    runner = PipelineRunner(job, source)
    monkeypatch.setattr(runner, "_stage_prepare", lambda: Path("audio.wav"))

    def transcribe(audio):
        logging.getLogger("autoclip.pipeline.transcribe").info("Transcription started")
        if fail:
            raise RuntimeError("Inference failed")
        return Transcript()

    async def highlights(*args):
        return []

    monkeypatch.setattr(runner, "_stage_transcribe", transcribe)
    monkeypatch.setattr(runner, "_load_or_detect_silences", lambda audio: [])
    monkeypatch.setattr(runner, "_stage_highlights", highlights)
    monkeypatch.setattr(runner, "_stage_reframe", lambda *args: {})
    monkeypatch.setattr(runner, "_stage_captions", lambda *args: None)
    monkeypatch.setattr(runner, "_stage_export", lambda *args: None)
    if fail:
        with pytest.raises(RuntimeError, match="Inference failed"):
            await runner.run()
    else:
        assert await runner.run() == []
    entries = read_logs(job.id)
    assert any(entry["message"] == "Transcription started" for entry in entries)
    assert store.get_job(job.id).status == ("failed" if fail else "done")
    if fail:
        assert any("RuntimeError: Inference failed" in entry["message"] for entry in entries)
