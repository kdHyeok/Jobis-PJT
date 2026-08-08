from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
import subprocess
from threading import RLock
from typing import Iterator


_current_job_id: ContextVar[str | None] = ContextVar("jobis_ai_job_id", default=None)
_lock = RLock()
_processes: dict[str, set[subprocess.Popen[str]]] = {}
_cancelled: set[str] = set()


class AnalysisCancelled(RuntimeError):
    pass


@contextmanager
def bind_analysis_job(job_id: str) -> Iterator[None]:
    token = _current_job_id.set(job_id)
    with _lock:
        _cancelled.discard(job_id)
    try:
        yield
    finally:
        with _lock:
            processes = _processes.pop(job_id, set())
            _cancelled.discard(job_id)
        for process in processes:
            if process.poll() is None:
                process.kill()
        _current_job_id.reset(token)


def register_process(process: subprocess.Popen[str]) -> None:
    job_id = _current_job_id.get()
    if job_id is None:
        return
    with _lock:
        if job_id in _cancelled:
            process.kill()
            raise AnalysisCancelled("analysis was cancelled by the user")
        _processes.setdefault(job_id, set()).add(process)


def current_analysis_job_id() -> str | None:
    """Return the bound formal-analysis job, if this call belongs to one."""

    return _current_job_id.get()


def cancel_analysis(job_id: str) -> bool:
    with _lock:
        _cancelled.add(job_id)
        processes = list(_processes.get(job_id, set()))
    found = bool(processes)
    for process in processes:
        if process.poll() is None:
            found = True
            process.kill()
    return found


def raise_if_cancelled() -> None:
    job_id = _current_job_id.get()
    if job_id is None:
        return
    with _lock:
        cancelled = job_id in _cancelled
    if cancelled:
        raise AnalysisCancelled("analysis was cancelled by the user")
