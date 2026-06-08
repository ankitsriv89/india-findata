"""
pipeline — batch data pipeline for Indian financial and economic data.

Package layout:
  pipeline/schema/    — Record dataclass and pydantic validators
  pipeline/sources/   — one module per data source (mospi, data_gov_in, nse, ...)
  pipeline/store/     — ClickHouse insert + Postgres run-logging
  pipeline/scheduler.py — APScheduler job registration
  pipeline/main.py    — FastAPI app + scheduler startup
"""
