"""
Unit tests for fx.py (plan §2.3 / §5 step 1). No network: ``requests.get`` is
monkeypatched with a router over the JSON fixtures. No Streamlit server is
needed (the store falls back to bare-mode caching).
"""

import json
import os
import sys
from datetime import date, datetime, timedelta
from decimal import Decimal

import pandas as pd
import pytest
import requests

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import fx  # noqa: E402
from config import FX_FALLBACK_DATE, FX_FALLBACK_RATES  # noqa: E402
from helpers import LOCAL_TZ  # noqa: E402

TODAY = date(2026, 9, 8)
NOW = datetime(2026, 9, 8, 10, 0, 0, tzinfo=LOCAL_TZ)


def _fixture(name):
    with open(os.path.join(HERE, "fixtures", name), encoding="utf-8") as fh:
        return json.load(fh)


class FakeResponse:
    def __init__(self, payload=None, status=200, text=None):
        self.status_code = status
        self._payload = payload
        self._text = text

    def json(self):
        if self._text is not None:
            return json.loads(self._text)  # raises on malformed
        return self._payload


class Router:
    """Route requests.get(url, ...) by URL substring; record calls."""

    # handler name -> URL substring it matches
    HOSTS = {"frankfurter": "api.frankfurter.dev", "erapi": "open.er-api.com",
             "jsdelivr": "cdn.jsdelivr.net", "pages": "currency-api.pages.dev"}

    def __init__(self, **handlers):
        # name -> callable(url, params) | FakeResponse | Exception
        self.handlers = {self.HOSTS[k]: v for k, v in handlers.items()}
        self.calls = []

    def __call__(self, url, params=None, timeout=None, **kw):
        self.calls.append((url, params, timeout))
        for key, handler in self.handlers.items():
            if key in url:
                if isinstance(handler, Exception):
                    raise handler
                if callable(handler):
                    return handler(url, params)
                return handler
        raise requests.ConnectionError(f"unrouted url {url}")

    def hosts(self):
        return [u.split("/")[2] for u, _, _ in self.calls]


ALL_OK = dict(
    frankfurter=FakeResponse(_fixture("frankfurter.json")),
    erapi=FakeResponse(_fixture("erapi.json")),
    jsdelivr=FakeResponse(_fixture("fawaz.json")),
    pages=FakeResponse(_fixture("fawaz.json")),
)


@pytest.fixture
def clock(monkeypatch):
    """Controllable wall clock for fx.now_local / fx.today_local."""
    state = {"now": NOW}

    def now_local():
        return state["now"]

    monkeypatch.setattr(fx, "now_local", now_local)
    monkeypatch.setattr(fx, "today_local", lambda: state["now"].date())

    def advance(**kw):
        state["now"] = state["now"] + timedelta(**kw)

    state["advance"] = advance
    return state


@pytest.fixture
def store(monkeypatch):
    """Fresh, isolated store per test (the real cache_resource one is tested separately)."""
    s = fx._new_store()
    monkeypatch.setattr(fx, "_fx_store", lambda: s)
    return s


@pytest.fixture
def router(monkeypatch):
    def install(**handlers):
        r = Router(**handlers)
        monkeypatch.setattr(fx.requests, "get", r)
        return r

    return install


# --------------------------------------------------------------------------- fetchers
def test_frankfurter_parses_real_shape(clock, router):
    r = router(**ALL_OK)
    q = fx._fetch_frankfurter("SGD", TODAY)
    assert q.rate == Decimal("24.908000") and q.as_of == date(2026, 9, 8)
    assert q.source == "frankfurter" and q.state == "live"
    url, params, timeout = r.calls[0]
    assert params == {"base": "SGD", "quotes": "TWD"} and timeout == fx.FX_TIMEOUT_S


def test_frankfurter_dated_lookup_adds_date_param(clock, router):
    r = router(frankfurter=FakeResponse([{"date": "2026-09-04", "base": "SGD", "quote": "TWD", "rate": 24.981}]))
    q = fx._fetch_frankfurter("SGD", date(2026, 9, 4))
    assert q.as_of == date(2026, 9, 4) and q.rate == Decimal("24.981000")
    assert r.calls[0][1]["date"] == "2026-09-04"


