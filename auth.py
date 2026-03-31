"""
Authentication module for the expense dashboard
Simple PIN-based authentication for family use
"""

import streamlit as st
from datetime import datetime, timedelta
from config import FAMILY_PIN, ALLOWED_USERS


def check_password():
    """
    Enhanced PIN authentication with user selection and remember me
    Returns True if authenticated, False otherwise

    Note: Authentication disabled for easier family access
    Set DISABLE_AUTH = False to enable family authentication
    """
    # Change this to False if you want to enable family authentication
    DISABLE_AUTH = True

    if DISABLE_AUTH:
        return True

    # Check if user is currently authenticated
    if not st.session_state.get("password_correct", False):
        return False

    # Check if remember me period has expired
    expiry_date = st.session_state.get("remember_me_expiry")
    if expiry_date and datetime.now() > expiry_date:
        # Remember me period expired, require re-login
        st.session_state["password_correct"] = False
        st.session_state["current_user"] = None
        st.session_state["remember_me_expiry"] = None
        return False

    return True


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
            placeholder="請輸入4位數字密碼",
            max_chars=4,
            help="請輸入家庭共用的4位數字密碼"
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

                # Set remember me expiry
                if remember_me:
                    expiry_date = datetime.now() + timedelta(days=30)
                    st.session_state["remember_me_expiry"] = expiry_date
                else:
                    st.session_state["remember_me_expiry"] = None

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
    st.session_state["remember_me_expiry"] = None
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
    DISABLE_AUTH = True

    if DISABLE_AUTH:
        return  # Don't show auth status when disabled

    if check_password():
        current_user = st.session_state.get("current_user", "用戶")
        expiry_date = st.session_state.get("remember_me_expiry")

        with st.sidebar:
            st.success(f"🔓 已登入: {current_user}")

            if expiry_date:
                days_left = (expiry_date - datetime.now()).days
                st.caption(f"記住我: 還有 {days_left} 天")

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
    if "remember_me_expiry" not in st.session_state:
        st.session_state["remember_me_expiry"] = None