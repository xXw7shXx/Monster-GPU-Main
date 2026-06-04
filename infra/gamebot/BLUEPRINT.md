# 🚀 Telegram Bot Enterprise Blueprint

This document serves as the master reference for the architecture and implementation of the "GameBot" ecosystem. Use this as a guide to replicate this professional setup for future bots.

## 🏗️ System Architecture
The ecosystem is built on a **Decoupled API-Driven Architecture** consisting of 5 main components:
1.  **Telegram Bot (Python):** The core service using `python-telegram-bot`.
2.  **TikTok Bot (Integrated):** Webhook-based service integrated into the Internal API.
3.  **Internal API (FastAPI):** Central hub for stats, broadcasts, and TikTok interactions.
4.  **Database (SQLite/PostgreSQL):** Scalable storage with Alembic for migrations.
5.  **Super Admin Dashboard (React + FastAPI):** Centralized hub to manage both Telegram and TikTok bots.

## 📂 Folder Structure Reference
```text
/
├── bot.py                  # Entry point (Telegram Bot + Internal API)
├── ...
├── services/               
│   ├── api.py              # Internal API & TikTok Webhook Handler
│   ├── tiktok_api.py       # TikTok Messaging Service
│   └── ...
```

## 🛠️ Enterprise Features (The "Standard")
*   **Multi-Platform Support:** Seamlessly handles both Telegram and TikTok users.
*   **Cross-Platform Broadcast:** Sends announcements to all users across platforms in one click.
*   **Platform-Agnostic Database:** Unified user profiles supporting multiple social IDs.

## 🛠️ Enterprise Features (The "Standard")
When creating a new bot, ensure these features are ported:
*   **Rate Limiting:** Use the `@rate_limit` decorator in `utils/middleware.py` to prevent spam.
*   **Sentry:** error tracking configured in `bot.py` via `SENTRY_DSN`.
*   **Rotating Logs:** 10MB x 5 logs managed via `RotatingFileHandler`.
*   **Branded Start:** Always send a logo with the first `/start` message.
*   **Admin-Only Analytics:** Restrict sensitive commands to the `ADMIN_IDS` list.
*   **Localization:** Centralized `utils/localization.py` for multi-language support.

## ⚙️ Environment Variables (.env)
```env
TELEGRAM_BOT_TOKEN=...
RAWG_API_KEY=...       # Feature specific
ADMIN_IDS=123,456      # Numeric IDs only
SENTRY_DSN=...         # For error tracking
DB_USER=gamebot
DB_PASSWORD=password
DB_NAME=gamebot_db
INTERNAL_API_KEY=...   # Shared secret between Bot and Super Admin
```

## 🔄 Replicating for a New Bot
1.  **Clone:** Copy the entire folder structure.
2.  **Update Models:** Change `database/models.py` for your new bot's needs.
3.  **Update Handlers:** Replace `handlers/commands.py` with new bot logic.
4.  **Configure:** Update `.env` with a new Telegram Token and unique DB name.
5.  **Dashboard:** Add the new bot's URL and API Key to `super_admin/backend/main.py`.

## 🚢 Deployment (Docker)
Always deploy using `docker-compose up -d --build`. This ensures PostgreSQL and the Dashboard are correctly linked via the internal Docker network.

---
*Created on May 1, 2026, as the "Gold Standard" for Bot Development.*