def test_erapi_parses_real_shape_and_flags_attribution(clock, router):
    router(**ALL_OK)
    q = fx._fetch_erapi("SGD", TODAY)
    assert q.rate == Decimal("24.912776") and q.source == "erapi" and q.needs_attribution
    assert q.as_of == date(2026, 9, 8)


def test_erapi_skipped_when_eol_or_not_today(clock, router):
    eol = dict(_fixture("erapi.json"), time_eol_unix=1800000000)
    r = router(erapi=FakeResponse(eol))
    assert fx._fetch_erapi("SGD", TODAY) is None
    assert fx._fetch_erapi("SGD", TODAY - timedelta(days=1)) is None
    assert len(r.calls) == 1  # the dated lookup never hit the network


def test_fawaz_cdn_then_pages_mirror(clock, router):
    r = router(jsdelivr=requests.Timeout("slow"), pages=FakeResponse(_fixture("fawaz.json")))
    q = fx._fetch_fawaz("SGD", TODAY)
    assert q.rate == Decimal("24.886722") and q.source == "fawaz_pages"
    assert r.hosts() == ["cdn.jsdelivr.net", "latest.currency-api.pages.dev"]
    assert "sgd.min.json" in r.calls[0][0]


def test_fawaz_dated_url(clock, router):
    r = router(jsdelivr=FakeResponse({"date": "2026-09-04", "sgd": {"twd": 24.9}}))
    q = fx._fetch_fawaz("SGD", date(2026, 9, 4))
    assert q.as_of == date(2026, 9, 4)
    assert "currency-api@2026-09-04/" in r.calls[0][0]


# --------------------------------------------------------------------------- chain
def test_chain_order_first_success_wins(clock, store, router):
    r = router(**ALL_OK)
    q = fx.get_quote("SGD", TODAY)
    assert q.source == "frankfurter" and q.state == "live"
    assert r.hosts() == ["api.frankfurter.dev"]


@pytest.mark.parametrize("failure", [
    requests.Timeout("timeout"),
    requests.ConnectionError("down"),
    FakeResponse(status=503),
    FakeResponse(text="<html>not json"),
    FakeResponse([{"date": "2026-09-08", "base": "SGD", "quote": "USD", "rate": 0.79}]),  # no TWD row
    FakeResponse({"status": 422, "message": "invalid currency"}),                        # wrong shape
])
def test_chain_falls_through_per_source(clock, store, router, failure):
    r = router(frankfurter=failure, erapi=ALL_OK["erapi"], jsdelivr=ALL_OK["jsdelivr"])
    q = fx.get_quote("SGD", TODAY)
    assert q.source == "erapi" and q.rate == Decimal("24.912776")
    assert r.hosts() == ["api.frankfurter.dev", "open.er-api.com"]


def test_chain_reaches_fawaz_after_frankfurter_and_erapi_fail(clock, store, router):
    r = router(frankfurter=FakeResponse(status=500),
               erapi=FakeResponse(dict(_fixture("erapi.json"), time_eol_unix=5)),
               jsdelivr=requests.Timeout("slow"), pages=ALL_OK["pages"])
    q = fx.get_quote("SGD", TODAY)
    assert q.source == "fawaz_pages"
    assert r.hosts() == ["api.frankfurter.dev", "open.er-api.com",
                         "cdn.jsdelivr.net", "latest.currency-api.pages.dev"]


def test_every_source_carries_timeout(clock, store, router):
    r = router(frankfurter=requests.Timeout(), erapi=requests.Timeout(),
               jsdelivr=requests.Timeout(), pages=requests.Timeout())
    fx.get_quote("SGD", TODAY)
    assert len(r.calls) == 4 and all(t == fx.FX_TIMEOUT_S for _, _, t in r.calls)


# --------------------------------------------------------------------------- caching
def test_cache_hit_within_ttl_no_network(clock, store, router):
    r = router(**ALL_OK)
    first = fx.get_quote("SGD", TODAY)
    clock["advance"](hours=11)
    second = fx.get_quote("SGD", TODAY)
    assert first.state == "live" and second.state == "cached"
    assert second.rate == first.rate and second.fetched_at == first.fetched_at
    assert len(r.calls) == 1


def test_cache_expires_after_ttl(clock, store, router):
    r = router(**ALL_OK)
    fx.get_quote("SGD", TODAY)
    clock["advance"](hours=12, seconds=1)
    q = fx.get_quote("SGD", TODAY)
    assert q.state == "live" and len(r.calls) == 2


