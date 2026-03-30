"""
Debug Component for Google Sheets API Authentication
Can be imported and used within the main app for ongoing diagnostics
"""

import streamlit as st
import json
import gspread
from google.oauth2.service_account import Credentials
import traceback

def show_auth_debug(expanded=False):
    """Show authentication debug information in an expandable section"""

    with st.expander("🔍 Authentication Debug Info", expanded=expanded):
        st.write("**Quick Authentication Check**")

        # Check secrets availability
        if "google_sheets" not in st.secrets:
            st.error("❌ google_sheets secrets not found")
            return False

        credentials_dict = dict(st.secrets["google_sheets"])

        # Check critical fields
        critical_fields = ['client_email', 'private_key', 'project_id']
        missing_critical = []

        for field in critical_fields:
            if field not in credentials_dict or not credentials_dict[field]:
                missing_critical.append(field)

        if missing_critical:
            st.error(f"❌ Missing critical fields: {', '.join(missing_critical)}")
            return False

        # Show key info
        st.success("✅ Critical secrets present")
        st.write(f"**Service Account:** {credentials_dict.get('client_email', 'N/A')}")
        st.write(f"**Project ID:** {credentials_dict.get('project_id', 'N/A')}")

        # Test authentication
        try:
            scopes = [
                'https://www.googleapis.com/auth/spreadsheets',
                'https://www.googleapis.com/auth/drive'
            ]

            credentials = Credentials.from_service_account_info(
                credentials_dict, scopes=scopes
            )

            gc = gspread.authorize(credentials)
            sheet_id = "16JzKmS8Jq9H6NmjrpKkqBqNfnXkC_gfPiMV6Y6qP_kQ"
            sheet = gc.open_by_key(sheet_id)

            st.success(f"✅ Authentication successful - Connected to: {sheet.title}")
            return True

        except Exception as e:
            st.error(f"❌ Authentication failed: {str(e)}")

            # Show specific error hints
            error_str = str(e).lower()
            if "permission denied" in error_str or "insufficient permission" in error_str:
                st.warning("💡 **Hint:** Sheet not shared with service account or insufficient permissions")
            elif "not found" in error_str or "requested entity was not found" in error_str:
                st.warning("💡 **Hint:** Sheet ID might be incorrect or sheet was deleted")
            elif "invalid_grant" in error_str:
                st.warning("💡 **Hint:** Private key might be malformed or expired")
            elif "service account" in error_str:
                st.warning("💡 **Hint:** Service account configuration issue")

            return False

def show_detailed_secrets_info():
    """Show detailed information about all secrets (for troubleshooting)"""

    st.subheader("🔐 Detailed Secrets Information")

    if "google_sheets" not in st.secrets:
        st.error("No google_sheets section found in secrets")
        return

    credentials_dict = dict(st.secrets["google_sheets"])

    st.write("**All Secret Keys Present:**")
    for key in sorted(credentials_dict.keys()):
        value = credentials_dict[key]
        if key == 'private_key':
            # Show private key validation
            if isinstance(value, str):
                if value.startswith('-----BEGIN PRIVATE KEY-----') and value.endswith('-----END PRIVATE KEY-----'):
                    st.success(f"✅ {key}: Valid format ({len(value)} characters)")
                else:
                    st.error(f"❌ {key}: Invalid format")
            else:
                st.error(f"❌ {key}: Not a string")
        elif key == 'client_email':
            if '@' in str(value) and 'gserviceaccount.com' in str(value):
                st.success(f"✅ {key}: {value}")
            else:
                st.error(f"❌ {key}: Invalid service account email format")
        else:
            if value:
                st.success(f"✅ {key}: Present")
            else:
                st.error(f"❌ {key}: Empty or missing")

def test_sheet_connection():
    """Test the sheet connection and show detailed results"""

    st.subheader("🧪 Connection Test")

    if st.button("Test Connection Now"):
        with st.spinner("Testing connection..."):
            try:
                # Get credentials
                credentials_dict = dict(st.secrets["google_sheets"])
                scopes = [
                    'https://www.googleapis.com/auth/spreadsheets',
                    'https://www.googleapis.com/auth/drive'
                ]

                credentials = Credentials.from_service_account_info(
                    credentials_dict, scopes=scopes
                )

                # Test gspread
                gc = gspread.authorize(credentials)

                # Test sheet access
                sheet_id = "16JzKmS8Jq9H6NmjrpKkqBqNfnXkC_gfPiMV6Y6qP_kQ"
                sheet = gc.open_by_key(sheet_id)
                worksheet = sheet.get_worksheet(0)

                # Test data reading
                records = worksheet.get_all_records(head=1)  # Just get headers

                st.success("🎉 Full connection test successful!")
                st.info(f"Connected to sheet: '{sheet.title}' (Worksheet: '{worksheet.title}')")

            except Exception as e:
                st.error(f"Connection test failed: {str(e)}")

                # Show the full traceback in a code block for technical users
                with st.expander("View Full Error Details"):
                    st.code(traceback.format_exc())

def show_secrets_format_help():
    """Show the correct format for Streamlit Cloud secrets"""

    st.subheader("📋 Correct Secrets Format")
    st.write("Your Streamlit Cloud secrets should look exactly like this:")

    secrets_example = '''[google_sheets]
type = "service_account"
project_id = "your-project-id"
private_key_id = "your-private-key-id"
private_key = """-----BEGIN PRIVATE KEY-----
YOUR_PRIVATE_KEY_CONTENT_HERE
-----END PRIVATE KEY-----"""
client_email = "your-service-account@your-project.iam.gserviceaccount.com"
client_id = "your-client-id"
auth_uri = "https://accounts.google.com/o/oauth2/auth"
token_uri = "https://oauth2.googleapis.com/token"
auth_provider_x509_cert_url = "https://www.googleapis.com/oauth2/v1/certs"
client_x509_cert_url = "https://www.googleapis.com/robot/v1/metadata/x509/your-service-account%40your-project.iam.gserviceaccount.com"
universe_domain = "googleapis.com"'''

    st.code(secrets_example, language="toml")

    st.warning("⚠️ **Important Notes:**")
    st.write("1. Use triple quotes for the private_key field")
    st.write("2. Make sure there are no extra spaces or newlines")
    st.write("3. The client_email must match your service account")
    st.write("4. All fields are required")

def run_comprehensive_debug():
    """Run a comprehensive debug session"""

    st.title("🔍 Comprehensive Authentication Debug")

    tabs = st.tabs(["Quick Check", "Detailed Info", "Connection Test", "Format Help"])

    with tabs[0]:
        show_auth_debug(expanded=True)

    with tabs[1]:
        show_detailed_secrets_info()

    with tabs[2]:
        test_sheet_connection()

    with tabs[3]:
        show_secrets_format_help()

if __name__ == "__main__":
    # If run directly, show the comprehensive debug
    run_comprehensive_debug()