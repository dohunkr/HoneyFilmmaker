"""Persistent job queue with retry + progress. Stdlib only."""
from __future__ import annotations
import json
import time
import uuid
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Callable


@dataclass
class Job:
    id: str
    kind: str
    payload: dict[str, Any] = field(default_factory=dict)
    status: str = "pending"  # pending|running|done|failed
    progress: float = 0.0
    attempts: int = 0
    max_retries: int = 3
    error: str = ""
    result: dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)


class JobQueue:
    def __init__(self, persist_path: Path, max_retries: int = 3) -> None:
        self.persist_path = persist_path
        self.max_retries = max_retries
        self.jobs: dict[str, Job] = {}
        self._handlers: dict[str, Callable[[dict[str, Any], Callable[[float], None]], dict[str, Any]]] = {}
        self.load()

    def register(self, kind: str, fn) -> None:
        self._handlers[kind] = fn

    def submit(self, kind: str, payload: dict[str, Any] | None = None,
               max_retries: int | None = None) -> Job:
        j = Job(id=f"job-{uuid.uuid4().hex[:8]}", kind=kind,
                payload=payload or {},
                max_retries=self.max_retries if max_retries is None else max_retries)
        self.jobs[j.id] = j
        self.save()
        return j

    def run_sync(self, job_id: str) -> Job:
        job = self.jobs[job_id]
        handler = self._handlers.get(job.kind)
        if handler is None:
            job.status = "failed"
            job.error = f"no handler for kind={job.kind}"
            self.save()
            return job

        def _progress(p: float) -> None:
            job.progress = max(0.0, min(1.0, float(p)))
            job.updated_at = time.time()
            self.save()

        last_err = ""
        while job.attempts <= job.max_retries:
            job.status = "running"
            job.updated_at = time.time()
            self.save()
            try:
                res = handler(job.payload, _progress)
                job.result = res if isinstance(res, dict) else {"value": res}
                job.status = "done"
                job.progress = 1.0
                job.error = ""
                self.save()
                return job
            except Exception as e:  # noqa: BLE001
                last_err = str(e)
                job.attempts += 1
                job.error = last_err
                job.updated_at = time.time()
                self.save()
                if job.attempts > job.max_retries:
                    job.status = "failed"
                    self.save()
                    return job
        job.status = "failed"
        job.error = last_err
        self.save()
        return job

    def get(self, job_id: str) -> Job | None:
        return self.jobs.get(job_id)

    def save(self) -> None:
        self.persist_path.parent.mkdir(parents=True, exist_ok=True)
        data = {k: asdict(v) for k, v in self.jobs.items()}
        tmp = self.persist_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.persist_path)

    def load(self) -> None:
        try:
            if not self.persist_path.is_file():
                return
            raw = json.loads(self.persist_path.read_text(encoding="utf-8"))
            for k, v in raw.items():
                self.jobs[k] = Job(**v)
        except Exception:
            self.jobs = {}
