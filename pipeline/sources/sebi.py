"""
pipeline.sources.sebi — daily FII/DII net equity flows.

FII (Foreign Institutional Investor) and DII (Domestic Institutional Investor)
net buy/sell figures are published daily by NSE on behalf of SEBI.  They are a
key market-sentiment indicator: heavy FII selling often precedes index dips.

Source format:
    NSE publishes a small daily CSV of provisional institutional flows.  Each
    row is one category (FII or DII) with gross buy, gross sell, and net values
    in crore INR.  We emit the NET equity figure per category:
        FII_NET_EQUITY — FII net equity purchase (crore INR, can be negative)
        DII_NET_EQUITY — DII net equity purchase (crore INR, can be negative)

CSV columns (NSE FII/DII report):
    DATE, CATEGORY, BUY_VALUE, SELL_VALUE, NET_VALUE
    (CATEGORY ∈ {"FII/FPI", "DII"})

Live-URL fragility (roadmap risk):
    The exact NSE/SEBI endpoint changes and may require browser session
    cookies.  Per the approved plan this is fixture-tested now and the live
    fetch URL is wired but treated as best-effort — a fetch failure logs and
    returns [] rather than crashing the scheduler.
"""

import csv
import io
from datetime import date, datetime

import httpx
import structlog
from pydantic import ValidationError

from pipeline.schema.record import Record
from pipeline.schema.validators import FIIDIIRow
from pipeline.sources.base import Source

log = structlog.get_logger()

# Best-effort NSE FII/DII report endpoint.  Kept configurable in one place so
# updating it when NSE moves the report is a one-line change.
_FII_DII_URL = "https://archives.nseindia.com/content/fo/fii_dii.csv"

_BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept": "*/*",
}

# Map the report's CATEGORY label → our canonical series name.
_CATEGORY_TO_SERIES = {
    "FII/FPI": "FII_NET_EQUITY",
    "FII": "FII_NET_EQUITY",
    "DII": "DII_NET_EQUITY",
}


class FIIDIISource(Source):
    """
    Fetches daily FII/DII net equity flows from the NSE report.

    Emits one Record per category per day with dimension="net_flow" and
    unit="crore_INR".  Net flow can be negative (net selling) — that is valid
    data, not an error, so the value validator does NOT reject negatives.

    Args:
        None — the report is public.
    """

    name = "fii_dii"

    def __init__(self) -> None:
        self._client = httpx.Client(
            timeout=30.0, follow_redirects=True, headers=_BROWSER_HEADERS
        )

    def fetch(self, target_date: date) -> list[Record]:
        """
        Fetch the latest FII/DII report and parse it.

        The NSE report is a single small CSV covering the most recent trading
        day (and sometimes a short trailing history).  We parse whatever dates
        the file contains; target_date is used only for logging context.

        Returns [] on any download failure (live-URL fragility, see module doc).
        """
        try:
            resp = self._client.get(_FII_DII_URL)
            resp.raise_for_status()
        except Exception as exc:
            # Best-effort source: log and skip rather than crash the scheduler.
            log.warning(
                "fii_dii.fetch_failed",
                source=self.name,
                target_date=str(target_date),
                error=str(exc),
            )
            return []
        return self.parse(resp.content)

    def backfill(self, from_date: date, to_date: date) -> list[Record]:
        """
        Backfill FII/DII flows.

        NSE does not expose a clean per-date archive for this report, so the
        backfill simply fetches the current report and keeps rows that fall in
        the requested range.  Historical depth therefore depends on what the
        live report carries (typically recent days only).
        """
        records = self.fetch(to_date)
        return [r for r in records if from_date <= r.date <= to_date]

    def parse(self, csv_bytes: bytes) -> list[Record]:
        """
        Parse FII/DII CSV bytes into net-flow Records.

        Pure function (unit-tested with a fixture).  Skips rows whose category
        is unrecognised or whose net value is non-numeric, logging a warning.
        """
        records: list[Record] = []
        text = csv_bytes.decode("latin-1")
        reader = csv.DictReader(io.StringIO(text))

        for raw in reader:
            row = {(k or "").strip(): (v or "").strip() for k, v in raw.items()}

            category = row.get("CATEGORY", "")
            series = _CATEGORY_TO_SERIES.get(category)
            if series is None:
                log.warning("fii_dii.unknown_category", category=category)
                continue

            try:
                # model_validate() lets pydantic coerce the raw strings and
                # accept the "date" alias without mypy flagging types.
                parsed = FIIDIIRow.model_validate(
                    {
                        "date": row.get("DATE", ""),
                        "net_value": row.get("NET_VALUE", ""),
                    }
                )
            except (ValidationError, ValueError) as exc:
                log.warning(
                    "fii_dii.row_skip",
                    source=self.name,
                    category=category,
                    error=str(exc),
                )
                continue

            records.append(
                Record(
                    source=self.name,
                    series=series,
                    dimension="net_flow",
                    value=parsed.net_value,
                    date=parsed.observation_date(),
                    granularity="daily",
                    unit="crore_INR",
                    region="india",
                    tags={"category": category},
                )
            )

        log.info("fii_dii.parsed", source=self.name, records=len(records))
        return records


def _parse_flow_date(raw: str) -> date:
    """
    Parse an NSE FII/DII date string into a date.

    NSE uses "DD-Mon-YYYY" (e.g. "02-Jun-2026") in this report.  Kept as a
    module function so the validator can reuse it and tests can target it.

    Raises:
        ValueError: if the string matches no known format (caller skips).
    """
    raw = raw.strip()
    for fmt in ("%d-%b-%Y", "%d-%m-%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"unparseable FII/DII date: {raw!r}")
