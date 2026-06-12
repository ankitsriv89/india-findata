"""
tests.test_rbi — unit tests for RBI DBIE Excel + PDF parsing.

No network: we read committed fixture files (a tiny openpyxl-built .xlsx and a
generated .pdf with a gross-NPA table) and call the pure parse_* methods.

Coverage:
  - Excel: valid rows → Records, missing/non-numeric values skipped, month
    labels normalised to first-of-month, unknown layout returns [] (defensive)
  - PDF: NPA quarters extracted, non-numeric ratio + non-quarter rows skipped,
    fiscal-quarter labels mapped to quarter-start dates
"""

from datetime import date
from pathlib import Path

import pytest

from pipeline.sources.rbi import RBIDBIESource

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def source() -> RBIDBIESource:
    return RBIDBIESource()


# ── Excel: forex (weekly, USD billion) ────────────────────────────────────────

def test_forex_excel_valid_rows(source):
    """3 valid weekly rows; the blank-value and footnote rows are skipped."""
    records = source.parse_excel(
        (FIXTURES / "rbi_wss_sample.xlsx").read_bytes(),
        "FOREX_RESERVES", "value", "USD_billion", "weekly",
    )
    assert len(records) == 3
    assert {str(r.date) for r in records} == {"2026-05-09", "2026-05-16", "2026-05-23"}


def test_forex_record_fields(source):
    """Forex Records carry the right series/unit/granularity/tags."""
    records = source.parse_excel(
        (FIXTURES / "rbi_wss_sample.xlsx").read_bytes(),
        "FOREX_RESERVES", "value", "USD_billion", "weekly",
    )
    r = next(r for r in records if str(r.date) == "2026-05-23")
    assert r.source == "rbi_dbie"
    assert r.series == "FOREX_RESERVES"
    assert r.dimension == "value"
    assert r.value == 652.34
    assert r.unit == "USD_billion"
    assert r.granularity == "weekly"
    assert r.tags["publisher"] == "rbi"


# ── Excel: M3 (monthly, crore INR) ────────────────────────────────────────────

def test_m3_skips_non_numeric_and_normalises_month(source):
    """'N.A.' row skipped; 'Jan 2026' → 2026-01-01 (first of month)."""
    records = source.parse_excel(
        (FIXTURES / "rbi_m3_sample.xlsx").read_bytes(),
        "M3_MONEY_SUPPLY", "value", "crore_INR", "monthly",
    )
    assert len(records) == 3  # Jan, Feb, Apr (Mar is N.A.)
    for r in records:
        assert r.date.day == 1
    jan = next(r for r in records if r.date == date(2026, 1, 1))
    assert jan.value == 24500000.0
    assert jan.unit == "crore_INR"


# ── Excel: defensive layout handling ──────────────────────────────────────────

def test_unknown_layout_returns_empty(source):
    """A sheet with no recognisable date/value header yields [] (no crash)."""
    records = source.parse_excel(
        (FIXTURES / "rbi_unknown_layout.xlsx").read_bytes(),
        "X", "value", "x", "monthly",
    )
    assert records == []


def test_garbage_bytes_returns_empty(source):
    """Non-Excel bytes are handled gracefully (logged + skipped)."""
    assert source.parse_excel(b"not a workbook", "X", "value", "x", "monthly") == []


# ── PDF: NPA (quarterly) ──────────────────────────────────────────────────────

def test_npa_pdf_extracts_quarters(source):
    """3 valid quarters; 'n/a' ratio and 'All Banks' (non-quarter) skipped."""
    records = source.parse_npa((FIXTURES / "rbi_npa_sample.pdf").read_bytes())
    assert len(records) == 3
    # Indian fiscal: Q1 2025-26 → 2025-04-01, Q2 → 07-01, Q3 → 10-01
    assert {str(r.date) for r in records} == {"2025-04-01", "2025-07-01", "2025-10-01"}


def test_npa_record_fields(source):
    """NPA Records carry GROSS_NPA_RATIO / percent / quarterly."""
    records = source.parse_npa((FIXTURES / "rbi_npa_sample.pdf").read_bytes())
    q1 = next(r for r in records if str(r.date) == "2025-04-01")
    assert q1.series == "GROSS_NPA_RATIO"
    assert q1.dimension == "value"
    assert q1.value == 2.80
    assert q1.unit == "percent"
    assert q1.granularity == "quarterly"
    assert q1.tags["report"] == "npa"


def test_npa_garbage_pdf_returns_empty(source):
    """Non-PDF bytes are handled gracefully."""
    assert source.parse_npa(b"%PDF-not-really") == []
