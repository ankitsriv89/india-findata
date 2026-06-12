"""
pipeline.schema.validators — pydantic v2 models for raw API responses.

Each source's raw JSON/CSV is parsed into one of these models *before* being
normalised into Record objects.  This gives us:

  1. Automatic type coercion (string "190.3" → float 190.3)
  2. Validation errors pinpoint the exact field that's wrong
  3. Documentation of what each source's API actually returns

Why validate twice (pydantic + the Record dataclass)?
  - The validators here catch problems in the raw source data.
  - The Record dataclass is the cleaned, normalised form we insert.
  Keeping them separate makes it easy to add a new source: write a
  validator for the raw response, then write the normalisation function.
"""

from datetime import date
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator


class MOSPISeriesPoint(BaseModel):
    """
    One data point from the MOSPI API.

    The MOSPI CPI/IIP/GDP API returns a list of these objects.
    Field names match what the API actually returns (snake_case after
    normalisation — the API uses camelCase which pydantic handles via alias).

    Example raw API response item:
        {"month": "2024-01", "value": "190.3", "series": "CPI_GENERAL"}
    """

    month: str          # "YYYY-MM" for CPI/IIP, "YYYY-QN" for GDP (e.g. "2024-Q1")
    value: float        # pydantic coerces string "190.3" → float
    series: str         # "CPI_GENERAL" | "CPI_FOOD" | "IIP_GENERAL" | "GDP_GROWTH_RATE"

    @field_validator("value", mode="before")
    @classmethod
    def coerce_value(cls, v: Any) -> float:
        """
        MOSPI sometimes returns values as strings or uses "-" for missing data.
        We reject missing/null values here — callers skip records where this
        raises a ValueError rather than inserting NaN.
        """
        if v is None or v == "" or v == "-" or v == "NA":
            raise ValueError(f"Missing value from MOSPI API: {v!r}")
        return float(v)

    def observation_date(self) -> date:
        """
        Convert the MOSPI month/quarter string to a Python date.

        Monthly data ("2024-01") → first day of that month: 2024-01-01
        Quarterly data ("2024-Q1") → first day of that quarter: 2024-01-01

        Using the first day of the period is the convention throughout this
        pipeline — it makes date arithmetic and ClickHouse partitioning simple.
        """
        if "-Q" in self.month:
            # Quarterly: "2024-Q1" → 2024-01-01, "2024-Q2" → 2024-04-01, etc.
            year_str, q_str = self.month.split("-Q")
            quarter_start_month = (int(q_str) - 1) * 3 + 1
            return date(int(year_str), quarter_start_month, 1)
        else:
            # Monthly: "2024-01" → 2024-01-01
            year_str, month_str = self.month.split("-")
            return date(int(year_str), int(month_str), 1)


class DataGovInRecord(BaseModel):
    """
    One record from the data.gov.in REST API.

    The data.gov.in API returns paginated JSON. Each item in the `records`
    array is a flat dict with string values.  Field names vary by dataset
    (each resource has its own schema), so this model is intentionally loose —
    it captures the raw fields dict and lets the source module extract what
    it needs.

    Example raw API response item for RBI repo rate:
        {
          "date": "2024-02-08",
          "repo_rate": "6.50",
          "reverse_repo_rate": "3.35",
          "_id": 42
        }
    """

    fields: dict[str, str]  # all raw string fields from the API record

    @model_validator(mode="before")
    @classmethod
    def capture_all_fields(cls, data: Any) -> Any:
        """
        data.gov.in records are flat dicts.  Wrap them in our `fields` key so
        the rest of the model works uniformly.
        """
        if isinstance(data, dict) and "fields" not in data:
            return {"fields": data}
        return data

    def get(self, key: str, default: str = "") -> str:
        """Convenience accessor that normalises key lookup to lowercase."""
        # API field names are inconsistent across datasets — try both cases
        return self.fields.get(key) or self.fields.get(key.lower()) or default


