#!/usr/bin/env python3
"""
Test script to verify Google Sheets data connection
"""

import pandas as pd
import requests

# Test URL
SHEET_URL = "https://docs.google.com/spreadsheets/d/16JzKmS8Jq9H6NmjrpKkqBqNfnXkC_gfPiMV6Y6qP_kQ/export?format=csv&gid=720407773"

def test_data_connection():
    """Test the Google Sheets data connection"""
    try:
        print("📡 Testing connection to Google Sheets...")

        # Load data from Google Sheets CSV export
        df = pd.read_csv(SHEET_URL)

        print(f"✅ Successfully loaded {len(df)} records")
        print(f"📅 Date range: {df.iloc[:, 0].min()} to {df.iloc[:, 0].max()}")
        print(f"📊 Columns: {list(df.columns)}")

        # Show first few rows
        print("\n📋 Sample data:")
        print(df.head().to_string())

        # Basic stats
        print(f"\n💰 Basic stats:")
        amount_col = df.columns[3]  # Should be 金額 (amount)
        print(f"   - Total records: {len(df):,}")
        print(f"   - Amount column: '{amount_col}'")
        if pd.api.types.is_numeric_dtype(df[amount_col]):
            print(f"   - Total amount: NT$ {df[amount_col].sum():,.0f}")
            print(f"   - Average transaction: NT$ {df[amount_col].mean():,.0f}")
        else:
            print(f"   - Amount column needs conversion")

        return True

    except Exception as e:
        print(f"❌ Error: {str(e)}")
        return False

if __name__ == "__main__":
    test_data_connection()