def test_failed_chain_not_memoised_and_negative_cache(clock, store, router):
    down = router(frankfurter=requests.Timeout(), erapi=requests.Timeout(),
                  jsdelivr=requests.Timeout(), pages=requests.Timeout())
    q = fx.get_quote("SGD", TODAY)
    assert q.state == "static" and fx._key("SGD", TODAY) not in store["quotes"]
    assert len(down.calls) == 4

    # negative cache: within 10 minutes no retry, even though the network is back
    ok = router(**ALL_OK)
    clock["advance"](minutes=9)
    q2 = fx.get_quote("SGD", TODAY)
    assert q2.state == "static" and ok.calls == []

    # negative cache expired -> live quote (G9: the failure was never memoised)
    clock["advance"](minutes=1, seconds=1)
    q3 = fx.get_quote("SGD", TODAY)
    assert q3.state == "live" and q3.source == "frankfurter" and len(ok.calls) == 1
    assert fx._key("SGD", TODAY) not in store["neg"]


def test_stale_while_error_uses_last_good(clock, store, router):
    router(**ALL_OK)
    live = fx.get_quote("SGD", TODAY)
    # next day, everything down -> yesterday's quote marked stale
    clock["advance"](days=1)
    router(frankfurter=requests.Timeout(), erapi=requests.Timeout(),
           jsdelivr=requests.Timeout(), pages=requests.Timeout())
    q = fx.get_quote("SGD", TODAY + timedelta(days=1))
    assert q.state == "stale" and q.rate == live.rate and q.as_of == live.as_of
    assert q.source == "frankfurter"


def test_invalidate_evicts_one_key_only(clock, store, router):
    r = router(**ALL_OK)
    fx.get_quote("SGD", TODAY)
    fx.get_quote("SGD", TODAY - timedelta(days=1))
    assert len(store["quotes"]) == 2
    fx.invalidate("SGD", TODAY)
    assert fx._key("SGD", TODAY) not in store["quotes"]
    assert fx._key("SGD", TODAY - timedelta(days=1)) in store["quotes"]
    # refetch happens for the evicted key only
    n = len(r.calls)
    fx.get_quote("SGD", TODAY - timedelta(days=1))
    assert len(r.calls) == n
    fx.get_quote("SGD", TODAY)
    assert len(r.calls) == n + 1


def test_invalidate_clears_negative_cache(clock, store, router):
    router(frankfurter=requests.Timeout(), erapi=requests.Timeout(),
           jsdelivr=requests.Timeout(), pages=requests.Timeout())
    fx.get_quote("SGD", TODAY)
    assert fx._key("SGD", TODAY) in store["neg"]
    fx.invalidate("SGD", TODAY)
    ok = router(**ALL_OK)
    assert fx.get_quote("SGD", TODAY).state == "live" and len(ok.calls) == 1


def test_store_is_cache_resource_and_survives_cache_data_clear(monkeypatch):
    st = pytest.importorskip("streamlit")
    fx._fx_store.clear()
    s = fx._fx_store()
    s["quotes"]["marker"] = 1
    st.cache_data.clear()
    assert fx._fx_store() is s and s["quotes"]["marker"] == 1
    assert hasattr(fx._fx_store, "clear")  # cache_resource-decorated
    fx._fx_store.clear()
    assert "marker" not in fx._fx_store()["quotes"]


# --------------------------------------------------------------------------- tiers 4 & 5
def _df(rows):
    return pd.DataFrame(rows, columns=["date", "amount", "currency", "orig_amount", "fx_rate"])


def test_last_used_tier_from_df(clock, store, router):
    router(frankfurter=requests.Timeout(), erapi=requests.Timeout(),
           jsdelivr=requests.Timeout(), pages=requests.Timeout())
    df = _df([
        (pd.Timestamp("2026-09-05"), 316, "SGD", 12.5, 25.28),
        (pd.Timestamp("2026-09-07"), 480, "SGD", 19.0, 25.263158),  # most recent SGD row
        (pd.Timestamp("2026-09-08"), 1000, "MYR", 130, 7.69),
        (pd.Timestamp("2026-09-08"), 200, "", float("nan"), float("nan")),
    ])
    q = fx.get_quote("SGD", TODAY, df=df)
    assert q.state == "last_used" and q.source == "last_used"
    assert q.rate == Decimal("25.263158") and q.as_of == date(2026, 9, 7)
    assert "🔁 上次使用 09/07" in fx.freshness_caption(q)