class BhavcopyRow(BaseModel):
    """
    One validated equity row from an NSE or BSE daily bhavcopy CSV.

    Shared by both exchange sources (they map their differently-named columns
    onto these canonical fields before constructing the model).  The validators
    enforce the pipeline's "skip-bad-rows, never insert NaN" rule:

      - Prices and volume must be present and numeric; blank/"-"/non-numeric
        raises ValueError so the source skips the row with a warning.
      - Negative prices are rejected (a price can't be negative); a price of
        exactly 0 is allowed (some illiquid scrips legitimately print 0 for a
        day with no trades, which the volume==0 case captures).

    Example (NSE columns mapped):
        BhavcopyRow(symbol="TCS", series="EQ", open="3850.0", high="3899.9",
                    low="3840.1", close="3888.5", volume="1234567",
                    isin="INE467B01029")
    """

    symbol: str
    series: str
    open: float
    high: float
    low: float
    close: float
    volume: float
    isin: str = ""

    @field_validator("open", "high", "low", "close", mode="before")
    @classmethod
    def coerce_price(cls, v: Any) -> float:
        """Reject missing/non-numeric prices and negatives (skip-not-crash)."""
        if v is None or v == "" or v == "-" or v == "NA":
            raise ValueError(f"missing price: {v!r}")
        price = float(v)
        if price < 0:
            raise ValueError(f"negative price: {price}")
        return price

    @field_validator("volume", mode="before")
    @classmethod
    def coerce_volume(cls, v: Any) -> float:
        """Volume must be a non-negative number; blank/non-numeric is skipped."""
        if v is None or v == "" or v == "-" or v == "NA":
            raise ValueError(f"missing volume: {v!r}")
        vol = float(v)
        if vol < 0:
            raise ValueError(f"negative volume: {vol}")
        return vol

    @field_validator("symbol", mode="before")
    @classmethod
    def require_symbol(cls, v: Any) -> str:
        """A row with no symbol is unusable — reject it."""
        s = str(v).strip()
        if not s:
            raise ValueError("empty symbol")
        return s


class FIIDIIRow(BaseModel):
    """
    One validated FII/DII net-flow row from the NSE daily report.

    Unlike prices, the NET value may legitimately be NEGATIVE (net selling),
    so the validator only rejects missing/non-numeric values — never the sign.

    Example:
        FIIDIIRow(date="02-Jun-2026", net_value="-1234.56")
    """

    date_str: str = Field(alias="date")
    net_value: float

    model_config = {"populate_by_name": True}

    @field_validator("net_value", mode="before")
    @classmethod
    def coerce_net(cls, v: Any) -> float:
        """Net flow: reject only missing/non-numeric (negatives are valid)."""
        if v is None or v == "" or v == "-" or v == "NA":
            raise ValueError(f"missing net value: {v!r}")
        # NSE writes large numbers with thousands commas, e.g. "12,345.67".
        if isinstance(v, str):
            v = v.replace(",", "")
        return float(v)

    def observation_date(self) -> date:
        """Parse the report's date string into a Python date."""
        # Import here to avoid a circular import (sebi imports this module).
        from pipeline.sources.sebi import _parse_flow_date

        return _parse_flow_date(self.date_str)


class RBIDataPoint(BaseModel):
    """
    One validated observation from an RBI DBIE publication (Excel or PDF).

    DBIE publications have no stable schema — column names and layout drift
    between releases — so the source modules do the messy extraction and hand
    this model a clean (date, value) pair plus the already-resolved series.
    This model's only job is the universal numeric guard: reject missing /
    non-numeric values so we never insert NaN, while ALLOWING values that some
    series can legitimately have at zero or (for growth/NPA deltas) negative.

    Example:
        RBIDataPoint(observation=date(2026, 5, 30), value="652.34",
                     series="FOREX_RESERVES")
    """

    observation: date
    value: float
    series: str

    @field_validator("value", mode="before")
    @classmethod
    def coerce_value(cls, v: Any) -> float:
        """Reject missing/non-numeric; strip thousands commas; keep the sign."""
        if v is None or v == "" or v == "-" or v == "NA":
            raise ValueError(f"missing RBI value: {v!r}")
        if isinstance(v, str):
            v = v.replace(",", "").strip()
        return float(v)


class MCPDataPoint(BaseModel):
    """
    One numeric value from a MOSPI MCP data row.

    The MCP `get_data` rows are clean dicts, but values arrive as strings
    ("204.7", "8.65") and some cells are null/blank.  This model is the single
    numeric guard the mospi_mcp source uses for every value it extracts: it
    rejects missing/non-numeric (so we skip the row, never insert NaN) and keeps
    the sign (inflation/growth can be negative).

    Example:
        MCPDataPoint(value="204.7")  → value == 204.7
    """

    value: float

    @field_validator("value", mode="before")
    @classmethod
    def coerce_value(cls, v: Any) -> float:
        """Reject None/blank/'NA'; strip commas; allow negatives."""
        if v is None or v == "" or v == "-" or str(v).strip().upper() == "NA":
            raise ValueError(f"missing MCP value: {v!r}")
        if isinstance(v, str):
            v = v.replace(",", "").strip()
        return float(v)
