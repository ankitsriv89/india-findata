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