def test_last_used_rate_tolerates_legacy_frames():
    assert fx.last_used_rate(None, "SGD") is None
    assert fx.last_used_rate(pd.DataFrame({"date": [], "amount": []}), "SGD") is None
    assert fx.last_used_rate(_df([]), "SGD") is None
    df = _df([(pd.Timestamp("2026-09-05"), 316, "sgd", "12.5", "25.28")])  # str cells, lower-case
    q = fx.last_used_rate(df, "SGD")
    assert q.rate == Decimal("25.280000")
    assert fx.last_used_rate(df, "JPY") is None


def test_static_tier_when_nothing_else(clock, store, router):
    router(frankfurter=requests.Timeout(), erapi=requests.Timeout(),
           jsdelivr=requests.Timeout(), pages=requests.Timeout())
    q = fx.get_quote("JPY", TODAY, df=_df([]))
    assert q.state == "static" and q.source == "static"
    assert q.rate == Decimal(str(FX_FALLBACK_RATES["JPY"])).quantize(Decimal("0.000001"))
    assert q.as_of == date.fromisoformat(FX_FALLBACK_DATE)
    assert fx.freshness_caption(q) == f"⚠️ 離線匯率 {FX_FALLBACK_DATE}，請確認"


def test_unknown_currency_without_data_returns_none(clock, store, router):
    router(frankfurter=requests.Timeout(), erapi=requests.Timeout(),
           jsdelivr=requests.Timeout(), pages=requests.Timeout())
    assert fx.get_quote("XXX", TODAY) is None
    assert "手動" in fx.freshness_caption(None)


def test_twd_never_hits_network(clock, store, router):
    r = router(**ALL_OK)
    q = fx.get_quote("TWD", TODAY)
    assert q.rate == Decimal("1.000000") and r.calls == [] and store["quotes"] == {}


# --------------------------------------------------------------------------- caption / effective rate
def test_freshness_caption_states(clock):
    base = fx.Quote("SGD", Decimal("24.908000"), TODAY, "frankfurter", "live", NOW)
    assert fx.freshness_caption(base) == "✅ 今日匯率 · Frankfurter 2026-09-08"
    cached = fx.Quote("SGD", Decimal("24.908000"), TODAY, "frankfurter", "cached", NOW)
    assert fx.freshness_caption(cached, now=NOW + timedelta(hours=2)) == "🕒 快取 2 小時前 · Frankfurter 2026-09-08"
    # a same-day quote fetched under an hour ago still reads as today's rate
    assert fx.freshness_caption(cached, now=NOW + timedelta(minutes=15)) == "✅ 今日匯率 · Frankfurter 2026-09-08"
    assert fx.freshness_caption(cached, now=NOW + timedelta(minutes=75)).startswith("🕒 快取 1 小時前")
    stale = fx.Quote("SGD", Decimal("24.908000"), TODAY, "fawaz_cdn", "stale", NOW)
    assert fx.freshness_caption(stale) == "⚠️ 無法更新，沿用 currency-api 2026-09-08"


def test_freshness_caption_erapi_attribution_link():
    q = fx.Quote("SGD", Decimal("24.912776"), TODAY, "erapi", "live", NOW)
    cap = fx.freshness_caption(q, now=NOW)
    assert "Rates By Exchange Rate API" in cap and "https://www.exchangerate-api.com" in cap
    assert cap.startswith("✅ 今日匯率 · Exchange Rate API 2026-09-08")
    # attribution follows the quote through cached/stale states too
    assert "Rates By Exchange Rate API" in fx.freshness_caption(fx.replace(q, state="stale"), now=NOW)
    # and never appears for other sources
    assert "Exchange Rate API" not in fx.freshness_caption(fx.replace(q, source="frankfurter"), now=NOW)


def test_effective_rate_with_card_fee():
    assert fx.effective_rate(24.908, False) == Decimal("24.908000")
    assert fx.effective_rate(24.908, True) == Decimal("25.281620")   # 24.908 × 1.015
    assert fx.effective_rate(Decimal("0.205065"), True) == Decimal("0.208141")  # half-up at 6 dp
    assert fx.effective_rate("24.908", True) == fx.effective_rate(24.908, True)


