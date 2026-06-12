"""
api.routes.markets — query endpoints for the Markets layer (Phase 2).

Serves NSE/BSE equity prices, FII/DII flows, top movers, and a sector heatmap
from the same `records` table the macro layer uses.  Two endpoint shapes:

  1. Plain time-series (equity, fii) — reuse the macro `_query_records` helper
     and the shared TimeSeriesResponse envelope.
  2. Cross-sectional snapshots (movers, heatmap) — dedicated parameterised
     ClickHouse queries that compare close vs prev-day close for ONE date.
     These return purpose-built response models.

Error handling mirrors macro.py:
  404 — no data found for the requested parameters
  503 — ClickHouse query failed

All queries use FINAL (ReplacingMergeTree dedup) and parameter binding (never
string interpolation of user input) — same safety pattern as macro.py.
"""

from datetime import date

import structlog
from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

# Reuse the macro helpers so equity/fii share one query path + envelope.
from api.routes.macro import TimeSeriesResponse, _default_from, _query_records

log = structlog.get_logger()

router = APIRouter()


# ── Response models for the cross-sectional endpoints ─────────────────────────

class Mover(BaseModel):
    """One symbol's day move: close, previous close, and % change."""
    symbol: str
    close: float
    prev_close: float
    change_pct: float


class MoversResponse(BaseModel):
    """Top gainers and losers for an exchange on a given date."""
    exchange: str
    date: str
    gainers: list[Mover]
    losers: list[Mover]


class HeatmapCell(BaseModel):
    """One sector's average % change (for the D3 heatmap grid)."""
    sector: str
    change_pct: float
    symbols: int


class HeatmapResponse(BaseModel):
    """Sector → average %change grid for an exchange on a given date."""
    exchange: str
    date: str
    cells: list[HeatmapCell]


# ── Source name per exchange ──────────────────────────────────────────────────
# The bhavcopy sources write source="nse_bhavcopy" / "bse_bhavcopy".  Both also
# carry an "exchange" tag, but filtering by source is cheaper (it's the primary
# sort key) so we map the exchange query param to a source here.
_EXCHANGE_SOURCE = {
    "NSE": "nse_bhavcopy",
    "BSE": "bse_bhavcopy",
}


def _source_for_exchange(exchange: str) -> str:
    """Map an exchange code to its bhavcopy source, or 400 if unknown."""
    src = _EXCHANGE_SOURCE.get(exchange.upper())
    if src is None:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown exchange '{exchange}'. Use one of: {list(_EXCHANGE_SOURCE)}",
        )
    return src


# ── Time-series endpoints (reuse macro helper) ────────────────────────────────

@router.get("/equity", response_model=TimeSeriesResponse)
async def get_equity(
    request: Request,
    symbol: str = Query(description="Ticker symbol, e.g. TCS, RELIANCE"),
    exchange: str = Query(default="NSE", description="NSE | BSE"),
    dimension: str = Query(
        default="close_price",
        description="open_price | high_price | low_price | close_price | volume",
    ),
    from_date: date = Query(default_factory=_default_from, alias="from"),
    to_date: date = Query(default_factory=date.today, alias="to"),
) -> TimeSeriesResponse:
    """
    Daily price (or volume) series for one equity symbol.

    The bhavcopy sources store one Record per (symbol, dimension, day), so a
    single (source, series=symbol, dimension) filter yields the time series.
    Close price is the default dimension.
    """
    source = _source_for_exchange(exchange)
    # extra_where pins the dimension; _query_records selects date+value.
    data = _query_records(
        request,
        source=source,
        series=symbol,
        from_date=from_date,
        to_date=to_date,
        extra_where="AND dimension = {dimension:String}",
        extra_params={"dimension": dimension},
    )
    unit = "shares" if dimension == "volume" else "INR"
    return TimeSeriesResponse(
        series=symbol,
        from_date=str(from_date),
        to_date=str(to_date),
        granularity="daily",
        unit=unit,
        data=data,
    )


@router.get("/fii", response_model=TimeSeriesResponse)
async def get_fii(
    request: Request,
    series: str = Query(
        default="FII_NET_EQUITY",
        description="FII_NET_EQUITY | DII_NET_EQUITY",
    ),
    from_date: date = Query(default_factory=_default_from, alias="from"),
    to_date: date = Query(default_factory=date.today, alias="to"),
) -> TimeSeriesResponse:
    """
    Daily FII/DII net equity flow (crore INR; negative = net selling).

    Two series available — FII (foreign) and DII (domestic) institutional net
    equity purchases.  The dashboard overlays these as bars against an index.
    """
    data = _query_records(
        request,
        source="fii_dii",
        series=series,
        from_date=from_date,
        to_date=to_date,
    )
    return TimeSeriesResponse(
        series=series,
        from_date=str(from_date),
        to_date=str(to_date),
        granularity="daily",
        unit="crore_INR",
        data=data,
    )


# ── Cross-sectional endpoints (dedicated queries) ─────────────────────────────

