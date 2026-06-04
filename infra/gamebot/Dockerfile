FROM python:3.12-slim

# Install system dependencies if needed (e.g., for sqlite or build tools)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy requirements first to leverage Docker cache
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright browsers and dependencies for mobile scraping
RUN playwright install chromium --with-deps

# Copy the rest of the application
COPY . .

# Ensure the logs directory exists
RUN mkdir -p logs

# Run the bot
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=5).read()" || exit 1
CMD ["python", "bot.py"]
