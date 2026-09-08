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

    # All three tabs rendered. 總覽 has no st.title since the §3 redesign: the
    # period control and hero metric carry the heading instead.
    assert [t.label for t in at.tabs] == ["➕ 新增", "✏️ 編輯", "📊 總覽"]
    assert [t.value for t in at.title] == ["➕ 新增支出", "✏️ 編輯支出"]
    assert at.metric, "總覽 hero metric missing"

    # Stub API is the one the page saw (writable, not the CSV fallback). Since the
    # §3 redesign a healthy connection is a sidebar dot, not a full-width banner.
    assert "🟢 Google Sheets API 連線正常" in [c.value for c in at.sidebar.caption]
    assert not [w.value for w in at.warning if "唯讀" in w.value]

    # Auth patched, not bypassed: sidebar shows the stub user.
    assert "🔓 已登入: 菇菇" in [s.value for s in at.sidebar.success]

    # Dashboard rendered the hero metric from the fixture df. Its label names the
    # period and span ('本月支出 · 09/01–09/09') since the §3 redesign.
    assert any("支出 · " in m.label for m in at.metric), [m.label for m in at.metric]

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
