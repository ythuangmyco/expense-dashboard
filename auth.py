"""
Authentication module for the expense dashboard
Simple PIN-based authentication for family use
"""

import streamlit as st
from datetime import datetime, timedelta
import base64
import json
from config import FAMILY_PIN, ALLOWED_USERS


def set_auth_cookie(user: str, remember_days: int = 30):
    """
    Set authentication cookie for remember me functionality
    """
    try:
        expiry_date = datetime.now() + timedelta(days=remember_days)
        auth_data = {
            "user": user,
            "expiry": expiry_date.isoformat(),
            "token": f"{user}_{FAMILY_PIN}_{expiry_date.strftime('%Y%m%d')}"
        }

        # Encode the auth data
        encoded_data = base64.b64encode(json.dumps(auth_data).encode()).decode()

        # Set cookie using Streamlit's HTML capability
        st.components.v1.html(f"""
        <script>
        document.cookie = "expense_auth={encoded_data}; path=/; max-age={remember_days * 24 * 60 * 60}; SameSite=Strict";
        </script>
        """, height=0)

        return True
    except Exception as e:
        st.error(f"設定記住我功能失敗: {str(e)}")
        return False


def get_auth_cookie():
    """
    Get authentication data from cookie
    """
    try:
        # Get cookie using JavaScript
        cookie_script = """
        <script>
        function getCookie(name) {
            let cookieValue = null;
            if (document.cookie && document.cookie !== '') {
                const cookies = document.cookie.split(';');
                for (let i = 0; i < cookies.length; i++) {
                    const cookie = cookies[i].trim();
                    if (cookie.substring(0, name.length + 1) === (name + '=')) {
                        cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
                        break;
                    }
                }
            }
            return cookieValue;
        }

        const authCookie = getCookie('expense_auth');
        if (authCookie) {
            window.parent.postMessage({type: 'AUTH_COOKIE', data: authCookie}, '*');
        }
        </script>
        """

        # For now, let's use a simpler approach with session state backup
        return st.session_state.get("auth_cookie_data", None)

    except Exception as e:
        return None


def clear_auth_cookie():
    """
    Clear authentication cookie
    """
    try:
        st.components.v1.html("""
        <script>
        document.cookie = "expense_auth=; path=/; expires=Thu, 01 Jan 1970 00:00:00 GMT";
        </script>
        """, height=0)

        # Also clear from session state
        if "auth_cookie_data" in st.session_state:
            del st.session_state["auth_cookie_data"]

        return True
    except:
        return False


def check_cookie_auth():
    """
    Check if user is authenticated via remember me cookie
    """
    try:
        # For simplicity, let's use session storage for now
        # In a production app, you'd want proper cookie handling

        remember_data = st.session_state.get("remember_me_data")
        if not remember_data:
            return None

        # Check if remember me period has expired
        expiry_str = remember_data.get("expiry")
        if expiry_str:
            expiry_date = datetime.fromisoformat(expiry_str)
            if datetime.now() > expiry_date:
                # Expired, clear the data
                del st.session_state["remember_me_data"]
                return None

        # Validate the user is still in allowed users
        user = remember_data.get("user")
        if user in ALLOWED_USERS:
            return user

        return None

    except Exception as e:
        return None


def check_password():
    """
    Enhanced authentication with persistent remember me functionality
    Returns True if authenticated, False otherwise

    Note: Authentication disabled for easier family access
    Set DISABLE_AUTH = False to enable family authentication
    """
    # Change this to False if you want to enable family authentication
    DISABLE_AUTH = False

    if DISABLE_AUTH:
        return True

    # First check if already authenticated in this session
    if st.session_state.get("password_correct", False):
        return True

    # Check for remember me authentication
    remembered_user = check_cookie_auth()
    if remembered_user:
        # Auto-authenticate from remember me
        st.session_state["password_correct"] = True
        st.session_state["current_user"] = remembered_user
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
            "記住我 (30天)",
            value=True,
            help="勾選後30天內不需重新登入"
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

                # Set remember me functionality
                if remember_me:
                    expiry_date = datetime.now() + timedelta(days=30)
                    remember_data = {
                        "user": selected_user,
                        "expiry": expiry_date.isoformat()
                    }
                    st.session_state["remember_me_data"] = remember_data

                    # Try to set cookie for browser persistence
                    set_auth_cookie(selected_user, 30)
                else:
                    # Clear any existing remember me data
                    if "remember_me_data" in st.session_state:
                        del st.session_state["remember_me_data"]

                st.success(f"✅ 登入成功！歡迎 {selected_user}")
                st.rerun()
            else:
                st.error("❌ 密碼錯誤，請重試")
                st.session_state["password_correct"] = False


def logout():
    """
    Logout function to clear authentication and user data
    """
    st.session_state["password_correct"] = False
    st.session_state["current_user"] = None

    # Clear remember me data
    if "remember_me_data" in st.session_state:
        del st.session_state["remember_me_data"]

    # Clear cookie
    clear_auth_cookie()

    st.rerun()


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
        remember_data = st.session_state.get("remember_me_data")

        with st.sidebar:
            st.success(f"🔓 已登入: {current_user}")

            if remember_data:
                expiry_str = remember_data.get("expiry")
                if expiry_str:
                    expiry_date = datetime.fromisoformat(expiry_str)
                    days_left = (expiry_date - datetime.now()).days
                    if days_left > 0:
                        st.caption(f"記住我: 還有 {days_left} 天")
                    else:
                        st.caption("記住我: 即將過期")

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
    if "remember_me_data" not in st.session_state:
        st.session_state["remember_me_data"] = None