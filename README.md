# 📊 Family Expense Dashboard

A mobile-first expense tracking application built with Streamlit and Google Sheets.

## 🚀 Features

- **Quick Entry**: One-tap expense logging with smart favorites
- **Real-time Sync**: Google Sheets as live database
- **Mobile-First**: Optimized for phone use
- **Family-Friendly**: Simple PIN authentication, multiple accounts
- **Progressive Enhancement**: Works with fallback CSV when API unavailable

## 🏗️ Architecture

- **Frontend**: Streamlit (Python web framework)
- **Database**: Google Sheets API with CSV fallback
- **Charts**: Plotly for interactive visualizations
- **Auth**: Simple PIN + Google Service Account

## ⚡ Quick Start

1. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

2. Set up Google Sheets API (see deployment guide)

3. Run locally:
   ```bash
   streamlit run app.py
   ```

4. Access at `http://localhost:8501`

## 💱 Foreign currency (外幣換算)

Entries abroad can be typed in the local currency; the app converts to integer TWD
(`金額`, the single source of truth) and stores `幣別` / `原幣金額` / `匯率` beside it.
Rates: Frankfurter → open.er-api ("Rates By Exchange Rate API" attribution shown when
used) → fawazahmed0 currency-api → last used rate from the sheet → static
`config.FX_FALLBACK_RATES` (refresh occasionally; stamped by `FX_FALLBACK_DATE`).
The rate is always editable; the add form quotes today's rate even for back-dated entries.
The sheet needs the three optional header cells — see `DEPLOYMENT.md` Step 8 and
`scripts/migrate_add_currency_columns.py`.

Tests: `expense_env/bin/python -m pytest -q` (no network, no real sheet).

## 📱 Design Principles

- **Speed First**: Make expense entry faster than opening traditional apps
- **Smart Defaults**: Learn from user patterns
- **Graceful Fallbacks**: Always works, even without full API setup
- **Visual Categories**: Emoji-based categorization for quick recognition

Built for real family use - prioritizing practical functionality over complex features.