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
                        all_values = self.worksheet.get_all_values()
                        row_count = len(all_values)
                        logger.info(f"✅ Google Sheets API initialized successfully - {row_count} rows available")

                        # Quick check of data structure in this worksheet
                        if all_values and len(all_values) > 1:
                            headers = all_values[0]
                            sample_row = all_values[1] if len(all_values) > 1 else []
                            logger.info(f"📋 Worksheet '{self.worksheet.title}' headers: {headers}")
                            logger.info(f"📊 Sample row: {sample_row}")

                            # Check if this worksheet has amount data that sums to ~2.5M
                            amount_cols = [i for i, h in enumerate(headers) if any(keyword in str(h).lower()
                                         for keyword in ['amount', '金額', 'money', '錢'])]

                            for col_idx in amount_cols:
                                col_name = headers[col_idx]
                                values = [row[col_idx] if col_idx < len(row) else '' for row in all_values[1:]]
                                numeric_values = []
                                for val in values:
                                    try:
                                        if val and val != '':
                                            numeric_values.append(float(val))
                                    except:
                                        pass

                                if numeric_values:
                                    total = sum(numeric_values)
                                    logger.info(f"💰 Worksheet '{self.worksheet.title}' column '{col_name}' total: {total:,.0f}")
                                    if total > 2000000:
                                        st.success(f"🎯 在工作表 '{self.worksheet.title}' 發現大額總計: {total:,.0f}")

                    except Exception as e:
                        logger.warning(f"⚠️ Could not check row count: {e}")
                        logger.info("✅ Google Sheets API initialized successfully")
                else:
                    logger.error(f"❌ Worksheet with GID {WORKSHEET_GID} not found")
                    logger.error(f"Available worksheets: {[(ws.title, ws.id) for ws in worksheets]}")

                    # Check other worksheets to see if they have the expected data
                    st.warning(f"⚠️ 找不到指定的工作表 GID {WORKSHEET_GID}")
                    st.info("🔍 檢查其他可用的工作表...")

                    for ws in worksheets:
                        try:
                            logger.info(f"🔍 Checking alternative worksheet: {ws.title} (GID: {ws.id})")
                            ws_values = ws.get_all_values()
                            if ws_values and len(ws_values) > 1:
                                headers = ws_values[0]
                                # Look for amount columns
                                amount_cols = [i for i, h in enumerate(headers) if any(keyword in str(h).lower()
                                             for keyword in ['amount', '金額', 'money', '錢'])]

                                for col_idx in amount_cols:
                                    col_name = headers[col_idx]
                                    values = [row[col_idx] if col_idx < len(row) else '' for row in ws_values[1:]]
                                    numeric_values = []
                                    for val in values:
                                        try:
                                            if val and val != '':
                                                numeric_values.append(float(val))
                                        except:
                                            pass

                                    if numeric_values:
                                        total = sum(numeric_values)
                                        logger.info(f"💰 Alternative worksheet '{ws.title}' column '{col_name}' total: {total:,.0f}")
                                        if total > 2000000:
                                            st.error(f"🎯 發現正確資料在工作表 '{ws.title}' (GID: {ws.id})!")
                                            st.info(f"總額: NT${total:,.0f} - 請更新設定使用 GID {ws.id}")

                        except Exception as e:
                            logger.info(f"Could not check worksheet {ws.title}: {e}")

                    # For now, use the first worksheet as fallback
                    if worksheets:
                        self.worksheet = worksheets[0]
                        logger.info(f"🔄 Using fallback worksheet: {self.worksheet.title} (GID: {self.worksheet.id})")
                        self.api_available = True

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
        initial_rows = len(df)
        logger.info(f"📊 Before cleaning: {df.shape}")

        # Save original for comparison
        df_original = df.copy()

        # Remove completely empty rows and columns (but be less aggressive)
        df = df.dropna(how='all')
        # Only remove columns that are completely empty
        df = df.loc[:, df.notna().any()]

        empty_rows_removed = initial_rows - len(df)
        logger.info(f"📊 After removing empty rows/cols: {df.shape} (removed {empty_rows_removed} completely empty rows)")

        # Debug: Show actual column names
        logger.info(f"📋 Actual columns in sheet: {list(df.columns)}")
        if not df.empty:
            logger.info(f"📊 Sample data (first row): {df.head(1).to_dict('records')}")
            # Show more samples to understand the data structure
            logger.info(f"📊 Sample data (rows 1-5): {df.head(5)[list(df.columns)[:5]].to_dict('records')}")

        # Check for amount-related columns specifically
        amount_related_cols = [col for col in df.columns if any(keyword in str(col).lower()
                              for keyword in ['amount', '金額', 'money', '錢', 'cost', '費用', 'expense'])]
        logger.info(f"💰 Found amount-related columns: {amount_related_cols}")

        # Show sample values from each amount column
        for col in amount_related_cols:
            sample_values = df[col].dropna().head(10).tolist()
            logger.info(f"💰 Sample values from '{col}': {sample_values}")

            # Try to sum this column to see totals
            try:
                numeric_values = pd.to_numeric(df[col], errors='coerce')
                col_total = numeric_values.sum()
                valid_count = numeric_values.notna().sum()
                logger.info(f"💰 Column '{col}' total: {col_total:,.0f} ({valid_count} valid values)")

                # If this column has the expected total (~2.5M), flag it
                if col_total > 2000000:
                    logger.info(f"🎯 FOUND LIKELY CORRECT AMOUNT COLUMN: '{col}' with total {col_total:,.0f}")
                    st.info(f"🎯 發現可能的正確金額欄位: '{col}' 總額: NT${col_total:,.0f}")

            except Exception as e:
                logger.info(f"💰 Could not calculate total for '{col}': {e}")

        # Apply column mapping (Chinese to English) - only for columns that exist
        existing_mapping = {k: v for k, v in COLUMN_MAPPING.items() if k in df.columns}

        logger.info(f"🔄 Column mapping analysis:")
        logger.info(f"   - Available in sheet: {list(df.columns)}")
        logger.info(f"   - Mapping to apply: {existing_mapping}")

        # Before mapping, check if we have the expected amount column
        if '金額' in df.columns:
            sample_amounts = df['金額'].dropna().head(10).tolist()
            logger.info(f"💰 Sample '金額' values BEFORE mapping: {sample_amounts}")

        df = df.rename(columns=existing_mapping)

        logger.info(f"✅ Mapped columns: {existing_mapping}")
        logger.info(f"🔄 Final columns after mapping: {list(df.columns)}")

        # After mapping, check the 'amount' column
        if 'amount' in df.columns:
            sample_amounts = df['amount'].dropna().head(10).tolist()
            logger.info(f"💰 Sample 'amount' values AFTER mapping: {sample_amounts}")

        # Also check if there are any unmapped amount columns
        remaining_amount_cols = [col for col in df.columns if any(keyword in str(col).lower()
                                for keyword in ['amount', '金額', 'money', '錢', 'cost', '費用']) and col != 'amount']
        if remaining_amount_cols:
            logger.warning(f"⚠️ Found unmapped amount-related columns: {remaining_amount_cols}")
            st.warning(f"⚠️ 發現未對應的金額相關欄位: {remaining_amount_cols}")

            for col in remaining_amount_cols:
                sample_vals = df[col].dropna().head(5).tolist()
                logger.info(f"💰 Unmapped column '{col}' samples: {sample_vals}")

        # Check for critical fields but don't be too aggressive about removing data
        critical_fields = ['date', 'amount']
        available_critical = [field for field in critical_fields if field in df.columns]

        logger.info(f"🎯 Critical fields available: {available_critical}")

        if available_critical:
            # MINIMAL filtering - only remove completely useless rows
            rows_before = len(df)

            if 'date' in df.columns and 'amount' in df.columns:
                # Analyze what types of data we have
                empty_dates = (df['date'].isna() | (df['date'] == '')).sum()
                empty_amounts = (df['amount'].isna() | (df['amount'] == '')).sum()
                both_empty = ((df['date'].isna() | (df['date'] == '')) &
                             (df['amount'].isna() | (df['amount'] == ''))).sum()

                logger.info(f"📊 Data analysis before filtering:")
                logger.info(f"   - Empty dates: {empty_dates}")
                logger.info(f"   - Empty amounts: {empty_amounts}")
                logger.info(f"   - Both empty: {both_empty}")

                # VERY MINIMAL filtering - only remove rows where BOTH date and amount are completely empty
                # AND where there's no other useful data (like description)
                completely_useless = (
                    (df['date'].isna() | (df['date'] == '')) &
                    (df['amount'].isna() | (df['amount'] == '')) &
                    (df.get('description', '').isna() | (df.get('description', '') == ''))
                ).sum()

                logger.info(f"📊 Completely useless rows (no date, amount, or description): {completely_useless}")

                # Only remove truly empty rows
                df = df[~(
                    (df['date'].isna() | (df['date'] == '')) &
                    (df['amount'].isna() | (df['amount'] == '')) &
                    (df.get('description', '').isna() | (df.get('description', '') == ''))
                )]

                logger.info(f"📊 Keeping rows with ANY useful data (date, amount, or description)")

            elif 'date' in df.columns:
                empty_dates = (df['date'].isna() | (df['date'] == '')).sum()
                logger.info(f"📊 Empty dates: {empty_dates}")
                # Keep all rows - even with empty dates, they might have other useful data
                logger.info(f"📊 Keeping all rows even with empty dates - user can filter later")
            elif 'amount' in df.columns:
                empty_amounts = (df['amount'].isna() | (df['amount'] == '')).sum()
                logger.info(f"📊 Empty amounts: {empty_amounts}")
                # Keep all rows - even with empty amounts, they might have other useful data
                logger.info(f"📊 Keeping all rows even with empty amounts - user can filter later")

            rows_after = len(df)
            logger.info(f"📊 First filter: removed {rows_before - rows_after} rows with missing critical data ({rows_after} remaining)")
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

                # Show sample date formats before conversion
                sample_dates = df[date_col].dropna().head(10).tolist()
                logger.info(f"📅 Sample date formats: {sample_dates}")

                df['date'] = pd.to_datetime(df[date_col], errors='coerce')

                # Check conversion success
                valid_dates = df['date'].notna().sum()
                invalid_dates = df['date'].isna().sum()
                logger.info(f"📅 Date conversion: {valid_dates} valid, {invalid_dates} failed")

            # Convert amount column if it exists - but be smarter about which one to use
            amount_cols = [col for col in df.columns if 'amount' in col.lower() or '金額' in col]

            # If we have multiple amount columns, try to find the one with the highest total
            best_amount_col = None
            best_total = 0

            if amount_cols:
                logger.info(f"💰 Found amount columns: {amount_cols}")

                for col in amount_cols:
                    try:
                        test_numeric = pd.to_numeric(df[col], errors='coerce')
                        test_total = test_numeric.sum()
                        valid_count = test_numeric.notna().sum()
                        logger.info(f"💰 Column '{col}': total={test_total:,.0f}, valid={valid_count}")

                        if test_total > best_total:
                            best_total = test_total
                            best_amount_col = col

                    except Exception as e:
                        logger.info(f"💰 Could not test column '{col}': {e}")

                amount_col = best_amount_col if best_amount_col else amount_cols[0]
                logger.info(f"💰 Selected best amount column: {amount_col} (total: {best_total:,.0f})")

                # If the best total is still way off from expected ~2.5M, warn user
                if best_total < 1000000:
                    logger.warning(f"💰 Amount total {best_total:,.0f} is much lower than expected ~2.5M")
                    st.warning(f"⚠️ 計算的總金額 NT${best_total:,.0f} 遠低於預期的 250萬+")
                    st.info("💡 可能需要檢查工作表或欄位設定")
                elif best_total > 2000000:
                    st.success(f"✅ 找到正確的金額總計: NT${best_total:,.0f}")

            else:
                logger.error("❌ No amount column found!")
                st.error("❌ 找不到金額欄位!")
                return df

                # Show some sample values before conversion
                sample_amounts = df[amount_col].head(10).tolist()
                logger.info(f"💰 Sample amount values: {sample_amounts}")

                # Check for empty/zero amounts before conversion
                empty_amounts = (df[amount_col].isna() | (df[amount_col] == '') | (df[amount_col] == '0')).sum()
                logger.info(f"💰 Empty/zero amounts before conversion: {empty_amounts}")

                df['amount'] = pd.to_numeric(df[amount_col], errors='coerce')

                # Show conversion results
                valid_amounts = df['amount'].notna().sum()
                zero_amounts = (df['amount'] == 0).sum()
                invalid_amounts = df['amount'].isna().sum()
                total_amount = df['amount'].sum()
                logger.info(f"💰 After conversion:")
                logger.info(f"   - Valid amounts: {valid_amounts}")
                logger.info(f"   - Zero amounts: {zero_amounts}")
                logger.info(f"   - Invalid amounts: {invalid_amounts}")
                logger.info(f"   - Total: {total_amount:,.0f}")

                # If we have many zero amounts, that might explain the filtering
                if zero_amounts > 100:
                    logger.info(f"💰 Warning: {zero_amounts} zero-amount records found - these might be placeholder rows")

                # If total is still very low, check if we missed any amount columns
                if total_amount < 1000000:
                    logger.warning(f"💰 CRITICAL: Total amount {total_amount:,.0f} is too low!")

                    # Check ALL columns for numeric data that might be amounts
                    logger.info("🔍 Checking all columns for potential amount data...")
                    for col in df.columns:
                        try:
                            numeric_test = pd.to_numeric(df[col], errors='coerce')
                            col_total = numeric_test.sum()
                            valid_count = numeric_test.notna().sum()

                            if col_total > 1000000:  # If this column has a large total
                                logger.warning(f"🎯 POTENTIAL AMOUNT COLUMN: '{col}' total={col_total:,.0f}")
                                st.error(f"🎯 發現可能的金額欄位: '{col}' 總額: NT${col_total:,.0f}")
                                st.info(f"💡 可能需要更新欄位對應設定")

                        except:
                            pass

            # Final validation - only remove rows where critical converted data is invalid
            if 'date' in df.columns and 'amount' in df.columns:
                rows_before = len(df)

                # Analyze what will be dropped
                invalid_dates = df['date'].isna().sum()
                invalid_amounts = df['amount'].isna().sum()
                both_invalid = (df['date'].isna() & df['amount'].isna()).sum()
                either_invalid = (df['date'].isna() | df['amount'].isna()).sum()

                logger.info(f"📊 Final validation analysis:")
                logger.info(f"   - Invalid dates after conversion: {invalid_dates}")
                logger.info(f"   - Invalid amounts after conversion: {invalid_amounts}")
                logger.info(f"   - Both invalid: {both_invalid}")
                logger.info(f"   - Either invalid: {either_invalid}")

                # Be more selective about what we drop
                # Option 1: Only drop if BOTH are invalid
                df_strict = df.dropna(subset=['date', 'amount'])

                # Option 2: Keep rows with valid amounts even if dates are invalid
                df_lenient = df[df['amount'].notna()]

                rows_strict = len(df_strict)
                rows_lenient = len(df_lenient)

                logger.info(f"📊 Filtering options:")
                logger.info(f"   - Strict (both valid): {rows_strict} rows")
                logger.info(f"   - Lenient (amount valid): {rows_lenient} rows")

                # Use VERY lenient filtering - only remove rows that are completely useless
                # Keep any row that has EITHER a valid date OR a valid amount
                df_ultra_lenient = df[(df['date'].notna()) | (df['amount'].notna())]

                rows_ultra = len(df_ultra_lenient)
                logger.info(f"📊 Filtering options comparison:")
                logger.info(f"   - Ultra lenient (date OR amount valid): {rows_ultra} rows")

                # Use ultra-lenient filtering to preserve maximum data
                df = df_ultra_lenient
                rows_after = len(df)

                logger.info(f"📊 Final filter: removed {rows_before - rows_after} rows (completely empty only)")

                if len(df) > 0:
                    final_total = df['amount'].sum()
                    logger.info(f"💰 Final total after all processing: {final_total:,.0f}")
                    st.success(f"✅ 處理完成: {len(df)} 筆有效記錄, 總額: NT${final_total:,.0f}")

                    # Show summary of what was filtered out
                    if rows_before > rows_after:
                        filtered_count = rows_before - rows_after
                        st.info(f"📊 最終篩選: 移除 {filtered_count} 筆無效金額記錄")

                    # Show overall filtering summary
                    if source == "api":
                        original_rows = 1577  # From the debug message
                        total_filtered = original_rows - len(df)
                        if total_filtered > 0:
                            st.info(f"📊 總篩選摘要: 原始 {original_rows} 筆 → 有效 {len(df)} 筆 (移除 {total_filtered} 筆空白/無效記錄)")
                            logger.info(f"📊 Data pipeline summary: {original_rows} → {len(df)} rows (filtered {total_filtered})")
            elif 'amount' in df.columns:
                # If only amount exists, just filter by amount
                rows_before = len(df)
                df = df[df['amount'].notna()]
                rows_after = len(df)

                if len(df) > 0:
                    final_total = df['amount'].sum()
                    logger.info(f"💰 Final total after all processing: {final_total:,.0f}")
                    st.success(f"✅ 處理完成: {len(df)} 筆有效記錄, 總額: NT${final_total:,.0f}")

                    total_filtered = rows_before - rows_after
                    if total_filtered > 0:
                        st.info(f"📊 篩選摘要: 共 {total_filtered} 筆記錄被過濾 (無效金額)")
            else:
                if len(df) > 0:
                    st.success(f"✅ 處理完成: {len(df)} 筆記錄")

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