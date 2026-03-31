#!/usr/bin/env python3
"""
Verify that all fixes are applied correctly
Run this before starting Streamlit to check everything is working
"""

def check_edit_form_fix():
    """Check if the edit form number input fix is applied"""
    with open('input_forms.py', 'r', encoding='utf-8') as f:
        content = f.read()

    # Check for the fix
    if 'value=current_amount,  # Use consistent float type' in content:
        print("✅ Edit form float type fix - APPLIED")
        return True
    else:
        print("❌ Edit form float type fix - MISSING")
        return False

def check_time_period_functions():
    """Check if time period functions exist"""
    with open('app.py', 'r', encoding='utf-8') as f:
        content = f.read()

    functions_to_check = [
        'def get_period_dates',
        'def time_period_selector',
        'def additional_filters',
        'def apply_additional_filters'
    ]

    all_present = True
    for func in functions_to_check:
        if func in content:
            print(f"✅ {func} - FOUND")
        else:
            print(f"❌ {func} - MISSING")
            all_present = False

    return all_present

def check_main_dashboard():
    """Check if main dashboard uses new time period selector"""
    with open('app.py', 'r', encoding='utf-8') as f:
        content = f.read()

    if 'start_date, end_date, selected_period = time_period_selector(df)' in content:
        print("✅ Main dashboard time period integration - APPLIED")
        return True
    else:
        print("❌ Main dashboard time period integration - MISSING")
        return False

def main():
    print("🔍 Verifying Expense Dashboard Fixes")
    print("=" * 40)

    edit_fix = check_edit_form_fix()
    time_functions = check_time_period_functions()
    dashboard_integration = check_main_dashboard()

    print("\n📊 Summary:")
    if edit_fix and time_functions and dashboard_integration:
        print("🎉 ALL FIXES APPLIED CORRECTLY!")
        print("\n📝 Next Steps:")
        print("1. Restart Streamlit: streamlit run app.py")
        print("2. Hard refresh browser (Ctrl+Shift+R)")
        print("3. You should now see:")
        print("   - Time period selection dropdown")
        print("   - Quick period buttons")
        print("   - Fixed edit form without errors")
    else:
        print("⚠️  Some fixes are missing - check the output above")

if __name__ == "__main__":
    main()