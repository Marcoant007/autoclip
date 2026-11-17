"""Per-job log history and live events, isolated to the pipeline's thread."""

from __future__ import annotations

import contextlib
import json
import logging
import threading
from collections import deque
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import TextIO
from uuid import uuid4

from .. import paths
from .events import Event, broker

HISTORY_LIMIT = 1000


def read_logs(job_id: str, limit: int = HISTORY_LIMIT) -> list[dict]:
    """Read the most recent entries, tolerating an interrupted final write."""
    path = paths.job_work_dir(job_id) / "logs.jsonl"
    entries: deque[dict] = deque(maxlen=limit)
    try:
        with path.open(encoding="utf-8") as stream:
            for line in stream:
                try:
                    entry = json.loads(line)
                except (ValueError, TypeError):
                    continue
                if isinstance(entry, dict) and all(
                    key in entry for key in ("id", "timestamp", "level", "logger", "message")
                ):
                    entries.append(entry)
    except FileNotFoundError:
        pass
    return list(entries)


class JobLogHandler(logging.Handler):
    def __init__(self, job_id: str) -> None:
        super().__init__(logging.INFO)
        self.stream: TextIO | None = None
        self.job_id = job_id
        self.thread_id = threading.get_ident()
        path = paths.job_work_dir(job_id) / "logs.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        self.stream = path.open("a", encoding="utf-8")
        self.setFormatter(logging.Formatter("%(message)s"))

    def emit(self, record: logging.LogRecord) -> None:
        if record.thread != self.thread_id or self.stream is None:
            return
        try:
            entry = {
                "id": uuid4().hex,
                "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(),
                "level": record.levelname,
                "logger": record.name,
                "message": self.format(record)[:8000],
            }
            self.stream.write(json.dumps(entry, ensure_ascii=False) + "\n")
            self.stream.flush()
            broker.publish(Event(type="log", job_id=self.job_id, data={"entry": entry}))
        except Exception:
            # Observability must not turn a successful inference into a failure.
            self.handleError(record)

    def close(self) -> None:
        if self.stream is not None:
            self.stream.close()
        super().close()


@contextlib.contextmanager
def capture_job_logs(job_id: str) -> Iterator[None]:
    logger = logging.getLogger("autoclip")
    previous_level = logger.level
    try:
        handler = JobLogHandler(job_id)
    except OSError:
        logging.getLogger(__name__).warning("Could not open job log history.", exc_info=True)
        yield
        return
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    try:
        logger.info("Processing started.")
        yield
    except BaseException:
        logger.error("Processing stopped with an error.", exc_info=True)
        raise
    else:
        logger.info("Processing completed successfully.")
    finally:
        logger.removeHandler(handler)
        logger.setLevel(previous_level)
        handler.close()
