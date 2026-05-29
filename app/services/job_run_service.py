from __future__ import annotations

import inspect
import sqlite3
from typing import Any, Callable

from app.storage.repositories import JobRunRepository


def execute_job(
    conn: sqlite3.Connection,
    *,
    job_name: str,
    runner: Callable[..., dict[str, Any]],
    atomic: bool = False,
) -> dict[str, Any]:
    repo = JobRunRepository(conn)
    job_run_id = repo.start(job_name, commit=not atomic)
    try:
        params = inspect.signature(runner).parameters
        if params:
            result = runner(conn) or {}
        else:
            result = runner() or {}
        inserted = int(result.get("inserted", result.get("inserted_orders", result.get("leaders_inserted", 0))))
        skipped = int(result.get("skipped", result.get("trades_skipped", 0)))
        repo.finish(
            job_run_id,
            status="completed",
            inserted_count=inserted,
            skipped_count=skipped,
            commit=not atomic,
        )
        if atomic:
            conn.commit()
        payload = dict(result)
        payload["job_run_id"] = job_run_id
        return payload
    except Exception as exc:
        if atomic:
            conn.rollback()
            failed_job_run_id = repo.start(job_name)
            repo.finish(failed_job_run_id, status="failed", error_message=str(exc))
        else:
            repo.finish(job_run_id, status="failed", error_message=str(exc))
        raise
