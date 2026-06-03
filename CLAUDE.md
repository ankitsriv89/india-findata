# india-findata — Claude Instructions

This file is read at the start of every session. All instructions are mandatory.

---

## Repo identity

This is a **batch data pipeline + analytics dashboard** for Indian financial and economic data.
It is NOT a streaming platform — see `datastream-lab` for that. Data is pulled on schedules
matched to source cadence (daily, weekly, monthly, quarterly).

- **Backend language**: Python 3.12+
- **Frontend**: React + Vite (TypeScript) — no Next.js, no SSR
- **Storage**: ClickHouse (time-series analytics) + PostgreSQL (pipeline metadata)
- **Orchestration**: APScheduler embedded in FastAPI — no Airflow
- **Package manager**: `uv` (not pip, not poetry)
- **Linting**: ruff + mypy
- **Testing**: pytest

---

## Comments and tutorials — this repo is a learning resource

Comments and documentation are **tutorial-grade** — explain what AND why for non-obvious patterns.
This is a learning resource, not production code.

**Python code comments:**
- Every module gets a module-level docstring explaining its role in the pipeline
- Every class and public function gets a docstring: what it does, parameters, return value, side effects
- Non-obvious logic gets inline comments explaining the reasoning
- Data source quirks (irregular column names, missing data, encoding issues) always documented inline
- Every `try/except` block explains what error is expected and why

**Tutorial docs (`docs/tutorial.md`) — required:**
- Step-by-step walkthrough: "How does data flow from RBI to the dashboard?"
- Every non-obvious Python pattern explained: `@dataclass`, pydantic validators, APScheduler decorators
- "Try it yourself" prompts suggesting experiments (change schedule, add a new source, backfill more history)

**`docs/concepts.md` — required:**
- Explains batch pipeline patterns: idempotency, backfill, incremental load, data revisions (SCD Type 2)
- Written for someone who knows programming but hasn't built data pipelines before

---

## Python conventions

### Structure
Every source follows the same pattern:
```
pipeline/sources/<name>.py  — fetches and normalizes to Record dataclass
pipeline/store/              — loads Records into ClickHouse / logs run to Postgres
pipeline/scheduler.py        — registers jobs with APScheduler
pipeline/main.py             — starts scheduler + FastAPI app
```

### Error handling
- Wrap errors with context: `raise RuntimeError(f"mospi: fetch CPI: {e}") from e`
- Log every pipeline run result (rows fetched, rows inserted, errors) to Postgres `pipeline_runs` table
- A source failure must NOT crash the scheduler — catch at job level, log, continue

### Logging
- Use `structlog` for structured logging (JSON lines in production, coloured in dev)
- Every log entry includes `source=`, `job_id=`, and for errors: `error=`
- No `print()` anywhere in pipeline code

### HTTP clients
- Use a module-level `httpx.Client` (sync) or `httpx.AsyncClient` (async) — never create per-request
- Set explicit timeouts: `httpx.Client(timeout=30.0)`
- Respect rate limits: data.gov.in = 1000 req/hr; add `time.sleep` between calls when batching

### Data validation
- All records pass through pydantic validators before insertion
- Unknown/null values for `value` field: skip the record, log a warning — never insert NaN

### Testing
- Unit tests for each source's `parse()` logic using fixture files in `tests/fixtures/`
- No network calls in unit tests — use `httpx.MockTransport` or fixture CSVs
- Run: `pytest tests/ -v`

---

## Storage conventions

### ClickHouse
- All time-series data into the `records` table (ReplacingMergeTree)
- Always use `INSERT INTO records ... FORMAT JSONEachRow` for batch inserts
- Never DELETE — use ReplacingMergeTree's deduplication for corrections
- Partitioned by `toYYYYMM(date)` — queries always filter on date range first

### PostgreSQL
- `pipeline_runs` table: source, job_id, started_at, finished_at, rows_fetched, rows_inserted, status, error_message
- Used only for pipeline metadata — no analytics data here

---

## Frontend conventions

- React + Vite + TypeScript — no class components, hooks only
- Charting: **Recharts** for line/bar/area, **D3.js** for custom heatmaps
- No `innerHTML` with API data — always `textContent` or React's JSX rendering
- Tabs: Macro | Markets | Correlation | Pipeline
- API base URL from `VITE_API_URL` env var (default `http://localhost:8090`)
- No mock data in components — all data from real API calls

---

## Workflow: after every successful implementation

After `pytest tests/`, `ruff check .`, `mypy pipeline/` all pass:

1. `docs/architecture.md` — Mermaid diagram of full pipeline + query path
2. `docs/concepts.md` — batch pipeline concepts: idempotency, backfill, revisions
3. `docs/sources.md` — data source catalogue: fields, cadence, example values
4. `docs/tutorial.md` — walkthrough for Python + ClickHouse beginners
5. `docs/build-log.md` — Python version, deps, test output
6. `docs/changelog.md` — Keep a Changelog format, start at 0.1.0

Commit message: `feat(india-findata): <description>`

---

## Port assignments

| Service | Port |
|---------|------|
| FastAPI (query + pipeline API) | 8090 |
| React dev server (Vite) | 5190 |
| ClickHouse HTTP | 8123 |
| ClickHouse native | 9001 |
| PostgreSQL | 5433 |
| Prometheus | 9091 |
| Grafana | 3200 |

(All chosen to avoid conflicts with system-design projects and datastream-lab)

---

## What never to do

- No `print()` in pipeline code — use structlog
- No hardcoded API keys — use environment variables, loaded from `.env` (gitignored)
- No scraping of dynamic NSE/BSE pages — only official bulk download CSV endpoints
- No `time.sleep()` in request handlers — only in batch fetch loops with explicit rate-limit comments
- No Airflow, no Celery, no Redis — APScheduler only for POC scale
- No `pandas` in hot paths — use Python stdlib `csv` module for large CSV parsing
- Never commit `.env` or `secrets.json`
