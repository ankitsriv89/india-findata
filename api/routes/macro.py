"""
api.routes.macro — query endpoints for macro-economic time-series data.

All endpoints query ClickHouse with FINAL (forces deduplication from
ReplacingMergeTree) and return a consistent JSON envelope:

  {
    "series": "CPI_GENERAL",
    "from": "2023-01-01",
    "to": "2026-06-08",
    "granularity": "monthly",
    "unit": "index_points",
    "data": [{"date": "2023-01-01", "value": 184.5}, ...]
  }

Error handling:
  404 — no data found for the requested parameters
  503 — ClickHouse query failed (returned as detail message)
  422 — invalid date format (FastAPI validates automatically via pydantic)

All date parameters are strings in YYYY-MM-DD format.  FastAPI coerces
them to datetime.date via the date type annotation.
"""

import structlog
from datetime import date
from typing import Any

from fastapi import APIRouter, HTTPException, Request, Query
from pydantic import BaseModel

log = structlog.get_logger()

router = APIRouter()

# Default lookback: 5 years from today
_DEFAULT_LOOKBACK_YEARS = 5


class TimeSeriesResponse(BaseModel):
    """Standard response envelope for all macro endpoints."""
    series: str
    from_date: str
    to_date: str
    granularity: str
    unit: str
    data: list[dict[str, Any]]

    model_config = {"populate_by_name": True}


def _default_from() -> date:
    """5-year lookback from today."""
    today = date.today()
    return date(today.year - _DEFAULT_LOOKBACK_YEARS, today.month, today.day)


def _query_records(
    request: Request,
    source: str,
    series: str,
    from_date: date,
    to_date: date,
    extra_where: str = "",
) -> list[dict[str, Any]]:
    """
    Execute a ClickHouse query against the records table.

    Uses FINAL to ensure we get deduplicated rows from ReplacingMergeTree.
    Always filters on date range first (uses partition pruning).

    Args:
        request:     FastAPI request (for app.state.ch_client access)
        source:      records.source filter
        series:      records.series filter
        from_date:   inclusive start date
        to_date:     inclusive end date
        extra_where: optional additional WHERE clause fragment (must start with AND)

    Returns:
        List of {"date": "YYYY-MM-DD", "value": float} dicts, ordered by date.

    Raises:
        HTTPException 503 on ClickHouse query failure.
        HTTPException 404 if no rows returned.
    """
    ch = request.app.state.ch_client

    query = f"""
        SELECT date, value
        FROM records FINAL
        WHERE source = {{source:String}}
          AND series = {{series:String}}
          AND date BETWEEN {{from_date:Date}} AND {{to_date:Date}}
          {extra_where}
        ORDER BY date
    """

    try:
        result = ch.query(
            query,
            parameters={
                "source": source,
                "series": series,
                "from_date": from_date.isoformat(),
                "to_date": to_date.isoformat(),
            },
        )
    except Exception as exc:
        log.error("macro.query_failed", source=source, series=series, error=str(exc))
        raise HTTPException(status_code=503, detail=f"ClickHouse query failed: {exc}")

    rows = [{"date": str(row[0]), "value": row[1]} for row in result.result_rows]

    if not rows:
        raise HTTPException(
            status_code=404,
            detail=f"No data found: source={source} series={series} {from_date}..{to_date}",
        )

    return rows


@router.get("/cpi", response_model=TimeSeriesResponse)
async def get_cpi(
    request: Request,
    series: str = Query(default="CPI_GENERAL", description="CPI series: CPI_GENERAL | CPI_FOOD | CPI_RURAL | CPI_URBAN"),
    from_date: date = Query(default_factory=_default_from, alias="from"),
    to_date: date = Query(default_factory=date.today, alias="to"),
) -> TimeSeriesResponse:
    """
    CPI (Consumer Price Index) time series.

    Returns monthly index values (base year 2012=100).  To compute YoY
    inflation, compare the same month across years:
      inflation_rate = (current - prev_year) / prev_year * 100

    Available series:
      CPI_GENERAL — All India CPI (headline inflation)
      CPI_FOOD    — Food and beverages sub-index
      CPI_RURAL   — Rural CPI
      CPI_URBAN   — Urban CPI
    """
    data = _query_records(request, "mospi_cpi", series, from_date, to_date)
    return TimeSeriesResponse(
        series=series,
        from_date=str(from_date),
        to_date=str(to_date),
        granularity="monthly",
        unit="index_points",
        data=data,
    )


