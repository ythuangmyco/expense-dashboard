"""
Google Sheets API integration with progressive fallback
Handles data reading, writing, and fallback to CSV export
"""

import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
import requests
from datetime import datetime
import logging
from typing import Optional, Dict, List, Union
from config import SHEET_ID, WORKSHEET_GID, SHEET_URL, COLUMN_MAPPING

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class SheetsAPI:
    """
    Google Sheets API client with fallback capabilities
    """

    def __init__(self):
        self.client = None
        self.worksheet = None
        self.api_available = False
        self._initialize_api()

    def _initialize_api(self):
        """
        Initialize Google Sheets API with service account credentials
        Falls back gracefully if credentials are not available
        """
        try:
            # Try to get credentials from Streamlit secrets
            if "google_sheets" in st.secrets:
                credentials = Credentials.from_service_account_info(
                    st.secrets["google_sheets"],
                    scopes=[
                        "https://www.googleapis.com/auth/spreadsheets",
                        "https://www.googleapis.com/auth/drive.readonly"
                    ]
                )
                self.client = gspread.authorize(credentials)

                # Get sheet ID from secrets if available
                sheet_id = st.secrets.get("app", {}).get("sheet_id", SHEET_ID)

                # Open the spreadsheet and worksheet
                spreadsheet = self.client.open_by_key(sheet_id)

                # Find worksheet by GID
                self.worksheet = None
                for ws in spreadsheet.worksheets():
                    if str(ws.id) == str(WORKSHEET_GID):
                        self.worksheet = ws
                        break

                if self.worksheet:
                    self.api_available = True
                    logger.info("✅ Google Sheets API initialized successfully")
                else:
                    logger.warning(f"⚠️ Worksheet with GID {WORKSHEET_GID} not found")

            else:
                logger.info("ℹ️ No Google Sheets credentials found, using CSV fallback")

        except Exception as e:
            logger.error(f"❌ Failed to initialize Google Sheets API: {str(e)}")
            self.api_available = False

    def load_data(self) -> Optional[pd.DataFrame]:
        """
        Load expense data with progressive fallback
        1. Try Google Sheets API
        2. Fall back to CSV export
        3. Return empty DataFrame if all fails
        """
        # Try API first
        if self.api_available and self.worksheet:
            try:
                return self._load_from_api()
            except Exception as e:
                logger.warning(f"⚠️ API failed, falling back to CSV: {str(e)}")

        # Fallback to CSV
        try:
            return self._load_from_csv()
        except Exception as e:
            logger.error(f"❌ CSV fallback failed: {str(e)}")
            st.error("無法載入資料，請檢查網路連線或聯絡管理員")
            return pd.DataFrame()

    def _load_from_api(self) -> pd.DataFrame:
        """Load data directly from Google Sheets API"""
        logger.info("📊 Loading data from Google Sheets API...")

        # Get all values from the worksheet
        all_values = self.worksheet.get_all_values()

        if not all_values:
            return pd.DataFrame()

        # First row is headers
        headers = all_values[0]
        data_rows = all_values[1:]

        # Create DataFrame
        df = pd.DataFrame(data_rows, columns=headers)

        # Clean and process the data
        return self._process_data(df, source="api")

    def _load_from_csv(self) -> pd.DataFrame:
        """Load data from CSV export as fallback"""
        logger.info("📄 Loading data from CSV export...")

        # Construct CSV URL with specific GID
        csv_url = SHEET_URL
        if "google_sheets" in st.secrets and "app" in st.secrets:
            sheet_id = st.secrets["app"].get("sheet_id", SHEET_ID)
            csv_url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv&gid={WORKSHEET_GID}"

        # Download CSV data
        response = requests.get(csv_url, timeout=10)
        response.raise_for_status()

        # Read into DataFrame
        from io import StringIO
        df = pd.read_csv(StringIO(response.text))

        return self._process_data(df, source="csv")

    def _process_data(self, df: pd.DataFrame, source: str) -> pd.DataFrame:
        """
        Clean and process the raw data from Google Sheets
        """
        logger.info(f"🧹 Processing data from {source}...")

        # Remove completely empty rows and columns
        df = df.dropna(how='all')
        df = df.loc[:, (df != '').any(axis=0)]

        # Apply column mapping (Chinese to English)
        df = df.rename(columns=COLUMN_MAPPING)

        # Remove rows where critical fields are missing
        critical_fields = ['date', 'amount']
        for field in critical_fields:
            if field in df.columns:
                df = df[df[field].notna() & (df[field] != '')]

        if df.empty:
            logger.warning("⚠️ No valid data found after cleaning")
            return df

        # Data type conversion
        try:
            # Convert date column
            if 'date' in df.columns:
                df['date'] = pd.to_datetime(df['date'], errors='coerce')

            # Convert amount column
            if 'amount' in df.columns:
                df['amount'] = pd.to_numeric(df['amount'], errors='coerce')

            # Remove rows with invalid date or amount
            df = df.dropna(subset=['date', 'amount'])

            # Add derived fields for analysis
            if 'date' in df.columns:
                df['year'] = df['date'].dt.year
                df['month'] = df['date'].dt.month
                df['month_year'] = df['date'].dt.to_period('M')
                df['weekday'] = df['date'].dt.day_name()

            # Ensure text fields are strings
            text_fields = ['description', 'category_type', 'category_emoji', 'account', 'country', 'location', 'notes']
            for field in text_fields:
                if field in df.columns:
                    df[field] = df[field].astype(str).fillna('')

            logger.info(f"✅ Processed {len(df)} expense records")

        except Exception as e:
            logger.error(f"❌ Error processing data: {str(e)}")
            st.error(f"資料處理錯誤: {str(e)}")

        return df

    def add_expense(self, expense_data: Dict) -> bool:
        """
        Add a new expense record to the sheet
        Returns True if successful, False otherwise
        """
        if not self.api_available or not self.worksheet:
            st.warning("⚠️ 無法新增資料，API 不可用")
            return False

        try:
            # Prepare row data in correct column order
            row_data = [
                expense_data.get('date', ''),
                expense_data.get('category_emoji', ''),
                expense_data.get('category_type', ''),
                expense_data.get('amount', ''),
                expense_data.get('account', ''),
                expense_data.get('description', ''),
                expense_data.get('country', ''),
                expense_data.get('location', ''),
                expense_data.get('notes', ''),
                expense_data.get('combined_location', '')  # 合併地點
            ]

            # Append to worksheet
            self.worksheet.append_row(row_data)
            logger.info(f"✅ Added expense: {expense_data.get('description', '')} - NT${expense_data.get('amount', 0)}")

            # Clear Streamlit cache to reflect changes
            st.cache_data.clear()

            return True

        except Exception as e:
            logger.error(f"❌ Failed to add expense: {str(e)}")
            st.error(f"新增失敗: {str(e)}")
            return False

    def update_expense(self, row_index: int, expense_data: Dict) -> bool:
        """
        Update an existing expense record
        """
        if not self.api_available or not self.worksheet:
            st.warning("⚠️ 無法更新資料，API 不可用")
            return False

        try:
            # Calculate actual row number (accounting for header row)
            row_number = row_index + 2

            # Prepare row data
            row_data = [
                expense_data.get('date', ''),
                expense_data.get('category_emoji', ''),
                expense_data.get('category_type', ''),
                expense_data.get('amount', ''),
                expense_data.get('account', ''),
                expense_data.get('description', ''),
                expense_data.get('country', ''),
                expense_data.get('location', ''),
                expense_data.get('notes', ''),
                expense_data.get('combined_location', '')
            ]

            # Update the row
            self.worksheet.update(f'A{row_number}:J{row_number}', [row_data])
            logger.info(f"✅ Updated expense at row {row_index}")

            # Clear cache
            st.cache_data.clear()

            return True

        except Exception as e:
            logger.error(f"❌ Failed to update expense: {str(e)}")
            st.error(f"更新失敗: {str(e)}")
            return False

    def delete_expense(self, row_index: int) -> bool:
        """
        Delete an expense record
        """
        if not self.api_available or not self.worksheet:
            st.warning("⚠️ 無法刪除資料，API 不可用")
            return False

        try:
            # Calculate actual row number
            row_number = row_index + 2

            # Delete the row
            self.worksheet.delete_rows(row_number)
            logger.info(f"✅ Deleted expense at row {row_index}")

            # Clear cache
            st.cache_data.clear()

            return True

        except Exception as e:
            logger.error(f"❌ Failed to delete expense: {str(e)}")
            st.error(f"刪除失敗: {str(e)}")
            return False

    def get_status(self) -> Dict:
        """Get API status information"""
        return {
            "api_available": self.api_available,
            "worksheet_connected": self.worksheet is not None,
            "sheet_id": SHEET_ID if "google_sheets" not in st.secrets else st.secrets.get("app", {}).get("sheet_id", SHEET_ID),
            "worksheet_gid": WORKSHEET_GID
        }


# Global instance
_sheets_api = None

def get_sheets_api() -> SheetsAPI:
    """
    Get or create the global SheetsAPI instance
    """
    global _sheets_api
    if _sheets_api is None:
        _sheets_api = SheetsAPI()
    return _sheets_api


@st.cache_data(ttl=300)  # Cache for 5 minutes
def load_expense_data() -> pd.DataFrame:
    """
    Cached function to load expense data
    """
    api = get_sheets_api()
    return api.load_data()


def refresh_data():
    """
    Force refresh of cached data
    """
    st.cache_data.clear()
    logger.info("🔄 Data cache cleared")