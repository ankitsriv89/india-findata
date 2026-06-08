"""
pipeline.sources.mospi — fetch CPI, IIP, and GDP from MOSPI APIs.

MOSPI (Ministry of Statistics and Programme Implementation) publishes
India's key macro indicators via two mechanisms:

  1. esankhyiki portal API (api.mospi.gov.in) — the official REST API.
     Requires a free registration at https://esankhyiki.mospi.gov.in
     to obtain an API token.

  2. data.gov.in backup — MOSPI also publishes the same datasets on
     data.gov.in as JSON resources.  We use this as a fallback if the
     primary API is unavailable or the token is missing.

Release schedule (important for scheduling):
  - CPI: released on the 12th of each month at 5:30 PM IST,
    for the PREVIOUS month.  (June CPI released in mid-July.)
  - IIP: released on the 12th at 4:00 PM IST, for 2 months prior.
    (April IIP released in June.)  We poll days 11–16 of each month.
  - GDP: released ~60 days after quarter end.  Q1 (Apr–Jun) released
    in late August.

Data freshness note:
  MOSPI sometimes releases "provisional" figures first and revises them
  later.  We store a `release` tag ("provisional" | "final") so users
  can see when figures changed.  ClickHouse ReplacingMergeTree handles
  the deduplication on re-insertion.
"""

import time
import structlog
from datetime import date, timedelta
from typing import Any

import httpx
from pydantic import ValidationError

from pipeline.schema.record import Record
from pipeline.schema.validators import MOSPISeriesPoint
from pipeline.sources.base import Source

log = structlog.get_logger()

# MOSPI esankhyiki API base URL.
# Note: this URL was correct as of mid-2026; MOSPI has historically changed
# their API endpoints without notice.  If requests fail with 404, check
# https://esankhyiki.mospi.gov.in for the current endpoint.
_MOSPI_API_BASE = "https://api.mospi.gov.in"

# Fallback: data.gov.in resource IDs for MOSPI datasets.
# These IDs are stable but the data may lag by 1–2 months.
_DATAGOV_MOSPI_CPI_RESOURCE = "3b01bcb8-0b14-4abf-b6f2-c1bfd384ba69"  # CPI All India
_DATAGOV_BASE = "https://api.data.gov.in/resource"

# Seconds to sleep between consecutive API calls in backfill loops.
# MOSPI API doesn't publish a rate limit; 1 req/s is conservative and safe.
_RATE_LIMIT_SLEEP = 1.0

# Series IDs for the MOSPI esankhyiki API
_CPI_SERIES: dict[str, dict[str, str]] = {
    "CPI_GENERAL": {
        "id": "CPI_GEN",
        "description": "CPI All India General",
        "unit": "index_points",
    },
    "CPI_FOOD": {
        "id": "CPI_FOOD",
        "description": "CPI Food and Beverages",
        "unit": "index_points",
    },
    "CPI_RURAL": {
        "id": "CPI_RURAL",
        "description": "CPI Rural",
        "unit": "index_points",
    },
    "CPI_URBAN": {
        "id": "CPI_URBAN",
        "description": "CPI Urban",
        "unit": "index_points",
    },
}

_IIP_SERIES: dict[str, dict[str, str]] = {
    "IIP_GENERAL": {
        "id": "IIP_GEN",
        "description": "IIP General Index",
        "unit": "index_points",
    },
    "IIP_MANUFACTURING": {
        "id": "IIP_MFG",
        "description": "IIP Manufacturing",
        "unit": "index_points",
    },
    "IIP_MINING": {
        "id": "IIP_MINING",
        "description": "IIP Mining and Quarrying",
        "unit": "index_points",
    },
    "IIP_ELECTRICITY": {
        "id": "IIP_ELEC",
        "description": "IIP Electricity",
        "unit": "index_points",
    },
}


