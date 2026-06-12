"""
pipeline.main — FastAPI application entry point.

Starts two things in a single process:
  1. APScheduler (background thread pool) — fires fetch jobs on schedule
  2. FastAPI/uvicorn (async event loop) — serves the query API

Single-process design is intentional for POC scale: simpler to deploy
(one container, one process), easier to debug, no inter-process messaging.
At production scale you'd separate the scheduler into its own worker.

Startup sequence (FastAPI lifespan):
  1. Configure structlog
  2. Connect to ClickHouse — verify the records table exists
  3. Connect to PostgreSQL — create pool
  4. Register routes
  5. Start APScheduler
  → App is now ready to serve requests and fire jobs

Shutdown sequence:
  1. Stop APScheduler (waits for running jobs to finish, up to 5 seconds)
  2. Close DB connections
"""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import asyncpg
import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

import pipeline.store.clickhouse as ch_store
import pipeline.store.postgres as pg_store
from pipeline.config import settings
from pipeline.scheduler import create_scheduler

# ── Logging setup ────────────────────────────────────────────────────────────
# structlog is configured once at module load.  In production (LOG_LEVEL=INFO)
# it emits JSON lines.  In development (LOG_LEVEL=DEBUG) it uses coloured output.

def _configure_logging() -> None:
    """
    Configure structlog to emit JSON in production, coloured text in development.

    We bind level=DEBUG/INFO/etc to the root stdlib logger so that libraries
    (apscheduler, uvicorn, clickhouse_connect) also respect the log level.
    """
    log_level = getattr(logging, settings.log_level.upper(), logging.INFO)
    logging.basicConfig(level=log_level)

    is_dev = settings.log_level.upper() == "DEBUG"

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_log_level,
            structlog.stdlib.add_logger_name,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            (
                structlog.dev.ConsoleRenderer()
                if is_dev
                else structlog.processors.JSONRenderer()
            ),
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
    )


_configure_logging()
log = structlog.get_logger()


# ── App state ─────────────────────────────────────────────────────────────────
# We store shared resources (DB clients) on app.state so route handlers can
# access them without module-level globals.  FastAPI's dependency injection
# would also work but app.state is simpler for a small app.

class AppState:
    ch_client = None       # clickhouse_connect Client
    pg_pool = None         # psycopg2 SimpleConnectionPool
    asyncpg_pool = None    # asyncpg Pool (for async route handlers)
    scheduler = None       # APScheduler BackgroundScheduler


# ── Lifespan ──────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """
    FastAPI lifespan context manager — runs startup/shutdown logic.

    Using lifespan instead of @app.on_event("startup") because on_event
    is deprecated in FastAPI 0.93+.  The lifespan pattern is cleaner:
    everything before `yield` runs on startup, everything after on shutdown.
    """
    log.info("app.starting", version="0.1.0")

    # 1. Connect to ClickHouse
    try:
        AppState.ch_client = ch_store.get_client(
            host=settings.clickhouse_host,
            port=settings.clickhouse_port,
            database=settings.clickhouse_db,
            username=settings.clickhouse_user,
            password=settings.clickhouse_password,
        )
        if not ch_store.table_exists(AppState.ch_client):
            raise RuntimeError(
                "ClickHouse `records` table not found. Run: scripts/migrate.sql"
            )
        log.info("clickhouse.connected", host=settings.clickhouse_host)
    except Exception as exc:
        log.error("clickhouse.connect_failed", error=str(exc))
        raise

    # 2. Connect to PostgreSQL (sync pool for scheduler jobs)
    try:
        AppState.pg_pool = pg_store.create_pool(settings.postgres_dsn)
        log.info("postgres.connected")
    except Exception as exc:
        log.error("postgres.connect_failed", error=str(exc))
        raise

    # 3. Async pool for FastAPI route handlers (asyncpg is async, psycopg2 is sync)
    try:
        AppState.asyncpg_pool = await asyncpg.create_pool(settings.postgres_dsn)
        log.info("asyncpg.connected")
    except Exception as exc:
        log.error("asyncpg.connect_failed", error=str(exc))
        raise

    # 4. Start APScheduler
    AppState.scheduler = create_scheduler(AppState.ch_client, AppState.pg_pool)
    AppState.scheduler.start()
    log.info("scheduler.started", jobs=len(AppState.scheduler.get_jobs()))

    app.state.ch_client = AppState.ch_client
    app.state.pg_pool = AppState.pg_pool
    app.state.asyncpg_pool = AppState.asyncpg_pool

    log.info("app.ready", port=settings.api_port)
    yield  # ← app is running here

    # ── Shutdown ──────────────────────────────────────────────────────────────
    log.info("app.shutting_down")

    if AppState.scheduler:
        # wait=True blocks until running jobs finish (up to 5s timeout)
        AppState.scheduler.shutdown(wait=True)
        log.info("scheduler.stopped")

    if AppState.asyncpg_pool:
        await AppState.asyncpg_pool.close()

    if AppState.pg_pool:
        AppState.pg_pool.closeall()

    log.info("app.stopped")


# ── FastAPI app ────────────────────────────────────────────────────────────────

app = FastAPI(
    title="india-findata API",
    description="Query API for Indian financial and economic time-series data.",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS: allow the Vite dev server and production domain.
# The wildcard fallback is intentional for local Docker Compose testing.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5190",    # Vite dev server
        "http://localhost:3000",    # alternative dev port
        "*",                        # Docker Compose / production (restrict in prod)
    ],
    allow_methods=["GET"],
    allow_headers=["*"],
)

# Register route modules (imported here to avoid circular imports)
from api.routes import banking, macro, markets, pipeline_routes  # noqa: E402

app.include_router(macro.router, prefix="/macro", tags=["macro"])
app.include_router(markets.router, prefix="/markets", tags=["markets"])
app.include_router(banking.router, prefix="/banking", tags=["banking"])
app.include_router(pipeline_routes.router, prefix="/pipeline", tags=["pipeline"])


@app.get("/health")
async def health() -> dict:
    """
    Health check endpoint.  Returns 200 if the app is running and DB connections
    are alive.  Used by Docker healthcheck and load balancers.
    """
    ch_ok = False
    pg_ok = False

    try:
        AppState.ch_client.query("SELECT 1")
        ch_ok = True
    except Exception:
        pass

    try:
        # Quick check: can we get a connection from the pool?
        conn = AppState.pg_pool.getconn()
        AppState.pg_pool.putconn(conn)
        pg_ok = True
    except Exception:
        pass

    status = "ok" if (ch_ok and pg_ok) else "degraded"
    return {"status": status, "clickhouse": ch_ok, "postgres": pg_ok}