# Compute each symbol's % change as (today_close - prev_close)/prev_close*100.
# "prev_close" is the most recent close STRICTLY BEFORE the requested date for
# the same symbol.  We do this in ClickHouse with a self-join on close_price.
_MOVERS_QUERY = """
WITH
    today AS (
        SELECT series AS symbol, value AS close
        FROM records FINAL
        WHERE source = {source:String}
          AND dimension = 'close_price'
          AND date = {date:Date}
    ),
    prev AS (
        SELECT series AS symbol, argMax(value, date) AS prev_close
        FROM records FINAL
        WHERE source = {source:String}
          AND dimension = 'close_price'
          AND date < {date:Date}
          AND date >= {date:Date} - INTERVAL 14 DAY
        GROUP BY series
    )
SELECT
    today.symbol AS symbol,
    today.close AS close,
    prev.prev_close AS prev_close,
    (today.close - prev.prev_close) / prev.prev_close * 100 AS change_pct
FROM today
INNER JOIN prev ON today.symbol = prev.symbol
WHERE prev.prev_close > 0
ORDER BY change_pct DESC
"""


@router.get("/movers", response_model=MoversResponse)
async def get_movers(
    request: Request,
    date_param: date = Query(alias="date", description="Trading date (YYYY-MM-DD)"),
    exchange: str = Query(default="NSE", description="NSE | BSE"),
    n: int = Query(default=10, ge=1, le=50, description="Number of gainers/losers"),
) -> MoversResponse:
    """
    Top N gainers and losers for an exchange on a given trading date.

    % change is computed against each symbol's previous available close (within
    a 14-day lookback so a holiday gap doesn't drop the symbol).  The single
    sorted query is split client-side here into the top-N and bottom-N.
    """
    source = _source_for_exchange(exchange)
    ch = request.app.state.ch_client

    try:
        result = ch.query(
            _MOVERS_QUERY,
            parameters={"source": source, "date": date_param.isoformat()},
        )
    except Exception as exc:
        log.error("markets.movers_failed", exchange=exchange, error=str(exc))
        raise HTTPException(status_code=503, detail=f"ClickHouse query failed: {exc}") from exc

    rows = result.result_rows
    if not rows:
        raise HTTPException(
            status_code=404,
            detail=f"No movers data: exchange={exchange} date={date_param}",
        )

    movers = [
        Mover(
            symbol=r[0],
            close=round(r[1], 2),
            prev_close=round(r[2], 2),
            change_pct=round(r[3], 2),
        )
        for r in rows
    ]
    # rows are sorted change_pct DESC: head = gainers, tail = losers.
    gainers = movers[:n]
    losers = list(reversed(movers[-n:])) if len(movers) >= n else list(reversed(movers))

    return MoversResponse(
        exchange=exchange.upper(),
        date=str(date_param),
        gainers=gainers,
        losers=losers,
    )


# Sector lives in the `region` tag as "sector:<NAME>" (matching the Record
# schema convention).  Symbols without a sector tag fall into "UNCLASSIFIED".
# We average each symbol's day %change within its sector.
_HEATMAP_QUERY = """
WITH
    today AS (
        SELECT series AS symbol,
               value AS close,
               if(startsWith(region, 'sector:'), substring(region, 8), 'UNCLASSIFIED') AS sector
        FROM records FINAL
        WHERE source = {source:String}
          AND dimension = 'close_price'
          AND date = {date:Date}
    ),
    prev AS (
        SELECT series AS symbol, argMax(value, date) AS prev_close
        FROM records FINAL
        WHERE source = {source:String}
          AND dimension = 'close_price'
          AND date < {date:Date}
          AND date >= {date:Date} - INTERVAL 14 DAY
        GROUP BY series
    )
SELECT
    today.sector AS sector,
    avg((today.close - prev.prev_close) / prev.prev_close * 100) AS change_pct,
    count() AS symbols
FROM today
INNER JOIN prev ON today.symbol = prev.symbol
WHERE prev.prev_close > 0
GROUP BY today.sector
ORDER BY change_pct DESC
"""


@router.get("/heatmap", response_model=HeatmapResponse)
async def get_heatmap(
    request: Request,
    date_param: date = Query(alias="date", description="Trading date (YYYY-MM-DD)"),
    exchange: str = Query(default="NSE", description="NSE | BSE"),
) -> HeatmapResponse:
    """
    Sector-level average % change for an exchange on a given date.

    Feeds the D3 heatmap: one cell per sector, coloured by average daily move.
    Sector comes from the Record `region` tag ("sector:<NAME>"); symbols with
    no sector tag are grouped under UNCLASSIFIED.
    """
    source = _source_for_exchange(exchange)
    ch = request.app.state.ch_client

    try:
        result = ch.query(
            _HEATMAP_QUERY,
            parameters={"source": source, "date": date_param.isoformat()},
        )
    except Exception as exc:
        log.error("markets.heatmap_failed", exchange=exchange, error=str(exc))
        raise HTTPException(status_code=503, detail=f"ClickHouse query failed: {exc}") from exc

    rows = result.result_rows
    if not rows:
        raise HTTPException(
            status_code=404,
            detail=f"No heatmap data: exchange={exchange} date={date_param}",
        )

    cells = [
        HeatmapCell(sector=r[0], change_pct=round(r[1], 2), symbols=int(r[2]))
        for r in rows
    ]
    return HeatmapResponse(exchange=exchange.upper(), date=str(date_param), cells=cells)
