"""
Plan §5 step 0 — AppTest smoke: ``app.main()`` renders end-to-end with stubs.

Stubs (all from conftest): fake SheetsAPI over the in-memory snapshot worksheet,
``auth.get_current_user`` patched, session pre-authenticated via session_state,
every ``requests`` call blocked. Regression for the review finding that no test
exercised ``streamlit.testing.v1.AppTest``.
"""

from conftest import make_fake_api, make_fake_ws


def _exceptions(at):
    return [str(e) for e in at.exception]


def test_apptest_smoke_renders_main(app_test, no_network):
    at = app_test()
    at.run()
    assert not at.exception, _exceptions(at)

    # All three tabs and their page titles rendered.
    assert [t.label for t in at.tabs] == ["➕ 新增", "✏️ 編輯", "📊 總覽"]
    assert [t.value for t in at.title] == ["➕ 新增支出", "✏️ 編輯支出", "📊 支出總覽"]

    # Stub API is the one the page saw (writable, not the CSV fallback).
    assert "🟢 Google Sheets API 連線正常 - 可新增/編輯支出" in [s.value for s in at.success]
    assert not [w.value for w in at.warning if "唯讀" in w.value]

    # Auth patched, not bypassed: sidebar shows the stub user.
    assert "🔓 已登入: 菇菇" in [s.value for s in at.sidebar.success]

    # Dashboard rendered metrics from the fixture df.
    assert "總支出" in [m.label for m in at.metric]

    # Nothing reached the network (Google Sheets or FX endpoints).
    assert no_network.calls == []


def test_apptest_unauthenticated_shows_password_screen(app_test):
    at = app_test(authed=False)
    at.run()
    assert not at.exception, _exceptions(at)
    assert [t.value for t in at.title] == []
    assert "用戶 👤" in [s.label for s in at.selectbox]
    assert "🔓 登入" in [b.label for b in at.button]


def test_apptest_uses_the_injected_api(app_test):
    """A custom stub (read-only) is what main() renders, proving the wiring."""
    api = make_fake_api(make_fake_ws())
    api.api_available = False
    api.read_only = True
    at = app_test(api=api)
    at.run()
    assert not at.exception, _exceptions(at)
    warnings = [w.value for w in at.warning]
    assert "🟡 唯讀模式 - 使用 CSV 資料" in warnings
    assert "📊 目前沒有支出資料" in warnings          # empty worksheet -> empty df, not a stale cache
