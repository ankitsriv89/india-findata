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

from pydantic import BaseModel, field_validator, model_validator


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
