#!/usr/bin/env python3
"""
Simple test script to check Google Sheets API connection
"""

import os
import sys
import json
from datetime import datetime

def test_service_account_file():
    """Test if service account file exists and is valid"""
    print("🔍 Testing service account setup...")

    if not os.path.exists('service-account-key.json'):
        print("❌ service-account-key.json not found")
        print("   Please follow GOOGLE_API_SETUP.md steps 1-3")
        return False

    try:
        with open('service-account-key.json', 'r') as f:
            credentials = json.load(f)

        required_fields = ['type', 'project_id', 'private_key', 'client_email']
        missing_fields = [field for field in required_fields if field not in credentials]

        if missing_fields:
            print(f"❌ Invalid service account file. Missing: {missing_fields}")
            return False

        print(f"✅ Service account file found")
        print(f"   Project: {credentials.get('project_id')}")
        print(f"   Email: {credentials.get('client_email')}")
        return True

    except Exception as e:
        print(f"❌ Error reading service account file: {e}")
        return False

def test_api_connection():
    """Test actual API connection"""
    print("\n🔗 Testing API connection...")

    try:
        # Import here to avoid module issues if run standalone
        from sheets_api import get_sheets_api

        sheets_api = get_sheets_api()
        if sheets_api.authenticate():
            print("✅ Google Sheets API authentication successful!")

            # Try to read data
            df = sheets_api.read_data()
            if not df.empty:
                print(f"✅ Successfully read {len(df)} expense records")
                print(f"   Date range: {df['date'].min().date()} to {df['date'].max().date()}")
                return True
            else:
                print("⚠️  API works but no data found (check sheet permissions)")
                return False
        else:
            print("❌ API authentication failed")
            return False

    except Exception as e:
        print(f"❌ API connection error: {e}")
        return False

def main():
    print("🧪 Expense Dashboard API Test")
    print("=" * 40)

    # Test service account file
    if not test_service_account_file():
        print("\n💡 Next steps:")
        print("1. Follow GOOGLE_API_SETUP.md to create service account")
        print("2. Download and place service-account-key.json in this folder")
        print("3. Run this test again")
        return

    # Test API connection
    if test_api_connection():
        print("\n🎉 All tests passed! Your expense tracker can now:")
        print("   ✅ Add new expenses")
        print("   ✅ Edit existing records")
        print("   ✅ Delete expenses")
        print("\n🚀 Run: streamlit run app.py")
    else:
        print("\n💡 Troubleshooting:")
        print("1. Ensure service account email is shared with your Google Sheet")
        print("2. Check that both Google Sheets API and Drive API are enabled")
        print("3. Verify sheet permissions (Editor access required)")

if __name__ == "__main__":
    main()