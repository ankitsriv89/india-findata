# Changelog

All notable changes to this project. Format: [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

---

## [0.3.0] — 2026-06-12

### Added

**Banking & Credit source (Phase 3)**
- `pipeline/sources/rbi.py` — `RBIDBIESource`: RBI DBIE indicators in one source.
  Excel via openpyxl (forex weekly, M3 + bank-credit monthly), PDF via pdfplumber
  (gross NPA quarterly). Defensive parsing — unknown columns / malformed rows are
  skipped with a warning, never crash the job.
- `pipeline/schema/validators.py` — `RBIDataPoint` (numeric guard; keeps sign for
  growth/credit values)
- `pdfplumber` runtime dep; `reportlab` dev dep (generates the NPA fixture PDF)

**API routes**
- `GET /banking/forex` · `GET /banking/m3` · `GET /banking/credit` · `GET /banking/npa`
  — all `TimeSeriesResponse` via the shared `_query_records` helper

**Frontend — new 5th tab (Macro | Markets | Banking | Correlation | Pipeline)**
- `web/src/components/BankingPanel.tsx` (Banking tab live)
- `charts/ForexReservesChart.tsx` (weekly area), `charts/M3Chart.tsx` (line),
  `charts/CreditGrowthChart.tsx` (credit vs GDP overlay — reuses `useGDP`),
  `charts/NPAChart.tsx` (quarterly bars, colour-graded by stress)
- `api/hooks.ts` — `useForex`, `useM3`, `useCredit`, `useNPA`
- `App.tsx` Tab union/TABS + `CLAUDE.md` tab list updated to five tabs

**Tests / fixtures**
- `tests/test_rbi.py` (8 tests): Excel parse, missing/non-numeric skip, month
  normalisation, unknown-layout → [], garbage bytes → [], NPA PDF extraction +
  non-quarter/non-numeric skip
- `tests/fixtures/`: `rbi_wss_sample.xlsx`, `rbi_m3_sample.xlsx`,
  `rbi_unknown_layout.xlsx`, `rbi_npa_sample.pdf`

**Wiring**
- `scripts/backfill.py` + `pipeline/scheduler.py` — `rbi_dbie` registered (weekly
  Friday 18:00 IST; one job pulls all DBIE datasets, idempotent re-pull)

### Notes
- 46 pytest pass, ruff clean, new Phase 3 code mypy-clean, web build green.
- Live DBIE URLs may be IP-blocked from the cloud box like MOSPI — irrelevant to
  this build (fully fixture-tested); revisited in the data-source step.

---

## [0.2.0] — 2026-06-12

### Added

**Markets sources (Phase 2)**
- `pipeline/sources/nse.py` — `NSEBhavcopySource`: daily NSE equity bhavcopy (ZIP→CSV, in-memory unzip, EQ-only filter), OHLC + volume Records per symbol
- `pipeline/sources/bse.py` — `BSEBhavcopySource`: daily BSE equity bhavcopy (different columns, SC_GROUP equity filter)
- `pipeline/sources/sebi.py` — `FIIDIISource`: daily FII/DII net equity flows (negatives valid; best-effort live URL)
- `pipeline/schema/validators.py` — `BhavcopyRow` and `FIIDIIRow` pydantic models (skip-bad-rows, never insert NaN)

**API routes**
- `GET /markets/equity` — per-symbol daily OHLC/volume series (`TimeSeriesResponse`)
- `GET /markets/fii` — FII/DII net flow series
- `GET /markets/movers` — top gainers/losers for a date (close vs prev-close %change in ClickHouse)
- `GET /markets/heatmap` — sector → average %change grid
- `_query_records` gained an `extra_params` argument for safe parameter binding in `extra_where`

**Frontend**
- `web/src/components/MarketsPanel.tsx` — Markets tab (replaces the Phase 2 placeholder)
- `charts/IndexChart.tsx`, `charts/FIIDIIChart.tsx`, `TopMoversTable.tsx`
- `charts/SectorHeatmap.tsx` — **first D3 usage** (React owns the `<svg>`, D3 draws inside via `useRef`+`useEffect`)
- `api/hooks.ts` — `useEquity`, `useFIIDII`, `useMovers`, `useHeatmap`

**Tests / fixtures**
- `tests/test_nse.py`, `tests/test_bse.py`, `tests/test_sebi.py` (15 tests) with committed CSV fixtures

### Fixed
- `pyproject.toml` — added `[tool.hatch.build.targets.wheel]` packages list so `uv sync`/`uv run` (and wheel builds) work; the default heuristic couldn't find `pipeline`/`api`/`scripts`
- `pipeline/sources/data_gov_in.py` — `DataGovInRecord(raw)` → `DataGovInRecord.model_validate(raw)` (pydantic v2 rejects positional construction; this was breaking 5 Phase 1 tests)
- `[tool.ruff.lint.flake8-bugbear]` `extend-immutable-calls` for FastAPI `Query`/`Depends` (silences B008 on endpoint signatures); added `from exc` on `raise HTTPException` sites (B904); repo-wide `ruff --fix` (UP017/UP035/SIM117/I001) — `ruff check .` is now clean

### Notes
- Phase 1 source files (mospi/data_gov_in/scheduler/main) still have pre-existing `mypy --strict` findings; all **new** Phase 2 code is mypy-clean. Strict-mypy cleanup of Phase 1 is tracked separately.

---

## [0.1.0] — 2026-06-08

### Added

**Pipeline core**
- `pipeline/schema/record.py` — universal `Record` dataclass; all sources normalise to this before ClickHouse insertion
- `pipeline/schema/validators.py` — pydantic v2 models for MOSPI and data.gov.in raw API responses
- `pipeline/sources/base.py` — abstract `Source` base class with `fetch()` and `backfill()` interface
- `pipeline/sources/mospi.py` — `MOSPISource` (CPI + IIP) and `MOSPIGDPSource` (GDP via data.gov.in fallback)
- `pipeline/sources/data_gov_in.py` — `RBIRatesSource` (repo/reverse repo) and `RBIForexSource` (weekly forex reserves)
- `pipeline/store/clickhouse.py` — batch insert to ClickHouse `records` table (1000-row chunks)
- `pipeline/store/postgres.py` — pipeline run logging to `pipeline_runs` table
- `pipeline/scheduler.py` — APScheduler job registration for all Phase 1 sources
- `pipeline/config.py` — pydantic-settings configuration loaded from environment/.env
- `pipeline/main.py` — FastAPI app with lifespan (startup/shutdown), CORS, health check

**API routes**
- `GET /macro/cpi` — CPI index values (monthly)
- `GET /macro/iip` — IIP by sector (monthly)
- `GET /macro/gdp` — GDP growth rate (quarterly)
- `GET /macro/rates` — RBI policy rates (step series)
- `GET /pipeline/status` — latest run per source
- `GET /pipeline/runs` — paginated run history
- `GET /health` — ClickHouse + PostgreSQL liveness check

**Frontend**
- React 18 + Vite + TypeScript SPA
- `MacroPanel` with 2×2 chart grid
- `CPIChart` — line + bar (YoY % computed client-side)
- `RepoRateChart` — step line chart with reference line at 4%
- `GDPChart` — bar chart with sign-coloured bars (saffron=positive, red=negative)
- `IIPChart` — grouped bar chart (4 sectors)
- `PipelinePanel` — source status table + run history table
- Date range picker with 1Y/3Y/5Y/10Y presets

**Infrastructure**
- `Dockerfile` (multi-stage Python build)
- `web/Dockerfile` (nginx serving React SPA)
- `docker-compose.yml` (all 6 services: clickhouse, postgres, api, web, prometheus, grafana)
- `infra/terraform/main.tf` — AWS EC2 t3.small in ap-south-1 (~$20/month on-demand, ~$5/month spot)
- `infra/prometheus.yml` — Prometheus scrape config

**Scripts**
- `scripts/migrate.sql` — ClickHouse + PostgreSQL DDL
- `scripts/backfill.py` — CLI for historical data loading
- `scripts/seed.sh` — one-shot setup: migrate + backfill 5 years

**Docs**
- `docs/architecture.md` — Mermaid system diagram + design decisions
- `docs/concepts.md` — batch pipeline concepts (idempotency, backfill, SCD Type 2)
- `docs/sources.md` — data source catalogue
- `docs/tutorial.md` — walkthrough: RBI rate → ClickHouse → dashboard
- `docs/build-log.md` — environment, deps, test commands
- `docs/changelog.md` — this file

**Tests**
- `tests/test_mospi.py` — CPI parse, date normalisation, missing value handling, GDP quarter parsing
- `tests/test_data_gov_in.py` — date format flexibility, RBI rates parse, edge cases
- `tests/fixtures/` — JSON fixture files (no network calls in tests)
