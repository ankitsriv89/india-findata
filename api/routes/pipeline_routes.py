"""
api.routes.pipeline_routes — pipeline status and run history endpoints.

These endpoints power the Pipeline tab in the dashboard, showing:
  - Current status of each source (last run, rows inserted, next scheduled run)
  - Paginated history of all past runs with error messages

Data comes from PostgreSQL (pipeline_runs table), not ClickHouse.

We use asyncpg (async) here so these queries don't block the event loop.
The scheduler uses psycopg2 (sync, in a thread pool) — two separate pools.
"""

import structlog
from datetime import datetime

from fastapi import APIRouter, HTTPException, Request, Query
from pydantic import BaseModel

log = structlog.get_logger()

router = APIRouter()


class PipelineRunSummary(BaseModel):
    """Summary of a single pipeline run (used in both status and history responses)."""
    source: str
    job_id: str | None
    started_at: datetime
    finished_at: datetime | None
    rows_fetched: int
    rows_inserted: int
    status: str          # "running" | "success" | "failed"
    error_msg: str | None


@router.get("/status")
async def get_pipeline_status(request: Request) -> list[PipelineRunSummary]:
    """
    Return the most recent run for each pipeline source.

    Used by the dashboard to show a status table:
      Source | Last run | Rows inserted | Status | Next run

    Sources that have never run are omitted from the response.
    """
    pool = request.app.state.asyncpg_pool

    try:
        rows = await pool.fetch(
            """
            SELECT DISTINCT ON (source)
                source, job_id, started_at, finished_at,
                rows_fetched, rows_inserted, status, error_msg
            FROM pipeline_runs
            ORDER BY source, started_at DESC
            """
        )
    except Exception as exc:
        log.error("pipeline.status_query_failed", error=str(exc))
        raise HTTPException(status_code=503, detail=f"Pipeline status query failed: {exc}")

    return [PipelineRunSummary(**dict(row)) for row in rows]


@router.get("/runs")
async def get_pipeline_runs(
    request: Request,
    source: str | None = Query(default=None, description="Filter by source name"),
    status: str | None = Query(default=None, description="Filter by status: success | failed | running"),
    limit: int = Query(default=50, ge=1, le=500, description="Max rows to return"),
) -> list[PipelineRunSummary]:
    """
    Return recent pipeline run history with optional filters.

    Used by the dashboard's run history table.  Paginate via the `limit`
    parameter (no cursor pagination — the dataset is small).
    """
    pool = request.app.state.asyncpg_pool

    # Build WHERE clause dynamically to avoid injecting values into the query string.
    # asyncpg uses $1, $2 positional placeholders.
    conditions = []
    params: list = []

    if source:
        params.append(source)
        conditions.append(f"source = ${len(params)}")

    if status and status != "all":
        params.append(status)
        conditions.append(f"status = ${len(params)}")

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    params.append(limit)

    try:
        rows = await pool.fetch(
            f"""
            SELECT source, job_id, started_at, finished_at,
                   rows_fetched, rows_inserted, status, error_msg
            FROM pipeline_runs
            {where}
            ORDER BY started_at DESC
            LIMIT ${len(params)}
            """,
            *params,
        )
    except Exception as exc:
        log.error("pipeline.runs_query_failed", error=str(exc))
        raise HTTPException(status_code=503, detail=f"Pipeline runs query failed: {exc}")

    return [PipelineRunSummary(**dict(row)) for row in rows]
