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

> **Login cookie secret (optional):** add `AUTH_COOKIE_SECRET = "<long random string>"` to the Streamlit Cloud secrets
> so the "記住我" cookie stays valid across redeploys/restarts (without it, the secret is derived from `FAMILY_PIN`).
> Put it as a **top-level key on the first line, above `[google_sheets]`** — a key pasted at the end of the secrets
> lands inside the `[app]` table. The app also accepts `[app] AUTH_COOKIE_SECRET` as a fallback, but keep it top-level
> to match `streamlit_secrets.template.toml`. When neither is set the app logs a one-time warning and uses the
> `FAMILY_PIN`-derived secret.
> Changing `AUTH_COOKIE_SECRET` (or `FAMILY_PIN` when no secret is set) invalidates every cookie and logs everyone out.

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
## 💱 Step 8: Foreign-currency columns migration (幣別 / 原幣金額 / 匯率)

The converter stores three **optional** header cells next to the 9 required ones
(live tab `new_to_fill`, gid `453361449`, header `A1:I1`, grid 26 columns wide).
`scripts/migrate_add_currency_columns.py` writes them by name into the first empty
header cells after the last used column (`J1:L1` today), RAW, header row only.
It refuses to run if a required name is missing, the target cells are not empty,
or the FX names are only partially present; re-running on a migrated sheet is a no-op.

**Deploy order: code first, then migrate.** The loader/writer tolerate both the
9-column and the 12-column sheet, so the app must already be on the FX-aware build
before the headers appear.

1. **Rehearse on the copy tab** `Copy of new_to_fill` (gid `1290819173`, same spreadsheet).
   In local `.streamlit/secrets.toml` add under `[app]`:
   ```toml
   worksheet_gid = 1290819173
   ```
   (The app honours the same key, so `streamlit run app.py` now reads/writes the copy.)
2. Dry run, then run:
   ```bash
   expense_env/bin/python scripts/migrate_add_currency_columns.py --dry-run
   expense_env/bin/python scripts/migrate_add_currency_columns.py
   ```
   Expected output: `target cells: J1:L1 (J, K, L)` and the resulting header row
   ending in `幣別, 原幣金額, 匯率`.
3. Verify on the copy: row 1 gains the three names, rows 2..N are unchanged; in the app
   add / edit / delete one SGD entry, then 🔄 重新整理.
4. **Live run:** remove `worksheet_gid` from the secrets (defaults to `453361449`) and run
   the same two commands. Explicit flags work too:
   `--sheet-id ID --worksheet-gid 453361449 --service-account key.json`.
5. Verify live as in step 3; each phone user taps 🔄 重新整理 once.

**Rollback:** clear the three header cells (find them by name, `J1:L1` today) — the code
tolerates their absence and falls back to TWD-only writes with a warning. Do not delete
the columns while rows below them hold values.

Exit codes: `0` done / already migrated, `1` refused (nothing written), `2` usage or
connection error. The script never touches data rows.

---

## 📊 Step 9: 總覽 (overview) layout

Rebuilt phone-first (390 px). Reading order, top to bottom:

1. **Period** — one `st.segmented_control` (今天 / 本週 / 本月 / 本年 / 更多…).
   `更多…` opens a popover with 上月 / 最近7天 / 最近30天 / 全部, a 自訂範圍 date
   pair, and one row per detected trip with a `查看` button.
2. **Hero** — total for the period, a delta against a *named* comparison window
   (本月 → 上月同期, 本週 → 上週同期, …), and a sparkline. When the comparison
   window has no rows the delta is dropped and the caption reads 無前期資料.
3. **Stat strip** — 今天, per-account, and 日常 vs 旅行 (the last only when the
   period contains 旅行 rows).
4. **Top 3 categories** as bars, then the **last 5 transactions**.
5. Everything else lives in collapsed expanders: 📋 本期全部交易, 📈 趨勢,
   👤 帳戶與類型, 🔍 篩選, 🧹 資料檢查.

Notes:

- Filters have **no 全部 sentinel** — an empty selection means "no filter". The
  active selection is echoed as a badge above the hero with a 清除 button.
- Trips are derived, not stored: 旅行 rows outside 台灣 grouped by country and
  split on gaps longer than `TRIP_GAP_DAYS`. 旅行 rows filed under 台灣
  (flights, insurance bought at home) attach to the next trip as 行前.
  A trip whose last row is within `TRIP_ACTIVE_GRACE_DAYS` shows as 正在旅行中.
