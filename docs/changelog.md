# Changelog

All notable changes to this project. Format: [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

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