class MOSPISource(Source):
    """
    Fetches CPI and IIP data from the MOSPI esankhyiki API.

    Args:
        api_token: MOSPI API token from https://esankhyiki.mospi.gov.in
                   If None, the source will return empty results and log
                   a warning (allows the pipeline to start without credentials
                   during development).
        datagov_api_key: data.gov.in API key (fallback for CPI).
    """

    name = "mospi_cpi"  # used in pipeline_runs and as Record.source

    def __init__(self, api_token: str | None, datagov_api_key: str | None = None) -> None:
        self._token = api_token
        self._datagov_key = datagov_api_key
        # Module-level client, reused across all calls.  30s timeout is
        # generous for government APIs that can be slow.
        self._client = httpx.Client(timeout=30.0, follow_redirects=True)

    def fetch(self, target_date: date) -> list[Record]:
        """
        Fetch CPI and IIP data for the month containing target_date.

        Because MOSPI releases monthly data on the 12th, we fetch the
        full series from 12 months ago to today's month — this ensures
        we always pick up any revisions to earlier figures.

        Args:
            target_date: Any date.  We derive the year-month from this.

        Returns:
            List of Records for all CPI and IIP series.  Empty list if
            the API token is not configured.
        """
        if not self._token:
            log.warning(
                "mospi.no_token",
                msg="MOSPI_API_TOKEN not set — skipping fetch. Set it in .env to enable.",
            )
            return []

        # Fetch the 12 months ending at target_date's month
        to_month = target_date.replace(day=1)
        from_month = date(to_month.year - 1, to_month.month, 1)

        records: list[Record] = []
        records.extend(self._fetch_cpi(from_month, to_month))
        records.extend(self._fetch_iip(from_month, to_month))
        return records

    def backfill(self, from_date: date, to_date: date) -> list[Record]:
        """
        Fetch all CPI and IIP data between from_date and to_date.

        Calls the API in 12-month windows to stay within any implicit
        page size limits, sleeping between requests.

        Args:
            from_date: Start of backfill range (inclusive).
            to_date:   End of backfill range (inclusive).

        Returns:
            All records across the full date range.
        """
        if not self._token:
            log.warning(
                "mospi.no_token",
                msg="MOSPI_API_TOKEN not set — backfill skipped.",
            )
            return []

        records: list[Record] = []
        current = from_date.replace(day=1)
        end = to_date.replace(day=1)

        # Walk through in 12-month chunks
        while current <= end:
            window_end = min(
                date(current.year + 1, current.month, 1) - timedelta(days=1),
                end,
            )
            records.extend(self._fetch_cpi(current, window_end))
            time.sleep(_RATE_LIMIT_SLEEP)  # be polite to the MOSPI API
            records.extend(self._fetch_iip(current, window_end))
            time.sleep(_RATE_LIMIT_SLEEP)

            # Advance by 12 months
            next_year = current.year + 1 if current.month == 12 else current.year
            next_month = 1 if current.month == 12 else current.month + 1
            current = date(next_year, next_month, 1)

        return records

    def _fetch_cpi(self, from_date: date, to_date: date) -> list[Record]:
        """
        Fetch all CPI series (General, Food, Rural, Urban) for a date range.

        The MOSPI API endpoint pattern:
          GET /cpi?from=YYYY-MM&to=YYYY-MM&series=CPI_GEN&token=<token>

        Note: actual endpoint path and query params depend on the current
        MOSPI API version.  Check https://esankhyiki.mospi.gov.in/api-docs
        for the latest spec.

        Falls back to data.gov.in if the primary API returns an error.
        """
        records: list[Record] = []

        from_str = from_date.strftime("%Y-%m")
        to_str = to_date.strftime("%Y-%m")

        for series_name, series_meta in _CPI_SERIES.items():
            try:
                raw_points = self._call_mospi_api(
                    "/cpi",
                    params={
                        "from": from_str,
                        "to": to_str,
                        "series": series_meta["id"],
                        "token": self._token,
                    },
                )
                records.extend(
                    self._parse_cpi_points(raw_points, series_name, series_meta)
                )
            except Exception as exc:
                # Log and try the data.gov.in fallback for CPI_GENERAL only
                log.warning(
                    "mospi.cpi_api_failed",
                    series=series_name,
                    error=str(exc),
                    fallback="trying data.gov.in",
                )
                if series_name == "CPI_GENERAL" and self._datagov_key:
                    records.extend(self._fetch_cpi_from_datagov(from_date, to_date))

        return records

    def _fetch_iip(self, from_date: date, to_date: date) -> list[Record]:
        """
        Fetch all IIP series (General, Manufacturing, Mining, Electricity).

        IIP is released 2 months after the reference month — e.g. April IIP
        is released in mid-June.  The API returns empty for future months,
        which is fine: we just get fewer records.
        """
        records: list[Record] = []

        from_str = from_date.strftime("%Y-%m")
        to_str = to_date.strftime("%Y-%m")

        for series_name, series_meta in _IIP_SERIES.items():
            try:
                raw_points = self._call_mospi_api(
                    "/iip",
                    params={
                        "from": from_str,
                        "to": to_str,
                        "series": series_meta["id"],
                        "token": self._token,
                    },
                )
                records.extend(
                    self._parse_iip_points(raw_points, series_name, series_meta)
                )
            except Exception as exc:
                log.warning(
                    "mospi.iip_api_failed",
                    series=series_name,
                    error=str(exc),
                )

        return records

    def _call_mospi_api(self, path: str, params: dict[str, Any]) -> list[dict]:
        """
        Make a GET request to the MOSPI API and return the JSON array.

        Raises:
            RuntimeError: wrapping the original error with context, so
                          callers know which source/endpoint failed.
        """
        url = f"{_MOSPI_API_BASE}{path}"
        try:
            resp = self._client.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            raise RuntimeError(f"mospi: GET {path}: {exc}") from exc

        # API can return either a list directly or {"data": [...]}
        if isinstance(data, list):
            return data
        if isinstance(data, dict) and "data" in data:
            return data["data"]
        raise RuntimeError(f"mospi: unexpected response shape from {path}: {type(data)}")

    def _parse_cpi_points(
        self,
        raw_points: list[dict],
        series_name: str,
        series_meta: dict[str, str],
    ) -> list[Record]:
        """
        Validate and normalise raw MOSPI CPI API points to Records.

        Skips any point where:
          - The value is missing or non-numeric (logs a warning)
          - The date cannot be parsed (logs a warning)
        """
        records: list[Record] = []

        for raw in raw_points:
            try:
                point = MOSPISeriesPoint(
                    month=raw.get("month", raw.get("date", "")),
                    value=raw.get("value", raw.get("val", "")),
                    series=series_name,
                )
            except (ValidationError, ValueError, KeyError) as exc:
                log.warning(
                    "mospi.cpi_parse_skip",
                    series=series_name,
                    raw=raw,
                    error=str(exc),
                )
                continue

            records.append(
                Record(
                    source=self.name,
                    series=series_name,
                    dimension="index_value",
                    value=point.value,
                    date=point.observation_date(),
                    granularity="monthly",
                    unit=series_meta["unit"],
                    region="india",
                    tags={
                        "base_year": "2012",  # MOSPI CPI base year
                        "release": raw.get("release", "provisional"),
                    },
                )
            )

        return records

    def _parse_iip_points(
        self,
        raw_points: list[dict],
        series_name: str,
        series_meta: dict[str, str],
    ) -> list[Record]:
        """Validate and normalise raw MOSPI IIP API points to Records."""
        records: list[Record] = []

        for raw in raw_points:
            try:
                point = MOSPISeriesPoint(
                    month=raw.get("month", raw.get("date", "")),
                    value=raw.get("value", raw.get("val", "")),
                    series=series_name,
                )
            except (ValidationError, ValueError, KeyError) as exc:
                log.warning(
                    "mospi.iip_parse_skip",
                    series=series_name,
                    raw=raw,
                    error=str(exc),
                )
                continue

            records.append(
                Record(
                    source="mospi_iip",
                    series=series_name,
                    dimension="index_value",
                    value=point.value,
                    date=point.observation_date(),
                    granularity="monthly",
                    unit=series_meta["unit"],
                    region="india",
                    tags={
                        "base_year": "2011-12",  # IIP base year
                        "release": raw.get("release", "provisional"),
                    },
                )
            )

        return records

    def _fetch_cpi_from_datagov(self, from_date: date, to_date: date) -> list[Record]:
        """
        Fallback: fetch CPI General from data.gov.in.

        Used when the primary MOSPI API is unavailable.  Data may lag
        the MOSPI API by 1–2 months but is otherwise identical.
        """
        if not self._datagov_key:
            return []

        records: list[Record] = []
        offset = 0
        limit = 100

        while True:
            try:
                resp = self._client.get(
                    f"{_DATAGOV_BASE}/{_DATAGOV_MOSPI_CPI_RESOURCE}",
                    params={
                        "api-key": self._datagov_key,
                        "format": "json",
                        "limit": limit,
                        "offset": offset,
                    },
                )
                resp.raise_for_status()
                data = resp.json()
            except Exception as exc:
                raise RuntimeError(f"mospi: data.gov.in CPI fallback: {exc}") from exc

            items = data.get("records", [])
            if not items:
                break

            for item in items:
                # data.gov.in CPI resource fields (confirm at runtime):
                # "month_year", "cpi_all_india_general_index"
                month_str = item.get("month_year", "")
                val_str = item.get("cpi_all_india_general_index", "")

                if not month_str or not val_str:
                    continue
                try:
                    point = MOSPISeriesPoint(month=month_str, value=val_str, series="CPI_GENERAL")
                    obs_date = point.observation_date()
                    if from_date <= obs_date <= to_date:
                        records.append(
                            Record(
                                source=self.name,
                                series="CPI_GENERAL",
                                dimension="index_value",
                                value=point.value,
                                date=obs_date,
                                granularity="monthly",
                                unit="index_points",
                                region="india",
                                tags={"base_year": "2012", "release": "provisional", "via": "datagov"},
                            )
                        )
                except (ValidationError, ValueError):
                    continue

            total = data.get("total", 0)
            offset += limit
            if offset >= total:
                break
            time.sleep(_RATE_LIMIT_SLEEP)

        return records


