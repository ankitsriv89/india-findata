"""
tests.test_bse — unit tests for BSE bhavcopy parsing.

Mirrors test_nse but exercises BSE's different columns (SC_NAME/SC_GROUP/
NO_OF_SHRS) and the SC_GROUP-based equity filter.
"""

from datetime import date
from pathlib import Path

import pytest

from pipeline.sources.bse import BSEBhavcopySource

FIXTURES = Path(__file__).parent / "fixtures"
OBS_DATE = date(2026, 6, 2)


@pytest.fixture
def source() -> BSEBhavcopySource:
    return BSEBhavcopySource()


@pytest.fixture
def csv_bytes() -> bytes:
    return (FIXTURES / "bse_bhavcopy_sample.csv").read_bytes()


def test_filters_to_equity_groups(source, csv_bytes):
    """Debt-segment group 'F' must be excluded; equity groups A/B/T kept."""
    records = source.parse(csv_bytes, OBS_DATE)
    names = {r.series for r in records}
    assert "DEBTINST" not in names      # group F (debt)
    assert "SMALLCAPCO" in names         # group B (equity)
    assert "SURVCO" in names             # group T (equity)


def test_skips_bad_rows(source, csv_bytes):
    """Blank-price and non-numeric-volume rows are skipped."""
    records = source.parse(csv_bytes, OBS_DATE)
    names = {r.series for r in records}
    assert "BLANKPRICE" not in names
    assert "BADVOL" not in names


def test_five_records_per_symbol(source, csv_bytes):
    """Each kept symbol yields 5 Records."""
    records = source.parse(csv_bytes, OBS_DATE)
    names = {r.series for r in records}
    assert len(records) == len(names) * 5


def test_record_fields(source, csv_bytes):
    """BSE Records carry exchange=BSE and the scrip code in tags."""
    records = source.parse(csv_bytes, OBS_DATE)
    close = next(r for r in records if r.series == "TCS" and r.dimension == "close_price")
    assert close.source == "bse_bhavcopy"
    assert close.value == 3889.00
    assert close.tags["exchange"] == "BSE"
    assert close.tags["sc_code"] == "532540"
    assert close.tags["isin"] == "INE467B01029"
    assert close.unit == "INR"