@router.get("/iip", response_model=TimeSeriesResponse)
async def get_iip(
    request: Request,
    series: str = Query(default="IIP_GENERAL", description="IIP series: IIP_GENERAL | IIP_MANUFACTURING | IIP_MINING | IIP_ELECTRICITY"),
    from_date: date = Query(default_factory=_default_from, alias="from"),
    to_date: date = Query(default_factory=date.today, alias="to"),
) -> TimeSeriesResponse:
    """
    IIP (Index of Industrial Production) time series.

    Monthly index values (base year 2011-12=100).  Released ~2 months
    after the reference period (so recent months may be missing).

    Available series:
      IIP_GENERAL       — Composite IIP
      IIP_MANUFACTURING — Manufacturing sector
      IIP_MINING        — Mining and quarrying
      IIP_ELECTRICITY   — Electricity generation
    """
    data = _query_records(request, "mospi_iip", series, from_date, to_date)
    return TimeSeriesResponse(
        series=series,
        from_date=str(from_date),
        to_date=str(to_date),
        granularity="monthly",
        unit="index_points",
        data=data,
    )


@router.get("/gdp", response_model=TimeSeriesResponse)
async def get_gdp(
    request: Request,
    series: str = Query(default="GDP_GROWTH_RATE", description="GDP series: GDP_GROWTH_RATE"),
    from_date: date = Query(default_factory=_default_from, alias="from"),
    to_date: date = Query(default_factory=date.today, alias="to"),
) -> TimeSeriesResponse:
    """
    GDP growth rate — quarterly YoY % change.

    India's GDP is measured at constant prices (2011-12 base).  The growth
    rate is YoY (year-on-year) — comparing Q1 FY2024 vs Q1 FY2023.

    Note: data dates are the first day of the fiscal quarter:
      Q1 (Apr–Jun) → YYYY-04-01
      Q2 (Jul–Sep) → YYYY-07-01
      Q3 (Oct–Dec) → YYYY-10-01
      Q4 (Jan–Mar) → YYYY-01-01
    """
    data = _query_records(request, "mospi_gdp", series, from_date, to_date)
    return TimeSeriesResponse(
        series=series,
        from_date=str(from_date),
        to_date=str(to_date),
        granularity="quarterly",
        unit="percent",
        data=data,
    )


@router.get("/rates", response_model=TimeSeriesResponse)
async def get_rates(
    request: Request,
    series: str = Query(default="REPO_RATE", description="Rate series: REPO_RATE | REVERSE_REPO_RATE"),
    from_date: date = Query(default_factory=_default_from, alias="from"),
    to_date: date = Query(default_factory=date.today, alias="to"),
) -> TimeSeriesResponse:
    """
    RBI policy rates — repo rate and reverse repo rate history.

    Returns one row per rate change date (not daily — rates only change
    on MPC decision days, ~6 times per year).  The dashboard step chart
    should display this as a step function: the rate is constant between
    change events.

    Available series:
      REPO_RATE         — RBI repo rate (the key policy rate)
      REVERSE_REPO_RATE — Reverse repo / Standing Deposit Facility rate
    """
    data = _query_records(request, "rbi_rates", series, from_date, to_date)
    return TimeSeriesResponse(
        series=series,
        from_date=str(from_date),
        to_date=str(to_date),
        granularity="daily",
        unit="percent",
        data=data,
    )
