from __future__ import annotations

import inspect


def test_job_wrappers_expose_run_functions():
    from app.jobs import run_daily_report, run_mark_to_market, run_pipeline

    assert callable(run_mark_to_market.run)
    assert callable(run_daily_report.run)
    assert callable(run_pipeline.run)



def test_job_wrappers_use_explicit_signatures_without_kwargs():
    from app.jobs import (
        run_daily_report,
        run_final_report,
        run_generate_signals,
        run_mark_to_market,
        run_poll_trades,
        run_select_leaders,
        run_simulate,
    )

    modules = [
        run_select_leaders,
        run_poll_trades,
        run_generate_signals,
        run_simulate,
        run_mark_to_market,
        run_daily_report,
        run_final_report,
    ]
    for module in modules:
        params = inspect.signature(module.run).parameters.values()
        assert all(param.kind != inspect.Parameter.VAR_KEYWORD for param in params), module.__name__