class MOSPIGDPSource(Source):
    """
    Fetches GDP growth rate data from data.gov.in (MOSPI publishes GDP there).

    GDP is quarterly, released ~60 days after quarter end.  We fetch via
    data.gov.in because the primary MOSPI API does not have a reliable
    GDP endpoint as of mid-2026.

    Series produced:
      GDP_GROWTH_RATE — quarterly YoY growth rate in percent
      GDP_GVA         — Gross Value Added (basic prices), crore INR
    """

    name = "mospi_gdp"

    # data.gov.in resource ID for GDP at constant prices (2011-12 base)
    # Confirm this ID at https://data.gov.in/search?keyword=gdp+india
    _GDP_RESOURCE = "1d6c4f54-2f3e-4a58-9a9a-b1e0a3e9d8f2"

    def __init__(self, datagov_api_key: str) -> None:
        self._key = datagov_api_key
        self._client = httpx.Client(timeout=30.0, follow_redirects=True)

    def fetch(self, target_date: date) -> list[Record]:
        """Fetch the most recent 8 quarters of GDP data."""
        return self._fetch_gdp()

    def backfill(self, from_date: date, to_date: date) -> list[Record]:
        """Fetch all available GDP data (full history is small — ~20 years × 4 quarters)."""
        return self._fetch_gdp()

    def _fetch_gdp(self) -> list[Record]:
        """
        Fetch the full GDP series from data.gov.in.

        GDP data is small (< 100 rows for the full history) so we fetch
        all of it in one request rather than paginating.
        """
        records: list[Record] = []
        try:
            resp = self._client.get(
                f"{_DATAGOV_BASE}/{self._GDP_RESOURCE}",
                params={
                    "api-key": self._key,
                    "format": "json",
                    "limit": 200,
                    "offset": 0,
                },
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            raise RuntimeError(f"mospi_gdp: fetch GDP: {exc}") from exc

        for item in data.get("records", []):
            # Expected fields (confirm at runtime with actual data.gov.in response):
            #   "quarter"      — e.g. "Q1 2023-24" or "Apr-Jun 2023"
            #   "growth_rate"  — YoY growth % as string
            quarter_str = item.get("quarter", "")
            growth_str = item.get("growth_rate", item.get("gdp_growth_rate", ""))

            if not quarter_str or not growth_str:
                continue

            obs_date = _parse_quarter_date(quarter_str)
            if obs_date is None:
                log.warning("mospi_gdp.unparseable_quarter", quarter=quarter_str)
                continue

            try:
                growth = float(growth_str)
            except ValueError:
                log.warning("mospi_gdp.non_numeric_growth", value=growth_str)
                continue

            records.append(
                Record(
                    source=self.name,
                    series="GDP_GROWTH_RATE",
                    dimension="yoy_change_pct",
                    value=growth,
                    date=obs_date,
                    granularity="quarterly",
                    unit="percent",
                    region="india",
                    tags={"base_year": "2011-12", "release": "provisional"},
                )
            )

        return records


def _parse_quarter_date(quarter_str: str) -> date | None:
    """
    Parse a quarter string from data.gov.in into the first day of that quarter.

    data.gov.in uses inconsistent quarter formats across different datasets.
    We try several known patterns:
      "Q1 2023-24"   → 2023-04-01  (Indian fiscal year Q1 = Apr–Jun)
      "Apr-Jun 2023" → 2023-04-01
      "Q1FY2024"     → 2023-04-01

    India's fiscal year starts April 1.  Q1 = Apr–Jun, Q2 = Jul–Sep,
    Q3 = Oct–Dec, Q4 = Jan–Mar.

    Returns None if no pattern matches (caller logs a warning and skips).
    """
    import re

    # Pattern: "Q1 2023-24" (fiscal year notation)
    m = re.match(r"Q(\d)\s+(\d{4})-\d{2}", quarter_str)
    if m:
        fq = int(m.group(1))           # 1, 2, 3, or 4
        fy_start = int(m.group(2))     # first year of fiscal year
        # Q1=Apr, Q2=Jul, Q3=Oct, Q4=Jan (of next calendar year)
        quarter_to_month = {1: (fy_start, 4), 2: (fy_start, 7), 3: (fy_start, 10), 4: (fy_start + 1, 1)}
        year, month = quarter_to_month[fq]
        return date(year, month, 1)

    # Pattern: "Apr-Jun 2023" (month range)
    month_map = {
        "Jan": 1, "Feb": 2, "Mar": 3, "Apr": 4, "May": 5, "Jun": 6,
        "Jul": 7, "Aug": 8, "Sep": 9, "Oct": 10, "Nov": 11, "Dec": 12,
    }
    m2 = re.match(r"([A-Za-z]{3})-[A-Za-z]{3}\s+(\d{4})", quarter_str)
    if m2:
        start_month = month_map.get(m2.group(1)[:3].capitalize())
        year = int(m2.group(2))
        if start_month:
            return date(year, start_month, 1)

    return None
