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

## 📱 Design Principles

- **Speed First**: Make expense entry faster than opening traditional apps
- **Smart Defaults**: Learn from user patterns
- **Graceful Fallbacks**: Always works, even without full API setup
- **Visual Categories**: Emoji-based categorization for quick recognition

Built for real family use - prioritizing practical functionality over complex features.