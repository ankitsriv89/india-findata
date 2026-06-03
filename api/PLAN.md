# api/ — FastAPI Query API

## Overview

Thin HTTP layer over ClickHouse. Handles time-range filtering, series selection,
and aggregation parameters. No business logic — all computation happens in ClickHouse SQL.

---

## Routes

### `GET /macro/cpi`
Query CPI index values.

**Parameters**: `from` (date), `to` (date, default today), `series` (default `CPI_GENERAL`)
**ClickHouse query**:
```sql
SELECT date, value, tags['release'] as release
FROM records FINAL
WHERE source = 'mospi_cpi'
  AND series = {series}
  AND date BETWEEN {from} AND {to}
ORDER BY date
```
`FINAL` forces deduplication — ensures we always read the latest revision.

---

### `GET /macro/gdp`
Quarterly GDP growth rate.

**Parameters**: `from`, `to`, `series` (default `GDP_GROWTH_RATE`)

---

### `GET /macro/iip`
Index of Industrial Production by sector.

**Parameters**: `from`, `to`, `sector` (optional filter on `tags['sector']`)

---

### `GET /macro/rates`
RBI policy rates — repo rate, reverse repo, CRR, SLR.

**Parameters**: `from`, `to`, `rate_type` (default all)

---

### `GET /markets/equity`
Equity EOD prices for a symbol or index.

**Parameters**: `symbol` (required), `from`, `to`, `exchange` (NSE/BSE, default NSE)
**Returns**: OHLC + volume per day

---

### `GET /markets/fii`
FII/DII daily net flows.

**Parameters**: `from`, `to`, `category` (FII/DII/both)

---

### `GET /markets/indices`
NIFTY50 and other index values.

**Parameters**: `index` (default NIFTY50), `from`, `to`

---

### `GET /pipeline/status`
Current status of all pipeline jobs — last run time, row count, next scheduled run, error.

**Source**: queries `pipeline_runs` table in PostgreSQL (latest row per source).

---

### `GET /pipeline/runs`
Recent pipeline run history.

**Parameters**: `source` (optional), `limit` (default 50), `status` (success/failed/all)

---

## Response format

All endpoints return:
```json
{
  "series": "CPI_GENERAL",
  "from": "2023-01-01",
  "to": "2026-06-02",
  "granularity": "monthly",
  "unit": "index_points",
  "data": [
    {"date": "2023-01-01", "value": 184.5},
    {"date": "2023-02-01", "value": 185.2}
  ]
}
```

---

## Error handling

- 404: series/symbol not found in records table
- 422: invalid date format (FastAPI handles automatically via pydantic)
- 503: ClickHouse connection failure (health check endpoint: `GET /health`)

---

## Middleware

- CORS: allow `http://localhost:5190` (Vite dev) and production domain
- Request logging: structlog, includes `path`, `method`, `duration_ms`, `status_code`
- Prometheus metrics: `api_request_total`, `api_request_duration_seconds` (per path)
