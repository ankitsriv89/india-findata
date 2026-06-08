-- =============================================================================
-- migrate.sql — Database schema for india-findata
-- =============================================================================
-- Run this once after `docker compose up -d` to create all tables.
-- Safe to re-run: all statements use IF NOT EXISTS.
--
-- Two databases:
--   ClickHouse  — time-series records (all actual data points)
--   PostgreSQL  — pipeline metadata only (run history, job status)
-- =============================================================================


-- ---------------------------------------------------------------------------
-- CLICKHOUSE SCHEMA
-- ---------------------------------------------------------------------------
-- Run against ClickHouse HTTP port 8123:
--   clickhouse-client --host localhost --port 9000 < scripts/migrate.sql
-- Or via HTTP:
--   curl -u default: "http://localhost:8123/" --data-binary @scripts/migrate.sql
-- ---------------------------------------------------------------------------

-- Main time-series table.
--
-- ReplacingMergeTree(fetched_at): when the same (source, series, dimension, date)
-- is re-inserted (e.g. a revised GDP figure), the row with the latest fetched_at
-- wins and replaces the old value during background merges.
--
-- Always query with FINAL to force deduplication:
--   SELECT ... FROM records FINAL WHERE ...
--
-- Partitioned by month so queries with a date range only scan relevant partitions.
-- ORDER BY is the primary index — put high-cardinality columns last.
CREATE TABLE IF NOT EXISTS indiafindata.records
(
    source      LowCardinality(String),   -- "mospi_cpi" | "nse_bhavcopy" | "rbi_rates"
    series      LowCardinality(String),   -- "CPI_GENERAL" | "NIFTY50" | "REPO_RATE"
    dimension   LowCardinality(String),   -- "index_value" | "close_price" | "rate_pct"
    value       Float64,                  -- the actual number
    date        Date,                     -- observation date (not fetch date)
    granularity LowCardinality(String),   -- "daily" | "monthly" | "quarterly"
    unit        LowCardinality(String),   -- "index_points" | "INR" | "percent"
    region      LowCardinality(String),   -- "india" | "sector:IT" | "mumbai"
    tags        Map(String, String),      -- {"base_year": "2012", "sector": "IT"}
    fetched_at  DateTime DEFAULT now()    -- when this row was fetched (used by ReplacingMergeTree)
)
ENGINE = ReplacingMergeTree(fetched_at)
PARTITION BY toYYYYMM(date)
ORDER BY (source, series, dimension, date)
SETTINGS index_granularity = 8192;


-- ---------------------------------------------------------------------------
-- POSTGRESQL SCHEMA
-- ---------------------------------------------------------------------------
-- Run against PostgreSQL:
--   psql -h localhost -p 5433 -U findata -d indiafindata < scripts/migrate.sql
-- Or via the seed script which handles both databases.
-- ---------------------------------------------------------------------------

-- pipeline_runs tracks every execution of a fetch job.
-- One row is written when the job starts (status='running'),
-- then updated when it finishes (status='success' or 'failed').
-- This powers the Pipeline Status tab in the dashboard.
CREATE TABLE IF NOT EXISTS pipeline_runs (
    id             SERIAL PRIMARY KEY,
    source         VARCHAR(64)  NOT NULL,            -- matches Record.source
    job_id         VARCHAR(128),                     -- APScheduler job ID
    started_at     TIMESTAMPTZ  NOT NULL DEFAULT now(),
    finished_at    TIMESTAMPTZ,
    rows_fetched   INTEGER      NOT NULL DEFAULT 0,  -- raw rows from source API
    rows_inserted  INTEGER      NOT NULL DEFAULT 0,  -- rows actually written to ClickHouse
    status         VARCHAR(16)  NOT NULL DEFAULT 'running', -- 'running'|'success'|'failed'
    error_msg      TEXT                              -- NULL on success, exception message on failure
);

-- Index for the two common query patterns:
--   1. Dashboard: latest run per source (WHERE source = X ORDER BY started_at DESC)
--   2. Run history: paginated list of all recent runs (ORDER BY started_at DESC)
CREATE INDEX IF NOT EXISTS pipeline_runs_source_started
    ON pipeline_runs (source, started_at DESC);
