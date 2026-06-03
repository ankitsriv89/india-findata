# pipeline/ — Batch Extraction & Load Pipeline

## Overview

The pipeline package contains everything between "fetch from source" and "rows in ClickHouse".
It runs as a long-lived Python process: FastAPI serves the query API while APScheduler fires
fetch jobs on their configured cron schedules.

---

## packages

### `pipeline/schema/record.py`

```python
from dataclasses import dataclass, field
from datetime import date, datetime

@dataclass
class Record:
    """
    Universal time-series record. Every source normalizes its output to this
    before inserting into ClickHouse. Keeping one schema means the dashboard
    and API never need to know which source produced a row.
    """
    source:      str              # "nse_bhavcopy" | "mospi_cpi" | "rbi_rates" | ...
    series:      str              # "NIFTY50" | "CPI_GENERAL" | "REPO_RATE"
    dimension:   str              # "close_price" | "index_value" | "rate_pct"
    value:       float
    date:        date             # observation date (not fetch date)
    granularity: str              # "daily" | "monthly" | "quarterly"
    unit:        str              # "INR" | "percent" | "index_points" | "USD" | "crore_INR"
    region:      str              # "india" | "sector:IT" | "mumbai"
    tags:        dict[str, str]   # {"symbol": "TCS", "sector": "IT", "release": "final"}
    fetched_at:  datetime = field(default_factory=datetime.utcnow)
```

### `pipeline/schema/validators.py`

Pydantic v2 models for each source type — validates column names, value ranges,
date formats. Used before `store.clickhouse.insert_batch()`.

```python
class NSERecord(BaseModel):
    SYMBOL: str
    SERIES: str
    OPEN: float
    HIGH: float
    LOW: float
    CLOSE: float
    TOTTRDQTY: int
    TIMESTAMP: str  # "02-JUN-2026" format
    # ... etc
```

---

### `pipeline/sources/base.py`

```python
from abc import ABC, abstractmethod
from pipeline.schema.record import Record

class Source(ABC):
    """
    Base class for all data sources. Each source implements fetch() which
    returns a list of Records ready for ClickHouse insertion.

    fetch() must be idempotent — calling it twice for the same date range
    produces the same records. The store layer uses ReplacingMergeTree to
    handle duplicates if fetch() is retried.
    """
    name: str  # used in logs and pipeline_runs table

    @abstractmethod
    def fetch(self, target_date: date) -> list[Record]:
        """Fetch data for target_date. Returns empty list if no data available yet."""
        ...

    @abstractmethod  
    def backfill(self, from_date: date, to_date: date) -> list[Record]:
        """Fetch all available data between from_date and to_date inclusive."""
        ...
```

---

### `pipeline/sources/mospi.py` — MOSPI CPI / IIP / WPI / GDP

**API**: MOSPI has an official CPI API at `api.mospi.gov.in`. Requires a free signup for
an API token. Also supports bulk CSV download from esankhyiki portal.

**CPI series IDs** (from MOSPI API docs):
- `CPI_GENERAL` — all-India CPI (General)
- `CPI_FOOD` — food and beverages sub-index
- `CPI_RURAL`, `CPI_URBAN` — rural/urban breakdowns

**Fetch pattern**:
```python
# GET https://api.mospi.gov.in/cpi?from=2024-01&to=2026-06&token=<token>
# Returns JSON: [{"month": "2024-01", "value": 190.3, "series": "CPI_GENERAL"}, ...]
```

**IIP** (Index of Industrial Production): same API with different endpoint.
Released monthly on the 12th at 4 PM IST for the month 2 months prior
(e.g. April IIP released on June 12th). Build in a 5-day polling window.

**GDP**: quarterly, ~60 days after quarter end. Available via data.gov.in backup.

**Normalization to Record**:
- `source = "mospi_cpi"`
- `series = "CPI_GENERAL"` (etc.)
- `dimension = "index_value"`
- `granularity = "monthly"`
- `unit = "index_points"`
- `tags = {"base_year": "2012", "release": "final"}`

---

### `pipeline/sources/data_gov_in.py` — data.gov.in REST API

**API**: `https://api.data.gov.in/resource/<resource_id>?api-key=<key>&format=json`

Rate limit: 1,000 requests/hour. Use `time.sleep(3.6)` between requests in batch loops
(= 1000 req/hr → 1 req per 3.6s).

**Key resource IDs** (to confirm at implementation time):
- RBI repo rate history
- RBI forex reserves (weekly)
- SEBI mutual fund monthly data
- Banking credit growth

**Pagination**: responses include `total` and `offset` — iterate with `offset` parameter
until all records fetched.

**Normalization**: map response JSON fields to Record fields. Source-specific tags carry
original field names for traceability.

---

### `pipeline/sources/nse.py` — NSE Bhavcopy (Equity EOD)

**URL pattern** (official NSE bulk download):
```
https://archives.nseindia.com/content/historical/EQUITIES/<YYYY>/<MON>/cm<DD><MON><YYYY>bhav.csv.zip
# Example: cm02JUN2026bhav.csv.zip
```

No authentication required for historical bhavcopy. After market close (~6:30 PM IST),
today's file becomes available around 7 PM.

**CSV columns** (bhavcopy format):
`SYMBOL, SERIES, OPEN, HIGH, LOW, CLOSE, LAST, PREVCLOSE, TOTTRDQTY, TOTTRDVAL, TIMESTAMP, TOTALTRADES, ISIN`

**Filter to EQ series** (equity only — skip BE, BL, etc.).

