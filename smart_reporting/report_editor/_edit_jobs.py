"""改图与改表共用的任务保留期和限流窗口清理。"""

import asyncio
from typing import Any, Protocol


class _FinishedJob(Protocol):
    task: asyncio.Task[dict[str, Any]]
    finished_at: float | None


def prune_finished_jobs[Job: _FinishedJob](
    jobs: dict[str, Job], *, now: float, retention_seconds: float
) -> None:
    for edit_id, job in list(jobs.items()):
        if job.task.done():
            if job.finished_at is None:
                job.finished_at = now
            if now - job.finished_at > retention_seconds:
                del jobs[edit_id]


def prune_hourly_window(
    history: dict[str, list[float]], user_id: str, *, now: float
) -> None:
    window = [stamp for stamp in history.get(user_id, ()) if now - stamp < 3600]
    if window:
        history[user_id] = window
    else:
        history.pop(user_id, None)
