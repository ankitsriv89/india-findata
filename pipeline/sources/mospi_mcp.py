"""
pipeline.sources.mospi_mcp — live macro data via the MOSPI MCP server.

This is the unblock for the macro layer.  MOSPI's primary REST host
(api.mospi.gov.in) IP-filters datacenter IPs, so the Phase 1 `mospi.py` source
hangs from the cloud box.  MOSPI also runs an **MCP server** at a *different*
host — `mcp.mospi.gov.in` — which is NOT filtered and serves the same official
series (CPI, WPI, IIP, National Accounts/GDP) through a small JSON-RPC API with
no authentication.  Verified live to Dec 2024 (CPI/WPI), 2026 (IIP), 2025-26
(GDP).

How the MCP server works (JSON-RPC 2.0 over an SSE response body):
  POST {url}  body: {"jsonrpc":"2.0","id":N,"method":"tools/call",
                     "params":{"name":<tool>,"arguments":{...}}}
  The 200 response is `text/event-stream`: lines `event: message` then
  `data: {json}`.  We extract the `data:` line and parse it.  The tool result
  is at result.content[0].text — itself a JSON string — which decodes to
  {data: [...rows], meta_data, msg, statusCode}.

Tools (we only need get_data; metadata was used during development to learn the
filter vocabulary — see memory `findata-mospi-mcp-contract`):
  get_data(dataset, filters)  — fetch rows for a dataset given filter k/v pairs.

Design (CLAUDE.md):
  - One module-level httpx.Client with an explicit timeout, reused across calls.
  - Each dataset is its own Source subclass with the same fetch→parse→Record
    shape as every other source.  The `parse_*` methods are pure and unit-tested
    against captured fixture responses (no network in tests).
  - Skip-not-crash: a row with a missing/non-numeric value is skipped with a
    warning, never inserted as NaN.
"""

import json
import time
from datetime import date
from itertools import count
from typing import Any

import httpx
import structlog
from pydantic import ValidationError

from pipeline.schema.record import Record
from pipeline.schema.validators import MCPDataPoint
from pipeline.sources.base import Source

log = structlog.get_logger()

# Month name → number (the MCP returns month names, not codes, in data rows).
_MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11,
    "december": 12,
}

# Polite delay between get_data calls in a backfill loop (one call per year).
_RATE_LIMIT_SLEEP = 0.3


class MCPClient:
    """
    Minimal JSON-RPC client for the MOSPI MCP server.

    Stateless (the server needs no session header).  `call_tool` POSTs a
    tools/call request, parses the SSE `data:` line, and returns the decoded
    `{data: [...], ...}` payload from result.content[0].text.

    Raises:
        RuntimeError: wrapped with context on transport or protocol errors, so
                      callers know it was the MCP layer that failed.
    """

    def __init__(self, url: str, client: httpx.Client) -> None:
        self._url = url
        self._client = client
        self._ids = count(1)

    def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """
        Call an MCP tool and return its decoded JSON payload.

        Args:
            name:      Tool name, e.g. "get_data".
            arguments: The tool's arguments dict, e.g. {"dataset": "CPI", ...}.

        Returns:
            The parsed payload dict (typically {"data": [...], "msg": ..., ...}).
        """
        body = {
            "jsonrpc": "2.0",
            "id": next(self._ids),
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        }
        try:
            resp = self._client.post(
                self._url,
                json=body,
                headers={"Accept": "application/json, text/event-stream"},
            )
            resp.raise_for_status()
        except Exception as exc:
            raise RuntimeError(f"mospi_mcp: POST {name}: {exc}") from exc

        return self._decode(resp.text, name)

    @staticmethod
    def _decode(raw: str, tool: str) -> dict[str, Any]:
        """
        Parse the SSE response body into the tool's payload dict.

        The body looks like:
            event: message
            data: {"jsonrpc":"2.0","id":1,"result":{"content":[{"text":"{...}"}]}}
        We take the first `data:` JSON object, then decode the inner
        result.content[0].text (itself JSON) into the payload.
        """
        envelope: dict[str, Any] = {}
        found = False
        for line in raw.splitlines():
            stripped = line.strip()
            if stripped.startswith("data:"):
                try:
                    envelope = json.loads(stripped[len("data:"):].strip())
                    found = True
                    break
                except json.JSONDecodeError:
                    continue
        if not found:
            # Some deployments may return plain JSON (no SSE framing).
            try:
                envelope = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise RuntimeError(f"mospi_mcp: {tool}: unparseable response") from exc

        if "error" in envelope:
            raise RuntimeError(f"mospi_mcp: {tool}: JSON-RPC error {envelope['error']}")

        content = envelope.get("result", {}).get("content", [])
        if not content:
            raise RuntimeError(f"mospi_mcp: {tool}: empty result content")

        text = content[0].get("text", "")
        try:
            payload: dict[str, Any] = json.loads(text)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"mospi_mcp: {tool}: result text not JSON") from exc
        return payload


