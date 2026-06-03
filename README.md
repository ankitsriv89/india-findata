# india-findata

Batch data pipeline and analytics dashboard for Indian financial and economic data.

Pulls from government portals (RBI, MOSPI, NSE/BSE, SEBI, data.gov.in), normalizes into a
universal time-series schema, stores in ClickHouse, and serves a React dashboard.

**Not real-time.** Each source is fetched on its natural cadence — daily for market prices,
weekly for RBI supplements, monthly for CPI/GDP/IIP.

---

## Stack

| Layer | Technology |
|-------|-----------|
| Scrapers / pipeline | Python 3.12, httpx, openpyxl, BeautifulSoup4 |
| Data validation | Pydantic v2 |
| Scheduling | APScheduler (embedded in FastAPI) |
| Analytics storage | ClickHouse (ReplacingMergeTree) |
| Pipeline metadata | PostgreSQL |
| Query API | FastAPI |
| Dashboard | React + Vite (TypeScript), Recharts, D3.js |
| Observability | Prometheus + Grafana |
| Infra | Docker Compose (self-contained) |

---

## Data Sources

| Source | Data | Access | Cadence |
|--------|------|--------|---------|
| [data.gov.in](https://www.data.gov.in) | RBI rates, banking aggregates, SEBI stats | Official REST API (OGL) | Monthly–Quarterly |
| [MOSPI esankhyiki](https://esankhyiki.mospi.gov.in) | CPI, IIP, WPI, GDP | Official API + CSV | Monthly (CPI/IIP: 12th) |
| [NSE bhavcopy](https://www.nseindia.com/all-reports) | Equity EOD prices, FII/DII | Official CSV download | Daily 7 PM IST |
| [BSE bhavcopy](https://www.bseindia.com/markets/MarketInfo/BhavCopy) | Equity EOD prices | Official CSV download | Daily at market close |
| [RBI DBIE](https://data.rbi.org.in) | Forex reserves, repo rate, M3, credit | HTML/Excel parse | Weekly/Monthly |
| [SEBI via NSE](https://www.nseindia.com/reports/fii-dii) | FII/DII flows, MF data | Official file download | Daily/Monthly |

All access uses official APIs or explicitly provided bulk download files. No dynamic page scraping.

---

## Universal Record Schema

Every source normalizes to a flat `Record`:

```python
Record(
    source      = "nse_bhavcopy",        # source identifier
    series      = "NIFTY50",             # what is being measured
    dimension   = "close_price",         # which aspect of the series
    value       = 24356.78,              # the number
    date        = date(2026, 6, 2),      # observation date
    granularity = "daily",               # daily | monthly | quarterly
    unit        = "INR",                 # INR | percent | index_points | USD
    region      = "india",               # india | sector:IT | mumbai
    tags        = {"symbol": "NIFTY50"}, # additional dimensions
    fetched_at  = datetime(...)          # when this pipeline run fetched it
)
```

ClickHouse uses `ReplacingMergeTree(fetched_at)` — re-inserting a revised value
(e.g. GDP preliminary → final) automatically replaces the older fetch.

---

## Build Phases

### Phase 1 — Macro Foundation
- Sources: MOSPI CPI/IIP/GDP, data.gov.in (RBI rates)
- Dashboard: CPI timeline, repo rate history, GDP growth bars
- Complexity: low — official JSON APIs

### Phase 2 — Markets Layer
- Sources: NSE/BSE bhavcopy, FII/DII flows
- Dashboard: NIFTY50 chart, FII net flow vs index, top movers
- Complexity: medium — CSV parsing, date normalization

### Phase 3 — Banking & Credit
- Sources: RBI DBIE — M3, bank credit, forex reserves, NPA data
- Dashboard: credit growth vs GDP, money supply trends
- Complexity: high — HTML/Excel parsing, irregular schemas

### Phase 4 — Cross-domain Analytics
- CPI vs repo rate vs equity market correlation
- FII inflows vs INR/USD
- IIP sector data vs NSE sectoral indices

---

## Quick Start

```bash
# Copy and fill in API keys (data.gov.in and MOSPI tokens)
cp .env.example .env

# Start all services
docker compose up -d

# Run initial backfill (Phase 1 sources, last 5 years)
python -m scripts.backfill --from 2021-01-01

# Open dashboard
open http://localhost:5190

# API
curl http://localhost:8090/macro/cpi?from=2023-01-01
```

---

## Ports

| Service | Port |
|---------|------|
| FastAPI | 8090 |
| React dev (Vite) | 5190 |
| ClickHouse HTTP | 8123 |
| PostgreSQL | 5433 |
| Grafana | 3200 |
| Prometheus | 9091 |

---

## Repo Structure

```
india-findata/
├── pipeline/
│   ├── sources/        — one file per data source (fetch + normalize)
│   ├── schema/         — Record dataclass + pydantic validators
│   ├── store/          — ClickHouse + Postgres loaders
│   ├── scheduler.py    — APScheduler job registration
│   └── main.py         — FastAPI app + scheduler startup
├── api/
│   └── routes/         — macro.py, markets.py, pipeline.py
├── web/                — React + Vite TypeScript dashboard
├── scripts/            — backfill.py, migrate.sql, seed.sh
└── docs/               — architecture, sources catalogue, tutorial
```
