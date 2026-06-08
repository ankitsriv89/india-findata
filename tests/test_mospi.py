"""
tests.test_mospi — unit tests for MOSPI source parsing logic.

These tests exercise the parse/normalise functions WITHOUT any network calls.
We load fixture JSON files and pass them through the same parse methods that
the live source calls after receiving an API response.

Why test parse() separately from fetch()?
  - parse() is pure logic: input → output with no side effects.
  - fetch() requires network + API credentials — not suitable for unit tests.
  - By testing parse() in isolation, we can verify edge cases (missing values,
    null values, invalid dates) without needing a live MOSPI API token.
"""

import json
import pytest
from datetime import date
from pathlib import Path

from pipeline.sources.mospi import MOSPISource, _parse_quarter_date
from pipeline.schema.record import Record

FIXTURES = Path(__file__).parent / "fixtures"


# ── CPI tests ─────────────────────────────────────────────────────────────────

@pytest.fixture
def mospi_source():
    """MOSPISource instance with no real token — tests don't call the network."""
    return MOSPISource(api_token="test_token_unused", datagov_api_key=None)


@pytest.fixture
def cpi_raw_data():
    return json.loads((FIXTURES / "mospi_cpi_response.json").read_text())


def test_cpi_parse_valid_records(mospi_source, cpi_raw_data):
    """Valid CPI rows should produce Record objects with correct fields."""
    records = mospi_source._parse_cpi_points(
        cpi_raw_data,
        series_name="CPI_GENERAL",
        series_meta={"unit": "index_points"},
    )

    # 4 valid rows (2 with "-" and null are skipped)
    assert len(records) == 4


def test_cpi_record_fields(mospi_source, cpi_raw_data):
    """First valid record should have correct field values."""
    records = mospi_source._parse_cpi_points(
        cpi_raw_data,
        series_name="CPI_GENERAL",
        series_meta={"unit": "index_points"},
    )

    r = records[0]
    assert isinstance(r, Record)
    assert r.source == "mospi_cpi"
    assert r.series == "CPI_GENERAL"
    assert r.dimension == "index_value"
    assert r.value == 190.3
    assert r.date == date(2024, 1, 1)   # "2024-01" → first of month
    assert r.granularity == "monthly"
    assert r.unit == "index_points"
    assert r.region == "india"
    assert r.tags["base_year"] == "2012"


def test_cpi_skips_missing_values(mospi_source, cpi_raw_data):
    """Rows with value="-" or value=null must be skipped, not inserted as NaN."""
    records = mospi_source._parse_cpi_points(
        cpi_raw_data,
        series_name="CPI_GENERAL",
        series_meta={"unit": "index_points"},
    )

    values = [r.value for r in records]
    # None of the values should be NaN
    import math
    assert all(not math.isnan(v) for v in values)
    # The 4 valid values should be present
    assert 190.3 in values
    assert 194.8 in values


def test_cpi_date_normalisation(mospi_source, cpi_raw_data):
    """Monthly "YYYY-MM" strings should be converted to first-of-month dates."""
    records = mospi_source._parse_cpi_points(
        cpi_raw_data,
        series_name="CPI_GENERAL",
        series_meta={"unit": "index_points"},
    )

    for r in records:
        # All dates should be on the 1st of the month
        assert r.date.day == 1


def test_cpi_release_tag(mospi_source, cpi_raw_data):
    """Release tag (final/provisional) should be carried through to Record.tags."""
    records = mospi_source._parse_cpi_points(
        cpi_raw_data,
        series_name="CPI_GENERAL",
        series_meta={"unit": "index_points"},
    )

    # First 3 rows are "final", 4th is "provisional"
    assert records[0].tags["release"] == "final"
    assert records[3].tags["release"] == "provisional"


# ── GDP tests ─────────────────────────────────────────────────────────────────

def test_parse_quarter_date_fiscal_format():
    """'Q1 2023-24' should map to 2023-04-01 (Indian fiscal Q1 starts April)."""
    result = _parse_quarter_date("Q1 2023-24")
    assert result == date(2023, 4, 1)


def test_parse_quarter_date_all_quarters():
    """Verify all four quarters map to correct calendar month starts."""
    assert _parse_quarter_date("Q1 2024-25") == date(2024, 4, 1)
    assert _parse_quarter_date("Q2 2024-25") == date(2024, 7, 1)
    assert _parse_quarter_date("Q3 2024-25") == date(2024, 10, 1)
    assert _parse_quarter_date("Q4 2024-25") == date(2025, 1, 1)


def test_parse_quarter_date_month_range_format():
    """'Apr-Jun 2023' format should also parse correctly."""
    result = _parse_quarter_date("Apr-Jun 2023")
    assert result == date(2023, 4, 1)


def test_parse_quarter_date_invalid_returns_none():
    """Unknown formats should return None (caller skips rather than crashes)."""
    result = _parse_quarter_date("INVALID")
    assert result is None


def test_parse_quarter_date_empty_returns_none():
    result = _parse_quarter_date("")
    assert result is None
