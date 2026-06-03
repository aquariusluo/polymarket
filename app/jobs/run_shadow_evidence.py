from __future__ import annotations

from app.config import Settings, get_settings
from app.services.artifact_service import write_shadow_evidence
from app.services.job_run_service import execute_job
from app.services.reporting_service import ReportingService
from app.storage.db import get_connection, init_db


def run(
    settings: Settings | None = None,
    *,
    project_root=None,
    reporting_service_cls=ReportingService,
    artifact_writer=write_shadow_evidence,
    conn=None,
) -> dict:
    settings = settings or get_settings(project_root)

    def runner(conn) -> dict:
        report = reporting_service_cls(conn, settings).generate_shadow_evidence_report()
        report.update(artifact_writer(report, project_root=project_root))
        return report

    if conn is not None:
        return execute_job(conn, job_name='shadow-evidence', runner=runner)
    with get_connection(settings.db_path) as own_conn:
        init_db(settings.db_path, conn=own_conn)
        return execute_job(own_conn, job_name='shadow-evidence', runner=runner)
