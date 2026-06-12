"""
api.routes.analytics — cross-domain analytics (Phase 4).

This layer adds NO new pipeline source — it's pure query + compute over the data
Phases 1–3 already produce.  Two endpoints:

  GET /analytics/correlation — pull two series (each identified by source+series),
      align them by date, and compute the Pearson correlation coefficient plus a
      small best-lag scan.  Returns both aligned series so the frontend can draw a
      dual-axis chart without a second round-trip.

  GET /analytics/annotations — a small curated list of macro event dates (RBI
      policy moves, budgets, elections) for the chart annotation layer.

Pearson r is computed in pure Python (`statistics`/stdlib) — NO pandas, per
CLAUDE.md.  The maths is simple enough that pulling in a dependency would be
overkill and the explicit formula is more tutorial-friendly.
"""

import statistics
from datetime import date
from typing import Any

import structlog
from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

from api.routes.macro import _default_from

log = structlog.get_logger()

router = APIRouter()

# Maximum lag (in aligned-sample steps) to scan when looking for the lag that
# maximises |correlation|.  Kept small — this is an illustrative lead/lag probe,
# not a full cross-correlation analysis.
_MAX_LAG = 6


class CorrelationResponse(BaseModel):
    """
    Correlation between two series plus the aligned data for plotting.

    pearson_r is computed on the date-aligned overlap.  best_lag is the lag
    (in steps of series B relative to A) that maximises |r|; best_lag_r is the
    correlation at that lag.  n is the number of aligned points.
    """
    series_a: str
    series_b: str
    n: int
    pearson_r: float | None
    best_lag: int
    best_lag_r: float | None
    # Aligned rows: [{date, a, b}] for the dual-axis chart.
    data: list[dict[str, Any]]


class Annotation(BaseModel):
    """One dated macro event for the chart annotation layer."""
    date: str
    label: str
    category: str  # "monetary" | "fiscal" | "political"


# Curated, repo-local annotations.  Small and static on purpose — a richer feed
# would be its own pipeline source; for the explorer a hand-picked set of the
# events most likely to explain a kink in a macro series is enough.
_ANNOTATIONS: list[Annotation] = [
    Annotation(date="2016-11-08", label="Demonetisation", category="monetary"),
    Annotation(date="2017-07-01", label="GST rollout", category="fiscal"),
    Annotation(date="2019-05-23", label="2019 General Election result", category="political"),
    Annotation(date="2020-03-25", label="COVID-19 nationwide lockdown", category="political"),
    Annotation(date="2020-03-27", label="RBI emergency repo cut (−75bps)", category="monetary"),
    Annotation(date="2022-05-04", label="RBI off-cycle hike (tightening cycle begins)", category="monetary"),
    Annotation(date="2023-02-01", label="Union Budget 2023-24", category="fiscal"),
    Annotation(date="2024-06-04", label="2024 General Election result", category="political"),
    Annotation(date="2025-02-01", label="Union Budget 2025-26", category="fiscal"),
]


