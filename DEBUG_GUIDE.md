# Google Sheets API Debug Guide

## Quick Fix for "API 認證失敗" Error

This guide will help you debug and fix Google Sheets API authentication issues in Streamlit Cloud.

## Step 1: Deploy the Debug App

1. **Backup your current app:**
   ```bash
   mv app.py app_backup.py
   ```

2. **Use the debug app:**
   ```bash
   mv debug_app.py app.py
   ```

3. **Deploy to Streamlit Cloud** - the debug app will now run instead of your main app

## Step 2: Run the Debug Tests

The debug app will automatically check:

✅ **Secrets Availability**
- Confirms `st.secrets` is working
- Verifies `google_sheets` section exists

✅ **Field Validation**
- Checks all required fields are present
- Validates private key format
- Verifies service account email format

✅ **Credential Creation**
- Tests Google OAuth2 credential creation
- Shows specific errors if credentials fail

✅ **gspread Authorization**
- Tests authorization with Google API
- Identifies permission issues

✅ **Sheet Access**
- Attempts to open your specific sheet
- Tests read permissions
- Shows sample data

## Step 3: Common Issues and Fixes

### Issue: Missing Fields in Secrets

**Error:** "Missing required fields in secrets"

**Fix:** Ensure your Streamlit Cloud secrets contain ALL these fields:
```toml
[google_sheets]
type = "service_account"
project_id = "your-project-id"
private_key_id = "your-key-id"
private_key = """-----BEGIN PRIVATE KEY-----
YOUR_PRIVATE_KEY_HERE
-----END PRIVATE KEY-----"""
client_email = "your-service-account@project.iam.gserviceaccount.com"
client_id = "your-client-id"
auth_uri = "https://accounts.google.com/o/oauth2/auth"
token_uri = "https://oauth2.googleapis.com/token"
auth_provider_x509_cert_url = "https://www.googleapis.com/oauth2/v1/certs"
client_x509_cert_url = "https://www.googleapis.com/robot/v1/metadata/x509/your-encoded-email"
universe_domain = "googleapis.com"
```

### Issue: Private Key Format Error

**Error:** "Invalid private key format" or "ValueError: Could not deserialize"

**Fix:**
1. Use **triple quotes** for the private key in secrets:
   ```toml
   private_key = """-----BEGIN PRIVATE KEY-----
   YOUR_ACTUAL_KEY_CONTENT
   -----END PRIVATE KEY-----"""
   ```

2. Ensure no extra spaces or characters in the key

3. Copy the key exactly from your JSON file

### Issue: Sheet Not Found / Permission Denied

**Error:** "Spreadsheet not found" or "Permission denied"

**Fix:**
1. **Share your Google Sheet** with the service account email
2. Go to your Google Sheet
3. Click "Share"
4. Add your service account email as **Editor**
5. Service account email format: `name@project-id.iam.gserviceaccount.com`

### Issue: Invalid Grant Error

**Error:** "invalid_grant" or "Token has been expired or revoked"

**Fix:**
1. **Regenerate the service account key:**
   - Go to Google Cloud Console
   - Navigate to IAM & Admin > Service Accounts
   - Find your service account
   - Click "Keys" tab
   - Delete the old key
   - Create a new key (JSON format)
   - Update your secrets with the new key

2. **Check system clock** - OAuth2 is time-sensitive

## Step 4: Advanced Debugging

If the basic debug doesn't solve it, use the comprehensive debug:

```python
# Add to your main app temporarily
from debug_component import show_auth_debug, run_comprehensive_debug

# Quick check in sidebar
if st.sidebar.checkbox("Show Debug"):
    show_auth_debug(expanded=True)

# Or full debug page
run_comprehensive_debug()
```

## Step 5: Test Locally First

Before deploying to Streamlit Cloud:

1. **Test with local file:**
   ```bash
   python debug_auth.py
   ```

2. **Test with environment variables:**
   ```bash
   export GOOGLE_APPLICATION_CREDENTIALS="path/to/service-account.json"
   python test_api.py
   ```

## Step 6: Restore Your App

After fixing the issues:

1. **Restore your original app:**
   ```bash
   mv app.py debug_app.py  # Keep debug app for future use
   mv app_backup.py app.py
   ```

2. **Deploy the fixed app to Streamlit Cloud**

## Debugging Checklist

- [ ] All 11 required fields present in secrets
- [ ] Private key uses triple quotes and correct format
- [ ] Service account email is correct format
- [ ] Google Sheet is shared with service account email
- [ ] Service account has Editor permissions on sheet
- [ ] Sheet ID is correct (from the URL)
- [ ] Service account key is not expired
- [ ] No extra spaces/newlines in secret values

## Emergency Reset

If nothing works:

1. **Create a new service account:**
   - Google Cloud Console > IAM & Admin > Service Accounts
   - Create new service account
   - Generate new JSON key
   - Enable Google Sheets API and Google Drive API

2. **Update all references:**
   - Share sheet with new service account email
   - Update Streamlit secrets with new credentials
   - Test locally first

## Support Files

- `streamlit_debug.py` - Comprehensive debug app
- `debug_component.py` - Reusable debug components
- `debug_app.py` - Temporary app for Streamlit Cloud
- `STREAMLIT_SECRETS.toml` - Reference format for secrets

## Still Having Issues?

If the debug shows all tests passing but you still get authentication errors:

1. **Clear Streamlit cache:**
   - Add "Clear cache" button to your app
   - Or redeploy the app completely

2. **Check for caching issues:**
   - The `@st.cache_resource` decorator might be caching old credentials
   - Temporarily remove caching to test

3. **Verify sheet permissions:**
   - Make sure the service account can read AND write
   - Test with a simple sheet first

The debug tools will give you specific error messages and guidance to fix each issue.