def _obs_date(year: int, month_name: str) -> date | None:
    """Convert (year, 'December') → 2024-12-01, or None if the month is unknown."""
    m = _MONTHS.get(str(month_name).strip().lower())
    if m is None:
        return None
    return date(year, m, 1)


def _fiscal_quarter_date(fiscal_year: str, quarter: str) -> date | None:
    """
    Map an Indian fiscal year + quarter to the quarter's first day.

    "2025-26" + "Q1" → 2025-04-01 (fiscal Q1 = Apr–Jun), Q2 → Jul, Q3 → Oct,
    Q4 → Jan of the *next* calendar year.  Returns None if unparseable.
    """
    try:
        start_year = int(str(fiscal_year).split("-")[0])
    except (ValueError, IndexError):
        return None
    q = str(quarter).strip().upper().lstrip("Q")
    month_by_q = {"1": (start_year, 4), "2": (start_year, 7),
                  "3": (start_year, 10), "4": (start_year + 1, 1)}
    if q not in month_by_q:
        return None
    y, mo = month_by_q[q]
    return date(y, mo, 1)


# ── Base for the MCP-backed sources (shares the client + fetch/backfill loop) ──

class _MCPSource(Source):
    """
    Shared base for the MOSPI MCP sources.

    Subclasses set `name`, the MCP `dataset`, and implement `_filters_for_year`
    (the get_data filters for a given year) and `parse` (rows → Records).
    fetch()/backfill() here drive the year-by-year pull loop.
    """

    dataset: str

    def __init__(self, url: str) -> None:
        # 45s timeout: the MCP server proxies to MOSPI and can be slow.
        self._client = httpx.Client(timeout=45.0, follow_redirects=True)
        self._mcp = MCPClient(url, self._client)

    def _filters_for_year(self, year: int) -> dict[str, Any]:  # pragma: no cover
        raise NotImplementedError

    def parse(self, payload: dict[str, Any]) -> list[Record]:  # pragma: no cover
        raise NotImplementedError

    def _fetch_year(self, year: int) -> list[Record]:
        """Pull one year of data for this dataset; [] on any failure."""
        try:
            payload = self._mcp.call_tool(
                "get_data",
                {"dataset": self.dataset, "filters": self._filters_for_year(year)},
            )
        except Exception as exc:
            log.warning("mospi_mcp.fetch_failed", source=self.name, year=year,
                        error=str(exc))
            return []
        if isinstance(payload, dict) and payload.get("error"):
            log.warning("mospi_mcp.bad_filters", source=self.name, year=year,
                        hint=payload.get("hint"))
            return []
        return self.parse(payload)

    def fetch(self, target_date: date) -> list[Record]:
        """
        Fetch the year containing target_date plus the previous year.

        We pull two years so month-over-month revisions to the prior year are
        picked up (ReplacingMergeTree dedups on re-insert).
        """
        records: list[Record] = []
        for yr in (target_date.year - 1, target_date.year):
            records.extend(self._fetch_year(yr))
        return records

    def backfill(self, from_date: date, to_date: date) -> list[Record]:
        """Pull every calendar year in the range, sleeping between calls."""
        records: list[Record] = []
        for yr in range(from_date.year, to_date.year + 1):
            records.extend(self._fetch_year(yr))
            time.sleep(_RATE_LIMIT_SLEEP)  # polite pacing for the MCP server
        return records


# ── CPI ───────────────────────────────────────────────────────────────────────

