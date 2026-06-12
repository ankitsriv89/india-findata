# Tutorial: How data flows from RBI to the dashboard

This walkthrough traces one data point — the RBI repo rate — all the way from the government API to the chart in your browser. Follow along to understand how the entire pipeline works.

---

## Step 1: Start the stack

```bash
# Clone the repo and start all services
docker compose up -d

# Wait for services to be healthy (~30 seconds)
docker compose ps
```

You should see all services `healthy`: clickhouse, postgres, api, web.

---

## Step 2: Apply database migrations

The `records` table (ClickHouse) and `pipeline_runs` table (PostgreSQL) don't exist yet. Create them:

```bash
bash scripts/seed.sh
```

This runs `scripts/migrate.sql` against both databases and then triggers a backfill of all Phase 1 sources from 5 years ago.

**Try it yourself**: Open a ClickHouse shell and inspect the table:
```bash
docker exec -it india-findata-clickhouse-1 clickhouse-client
> SELECT count() FROM indiafindata.records;
> DESCRIBE TABLE indiafindata.records;
```

---

## Step 3: Trace a fetch job

The RBI rates source fetches from `data.gov.in`. Let's trace what happens when the scheduler fires:

**1. APScheduler calls `_run_job(rbi_rates_src, ...)`** (in `pipeline/scheduler.py`):
```python
run_id = pg_store.start_run(pool, "rbi_rates", "rbi_rates")
records = rbi_rates_src.fetch(today)
rows_inserted = ch_store.insert_batch(ch_client, records)
pg_store.finish_run(pool, run_id, ..., status="success")
```

**2. `RBIRatesSource.fetch()` calls `_fetch_rates()`** (in `pipeline/sources/data_gov_in.py`):
```python
resp = self._client.get(
    "https://api.data.gov.in/resource/<resource_id>",
    params={"api-key": key, "format": "json", "limit": 100}
)
```

**3. Raw JSON is parsed into Records** via `_parse_rate_record()`:
```python
# Raw API row:
{"effective_date": "2024-02-08", "repo_rate": "6.50", "reverse_repo_rate": "3.35"}

# After parsing → Record:
Record(
    source="rbi_rates",
    series="REPO_RATE",
    dimension="rate_pct",
    value=6.5,
    date=date(2024, 2, 8),
    granularity="daily",
    unit="percent",
    region="india",
    tags={"type": "policy_rate"},
)
```

**4. `ch_store.insert_batch()` inserts to ClickHouse**:
```python
client.insert("records", rows, column_names=[...])
```
ClickHouse stores this as a row in the `records` table.

---

## Step 4: Query via FastAPI

The React dashboard calls `GET /macro/rates?series=REPO_RATE&from=2020-01-01`.

The route handler in `api/routes/macro.py` runs:
```sql
SELECT date, value
FROM records FINAL
WHERE source = 'rbi_rates'
  AND series = 'REPO_RATE'
  AND date BETWEEN '2020-01-01' AND '2024-06-08'
ORDER BY date
```

**Why `FINAL`?** Without it, ClickHouse might return duplicate rows if a background merge hasn't run yet. `FINAL` forces deduplication before returning results.

**Try it yourself**:
```bash
curl "http://localhost:8090/macro/rates?series=REPO_RATE&from=2022-01-01" | python -m json.tool
```

---

## Step 5: The chart renders

In `web/src/components/charts/RepoRateChart.tsx`:

```typescript
const { data: repoResp } = useRates(from, to, 'REPO_RATE')

// TanStack Query calls GET /macro/rates and caches the result for 5 minutes
// On success, the chart re-renders with the new data
```

The chart uses `type="stepAfter"` in Recharts because repo rates change discretely on MPC meeting dates — a step function is more accurate than a smooth curve.

---

## Try it yourself: experiments

1. **Add a new rate series**: modify `_parse_rate_record()` to also extract CRR (Cash Reserve Ratio) from the API response. Add it to the chart.

2. **Change the backfill start date**: run `python -m scripts.backfill --source rbi_rates --from 2000-01-01` to get 24 years of rate history.

3. **Watch a job fire**: set the scheduler to run every minute for testing:
   ```python
   # In scheduler.py, temporarily change:
   CronTrigger(minute='*/1')  # every minute
   ```
   Watch the Pipeline tab update in real time.

4. **Inspect the data revision mechanism**: run a backfill twice for the same date range. Check ClickHouse:
   ```sql
   SELECT count() FROM records WHERE source = 'rbi_rates';
   SELECT count() FROM records FINAL WHERE source = 'rbi_rates';
   -- FINAL count should be ≤ raw count (deduplication in action)
   ```

---

## Python patterns explained

### `@dataclass` for Record

```python
@dataclass
class Record:
    source: str
    value: float
    # ...
    fetched_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
```

`@dataclass` auto-generates `__init__`, `__repr__`, `__eq__` from the field annotations. `field(default_factory=...)` is used instead of `field(default=datetime.now())` because a default with `()` would be evaluated once at class definition time — every instance would share the same timestamp.