def _fetch_series(
    request: Request, source: str, series: str, from_date: date, to_date: date
) -> dict[str, float]:
    """
    Pull one series as a {date_iso: value} dict (deduplicated via FINAL).

    Unlike macro `_query_records` (which 404s on empty and returns a list), this
    returns a dict keyed by date so the caller can align two series by date with
    a simple key intersection.  Empty result → empty dict (caller decides what an
    empty overlap means).

    Raises:
        HTTPException 503 on ClickHouse failure.
    """
    ch = request.app.state.ch_client
    query = """
        SELECT date, value
        FROM records FINAL
        WHERE source = {source:String}
          AND series = {series:String}
          AND date BETWEEN {from_date:Date} AND {to_date:Date}
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
        log.error("analytics.query_failed", source=source, series=series, error=str(exc))
        raise HTTPException(status_code=503, detail=f"ClickHouse query failed: {exc}") from exc

    return {str(row[0]): float(row[1]) for row in result.result_rows}


def _pearson(xs: list[float], ys: list[float]) -> float | None:
    """
    Pearson correlation coefficient of two equal-length samples.

    Returns None when it's undefined: fewer than 2 points, or either series has
    zero variance (a flat line correlates with nothing).  Computed from the
    explicit covariance / (std_x * std_y) formula using stdlib `statistics`
    (no pandas/numpy).
    """
    n = len(xs)
    if n < 2 or len(ys) != n:
        return None
    try:
        sx = statistics.pstdev(xs)
        sy = statistics.pstdev(ys)
    except statistics.StatisticsError:
        return None
    if sx == 0 or sy == 0:
        return None

    mx = statistics.fmean(xs)
    my = statistics.fmean(ys)
    cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=True)) / n
    r = cov / (sx * sy)
    # Clamp tiny floating-point overshoots to [-1, 1].
    return max(-1.0, min(1.0, r))


def _best_lag(a: list[float], b: list[float]) -> tuple[int, float | None]:
    """
    Scan lags in [-_MAX_LAG, _MAX_LAG] for the one maximising |corr(a, b_lagged)|.

    A positive lag k correlates a[t] with b[t-k] (B leading A by k steps); a
    negative lag is the reverse.  Returns (best_lag, r_at_best_lag).  Falls back
    to (0, r_at_0) when no lagged window has enough overlap.
    """
    best_lag = 0
    best_r = _pearson(a, b)
    best_abs = abs(best_r) if best_r is not None else -1.0

    for lag in range(-_MAX_LAG, _MAX_LAG + 1):
        if lag == 0:
            continue
        if lag > 0:
            xa, xb = a[lag:], b[:-lag]
        else:
            xa, xb = a[:lag], b[-lag:]
        if len(xa) < 2:
            continue
        r = _pearson(xa, xb)
        if r is not None and abs(r) > best_abs:
            best_abs = abs(r)
            best_r = r
            best_lag = lag

    return best_lag, best_r


@router.get("/correlation", response_model=CorrelationResponse)
async def get_correlation(
    request: Request,
    series_a: str = Query(description="Series name for A, e.g. CPI_GENERAL"),
    source_a: str = Query(description="Source for A, e.g. mospi_cpi"),
    series_b: str = Query(description="Series name for B, e.g. REPO_RATE"),
    source_b: str = Query(description="Source for B, e.g. rbi_rates"),
    from_date: date = Query(default_factory=_default_from, alias="from"),
    to_date: date = Query(default_factory=date.today, alias="to"),
) -> CorrelationResponse:
    """
    Correlate two series and return both aligned for plotting.

    The two series are pulled independently, then aligned on the dates they
    share (inner join).  Pearson r is computed on that overlap, plus a best-lag
    scan to hint at lead/lag relationships (e.g. does credit growth lead GDP?).

    A 404 is returned only if a series has no data at all; an empty *overlap*
    (both have data but on disjoint dates — common when one is monthly and the
    other is on irregular event dates) returns n=0 and pearson_r=null rather than
    an error, so the UI can explain the mismatch.
    """
    a_map = _fetch_series(request, source_a, series_a, from_date, to_date)
    b_map = _fetch_series(request, source_b, series_b, from_date, to_date)

    if not a_map:
        raise HTTPException(status_code=404, detail=f"No data: {source_a}/{series_a}")
    if not b_map:
        raise HTTPException(status_code=404, detail=f"No data: {source_b}/{series_b}")

    # Inner-join on the dates both series share, ordered chronologically.
    common_dates = sorted(set(a_map) & set(b_map))
    a_vals = [a_map[d] for d in common_dates]
    b_vals = [b_map[d] for d in common_dates]

    pearson_r = _pearson(a_vals, b_vals)
    best_lag, best_lag_r = _best_lag(a_vals, b_vals)

    data = [
        {"date": d, "a": a_map[d], "b": b_map[d]} for d in common_dates
    ]

    return CorrelationResponse(
        series_a=series_a,
        series_b=series_b,
        n=len(common_dates),
        pearson_r=pearson_r,
        best_lag=best_lag,
        best_lag_r=best_lag_r,
        data=data,
    )


@router.get("/annotations", response_model=list[Annotation])
async def get_annotations() -> list[Annotation]:
    """
    Return the curated macro event annotations (RBI/budget/election dates).

    Static repo-local list — the chart overlays these as vertical reference
    lines so users can eyeball whether a kink in a series lines up with a known
    event.
    """
    return _ANNOTATIONS
