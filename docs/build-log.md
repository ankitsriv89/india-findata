# Build Log

## Environment

| Component | Version |
|-----------|---------|
| Python | 3.12+ |
| uv | latest |
| Node.js | 20 LTS |
| Docker Compose | v2 |
| ClickHouse | 24.3 |
| PostgreSQL | 16 |

## Dependencies

Key Python packages (see `pyproject.toml` for full list):

| Package | Purpose |
|---------|---------|
| fastapi 0.111+ | HTTP API framework |
| uvicorn[standard] | ASGI server |
| apscheduler 3.10+ | Background job scheduler |
| httpx 0.27+ | HTTP client for source fetches |
| pydantic 2.7+ | Data validation |
| clickhouse-connect 0.7+ | ClickHouse Python driver (pure Python) |
| asyncpg 0.29+ | Async PostgreSQL driver for FastAPI routes |
| psycopg2-binary 2.9+ | Sync PostgreSQL for APScheduler jobs |
| structlog 24+ | Structured logging |

Key frontend packages:

| Package | Purpose |
|---------|---------|
| react 18 | UI framework |
| @tanstack/react-query 5 | Data fetching + caching |
| recharts 2 | Charts (line, bar, step) |
| d3 7 | Custom visualisations (Phase 4 heatmap) |
| axios 1.7 | HTTP client |
| date-fns 3 | Date formatting |
| vite 5 | Build tool |

## Running tests

```bash
# Install dev dependencies
uv sync --all-extras

# Run all tests
pytest tests/ -v

# With coverage
pytest tests/ -v --cov=pipeline --cov-report=term-missing
```

Expected output (Phase 1 tests):
```
tests/test_mospi.py::test_cpi_parse_valid_records PASSED
tests/test_mospi.py::test_cpi_record_fields PASSED
tests/test_mospi.py::test_cpi_skips_missing_values PASSED
tests/test_mospi.py::test_cpi_date_normalisation PASSED
tests/test_mospi.py::test_cpi_release_tag PASSED
tests/test_mospi.py::test_parse_quarter_date_fiscal_format PASSED
tests/test_mospi.py::test_parse_quarter_date_all_quarters PASSED
tests/test_mospi.py::test_parse_quarter_date_month_range_format PASSED
tests/test_mospi.py::test_parse_quarter_date_invalid_returns_none PASSED
tests/test_mospi.py::test_parse_quarter_date_empty_returns_none PASSED
tests/test_data_gov_in.py::test_parse_date_flexible_known_formats[...] PASSED (6)
tests/test_data_gov_in.py::test_parse_date_flexible_unknown_returns_none PASSED
tests/test_data_gov_in.py::test_parse_date_flexible_strips_whitespace PASSED
tests/test_data_gov_in.py::test_rbi_rates_parse_produces_pairs PASSED
tests/test_data_gov_in.py::test_rbi_rates_record_fields PASSED
tests/test_data_gov_in.py::test_rbi_rates_skips_invalid_date PASSED
tests/test_data_gov_in.py::test_rbi_rates_skips_non_numeric_value PASSED
tests/test_data_gov_in.py::test_rbi_rates_skips_missing_date PASSED
```

## Linting

```bash
ruff check .
mypy pipeline/
```