# --------------------------------------------------------------------------- date coercion (repair round 1)
ALL_DOWN = dict(frankfurter=requests.Timeout(), erapi=requests.Timeout(),
                jsdelivr=requests.Timeout(), pages=requests.Timeout())


@pytest.mark.parametrize("on_date", [
    pd.Timestamp("2026-09-06"),
    datetime(2026, 9, 6),
    datetime(2026, 9, 6, 15, 30, tzinfo=LOCAL_TZ),
    "2026-09-06",
])
def test_get_quote_accepts_datetime_like_and_falls_through(clock, store, router, on_date):
    """Regression: a Timestamp/datetime on_date used to TypeError in _fetch_fawaz
    (`on_date < today_local()` outside its try) and abort the whole chain."""
    router(**ALL_DOWN)
    q = fx.get_quote("SGD", on_date)           # must not raise
    assert q is not None and q.state == "static"
    # the key is the plain ISO date, so invalidate(ccy, date) can evict it
    assert fx._key("SGD", date(2026, 9, 6)) in store["neg"]
    assert fx._key("SGD", on_date) == ("SGD", "2026-09-06")


def test_get_quote_datetime_like_live_and_dated_urls(clock, store, router):
    r = router(**ALL_OK)
    q = fx.get_quote("SGD", pd.Timestamp("2026-09-06 09:00"))
    assert q.state == "live"
    # dated lookup: frankfurter received date=2026-09-06, not a timestamp string
    url, params, _ = r.calls[0]
    assert "frankfurter" in url and params["date"] == "2026-09-06"
    # cache key shared with the plain-date form -> second call is a cache hit
    n = len(r.calls)
    assert fx.get_quote("SGD", date(2026, 9, 6)).state == "cached"
    assert len(r.calls) == n


def test_fawaz_dated_tag_with_timestamp(clock, router):
    r = router(jsdelivr=FakeResponse(_fixture("fawaz.json")))
    q = fx._fetch_fawaz("SGD", pd.Timestamp("2026-09-06").date())
    assert q is not None
    assert "2026-09-06" in r.calls[0][0]


def test_fawaz_never_raises_on_bad_date_type(clock, router):
    """Fetcher contract: return None, never raise (comparison now inside the try)."""
    router(**ALL_OK)
    assert fx._fetch_fawaz("SGD", object()) is None


def test_invalidate_with_timestamp_evicts_plain_date_key(clock, store, router):
    router(**ALL_OK)
    fx.get_quote("SGD", TODAY)
    assert fx._key("SGD", TODAY) in store["quotes"]
    fx.invalidate("sgd", pd.Timestamp(TODAY))
    assert fx._key("SGD", TODAY) not in store["quotes"]


def test_as_date_none_and_nat_mean_today(clock):
    assert fx._as_date(None) == TODAY
    assert fx._as_date(pd.NaT) == TODAY
    assert fx._as_date("not-a-date") == TODAY
    assert fx._as_date(pd.Timestamp("2026-09-06 23:59")) == date(2026, 9, 6)


# --------------------------------------------------------------------------- fixtures are committable
FIXTURE_FILES = ("frankfurter.json", "erapi.json", "fawaz.json")


def test_fixture_files_present_and_parse():
    for name in FIXTURE_FILES:
        path = os.path.join(HERE, "fixtures", name)
        assert os.path.isfile(path), f"missing FX fixture {path}"
        assert _fixture(name)  # valid, non-empty JSON


def test_fixture_files_not_gitignored():
    """Regression: root .gitignore has ``*.json`` (service-account keys); the
    fixtures must be re-included (tests/fixtures/.gitignore) or a fresh clone
    aborts at collection with FileNotFoundError."""
    import shutil
    import subprocess

    repo = os.path.dirname(HERE)
    git = shutil.which("git")
    if git is None or not os.path.isdir(os.path.join(repo, ".git")):
        pytest.skip("git or .git not available")
    paths = [os.path.join("tests", "fixtures", n) for n in FIXTURE_FILES]
    # exit 0 = at least one path is ignored, 1 = none ignored
    proc = subprocess.run([git, "check-ignore", "-v", *paths], cwd=repo,
                          capture_output=True, text=True)
    ignored = [line for line in proc.stdout.splitlines()
               if line and not line.split("\t")[0].split(":")[-1].startswith("!")]
    assert not ignored, f"FX fixtures are git-ignored:\n{proc.stdout}"
