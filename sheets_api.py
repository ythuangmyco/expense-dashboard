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
                worksheets = spreadsheet.worksheets()
                logger.info(f"📋 Available worksheets: {[(ws.title, ws.id) for ws in worksheets]}")

                for ws in worksheets:
                    logger.info(f"🔍 Checking worksheet: {ws.title} (GID: {ws.id})")
                    if str(ws.id) == str(WORKSHEET_GID):
                        self.worksheet = ws
                        logger.info(f"✅ Found target worksheet: {ws.title}")
                        break

                if self.worksheet:
                    self.api_available = True
                    # Check worksheet has data
                    try:
                        row_count = len(self.worksheet.get_all_values())
                        logger.info(f"✅ Google Sheets API initialized successfully - {row_count} rows available")
                    except Exception as e:
                        logger.warning(f"⚠️ Could not check row count: {e}")
                        logger.info("✅ Google Sheets API initialized successfully")
                else:
                    logger.error(f"❌ Worksheet with GID {WORKSHEET_GID} not found")
                    logger.error(f"Available worksheets: {[(ws.title, ws.id) for ws in worksheets]}")

            else:
                logger.info("ℹ️ No Google Sheets credentials found, using CSV fallback")

        except Exception as e:
            logger.error(f"❌ Failed to initialize Google Sheets API: {str(e)}")
            self.api_available = False

    def load_data(self) -> Optional[pd.DataFrame]:
        """
        Load expense data with progressive fallback
        1. Try Google Sheets API (PREFERRED - has all data)
        2. Fall back to CSV export (may have authentication issues)
        3. Return empty DataFrame if all fails
        """
        # Try API first - this is our primary method
        if self.api_available and self.worksheet:
            try:
                logger.info("🚀 Attempting to load data via Google Sheets API...")
                df = self._load_from_api()
                if not df.empty:
                    logger.info(f"✅ API loaded {len(df)} records successfully")
                    return df
                else:
                    logger.warning("⚠️ API returned empty DataFrame")
            except Exception as e:
                logger.error(f"❌ API failed: {str(e)}")
                st.error(f"Google Sheets API 錯誤: {str(e)}")
                # Don't fall back to CSV if API fails - CSV is likely to have auth issues too

        # Show API status
        if not self.api_available:
            st.error("❌ Google Sheets API 不可用")
            st.info("💡 請確認 Streamlit Cloud secrets 設定正確")

        if not self.worksheet:
            st.error("❌ 無法連接到工作表")
            st.info(f"💡 請確認工作表 GID {WORKSHEET_GID} 存在且可訪問")

        # Only try CSV as last resort and warn user
        st.warning("⚠️ 嘗試 CSV 備用方案 (可能無法存取完整資料)")
        try:
            return self._load_from_csv()
        except Exception as e:
            logger.error(f"❌ CSV fallback failed: {str(e)}")
            st.error("❌ 所有資料載入方法均失敗")
            st.info("💡 請檢查網路連線和 Google Sheets 權限設定")
            return pd.DataFrame()

    def _load_from_api(self) -> pd.DataFrame:
        """Load data directly from Google Sheets API"""
        logger.info("📊 Loading data from Google Sheets API...")

        # Get all values from the worksheet
        all_values = self.worksheet.get_all_values()

        logger.info(f"📊 Retrieved {len(all_values)} total rows from API")

        if not all_values:
            logger.warning("⚠️ No data retrieved from API")
            return pd.DataFrame()

        # First row is headers
        headers = all_values[0]
        data_rows = all_values[1:]

        logger.info(f"📋 Headers: {headers}")
        logger.info(f"📊 Data rows: {len(data_rows)}")

        # Create DataFrame
        df = pd.DataFrame(data_rows, columns=headers)

        # Show summary before processing
        logger.info(f"📊 Raw DataFrame shape: {df.shape}")
        if 'amount' in df.columns or '金額' in df.columns:
            amount_col = '金額' if '金額' in df.columns else 'amount'
            # Convert to numeric for sum calculation
            numeric_amounts = pd.to_numeric(df[amount_col], errors='coerce')
            total = numeric_amounts.sum()
            logger.info(f"💰 Total amount before processing: {total:,.0f}")
            st.info(f"📊 載入原始資料: {len(df)} 筆, 總額: NT${total:,.0f}")

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

        logger.info(f"📄 CSV URL: {csv_url}")

        try:
            # Download CSV data with proper UTF-8 handling
            response = requests.get(csv_url, timeout=10)
            logger.info(f"📄 CSV response status: {response.status_code}")

            # Check if we got redirected or have authentication issues
            if response.status_code == 200:
                content_type = response.headers.get('content-type', '')
                if 'text/html' in content_type:
                    logger.warning("📄 CSV export returned HTML (likely authentication required)")
                    st.warning("⚠️ CSV 匯出需要驗證，僅使用 API 模式")
                    return pd.DataFrame()

            response.raise_for_status()

            # Try multiple encoding approaches
            try:
                # Method 1: Force UTF-8 encoding
                response.encoding = 'utf-8'
                csv_text = response.text
            except UnicodeDecodeError:
                try:
                    # Method 2: Use raw bytes with UTF-8
                    csv_text = response.content.decode('utf-8')
                except UnicodeDecodeError:
                    # Method 3: Use raw bytes with UTF-8 and ignore errors
                    csv_text = response.content.decode('utf-8', errors='replace')

        except Exception as e:
            logger.warning(f"📄 CSV fallback failed: {str(e)}")
            st.warning("⚠️ CSV 資料載入失敗，請確認 Google Sheets API 設定正確")
            return pd.DataFrame()

        # Read into DataFrame
        from io import StringIO
        df = pd.read_csv(StringIO(csv_text))

        # Try to fix column encoding if needed
        if df.columns.size > 0 and any('\\x' in str(col) for col in df.columns):
            logger.info("🔧 Attempting to fix UTF-8 encoding in column names...")
            new_columns = []
            for col in df.columns:
                try:
                    # Try to decode UTF-8 encoded strings
                    if isinstance(col, str) and '\\x' in col:
                        # This handles the æ\x97¥æ\x9c\x9f format
                        fixed_col = col.encode('latin-1').decode('utf-8')
                        new_columns.append(fixed_col)
                        logger.info(f"✅ Fixed column: {col} → {fixed_col}")
                    else:
                        new_columns.append(col)
                except:
                    new_columns.append(col)
            df.columns = new_columns

        return self._process_data(df, source="csv")

    def _process_data(self, df: pd.DataFrame, source: str) -> pd.DataFrame:
        """
        Clean and process the raw data from Google Sheets
        """
        logger.info(f"🧹 Processing data from {source}...")

        # Show shape before cleaning
        logger.info(f"📊 Before cleaning: {df.shape}")

        # Remove completely empty rows and columns (but be less aggressive)
        df = df.dropna(how='all')
        # Only remove columns that are completely empty
        df = df.loc[:, df.notna().any()]

        logger.info(f"📊 After removing empty rows/cols: {df.shape}")

        # Debug: Show actual column names
        logger.info(f"📋 Actual columns in sheet: {list(df.columns)}")
        if not df.empty:
            logger.info(f"📊 Sample data: {df.head(1).to_dict('records')}")

        # Apply column mapping (Chinese to English) - only for columns that exist
        existing_mapping = {k: v for k, v in COLUMN_MAPPING.items() if k in df.columns}
        df = df.rename(columns=existing_mapping)

        logger.info(f"✅ Mapped columns: {existing_mapping}")
        logger.info(f"🔄 Final columns: {list(df.columns)}")

        # Check for critical fields but don't be too aggressive about removing data
        critical_fields = ['date', 'amount']
        available_critical = [field for field in critical_fields if field in df.columns]

        logger.info(f"🎯 Critical fields available: {available_critical}")

        if available_critical:
            # Only remove rows where BOTH date AND amount are missing/empty
            # Be more lenient - allow rows with some missing data
            rows_before = len(df)
            if 'date' in df.columns and 'amount' in df.columns:
                # Only remove rows where both date and amount are empty
                df = df[~(df['date'].isna() & df['amount'].isna())]
                # Also remove rows where both are empty strings
                df = df[~((df['date'] == '') & (df['amount'] == ''))]
            elif 'date' in df.columns:
                # Only remove rows with empty dates
                df = df[df['date'].notna() & (df['date'] != '')]
            elif 'amount' in df.columns:
                # Only remove rows with empty amounts
                df = df[df['amount'].notna() & (df['amount'] != '')]

            rows_after = len(df)
            logger.info(f"📊 Removed {rows_before - rows_after} rows with missing critical data")
        else:
            logger.warning(f"⚠️ No critical fields found! Available columns: {list(df.columns)}")
            st.warning(f"找不到必要欄位 (date/amount)。實際欄位: {list(df.columns)}")

        if df.empty:
            logger.warning("⚠️ No valid data found after cleaning")
            return df

        # Data type conversion
        try:
            # Convert date column if it exists
            date_cols = [col for col in df.columns if 'date' in col.lower() or '日期' in col]
            if date_cols:
                date_col = date_cols[0]
                logger.info(f"📅 Converting date column: {date_col}")
                df['date'] = pd.to_datetime(df[date_col], errors='coerce')

            # Convert amount column if it exists
            amount_cols = [col for col in df.columns if 'amount' in col.lower() or '金額' in col]
            if amount_cols:
                amount_col = amount_cols[0]
                logger.info(f"💰 Converting amount column: {amount_col}")

                # Show some sample values before conversion
                logger.info(f"💰 Sample amount values: {df[amount_col].head().tolist()}")

                df['amount'] = pd.to_numeric(df[amount_col], errors='coerce')

                # Show conversion results
                valid_amounts = df['amount'].notna().sum()
                total_amount = df['amount'].sum()
                logger.info(f"💰 After conversion: {valid_amounts} valid amounts, total: {total_amount:,.0f}")

            # Only remove rows with invalid data if both date and amount exist, but be more lenient
            if 'date' in df.columns and 'amount' in df.columns:
                rows_before = len(df)
                # Only drop rows where BOTH date and amount are invalid
                df = df.dropna(subset=['date', 'amount'])
                rows_after = len(df)
                logger.info(f"📊 Removed {rows_before - rows_after} rows with invalid date/amount")

                if len(df) > 0:
                    final_total = df['amount'].sum()
                    logger.info(f"💰 Final total after all processing: {final_total:,.0f}")
                    st.success(f"✅ 處理完成: {len(df)} 筆有效記錄, 總額: NT${final_total:,.0f}")

            # Add derived fields for analysis (only if date column exists)
            if 'date' in df.columns:
                df['year'] = df['date'].dt.year
                df['month'] = df['date'].dt.month
                df['month_year'] = df['date'].dt.to_period('M')
                df['weekday'] = df['date'].dt.day_name()

            # Ensure text fields are strings (only for fields that exist)
            text_fields = ['description', 'category_type', 'type_1', 'account', 'country', 'location', 'notes']
            for field in text_fields:
                if field in df.columns:
                    df[field] = df[field].astype(str).fillna('')

            logger.info(f"✅ Processed {len(df)} expense records")

        except Exception as e:
            logger.error(f"❌ Error processing data: {str(e)}")
            st.error(f"資料處理錯誤: {str(e)}")
            # Return empty DataFrame with expected columns if processing fails
            return pd.DataFrame(columns=['date', 'amount', 'description', 'account'])

        return df

    def add_expense(self, expense_data: Dict) -> bool:
        """
        Add a new expense record to the sheet
        Returns True if successful, False otherwise
        """
        logger.info(f"🔍 Attempting to add expense: {expense_data}")

        if not self.api_available:
            st.error("❌ Google Sheets API 未設定或不可用")
            st.info("💡 請確認已在 Streamlit Cloud 設定 secrets，或本地設定 service account 金鑰")
            return False

        if not self.worksheet:
            st.error("❌ 無法連接到工作表")
            st.info("💡 請確認 Google Sheet 已與 service account 共用，且有編輯權限")
            return False

        try:
            # Convert date to match existing format (MM/DD/YYYY)
            try:
                from datetime import datetime
                date_obj = datetime.strptime(expense_data.get('date', ''), '%Y-%m-%d')
                formatted_date = date_obj.strftime('%m/%d/%Y')
            except:
                formatted_date = expense_data.get('date', '')

            # Prepare row data in EXACT Google Form format (matching existing data)
            row_data = [
                formatted_date,                          # MM/DD/YYYY format
                expense_data.get('type_1', ''),          # 📅 日常 or ✈️ 旅行
                expense_data.get('category_type', ''),   # 🍽️ 飲食, 👶 寶寶 etc. (exact form values)
                expense_data.get('amount', ''),
                expense_data.get('account', ''),
                expense_data.get('description', ''),
                expense_data.get('country', ''),
                expense_data.get('location', ''),
                expense_data.get('notes', '')
            ]

            logger.info(f"📝 Row data to append: {row_data}")

            # Append to worksheet
            self.worksheet.append_row(row_data)
            logger.info(f"✅ Successfully added expense: {expense_data.get('description', '')} - NT${expense_data.get('amount', 0)}")

            # Clear Streamlit cache to reflect changes
            st.cache_data.clear()

            # Show success message with details
            st.success(f"✅ 成功新增支出: {expense_data.get('description', '')} - NT${expense_data.get('amount', 0):,.0f}")

            return True

        except Exception as e:
            error_msg = str(e)
            logger.error(f"❌ Failed to add expense: {error_msg}")

            # Provide specific error guidance
            if "403" in error_msg:
                st.error("❌ 權限不足：請確認 Google Sheet 已與 service account 共用")
                st.info("💡 Service account email: expense-dashboard@divine-engine-491814-c3.iam.gserviceaccount.com")
            elif "404" in error_msg:
                st.error("❌ 找不到工作表：請確認 Sheet ID 和 GID 正確")
            else:
                st.error(f"❌ 新增失敗: {error_msg}")

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

            # Convert date to match existing format (MM/DD/YYYY)
            try:
                from datetime import datetime
                date_obj = datetime.strptime(expense_data.get('date', ''), '%Y-%m-%d')
                formatted_date = date_obj.strftime('%m/%d/%Y')
            except:
                formatted_date = expense_data.get('date', '')

            # Prepare row data in EXACT Google Form format
            row_data = [
                formatted_date,                          # MM/DD/YYYY format
                expense_data.get('type_1', ''),          # 📅 日常 or ✈️ 旅行
                expense_data.get('category_type', ''),   # 🍽️ 飲食, 👶 寶寶 etc.
                expense_data.get('amount', ''),
                expense_data.get('account', ''),
                expense_data.get('description', ''),
                expense_data.get('country', ''),
                expense_data.get('location', ''),
                expense_data.get('notes', '')
            ]

            # Update the row
            self.worksheet.update(f'A{row_number}:I{row_number}', [row_data])
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


@st.cache_data(ttl=60)  # Cache for 1 minute to see updates faster
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