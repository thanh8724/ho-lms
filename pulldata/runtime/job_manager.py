from __future__ import annotations

import contextlib
import io
import tempfile
import threading
import time
import traceback
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable


@dataclass
class Artifact:
    name: str
    data: bytes
    content_type: str = "text/csv"


@dataclass
class Job:
    id: str
    label: str
    status: str = "queued"
    started_at: str = ""
    finished_at: str = ""
    logs: list[str] = field(default_factory=list)
    artifacts: list[Artifact] = field(default_factory=list)
    result: str = ""
    error: str = ""


class LiveLogBuffer(io.TextIOBase):
    """Small stdout-like sink that exposes exporter logs while it is running."""

    def __init__(self, job: Job, lock: threading.RLock):
        super().__init__()
        self.job = job
        self.lock = lock
        self.partial = ""

    def write(self, value: str) -> int:
        if not value:
            return 0
        with self.lock:
            self.partial += value
            lines = self.partial.splitlines(keepends=True)
            self.partial = ""
            if lines and not lines[-1].endswith(("\n", "\r")):
                self.partial = lines.pop()
            self.job.logs.extend(line.rstrip("\r\n") for line in lines if line.rstrip("\r\n"))
        return len(value)

    def flush(self) -> None:
        with self.lock:
            if self.partial.strip():
                self.job.logs.append(self.partial.strip())
            self.partial = ""


class JobManager:
    def __init__(self):
        self._jobs: dict[str, Job] = {}
        self._lock = threading.RLock()

    def get(self, job_id: str | None) -> Job | None:
        if not job_id:
            return None
        with self._lock:
            return self._jobs.get(job_id)

    def wait(self, job_id: str, timeout: float = 30) -> Job | None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            job = self.get(job_id)
            if job and job.status in {"success", "failed"}:
                return job
            time.sleep(0.02)
        return self.get(job_id)

    def start(self, label: str, worker: Callable[[Path], tuple[list[Path], str]]) -> str:
        job_id = uuid.uuid4().hex
        job = Job(id=job_id, label=label)
        with self._lock:
            self._jobs[job_id] = job

        def run():
            job.status = "running"
            job.started_at = datetime.now().isoformat(timespec="seconds")
            buffer = LiveLogBuffer(job, self._lock)
            try:
                with tempfile.TemporaryDirectory(prefix="ho-pulldata-") as tmp:
                    with contextlib.redirect_stdout(buffer), contextlib.redirect_stderr(buffer):
                        paths, result = worker(Path(tmp))
                    job.result = result or ""
                    for path in paths:
                        if path.exists():
                            job.artifacts.append(Artifact(path.name, path.read_bytes()))
                job.status = "success"
            except Exception as exc:
                job.status = "failed"
                job.error = f"{type(exc).__name__}: {exc}\n{traceback.format_exc()}"
            finally:
                buffer.flush()
                job.finished_at = datetime.now().isoformat(timespec="seconds")

        threading.Thread(target=run, daemon=True, name=f"pulldata-{job_id[:8]}").start()
        return job_id


def manager(session_state) -> JobManager:
    return session_state.setdefault("job_manager", JobManager())
