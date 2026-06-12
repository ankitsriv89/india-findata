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

## High-volume daily batches (Markets layer)

Macro sources emit a handful of rows per run (CPI has ~4 series × 12 months). A
single NSE bhavcopy is a different scale: ~2000 symbols × 5 dimensions (OHLC +
volume) ≈ **10,000 records per day**. Two patterns keep this manageable:

1. **Chunked inserts** — `insert_batch` splits records into 1000-row chunks, so a
   day becomes ~10 `INSERT`s rather than one giant statement. This bounds memory
   and stays under ClickHouse's `max_query_size`. (`test_nse.py` asserts the
   chunk arithmetic: `2000×5 → 10 batches`.)
2. **One dimension per record, not one wide row** — instead of a row with
   open/high/low/close/volume columns, each becomes its own `Record` sharing the
   universal schema. The dashboard then queries exactly the dimension it needs
   (`WHERE dimension = 'close_price'`) and the `records` table never grows new
   columns when we add a source.

## Time-series vs cross-sectional queries

The Markets API shows the two query shapes a financial dashboard needs:

- **Time-series** (`/markets/equity`, `/markets/fii`) — *one* series over *many*
  dates. These reuse the macro `_query_records` helper: filter `source`+`series`,
  range over `date`, return `[{date, value}]`.
- **Cross-sectional** (`/markets/movers`, `/markets/heatmap`) — *many* series on
  *one* date, compared against each other. Top movers needs each symbol's % change
  = `(today_close − prev_close)/prev_close`. We compute it in ClickHouse with a
  self-join: a `today` CTE (close on the requested date) joined to a `prev` CTE
  (`argMax(value, date)` over the prior 14 days, so a holiday gap doesn't drop the
  symbol). The heatmap is the same join, then `avg()` grouped by the sector tag.

Doing the comparison in SQL (not Python) means we move two numbers per symbol over
the wire, not the whole price history.

## Skip-not-crash on messy real-world files

Bhavcopy and FII/DII files contain rows we can't use: suspended scrips with blank
prices, settlement-series rows, the occasional malformed line. Every source
validates each row through pydantic and **skips** bad ones with a logged warning —
it never inserts `NaN` and never lets one bad row abort the whole day. A signed
caveat: FII/DII *net flow* can legitimately be negative (net selling), so its
validator rejects only missing/non-numeric values, never the sign. Compare with
the price validator, which also rejects negatives (a price can't be below zero).

## Parsing irregular, layout-drifting sources

Phase 1/2 sources have stable shapes (a JSON API, a fixed CSV header). The RBI
DBIE sources are the opposite: there is **no contract**. Excel workbooks rename
columns and reshuffle rows between releases; the NPA PDF's table layout shifts.
Three habits make this survivable:

1. **Locate, don't assume.** Instead of hard-coding "the date is column A," the
   Excel parser scans the first ~10 rows for a header cell that *looks like* a
   date column and one that looks like a value column (keyword substring match).
   If it can't find both, it logs `excel_unknown_layout` and returns `[]` — the
   job succeeds with zero rows rather than crashing on a renamed header.
2. **Validate every cell, skip the bad ones.** Each candidate row goes through
   `RBIDataPoint` (numeric guard). Footnotes, totals, "n/a", and blank rows fail
   validation and are skipped with a warning. One malformed row never aborts the
   release.
3. **Trust the data's own dates.** DBIE rows carry their observation date; we
   parse it flexibly (real Excel dates, `YYYY-MM-DD`, `Mar-2026`, `March 2026`)
   and fall back to skipping a row whose date we can't read.

This is the same skip-not-crash discipline as the CSV sources, pushed harder
because the input is less trustworthy. The unit tests prove it: a fixture with a
renamed-column sheet returns `[]`, and a PDF with an "n/a" ratio and a non-quarter
"All Banks" row yields exactly the three valid quarters.

## Revisions and idempotent re-pull

DBIE workbooks contain the full history every time you download them, and RBI
revises recent figures. We don't try to fetch "just the new rows" — the weekly job
re-pulls the whole workbook and re-inserts everything. ClickHouse's
ReplacingMergeTree deduplicates on `(source, series, dimension, date)` keeping the
latest `fetched_at`, so a revised value transparently replaces the old one and a
re-pull of unchanged data is a no-op. This is the [idempotency](#idempotency) and
[data-revision](#data-revisions-scd-type-2) machinery from Phase 1, now doing real
work on a genuinely-revising source.
