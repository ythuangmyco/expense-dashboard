# 🚀 Deployment Instructions

## Option 1: Streamlit Cloud (Recommended - FREE)

### Prerequisites
- GitHub account
- This repository pushed to GitHub

### Steps

1. **Push to GitHub**
   ```bash
   # Create a new repository on GitHub (e.g., "expense-dashboard")
   git remote add origin https://github.com/YOUR_USERNAME/expense-dashboard.git
   git branch -M main
   git push -u origin main
   ```

2. **Deploy on Streamlit Cloud**
   - Go to [share.streamlit.io](https://share.streamlit.io)
   - Sign in with GitHub
   - Click "New app"
   - Select your repository: `YOUR_USERNAME/expense-dashboard`
   - Set main file path: `app.py`
   - Click "Deploy!"

3. **Access Your Dashboard**
   - Your app will be available at: `https://your-app-name.streamlit.app/`
   - Share this URL with your wife for mobile/laptop access

## Option 2: Local Development

```bash
# Clone and setup
git clone https://github.com/YOUR_USERNAME/expense-dashboard.git
cd expense-dashboard

# Create virtual environment
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Run locally
streamlit run app.py
```

## Option 3: Other Hosting Platforms

### Heroku (Free tier discontinued, but still available)
1. Create `Procfile`:
   ```
   web: streamlit run app.py --server.port $PORT --server.headless true
   ```

### Railway/Render
1. Connect your GitHub repository
2. Set build command: `pip install -r requirements.txt`
3. Set start command: `streamlit run app.py --server.port $PORT --server.headless true`

## 📱 Mobile Access

Once deployed, the dashboard works perfectly on mobile devices:
- Responsive design adapts to phone screens
- Touch-friendly filter controls
- Optimized charts for mobile viewing
- Fast loading with data caching

## 🔧 Customization

### Change Google Sheets Source
Edit `SHEET_URL` in `app.py`:
```python
SHEET_URL = "https://docs.google.com/spreadsheets/d/YOUR_SHEET_ID/export?format=csv&gid=YOUR_GID"
```

### Update Styling
Modify the CSS in the `st.markdown()` section of `app.py`.

### Add New Visualizations
Add new chart functions in the `show_visualizations()` function.

## 🆘 Troubleshooting

### Data Not Loading
- Check Google Sheets is public (anyone with link can view)
- Verify the CSV export URL works in browser
- Check for changes in column names

### App Crashes
- Check logs in Streamlit Cloud dashboard
- Verify all dependencies in requirements.txt
- Test locally first with `streamlit run app.py`

## 💡 Pro Tips

1. **Automatic Updates**: The dashboard automatically refreshes data from Google Sheets
2. **Mobile Bookmarks**: Add the app URL to phone home screen for easy access
3. **Data Caching**: Data is cached for 5 minutes to improve performance
4. **Sharing**: The public URL works for anyone - no login required