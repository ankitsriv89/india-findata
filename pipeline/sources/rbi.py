"""
pipeline.sources.rbi — RBI DBIE banking & credit indicators (Phase 3).

The RBI's Database on Indian Economy (DBIE, data.rbi.org.in) has **no clean
public API**.  Data is published as downloadable Excel workbooks and, for some
reports, PDF tables — with layouts that drift between releases.  This source
therefore does messy, *defensive* extraction:

    forex reserves      weekly    Excel (.xlsx)   USD_billion
    M3 broad money      monthly   Excel (.xlsx)   crore_INR
    bank credit growth  monthly   Excel (.xlsx)   percent
    gross NPA ratio     quarterly PDF             percent

Design rules (CLAUDE.md):
  - **Skip, don't crash.**  DBIE renames columns and reshuffles rows without
    notice.  Every extractor logs a warning and skips a row/column it can't
    understand — a layout change must never take down the scheduler.
  - **stdlib + openpyxl + pdfplumber only** — no pandas.  We read worksheet
    cells directly and PDF tables via pdfplumber's `extract_tables()`.
  - Each dataset has a pure `parse_*` method the unit tests call with fixture
    bytes, so the whole source is verified offline.

Relationship to the Phase 1 data.gov.in RBI sources:
  `rbi_forex` (data.gov.in) still exists for the headline forex number; this
  DBIE source is the richer, multi-indicator banking layer.  They write
  different `source` values so they never collide in the `records` table.
"""

import io
from collections.abc import Sequence
from datetime import date, datetime

import httpx
import openpyxl
import pdfplumber
import structlog
from pydantic import ValidationError

from pipeline.schema.record import Record
from pipeline.schema.validators import RBIDataPoint
from pipeline.sources.base import Source

log = structlog.get_logger()

_BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept": "*/*",
}

# Best-effort DBIE download URLs.  Kept in one dict so updating them when RBI
# moves a publication is a single edit.  These are the fragile, IP-blockable
# endpoints the data-source work will revisit (see memory); the source is
# fully fixture-tested regardless of whether these resolve.
_DBIE_URLS = {
    "forex": "https://data.rbi.org.in/DBIE/wss_forex.xlsx",
    "m3": "https://data.rbi.org.in/DBIE/m3_money.xlsx",
    "credit": "https://data.rbi.org.in/DBIE/bank_credit.xlsx",
    "npa": "https://data.rbi.org.in/DBIE/gross_npa.pdf",
}

# How each Excel dataset maps onto a Record.  (series, dimension, unit).
_EXCEL_META = {
    "forex": ("FOREX_RESERVES", "value", "USD_billion", "weekly"),
    "m3": ("M3_MONEY_SUPPLY", "value", "crore_INR", "monthly"),
    "credit": ("BANK_CREDIT_GROWTH", "value", "percent", "monthly"),
}


class RBIDBIESource(Source):
    """
    Fetches RBI DBIE banking indicators (forex, M3, credit, NPA).

    A single source class covers all four datasets because they share the same
    fetch→parse→Record shape and schedule context.  fetch() pulls every dataset;
    the per-dataset `parse_*` methods are pure and unit-tested with fixtures.

    Args:
        None — DBIE downloads need no credentials.
    """

    name = "rbi_dbie"

    def __init__(self) -> None:
        self._client = httpx.Client(
            timeout=60.0, follow_redirects=True, headers=_BROWSER_HEADERS
        )

    def fetch(self, target_date: date) -> list[Record]:
        """
        Fetch all DBIE datasets and return their combined Records.

        Each dataset is fetched independently; a failure on one (download error
        or layout it can't parse) logs a warning and contributes [] rather than
        aborting the others.  target_date is used only for logging context — the
        publications carry their own observation dates.
        """
        records: list[Record] = []
        for key, (series, dimension, unit, granularity) in _EXCEL_META.items():
            records.extend(
                self._fetch_excel(key, series, dimension, unit, granularity)
            )
        records.extend(self._fetch_npa())
        log.info("rbi_dbie.fetched", source=self.name, records=len(records),
                 target_date=str(target_date))
        return records

    def backfill(self, from_date: date, to_date: date) -> list[Record]:
        """
        Backfill DBIE data.

        DBIE workbooks already contain long history (years of weekly/monthly
        rows), so a single fetch returns the full series; we filter to the
        requested window.  There is no per-date archive to walk.
        """
        records = self.fetch(to_date)
        return [r for r in records if from_date <= r.date <= to_date]

    # ── Excel datasets (forex / M3 / credit) ──────────────────────────────────

    def _fetch_excel(
        self, key: str, series: str, dimension: str, unit: str, granularity: str
    ) -> list[Record]:
        """Download one Excel dataset and parse it; [] on any failure."""
        url = _DBIE_URLS[key]
        try:
            resp = self._client.get(url)
            resp.raise_for_status()
        except Exception as exc:
            log.warning("rbi_dbie.excel_fetch_failed", dataset=key, error=str(exc))
            return []
        return self.parse_excel(resp.content, series, dimension, unit, granularity)

    def parse_excel(
        self,
        xlsx_bytes: bytes,
        series: str,
        dimension: str,
        unit: str,
        granularity: str,
    ) -> list[Record]:
        """
        Parse a DBIE Excel workbook into Records.

        Pure function (unit-tested with an openpyxl-built fixture).  Defensive
        layout handling:
          - Reads the first worksheet.
          - Finds the header row by locating the cells that look like "Date"/
            "Week"/"Month" and a value column; if it can't, logs and returns [].
          - Each data row → RBIDataPoint (numeric guard).  Rows with an
            unparseable date or non-numeric value are skipped with a warning.

        Args:
            xlsx_bytes: Raw .xlsx file bytes.
            series/dimension/unit/granularity: Record metadata for this dataset.
        """
        records: list[Record] = []
        try:
            wb = openpyxl.load_workbook(io.BytesIO(xlsx_bytes), read_only=True, data_only=True)
        except Exception as exc:
            log.warning("rbi_dbie.excel_open_failed", series=series, error=str(exc))
            return []

        ws = wb.active
        if ws is None:
            log.warning("rbi_dbie.excel_no_sheet", series=series)
            return []

        # Materialise rows (read_only worksheets are generators).
        rows = [list(r) for r in ws.iter_rows(values_only=True)]
        date_col, value_col, header_idx = _locate_columns(rows)
        if date_col is None or value_col is None:
            # Layout we don't recognise — skip-not-crash.
            log.warning("rbi_dbie.excel_unknown_layout", series=series)
            return []

        for row in rows[header_idx + 1:]:
            if date_col >= len(row) or value_col >= len(row):
                continue  # ragged row — skip
            raw_date = row[date_col]
            raw_value = row[value_col]
            obs = _coerce_date(raw_date)
            if obs is None:
                continue  # blank/garbage date row (footnotes, totals) — skip

            try:
                # model_validate() lets the "before" validator coerce the raw
                # cell (str/number) without mypy flagging the call-site type.
                point = RBIDataPoint.model_validate(
                    {"observation": obs, "value": raw_value, "series": series}
                )
            except (ValidationError, ValueError) as exc:
                log.warning("rbi_dbie.excel_row_skip", series=series,
                            raw_value=raw_value, error=str(exc))
                continue

            records.append(
                Record(
                    source=self.name,
                    series=series,
                    dimension=dimension,
                    value=point.value,
                    date=point.observation,
                    granularity=granularity,
                    unit=unit,
                    region="india",
                    tags={"publisher": "rbi", "via": "dbie"},
                )
            )

        log.info("rbi_dbie.excel_parsed", series=series, records=len(records))
        return records

    # ── NPA dataset (PDF) ─────────────────────────────────────────────────────

    def _fetch_npa(self) -> list[Record]:
        """Download the quarterly NPA PDF and parse it; [] on any failure."""
        url = _DBIE_URLS["npa"]
        try:
            resp = self._client.get(url)
            resp.raise_for_status()
        except Exception as exc:
            log.warning("rbi_dbie.npa_fetch_failed", error=str(exc))
            return []
        return self.parse_npa(resp.content)

    def parse_npa(self, pdf_bytes: bytes) -> list[Record]:
        """
        Extract the gross-NPA-ratio series from the quarterly RBI PDF.

        Pure function (unit-tested with a generated fixture PDF).  We use
        pdfplumber's table extraction, then look for rows shaped like
        (quarter_label, npa_ratio).  PDF table shape drifts a lot, so every row
        that doesn't yield a parseable quarter + numeric ratio is skipped with a
        warning — never a crash.

        Quarter labels use the same Indian-fiscal convention as GDP
        ("Q1 2025-26" → 2025-04-01); we reuse the existing parser for that.
        """
        records: list[Record] = []
        try:
            with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
                tables: list[list[list[str | None]]] = []
                for page in pdf.pages:
                    tables.extend(page.extract_tables() or [])
        except Exception as exc:
            log.warning("rbi_dbie.npa_open_failed", error=str(exc))
            return []

        for table in tables:
            for row in table:
                if not row or len(row) < 2:
                    continue
                quarter_label = (row[0] or "").strip()
                ratio_raw = (row[1] or "").strip()
                obs = _parse_quarter_label(quarter_label)
                if obs is None:
                    continue  # header row / non-quarter label — skip

                try:
                    point = RBIDataPoint.model_validate(
                        {"observation": obs, "value": ratio_raw,
                         "series": "GROSS_NPA_RATIO"}
                    )
                except (ValidationError, ValueError) as exc:
                    log.warning("rbi_dbie.npa_row_skip", quarter=quarter_label,
                                raw=ratio_raw, error=str(exc))
                    continue

                records.append(
                    Record(
                        source=self.name,
                        series="GROSS_NPA_RATIO",
                        dimension="value",
                        value=point.value,
                        date=point.observation,
                        granularity="quarterly",
                        unit="percent",
                        region="india",
                        tags={"publisher": "rbi", "via": "dbie", "report": "npa"},
                    )
                )

        log.info("rbi_dbie.npa_parsed", records=len(records))
        return records


# ── Module-level helpers (pure, easy to unit-test) ────────────────────────────

# Header keywords that mark the date column and the value column in DBIE Excel.
_DATE_HEADERS = {"date", "week", "week ended", "month", "as on", "period"}
_VALUE_HEADERS = {"value", "amount", "reserves", "m3", "credit", "growth",
                  "outstanding", "total", "usd", "rs", "₹"}


def _locate_columns(
    rows: Sequence[Sequence[object]],
) -> tuple[int | None, int | None, int]:
    """
    Find (date_col_index, value_col_index, header_row_index) in a DBIE sheet.

    Scans the first ~10 rows for a header row containing a date-like and a
    value-like column name (case-insensitive substring match).  Returns
    (None, None, 0) if no header is recognised — the caller then skips the
    dataset rather than guessing.
    """
    for idx, row in enumerate(rows[:10]):
        cells = [str(c).strip().lower() if c is not None else "" for c in row]
        date_col = _match_col(cells, _DATE_HEADERS)
        value_col = _match_col(cells, _VALUE_HEADERS)
        if date_col is not None and value_col is not None and date_col != value_col:
            return date_col, value_col, idx
    return None, None, 0


def _match_col(cells: list[str], keywords: set[str]) -> int | None:
    """Return the index of the first cell containing any keyword, else None."""
    for i, cell in enumerate(cells):
        if any(kw in cell for kw in keywords):
            return i
    return None


def _coerce_date(value: object) -> date | None:
    """
    Convert a DBIE date cell into a date, or None if it isn't a date.

    Handles the three shapes DBIE cells take:
      - a real datetime/date (openpyxl parses Excel date cells) → use directly
      - "YYYY-MM-DD" / "DD-MM-YYYY" / "DD Mon YYYY" strings
      - a month label like "Mar-2026" / "March 2026"
    Returns None for totals/footnote/blank cells (caller skips them).
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value

    s = str(value).strip()
    if not s:
        return None
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d %b %Y", "%d %B %Y",
                "%b-%Y", "%B %Y", "%b %Y", "%Y-%m"):
        try:
            parsed = datetime.strptime(s, fmt).date()
            # Month-only formats land on day 1 (pipeline convention).
            return parsed
        except ValueError:
            continue
    return None


def _parse_quarter_label(label: str) -> date | None:
    """
    Parse an Indian-fiscal quarter label into the quarter's first day.

    Reuses the GDP quarter parser ("Q1 2025-26" → 2025-04-01).  Returns None
    for anything that isn't a recognised quarter (header cells, blanks).
    """
    if not label:
        return None
    # Import here to avoid a top-level dependency cycle with mospi.
    from pipeline.sources.mospi import _parse_quarter_date

    return _parse_quarter_date(label)
