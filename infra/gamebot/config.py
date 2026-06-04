import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# Base directory
BASE_DIR = Path(__file__).resolve().parent

# Bot Configuration
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
def _parse_admin_ids():
    raw_ids = os.getenv("ADMIN_IDS", "").split(",")
    parsed_ids = []
    for rid in raw_ids:
        rid = rid.strip()
        if not rid:
            continue
        try:
            parsed_ids.append(int(rid))
        except ValueError:
            # Skip non-numeric IDs like @usernames as Telegram Bot API requires numeric IDs
            continue
    return parsed_ids

ADMIN_IDS = _parse_admin_ids()

# Assets
LOGO_PATH = BASE_DIR / "logo.png"

# Templates
TEMPLATES_DIR = BASE_DIR / "templates"
TEMPLATES_DIR.mkdir(exist_ok=True)

# API Keys
RAWG_API_KEY = os.getenv("RAWG_API_KEY")
INTERNAL_API_KEY = os.getenv("INTERNAL_API_KEY")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_PROJECT_NAME = os.getenv("GEMINI_PROJECT_NAME")
GEMINI_MODEL_ID = os.getenv("GEMINI_MODEL_ID", "gemini-2.0-flash-exp")

# Logging
LOG_DIR = BASE_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)
LOG_FILE = LOG_DIR / "bot.log"
