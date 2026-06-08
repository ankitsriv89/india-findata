"""
pipeline.scheduler — APScheduler job registration for all data sources.

We use APScheduler's BackgroundScheduler which runs jobs in a thread pool
alongside the FastAPI event loop.  This is the right choice for our use case:
jobs are I/O-bound (HTTP fetches) and run infrequently (daily/weekly/monthly).

Schedule overview (all times IST / Asia/Kolkata):
  MOSPI CPI/IIP  — monthly, days 11–16 at 4:30 PM
                   (MOSPI releases on the 12th; we poll a window in case of delays)
  GDP            — monthly, days 28–31 at 10 AM
                   (released ~60 days after quarter end — we poll end of month)
  RBI rates      — weekly, Sunday 2 AM (rates dataset is small, cheap to refresh)
  RBI forex      — weekly, Friday 7 PM (published after market close each Friday)

Job execution model:
  Each job function:
    1. Writes pipeline_runs row with status='running'
    2. Calls source.fetch(today)
    3. Calls store.clickhouse.insert_batch(records)
    4. Updates pipeline_runs row: status='success' or 'failed'

  A job failure NEVER crashes the scheduler.  Exceptions are caught here,
  logged via structlog, and written to pipeline_runs.error_msg.
"""

import structlog
from datetime import timezone, datetime

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from pipeline.config import settings
from pipeline.sources.mospi import MOSPISource, MOSPIGDPSource
from pipeline.sources.data_gov_in import RBIRatesSource, RBIForexSource
import pipeline.store.clickhouse as ch_store
import pipeline.store.postgres as pg_store

log = structlog.get_logger()


def _run_job(
    source_obj,  # any Source subclass
    ch_client,
    pg_pool,
    job_id: str,
) -> None:
    """
    Generic job runner — wraps fetch + insert + logging.

    Args:
        source_obj: An instantiated Source subclass.
        ch_client:  ClickHouse client (from ch_store.get_client()).
        pg_pool:    psycopg2 connection pool (from pg_store.create_pool()).
        job_id:     APScheduler job ID string for correlation.

    This function is called in a background thread by APScheduler.
    All exceptions are caught so a single source failure can't kill the
    scheduler or affect other jobs.
    """
    source_name = source_obj.name
    run_id: int | None = None
    rows_fetched = 0
    rows_inserted = 0

    try:
        run_id = pg_store.start_run(pg_pool, source_name, job_id)
        today = datetime.now(timezone.utc).date()

        records = source_obj.fetch(today)
        rows_fetched = len(records)

        if records:
            rows_inserted = ch_store.insert_batch(ch_client, records)

        pg_store.finish_run(
            pg_pool, run_id, source_name,
            rows_fetched=rows_fetched,
            rows_inserted=rows_inserted,
            status="success",
        )
        log.info(
            "job.success",
            source=source_name,
            job_id=job_id,
            rows_fetched=rows_fetched,
            rows_inserted=rows_inserted,
        )

    except Exception as exc:
        error_msg = f"{type(exc).__name__}: {exc}"
        log.error("job.failed", source=source_name, job_id=job_id, error=error_msg)
        if run_id is not None:
            try:
                pg_store.finish_run(
                    pg_pool, run_id, source_name,
                    rows_fetched=rows_fetched,
                    rows_inserted=rows_inserted,
                    status="failed",
                    error_msg=error_msg,
                )
            except Exception as log_exc:
                # If logging to Postgres also fails, at least we have structlog output
                log.error("job.log_failed", source=source_name, error=str(log_exc))


def create_scheduler(ch_client, pg_pool) -> BackgroundScheduler:
    """
    Build and return a configured APScheduler BackgroundScheduler.

    Jobs are registered here but the scheduler is NOT started — the caller
    (pipeline/main.py FastAPI lifespan) starts it after DB connections are
    verified.

    Args:
        ch_client: Connected ClickHouse client.
        pg_pool:   psycopg2 connection pool.

    Returns:
        A configured but not-yet-started BackgroundScheduler.
    """
    scheduler = BackgroundScheduler(timezone=settings.tz)

    # Instantiate all Phase 1 sources
    mospi_src = MOSPISource(
        api_token=settings.mospi_api_token or None,
        datagov_api_key=settings.data_gov_in_api_key or None,
    )
    gdp_src = MOSPIGDPSource(datagov_api_key=settings.data_gov_in_api_key)
    rbi_rates_src = RBIRatesSource(api_key=settings.data_gov_in_api_key)
    rbi_forex_src = RBIForexSource(api_key=settings.data_gov_in_api_key)

    # Helper to DRY up job registration
    def add(source_obj, job_id: str, trigger: CronTrigger) -> None:
        scheduler.add_job(
            _run_job,
            trigger=trigger,
            id=job_id,
            args=[source_obj, ch_client, pg_pool, job_id],
            # Replace existing job if scheduler is restarted (e.g. after config change)
            replace_existing=True,
            # Coalesce missed runs — if the server was down at 4:30 PM and
            # comes back up at 4:45 PM, run the job once (not twice).
            coalesce=True,
            # Don't run more than 1 instance of the same job concurrently.
            # If a fetch takes longer than expected, skip rather than pile up.
            max_instances=1,
        )

    # MOSPI CPI + IIP — monthly, poll window days 11–16 at 16:30 IST
    # MOSPI releases on the 12th but sometimes delays to the 13th or 14th.
    add(
        mospi_src,
        "mospi_cpi_iip",
        CronTrigger(day="11-16", hour=16, minute=30, timezone=settings.tz),
    )

    # GDP — quarterly release, check end of month (28th–31st) at 10:00 IST
    add(
        gdp_src,
        "mospi_gdp",
        CronTrigger(day="28-31", hour=10, minute=0, timezone=settings.tz),
    )

    # RBI rates — small dataset, refresh weekly on Sunday at 02:00 IST
    add(
        rbi_rates_src,
        "rbi_rates",
        CronTrigger(day_of_week="sun", hour=2, minute=0, timezone=settings.tz),
    )

    # RBI forex reserves — published every Friday evening
    add(
        rbi_forex_src,
        "rbi_forex",
        CronTrigger(day_of_week="fri", hour=19, minute=0, timezone=settings.tz),
    )

    return scheduler