### Pydantic validators

```python
class MOSPISeriesPoint(BaseModel):
    @field_validator("value", mode="before")
    @classmethod
    def coerce_value(cls, v):
        if v == "-" or v is None:
            raise ValueError(f"Missing value: {v!r}")
        return float(v)
```

`mode="before"` means the validator runs on the raw input before Pydantic tries to coerce the type. This lets us intercept MOSPI's `"-"` missing-value sentinel before it causes a float conversion error.

### APScheduler `coalesce=True`

```python
scheduler.add_job(fn, coalesce=True, max_instances=1)
```

`coalesce=True`: if the server was down and missed 3 scheduled fires, run the job once when it comes back (not 3 times). `max_instances=1`: if a fetch takes longer than the schedule interval, don't start a second instance in parallel.

---

## Phase 2: Trace a bhavcopy fetch (Markets layer)

The macro walkthrough above traces a JSON-API fetch. The Markets sources work a
little differently — they download a ZIP, unzip it in memory, and parse a CSV with
the stdlib. Let's follow one NSE day end-to-end.

### 1. The source builds a URL and downloads a ZIP

`NSEBhavcopySource.fetch(date(2026, 6, 2))` builds the archive URL
`…/EQUITIES/2026/JUN/cm02JUN2026bhav.csv.zip` and GETs it with a module-level
`httpx.Client`. A 404 means a non-trading day (weekend/holiday) — the source
returns `[]` rather than raising, so the scheduler just logs "no file" and moves on.

### 2. Unzip in memory, parse with stdlib `csv`

```python
with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
    csv_bytes = zf.read(<the one .csv member>)
reader = csv.DictReader(io.StringIO(csv_bytes.decode("latin-1")))
```

No temp files, no pandas — exactly the constraints in CLAUDE.md. Each row is
filtered to `SERIES == "EQ"`, validated through the `BhavcopyRow` pydantic model
(which coerces price/volume strings to floats and rejects blanks), and expanded
into **five** `Record`s: `open_price`, `high_price`, `low_price`, `close_price`,
`volume`.

### 3. Insert (chunked) and query cross-sectionally

`insert_batch` writes the ~10k records in 1000-row chunks. Now the movers endpoint
can answer "top 10 gainers on 2026-06-02":

```bash
curl "http://localhost:8090/markets/movers?date=2026-06-02&exchange=NSE&n=10"
```

ClickHouse joins each symbol's close on that date to its previous close and returns
the sorted `%change` — the API splits the sorted list into gainers (head) and
losers (tail).

### 4. The D3 heatmap renders

`/markets/heatmap` returns `[{sector, change_pct, symbols}]`. `SectorHeatmap.tsx`
is the repo's first D3 component: React owns the `<svg>` element via `useRef`, and a
`useEffect` runs D3 imperatively to draw one coloured rectangle per sector
(red→white→green diverging scale). React and D3 share exactly one boundary — the
svg node — which keeps them from fighting over the DOM.

### Try it yourself

- **Backfill a week of equity data**:
  `uv run python -m scripts.backfill --source nse_bhavcopy --from 2026-06-01 --to 2026-06-07`
  (weekends will simply produce no file).
- **Add a sector tag**: bhavcopy doesn't carry sectors. Extend `nse.py` to map ISIN
  or symbol → sector (e.g. a small lookup dict) and set `region = "sector:IT"`. The
  heatmap will immediately group by your new sectors.
- **Change the dimension**: hit `/markets/equity?symbol=TCS&dimension=volume` and
  watch the IndexChart-style series switch from price to traded shares.

## More Python patterns explained (Phase 2)

### In-memory ZIP handling — `io.BytesIO` + `zipfile`
`zipfile.ZipFile` accepts any file-like object, so wrapping the downloaded
`bytes` in `io.BytesIO` lets us read the archive without ever touching disk. The
source stays stateless and there's nothing to clean up.

### `model_validate({...})` vs keyword construction
The sources build a dict and call `BhavcopyRow.model_validate(raw_dict)` rather
than `BhavcopyRow(open=..., ...)`. Pydantic v2's `model_validate` accepts `Any`,
which lets the `mode="before"` field validators coerce the raw CSV strings — and
keeps `mypy --strict` happy (it would otherwise flag `str` passed to a `float`
field at the call site).

---

## Phase 3: Parse a PDF table (Banking layer)

The RBI gross-NPA ratio only exists as a PDF. Here's how `RBIDBIESource.parse_npa`
turns it into Records — the repo's first PDF-parsing path.

### 1. Open the PDF and pull every table

```python
with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
    tables = []
    for page in pdf.pages:
        tables.extend(page.extract_tables() or [])
```

`extract_tables()` returns each table as a list of rows, each row a list of cell
strings. It works best when the PDF has real ruled lines — which is why the test
fixture is generated with reportlab's `GRID` table style.

