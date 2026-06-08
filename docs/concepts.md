# Batch Pipeline Concepts

A guide for developers who know programming but haven't built data pipelines before.

---

## What is a batch pipeline?

A **batch pipeline** fetches data at scheduled intervals (daily, weekly, monthly) and stores it in a database. Contrast with:
- **Streaming**: data flows continuously, millisecond-to-second latency (Kafka, Flink)
- **Batch**: data is fetched in chunks on a schedule, minute-to-day latency

This project is batch — Indian macro data is published monthly/quarterly. There's nothing to stream.

---

## Idempotency

**Definition**: calling the same operation twice produces the same result as calling it once.

**Why it matters**: schedulers fail, servers restart, API calls time out. If a job re-runs, you don't want duplicate data or inconsistent state.

**How we achieve it**:
1. Each source's `fetch()` always fetches the same records for the same date range.
2. ClickHouse's `ReplacingMergeTree` deduplicates on `(source, series, dimension, date)`.
3. Re-running a backfill is always safe — just extra inserts that deduplicate.

```python
# Idempotent: calling twice for 2024-01 always gives the same Record
records = source.fetch(date(2024, 1, 1))
# Safe to insert even if we already inserted these records yesterday
store.insert_batch(client, records)
```

---

## Backfill

**Definition**: loading historical data that existed before you started running the pipeline.

When you first set up this project, ClickHouse is empty. You need to backfill years of CPI data, RBI rate history, etc. before the dashboard shows anything useful.

```bash
# Load 5 years of all Phase 1 sources
python -m scripts.backfill --all --from 2020-01-01
```

The backfill script calls `source.backfill(from_date, to_date)` which may make many API calls with rate-limiting sleeps between them.

---

## Incremental load

**Definition**: on each scheduled run, only fetch new data since the last run.

We don't track "last fetched date" explicitly — instead:
1. Daily jobs fetch today's data.
2. Monthly jobs fetch the last 12 months (picks up any revisions).
3. If a job misses a day (server was down), APScheduler's `coalesce=True` runs it once when the server comes back up.

---

## Data revisions (SCD Type 2)

**Definition**: a data point that was published as X is later corrected to Y.

Indian government agencies frequently revise data:
- MOSPI publishes "provisional" CPI, then revises to "final" ~3 months later.
- GDP figures are revised up to 2 years after initial release.

**How we handle revisions**:
- `ReplacingMergeTree(fetched_at)`: when the same `(source, series, dimension, date)` is inserted again, the row with the **latest `fetched_at`** wins during background merges.
- We store a `release` tag ("provisional" | "final") so users can see when figures changed.
- Always query with `FINAL` to get the current (post-revision) value:

```sql
-- Without FINAL: might see both the original and revised value
SELECT date, value FROM records WHERE source = 'mospi_cpi';

-- With FINAL: always sees the latest revision
SELECT date, value FROM records FINAL WHERE source = 'mospi_cpi';
```

---

## Rate limits

Government APIs have rate limits. Violating them gets your IP blocked.

- **data.gov.in**: 1,000 requests/hour
  - We sleep 3.6 seconds between requests in batch loops = 1 req/3.6s = 1000 req/hr
- **MOSPI API**: no published limit, we use 1 req/s conservatively
- **NSE bhavcopy** (Phase 2): one ZIP file per day, no rate limit concern

---

## The pipeline_runs table

Every job writes to `pipeline_runs` twice:
1. **Start**: `status = 'running'`, `started_at = now()`
2. **End**: `status = 'success' or 'failed'`, `finished_at`, `rows_fetched`, `rows_inserted`, `error_msg`

This gives you:
- A live view of what's currently running
- History of all past runs (useful for debugging)
- Error messages when something goes wrong

The Pipeline tab in the dashboard reads directly from this table.
