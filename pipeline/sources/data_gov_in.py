"""
pipeline.sources.data_gov_in — fetch RBI policy rates and banking data
from the data.gov.in REST API.

data.gov.in is the Indian government's open data portal.  It hosts many
RBI datasets that would otherwise require scraping the RBI website.

API overview:
  Base URL: https://api.data.gov.in/resource/<resource_id>
  Auth:     ?api-key=<key>  (free key from https://data.gov.in/user/register)
  Format:   ?format=json
  Pagination: ?limit=100&offset=0
              Response includes "total" for computing total pages.

Rate limit: 1,000 requests per hour.
  At 1 req / 3.6 seconds = 1000 req/hr.  We use _RATE_LIMIT_SLEEP=3.6s
  between paginated requests within a single backfill call.
  For scheduled daily/weekly jobs the rate limit is irrelevant (< 5 requests).

Resource IDs used (verify these at https://data.gov.in — they are stable
but occasionally updated when MOSPI/RBI refreshes the dataset):

  RBI_REPO_RATE_RESOURCE   — RBI repo rate and reverse repo rate history
  RBI_FOREX_RESOURCE       — Foreign exchange reserves (weekly, USD billion)
  RBI_CRR_SLR_RESOURCE     — CRR and SLR history

These resource IDs should be treated as starting points — validate them
by querying the API and checking the field names before building on them.
"""

import time
from datetime import date, datetime
from typing import Any

import httpx
import structlog
from pydantic import ValidationError

from pipeline.schema.record import Record
from pipeline.schema.validators import DataGovInRecord
from pipeline.sources.base import Source

log = structlog.get_logger()

_DATAGOV_BASE = "https://api.data.gov.in/resource"

# 1 req / 3.6 seconds = ~1000 req/hr, safely within the rate limit.
# The comment is here because a bare magic number would be confusing.
_RATE_LIMIT_SLEEP = 3.6

# Resource IDs for RBI datasets on data.gov.in.
# Check https://data.gov.in/search?keyword=rbi+repo+rate for current IDs.
_RBI_REPO_RATE_RESOURCE = "2e182baf-42e0-4050-9c07-a38eba7af44e"
_RBI_FOREX_RESOURCE = "7c2f254a-5f7c-4a61-9e7a-7d3f1c8a0e2b"
_RBI_BANKING_CREDIT_RESOURCE = "a3d8f2c1-9b4e-4f7d-8e5c-2a6b0f1e3d4c"


