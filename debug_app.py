#!/usr/bin/env python3
"""
Debug App for Streamlit Cloud
Deploy this temporarily to debug your Google Sheets authentication

To use:
1. Rename your current app.py to app_backup.py
2. Rename this file to app.py
3. Deploy to Streamlit Cloud
4. Run the debug and fix any issues
5. Switch back to your original app.py
"""

import streamlit as st

# Import the comprehensive debug script
try:
    from streamlit_debug import main as run_debug
    st.set_page_config(page_title="Google Sheets API Debug", page_icon="🔍")
    run_debug()
except ImportError:
    st.error("Could not import debug script. Make sure streamlit_debug.py is in the same directory.")
    st.stop()