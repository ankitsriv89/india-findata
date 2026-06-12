"""
tests.test_analytics — unit tests for the correlation math (Phase 4).

The correlation endpoint's data-pull needs ClickHouse, but the maths is pure and
testable in isolation: `_pearson` and `_best_lag` take plain float lists.  These
tests pin the statistical behaviour without any network or DB.
"""

import math

from api.routes.analytics import _best_lag, _pearson

# ── Pearson r ─────────────────────────────────────────────────────────────────

def test_perfect_positive_correlation():
    xs = [1.0, 2.0, 3.0, 4.0, 5.0]
    ys = [2.0, 4.0, 6.0, 8.0, 10.0]  # y = 2x → r = +1
    r = _pearson(xs, ys)
    assert r is not None
    assert math.isclose(r, 1.0, abs_tol=1e-9)


def test_perfect_negative_correlation():
    xs = [1.0, 2.0, 3.0, 4.0, 5.0]
    ys = [10.0, 8.0, 6.0, 4.0, 2.0]  # y = -2x + c → r = -1
    r = _pearson(xs, ys)
    assert r is not None
    assert math.isclose(r, -1.0, abs_tol=1e-9)


def test_zero_variance_returns_none():
    """A flat series has no variance → correlation is undefined (None)."""
    xs = [3.0, 3.0, 3.0, 3.0]
    ys = [1.0, 2.0, 3.0, 4.0]
    assert _pearson(xs, ys) is None


def test_too_few_points_returns_none():
    assert _pearson([1.0], [2.0]) is None
    assert _pearson([], []) is None


def test_mismatched_lengths_returns_none():
    assert _pearson([1.0, 2.0, 3.0], [1.0, 2.0]) is None


def test_known_moderate_correlation():
    """A hand-checkable moderate-positive case stays in (0, 1)."""
    xs = [1.0, 2.0, 3.0, 4.0, 5.0]
    ys = [1.0, 3.0, 2.0, 5.0, 4.0]
    r = _pearson(xs, ys)
    assert r is not None
    assert 0.5 < r < 0.95


def test_pearson_clamped_to_unit_interval():
    """Result never escapes [-1, 1] even with float noise."""
    xs = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6]
    ys = [0.2, 0.4, 0.6, 0.8, 1.0, 1.2]
    r = _pearson(xs, ys)
    assert r is not None
    assert -1.0 <= r <= 1.0


# ── Best-lag scan ─────────────────────────────────────────────────────────────

def test_best_lag_detects_shift():
    """
    If B is A shifted forward by 2 steps, the best lag should recover a strong
    correlation at a non-zero lag (B leads/lags A).
    """
    a = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0]
    b = [0.0, 0.0, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0]  # ~A delayed by 2
    lag, r = _best_lag(a, b)
    assert r is not None
    assert abs(r) > 0.95
    assert lag != 0


def test_best_lag_zero_for_aligned_series():
    """Identical series correlate best at lag 0."""
    a = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0]
    lag, r = _best_lag(a, a)
    assert lag == 0
    assert r is not None
    assert math.isclose(r, 1.0, abs_tol=1e-9)
