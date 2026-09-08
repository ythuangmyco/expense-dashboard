"""
Constants shared by runner.py (the stubbed app) and drive_fx.py (the driver):
the rates the fake FX endpoints answer with and the seed row that is already
converted. Importing this module has no side effects (runner.py runs the app).
"""
import time

from config import FX_FALLBACK_RATES

# TWD per 1 unit, answered by every fake FX source. SGD matches
# tests/fixtures/frankfurter.json so AppTest and browser checks agree.
HARNESS_RATES = dict(FX_FALLBACK_RATES)
HARNESS_RATES["SGD"] = 24.908
HARNESS_DATE = time.strftime("%Y-%m-%d")

# One already-converted row (SGD 12.50 @ 24.908 = NT$311) so the edit scenarios
# have something to open. Only seeded when FX_HEADERS=1.
CONVERTED_ROW = ["09/06/2026", "✈️ 旅行", "🍽️ 飲食", "311", "菇菇", "新加坡咖啡",
                 "新加坡", "新加坡", "harness", "SGD", "12.50", "24.908"]
