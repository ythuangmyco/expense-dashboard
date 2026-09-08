"""
Authentication module for the expense dashboard
Simple PIN-based authentication for family use

"Remember me" is implemented as a per-browser signed cookie (expense_auth).
Cookie value = base64url(JSON {user, exp}) + "." + HMAC-SHA256 hex signature.
The cookie is read via st.context.cookies and written/cleared via a tiny JS
snippet (Streamlit has no server-side set-cookie API). Because
st.context.cookies is snapshotted when the browser session connects, the page
is reloaded right after the cookie is set/cleared so the new session sees it.
"""

import streamlit as st
import streamlit.components.v1 as components
from datetime import datetime
import base64
import hashlib
import hmac
import json
import logging
import time
from config import FAMILY_PIN, ALLOWED_USERS


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

COOKIE_NAME = "expense_auth"
REMEMBER_DAYS = 30
SESSION_ONLY_HOURS = 12  # validity of the session cookie when "記住我" is unticked


# ---------------------------------------------------------------------------
# Token helpers (pure functions, no Streamlit UI; unit-tested in
# tests_auth_token.py)
# ---------------------------------------------------------------------------

def _b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64url_decode(text: str) -> bytes:
    padding = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + padding)


_fallback_secret_warned = False


def get_cookie_secret() -> str:
    """
    Secret used to sign the auth cookie.
    Prefer the top-level st.secrets["AUTH_COOKIE_SECRET"]; also accept
    st.secrets["app"]["AUTH_COOKIE_SECRET"] (the natural place to append it
    in a secrets.toml that ends inside [app]). Fall back to a deterministic
    value derived from FAMILY_PIN so the app works without secrets.toml, and
    log a one-time warning when that fallback is used.
    """
    global _fallback_secret_warned
    try:
        secret = st.secrets.get("AUTH_COOKIE_SECRET")
        if not secret:
            app_section = st.secrets.get("app")
            if app_section is not None and hasattr(app_section, "get"):
                secret = app_section.get("AUTH_COOKIE_SECRET")
        if secret:
            return str(secret)
    except Exception:
        pass
    if not _fallback_secret_warned:
        _fallback_secret_warned = True
        logging.getLogger(__name__).warning(
            "AUTH_COOKIE_SECRET not set in st.secrets; deriving the cookie "
            "signing secret from FAMILY_PIN (cookies will be invalidated if "
            "FAMILY_PIN changes)."
        )
    return hashlib.sha256(("cookie-secret:" + FAMILY_PIN).encode()).hexdigest()


def _sign(payload_b64: str, secret: str) -> str:
    return hmac.new(secret.encode(), payload_b64.encode(), hashlib.sha256).hexdigest()


def make_auth_token(user: str, days: float = REMEMBER_DAYS, secret: str = None, now: int = None) -> str:
    """
    Build a signed token: base64url(JSON {user, exp}) + "." + HMAC-SHA256 hex
    """
    if secret is None:
        secret = get_cookie_secret()
    if now is None:
        now = int(time.time())
    exp = int(now + days * 86400)
    payload = json.dumps({"user": user, "exp": exp}, separators=(",", ":"), ensure_ascii=False)
    payload_b64 = _b64url_encode(payload.encode("utf-8"))
    return payload_b64 + "." + _sign(payload_b64, secret)


def verify_auth_token(token: str, secret: str = None, now: int = None):
    """
    Verify a token. Returns the payload dict {user, exp} if the signature is
    valid, the token is not expired and the user is allowed; otherwise None.
    """
    if not token or not isinstance(token, str) or "." not in token:
        return None
    if secret is None:
        secret = get_cookie_secret()
    if now is None:
        now = int(time.time())

    payload_b64, _, sig = token.rpartition(".")
    if not payload_b64 or not sig:
        return None

    expected = _sign(payload_b64, secret)
    try:
        if not hmac.compare_digest(expected.encode("ascii"), sig.encode("utf-8")):
            return None
    except Exception:
        return None

    try:
        payload = json.loads(_b64url_decode(payload_b64).decode("utf-8"))
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None

    user = payload.get("user")
    exp = payload.get("exp")
    if not isinstance(exp, int) or exp <= now:
        return None
    if user not in ALLOWED_USERS:
        return None

    return {"user": user, "exp": exp}


