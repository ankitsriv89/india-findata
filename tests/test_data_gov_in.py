"""
tests.test_data_gov_in — unit tests for data.gov.in source parsing.

Tests the _parse_date_flexible() helper (handles all the inconsistent
date formats across government datasets) and the RBI rates parse logic.
"""

import json
from datetime import date
from pathlib import Path

import pytest

from pipeline.schema.record import Record
from pipeline.sources.data_gov_in import RBIRatesSource, _parse_date_flexible

FIXTURES = Path(__file__).parent / "fixtures"


# ── _parse_date_flexible ───────────────────────────────────────────────────────

@pytest.mark.parametrize("date_str,expected", [
    ("2024-02-08",   date(2024, 2, 8)),   # ISO 8601
    ("08/02/2024",   date(2024, 2, 8)),   # DD/MM/YYYY (common in Indian datasets)
    ("08-02-2024",   date(2024, 2, 8)),   # DD-MM-YYYY
    ("Feb 08, 2024", date(2024, 2, 8)),   # English month name
    ("08-Feb-2024",  date(2024, 2, 8)),   # DD-Mon-YYYY (RBI publications)
    ("08 Feb 2024",  date(2024, 2, 8)),   # DD Mon YYYY
])
def test_parse_date_flexible_known_formats(date_str, expected):
    """All date formats used across data.gov.in datasets should parse correctly."""
    assert _parse_date_flexible(date_str) == expected


def test_parse_date_flexible_unknown_returns_none():
    """Unrecognised format returns None so the caller can skip the record."""
    assert _parse_date_flexible("32-13-2024") is None
    assert _parse_date_flexible("not-a-date") is None
    assert _parse_date_flexible("") is None


def test_parse_date_flexible_strips_whitespace():
    """Leading/trailing whitespace in API responses should be tolerated."""
    assert _parse_date_flexible("  2024-02-08  ") == date(2024, 2, 8)


# ── RBIRatesSource.parse ───────────────────────────────────────────────────────

@pytest.fixture
def rbi_source():
    return RBIRatesSource(api_key="test_key_unused")


@pytest.fixture
def rates_raw_data():
    return json.loads((FIXTURES / "rbi_rates_response.json").read_text())


def test_rbi_rates_parse_produces_pairs(rbi_source, rates_raw_data):
    """
    Each valid row should produce two Records: one for repo, one for reverse repo.
    With 6 fixture rows, 2 should be skipped (invalid date + non-numeric repo rate).
    """
    records = []
    for raw in rates_raw_data:
        records.extend(rbi_source._parse_rate_record(raw))

    # 4 valid rows × 2 series = 8 records
    # Row with "invalid-date" → 0 records (date parse fails)
    # Row with "not_a_number" repo rate → only 1 record (reverse repo still valid)
    repo_records = [r for r in records if r.series == "REPO_RATE"]
    rr_records   = [r for r in records if r.series == "REVERSE_REPO_RATE"]

    assert len(repo_records) >= 4
    assert len(rr_records)   >= 4


def test_rbi_rates_record_fields(rbi_source, rates_raw_data):
    """First valid row should produce a Record with correct field values."""
    records = rbi_source._parse_rate_record(rates_raw_data[0])

    repo = next(r for r in records if r.series == "REPO_RATE")
    assert isinstance(repo, Record)
    assert repo.source == "rbi_rates"
    assert repo.dimension == "rate_pct"
    assert repo.value == 6.5
    assert repo.date == date(2023, 2, 8)
    assert repo.granularity == "daily"
    assert repo.unit == "percent"
    assert repo.region == "india"


def test_rbi_rates_skips_invalid_date(rbi_source, rates_raw_data):
    """Row with 'invalid-date' should be skipped (returns empty list)."""
    invalid_row = {"effective_date": "invalid-date", "repo_rate": "6.50", "reverse_repo_rate": "3.35"}
    records = rbi_source._parse_rate_record(invalid_row)
    assert records == []


def test_rbi_rates_skips_non_numeric_value(rbi_source, rates_raw_data):
    """Row with non-numeric repo_rate should skip repo but still emit reverse_repo."""
    row = {"effective_date": "2024-06-07", "repo_rate": "not_a_number", "reverse_repo_rate": "3.35"}
    records = rbi_source._parse_rate_record(row)

    # Should have 0 repo records but 1 reverse_repo record
    series = {r.series for r in records}
    assert "REPO_RATE" not in series
    assert "REVERSE_REPO_RATE" in series


def test_rbi_rates_skips_missing_date(rbi_source):
    """Row with no date field at all should return empty list."""
    records = rbi_source._parse_rate_record({"repo_rate": "6.50"})
    assert records == []
