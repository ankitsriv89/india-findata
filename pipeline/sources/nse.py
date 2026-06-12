"""
pipeline.sources.nse — NSE (National Stock Exchange) daily equity bhavcopy.

The "bhavcopy" is NSE's official end-of-day price report: one row per traded
security with OHLC prices, traded quantity, and value.  It is published as a
ZIP-compressed CSV after market close each trading day — no authentication
required, which is why we use it instead of scraping the (JavaScript-heavy,
session-gated) live NSE site.

URL pattern (official NSE archives):
    https://archives.nseindia.com/content/historical/EQUITIES/
        <YYYY>/<MON>/cm<DD><MON><YYYY>bhav.csv.zip
    e.g. cm02JUN2026bhav.csv.zip   (for 2 June 2026)

CSV columns (legacy bhavcopy format):
    SYMBOL, SERIES, OPEN, HIGH, LOW, CLOSE, LAST, PREVCLOSE,
    TOTTRDQTY, TOTTRDVAL, TIMESTAMP, TOTALTRADES, ISIN

Normalisation:
    We keep only SERIES == "EQ" (ordinary equity — skip BE/BL/etc. settlement
    series).  Each symbol becomes one `series` value, and we emit FIVE Records
    per symbol — one per dimension: open_price, high_price, low_price,
    close_price, volume.  This fits the universal Record schema with no new
    columns: the dashboard queries a single (source, series, dimension).

Volume note (roadmap challenge):
    ~2000 symbols × 5 dimensions ≈ 10k Records/day.  insert_batch() already
    chunks at 1000 rows, so a single day's fetch becomes ~10 INSERTs.  A
    fixture test asserts the per-symbol Record count so this stays correct.

Data-quirk discipline (CLAUDE.md):
    Bhavcopy occasionally contains rows with blank prices (suspended scrips)
    or stray header/footer lines.  We validate every row through pydantic and
    SKIP bad rows with a logged warning — never crash, never insert NaN.
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

# NSE serves bhavcopy ZIPs from this archive host.  No API key needed.
_NSE_ARCHIVE_BASE = "https://archives.nseindia.com/content/historical/EQUITIES"

# NSE's archive blocks clients that don't look like a browser, so we send a
# minimal browser-like User-Agent.  This is a public bulk file, not scraping
# of a dynamic page (allowed by CLAUDE.md).
_BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept": "*/*",
}

# Polite delay between per-day fetches inside a backfill loop.  NSE publishes
# no formal rate limit; 0.5s/day keeps us well-behaved over a long backfill.
_RATE_LIMIT_SLEEP = 0.5

# Three-letter uppercase month abbreviations as NSE writes them in filenames.
_MONTHS = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN",
           "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]


class NSEBhavcopySource(Source):
    """
    Fetches the daily NSE equity bhavcopy and normalises it to Records.

    Each call to fetch(target_date) downloads exactly one day's ZIP, unzips it
    in memory, parses the CSV with the stdlib `csv` module (no pandas — CLAUDE.md),
    filters to EQ series, and emits OHLC + volume Records per symbol.

    Args:
        None — bhavcopy needs no credentials.  A module-level httpx.Client is
        created once and reused (CLAUDE.md: never one client per request).
    """

    name = "nse_bhavcopy"  # Record.source + pipeline_runs key

    def __init__(self) -> None:
        # follow_redirects: NSE occasionally 301s archive paths.
        self._client = httpx.Client(
            timeout=30.0, follow_redirects=True, headers=_BROWSER_HEADERS
        )

    def fetch(self, target_date: date) -> list[Record]:
        """
        Fetch and parse the bhavcopy for a single trading day.

        Args:
            target_date: The trading day to fetch.  Weekends/holidays have no
                         file — the source returns [] (the 404 is expected and
                         logged at debug level, not raised).

        Returns:
            List of OHLC + volume Records for every EQ-series symbol.  Empty
            list if the file does not exist (non-trading day) or download fails.

        Never raises — the scheduler logs failures to pipeline_runs.
        """
        raw = self._download(target_date)
        if raw is None:
            return []
        return self.parse(raw, target_date)

    def backfill(self, from_date: date, to_date: date) -> list[Record]:
        """
        Fetch every trading-day bhavcopy in [from_date, to_date].

        Walks the range day by day.  Non-trading days simply yield no file and
        are skipped.  Sleeps between days to stay polite to the NSE archive.

        Args:
            from_date: Start of range (inclusive).
            to_date:   End of range (inclusive).

        Returns:
            All Records across the range (caller batches the insert).
        """
        records: list[Record] = []
        current = from_date
        while current <= to_date:
            day_records = self.fetch(current)
            records.extend(day_records)
            time.sleep(_RATE_LIMIT_SLEEP)  # polite delay between archive hits
            current += timedelta(days=1)
        return records

    def _build_url(self, target_date: date) -> str:
        """
        Construct the bhavcopy ZIP URL for a date.

        Filename example for 2 June 2026: cm02JUN2026bhav.csv.zip
        The day is zero-padded; the month is the uppercase 3-letter abbrev.
        """
        dd = f"{target_date.day:02d}"
        mon = _MONTHS[target_date.month - 1]
        yyyy = target_date.year
        filename = f"cm{dd}{mon}{yyyy}bhav.csv.zip"
        return f"{_NSE_ARCHIVE_BASE}/{yyyy}/{mon}/{filename}"

    def _download(self, target_date: date) -> bytes | None:
        """
        Download the ZIP for target_date and return the inner CSV bytes.

        Returns None (not an exception) when the file is missing — non-trading
        days legitimately have no bhavcopy, so a 404 is normal, not an error.

        Raises:
            RuntimeError: only for unexpected failures (network, corrupt ZIP),
                          wrapped with source context per CLAUDE.md.
        """
        url = self._build_url(target_date)
        try:
            resp = self._client.get(url)
        except Exception as exc:
            raise RuntimeError(f"nse_bhavcopy: download {url}: {exc}") from exc

        # 404 = non-trading day (weekend/holiday).  Expected; skip quietly.
        if resp.status_code == 404:
            log.debug("nse.no_file", date=str(target_date), url=url)
            return None
        try:
            resp.raise_for_status()
        except Exception as exc:
            raise RuntimeError(f"nse_bhavcopy: HTTP {resp.status_code} for {url}") from exc

        return self._extract_csv(resp.content, url)

    @staticmethod
    def _extract_csv(zip_bytes: bytes, url: str) -> bytes:
        """
        Unzip the in-memory bhavcopy archive and return the single CSV member.

        The bhavcopy ZIP contains exactly one .csv file.  We read it without
        touching disk (io.BytesIO) so the source stays stateless.

        Raises:
            RuntimeError: if the archive is not a valid ZIP or has no CSV member.
        """
        try:
            with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
                csv_names = [n for n in zf.namelist() if n.lower().endswith(".csv")]
                if not csv_names:
                    raise RuntimeError(f"nse_bhavcopy: no CSV in archive {url}")
                return zf.read(csv_names[0])
        except zipfile.BadZipFile as exc:
            raise RuntimeError(f"nse_bhavcopy: bad ZIP from {url}: {exc}") from exc

    def parse(self, csv_bytes: bytes, target_date: date) -> list[Record]:
        """
        Parse bhavcopy CSV bytes into OHLC + volume Records.

        Pure function (no network) — this is what the unit tests exercise with
        a fixture CSV.  Filters to SERIES == "EQ" and skips any row that fails
        pydantic validation (blank prices, malformed numbers, header noise),
        logging a warning per skipped row.

        Args:
            csv_bytes:   Raw decoded-able CSV content from the bhavcopy.
            target_date: The trading day these rows belong to (used as
                         Record.date — the CSV's TIMESTAMP column is the same
                         day but formatted inconsistently across years, so we
                         trust the requested date instead).

        Returns:
            Five Records per valid EQ symbol: open/high/low/close + volume.
        """
        records: list[Record] = []

        # csv.DictReader over a text stream.  NSE bhavcopy is plain ASCII; we
        # decode latin-1 as a safe superset to tolerate the rare stray byte.
        text = csv_bytes.decode("latin-1")
        reader = csv.DictReader(io.StringIO(text))

        for raw in reader:
            # Bhavcopy headers sometimes carry trailing spaces ("SYMBOL ");
            # normalise keys so the validator sees canonical names.
            row = {(k or "").strip(): (v or "").strip() for k, v in raw.items()}

            if row.get("SERIES") != "EQ":
                continue  # equity-only — skip BE/BL/IL settlement series

            try:
                # model_validate() (vs kwargs) lets the pydantic "before"
                # validators coerce the raw CSV strings to float without mypy
                # flagging str→float at the call site.
                bhav = BhavcopyRow.model_validate(
                    {
                        "symbol": row.get("SYMBOL", ""),
                        "series": row.get("SERIES", ""),
                        "open": row.get("OPEN", ""),
                        "high": row.get("HIGH", ""),
                        "low": row.get("LOW", ""),
                        "close": row.get("CLOSE", ""),
                        "volume": row.get("TOTTRDQTY", ""),
                        "isin": row.get("ISIN", ""),
                    }
                )
            except (ValidationError, ValueError) as exc:
                # Suspended scrips have blank prices; malformed rows happen.
                # Skip-not-crash discipline (CLAUDE.md).
                log.warning(
                    "nse.row_skip",
                    source=self.name,
                    symbol=row.get("SYMBOL"),
                    error=str(exc),
                )
                continue

            records.extend(self._records_for_row(bhav, target_date))

        log.info(
            "nse.parsed",
            source=self.name,
            date=str(target_date),
            symbols=len(records) // 5 if records else 0,
            records=len(records),
        )
        return records

    def _records_for_row(self, bhav: "BhavcopyRow", obs_date: date) -> list[Record]:
        """
        Expand one validated bhavcopy row into its 5 dimension Records.

        OHLC prices share unit "INR"; volume uses unit "shares".  The exchange,
        ISIN, and EQ series go into tags so the heatmap/movers queries can group
        without new columns.
        """
        tags = {"exchange": "NSE", "isin": bhav.isin, "series": "EQ"}
        out: list[Record] = []

        # Four price dimensions
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

        # Volume dimension (shares traded)
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
