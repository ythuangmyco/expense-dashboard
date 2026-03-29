# 🔑 Google Sheets API Setup Guide

To enable adding/editing expenses in your dashboard, you need to set up Google Sheets API access.

## 🚀 Quick Setup (5 minutes)

### Step 1: Enable Google Sheets API

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project or select existing one
3. Navigate to **"APIs & Services"** → **"Enable APIs and Services"**
4. Search for **"Google Sheets API"** and enable it
5. Also enable **"Google Drive API"**

### Step 2: Create Service Account

1. Go to **"APIs & Services"** → **"Credentials"**
2. Click **"Create Credentials"** → **"Service Account"**
3. Service account name: `expense-dashboard`
4. Description: `Expense tracking dashboard access`
5. Click **"Create and Continue"**
6. Skip the optional steps, click **"Done"**

### Step 3: Download Key File

1. Click on your newly created service account
2. Go to **"Keys"** tab
3. Click **"Add Key"** → **"Create New Key"**
4. Choose **JSON** format
5. Download the file and rename it to `service-account-key.json`
6. **Save this file in your expense-dashboard folder**

### Step 4: Share Your Google Sheet

1. Open your Google Sheet: `https://docs.google.com/spreadsheets/d/16JzKmS8Jq9H6NmjrpKkqBqNfnXkC_gfPiMV6Y6qP_kQ`
2. Click **"Share"** button
3. Copy the **service account email** from the JSON file (looks like `expense-dashboard@project-name.iam.gserviceaccount.com`)
4. Add this email as an **Editor** to your Google Sheet
5. **IMPORTANT:** Uncheck "Notify people" before sharing

## 📁 Local Development Setup

Put your `service-account-key.json` file in the expense-dashboard folder:

```
expense-dashboard/
├── app.py
├── sheets_api.py
├── service-account-key.json  ← Place your file here
├── requirements.txt
└── ...
```

## 🚀 Deployment Setup (Streamlit Cloud)

For deployment, you'll add the credentials as secrets:

### Step 1: Prepare Credentials

1. Open your `service-account-key.json` file
2. Copy the entire contents

### Step 2: Add to Streamlit Secrets

1. In Streamlit Cloud, go to your app settings
2. Click **"Secrets"**
3. Add this format:

```toml
[google_sheets]
type = "service_account"
project_id = "your-project-id"
private_key_id = "your-private-key-id"
private_key = "-----BEGIN PRIVATE KEY-----\nYOUR-PRIVATE-KEY\n-----END PRIVATE KEY-----\n"
client_email = "expense-dashboard@your-project.iam.gserviceaccount.com"
client_id = "your-client-id"
auth_uri = "https://accounts.google.com/o/oauth2/auth"
token_uri = "https://oauth2.googleapis.com/token"
auth_provider_x509_cert_url = "https://www.googleapis.com/oauth2/v1/certs"
client_x509_cert_url = "https://www.googleapis.com/oauth2/v1/certs"
universe_domain = "googleapis.com"
```

Replace the values with your actual credentials from the JSON file.

## ⚠️ Security Notes

- **Never commit** `service-account-key.json` to Git (it's in .gitignore)
- **Keep credentials secure** - they give full access to your sheet
- **Use minimum permissions** - only share with the service account email

## 🧪 Test Your Setup

Once set up, your dashboard will be able to:

- ✅ Add new expenses
- ✅ Edit existing records
- ✅ Delete expenses
- ✅ Real-time sync with Google Sheets

The app will automatically detect if API access is available and enable input features!

## 🆘 Troubleshooting

**"Authentication failed"**: Check that:
- Service account email is shared with your Google Sheet
- JSON file is in the correct location
- All required APIs are enabled

**"Permission denied"**: Ensure service account has Editor access to the sheet

**"Sheet not found"**: Verify the SHEET_ID in `sheets_api.py` matches your sheet