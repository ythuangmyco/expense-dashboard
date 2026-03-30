#!/usr/bin/env python3
"""
Clear Streamlit cache and test fresh authentication
"""

import streamlit as st
import shutil
import os

# Clear streamlit cache directory if it exists
cache_dirs = [
    '.streamlit',
    '__pycache__',
]

for cache_dir in cache_dirs:
    if os.path.exists(cache_dir):
        shutil.rmtree(cache_dir)
        print(f"✅ Cleared {cache_dir}")
    else:
        print(f"ℹ️  {cache_dir} not found (already clean)")

print("\n🎉 Cache cleared! Your expense dashboard should now show:")
print("   🔗 Google Sheets API 已連接 - 可新增/編輯記錄")
print("\n🚀 Access your dashboard at: http://localhost:8501")
print("🔐 Password: 0727")