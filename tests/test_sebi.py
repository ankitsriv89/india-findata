"""
tests.test_sebi — unit tests for FII/DII flow parsing.

No network: call FIIDIISource.parse() on fixture bytes.  Verifies category
mapping, negative-net handling (valid, not skipped), date parsing, and that
unknown categories / missing values are skipped.
"""

from datetime import date
from pathlib import Path

import pytest

from pipeline.sources.sebi import FIIDIISource, _parse_flow_date

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def source() -> FIIDIISource:
    return FIIDIISource()


@pytest.fixture
def csv_bytes() -> bytes:
    return (FIXTURES / "fii_dii_sample.csv").read_bytes()


def test_category_mapping(source, csv_bytes):
    """FII/FPI → FII_NET_EQUITY, DII → DII_NET_EQUITY."""
    records = source.parse(csv_bytes)
    series = {r.series for r in records}
    assert "FII_NET_EQUITY" in series
    assert "DII_NET_EQUITY" in series


def test_negative_net_kept(source, csv_bytes):
    """Net selling (negative value) is valid data and must NOT be skipped."""
    records = source.parse(csv_bytes)
    fii = [r for r in records if r.series == "FII_NET_EQUITY"]
    values = [r.value for r in fii]
    assert -1234.56 in values  # 02-Jun FII net sell


def test_skips_unknown_category_and_missing(source, csv_bytes):
    """The 'MF' category row and the NA-value DII row are dropped."""
    records = source.parse(csv_bytes)
    # Fixture has 6 rows: FII Jun2, DII Jun2, FII Jun1, DII Jun1 (all valid),
    # plus 'MF' (unknown category → skipped) and DII Jun2 NA (missing → skipped).
    # → 4 valid Records.
    assert len(records) == 4


def test_record_fields(source, csv_bytes):
    """Net-flow Records carry the right dimension/unit/date."""
    records = source.parse(csv_bytes)
    r = next(r for r in records if r.series == "FII_NET_EQUITY" and r.date == date(2026, 6, 2))
    assert r.source == "fii_dii"
    assert r.dimension == "net_flow"
    assert r.unit == "crore_INR"
    assert r.granularity == "daily"
    assert r.value == -1234.56


def test_parse_flow_date_formats():
    """The date parser handles NSE's DD-Mon-YYYY and ISO fallbacks."""
    assert _parse_flow_date("02-Jun-2026") == date(2026, 6, 2)
    assert _parse_flow_date("2026-06-02") == date(2026, 6, 2)
    with pytest.raises(ValueError):
        _parse_flow_date("not-a-date")
