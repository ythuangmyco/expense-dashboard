"""
Authentication module for the expense dashboard
Simple PIN-based authentication for family use
"""

import streamlit as st
from datetime import datetime, timedelta
import base64
import json
import hashlib
from config import FAMILY_PIN, ALLOWED_USERS


import os


def get_auth_file_path():
    """
    Get the path for the auth file
    """
    return os.path.join(os.path.expanduser("~"), ".streamlit_expense_auth.json")


def save_remember_me_auth(user: str, remember_days: int = 30):
    """
    Save authentication data to file for persistent remember me
    """
    try:
        expiry_date = datetime.now() + timedelta(days=remember_days)
        auth_data = {
            "user": user,
            "expiry": expiry_date.isoformat(),
            "created": datetime.now().isoformat()
        }

        auth_file = get_auth_file_path()
        with open(auth_file, 'w') as f:
            json.dump(auth_data, f)

        return True

    except Exception as e:
        st.warning(f"記住我功能保存失敗: {str(e)}")
        return False


def load_remember_me_auth():
    """
    Load authentication data from file
    """
    try:
        auth_file = get_auth_file_path()

        if not os.path.exists(auth_file):
            return None

        with open(auth_file, 'r') as f:
            auth_data = json.load(f)

        # Check if expired
        expiry_date = datetime.fromisoformat(auth_data["expiry"])
        if datetime.now() > expiry_date:
            # Expired, remove the file
            os.remove(auth_file)
            return None

        # Check if user is still allowed
        user = auth_data["user"]
        if user not in ALLOWED_USERS:
            os.remove(auth_file)
            return None

        return auth_data

    except Exception as e:
        # If there's any error reading the file, remove it
        try:
            auth_file = get_auth_file_path()
            if os.path.exists(auth_file):
                os.remove(auth_file)
        except:
            pass
        return None


def clear_remember_me_auth():
    """
    Clear the remember me authentication file
    """
    try:
        auth_file = get_auth_file_path()
        if os.path.exists(auth_file):
            os.remove(auth_file)
        return True
    except Exception as e:
        return False


def check_persistent_auth():
    """
    Check if user is authenticated via remember me file
    """
    try:
        auth_data = load_remember_me_auth()
        if auth_data:
            return auth_data["user"]
        return None

    except Exception as e:
        return None


def check_password():
    """
    Enhanced authentication with persistent file-based remember me functionality
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

    # Check for persistent remember me authentication
    remembered_user = check_persistent_auth()
    if remembered_user:
        # Auto-authenticate from remember me file
        st.session_state["password_correct"] = True
        st.session_state["current_user"] = remembered_user
        st.info(f"🔓 自動登入: 歡迎回來 {remembered_user}!")
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
                    success = save_remember_me_auth(selected_user, 30)
                    if success:
                        st.success(f"✅ 登入成功！已設定記住我功能 (30天)")
                    else:
                        st.success(f"✅ 登入成功！但記住我功能設定失敗")
                else:
                    # Clear any existing remember me data
                    clear_remember_me_auth()
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

    # Clear persistent remember me data
    clear_remember_me_auth()

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

        with st.sidebar:
            st.success(f"🔓 已登入: {current_user}")

            # Check for persistent remember me data
            auth_data = load_remember_me_auth()
            if auth_data:
                expiry_str = auth_data.get("expiry")
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