"""
tests.test_mospi_mcp — unit tests for the MOSPI MCP sources.

No network: tests use **captured real responses** from the live MOSPI MCP server
(tests/fixtures/mcp_*_response.txt — the raw SSE bodies).  We exercise:
  - MCPClient._decode (SSE framing → payload dict)
  - each source's parse() (payload → Records) with correct fields
  - skip-not-crash on missing/non-numeric values

These fixtures are the actual server output, so the tests pin the real contract.
"""

from pathlib import Path

import pytest

from pipeline.sources.mospi_mcp import (
    MCPClient,
    MOSPIMCPCPISource,
    MOSPIMCPGDPSource,
    MOSPIMCPIIPSource,
    MOSPIMCPWPISource,
)

FIXTURES = Path(__file__).parent / "fixtures"


def _payload(name: str) -> dict:
    """Decode a captured SSE fixture into its payload dict."""
    return MCPClient._decode((FIXTURES / name).read_text(), name)


# ── MCPClient._decode (SSE framing) ──────────────────────────────────────────

def test_decode_extracts_payload_from_sse():
    p = _payload("mcp_cpi_response.txt")
    assert isinstance(p, dict)
    assert "data" in p and isinstance(p["data"], list)


def test_decode_plain_json_fallback():
    """A non-SSE plain-JSON body is still decoded (defensive fallback)."""
    raw = '{"jsonrpc":"2.0","id":1,"result":{"content":[{"text":"{\\"data\\": [1,2]}"}]}}'
    assert MCPClient._decode(raw, "t") == {"data": [1, 2]}


def test_decode_raises_on_jsonrpc_error():
    raw = 'data: {"jsonrpc":"2.0","id":1,"error":{"code":-32000,"message":"boom"}}'
    with pytest.raises(RuntimeError):
        MCPClient._decode(raw, "t")


# ── CPI ──────────────────────────────────────────────────────────────────────

def test_cpi_parse_fields():
    src = MOSPIMCPCPISource.__new__(MOSPIMCPCPISource)
    records = src.parse(_payload("mcp_cpi_response.txt"))
    assert records, "expected CPI records from the fixture"
    idx = next(r for r in records if r.dimension == "index_value")
    assert idx.source == "mospi_cpi"
    assert idx.series == "CPI_GENERAL"
    assert idx.unit == "index_points"
    assert idx.granularity == "monthly"
    assert idx.date.day == 1  # normalised to first of month
    assert idx.tags["via"] == "mcp"
    assert idx.tags["sector"] in {"Rural", "Urban", "Combined"}


def test_cpi_emits_index_and_inflation():
    src = MOSPIMCPCPISource.__new__(MOSPIMCPCPISource)
    records = src.parse(_payload("mcp_cpi_response.txt"))
    dims = {r.dimension for r in records}
    assert "index_value" in dims
    assert "yoy_change_pct" in dims  # inflation carried through


# ── WPI ──────────────────────────────────────────────────────────────────────

def test_wpi_headline_only():
    src = MOSPIMCPWPISource.__new__(MOSPIMCPWPISource)
    records = src.parse(_payload("mcp_wpi_response.txt"))
    assert records
    r = records[0]
    assert r.series == "WPI_ALL_COMMODITIES"
    assert r.dimension == "index_value"
    assert r.unit == "index_points"
    # Headline = no group/subgroup drill-down → exactly one row per month.
    assert len({rec.date for rec in records}) == len(records)


# ── IIP ──────────────────────────────────────────────────────────────────────

def test_iip_parse_fields():
    src = MOSPIMCPIIPSource.__new__(MOSPIMCPIIPSource)
    records = src.parse(_payload("mcp_iip_response.txt"))
    assert records
    idx = next(r for r in records if r.dimension == "index_value")
    assert idx.series == "IIP_GENERAL"
    assert idx.source == "mospi_iip"
    assert idx.unit == "index_points"
    assert {r.dimension for r in records} >= {"index_value", "yoy_change_pct"}


# ── GDP ──────────────────────────────────────────────────────────────────────

def test_gdp_level_records():
    src = MOSPIMCPGDPSource.__new__(MOSPIMCPGDPSource)
    records = src._parse_indicator(_payload("mcp_gdp_response.txt"), 5)
    assert records
    r = records[0]
    assert r.series == "GDP"
    assert r.dimension in {"constant_price", "current_price"}
    assert r.unit == "crore_INR"
    assert r.granularity == "quarterly"
    # Fiscal Q1 → April-start date.
    assert r.date.month in {1, 4, 7, 10}


def test_gdp_growth_records():
    src = MOSPIMCPGDPSource.__new__(MOSPIMCPGDPSource)
    records = src._parse_indicator(_payload("mcp_gdp_growth_response.txt"), 22)
    assert records
    r = records[0]
    assert r.series == "GDP_GROWTH_RATE"
    assert r.dimension == "yoy_change_pct"
    assert r.unit == "percent"


# ── skip-not-crash ───────────────────────────────────────────────────────────

def test_skips_missing_and_nonnumeric_values():
    """Rows with null/NA index must be skipped, never inserted as NaN."""
    src = MOSPIMCPCPISource.__new__(MOSPIMCPCPISource)
    payload = {
        "data": [
            {"year": 2024, "month": "December", "sector": "Rural",
             "group": "General", "index": None, "inflation": "5.0"},      # skip index
            {"year": 2024, "month": "December", "sector": "Urban",
             "group": "General", "index": "NA", "inflation": "4.0"},       # skip index
            {"year": 2024, "month": "December", "sector": "Combined",
             "group": "General", "index": "190.5", "inflation": "4.5"},    # valid
        ]
    }
    records = src.parse(payload)
    idx = [r for r in records if r.dimension == "index_value"]
    assert len(idx) == 1
    assert idx[0].value == 190.5


def test_unknown_month_skipped():
    src = MOSPIMCPWPISource.__new__(MOSPIMCPWPISource)
    payload = {"data": [{"year": 2024, "month": "Frobuary", "index_value": "100"}]}
    assert src.parse(payload) == []
