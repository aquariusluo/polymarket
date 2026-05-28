from __future__ import annotations

from pathlib import Path

import pytest

from app.services.job_run_service import execute_job
from app.storage.db import get_connection, init_db


def test_execute_job_records_completed_job_run(tmp_path: Path):
    db_path = tmp_path / "job-run-complete.db"
    init_db(str(db_path))

    with get_connection(str(db_path)) as conn:
        result = execute_job(
            conn,
            job_name="demo-job",
            runner=lambda: {"inserted": 3, "skipped": 1, "note": "ok"},
        )

        row = conn.execute(
            "SELECT job_name, status, inserted_count, skipped_count, error_message, finished_at FROM job_runs ORDER BY id DESC LIMIT 1"
        ).fetchone()

    assert result["inserted"] == 3
    assert row["job_name"] == "demo-job"
    assert row["status"] == "completed"
    assert row["inserted_count"] == 3
    assert row["skipped_count"] == 1
    assert row["error_message"] is None
    assert row["finished_at"] is not None


def test_execute_job_records_failed_job_run_and_reraises(tmp_path: Path):
    db_path = tmp_path / "job-run-failed.db"
    init_db(str(db_path))

    with get_connection(str(db_path)) as conn:
        with pytest.raises(RuntimeError, match="boom"):
            execute_job(
                conn,
                job_name="broken-job",
                runner=lambda: (_ for _ in ()).throw(RuntimeError("boom")),
            )

        row = conn.execute(
            "SELECT job_name, status, inserted_count, skipped_count, error_message, finished_at FROM job_runs ORDER BY id DESC LIMIT 1"
        ).fetchone()

    assert row["job_name"] == "broken-job"
    assert row["status"] == "failed"
    assert row["inserted_count"] == 0
    assert row["skipped_count"] == 0
    assert "boom" in row["error_message"]
    assert row["finished_at"] is not None
