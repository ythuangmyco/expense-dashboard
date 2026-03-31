#!/usr/bin/env python3
"""
Quick setup script for the Family Expense Dashboard
"""

import os
import sys
import json
from pathlib import Path


def create_streamlit_dir():
    """Create .streamlit directory if it doesn't exist"""
    streamlit_dir = Path(".streamlit")
    streamlit_dir.mkdir(exist_ok=True)
    print("✅ Created .streamlit directory")


def create_secrets_template():
    """Create secrets template file"""
    secrets_template = """# Streamlit Secrets Configuration
# Copy your Google Service Account JSON content here

[google_sheets]
type = "service_account"
project_id = "your-project-id"
private_key_id = "your-private-key-id"
private_key = "-----BEGIN PRIVATE KEY-----\\nYOUR_PRIVATE_KEY_HERE\\n-----END PRIVATE KEY-----\\n"
client_email = "your-service-account@your-project-id.iam.gserviceaccount.com"
client_id = "your-client-id"
auth_uri = "https://accounts.google.com/o/oauth2/auth"
token_uri = "https://oauth2.googleapis.com/token"
auth_provider_x509_cert_url = "https://www.googleapis.com/oauth2/v1/certs"
client_x509_cert_url = "https://www.googleapis.com/robot/v1/metadata/x509/your-service-account%40your-project-id.iam.gserviceaccount.com"

[app]
sheet_id = "your-actual-google-sheet-id-here"
"""

    secrets_file = Path(".streamlit/secrets.toml")
    if not secrets_file.exists():
        with open(secrets_file, "w") as f:
            f.write(secrets_template)
        print("✅ Created .streamlit/secrets.toml template")
    else:
        print("ℹ️  .streamlit/secrets.toml already exists")


def update_config():
    """Prompt user to update config.py with their settings"""
    print("\n📝 Configuration Setup")
    print("Please update the following in config.py:")
    print("1. SHEET_ID - Your Google Sheet ID")
    print("2. WORKSHEET_GID - Your worksheet GID")
    print("3. FAMILY_PIN - Change from default '0727' to your family PIN")
    print("4. DEFAULT_COUNTRY and DEFAULT_LOCATION - Set your defaults")
    print("5. QUICK_FAVORITES - Customize for your family's common expenses")


def check_requirements():
    """Check if required packages are installed"""
    try:
        import streamlit
        import pandas
        import plotly
        import gspread
        print("✅ All required packages are installed")
        return True
    except ImportError as e:
        print(f"❌ Missing required package: {e}")
        print("Please run: pip install -r requirements.txt")
        return False


def main():
    """Main setup function"""
    print("🚀 Setting up Family Expense Dashboard")
    print("=" * 50)

    # Check if we're in the right directory
    if not Path("app.py").exists():
        print("❌ app.py not found. Please run this script from the project root directory.")
        sys.exit(1)

    # Create necessary directories and files
    create_streamlit_dir()
    create_secrets_template()

    # Check requirements
    if not check_requirements():
        print("\n❌ Setup incomplete. Please install requirements first.")
        sys.exit(1)

    # Instructions
    print("\n📋 Next Steps:")
    print("1. Follow DEPLOYMENT.md to set up Google Sheets API")
    print("2. Edit .streamlit/secrets.toml with your Google credentials")
    print("3. Update config.py with your sheet details")
    print("4. Run: streamlit run app.py")
    print("5. Test locally before deploying to Streamlit Cloud")

    print("\n🎉 Setup complete! Check DEPLOYMENT.md for detailed instructions.")


if __name__ == "__main__":
    main()