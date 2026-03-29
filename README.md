# 📊 Personal Expense Dashboard

A real-time expense tracking dashboard that connects to Google Sheets data for family expense monitoring.

## 🚀 Features

- **Real-time Data**: Automatically syncs with Google Sheets expense tracker
- **Mobile-Friendly**: Responsive design works on phones and laptops
- **Interactive Visualizations**: Monthly trends, category breakdowns, account comparisons
- **Smart Filtering**: Filter by date range, account, and category
- **Summary Metrics**: Total spent, averages, transaction counts

## 📱 Key Visualizations

- 📈 Monthly spending trends over time
- 🥧 Expense category distribution (with emoji categories)
- 👥 Account holder comparison (菇菇 vs 過兒)
- 📝 Recent transactions table
- 💰 Summary metrics dashboard

## 🛠️ Setup

### Local Development

1. Clone the repository
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Run the app:
   ```bash
   streamlit run app.py
   ```

### Deployment

This app is designed to be deployed on Streamlit Cloud:

1. Push code to GitHub
2. Connect to Streamlit Cloud
3. Deploy directly from your repository

## 🌐 Data Source

The app connects to a live Google Sheets document that collects expense data from a Google Form. The data includes:

- **日期** (Date)
- **類型_1** (Category with emojis)
- **類型_2** (Subcategory)
- **金額** (Amount in TWD)
- **帳戶** (Account holder)
- **名稱** (Description)
- **國家** (Country)
- **地點** (Location)
- **備註** (Notes)

## 🔧 Configuration

To use with your own Google Sheets:

1. Make your Google Sheet public (view-only)
2. Get the CSV export URL
3. Update the `SHEET_URL` variable in `app.py`

## 📊 Dashboard Sections

1. **Summary Cards**: Quick overview of spending metrics
2. **Monthly Trends**: Line chart showing spending over time
3. **Category Analysis**: Pie chart of expense categories
4. **Account Comparison**: Bar chart comparing account holders
5. **Recent Transactions**: Table of latest expenses

## 💡 Technical Notes

- Data is cached for 5 minutes to improve performance
- Automatic data cleaning and type conversion
- Responsive CSS for mobile devices
- Error handling for data loading issues