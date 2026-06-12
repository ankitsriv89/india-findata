"""
pipeline.store.postgres — log pipeline run metadata to PostgreSQL.

Every fetch job writes two rows to the `pipeline_runs` table:
  1. On job start:  status='running', started_at=now
  2. On job end:    status='success' or 'failed', finished_at=now, row counts, error_msg

This gives the dashboard a live view of what's running and a history of
all past runs, including error messages for debugging.

We use psycopg2 (synchronous) here because APScheduler runs jobs in
threads, not in the async event loop.  The FastAPI layer uses asyncpg
to query pipeline_runs non-blockingly.

Connection management:
  - create_pool() returns a psycopg2 connection pool (SimpleConnectionPool).
  - All functions take the pool as an argument rather than a global — this
    makes them easy to test with a test database.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime

import psycopg2
import structlog
from psycopg2 import pool as pg_pool
from psycopg2.extras import RealDictCursor

log = structlog.get_logger()


def create_pool(dsn: str, min_conn: int = 1, max_conn: int = 5) -> pg_pool.SimpleConnectionPool:
    """
    Create a psycopg2 connection pool.

    Args:
        dsn:      PostgreSQL connection string, e.g.
                  "postgresql://findata:secret@localhost:5433/indiafindata"
        min_conn: Minimum connections kept open (default 1)
        max_conn: Maximum connections in pool (default 5 — enough for
                  concurrent scheduler jobs)

    Returns:
        A SimpleConnectionPool ready for use.
    """
    return pg_pool.SimpleConnectionPool(min_conn, max_conn, dsn=dsn)


@contextmanager
def _get_conn(pool: pg_pool.SimpleConnectionPool) -> Iterator[psycopg2.extensions.connection]:
    """
    Context manager that borrows a connection from the pool and returns it
    when the block exits (even on exception).

    Usage:
        with _get_conn(pool) as conn:
            with conn.cursor() as cur:
                cur.execute(...)
    """
    conn = pool.getconn()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        pool.putconn(conn)


def start_run(pool: pg_pool.SimpleConnectionPool, source: str, job_id: str) -> int:
    """
    Write a 'running' row to pipeline_runs and return its id.

    Call this at the start of every fetch job.  The returned id is passed
    to finish_run() to update the same row on completion.

    Args:
        pool:   psycopg2 connection pool
        source: data source name (e.g. "mospi_cpi")
        job_id: APScheduler job id (for correlation with scheduler logs)

    Returns:
        The new pipeline_runs.id (integer primary key).
    """
    with _get_conn(pool) as conn, conn.cursor() as cur:
        cur.execute(
            """
                INSERT INTO pipeline_runs (source, job_id, started_at, status)
                VALUES (%s, %s, %s, 'running')
                RETURNING id
                """,
            (source, job_id, datetime.now(UTC)),
        )
        row = cur.fetchone()
        run_id: int = row[0]  # type: ignore[index]

    log.info("pipeline_run.started", source=source, job_id=job_id, run_id=run_id)
    return run_id


def finish_run(
    pool: pg_pool.SimpleConnectionPool,
    run_id: int,
    source: str,
    rows_fetched: int,
    rows_inserted: int,
    status: str,
    error_msg: str | None = None,
) -> None:
    """
    Update an existing pipeline_runs row with the final outcome.

    Args:
        pool:          psycopg2 connection pool
        run_id:        id returned by start_run()
        source:        data source name (for logging context)
        rows_fetched:  raw rows returned by the source API
        rows_inserted: rows actually written to ClickHouse
        status:        "success" or "failed"
        error_msg:     exception message on failure, None on success
    """
    with _get_conn(pool) as conn, conn.cursor() as cur:
        cur.execute(
            """
                UPDATE pipeline_runs
                SET finished_at   = %s,
                    rows_fetched  = %s,
                    rows_inserted = %s,
                    status        = %s,
                    error_msg     = %s
                WHERE id = %s
                """,
            (
                datetime.now(UTC),
                rows_fetched,
                rows_inserted,
                status,
                error_msg,
                run_id,
            ),
        )

    log.info(
        "pipeline_run.finished",
        source=source,
        run_id=run_id,
        status=status,
        rows_fetched=rows_fetched,
        rows_inserted=rows_inserted,
        error_msg=error_msg,
    )


def get_latest_runs(pool: pg_pool.SimpleConnectionPool) -> list[dict]:
    """
    Return the most recent pipeline_runs row for each source.

    Used by the /pipeline/status API endpoint to populate the dashboard
    status table.

    Returns:
        List of dicts, one per source, with keys:
        source, job_id, started_at, finished_at, rows_fetched,
        rows_inserted, status, error_msg
    """
    with _get_conn(pool) as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            """
                SELECT DISTINCT ON (source)
                    source, job_id, started_at, finished_at,
                    rows_fetched, rows_inserted, status, error_msg
                FROM pipeline_runs
                ORDER BY source, started_at DESC
                """
        )
        return [dict(row) for row in cur.fetchall()]


def get_run_history(
    pool: pg_pool.SimpleConnectionPool,
    source: str | None = None,
    status: str | None = None,
    limit: int = 50,
) -> list[dict]:
    """
    Return recent pipeline run history with optional filters.

    Args:
        pool:   psycopg2 connection pool
        source: filter to one source (None = all sources)
        status: filter by status: "success" | "failed" | None (all)
        limit:  max rows to return (default 50)

    Returns:
        List of dicts ordered by started_at DESC.
    """
    conditions = []
    params: list = []

    if source:
        conditions.append("source = %s")
        params.append(source)
    if status and status != "all":
        conditions.append("status = %s")
        params.append(status)

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    params.append(limit)

    with _get_conn(pool) as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            f"""
                SELECT source, job_id, started_at, finished_at,
                       rows_fetched, rows_inserted, status, error_msg
                FROM pipeline_runs
                {where}
                ORDER BY started_at DESC
                LIMIT %s
                """,
            params,
        )
        return [dict(row) for row in cur.fetchall()]
