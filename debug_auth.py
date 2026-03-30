#!/usr/bin/env python3
"""
Enhanced debugging for Google Sheets API authentication (Local Testing)
Use this for local debugging before deploying to Streamlit Cloud
"""

import json
import os
from google.oauth2.service_account import Credentials
import gspread
import traceback

def validate_service_account_file(file_path):
    """Validate the service account JSON file format"""
    print("\n🔍 Validating Service Account File...")

    try:
        with open(file_path, 'r') as f:
            creds_dict = json.load(f)

        required_fields = [
            'type', 'project_id', 'private_key_id', 'private_key',
            'client_email', 'client_id', 'auth_uri', 'token_uri',
            'auth_provider_x509_cert_url', 'client_x509_cert_url'
        ]

        print(f"✅ JSON file loaded: {len(creds_dict)} fields found")

        missing_fields = []
        for field in required_fields:
            if field not in creds_dict:
                missing_fields.append(field)
            elif not creds_dict[field]:
                missing_fields.append(f"{field} (empty)")

        if missing_fields:
            print(f"❌ Missing/empty fields: {missing_fields}")
            return None

        # Validate specific fields
        if not creds_dict['client_email'].endswith('gserviceaccount.com'):
            print(f"⚠️  Unusual service account email: {creds_dict['client_email']}")

        if not creds_dict['private_key'].startswith('-----BEGIN PRIVATE KEY-----'):
            print("❌ Private key doesn't start with '-----BEGIN PRIVATE KEY-----'")
            return None

        if not creds_dict['private_key'].endswith('-----END PRIVATE KEY-----'):
            print("❌ Private key doesn't end with '-----END PRIVATE KEY-----'")
            return None

        print("✅ All required fields present and valid")
        print(f"   Service Account: {creds_dict['client_email']}")
        print(f"   Project ID: {creds_dict['project_id']}")
        print(f"   Private Key: {len(creds_dict['private_key'])} characters")

        return creds_dict

    except json.JSONDecodeError as e:
        print(f"❌ Invalid JSON format: {e}")
        return None
    except Exception as e:
        print(f"❌ Error reading file: {e}")
        return None

