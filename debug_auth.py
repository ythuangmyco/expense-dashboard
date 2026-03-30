#!/usr/bin/env python3
"""
Detailed debugging for Google Sheets API authentication
"""

import json
import os
from google.oauth2.service_account import Credentials
import gspread

def debug_authentication():
    print("🔍 Detailed Authentication Debug")
    print("=" * 50)

    # Check service account file
    if not os.path.exists('service-account-key.json'):
        print("❌ service-account-key.json not found!")
        return False

    try:
        with open('service-account-key.json', 'r') as f:
            creds_dict = json.load(f)

        print(f"✅ Service Account Email: {creds_dict.get('client_email')}")
        print(f"✅ Project ID: {creds_dict.get('project_id')}")

        # Try to create credentials
        scopes = [
            'https://www.googleapis.com/auth/spreadsheets',
            'https://www.googleapis.com/auth/drive'
        ]

        print("\n🔐 Creating credentials...")
        credentials = Credentials.from_service_account_info(creds_dict, scopes=scopes)
        print("✅ Credentials created successfully")

        # Try to authorize gspread
        print("\n📋 Authorizing gspread...")
        gc = gspread.authorize(credentials)
        print("✅ gspread authorized")

        # Try to open the specific sheet
        sheet_id = "16JzKmS8Jq9H6NmjrpKkqBqNfnXkC_gfPiMV6Y6qP_kQ"
        print(f"\n📊 Trying to open sheet: {sheet_id}")

        try:
            sheet = gc.open_by_key(sheet_id)
            print(f"✅ Sheet opened: {sheet.title}")

            # Try to get worksheet
            worksheet = sheet.get_worksheet(0)
            print(f"✅ Worksheet accessed: {worksheet.title}")

            # Try to read some data
            try:
                records = worksheet.get_all_records()
                print(f"✅ Successfully read {len(records)} records from sheet")

                if records:
                    print("📄 First record fields:")
                    for key in list(records[0].keys())[:5]:  # Show first 5 fields
                        print(f"   - {key}")

                return True

            except Exception as e:
                print(f"❌ Error reading data: {e}")
                return False

        except Exception as e:
            print(f"❌ Error opening sheet: {e}")
            print("\n💡 This usually means:")
            print("   1. Sheet not shared with service account email")
            print("   2. Service account doesn't have proper permissions")
            print("   3. Sheet ID is incorrect")
            return False

    except Exception as e:
        print(f"❌ Error with credentials: {e}")
        return False

if __name__ == "__main__":
    debug_authentication()