### 2. Keep rows that look like (quarter, ratio)

For each row we read `row[0]` (quarter label) and `row[1]` (ratio). The label goes
through the **same** fiscal-quarter parser the GDP source uses
(`Q1 2025-26 → 2025-04-01`); if it isn't a quarter (a header, a "All Banks" total),
the parser returns `None` and we skip the row. The ratio goes through
`RBIDataPoint`, which rejects "n/a"/blank. Survivors become quarterly Records with
`series="GROSS_NPA_RATIO"`, `unit="percent"`.

### 3. Query it like anything else

```bash
curl "http://localhost:8090/banking/npa?from=2024-01-01&to=2026-06-01"
```

Same `TimeSeriesResponse` envelope as every other endpoint — the universal Record
schema means a PDF-sourced series and a JSON-API series are indistinguishable
downstream. `NPAChart.tsx` renders it as colour-graded quarterly bars.

### Excel is the same idea

`parse_excel` opens the workbook with `openpyxl.load_workbook(..., read_only=True,
data_only=True)`, locates the date/value columns by header keywords, and applies the
same validate-and-skip loop. Forex, M3, and bank-credit all flow through it with
different `(series, unit, granularity)` metadata.

### Try it yourself

- **Break the layout on purpose**: rename a column header in
  `tests/fixtures/rbi_wss_sample.xlsx` (regenerate it) and watch `parse_excel`
  return `[]` with an `excel_unknown_layout` warning instead of crashing.
- **Add a DBIE series**: pick another DBIE workbook (e.g. CRR/SLR), add an entry to
  `_EXCEL_META` in `rbi.py` and a `/banking/...` endpoint — no schema changes
  needed.

## More Python patterns explained (Phase 3)

### `openpyxl` read-only + `data_only`
`read_only=True` streams the worksheet (bounded memory for large workbooks);
`data_only=True` returns cached cell *values* rather than formula strings. Together
they give clean `(date, number)` tuples without evaluating formulas.

### Keyword-based column location
`_locate_columns` does a tiny "schema inference": it treats any header containing
"date"/"week"/"month" as the date column and "value"/"reserves"/"credit"/… as the
value column. It's deliberately fuzzy because DBIE's exact wording drifts — better
to match loosely and validate the cells than to hard-code a brittle column index.

---

## Phase 4: Build a correlation (Analytics layer)

The Correlation tab lets you ask "do inflation and the repo rate move together?"
Here's the round trip.

### 1. Pick two series

`SeriesSelector` offers a catalogue spanning every layer — CPI, GDP, repo rate,
forex, M3, credit, NPA, FII/DII. Each option carries the `source` and `series` the
API needs. The panel defaults to CPI_GENERAL vs REPO_RATE.

### 2. The API aligns and computes

```bash
curl "http://localhost:8090/analytics/correlation?\
source_a=mospi_cpi&series_a=CPI_GENERAL&\
source_b=rbi_rates&series_b=REPO_RATE&from=2020-01-01&to=2026-06-01"
```

`get_correlation` pulls each series as a `{date: value}` dict, intersects the
dates, computes Pearson r and the best lag, and returns the aligned rows:

```json
{
  "series_a": "CPI_GENERAL", "series_b": "REPO_RATE",
  "n": 42, "pearson_r": 0.78, "best_lag": 2, "best_lag_r": 0.83,
  "data": [{"date": "2020-01-01", "a": 150.1, "b": 5.15}, ...]
}
```

### 3. The chart renders both axes + annotations

`DualAxisChart` plots A on the left axis and B on the right (their units differ, so
a shared axis would squash one). `useAnnotations()` overlays curated event dates as
vertical `ReferenceLine`s — the same Recharts primitive RepoRateChart uses for its
4% line. `CorrCoeff` shows the r badge with a strength label and the lag hint.

### Try it yourself

- **Find a lead/lag pair**: correlate *Bank credit growth* vs *GDP growth* and watch
  `best_lag` — does credit lead output?
- **Spot a spurious correlation**: pick two unrelated series over a short window and
  see how a high r can appear by chance (the `n` badge keeps you honest).
- **Add an event**: append a date to `_ANNOTATIONS` in `analytics.py` and it shows
  up as a new reference line — no rebuild of the data needed.

## More Python patterns explained (Phase 4)

### `statistics` over numpy/pandas
Pearson r needs only means and standard deviations. `statistics.fmean` and
`statistics.pstdev` (population stdev — we have the whole sample, not an estimate)
do it in stdlib. For POC-scale series this is plenty, and the explicit covariance
loop reads like the textbook formula — better for a learning repo than a one-line
`df.corr()` that hides the maths.

### `zip(..., strict=True)`
Pairing the two aligned series uses `zip(xs, ys, strict=True)` so that a
length mismatch raises instead of silently truncating — a small correctness guard
that documents the invariant "these two lists are the same length here."