class MOSPIMCPCPISource(_MCPSource):
    """
    All-India CPI index (base 2012) via the MOSPI MCP server.

    Emits the General/headline index and inflation rate.  The MCP returns one
    row per (sector, group, subgroup); we keep the overall/general rows so the
    series matches the Phase 1 `mospi_cpi` shape, tagging sector.
    """

    name = "mospi_cpi"
    dataset = "CPI"

    def _filters_for_year(self, year: int) -> dict[str, Any]:
        # state_code 99 = All India, series Current, base 2012 (the headline base).
        return {"base_year": "2012", "series": "Current", "state_code": 99,
                "year": year, "limit": 5000}

    def parse(self, payload: dict[str, Any]) -> list[Record]:
        """
        Parse CPI rows into index + inflation Records.

        Keeps the General index per sector (Rural/Urban/Combined).  Each kept
        row yields two Records: dimension="index_value" (the CPI index) and
        dimension="yoy_change_pct" (the published inflation rate).
        """
        records: list[Record] = []
        for raw in payload.get("data", []):
            # The General index is group "General" / subgroup "General" (the
            # all-items headline).  MOSPI labels vary slightly; match loosely.
            group = (raw.get("group") or "").strip().lower()
            if group not in {"general", "all groups", ""}:
                continue
            obs = _obs_date(raw.get("year", 0), raw.get("month", ""))
            if obs is None:
                continue
            sector = (raw.get("sector") or "Combined").strip()
            try:
                point = MCPDataPoint.model_validate({"value": raw.get("index")})
            except (ValidationError, ValueError) as exc:
                log.warning("mospi_mcp.cpi_skip", raw=raw, error=str(exc))
                continue

            tags = {"base_year": "2012", "sector": sector, "via": "mcp",
                    "status": str(raw.get("status", ""))}
            records.append(Record(
                source=self.name, series="CPI_GENERAL", dimension="index_value",
                value=point.value, date=obs, granularity="monthly",
                unit="index_points", region="india", tags=tags,
            ))
            # Inflation (YoY %) is published alongside — emit it when numeric.
            try:
                infl = MCPDataPoint.model_validate({"value": raw.get("inflation")})
                records.append(Record(
                    source=self.name, series="CPI_GENERAL",
                    dimension="yoy_change_pct", value=infl.value, date=obs,
                    granularity="monthly", unit="percent", region="india",
                    tags=tags,
                ))
            except (ValidationError, ValueError):
                pass  # inflation missing for the earliest months — fine
        log.info("mospi_mcp.cpi_parsed", records=len(records))
        return records


# ── WPI ───────────────────────────────────────────────────────────────────────

class MOSPIMCPWPISource(_MCPSource):
    """Wholesale Price Index (all-commodities headline) via MOSPI MCP."""

    name = "mospi_wpi"
    dataset = "WPI"

    def _filters_for_year(self, year: int) -> dict[str, Any]:
        return {"year": year, "limit": 5000}

    def parse(self, payload: dict[str, Any]) -> list[Record]:
        """
        Parse WPI rows into the headline index series.

        The all-commodities headline is the row whose majorgroup is "Wholesale
        price index" with null group/subgroup/item — i.e. the top-level total.
        """
        records: list[Record] = []
        for raw in payload.get("data", []):
            # Top-level total: no group/subgroup/item drill-down.
            if raw.get("group") or raw.get("subgroup") or raw.get("item"):
                continue
            obs = _obs_date(raw.get("year", 0), raw.get("month", ""))
            if obs is None:
                continue
            try:
                point = MCPDataPoint.model_validate({"value": raw.get("index_value")})
            except (ValidationError, ValueError) as exc:
                log.warning("mospi_mcp.wpi_skip", raw=raw, error=str(exc))
                continue
            records.append(Record(
                source=self.name, series="WPI_ALL_COMMODITIES",
                dimension="index_value", value=point.value, date=obs,
                granularity="monthly", unit="index_points", region="india",
                tags={"base_year": "2011-12", "via": "mcp"},
            ))
        log.info("mospi_mcp.wpi_parsed", records=len(records))
        return records


# ── IIP ───────────────────────────────────────────────────────────────────────

class MOSPIMCPIIPSource(_MCPSource):
    """Index of Industrial Production (General) via MOSPI MCP."""

    name = "mospi_iip"
    dataset = "IIP"

    def _filters_for_year(self, year: int) -> dict[str, Any]:
        # type "General" = the headline composite index.
        return {"base_year": "2011-12", "frequency": "Monthly",
                "type": "General", "year": year, "limit": 5000}

    def parse(self, payload: dict[str, Any]) -> list[Record]:
        """Parse IIP General rows into index + growth-rate Records."""
        records: list[Record] = []
        for raw in payload.get("data", []):
            obs = _obs_date(raw.get("year", 0), raw.get("month", ""))
            if obs is None:
                continue
            try:
                point = MCPDataPoint.model_validate({"value": raw.get("index")})
            except (ValidationError, ValueError) as exc:
                log.warning("mospi_mcp.iip_skip", raw=raw, error=str(exc))
                continue
            tags = {"base_year": "2011-12", "via": "mcp",
                    "category": str(raw.get("category", "General"))}
            records.append(Record(
                source=self.name, series="IIP_GENERAL", dimension="index_value",
                value=point.value, date=obs, granularity="monthly",
                unit="index_points", region="india", tags=tags,
            ))
            try:
                gr = MCPDataPoint.model_validate({"value": raw.get("growth_rate")})
                records.append(Record(
                    source=self.name, series="IIP_GENERAL",
                    dimension="yoy_change_pct", value=gr.value, date=obs,
                    granularity="monthly", unit="percent", region="india",
                    tags=tags,
                ))
            except (ValidationError, ValueError):
                pass
        log.info("mospi_mcp.iip_parsed", records=len(records))
        return records