# ---------------------------------------------------------------------------
# Cookie I/O
# ---------------------------------------------------------------------------

def read_auth_cookie():
    """
    Read and verify the auth cookie from the current browser session.
    Returns payload dict or None.
    """
    try:
        token = st.context.cookies.get(COOKIE_NAME)
    except Exception:
        return None
    return verify_auth_token(token)


def _emit_cookie_js(value: str, max_age: int = None, reload: bool = True):
    """
    Inject JS that writes the cookie on the parent (app) document and (by
    default) reloads the page so the next Streamlit session sees the cookie
    via st.context.cookies.
    max_age=None -> session cookie (dies when browser closes);
    max_age=0    -> delete cookie.
    reload=False -> silently refresh the cookie for an already-authenticated
                    session (used for the rolling 30-day renewal).
    """
    max_age_part = "" if max_age is None else f"; Max-Age={int(max_age)}"
    reload_part = "window.parent.location.reload();" if reload else ""
    js = f"""
<script>
(function() {{
  try {{
    var doc = window.parent.document;
    var secure = (window.parent.location.protocol === "https:") ? "; Secure" : "";
    doc.cookie = "{COOKIE_NAME}={value}{max_age_part}; Path=/; SameSite=Lax" + secure;
  }} catch (e) {{
    console.error("expense_auth cookie error", e);
  }}
  {reload_part}
}})();
</script>
"""
    components.html(js, height=0)


def set_auth_cookie(user: str, remember: bool):
    """
    Emit JS that sets the auth cookie and reloads the page.
    Must only be called once, right after a successful PIN submit.
    """
    if remember:
        token = make_auth_token(user, days=REMEMBER_DAYS)
        _emit_cookie_js(token, max_age=REMEMBER_DAYS * 86400)
    else:
        token = make_auth_token(user, days=SESSION_ONLY_HOURS / 24)
        _emit_cookie_js(token, max_age=None)


def refresh_auth_cookie(user: str):
    """
    Re-issue a fresh 30-day cookie without reloading. Called once per session
    on cookie auto-login so the expiry rolls forward on every visit. This also
    keeps Safari/iOS users logged in: WebKit caps script-written cookies at
    7 days, so a visit at least weekly renews it.
    """
    token = make_auth_token(user, days=REMEMBER_DAYS)
    _emit_cookie_js(token, max_age=REMEMBER_DAYS * 86400, reload=False)
    return int(time.time() + REMEMBER_DAYS * 86400)


def clear_auth_cookie():
    """
    Emit JS that deletes the auth cookie and reloads the page.
    Must only be called on explicit logout.
    """
    _emit_cookie_js("", max_age=0)


# ---------------------------------------------------------------------------
# Public auth API (imported by app.py)
# ---------------------------------------------------------------------------

def check_password():
    """
    Returns True if authenticated (session_state, or a valid auth cookie),
    False otherwise.

    Note: Set DISABLE_AUTH = True to disable family authentication
    """
    DISABLE_AUTH = False

    if DISABLE_AUTH:
        return True

    # Already authenticated in this session
    if st.session_state.get("password_correct", False):
        return True

    # Try the signed cookie
    auth = read_auth_cookie()
    if auth:
        st.session_state["password_correct"] = True
        st.session_state["current_user"] = auth["user"]
        st.session_state["auth_exp"] = auth["exp"]
        if not st.session_state.get("auto_login_notified", False):
            st.session_state["auto_login_notified"] = True
            # Only "remember me" cookies (validity beyond the session-only
            # window) are rolled forward; session-only cookies stay as they are.
            if auth["exp"] - int(time.time()) > SESSION_ONLY_HOURS * 3600:
                st.session_state["auth_exp"] = refresh_auth_cookie(auth["user"])
            st.info(f"🔓 已登入: 歡迎 {auth['user']}!")
        return True

    return False


