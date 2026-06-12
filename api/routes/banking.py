"""
api.routes.banking — query endpoints for the Banking & Credit layer (Phase 3).

Serves the RBI DBIE indicators (forex reserves, M3 broad money, bank credit
growth, gross NPA ratio) from the same `records` table as every other layer.
All four are plain time series, so each endpoint is a thin wrapper over the
shared macro `_query_records` helper + `TimeSeriesResponse` envelope.

Error handling mirrors macro.py / markets.py:
  404 — no data for the requested parameters
  503 — ClickHouse query failed

The source for all four is `rbi_dbie` (the Phase 3 RBIDBIESource); only the
series name and granularity/unit differ per endpoint.
"""

from datetime import date

from fastapi import APIRouter, Query, Request

from api.routes.macro import TimeSeriesResponse, _default_from, _query_records

router = APIRouter()


@router.get("/forex", response_model=TimeSeriesResponse)
async def get_forex(
    request: Request,
    from_date: date = Query(default_factory=_default_from, alias="from"),
    to_date: date = Query(default_factory=date.today, alias="to"),
) -> TimeSeriesResponse:
    """
    Foreign exchange reserves — weekly, USD billion.

    RBI publishes total reserves every Friday in the Weekly Statistical
    Supplement.  Reserves let the RBI intervene in currency markets to defend
    the rupee; large drawdowns often coincide with INR-defence episodes.
    """
    data = _query_records(request, "rbi_dbie", "FOREX_RESERVES", from_date, to_date)
    return TimeSeriesResponse(
        series="FOREX_RESERVES",
        from_date=str(from_date),
        to_date=str(to_date),
        granularity="weekly",
        unit="USD_billion",
        data=data,
    )


@router.get("/m3", response_model=TimeSeriesResponse)
async def get_m3(
    request: Request,
    from_date: date = Query(default_factory=_default_from, alias="from"),
    to_date: date = Query(default_factory=date.today, alias="to"),
) -> TimeSeriesResponse:
    """
    M3 broad money supply — monthly, crore INR.

    M3 = currency with the public + demand & time deposits + other deposits with
    the RBI.  Its growth rate is a key input to RBI monetary policy.
    """
    data = _query_records(request, "rbi_dbie", "M3_MONEY_SUPPLY", from_date, to_date)
    return TimeSeriesResponse(
        series="M3_MONEY_SUPPLY",
        from_date=str(from_date),
        to_date=str(to_date),
        granularity="monthly",
        unit="crore_INR",
        data=data,
    )


@router.get("/credit", response_model=TimeSeriesResponse)
async def get_credit(
    request: Request,
    from_date: date = Query(default_factory=_default_from, alias="from"),
    to_date: date = Query(default_factory=date.today, alias="to"),
) -> TimeSeriesResponse:
    """
    Bank credit growth — monthly, percent (YoY).

    Non-food bank credit growth gauges how fast banks are lending to the real
    economy.  The dashboard overlays this against GDP growth (useGDP) to show
    the credit–growth relationship.
    """
    data = _query_records(request, "rbi_dbie", "BANK_CREDIT_GROWTH", from_date, to_date)
    return TimeSeriesResponse(
        series="BANK_CREDIT_GROWTH",
        from_date=str(from_date),
        to_date=str(to_date),
        granularity="monthly",
        unit="percent",
        data=data,
    )


@router.get("/npa", response_model=TimeSeriesResponse)
async def get_npa(
    request: Request,
    from_date: date = Query(default_factory=_default_from, alias="from"),
    to_date: date = Query(default_factory=date.today, alias="to"),
) -> TimeSeriesResponse:
    """
    Gross NPA ratio (Scheduled Commercial Banks) — quarterly, percent.

    The gross non-performing-asset ratio is the headline bank-health metric:
    the share of loans that have stopped performing.  Sourced from the RBI's
    quarterly PDF report (parsed with pdfplumber).  Dates are quarter-starts
    (Indian fiscal: Q1 = Apr).
    """
    data = _query_records(request, "rbi_dbie", "GROSS_NPA_RATIO", from_date, to_date)
    return TimeSeriesResponse(
        series="GROSS_NPA_RATIO",
        from_date=str(from_date),
        to_date=str(to_date),
        granularity="quarterly",
        unit="percent",
        data=data,
    )
