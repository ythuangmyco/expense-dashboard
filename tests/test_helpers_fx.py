"""Unit tests for the pure FX helpers in helpers.py (plan §4, §5 step 1)."""

import os
import sys
from datetime import date, datetime
from decimal import Decimal

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from helpers import fmt_orig, fmt_pct, fmt_twd, q6, to_twd, week_bounds  # noqa: E402


# --------------------------------------------------------------------------- to_twd
def test_to_twd_decimal_str_not_binary_float():
    # Decimal(12.5)*Decimal(23.4) == 292.4999… (binary float); str() path gives 292.5 -> 293
    assert to_twd(12.5, 23.4) == 293
    assert int((Decimal(12.5) * Decimal(23.4)).quantize(Decimal(1))) == 292  # the trap we avoid


def test_to_twd_jpy_krw_reconciliation_examples():
    assert to_twd(200000, 0.205065, 0) == 41013
    assert to_twd(500000, 0.02345, 0) == 11725


def test_to_twd_float_noise_inputs():
    # 0.1*3 style floats are cleaned by Decimal(str()) + quantize
    assert to_twd(0.1 * 3, 10) == 3
    assert to_twd("12.50", "23.4") == 293
    assert to_twd(Decimal("12.5"), Decimal("23.4")) == 293
    assert to_twd("1,234.5", 1) == 1235  # thousands separator tolerated


@pytest.mark.parametrize("orig,rate,expected", [
    (0.5, 1, 1),        # .5 -> up
    (1.5, 1, 2),        # not banker's rounding (ROUND_HALF_EVEN would give 2, 2, 4)
    (2.5, 1, 3),
    (10.5, 1, 11),
    (1, 0.5, 1),        # boundary produced by the rate side: 0.5 -> 1
    (3, 0.5, 2),        # 1.5 -> 2
    (7, 0.5, 4),        # 3.5 -> 4
    (0.49, 1, 0),       # just below
])
def test_to_twd_half_up_boundaries(orig, rate, expected):
    assert to_twd(orig, rate) == expected


def test_to_twd_quantizes_orig_to_orig_dp_first():
    assert to_twd(0.4999, 1) == 1              # 0.4999 -> 0.50 (2 dp) -> 1
    assert to_twd(0.4999, 1, orig_dp=4) == 0   # kept at 4 dp -> 0.4999 -> 0
    assert to_twd(12.4, 1, orig_dp=0) == 12    # JPY/KRW style: whole units
    with pytest.raises(ValueError):
        to_twd(1, 1, orig_dp=-1)


def test_to_twd_uses_rate_rounded_to_6dp():
    # 0.2050654999 -> 0.205065 (6 dp) before multiplying
    assert to_twd(200000, 0.2050654999, 0) == to_twd(200000, 0.205065, 0) == 41013
    # 0.2050655 -> 0.205066 half-up -> 41013.2 -> 41013
    assert to_twd(200000, 0.2050655, 0) == 41013


def test_to_twd_rejects_nan_and_none():
    with pytest.raises(ValueError):
        to_twd(None, 1)
    with pytest.raises(ValueError):
        to_twd(float("nan"), 1)
    with pytest.raises(ValueError):
        to_twd(1, "abc")


# --------------------------------------------------------------------------- q6
def test_q6_six_decimals_half_up():
    assert q6(0.2050655) == Decimal("0.205066")
    assert q6(0.2050654) == Decimal("0.205065")
    assert q6(24.908) == Decimal("24.908000")
    assert str(q6(Decimal("1"))) == "1.000000"


# --------------------------------------------------------------------------- formatters
def test_fmt_orig_uses_currency_decimals():
    assert fmt_orig("SGD", 12.5) == "SGD 12.50"
    assert fmt_orig("sgd", "12.5") == "SGD 12.50"
    assert fmt_orig("JPY", 200000) == "JPY 200,000"
    assert fmt_orig("KRW", 500000.4) == "KRW 500,000"
    assert fmt_orig("MYR", 1234.567) == "MYR 1,234.57"
    assert fmt_orig("XXX", 1) == "XXX 1.00"  # unknown currency -> 2 dp
    assert fmt_orig("SGD", None) == ""
    assert fmt_orig("SGD", float("nan")) == ""


def test_fmt_twd():
    assert fmt_twd(1234) == "NT$1,234"
    assert fmt_twd(1234.4) == "NT$1,234"
    assert fmt_twd(1234.5) == "NT$1,235"
    assert fmt_twd(-10090) == "-NT$10,090"
    assert fmt_twd(0) == "NT$0"
    assert fmt_twd(None) == "—"
    assert fmt_twd(float("nan")) == "—"


def test_fmt_pct():
    assert fmt_pct(-0.123) == "-12%"
    assert fmt_pct(0.05) == "+5%"
    assert fmt_pct(0) == "0%"
    assert fmt_pct(-0.001) == "0%"
    assert fmt_pct(0.1234, 1) == "+12.3%"
    assert fmt_pct(None) == "—"
    assert fmt_pct(float("nan")) == "—"


# --------------------------------------------------------------------------- week_bounds
def test_week_bounds_monday_to_sunday():
    assert week_bounds(date(2026, 9, 8)) == (date(2026, 9, 7), date(2026, 9, 13))  # Tuesday
    assert week_bounds(date(2026, 9, 7)) == (date(2026, 9, 7), date(2026, 9, 13))  # Monday
    assert week_bounds(date(2026, 9, 13)) == (date(2026, 9, 7), date(2026, 9, 13))  # Sunday
    assert week_bounds(datetime(2026, 9, 9, 15, 0)) == (date(2026, 9, 7), date(2026, 9, 13))
