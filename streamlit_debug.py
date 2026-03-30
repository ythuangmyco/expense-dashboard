#!/usr/bin/env python3
"""
Streamlit Cloud Debug Script for Google Sheets API Authentication
Run this as your main Streamlit app to diagnose authentication issues
"""

import streamlit as st
import json
import gspread
from google.oauth2.service_account import Credentials
import pandas as pd
from datetime import datetime
import traceback

# Define the scope and sheet details
SCOPES = [
    'https://www.googleapis.com/auth/spreadsheets',
    'https://www.googleapis.com/auth/drive'
]

SHEET_ID = "16JzKmS8Jq9H6NmjrpKkqBqNfnXkC_gfPiMV6Y6qP_kQ"

def main():
    st.title("🔍 Google Sheets API Debug Tool")
    st.write("This tool will help diagnose authentication issues with Streamlit Cloud secrets")

    st.header("Step 1: Check Streamlit Secrets")

    # Check if secrets exist
    if not hasattr(st, 'secrets'):
        st.error("❌ st.secrets is not available!")
        st.stop()

    st.success("✅ st.secrets is available")

    # Check if google_sheets section exists
    if "google_sheets" not in st.secrets:
        st.error("❌ 'google_sheets' section not found in secrets!")
        st.write("**Available secret sections:**")
        try:
            sections = list(st.secrets.keys())
            if sections:
                for section in sections:
                    st.write(f"  - {section}")
            else:
                st.write("  No sections found")
        except Exception as e:
            st.write(f"  Error listing sections: {e}")
        st.stop()

    st.success("✅ 'google_sheets' section found in secrets")

    # Check required fields
    st.header("Step 2: Validate Required Fields")

    required_fields = [
        'type', 'project_id', 'private_key_id', 'private_key',
        'client_email', 'client_id', 'auth_uri', 'token_uri',
        'auth_provider_x509_cert_url', 'client_x509_cert_url', 'universe_domain'
    ]

    credentials_dict = dict(st.secrets["google_sheets"])

    st.write("**Field Validation Results:**")
    missing_fields = []
    empty_fields = []

    for field in required_fields:
        if field not in credentials_dict:
            missing_fields.append(field)
            st.error(f"❌ Missing field: {field}")
        elif not credentials_dict[field] or str(credentials_dict[field]).strip() == "":
            empty_fields.append(field)
            st.warning(f"⚠️ Empty field: {field}")
        else:
            if field == 'private_key':
                # Check private key format
                key_value = str(credentials_dict[field])
                if key_value.startswith('-----BEGIN PRIVATE KEY-----') and key_value.endswith('-----END PRIVATE KEY-----'):
                    st.success(f"✅ {field}: Valid format")
                else:
                    st.error(f"❌ {field}: Invalid format (should start with -----BEGIN PRIVATE KEY----- and end with -----END PRIVATE KEY-----)")
            elif field == 'client_email':
                # Check email format
                email = str(credentials_dict[field])
                if '@' in email and '.iam.gserviceaccount.com' in email:
                    st.success(f"✅ {field}: {email}")
                else:
                    st.warning(f"⚠️ {field}: {email} (doesn't look like a service account email)")
            elif field in ['project_id', 'client_id']:
                st.success(f"✅ {field}: {credentials_dict[field]}")
            else:
                st.success(f"✅ {field}: Present")

    if missing_fields:
        st.error(f"**Missing fields:** {', '.join(missing_fields)}")
        st.stop()

    if empty_fields:
        st.error(f"**Empty fields:** {', '.join(empty_fields)}")
        st.stop()

    # Show available fields (non-sensitive)
    st.header("Step 3: Secret Fields Overview")
    st.write("**Available fields in your secrets:**")
    for key in credentials_dict.keys():
        if key != 'private_key':  # Don't show private key value
            st.write(f"  - {key}: {credentials_dict[key]}")
        else:
            key_preview = str(credentials_dict[key])[:50] + "..." if len(str(credentials_dict[key])) > 50 else str(credentials_dict[key])
            st.write(f"  - {key}: {key_preview}")

    # Test credential creation
    st.header("Step 4: Test Credential Creation")

    try:
        st.write("🔐 Creating Google credentials...")
        credentials = Credentials.from_service_account_info(
            credentials_dict, scopes=SCOPES
        )
        st.success("✅ Credentials created successfully!")

        # Show some credential info
        st.write(f"**Service Account Email:** {credentials.service_account_email}")
        st.write(f"**Project ID:** {credentials.project_id}")
        st.write(f"**Scopes:** {', '.join(credentials.scopes)}")

    except Exception as e:
        st.error(f"❌ Failed to create credentials: {str(e)}")
        st.write("**Full error traceback:**")
        st.code(traceback.format_exc())
        st.stop()

    # Test gspread authorization
    st.header("Step 5: Test gspread Authorization")

    try:
        st.write("📋 Authorizing with gspread...")
        gc = gspread.authorize(credentials)
        st.success("✅ gspread authorization successful!")

    except Exception as e:
        st.error(f"❌ gspread authorization failed: {str(e)}")
        st.write("**Full error traceback:**")
        st.code(traceback.format_exc())
        st.stop()

    # Test sheet access
    st.header("Step 6: Test Sheet Access")

    try:
        st.write(f"📊 Attempting to open sheet: {SHEET_ID}")
        sheet = gc.open_by_key(SHEET_ID)
        st.success(f"✅ Sheet opened successfully: '{sheet.title}'")

        st.write("**Sheet Information:**")
        st.write(f"  - Title: {sheet.title}")
        st.write(f"  - ID: {sheet.id}")
        st.write(f"  - URL: {sheet.url}")

    except Exception as e:
        st.error(f"❌ Failed to open sheet: {str(e)}")
        st.write("**This usually means:**")
        st.write("1. The sheet is not shared with your service account email")
        st.write("2. The service account doesn't have proper permissions")
        st.write("3. The sheet ID is incorrect")
        st.write("4. The sheet has been deleted or moved")

        st.write("**Troubleshooting:**")
        st.write(f"1. Go to your Google Sheet: https://docs.google.com/spreadsheets/d/{SHEET_ID}")
        st.write(f"2. Click 'Share' and add this email as an Editor: {credentials.service_account_email}")
        st.write("3. Make sure the sheet ID in the URL matches the one in the code")

        st.write("**Full error traceback:**")
        st.code(traceback.format_exc())
        st.stop()

    # Test worksheet access
    st.header("Step 7: Test Worksheet Access")

    try:
        st.write("📄 Accessing first worksheet...")
        worksheet = sheet.get_worksheet(0)
        st.success(f"✅ Worksheet accessed: '{worksheet.title}'")

        st.write("**Worksheet Information:**")
        st.write(f"  - Title: {worksheet.title}")
        st.write(f"  - ID: {worksheet.id}")
        st.write(f"  - Row count: {worksheet.row_count}")
        st.write(f"  - Column count: {worksheet.col_count}")

    except Exception as e:
        st.error(f"❌ Failed to access worksheet: {str(e)}")
        st.write("**Full error traceback:**")
        st.code(traceback.format_exc())
        st.stop()

    # Test data reading
    st.header("Step 8: Test Data Reading")

    try:
        st.write("📖 Reading data from worksheet...")

        # First try to get headers
        headers = worksheet.row_values(1)
        st.success(f"✅ Headers read successfully: {len(headers)} columns")
        st.write("**Column headers:**")
        for i, header in enumerate(headers, 1):
            st.write(f"  {i}. {header}")

        # Try to get all records
        records = worksheet.get_all_records()
        st.success(f"✅ Data read successfully: {len(records)} records")

        if records:
            st.write("**Sample data (first record):**")
            sample_record = records[0]
            for key, value in sample_record.items():
                st.write(f"  - {key}: {value}")

            # Show as dataframe
            st.write("**Data as DataFrame:**")
            df = pd.DataFrame(records)
            st.dataframe(df.head())
        else:
            st.warning("⚠️ No data found in the sheet")

    except Exception as e:
        st.error(f"❌ Failed to read data: {str(e)}")
        st.write("**This might mean:**")
        st.write("1. The service account has read-only access (need Editor permissions)")
        st.write("2. The sheet structure is not as expected")
        st.write("3. There's a formatting issue with the data")

        st.write("**Full error traceback:**")
        st.code(traceback.format_exc())
        st.stop()

    # Final success message
    st.header("🎉 Success!")
    st.success("All authentication and access tests passed!")
    st.write("Your Google Sheets API integration is working correctly.")

    st.write("**Next Steps:**")
    st.write("1. Your secrets are properly configured")
    st.write("2. Your service account has the right permissions")
    st.write("3. You can now switch back to your main app.py")
    st.write("4. The authentication error should be resolved")

    # Show current timestamp
    st.write(f"**Debug completed at:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

if __name__ == "__main__":
    main()