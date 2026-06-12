"""
pipeline.sources.bse — BSE (Bombay Stock Exchange) daily equity bhavcopy.

BSE's equity bhavcopy mirrors NSE's: an EOD ZIP-compressed CSV with one row
per security, published after market close.  Same normalisation strategy as
`pipeline.sources.nse` — OHLC + volume Records per symbol, exchange tag flips
to "BSE".  See that module's docstring for the design rationale; this one only
documents the BSE-specific URL and column differences.

URL pattern (official BSE bulk download):
    https://www.bseindia.com/download/BhavCopy/Equity/EQ_ISINCODE_<DDMMYY>.ZIP
    e.g. EQ_ISINCODE_020626.ZIP   (for 2 June 2026)

CSV columns (BSE EQ_ISINCODE format):
    SC_CODE, SC_NAME, SC_GROUP, SC_TYPE, OPEN, HIGH, LOW, CLOSE, LAST,
    PREVCLOSE, NO_TRADES, NO_OF_SHRS, NET_TURNOV, TDCLOINDI, ISIN_CODE

Key column differences vs NSE:
    - Symbol is SC_CODE (numeric scrip code); the human name is SC_NAME.
      We use SC_NAME as the `series` so the dashboard shows readable tickers,
      and keep SC_CODE in tags.
    - Volume is NO_OF_SHRS (NSE uses TOTTRDQTY).
    - "Equity" filter is SC_GROUP membership rather than a SERIES=="EQ" flag;
      BSE groups A/B/T/etc. are all equity, so we keep rows whose SC_GROUP is
      non-empty and not a debt/derivative group.  We keep it simple: accept
      groups in _EQUITY_GROUPS.
"""

import csv
import io
import time
import zipfile
from datetime import date, timedelta

import httpx
import structlog
from pydantic import ValidationError

from pipeline.schema.record import Record
from pipeline.schema.validators import BhavcopyRow
from pipeline.sources.base import Source

log = structlog.get_logger()

_BSE_BASE = "https://www.bseindia.com/download/BhavCopy/Equity"

_BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept": "*/*",
}

_RATE_LIMIT_SLEEP = 0.5

# BSE equity groups we treat as ordinary equity.  A/B are the main boards;
# T/Z are trade-to-trade/surveillance but still equity.  Debt and derivative
# segments use other letters and are filtered out by absence from this set.
_EQUITY_GROUPS = {"A", "B", "T", "Z", "M", "MT", "X", "XT"}


class BSEBhavcopySource(Source):
    """
    Fetches the daily BSE equity bhavcopy and normalises it to Records.

    Identical Record shape to NSEBhavcopySource (5 dimensions/symbol) so the
    /markets API can query either exchange uniformly via the `exchange` tag.

    Args:
        None — BSE bhavcopy needs no credentials.
    """

    name = "bse_bhavcopy"

    def __init__(self) -> None:
        self._client = httpx.Client(
            timeout=30.0, follow_redirects=True, headers=_BROWSER_HEADERS
        )

    def fetch(self, target_date: date) -> list[Record]:
        """Fetch and parse one trading day's BSE bhavcopy (see NSE.fetch)."""
        raw = self._download(target_date)
        if raw is None:
            return []
        return self.parse(raw, target_date)

    def backfill(self, from_date: date, to_date: date) -> list[Record]:
        """Fetch every trading-day BSE bhavcopy in the range (see NSE.backfill)."""
        records: list[Record] = []
        current = from_date
        while current <= to_date:
            records.extend(self.fetch(current))
            time.sleep(_RATE_LIMIT_SLEEP)
            current += timedelta(days=1)
        return records

    def _build_url(self, target_date: date) -> str:
        """
        Construct the BSE bhavcopy ZIP URL.

        Filename example for 2 June 2026: EQ_ISINCODE_020626.ZIP
        Date is DDMMYY, all zero-padded, two-digit year.
        """
        ddmmyy = target_date.strftime("%d%m%y")
        return f"{_BSE_BASE}/EQ_ISINCODE_{ddmmyy}.ZIP"

    def _download(self, target_date: date) -> bytes | None:
        """Download + unzip; return CSV bytes, or None for non-trading days."""
        url = self._build_url(target_date)
        try:
            resp = self._client.get(url)
        except Exception as exc:
            raise RuntimeError(f"bse_bhavcopy: download {url}: {exc}") from exc

        if resp.status_code == 404:
            log.debug("bse.no_file", date=str(target_date), url=url)
            return None
        try:
            resp.raise_for_status()
        except Exception as exc:
            raise RuntimeError(f"bse_bhavcopy: HTTP {resp.status_code} for {url}") from exc

        return self._extract_csv(resp.content, url)

    @staticmethod
    def _extract_csv(zip_bytes: bytes, url: str) -> bytes:
        """Unzip in-memory and return the single CSV member (see NSE)."""
        try:
            with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
                csv_names = [n for n in zf.namelist() if n.lower().endswith(".csv")]
                if not csv_names:
                    raise RuntimeError(f"bse_bhavcopy: no CSV in archive {url}")
                return zf.read(csv_names[0])
        except zipfile.BadZipFile as exc:
            raise RuntimeError(f"bse_bhavcopy: bad ZIP from {url}: {exc}") from exc

    def parse(self, csv_bytes: bytes, target_date: date) -> list[Record]:
        """
        Parse BSE bhavcopy CSV bytes into OHLC + volume Records.

        Pure function (unit-tested with a fixture).  Keeps rows whose SC_GROUP
        is an equity group; skips rows that fail validation with a warning.
        """
        records: list[Record] = []
        text = csv_bytes.decode("latin-1")
        reader = csv.DictReader(io.StringIO(text))

        for raw in reader:
            row = {(k or "").strip(): (v or "").strip() for k, v in raw.items()}

            # BSE groups carry trailing spaces in some files; already stripped.
            if row.get("SC_GROUP", "") not in _EQUITY_GROUPS:
                continue

            try:
                # model_validate() (vs kwargs) lets pydantic coerce raw strings
                # to float without mypy flagging str→float (see nse.py).
                bhav = BhavcopyRow.model_validate(
                    {
                        "symbol": row.get("SC_NAME", ""),
                        "series": row.get("SC_GROUP", ""),
                        "open": row.get("OPEN", ""),
                        "high": row.get("HIGH", ""),
                        "low": row.get("LOW", ""),
                        "close": row.get("CLOSE", ""),
                        "volume": row.get("NO_OF_SHRS", ""),
                        "isin": row.get("ISIN_CODE", ""),
                    }
                )
            except (ValidationError, ValueError) as exc:
                log.warning(
                    "bse.row_skip",
                    source=self.name,
                    symbol=row.get("SC_NAME"),
                    error=str(exc),
                )
                continue

            sc_code = row.get("SC_CODE", "")
            records.extend(self._records_for_row(bhav, target_date, sc_code))

        log.info(
            "bse.parsed",
            source=self.name,
            date=str(target_date),
            symbols=len(records) // 5 if records else 0,
            records=len(records),
        )
        return records

    def _records_for_row(
        self, bhav: "BhavcopyRow", obs_date: date, sc_code: str
    ) -> list[Record]:
        """Expand one BSE row into 5 dimension Records (exchange tag = BSE)."""
        tags = {
            "exchange": "BSE",
            "isin": bhav.isin,
            "sc_code": sc_code,
            "group": bhav.series,
        }
        out: list[Record] = []

        prices = {
            "open_price": bhav.open,
            "high_price": bhav.high,
            "low_price": bhav.low,
            "close_price": bhav.close,
        }
        for dimension, value in prices.items():
            out.append(
                Record(
                    source=self.name,
                    series=bhav.symbol,
                    dimension=dimension,
                    value=value,
                    date=obs_date,
                    granularity="daily",
                    unit="INR",
                    region="india",
                    tags=tags,
                )
            )

        out.append(
            Record(
                source=self.name,
                series=bhav.symbol,
                dimension="volume",
                value=bhav.volume,
                date=obs_date,
                granularity="daily",
                unit="shares",
                region="india",
                tags=tags,
            )
        )
        return out
