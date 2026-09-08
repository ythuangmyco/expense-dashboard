"""
Foreign-exchange quotes for the 外幣換算 card (PLAN_fx_and_overview.md §2.3).

Rate chain, first success wins (each HTTP call times out after FX_TIMEOUT_S):
  1. Frankfurter v2      GET /v2/rates?base={CCY}&quotes=TWD[&date=YYYY-MM-DD]
  2. open.er-api         GET /v6/latest/{CCY} -> rates.TWD   (today only,
                         skipped when time_eol_unix != 0, attribution required)
  3. fawazahmed0         cdn.jsdelivr.net then currency-api.pages.dev mirror
  4. 上次使用             most recent row of the loaded df with that currency
  5. config.FX_FALLBACK_RATES (static, dated FX_FALLBACK_DATE)

Caching lives in ONE holder object under ``st.cache_resource`` so the many
``st.cache_data.clear()`` sites never flush it. A failed chain is never
memoised as a quote; it only arms a 10-minute negative cache.

Streamlit is optional: when it cannot be imported (plain pytest, scripts) the
store is a module-level dict with identical semantics.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Optional

import requests

from config import (
    CARD_FX_FEE,
    FX_ENDPOINTS,
    FX_FALLBACK_DATE,
    FX_FALLBACK_RATES,
    FX_NEG_CACHE_MIN,
    FX_TIMEOUT_S,
    FX_TTL_H,
)
from helpers import LOCAL_TZ, now_local, q6, today_local

logger = logging.getLogger(__name__)

STATES = ("live", "cached", "stale", "last_used", "static")

# Mandatory attribution when open.er-api supplied the rate
ERAPI_ATTRIBUTION_URL = "https://www.exchangerate-api.com"
ERAPI_ATTRIBUTION_MD = f"[Rates By Exchange Rate API]({ERAPI_ATTRIBUTION_URL})"

SOURCE_LABEL = {
    "frankfurter": "Frankfurter",
    "erapi": "Exchange Rate API",
    "fawaz_cdn": "currency-api",
    "fawaz_pages": "currency-api",
    "last_used": "上次使用",
    "static": "離線匯率",
    "identity": "TWD",
}


@dataclass(frozen=True)
class Quote:
    currency: str
    rate: Decimal            # TWD per 1 unit, 6 dp
    as_of: date              # the date the rate is for
    source: str              # key of SOURCE_LABEL
    state: str               # one of STATES
    fetched_at: datetime     # tz-aware, helpers.now_local()

    @property
    def needs_attribution(self) -> bool:
        return self.source == "erapi"


# ---------------------------------------------------------------------------
# Store (st.cache_resource when a Streamlit runtime/module exists)
# ---------------------------------------------------------------------------
def _new_store() -> dict:
    return {"quotes": {}, "last_good": {}, "neg": {}}


try:  # Streamlit is a soft dependency here (tests / scripts run bare)
    import streamlit as _st

    @_st.cache_resource(show_spinner=False)
    def _fx_store() -> dict:
        """ONE holder object; never memoises a None (see plan §2.3)."""
        return _new_store()

except Exception:  # pragma: no cover - exercised only without streamlit
    _BARE_STORE = _new_store()

    def _fx_store() -> dict:  # type: ignore[misc]
        return _BARE_STORE


def _as_date(on_date) -> date:
    """
    Normalise the ``on_date`` argument of the public API to a plain ``date``.

    Callers hand over whatever the row carries: a ``date`` (form widget), a
    ``datetime`` / ``pandas.Timestamp`` (the loaded df's 日期 column, whose
    Timestamp is a ``datetime`` subclass), an ISO string, or None/NaT. All of
    them must map to the same cache key and compare cleanly with
    ``today_local()``; anything unusable falls back to today.
    """
    if on_date is None:
        return today_local()
    if isinstance(on_date, datetime):          # datetime, pd.Timestamp, pd.NaT
        try:
            d = on_date.date()
        except Exception:
            return today_local()
        # pd.NaT.date() returns NaT again (NaT != NaT) -> treat as missing
        if type(d) is date and d == d:
            return d
        return today_local()
    if isinstance(on_date, date):
        return on_date
    if isinstance(on_date, str):
        try:
            return date.fromisoformat(on_date.strip()[:10])
        except Exception:
            return today_local()
    to_date = getattr(on_date, "date", None)   # numpy.datetime64 wrappers etc.
    if callable(to_date):
        try:
            return _as_date(to_date())
        except Exception:
            return today_local()
    return today_local()


def _key(currency: str, on_date) -> tuple:
    return (currency.upper(), _as_date(on_date).isoformat())


# ---------------------------------------------------------------------------
# Fetchers: return a Quote (state="live") or None; never raise
# ---------------------------------------------------------------------------
def _get_json(url: str, params: Optional[dict] = None):
    resp = requests.get(url, params=params, timeout=FX_TIMEOUT_S)
    if resp.status_code != 200:
        raise ValueError(f"HTTP {resp.status_code} from {url}")
    return resp.json()


def _rate_from(value) -> Decimal:
    rate = q6(value)
    if rate <= 0:
        raise ValueError(f"non-positive rate {value!r}")
    return rate


def _fetch_frankfurter(currency: str, on_date: date) -> Optional[Quote]:
    """[{"date":"2026-09-08","base":"SGD","quote":"TWD","rate":24.908}]"""
    try:
        params = {"base": currency, "quotes": "TWD"}
        if on_date < today_local():
            params["date"] = on_date.isoformat()
        data = _get_json(FX_ENDPOINTS["frankfurter"], params)
        if not isinstance(data, list):
            raise ValueError("frankfurter: not a list")
        for row in data:
            if (isinstance(row, dict) and row.get("base") == currency
                    and row.get("quote") == "TWD"):
                return Quote(currency, _rate_from(row["rate"]),
                             date.fromisoformat(str(row["date"])),
                             "frankfurter", "live", now_local())
        raise ValueError("frankfurter: no TWD row")
    except Exception as exc:  # network, timeout, JSON, shape
        logger.info("frankfurter failed for %s: %s", currency, exc)
        return None


def _fetch_erapi(currency: str, on_date: date) -> Optional[Quote]:
    """{"result":"success","time_eol_unix":0,"time_last_update_unix":…,"rates":{"TWD":24.91,…}}"""
    if on_date != today_local():
        return None  # er-api serves only the latest day
    try:
        data = _get_json(FX_ENDPOINTS["erapi"].format(ccy=currency))
        if not isinstance(data, dict) or data.get("result") != "success":
            raise ValueError("erapi: result != success")
        if int(data.get("time_eol_unix", 1)) != 0:
            raise ValueError("erapi: endpoint reached end-of-life")
        rate = _rate_from(data["rates"]["TWD"])
        ts = data.get("time_last_update_unix")
        as_of = (datetime.fromtimestamp(int(ts), LOCAL_TZ).date()
                 if ts else today_local())
        return Quote(currency, rate, as_of, "erapi", "live", now_local())
    except Exception as exc:
        logger.info("erapi failed for %s: %s", currency, exc)
        return None


def _fetch_fawaz(currency: str, on_date: date) -> Optional[Quote]:
    """{"date":"2026-09-08","sgd":{"twd":24.8867,…}} — jsDelivr, then the pages.dev mirror."""
    ccy = currency.lower()
    for source in ("fawaz_cdn", "fawaz_pages"):
        try:
            tag = on_date.isoformat() if on_date < today_local() else "latest"
            data = _get_json(FX_ENDPOINTS[source].format(date=tag, ccy=ccy))
            if not isinstance(data, dict):
                raise ValueError("fawaz: not an object")
            rate = _rate_from(data[ccy]["twd"])
            as_of = date.fromisoformat(str(data.get("date") or on_date.isoformat()))
            return Quote(currency, rate, as_of, source, "live", now_local())
        except Exception as exc:
            logger.info("%s failed for %s: %s", source, currency, exc)
    return None


CHAIN = (_fetch_frankfurter, _fetch_erapi, _fetch_fawaz)


def _run_chain(currency: str, on_date: date) -> Optional[Quote]:
    for fetch in CHAIN:
        q = fetch(currency, on_date)
        if q is not None:
            return q
    return None


# ---------------------------------------------------------------------------
# Fallback tiers 4 and 5
# ---------------------------------------------------------------------------
def last_used_rate(df, currency: str) -> Optional[Quote]:
    """
    Tier 4 (上次使用): the most recent row of ``df`` whose 幣別 equals
    ``currency`` and carries a numeric 匯率. Tolerates a legacy frame without
    the FX columns (returns None). Never raises.
    """
    if df is None or currency is None:
        return None
    try:
        cols = set(df.columns)
        if not {"currency", "fx_rate"} <= cols or len(df) == 0:
            return None
        import pandas as pd  # local: helpers stay pandas-free

        code = currency.upper()
        rates = pd.to_numeric(df["fx_rate"], errors="coerce")
        mask = (df["currency"].astype(str).str.strip().str.upper() == code) & rates.notna() & (rates > 0)
        if not mask.any():
            return None
        sub = df.loc[mask]
        if "date" in cols:
            dates = pd.to_datetime(sub["date"], errors="coerce")
            order = dates.sort_values(ascending=False, kind="mergesort").index
            sub = sub.loc[order]
            dates = dates.loc[order]
            first = sub.index[0]
            as_of_ts = dates.loc[first]
            as_of = as_of_ts.date() if pd.notna(as_of_ts) else today_local()
        else:
            first = sub.index[-1]
            as_of = today_local()
        rate = q6(float(rates.loc[first]))
        return Quote(code, rate, as_of, "last_used", "last_used", now_local())
    except Exception as exc:
        logger.info("last_used_rate failed for %s: %s", currency, exc)
        return None


def static_rate(currency: str) -> Optional[Quote]:
    """Tier 5: config.FX_FALLBACK_RATES, stamped FX_FALLBACK_DATE."""
    code = (currency or "").upper()
    if code == "TWD":
        return Quote("TWD", Decimal("1.000000"), today_local(), "identity", "live", now_local())
    value = FX_FALLBACK_RATES.get(code)
    if value is None:
        return None
    return Quote(code, q6(value), date.fromisoformat(FX_FALLBACK_DATE),
                 "static", "static", now_local())


def _fallback(store: dict, currency: str, df) -> Optional[Quote]:
    good = store["last_good"].get(currency)
    if good is not None:
        return replace(good, state="stale")
    return last_used_rate(df, currency) or static_rate(currency)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def get_quote(currency: str, on_date=None, df=None) -> Optional[Quote]:
    """
    TWD-per-unit quote for ``currency`` on ``on_date`` (a ``date``, ``datetime``,
    ``pandas.Timestamp`` or ISO string; None/NaT mean today — see ``_as_date``).

    * cache hit (< FX_TTL_H old)            -> the stored quote, state "cached"
    * negative cache armed (< FX_NEG_CACHE_MIN) -> stale / last_used / static
    * otherwise run the chain; success is stored (state "live"); failure arms
      the negative cache and returns stale / last_used / static.
    Returns None only for an unknown currency with no data anywhere.
    """
    code = (currency or "").upper()
    if code in ("", "TWD"):
        return static_rate("TWD")
    on_date = _as_date(on_date)
    store = _fx_store()
    k = _key(code, on_date)
    now = now_local()

    q = store["quotes"].get(k)
    if q is not None and now - q.fetched_at < timedelta(hours=FX_TTL_H):
        return replace(q, state="cached")

    neg_at = store["neg"].get(k)
    if neg_at is not None and now - neg_at < timedelta(minutes=FX_NEG_CACHE_MIN):
        return _fallback(store, code, df)

    q = _run_chain(code, on_date)
    if q is not None:
        store["quotes"][k] = q
        store["last_good"][code] = q
        store["neg"].pop(k, None)
        return q

    store["neg"][k] = now
    return _fallback(store, code, df)


def invalidate(currency: str, on_date=None) -> None:
    """Evict one (currency, date) quote and its negative-cache mark (↻ button)."""
    store = _fx_store()
    k = _key((currency or "").upper(), _as_date(on_date))
    store["quotes"].pop(k, None)
    store["neg"].pop(k, None)


def effective_rate(quote_rate, fee_on: bool) -> Decimal:
    """Rate actually stored/used: mid-market × (1 + CARD_FX_FEE) when the 信用卡結匯 toggle is on, 6 dp."""
    rate = q6(quote_rate)
    if fee_on:
        rate = q6(rate * (Decimal(1) + CARD_FX_FEE))
    return rate


def _age_text(delta: timedelta) -> str:
    minutes = int(delta.total_seconds() // 60)
    if minutes < 1:
        return "剛剛"
    if minutes < 60:
        return f"{minutes} 分鐘前"
    return f"{minutes // 60} 小時前"


def freshness_caption(quote: Optional[Quote], now: Optional[datetime] = None) -> str:
    """
    One-line freshness statement for the FX card caption (Markdown).
      live      -> "✅ 今日匯率 · Frankfurter 2026-09-08"
      cached    -> "🕒 快取 2 小時前 · Frankfurter 2026-09-08"
      stale     -> "⚠️ 無法更新，沿用 Frankfurter 2026-09-07"
      last_used -> "🔁 上次使用 09/07"
      static    -> "⚠️ 離線匯率 2026-09-08，請確認"
    When open.er-api supplied the rate the mandatory attribution link
    「Rates By Exchange Rate API」 is appended.
    """
    if quote is None:
        return "❌ 無匯率資料，請手動輸入匯率"
    label = SOURCE_LABEL.get(quote.source, quote.source)
    iso = quote.as_of.isoformat()
    if quote.state == "live":
        today = (now or now_local()).date()
        # Frankfurter returns the previous business day on weekends/holidays,
        # and the edit form quotes the row's own date: say which day it is.
        text = f"✅ 今日匯率 · {label} {iso}" if quote.as_of == today else f"✅ {iso} 匯率 · {label}"
    elif quote.state == "cached":
        now = now or now_local()
        age = now - quote.fetched_at
        if quote.as_of == now.date() and age < timedelta(hours=1):
            # fetched moments ago on the same rerun cycle: still "today's rate"
            text = f"✅ 今日匯率 · {label} {iso}"
        else:
            text = f"🕒 快取 {_age_text(age)} · {label} {iso}"
    elif quote.state == "stale":
        text = f"⚠️ 無法更新，沿用 {label} {iso}"
    elif quote.state == "last_used":
        text = f"🔁 上次使用 {quote.as_of.strftime('%m/%d')}"
    elif quote.state == "static":
        text = f"⚠️ 離線匯率 {iso}，請確認"
    else:
        text = f"{label} {iso}"
    if quote.needs_attribution:
        text += f" · {ERAPI_ATTRIBUTION_MD}"
    return text