# ── GDP (National Accounts) ───────────────────────────────────────────────────

class MOSPIMCPGDPSource(_MCPSource):
    """
    Quarterly GDP (constant + current prices) via MOSPI MCP National Accounts.

    Uses indicator_code 5 (Gross Domestic Product), frequency_code 2
    (Quarterly).  For this indicator the MCP returns the all-economy aggregate
    directly (one row per quarter), so we map rows straight to Records.
    """

    name = "mospi_gdp"
    dataset = "NAS"

    # NAS indicator codes (from get_indicators(NAS)): 5 = GDP level,
    # 22 = GDP Growth Rate.  We fetch BOTH so the dashboard's GDP_GROWTH_RATE
    # series works alongside the absolute level.
    _GDP_LEVEL_CODE = 5
    _GDP_GROWTH_CODE = 22

    def _filters_for_year(self, year: int) -> dict[str, Any]:  # pragma: no cover
        # Not used — GDP overrides the fetch loop to make two indicator calls.
        del year
        return {}

    def _filters_for_indicator(self, indicator_code: int) -> dict[str, Any]:
        # NAS doesn't accept a calendar-year filter for quarterly GDP (it uses
        # fiscal-year strings), so we pull the full series and filter by date.
        return {"base_year": "2011-12", "series": "Current",
                "frequency_code": 2, "indicator_code": indicator_code,
                "limit": 5000}

    def _fetch_indicator(self, indicator_code: int) -> list[Record]:
        """Pull one NAS indicator (level or growth) and parse it; [] on failure."""
        try:
            payload = self._mcp.call_tool(
                "get_data",
                {"dataset": self.dataset,
                 "filters": self._filters_for_indicator(indicator_code)},
            )
        except Exception as exc:
            log.warning("mospi_mcp.gdp_fetch_failed", indicator=indicator_code,
                        error=str(exc))
            return []
        return self._parse_indicator(payload, indicator_code)

    def fetch(self, target_date: date) -> list[Record]:
        """Fetch both GDP level and growth-rate series (covers all quarters)."""
        del target_date  # the MCP returns the full quarterly history
        return (self._fetch_indicator(self._GDP_LEVEL_CODE)
                + self._fetch_indicator(self._GDP_GROWTH_CODE))

    def backfill(self, from_date: date, to_date: date) -> list[Record]:
        """Fetch both indicators once, then filter to the requested range."""
        records = (self._fetch_indicator(self._GDP_LEVEL_CODE)
                   + self._fetch_indicator(self._GDP_GROWTH_CODE))
        return [r for r in records if from_date <= r.date <= to_date]

    def parse(self, payload: dict[str, Any]) -> list[Record]:
        """Parse a GDP-level (indicator 5) payload. See _parse_indicator."""
        return self._parse_indicator(payload, self._GDP_LEVEL_CODE)

    def _parse_indicator(
        self, payload: dict[str, Any], indicator_code: int
    ) -> list[Record]:
        """
        Parse a NAS GDP payload into Records.

        indicator 5  → series "GDP", dimensions constant_price/current_price
                       (crore INR; the all-economy aggregate, one row per quarter).
        indicator 22 → series "GDP_GROWTH_RATE", dimension yoy_change_pct
                       (the growth-rate value lives in the constant_price field;
                       this is the series the dashboard's /macro/gdp queries).
        """
        is_growth = indicator_code == self._GDP_GROWTH_CODE
        records: list[Record] = []
        for raw in payload.get("data", []):
            obs = _fiscal_quarter_date(raw.get("year", ""), raw.get("quarter", ""))
            if obs is None:
                continue
            tags = {"base_year": "2011-12", "via": "mcp",
                    "fiscal_year": str(raw.get("year", "")),
                    "quarter": str(raw.get("quarter", ""))}
            if is_growth:
                # Growth rate: the % is in constant_price (real growth).
                try:
                    v = MCPDataPoint.model_validate({"value": raw.get("constant_price")})
                except (ValidationError, ValueError):
                    continue
                records.append(Record(
                    source=self.name, series="GDP_GROWTH_RATE",
                    dimension="yoy_change_pct", value=round(v.value, 2), date=obs,
                    granularity="quarterly", unit="percent", region="india",
                    tags=tags,
                ))
            else:
                for dimension in ("constant_price", "current_price"):
                    try:
                        v = MCPDataPoint.model_validate({"value": raw.get(dimension)})
                    except (ValidationError, ValueError):
                        continue
                    records.append(Record(
                        source=self.name, series="GDP", dimension=dimension,
                        value=round(v.value, 3), date=obs, granularity="quarterly",
                        unit="crore_INR", region="india", tags=tags,
                    ))
        log.info("mospi_mcp.gdp_parsed", indicator=indicator_code,
                 records=len(records))
        return records
