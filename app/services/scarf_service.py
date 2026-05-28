from __future__ import annotations

from pathlib import Path

from app.config import Settings
from app.services import cron_service, dashboard_service


def write_default_cron_jobs(project_root: str | Path | None = None) -> str:
    return cron_service.write_default_cron_jobs(project_root=project_root)


def update_dashboard(*, project_root: str | Path | None = None, settings: Settings, pipeline_result: dict) -> str:
    return dashboard_service.update_dashboard(project_root=project_root, settings=settings, pipeline_result=pipeline_result)