**Normalization**: one Record per symbol per day:
- `source = "nse_bhavcopy"`
- `series = symbol` (e.g. "TCS")
- `dimension = "close_price"` (also emit open/high/low as separate dimensions)
- `granularity = "daily"`
- `unit = "INR"`
- `tags = {"exchange": "NSE", "series": "EQ", "isin": "..."}`

**FII/DII data** (separate NSE report):
```
https://www.nseindia.com/api/fiidiiTradeReact  — JSON endpoint after login (complex auth)
```
Alternative: download the FII/DII Excel report from NSE reports page. Implement as separate
`fetch_fii()` method; may require Selenium if the direct URL requires session cookies.
Mark as Phase 2 — confirm URL availability at implementation time.

---

### `pipeline/sources/bse.py` — BSE Bhavcopy

**URL pattern**:
```
https://www.bseindia.com/download/BhavCopy/Equity/EQ_ISINCODE_<DDMMYY>.ZIP
# Example: EQ_ISINCODE_020626.ZIP  (for 2 June 2026)
```

Same normalization as NSE but `tags = {"exchange": "BSE"}`.

**Deduplication**: many symbols trade on both NSE and BSE. The `series` field uses the
symbol name which may differ slightly. Keep both — the `exchange` tag disambiguates.

---

### `pipeline/sources/rbi.py` — RBI DBIE

**No official API.** Data is in the DBIE portal (data.rbi.org.in) as downloadable Excel files
and HTML tables.

**Approach for Phase 3**:
1. Download the "Weekly Statistical Supplement" PDF/Excel from RBI publications page
2. Parse with `openpyxl` (Excel) or `pdfplumber` (PDF)
3. Map to Records manually — schema varies by publication

**Key datasets to target**:
- Repo rate / reverse repo rate (policy rate history) — also available via data.gov.in
- Foreign exchange reserves (weekly, in USD billion)
- Broad money (M3) — monthly
- Bank credit growth (monthly, by sector)

**Implementation note**: RBI DBIE pages change layout periodically. Build defensively —
log a warning and skip rather than crash when a column is missing. Mark as Phase 3.

---

### `pipeline/sources/sebi.py` — SEBI (FII/DII via NSE)

FII/DII data is published by NSE on behalf of SEBI. The NSE reports page has a CSV export.

Daily FII/DII aggregate (net buy/sell by institutional category):
- `FII_NET_EQUITY` — FII net equity purchase (crore INR)
- `DII_NET_EQUITY` — DII net equity purchase (crore INR)

Monthly mutual fund data (AMFI publishes AUM, flows):
- Available from AMFI (amfiindia.com) as a text file — simpler to parse than SEBI directly

---

## `pipeline/store/clickhouse.py`

```python
def insert_batch(client: clickhouse_connect.Client, records: list[Record]) -> int:
    """
    Insert a batch of Records into ClickHouse using clickhouse-connect.
    Returns the number of rows inserted.

    Uses ReplacingMergeTree's deduplication: if a record with the same
    (source, series, dimension, date) was already inserted, the new
    fetched_at wins and replaces the old value on next merge.
    """
```

Uses `clickhouse-connect` (pure Python, no C driver needed).

Batch size: 1000 records per INSERT. Large bhavcopy files (~2000 symbols × 4 dimensions)
will be split into 8 batches.

---

## `pipeline/store/postgres.py`

Table: `pipeline_runs`
```sql
CREATE TABLE pipeline_runs (
    id           SERIAL PRIMARY KEY,
    source       VARCHAR(64) NOT NULL,
    job_id       VARCHAR(128),
    started_at   TIMESTAMPTZ NOT NULL,
    finished_at  TIMESTAMPTZ,
    rows_fetched INTEGER DEFAULT 0,
    rows_inserted INTEGER DEFAULT 0,
    status       VARCHAR(16) NOT NULL,  -- 'running' | 'success' | 'failed'
    error_msg    TEXT
);
```

Every job writes a row on start (status='running'), updates on completion (success/failed).
This powers the Pipeline Status tab in the dashboard.

---

## `pipeline/scheduler.py`

```python
from apscheduler.schedulers.background import BackgroundScheduler

scheduler = BackgroundScheduler(timezone="Asia/Kolkata")

# NSE + BSE bhavcopy — daily at 7 PM IST (after NSE processes EOD)
scheduler.add_job(run_nse_job,  'cron', hour=19, minute=0)
scheduler.add_job(run_bse_job,  'cron', hour=19, minute=15)

# SEBI FII/DII — daily at 7:30 PM IST
scheduler.add_job(run_fii_job,  'cron', hour=19, minute=30)

# MOSPI CPI/IIP — monthly, poll window: days 11-16 of each month at 4:30 PM
scheduler.add_job(run_mospi_job, 'cron', day='11-16', hour=16, minute=30)

# RBI forex/rates — weekly on Friday at 6 PM IST
scheduler.add_job(run_rbi_job,  'cron', day_of_week='fri', hour=18, minute=0)

# data.gov.in — weekly Sunday at 2 AM IST
scheduler.add_job(run_datagov_job, 'cron', day_of_week='sun', hour=2, minute=0)
```

Each `run_X_job()` function:
1. Writes `pipeline_runs` row with status='running'
2. Calls `source.fetch(today)`
3. Calls `store.clickhouse.insert_batch(records)`
4. Updates `pipeline_runs` row with status='success' or 'failed' + error_msg

---

## `pipeline/main.py`

```python
# Starts FastAPI app and APScheduler in the same process.
# On startup: apply DB migrations, verify ClickHouse connection, start scheduler.
# On shutdown: gracefully stop scheduler, close DB connections.
```

FastAPI lifespan events handle startup/shutdown cleanly.
