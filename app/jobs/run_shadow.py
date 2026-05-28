from __future__ import annotations

from app.config import get_settings
from app.jobs import run_pipeline
from app.services.scarf_service import update_dashboard, write_default_cron_jobs


def run(settings=None, *, project_root=None, **kwargs) -> dict:
    settings = settings or get_settings(project_root=project_root)
    result = run_pipeline.run(settings, max_iterations=1, sleep_seconds=0, project_root=project_root, **kwargs)
    result['dashboard_path'] = update_dashboard(project_root=project_root, settings=settings, pipeline_result=result)
    result['cron_jobs_path'] = write_default_cron_jobs(project_root=project_root)
    return result