class RBIRatesSource(Source):
    """
    Fetches RBI policy rate history from data.gov.in.

    Produces Records for:
      REPO_RATE         — RBI repo rate (percent)
      REVERSE_REPO_RATE — RBI reverse repo / SDF rate (percent)

    These rates change only on RBI Monetary Policy Committee (MPC) meeting
    dates (~6 times per year).  The dataset contains one row per rate change.
    We store the effective date of each change, not daily rows.

    Args:
        api_key: data.gov.in API key.
    """

    name = "rbi_rates"

    def __init__(self, api_key: str) -> None:
        self._key = api_key
        self._client = httpx.Client(timeout=30.0, follow_redirects=True)

    def fetch(self, target_date: date) -> list[Record]:
        """
        Fetch all RBI rate change records (full history, small dataset).

        The rate history is small (~50 rows since 2000) so we always
        fetch the complete dataset rather than filtering by date on the
        API side.

        Args:
            target_date: Unused (rate dataset is not date-paginated).
        """
        return self._fetch_rates()

    def backfill(self, from_date: date, to_date: date) -> list[Record]:
        """Fetch all rate records; filter client-side to from_date..to_date."""
        all_records = self._fetch_rates()
        return [r for r in all_records if from_date <= r.date <= to_date]

    def _fetch_rates(self) -> list[Record]:
        """
        Fetch the complete RBI rates dataset from data.gov.in.

        Handles pagination automatically.  The full dataset is small
        (~50 rows) so pagination rarely triggers but is implemented for
        correctness.
        """
        records: list[Record] = []
        offset = 0
        limit = 100

        while True:
            raw_items = self._call_api(_RBI_REPO_RATE_RESOURCE, limit=limit, offset=offset)

            if not raw_items:
                break

            for raw in raw_items:
                parsed = self._parse_rate_record(raw)
                if parsed:
                    records.extend(parsed)

            # If we got fewer rows than the page size, we're on the last page
            if len(raw_items) < limit:
                break

            offset += limit
            time.sleep(_RATE_LIMIT_SLEEP)  # respect 1000 req/hr limit

        return records

    def _parse_rate_record(self, raw: dict[str, Any]) -> list[Record]:
        """
        Parse one raw data.gov.in row into Records.

        Returns a list because one rate-change event produces multiple
        Records (repo rate + reverse repo rate as separate Records).

        The field names in this raw dict depend on what the API actually
        returns — these names are typical for the RBI rates dataset but
        MUST be verified against a live API response.  The comments below
        note which alternatives to try if the primary name fails.
        """
        try:
            # pydantic v2: validate a raw dict via model_validate() — calling
            # DataGovInRecord(raw) positionally raises TypeError under pydantic
            # 2.x (BaseModel.__init__ only accepts keyword args).
            rec = DataGovInRecord.model_validate(raw)
        except ValidationError as exc:
            log.warning("rbi_rates.parse_skip", raw=raw, error=str(exc))
            return []

        # Field name alternatives — data.gov.in is inconsistent across datasets
        date_str = (
            rec.get("effective_date")
            or rec.get("date")
            or rec.get("w.e.f")
            or rec.get("wef")
        )
        repo_str = (
            rec.get("repo_rate")
            or rec.get("repo rate")
            or rec.get("reporate")
        )
        reverse_repo_str = (
            rec.get("reverse_repo_rate")
            or rec.get("reverse repo rate")
            or rec.get("sdf_rate")   # RBI replaced reverse repo with SDF in 2022
        )

        if not date_str:
            log.warning("rbi_rates.no_date", raw=raw)
            return []

        obs_date = _parse_date_flexible(date_str)
        if obs_date is None:
            log.warning("rbi_rates.unparseable_date", date_str=date_str)
            return []

        results: list[Record] = []

        if repo_str:
            try:
                results.append(
                    Record(
                        source=self.name,
                        series="REPO_RATE",
                        dimension="rate_pct",
                        value=float(repo_str),
                        date=obs_date,
                        granularity="daily",  # one row per policy decision, not calendar-daily
                        unit="percent",
                        region="india",
                        tags={"type": "policy_rate"},
                    )
                )
            except ValueError:
                log.warning("rbi_rates.non_numeric_repo", value=repo_str)

        if reverse_repo_str:
            try:
                results.append(
                    Record(
                        source=self.name,
                        series="REVERSE_REPO_RATE",
                        dimension="rate_pct",
                        value=float(reverse_repo_str),
                        date=obs_date,
                        granularity="daily",
                        unit="percent",
                        region="india",
                        tags={"type": "policy_rate"},
                    )
                )
            except ValueError:
                log.warning("rbi_rates.non_numeric_reverse_repo", value=reverse_repo_str)

        return results

    def _call_api(
        self, resource_id: str, limit: int = 100, offset: int = 0
    ) -> list[dict]:
        """
        Call data.gov.in API and return the records array.

        Raises:
            RuntimeError: on HTTP error or unexpected response shape.
        """
        url = f"{_DATAGOV_BASE}/{resource_id}"
        try:
            resp = self._client.get(
                url,
                params={
                    "api-key": self._key,
                    "format": "json",
                    "limit": limit,
                    "offset": offset,
                },
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            raise RuntimeError(f"rbi_rates: GET {url}: {exc}") from exc

        records = data.get("records", data.get("data", []))
        if not isinstance(records, list):
            raise RuntimeError(f"rbi_rates: unexpected response shape: {type(records)}")

        return records


class RBIForexSource(Source):
    """
    Fetches RBI foreign exchange reserves from data.gov.in.

    Forex reserves are published weekly (every Friday) as USD billion.
    India's forex reserves are a key macro indicator — high reserves signal
    RBI's capacity to defend the INR against external shocks.

    Produces Records for:
      FOREX_RESERVES — Total forex reserves (USD billion, weekly)
    """

    name = "rbi_forex"

    def __init__(self, api_key: str) -> None:
        self._key = api_key
        self._client = httpx.Client(timeout=30.0, follow_redirects=True)

    def fetch(self, target_date: date) -> list[Record]:
        """Fetch the most recent ~52 weeks of forex reserve data."""
        all_records = self._fetch_forex()
        # Keep only the last 52 weeks from target_date
        cutoff = date(target_date.year - 1, target_date.month, target_date.day)
        return [r for r in all_records if r.date >= cutoff]

    def backfill(self, from_date: date, to_date: date) -> list[Record]:
        """Fetch full forex history and filter to the requested range."""
        all_records = self._fetch_forex()
        return [r for r in all_records if from_date <= r.date <= to_date]

    def _fetch_forex(self) -> list[Record]:
        """Fetch all forex reserve records with pagination."""
        records: list[Record] = []
        offset = 0
        limit = 100

        while True:
            url = f"{_DATAGOV_BASE}/{_RBI_FOREX_RESOURCE}"
            try:
                resp = self._client.get(
                    url,
                    params={
                        "api-key": self._key,
                        "format": "json",
                        "limit": limit,
                        "offset": offset,
                    },
                )
                resp.raise_for_status()
                data = resp.json()
            except Exception as exc:
                raise RuntimeError(f"rbi_forex: fetch: {exc}") from exc

            raw_items = data.get("records", [])
            if not raw_items:
                break

            for raw in raw_items:
                record = self._parse_forex_record(raw)
                if record:
                    records.append(record)

            total = int(data.get("total", 0))
            offset += limit
            if offset >= total:
                break
            time.sleep(_RATE_LIMIT_SLEEP)

        return records

    def _parse_forex_record(self, raw: dict[str, Any]) -> Record | None:
        """
        Parse one raw forex row into a Record.

        Expected fields (verify against live data.gov.in response):
          "date"           — observation date
          "forex_reserves" — total reserves in USD billion
        """
        try:
            rec = DataGovInRecord.model_validate(raw)  # see _parse_rate_record
        except ValidationError:
            return None

        date_str = rec.get("date") or rec.get("week_ending") or rec.get("as_on_date")
        value_str = (
            rec.get("forex_reserves")
            or rec.get("total_forex_reserves")
            or rec.get("foreign_currency_assets")
        )

        if not date_str or not value_str:
            return None

        obs_date = _parse_date_flexible(date_str)
        if obs_date is None:
            return None

        try:
            value = float(value_str)
        except ValueError:
            return None

        return Record(
            source=self.name,
            series="FOREX_RESERVES",
            dimension="total_usd_bn",
            value=value,
            date=obs_date,
            granularity="weekly",
            unit="USD_billion",
            region="india",
            tags={"published_by": "rbi"},
        )


def _parse_date_flexible(date_str: str) -> date | None:
    """
    Parse a date string from data.gov.in into a Python date.

    data.gov.in datasets use wildly inconsistent date formats.  We try
    the most common ones in order:

      "2024-02-08"   — ISO 8601 (most APIs)
      "08/02/2024"   — DD/MM/YYYY (many Indian govt datasets)
      "08-02-2024"   — DD-MM-YYYY
      "Feb 08, 2024" — English month name
      "08-Feb-2024"  — DD-Mon-YYYY (RBI publications)

    Returns None if none of the patterns match (caller logs and skips).
    """
    formats = [
        "%Y-%m-%d",     # ISO 8601
        "%d/%m/%Y",     # DD/MM/YYYY
        "%d-%m-%Y",     # DD-MM-YYYY
        "%b %d, %Y",    # Feb 08, 2024
        "%d-%b-%Y",     # 08-Feb-2024
        "%d %b %Y",     # 08 Feb 2024
        "%Y/%m/%d",     # YYYY/MM/DD (rare)
    ]
    for fmt in formats:
        try:
            return datetime.strptime(date_str.strip(), fmt).date()
        except ValueError:
            continue
    return None