def debug_authentication():
    print("🔍 Enhanced Authentication Debug")
    print("=" * 60)

    # Check service account file
    file_path = 'service-account-key.json'
    if not os.path.exists(file_path):
        print(f"❌ {file_path} not found!")
        print(f"   Current directory: {os.getcwd()}")
        print(f"   Files in directory: {os.listdir('.')}")
        return False

    # Validate the file format
    creds_dict = validate_service_account_file(file_path)
    if not creds_dict:
        return False

    # Try to create credentials
    scopes = [
        'https://www.googleapis.com/auth/spreadsheets',
        'https://www.googleapis.com/auth/drive'
    ]

    print("\n🔐 Creating Google Credentials...")
    try:
        credentials = Credentials.from_service_account_info(creds_dict, scopes=scopes)
        print("✅ Credentials created successfully")
        print(f"   Service Account Email: {credentials.service_account_email}")
        print(f"   Project ID: {credentials.project_id}")
        print(f"   Scopes: {', '.join(credentials.scopes)}")
    except Exception as e:
        print(f"❌ Credential creation failed: {e}")
        print("\n🔧 Debug info:")
        print(f"   Error type: {type(e).__name__}")
        print("   This usually means the private key is malformed")
        traceback.print_exc()
        return False

    # Try to authorize gspread
    print("\n📋 Authorizing with gspread...")
    try:
        gc = gspread.authorize(credentials)
        print("✅ gspread authorization successful")
    except Exception as e:
        print(f"❌ gspread authorization failed: {e}")
        traceback.print_exc()
        return False

    # Try to open the specific sheet
    sheet_id = "16JzKmS8Jq9H6NmjrpKkqBqNfnXkC_gfPiMV6Y6qP_kQ"
    print(f"\n📊 Opening Google Sheet...")
    print(f"   Sheet ID: {sheet_id}")

    try:
        sheet = gc.open_by_key(sheet_id)
        print(f"✅ Sheet opened successfully: '{sheet.title}'")
        print(f"   Sheet URL: {sheet.url}")
        print(f"   Sheet ID: {sheet.id}")
    except Exception as e:
        print(f"❌ Failed to open sheet: {e}")
        print(f"   Error type: {type(e).__name__}")

        if "PERMISSION_DENIED" in str(e) or "permission" in str(e).lower():
            print("\n💡 Permission Issue Detected!")
            print("   1. Go to your Google Sheet:")
            print(f"      https://docs.google.com/spreadsheets/d/{sheet_id}")
            print("   2. Click 'Share' button")
            print(f"   3. Add this email as Editor: {creds_dict['client_email']}")
            print("   4. Make sure the email is exactly correct")
        elif "NOT_FOUND" in str(e) or "not found" in str(e).lower():
            print("\n💡 Sheet Not Found!")
            print("   1. Check if the sheet ID is correct")
            print("   2. Verify the sheet hasn't been deleted")
            print("   3. Make sure you have access to the sheet")
        else:
            print("\n💡 Unexpected Error:")
            traceback.print_exc()

        return False

    # Try to get worksheet
    print(f"\n📄 Accessing worksheets...")
    try:
        worksheets = sheet.worksheets()
        print(f"✅ Found {len(worksheets)} worksheets:")
        for i, ws in enumerate(worksheets):
            print(f"   {i+1}. {ws.title} (ID: {ws.id})")

        worksheet = sheet.get_worksheet(0)
        print(f"✅ Using first worksheet: '{worksheet.title}'")
    except Exception as e:
        print(f"❌ Error accessing worksheets: {e}")
        traceback.print_exc()
        return False

    # Try to read data
    print(f"\n📖 Testing data access...")
    try:
        # First, get basic info
        print(f"   Rows: {worksheet.row_count}")
        print(f"   Columns: {worksheet.col_count}")

        # Get headers
        headers = worksheet.row_values(1)
        print(f"   Headers ({len(headers)}): {headers}")

        # Try to get all records
        records = worksheet.get_all_records()
        print(f"✅ Successfully read {len(records)} data records")

        if records:
            print("\n📊 Sample data (first record):")
            sample = records[0]
            for key, value in list(sample.items())[:5]:  # Show first 5 fields
                print(f"   {key}: {value}")

            if len(sample) > 5:
                print(f"   ... and {len(sample) - 5} more fields")
        else:
            print("⚠️  No data records found (only headers)")

        return True

    except Exception as e:
        print(f"❌ Error reading data: {e}")
        print(f"   Error type: {type(e).__name__}")

        if "PERMISSION_DENIED" in str(e):
            print("\n💡 The service account needs Editor permissions to read data")
            print("   Current permissions might be view-only")
        else:
            print("\n💡 Full error details:")
            traceback.print_exc()

        return False

def test_write_permissions():
    """Test if we can write to the sheet (optional test)"""
    print("\n✍️  Testing Write Permissions...")
    print("   (This will try to add and immediately remove a test row)")

    try:
        # This is a more complex test that would require the full setup
        # For now, just indicate that write testing is available
        print("   Write permission test available but not implemented in this debug")
        print("   The main app will test write permissions when adding expenses")
        return True
    except Exception as e:
        print(f"❌ Write test failed: {e}")
        return False

def main():
    """Main debug function"""
    success = debug_authentication()

    if success:
        print("\n" + "=" * 60)
        print("🎉 SUCCESS! All authentication tests passed!")
        print("=" * 60)
        print("\n✅ Your setup is working correctly:")
        print("   • Service account file is valid")
        print("   • Google API credentials work")
        print("   • Sheet access permissions are correct")
        print("   • Data can be read successfully")
        print("\n🚀 You can now use your Streamlit app with confidence!")
        print("\n💡 Next steps:")
        print("   1. Copy your service account details to Streamlit Cloud secrets")
        print("   2. Use the STREAMLIT_SECRETS.toml file as a reference")
        print("   3. Deploy your app to Streamlit Cloud")

        # Optionally test write permissions
        if input("\n❓ Test write permissions? (y/N): ").lower().startswith('y'):
            test_write_permissions()
    else:
        print("\n" + "=" * 60)
        print("❌ AUTHENTICATION FAILED")
        print("=" * 60)
        print("\n🔧 Follow the troubleshooting hints above to fix the issues.")
        print("\n📚 For more help, see DEBUG_GUIDE.md")

if __name__ == "__main__":
    main()