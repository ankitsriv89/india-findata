"""
pipeline.schema.record — the universal time-series record.

Every data source (MOSPI, NSE, RBI, data.gov.in) normalises its raw API
response into a list[Record] before inserting into ClickHouse.  Using a
single shared schema means:

  - The ClickHouse `records` table never needs source-specific columns.
  - The FastAPI query layer works the same way for every source.
  - The dashboard doesn't need to know which source produced a row.

Fields are a superset of what any one source needs — sources leave
optional fields at their defaults and fill the ones that make sense for
their data.
"""

from dataclasses import dataclass, field
from datetime import UTC, date, datetime


@dataclass
class Record:
    """
    One time-series observation from any data source.

    Args:
        source:      Unique identifier for the data source, e.g. "mospi_cpi",
                     "nse_bhavcopy", "rbi_rates".  Used as the primary filter
                     in ClickHouse queries.
        series:      The named series within the source, e.g. "CPI_GENERAL",
                     "NIFTY50", "REPO_RATE".  Think of it as the metric name.
        dimension:   What the value measures within the series: "index_value",
                     "close_price", "rate_pct", "yoy_change_pct".  One series
                     can have multiple dimensions (e.g. OHLC for equity data).
        value:       The numeric measurement.  Never NaN — records with null
                     values are skipped before reaching this point.
        date:        Observation date.  For monthly data this is always the
                     first of the month.  For quarterly data it's the first
                     day of the quarter.
        granularity: Sampling frequency: "daily" | "monthly" | "quarterly".
        unit:        Human-readable unit string: "index_points", "INR",
                     "percent", "USD", "crore_INR".
        region:      Geographic scope: "india", "sector:IT", "mumbai".
                     Sector tags start with "sector:".
        tags:        Arbitrary key/value metadata for the source to attach.
                     Examples: {"base_year": "2012", "release": "provisional"}
                     {"exchange": "NSE", "isin": "INE009A01021"}
        fetched_at:  When this record was fetched.  Used by ClickHouse's
                     ReplacingMergeTree to pick the latest revision of a row.
                     Defaults to utcnow() at construction time.
    """

    source: str
    series: str
    dimension: str
    value: float
    date: date
    granularity: str
    unit: str
    region: str
    tags: dict[str, str]
    fetched_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def as_dict(self) -> dict:
        """
        Return a dict suitable for ClickHouse JSONEachRow insertion.

        ClickHouse expects dates as "YYYY-MM-DD" strings and datetimes as
        "YYYY-MM-DD HH:MM:SS" strings when using the JSON format.
        """
        return {
            "source": self.source,
            "series": self.series,
            "dimension": self.dimension,
            "value": self.value,
            "date": self.date.isoformat(),
            "granularity": self.granularity,
            "unit": self.unit,
            "region": self.region,
            "tags": self.tags,
            "fetched_at": self.fetched_at.strftime("%Y-%m-%d %H:%M:%S"),
        }