def password_screen():
    """
    Display password entry screen with family-friendly PIN input and user selection
    """
    st.markdown("""
    <div style="text-align: center; padding: 2rem;">
        <h2>🔒 家庭支出追蹤</h2>
        <p>請選擇用戶並輸入家庭密碼</p>
    </div>
    """, unsafe_allow_html=True)

    # Create a form for login
    with st.form("password_form"):
        # User selection
        selected_user = st.selectbox(
            "用戶 👤",
            options=["請選擇用戶..."] + ALLOWED_USERS,
            help="選擇你的用戶名稱"
        )

        password = st.text_input(
            "密碼",
            type="password",
            placeholder="請輸入家庭密碼",
            help="請輸入家庭共用密碼"
        )

        # Remember me checkbox
        remember_me = st.checkbox(
            f"記住我 ({REMEMBER_DAYS}天)",
            value=True,
            help=f"勾選後{REMEMBER_DAYS}天內不需重新登入 (僅限此瀏覽器，每次開啟自動續期；iPhone/Safari 需至少每 7 天開啟一次)"
        )

        submit_button = st.form_submit_button("🔓 登入", use_container_width=True)

        if submit_button:
            # Validate user selection
            if selected_user == "請選擇用戶...":
                st.error("❌ 請選擇用戶")
                return

            # Validate PIN
            if password == FAMILY_PIN:
                st.session_state["password_correct"] = True
                st.session_state["current_user"] = selected_user

                if remember_me:
                    st.success(f"✅ 登入成功！已設定記住我功能 ({REMEMBER_DAYS}天)，頁面重新載入中...")
                else:
                    st.success(f"✅ 登入成功！歡迎 {selected_user}，頁面重新載入中...")

                # Write cookie via JS and reload; the reloaded session picks the
                # cookie up in check_password(). Do NOT st.rerun() here — the
                # component must render for the JS to execute.
                set_auth_cookie(selected_user, remember_me)
                st.stop()
            else:
                st.error("❌ 密碼錯誤，請重試")
                st.session_state["password_correct"] = False


def logout():
    """
    Logout: clear session state, delete the auth cookie and reload the page
    """
    st.session_state["password_correct"] = False
    st.session_state["current_user"] = None
    st.session_state.pop("auth_exp", None)
    st.session_state.pop("auto_login_notified", None)

    # Emit clear-cookie JS + reload; stop so the component actually renders.
    clear_auth_cookie()
    st.stop()


def require_auth(func):
    """
    Decorator to require authentication for a function
    Usage: @require_auth
    """
    def wrapper(*args, **kwargs):
        if not check_password():
            password_screen()
            return None
        return func(*args, **kwargs)
    return wrapper


def auth_sidebar():
    """
    Add authentication status to sidebar with user info
    """
    # Skip sidebar auth info when authentication is disabled
    DISABLE_AUTH = False

    if DISABLE_AUTH:
        return  # Don't show auth status when disabled

    if check_password():
        current_user = st.session_state.get("current_user", "用戶")

        with st.sidebar:
            st.success(f"🔓 已登入: {current_user}")

            # Days left from the cookie expiry
            exp = st.session_state.get("auth_exp")
            if exp is None:
                auth = read_auth_cookie()
                if auth:
                    exp = auth["exp"]
                    st.session_state["auth_exp"] = exp
            if exp:
                days_left = (datetime.fromtimestamp(exp) - datetime.now()).days
                if days_left >= 1:
                    st.caption(f"記住我: 還有 {days_left} 天")
                else:
                    st.caption("記住我: 未啟用或即將過期")

            if st.button("🚪 登出"):
                logout()
    else:
        with st.sidebar:
            st.warning("🔒 未登入")


def get_current_user():
    """
    Get the currently logged in user
    Returns user name or None if not authenticated
    """
    if check_password():
        return st.session_state.get("current_user", None)
    return None


def init_session_state():
    """
    Initialize session state for enhanced authentication
    """
    if "password_correct" not in st.session_state:
        st.session_state["password_correct"] = False
    if "current_user" not in st.session_state:
        st.session_state["current_user"] = None
