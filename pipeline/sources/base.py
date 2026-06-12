"""
pipeline.sources.base — abstract base class for all data sources.

Every source inherits from Source and must implement two methods:

  fetch(target_date)         — fetch data for a single date (used by scheduler)
  backfill(from_date, to_date) — fetch all data in a date range (used by backfill script)

Design principles:
  - fetch() is IDEMPOTENT: calling it twice for the same date must produce
    the same records.  The store layer uses ClickHouse ReplacingMergeTree
    so duplicate inserts are safe, but idempotency keeps the logic simple.
  - A source must NEVER crash the scheduler.  Errors are caught at the
    job level in scheduler.py and logged to pipeline_runs.
  - Sources use a module-level httpx.Client (created once, reused across
    calls) — never create a new client per request.
"""

from abc import ABC, abstractmethod
from datetime import date

import structlog

from pipeline.schema.record import Record

log = structlog.get_logger()


class Source(ABC):
    """
    Abstract base for all data sources.

    Subclasses must set the `name` class attribute — it becomes the `source`
    field on every Record and the key in pipeline_runs.
    """

    name: str  # e.g. "mospi_cpi", "rbi_rates", "nse_bhavcopy"

    @abstractmethod
    def fetch(self, target_date: date) -> list[Record]:
        """
        Fetch data for a single target_date.

        For monthly sources (CPI, IIP) this fetches the month containing
        target_date.  For daily sources (bhavcopy) it fetches exactly
        target_date.

        Returns an empty list if no data is available yet (e.g. calling
        fetch() on a date before the source has published).

        Never raises — callers catch exceptions and log to pipeline_runs.
        """
        ...

    @abstractmethod
    def backfill(self, from_date: date, to_date: date) -> list[Record]:
        """
        Fetch all available data between from_date and to_date inclusive.

        Used by the backfill CLI script to load historical data on first
        setup.  Implementations should:
          1. Respect source rate limits (add time.sleep between requests)
          2. Return all records in a single list (caller batches inserts)
          3. Skip dates where the source has no data (don't raise)
        """
        ...

    def __repr__(self) -> str:
        return f"<Source name={self.name!r}>"