- Converted rows show the original amount inside 名稱 (`咖啡 · SGD 12.50`)
  rather than in a separate column: a sixth column overflows 390 px.
- Charts are static (`staticPlot`), so a finger drag scrolls the page instead of
  zooming the chart.

### Refreshing the offline FX rates

`config.FX_FALLBACK_RATES` is the last-resort tier when every rate source fails.
Refresh it occasionally and bump `FX_FALLBACK_DATE` — the app shows that date in
the caption (⚠️ 離線匯率 …) so a stale table is visible rather than silent.

### Verifying a change

```bash
expense_env/bin/python -m pytest -q                       # unit + AppTest
expense_env/bin/python tests/chrome/drive_fx.py all       # FX flows in Chrome
expense_env/bin/python tests/chrome/drive_overview.py all # 總覽 layout at 390 px
```

---

## 🔐 Step 10: Why login survives (and when it will not)

Streamlit has no server-side set-cookie API, so "記住我" is a signed token written
from JavaScript. A JS-set cookie is the least durable thing a browser stores:
**WebKit — every browser on iPhone — caps it at 7 days** and drops it under
storage pressure, which is what made logins feel random.

The token is therefore kept in two places:

| Store | Written by | Read by | Survives |
|---|---|---|---|
| `expense_auth` cookie | JS on login / each visit | `st.context.cookies` (the only thing Python can see) | until the browser purges it |
| `localStorage["expense_auth"]` | the same JS | `restore_auth_cookie_js()` in the browser | a cookie purge |

On any page load where the cookie is missing but the localStorage copy is still
valid, the app writes the cookie back and reloads once — the login screen is
never reached. The copy is checked for expiry client-side to avoid a pointless
reload, and the signature is always re-verified on the server. A `sessionStorage`
flag makes it at most one reload per page load, so a rejected token cannot loop.

Logout clears **both** stores; otherwise the backup would silently log you in again.

Still logged out if: the token is genuinely older than 30 days, someone clears
site data, the browser is in private mode, or the device has not opened the app
for long enough that WebKit evicts script-writable storage (7 days of no visits).

Regression suite: `expense_env/bin/python tests/chrome/drive_auth.py all`
(purge the cookie → still logged in; logout wins; reloads never bounce).

---

## 🏠 Step 11: Self-hosting on the lab workstation (huangliu.family)

Why: Streamlit Community Cloud idles a free app after a quiet spell, and waking
it takes about half a minute of looking broken. Self-hosting removes that, and
Cloudflare terminates HTTPS so the login cookie finally gets its `Secure` flag.

### What runs

| Piece | Where |
|---|---|
| App | `huangliu-expense.service` (systemd), `Restart=always`, enabled at boot |
| Bind address | **127.0.0.1:8501 only** — never on the lab LAN; the tunnel reaches it locally |
| Public entry | the machine's existing `cloudflared` tunnel (already serves the LIMS and Specify) |
| Credentials | `.streamlit/secrets.toml`, mode 600, git-ignored |

```bash
sudo systemctl status huangliu-expense      # is it up
sudo systemctl restart huangliu-expense     # after a git pull
journalctl -u huangliu-expense -f           # logs
```

`.streamlit/secrets.toml` holds the real service account, the sheet id and gid,
and a dedicated `AUTH_COOKIE_SECRET`. That last one matters: with it, the cookie
no longer derives from `FAMILY_PIN`, so changing the PIN stops logging everyone
out. Changing `AUTH_COOKIE_SECRET` itself does log everyone out.

### Publishing it

The tunnel config gains one rule (the existing hostnames are untouched):

```yaml
  - hostname: huangliu.family
    service: http://localhost:8501
  - service: http_status:404        # keep the catch-all last
```

Then the DNS record, which the tunnel can create itself:

```bash
cloudflared tunnel route dns <tunnel-id> huangliu.family
sudo cloudflared --config /etc/cloudflared/config.yml tunnel ingress validate
sudo systemctl reload cloudflared        # or restart
```

Prerequisite: `huangliu.family` must be registered and added as a zone in the
same Cloudflare account as the tunnel, otherwise the DNS step has nothing to
write to.

### Worth adding

Put **Cloudflare Access** in front of the hostname (free at household size).
Today the family PIN is the only thing between the open internet and the
records; Access means an unapproved visitor never reaches the app at all.

### Trade-offs, honestly

Power or network loss at the lab takes the app down, and nobody else is on call.
The service restarts itself and comes back after a reboot, but the machine is
shared. Keep the Streamlit Cloud deployment as a fallback until this has proven
itself.
