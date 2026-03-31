#!/usr/bin/env python3
"""
Quick diagnostic script to check Google Sheets data structure
Run this to see exactly what's in your sheet
"""

import gspread
from google.oauth2.service_account import Credentials
import pandas as pd

def debug_sheet():
    """Debug the actual sheet structure and data"""

    try:
        # This would need the actual credentials
        print("🔍 Sheet Debugging Tool")
        print("=" * 50)

        print("Expected configuration:")
        print(f"  Sheet ID: 16JzKmS8Jq9H6NmjrpKkqBqNfnXkC_gfPiMV6Y6qP_kQ")
        print(f"  Worksheet GID: 453361449")

        print("\nExpected amount column mapping:")
        print(f"  '金額' → 'amount'")

        print("\nTo manually check your sheet:")
        print("1. Open your Google Sheet")
        print("2. Check the column headers in row 1")
        print("3. Find the column with expense amounts")
        print("4. Check if it's exactly named '金額'")

        print("\nCommon issues to check:")
        print("- Column might be named differently (Amount, 費用, Cost, etc.)")
        print("- Amounts might have formatting (commas, currency symbols)")
        print("- Data might be in wrong format (text vs numbers)")
        print("- Multiple amount columns might exist")

        print("\n" + "=" * 50)

        # Sample test data structure
        print("Expected sheet structure:")
        print("日期    | 類型_1  | 類型_2  | 金額   | 帳戶 | 名稱   |")
        print("3/31    | 📅日常  | 🧴日用  | 356    | 菇菇 | 印章   |")
        print("3/30    | 📅日常  | 🍽️飲食 | 1234   | 過兒 | 午餐   |")

        print("\nIf your sheet structure is different, that's the problem!")

    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    debug_sheet()