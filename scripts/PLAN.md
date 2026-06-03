# scripts/ — Migrations, Backfill, Seed

## `migrate.sql`

ClickHouse DDL:
```sql
-- Main time-series table
-- ReplacingMergeTree(fetched_at): when the same (source, series, dimension, date)
-- is re-inserted (e.g. GDP revised), the row with the latest fetched_at wins.
CREATE TABLE IF NOT EXISTS records (
    source      LowCardinality(String),
    series      LowCardinality(String),
    dimension   LowCardinality(String),
    value       Float64,
    date        Date,
    granularity LowCardinality(String),
    unit        LowCardinality(String),
    region      LowCardinality(String),
    tags        Map(String, String),
    fetched_at  DateTime DEFAULT now()
) ENGINE = ReplacingMergeTree(fetched_at)
PARTITION BY toYYYYMM(date)
ORDER BY (source, series, dimension, date);
```

PostgreSQL DDL:
```sql
CREATE TABLE IF NOT EXISTS pipeline_runs (
    id            SERIAL PRIMARY KEY,
    source        VARCHAR(64) NOT NULL,
    job_id        VARCHAR(128),
    started_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at   TIMESTAMPTZ,
    rows_fetched  INTEGER DEFAULT 0,
    rows_inserted INTEGER DEFAULT 0,
    status        VARCHAR(16) NOT NULL DEFAULT 'running',
    error_msg     TEXT
);

CREATE INDEX ON pipeline_runs (source, started_at DESC);
```

## `backfill.py`

CLI script for historical data loading:
```bash
python -m scripts.backfill --source mospi_cpi --from 2015-01-01 --to 2026-06-01
python -m scripts.backfill --source nse_bhavcopy --from 2024-01-01
python -m scripts.backfill --all --from 2020-01-01  # all Phase 1 sources
```

Respects rate limits: NSE bhavcopy = one file per day (fast), data.gov.in = 1000 req/hr
(add sleep between batches).

Idempotent: re-running for the same date range is safe — ClickHouse ReplacingMergeTree
deduplicates by (source, series, dimension, date).

## `seed.sh`

```bash
#!/bin/bash
# Apply migrations then backfill 5 years of Phase 1 sources.
# Run once after docker compose up -d.
docker exec india-findata-clickhouse-1 clickhouse-client < scripts/migrate.sql
python -m scripts.backfill --all --from $(date -d "5 years ago" +%Y-%m-%d)
```
