# 🚀 Deployment Guide

Complete guide to deploy your Family Expense Dashboard

## 📋 Prerequisites

- Google account with Google Sheets access
- GitHub account
- Streamlit Cloud account (free)

## 🔧 Step 1: Google Sheets Setup

### 1.1 Create Your Expense Sheet

1. Go to [Google Sheets](https://sheets.google.com)
2. Create a new spreadsheet
3. Name it "Family Expense Tracker" (or your preferred name)
4. Set up columns in the first row:
   ```
   日期 | 類型_1 | 類型_2 | 金額 | 帳戶 | 名稱 | 國家 | 地點 | 備註 | 合併地點
   ```

### 1.2 Get Sheet ID and GID

1. Open your sheet and copy the URL
2. Extract the Sheet ID from the URL:
   ```
   https://docs.google.com/spreadsheets/d/{SHEET_ID}/edit#gid={GID}
   ```
3. Note both the `SHEET_ID` and `GID` numbers

### 1.3 Set Up Google API Credentials

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project or select existing one
3. Enable the Google Sheets API:
   - Go to "APIs & Services" > "Library"
   - Search for "Google Sheets API"
   - Click "Enable"
4. Create service account credentials:
   - Go to "APIs & Services" > "Credentials"
   - Click "Create Credentials" > "Service Account"
   - Fill in the details and create
   - Download the JSON key file

### 1.4 Share Sheet with Service Account

1. Open the downloaded JSON file
2. Copy the `client_email` value
3. Go back to your Google Sheet
4. Click "Share" button
5. Add the service account email with "Editor" permissions
6. Uncheck "Notify people" to avoid spam

## ⚙️ Step 2: Local Development

### 2.1 Clone and Setup

```bash
git clone <your-repo-url>
cd expense-dashboard
pip install -r requirements.txt
```

### 2.2 Configure Credentials

1. Create `.streamlit` directory:
   ```bash
   mkdir .streamlit
   ```

2. Create `.streamlit/secrets.toml` file:
   ```toml
   [google_sheets]
   type = "service_account"
   project_id = "your-project-id"
   private_key_id = "your-private-key-id"  
   private_key = "-----BEGIN PRIVATE KEY-----\nYOUR_PRIVATE_KEY_HERE\n-----END PRIVATE KEY-----\n"
   client_email = "your-service-account@your-project.iam.gserviceaccount.com"
   client_id = "your-client-id"
   auth_uri = "https://accounts.google.com/o/oauth2/auth"
   token_uri = "https://oauth2.googleapis.com/token"
   auth_provider_x509_cert_url = "https://www.googleapis.com/oauth2/v1/certs"
   client_x509_cert_url = "https://www.googleapis.com/robot/v1/metadata/x509/your-service-account%40your-project.iam.gserviceaccount.com"

   [app]
   sheet_id = "your-actual-google-sheet-id"
   ```

3. Update `config.py` with your sheet details:
   ```python
   SHEET_ID = "your-sheet-id"
   WORKSHEET_GID = your-worksheet-gid  # Replace with actual GID
   ```

### 2.3 Test Locally

```bash
streamlit run app.py
```

Open `http://localhost:8501` and test the application.

## 🌐 Step 3: Deploy to Streamlit Cloud

### 3.1 Prepare Repository

1. Push your code to GitHub
2. Ensure `.streamlit/secrets.toml` is in `.gitignore` (it should be)
3. Make sure all files are committed

### 3.2 Deploy on Streamlit Cloud

1. Go to [Streamlit Cloud](https://share.streamlit.io/)
2. Sign in with GitHub
3. Click "New app"
4. Select your repository and branch
5. Set main file path: `app.py`
6. Click "Deploy"

### 3.3 Configure Secrets in Streamlit Cloud

1. In your Streamlit Cloud dashboard, go to your app
2. Click on "Settings" > "Secrets"
3. Copy the content from your local `.streamlit/secrets.toml`
4. Paste it into the secrets editor
5. Save the secrets

### 3.4 Update Configuration

If needed, update the following in your `config.py`:

```python
# Update these to match your setup
FAMILY_PIN = "0727"  # Change to your preferred PIN
DEFAULT_COUNTRY = "台灣"  # Set your default country
DEFAULT_LOCATION = "臺南"  # Set your default location
```

## 📱 Step 4: Mobile Optimization

### 4.1 Progressive Web App Setup

Add these meta tags to your app (Streamlit handles this automatically):
- Viewport meta tag for mobile responsiveness
- PWA manifest for "Add to Home Screen" functionality

### 4.2 Test on Mobile

1. Open the deployed app URL on your phone
2. Test the quick entry buttons
3. Verify the responsive layout
4. Test the PIN authentication

## 🔒 Step 5: Security Best Practices

### 5.1 Environment Security

- ✅ Never commit credentials to Git
- ✅ Use Streamlit Cloud secrets for production
- ✅ Regularly rotate service account keys
- ✅ Monitor Google Cloud Console for unusual activity

### 5.2 Application Security

- ✅ Change the default PIN from "0727" to your family PIN
- ✅ Keep the Google Sheet private (only shared with service account)
- ✅ Regularly backup your data

## 🐛 Troubleshooting

### Common Issues

**"No data available" or API errors:**
- Check Google Sheets API is enabled
- Verify service account email has sheet access
- Confirm sheet ID and GID are correct
- Check secrets are properly set in Streamlit Cloud

**Authentication errors:**
- Verify the private key format (includes \\n for newlines)
- Check all required fields are in secrets.toml
- Ensure service account has correct permissions

**Mobile layout issues:**
- Test on different devices and browsers
- Check CSS is loading properly
- Verify responsive breakpoints

### Debug Mode

Enable debug logging by adding to your `config.py`:

```python
import logging
logging.basicConfig(level=logging.DEBUG)
```

## 📊 Step 6: Usage Tips

### Family Adoption

1. **Share the PIN** with family members
2. **Demo the quick entry** - show how fast it is
3. **Customize favorites** in `config.py` based on your family's spending patterns
4. **Add to home screen** on everyone's phone

### Data Management

1. **Regular backups**: Download CSV periodically
2. **Category management**: Update `CATEGORIES` in config as needed
3. **Account management**: Modify `ACCOUNTS` for family members

## 🔄 Step 7: Maintenance

### Regular Updates

1. **Monitor usage** via Streamlit Cloud dashboard
2. **Update dependencies** periodically:
   ```bash
   pip install --upgrade -r requirements.txt
   ```
3. **Review and optimize** quick favorites based on usage patterns

### Scaling

If you need more features:
- Add budget tracking
- Implement expense limits/alerts  
- Add export functionality
- Create detailed reporting

---

🎉 **Your Family Expense Dashboard is now live!**

The mobile-first design ensures family members can quickly log expenses in under 10 seconds, making this more convenient than traditional expense apps.