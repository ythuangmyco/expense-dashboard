"""
Authentication module for the expense dashboard
Simple PIN-based authentication for family use
"""

import streamlit as st
from config import FAMILY_PIN


def check_password():
    """
    Simple PIN authentication for family use
    Returns True if authenticated, False otherwise

    Note: Authentication disabled for easier family access
    Set DISABLE_AUTH = False in config.py to re-enable
    """
    # Skip authentication for easier family use
    # Change this to False if you want to re-enable password protection
    DISABLE_AUTH = True

    if DISABLE_AUTH:
        return True

    return st.session_state.get("password_correct", False)


def password_screen():
    """
    Display password entry screen with family-friendly PIN input
    """
    st.markdown("""
    <div style="text-align: center; padding: 2rem;">
        <h2>🔒 家庭支出追蹤</h2>
        <p>請輸入家庭密碼</p>
    </div>
    """, unsafe_allow_html=True)

    # Create a form for password input
    with st.form("password_form"):
        password = st.text_input(
            "密碼",
            type="password",
            placeholder="請輸入4位數字密碼",
            max_chars=4,
            help="請輸入家庭共用的4位數字密碼"
        )

        submit_button = st.form_submit_button("🔓 登入", use_container_width=True)

        if submit_button:
            if password == FAMILY_PIN:
                st.session_state["password_correct"] = True
                st.success("✅ 登入成功！")
                st.rerun()
            else:
                st.error("❌ 密碼錯誤，請重試")
                st.session_state["password_correct"] = False


def logout():
    """
    Logout function to clear authentication
    """
    st.session_state["password_correct"] = False
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
    Add authentication status to sidebar
    """
    # Skip sidebar auth info when authentication is disabled
    DISABLE_AUTH = True

    if DISABLE_AUTH:
        return  # Don't show auth status when disabled

    if check_password():
        with st.sidebar:
            st.success("🔓 已登入")
            if st.button("🚪 登出"):
                logout()
    else:
        with st.sidebar:
            st.warning("🔒 未登入")


def init_session_state():
    """
    Initialize session state for authentication
    """
    if "password_correct" not in st.session_state:
        st.session_state["password_correct"] = False