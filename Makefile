# Family Expense Dashboard - Development Commands

.PHONY: help install setup run clean test deploy

help:  ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-15s\033[0m %s\n", $$1, $$2}'

install:  ## Install dependencies
	pip install -r requirements.txt

setup:  ## Run initial setup
	python setup.py

run:  ## Run the app locally
	streamlit run app.py

clean:  ## Clean cache and temporary files
	find . -type f -name "*.pyc" -delete
	find . -type d -name "__pycache__" -delete
	rm -rf .streamlit/
	mkdir .streamlit

test-api:  ## Test Google Sheets API connection
	python -c "from sheets_api import get_sheets_api; api = get_sheets_api(); print('✅ API Status:', api.get_status())"

deploy:  ## Deploy to Streamlit Cloud (manual step)
	@echo "🚀 To deploy to Streamlit Cloud:"
	@echo "1. Push your code to GitHub"
	@echo "2. Go to https://share.streamlit.io/"
	@echo "3. Connect your repository"
	@echo "4. Add your secrets in the dashboard"
	@echo "5. Deploy!"

check:  ## Check project structure
	@echo "📁 Project Structure:"
	@ls -la *.py *.md *.txt 2>/dev/null || true
	@echo ""
	@echo "🔧 Configuration Files:"
	@ls -la .streamlit/ 2>/dev/null || echo "No .streamlit directory"
	@echo ""
	@echo "📦 Dependencies:"
	@python -c "import pkg_resources; print('✅ All packages installed')" 2>/dev/null || echo "❌ Missing dependencies - run 'make install'"

dev-mode:  ## Run in development mode with auto-reload
	streamlit run app.py --server.runOnSave=true

backup:  ## Create a backup of the project
	@echo "💾 Creating backup..."
	@tar -czf backup_$(shell date +%Y%m%d_%H%M%S).tar.gz --exclude='.git' --exclude='__pycache__' --exclude='.streamlit/secrets.toml' .
	@echo "✅ Backup created"

update-deps:  ## Update all dependencies
	pip install --upgrade -r requirements.txt
	pip freeze > requirements.txt

# Default target
.DEFAULT_GOAL := help