"""
Google Sheets API Integration
Handles read/write operations for expense data
"""

import streamlit as st
import gspread
from google.oauth2.service_account import Credentials
import pandas as pd
import json
from datetime import datetime
import time

# Define the scope
SCOPES = [
    'https://www.googleapis.com/auth/spreadsheets',
    'https://www.googleapis.com/auth/drive'
]

# Your Google Sheet details
SHEET_ID = "16JzKmS8Jq9H6NmjrpKkqBqNfnXkC_gfPiMV6Y6qP_kQ"
WORKSHEET_GID = 811746503  # Updated to correct tab gid

class SheetsAPI:
    def __init__(self):
        self.gc = None
        self.sheet = None
        self.worksheet = None

    def authenticate(self):
        """Authenticate with Google Sheets API with better error handling"""
        try:
            credentials = None

            # Try Streamlit secrets first (for deployment)
            if "google_sheets" in st.secrets:
                try:
                    credentials_dict = dict(st.secrets["google_sheets"])

                    # Validate required fields
                    required_fields = ['type', 'project_id', 'private_key', 'client_email', 'token_uri']
                    missing_fields = [field for field in required_fields if field not in credentials_dict]

                    if missing_fields:
                        st.error(f"Missing required fields in secrets: {missing_fields}")
                        return False

                    credentials = Credentials.from_service_account_info(
                        credentials_dict, scopes=SCOPES
                    )

                except Exception as e:
                    st.error(f"Secrets format error: {str(e)}")
                    # Try local file as fallback

            # Fallback to local file (for development or if secrets fail)
            if credentials is None:
                try:
                    import os
                    if os.path.exists('service-account-key.json'):
                        credentials = Credentials.from_service_account_file(
                            'service-account-key.json', scopes=SCOPES
                        )
                    else:
                        st.error("No authentication method available. Please check secrets or service account file.")
                        return False
                except Exception as e:
                    st.error(f"Local file authentication failed: {str(e)}")
                    return False

            # Try to authenticate with Google
            self.gc = gspread.authorize(credentials)
            self.sheet = self.gc.open_by_key(SHEET_ID)
            # Get the specific worksheet by GID
            try:
                self.worksheet = self.sheet.get_worksheet_by_id(WORKSHEET_GID)
            except Exception:
                # Fallback to first worksheet if GID fails
                st.warning(f"Could not find worksheet with GID {WORKSHEET_GID}, using first worksheet")
                self.worksheet = self.sheet.get_worksheet(0)

            # Test the connection with a simple call
            try:
                self.worksheet.get_all_records(head=1)  # Just get headers to test
                return True
            except Exception as e:
                st.error(f"Sheet access failed. Check sharing permissions: {str(e)}")
                return False

        except Exception as e:
            st.error(f"Authentication error: {str(e)}")
            return False

    def read_data(self):
        """Read all expense data from the sheet"""
        try:
            if not self.worksheet:
                if not self.authenticate():
                    return pd.DataFrame()

            # Get raw data to handle duplicate headers
            all_values = self.worksheet.get_all_values()
            if not all_values:
                return pd.DataFrame()

            # Get headers and clean them
            headers = all_values[0]

            # Clean headers - remove empty and fix duplicates
            cleaned_headers = []
            for i, header in enumerate(headers):
                if header.strip():  # If not empty
                    cleaned_headers.append(header.strip())
                else:  # If empty, create a placeholder
                    cleaned_headers.append(f'empty_col_{i}')

            # Get data rows
            data_rows = all_values[1:]

            # Create DataFrame
            df = pd.DataFrame(data_rows, columns=cleaned_headers)

            # Remove completely empty rows
            df = df.dropna(how='all')

            # Remove empty columns
            df = df.loc[:, (df != '').any(axis=0)]

            # Handle duplicate column names (like duplicate '地點')
            # If there are duplicates, pandas will name them: '地點', '地點.1', etc.
            df.columns = df.columns.astype(str)  # Ensure string columns

            if df.empty:
                return df

            # Clean and process data - updated for actual sheet structure
            column_mapping = {
                'Timestamp': 'timestamp',
                '日期': 'date',
                '類型_1': 'category_emoji',
                '類型_2': 'category_type',
                '金額': 'amount',
                '帳戶': 'account',
                '名稱': 'description',
                '國家': 'country',
                '合併地點': 'location',  # Use your combined location column!
                '備註': 'notes'
            }

            # Rename columns if they exist
            df = df.rename(columns=column_mapping)

            # Drop duplicate location columns (keep only the mapped '合併地點' -> 'location')
            duplicate_location_cols = [col for col in df.columns if col.startswith('地點') and col != 'location']
            if duplicate_location_cols:
                df = df.drop(columns=duplicate_location_cols)

            # Convert date column
            if 'date' in df.columns:
                df['date'] = pd.to_datetime(df['date'], errors='coerce')

            # Convert amount to numeric
            if 'amount' in df.columns:
                df['amount'] = pd.to_numeric(df['amount'], errors='coerce')

            # Remove rows with invalid dates or amounts
            df = df.dropna(subset=['date', 'amount'])

            # Add derived columns
            if not df.empty:
                df['year'] = df['date'].dt.year
                df['month'] = df['date'].dt.month
                df['day_of_week'] = df['date'].dt.day_name()
                df['month_year'] = df['date'].dt.to_period('M').astype(str)

            return df

        except Exception as e:
            error_msg = str(e)
            if "duplicate" in error_msg.lower() and "header" in error_msg.lower():
                st.error("🔧 Sheet header issue detected - trying to fix automatically...")
                # This should now be handled by our improved logic above
                return pd.DataFrame()
            else:
                st.error(f"Error reading data: {error_msg}")
            return pd.DataFrame()

    def add_expense(self, expense_data):
        """Add a new expense record"""
        try:
            if not self.worksheet:
                if not self.authenticate():
                    return False

            # Convert expense_data to the format expected by the sheet
            row_data = [
                expense_data.get('date', ''),
                expense_data.get('category_emoji', ''),
                expense_data.get('category_type', ''),
                expense_data.get('amount', ''),
                expense_data.get('account', ''),
                expense_data.get('description', ''),
                expense_data.get('country', ''),
                expense_data.get('location', ''),
                expense_data.get('notes', '')
            ]

            # Append to the sheet
            self.worksheet.append_row(row_data)

            # Clear cache to refresh data
            st.cache_data.clear()

            return True

        except Exception as e:
            st.error(f"Error adding expense: {str(e)}")
            return False

    def update_expense(self, row_index, expense_data):
        """Update an existing expense record"""
        try:
            if not self.worksheet:
                if not self.authenticate():
                    return False

            # Convert expense_data to row format
            row_data = [
                expense_data.get('date', ''),
                expense_data.get('category_emoji', ''),
                expense_data.get('category_type', ''),
                expense_data.get('amount', ''),
                expense_data.get('account', ''),
                expense_data.get('description', ''),
                expense_data.get('country', ''),
                expense_data.get('location', ''),
                expense_data.get('notes', '')
            ]

            # Update the specific row (row_index + 2 because of header and 0-indexing)
            row_number = row_index + 2
            self.worksheet.update(f'A{row_number}:I{row_number}', [row_data])

            # Clear cache to refresh data
            st.cache_data.clear()

            return True

        except Exception as e:
            st.error(f"Error updating expense: {str(e)}")
            return False

    def delete_expense(self, row_index):
        """Delete an expense record"""
        try:
            if not self.worksheet:
                if not self.authenticate():
                    return False

            # Delete the specific row (row_index + 2 because of header and 0-indexing)
            row_number = row_index + 2
            self.worksheet.delete_rows(row_number)

            # Clear cache to refresh data
            st.cache_data.clear()

            return True

        except Exception as e:
            st.error(f"Error deleting expense: {str(e)}")
            return False

# Create a cached instance
@st.cache_resource
def get_sheets_api():
    """Get a cached instance of SheetsAPI"""
    return SheetsAPI()